# -*- coding: utf-8 -*-
"""
미국 공시(SEC EDGAR) 수집기 — 키 불필요, GitHub Actions에서 그대로 동작.

SEC는 자동 접근 도구에 '이름 + 연락 이메일' 형식의 User-Agent를 요구한다.
형식이 틀리면 Akamai가 403 "Undeclared Automated Tool"로 끊는다.
연락처는 공개 저장소에 적지 않고 SEC_UA 시크릿으로 받는다.

제출 목록만 받는 게 아니라 XBRL(companyfacts)에서 재무 시계열을 뽑아
QoQ·YoY·5개년·부채비율·매출채권·지배주주 몫까지 계산하고,
KIS 해외시세로 주가를 붙여 PER·PBR·PSR·EV/EBIT을 낸 뒤
같은 밸류체인 세부단계에 속한 기업끼리 중앙값과 비교한다.

출력
  public/data/sec/<티커>.json   종목별 제출 이력 + 재무 + 밸류
  public/data/sec/index.json    목록·갱신시각·분류체계 연결
  public/data/sec/fts.json      키워드 전문검색 결과
"""
import os, json, time, re, gzip, urllib.request, urllib.error, urllib.parse, pathlib, datetime

UA   = os.environ.get('SEC_UA', '').strip()
OUT  = pathlib.Path('public/data/sec')
TAX  = pathlib.Path('public/data/sec_tax.json')
MAX  = int(os.environ.get('MAXRUN', '120'))        # 분 단위 예산
GAP  = 0.15                                        # SEC 권장 초당 10회 이하
KEEP = 80                                          # 종목당 보관 제출 건수
VER  = 1

# 투자 판단에 쓰는 보고서만 남긴다(내부자 Form 4 등 잡음 제외)
FORMS = {'10-K','10-Q','8-K','20-F','6-K','40-F','S-1','S-3','424B5','424B2',
         'DEF 14A','SC 13D','SC 13G','11-K','10-K/A','10-Q/A','8-K/A'}

class Blocked(Exception): pass

# ───────────────────────── XBRL 재무 ─────────────────────────
# 회사마다 쓰는 태그가 달라 우선순위로 훑고, 중간에 태그를 바꾸는 경우가 흔해
# 첫 태그에서 끊지 않고 빠진 기간만 다음 태그로 채운다(NVDA는 2020년에 Revenues로 전환).
TAGS = {
 'rev':  ['RevenueFromContractWithCustomerExcludingAssessedTax','Revenues',
          'RevenueFromContractWithCustomerIncludingAssessedTax','SalesRevenueNet','SalesRevenueGoodsNet'],
 'op':   ['OperatingIncomeLoss'],
 'ni':   ['NetIncomeLoss'],
 'ni_all':['ProfitLoss'],
 'nci':  ['NetIncomeLossAttributableToNoncontrollingInterest'],
 'da':   ['DepreciationDepletionAndAmortization','DepreciationAmortizationAndAccretionNet','DepreciationAndAmortization'],
 'ast':  ['Assets'], 'liab': ['Liabilities'],
 'eq':   ['StockholdersEquity'],
 'eq_all':['StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest'],
 'ar':   ['AccountsReceivableNetCurrent','ReceivablesNetCurrent'],
 'inv':  ['InventoryNet'], 'cash': ['CashAndCashEquivalentsAtCarryingValue'],
 'debt_l':['LongTermDebtNoncurrent','LongTermDebt'],
 'debt_s':['LongTermDebtCurrent','ShortTermBorrowings','OtherShortTermBorrowings'],
 'eps':  ['EarningsPerShareDiluted','EarningsPerShareBasic'],
}
DUR = {'rev','op','ni','ni_all','nci','da','eps'}

# 외국 민간발행인(TSMC·ASML·UMC·STM 등)은 20-F/6-K를 IFRS 로 낸다 — 태그 이름이 다르다.
# 보고 통화도 USD 가 아닐 수 있어(TWD·EUR) 그대로 두고, 환산이 필요한 지표만 뒤에서 막는다.
ITAGS = {
 'rev':  ['Revenue','RevenueFromContractsWithCustomers','RevenueFromSaleOfGoods'],
 'op':   ['ProfitLossFromOperatingActivities','OperatingIncomeLoss'],
 'ni':   ['ProfitLossAttributableToOwnersOfParent','ProfitLoss'],
 'ni_all':['ProfitLoss'],
 'nci':  ['ProfitLossAttributableToNoncontrollingInterests'],
 'da':   ['DepreciationAndAmortisationExpense','DepreciationAmortisationAndImpairmentLossReversalOfImpairmentLossRecognisedInProfitOrLoss'],
 'ast':  ['Assets'], 'liab': ['Liabilities'],
 'eq':   ['EquityAttributableToOwnersOfParent','Equity'],
 'eq_all':['Equity'],
 'ar':   ['TradeAndOtherCurrentReceivables','CurrentTradeReceivables'],
 'inv':  ['Inventories'],
 'cash': ['CashAndCashEquivalents'],
 'debt_l':['NoncurrentPortionOfNoncurrentBorrowings','LongtermBorrowings','NoncurrentBorrowings'],
 'debt_s':['ShorttermBorrowings','CurrentPortionOfLongtermBorrowings','CurrentBorrowings'],
 'eps':  ['DilutedEarningsLossPerShare','BasicEarningsLossPerShare'],
}

def _cur(facts):
    """이 회사가 어떤 통화로 보고하는지 — 매출 태그에 가장 많이 쓰인 통화를 고른다."""
    best, bn = 'USD', -1
    for ns in ('us-gaap','ifrs-full'):
        for tag in TAGS['rev'] + ITAGS['rev']:
            node = (facts.get(ns) or {}).get(tag)
            if not node: continue
            for unit, rows in (node.get('units') or {}).items():
                if '/' in unit: continue
                if len(rows) > bn: best, bn = unit, len(rows)
    return best

def _d(x): return datetime.date.fromisoformat(x)

def _series(facts, keys, duration, ns='us-gaap', cur='USD'):
    q, a = {}, {}
    ok = (cur, cur+'/shares')
    for tag in keys:
        node = (facts.get(ns) or {}).get(tag)
        if not node: continue
        for unit, rows in (node.get('units') or {}).items():
            if unit not in ok: continue
            for r in rows:
                end, val = r.get('end'), r.get('val')
                if end is None or val is None: continue
                if duration:
                    st = r.get('start')
                    if not st: continue
                    n = (_d(end)-_d(st)).days
                    if 60 <= n <= 115:    tgt = q
                    elif 330 <= n <= 400: tgt = a
                    else: continue                      # 누계(6·9개월)는 버린다
                else: tgt = q
                prev = tgt.get(end)
                if prev is None or (prev[2] == tag and r.get('filed','') >= prev[1]):
                    tgt[end] = (val, r.get('filed',''), tag)
    f = lambda m: {k: v[0] for k, v in sorted(m.items())}
    return f(q), f(a)

def _fill_q4(q, a):
    """10-K에 4분기를 따로 싣지 않는 회사가 많다 → '연간 − 1~3분기 합'으로 채우고 표시한다."""
    out, made = dict(q), []
    for ay, av in a.items():
        ins = [k for k in q if 0 < (_d(ay)-_d(k)).days < 300]
        if len(ins) == 3 and ay not in q:
            out[ay] = av - sum(q[k] for k in ins); made.append(ay)
    return out, made

def _pct(x, y):
    if x is None or y is None or y <= 0: return None   # 적자 기준 증감률은 뜻이 없다
    return round((x-y)/y*100, 1)

def financials(cik, px=None, shr=None):
    j = get(f'https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json')
    if not j: return None
    j = json.loads(j); F0 = j.get('facts') or {}
    if not shr:
        n = (F0.get('dei') or {}).get('EntityCommonStockSharesOutstanding')
        if n:
            rs = [r for u, v in n['units'].items() for r in v]
            rs.sort(key=lambda r: (r.get('end') or '', r.get('filed') or ''))
            if rs: shr = rs[-1]['val']
    CUR = _cur(F0)
    F, A = {}, {}
    for k, keys in TAGS.items():
        qq, aa = _series(F0, keys, k in DUR, 'us-gaap', CUR)
        # us-gaap 로 안 잡히면 IFRS 태그로 다시 — 20-F/6-K 를 내는 외국 기업
        if not qq and not aa and ITAGS.get(k):
            qq, aa = _series(F0, ITAGS[k], k in DUR, 'ifrs-full', CUR)
        if k in DUR:
            qq, made = _fill_q4(qq, aa); F[k] = qq; A[k] = aa
            if k == 'rev': MADE = made
        else: F[k] = qq; A[k] = aa
    qs = sorted(F['rev'])[-13:]
    rows = []
    for i, k in enumerate(qs):
        r = {'d': k, 'est': k in MADE}
        for f in ('rev','op','ni','eps'): r[f] = F[f].get(k)
        prev = qs[i-1] if i else None
        yago = next((z for z in qs if 330 <= (_d(k)-_d(z)).days <= 400), None)
        for f in ('rev','op','ni'):
            r[f+'_q'] = _pct(r[f], F[f].get(prev)) if prev else None
            r[f+'_y'] = _pct(r[f], F[f].get(yago)) if yago else None
        if r['rev']:
            r['opm'] = round((r['op'] or 0)/r['rev']*100,1) if r['op'] is not None else None
        rows.append(r)
    ays = sorted(A['rev'])[-5:]
    ann = []
    for i, y in enumerate(ays):
        o = {'y': y[:4]}
        for f in ('rev','op','ni'): o[f] = A[f].get(y)
        if i: 
            for f in ('rev','op','ni'): o[f+'_g'] = _pct(o[f], A[f].get(ays[i-1]))
        if o['rev'] and o['op'] is not None: o['opm'] = round(o['op']/o['rev']*100,1)
        ann.append(o)
    T, T0 = {}, {}
    for f in ('rev','op','ni','ni_all','nci','da','eps'):
        ks = sorted(F[f])
        T[f]  = sum(F[f][k] for k in ks[-4:]) if len(ks) >= 4 else None
        T0[f] = sum(F[f][k] for k in ks[-8:-4]) if len(ks) >= 8 else None
    # 20-F 만 내는 외국 기업은 분기 XBRL 이 없다 — 최근 연간을 12개월 실적으로 대신 쓴다
    ANN_ONLY = 0
    if T.get('rev') is None and A.get('rev'):
        ANN_ONLY = 1
        ays2 = sorted(A['rev'])
        cur_y, prv_y = ays2[-1], (ays2[-2] if len(ays2) >= 2 else None)
        for f in ('rev','op','ni','ni_all','nci','da','eps'):
            T[f]  = A.get(f, {}).get(cur_y)
            T0[f] = A.get(f, {}).get(prv_y) if prv_y else None
    G = {f: _pct(T[f], T0[f]) for f in ('rev','op','ni')}
    last = lambda m: m[sorted(m)[-1]] if m else None
    bs = {k: last(F[k]) for k in ('ast','liab','eq','eq_all','ar','inv','cash','debt_l','debt_s')}
    debt = ((bs.get('debt_l') or 0) + (bs.get('debt_s') or 0)) or None
    R = {}
    # 총부채를 따로 싣지 않는 회사가 있다(인텔 등) → 자산 − 자본으로 보충
    liab = bs.get('liab')
    if liab is None and bs.get('ast') is not None:
        e2 = bs.get('eq_all') if bs.get('eq_all') is not None else bs.get('eq')
        if e2 is not None: liab = bs['ast'] - e2; bs['liab'] = liab; bs['liab_calc'] = 1
    # 자본잠식(자기자본 ≤ 0)이면 부채비율·ROE는 뜻이 없다 → 비우고 flag 로만 알린다
    if liab is not None and bs.get('eq') and bs['eq'] > 0: R['debt'] = round(liab/bs['eq']*100,1)
    if bs.get('eq') is not None and bs['eq'] <= 0: R['eq_neg'] = 1
    if bs.get('ar') and T.get('rev') and T['rev'] > 0:  R['ar_days'] = round(bs['ar']/T['rev']*365,1)
    if bs.get('inv') and T.get('rev') and T['rev'] > 0: R['inv_days'] = round(bs['inv']/T['rev']*365,1)
    if T.get('ni') and bs.get('eq') and bs['eq'] > 0:   R['roe'] = round(T['ni']/bs['eq']*100,1)
    if T.get('ni') and bs.get('ast') and bs['ast'] > 0: R['roa'] = round(T['ni']/bs['ast']*100,1)
    if T.get('rev') and T['rev'] > 0 and T.get('op') is not None:
        m = T['op']/T['rev']*100
        # 매출이 거의 없는 개발 단계 회사는 이익률이 수천 %로 튄다 → 수치 대신 '적자' 표시
        if m < -200: R['loss'] = 1
        else: R['opm'] = round(m,1)
    if T.get('op') is not None and T['op'] < 0: R['op_neg'] = 1
    if T.get('ni_all') and T.get('nci') is not None: R['nci'] = round(T['nci']/T['ni_all']*100,1)
    V = {}
    # 주가는 달러인데 재무가 대만달러·유로면 PER·PBR·PSR 이 뜻이 없다 — 통화가 같을 때만 계산한다
    if px and shr and CUR != 'USD':
        V['cur_skip'] = CUR
    elif px and shr:
        mc = px*shr; V.update({'px':round(px,2),'shr':shr,'mcap':mc})
        if T.get('ni') and T['ni']>0:  V['per'] = round(mc/T['ni'],1)
        if bs.get('eq') and bs['eq']>0: V['pbr'] = round(mc/bs['eq'],2)
        if T.get('rev'):                V['psr'] = round(mc/T['rev'],2)
        ev = mc + (debt or 0) - (bs.get('cash') or 0)
        if T.get('op') and T['op']>0:
            V['ev_ebit'] = round(ev/T['op'],1)
            if T.get('da'): V['ev_ebitda'] = round(ev/(T['op']+T['da']),1)
    return {'cur':CUR,'annonly':ANN_ONLY,'q':rows,'a':ann,'ttm':T,'g':G,'bs':bs,'r':R,'v':V}

# ───────────────────────── KIS 해외시세 ─────────────────────────
EXMAP = {'Nasdaq':'NAS','NYSE':'NYS','NYSE American':'AMS','AMEX':'AMS','CBOE':'NAS'}

def kis_token():
    k, sec = os.environ.get('KIS_APPKEY'), os.environ.get('KIS_APPSECRET')
    if not k or not sec: return None
    body = json.dumps({'grant_type':'client_credentials','appkey':k,'appsecret':sec}).encode()
    for i in range(3):
        try:
            rq = urllib.request.Request('https://openapi.koreainvestment.com:9443/oauth2/tokenP',
                                        data=body, headers={'content-type':'application/json'})
            with urllib.request.urlopen(rq, timeout=30) as f:
                t = json.loads(f.read().decode()).get('access_token')
            if t: return t
        except Exception: pass
        time.sleep(65)                      # 토큰 발급 1분 1회 제한
    return None

def kis_px(tok, ticker, ex):
    k, sec = os.environ.get('KIS_APPKEY'), os.environ.get('KIS_APPSECRET')
    excd = EXMAP.get(ex)
    if not (tok and excd): return None
    u = ('https://openapi.koreainvestment.com:9443/uapi/overseas-price/v1/quotations/price-detail'
         f'?AUTH=&EXCD={excd}&SYMB={ticker}')
    try:
        rq = urllib.request.Request(u, headers={'content-type':'application/json',
            'authorization':'Bearer '+tok, 'appkey':k, 'appsecret':sec,
            'tr_id':'HHDFS76200200', 'custtype':'P'})
        with urllib.request.urlopen(rq, timeout=30) as f:
            o = (json.loads(f.read().decode()) or {}).get('output') or {}
        v = o.get('last') or o.get('base')
        return float(v) if v not in (None,'','0') else None
    except Exception:
        return None

def get(url, tries=3):
    for i in range(tries):
        try:
            r = urllib.request.Request(url, headers={
                'User-Agent': UA, 'Accept-Encoding': 'gzip, deflate'})
            with urllib.request.urlopen(r, timeout=40) as f:
                b = f.read()
                if f.headers.get('Content-Encoding') == 'gzip': b = gzip.decompress(b)
                return b.decode('utf-8', 'ignore')
        except urllib.error.HTTPError as e:
            if e.code == 403: raise Blocked('SEC 403 — User-Agent 형식 확인 필요')
            if e.code == 404: return ''
            time.sleep(1.5 * (i + 1))
        except Exception:
            time.sleep(1.5 * (i + 1))
    return ''

def tickers_from_tax(tax):
    """분류체계에서 미국 상장 티커와 그 위치(섹터/그룹/세부단계)를 뽑는다"""
    out = {}
    for sec, v in tax['sectors'].items():
        for g in v['groups']:
            for st in g['stages']:
                for c in st['co']:
                    if c.get('notus'): continue
                    out.setdefault(c['t'], []).append(f"{sec}/{g['id']}/{st['id']}")
    return out

def filings(cik):
    j = get(f'https://data.sec.gov/submissions/CIK{cik}.json')
    if not j: return None, []
    d = json.loads(j)
    R = d.get('filings', {}).get('recent', {})
    n = len(R.get('form', []))
    rows = []
    for i in range(n):
        f = R['form'][i]
        if f not in FORMS: continue
        acc = R['accessionNumber'][i]
        rows.append({
            'f': f,
            'd': R['filingDate'][i],
            'rd': R.get('reportDate', [''] * n)[i],
            'acc': acc,
            'u': f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{acc.replace('-','')}/{R['primaryDocument'][i]}",
            'items': (R.get('items', [''] * n)[i] or '')[:60],
        })
        if len(rows) >= KEEP: break
    meta = {'name': d.get('name'), 'sic': d.get('sicDescription'),
            'ex': (d.get('exchanges') or [''])[0], 'fy': d.get('fiscalYearEnd')}
    return meta, rows

def fulltext(q, forms='10-K,10-Q,20-F', days=400):
    """EDGAR 전문검색 — 키워드를 본문에 쓴 기업을 역추적"""
    end = datetime.date.today()
    beg = end - datetime.timedelta(days=days)
    u = ('https://efts.sec.gov/LATEST/search-index?q=' + urllib.parse.quote(f'"{q}"') +
         f'&forms={urllib.parse.quote(forms)}&dateRange=custom'
         f'&startdt={beg}&enddt={end}')
    j = get(u)
    if not j: return {'q': q, 'n': 0, 'hits': []}
    d = json.loads(j)
    hits = []
    for h in d.get('hits', {}).get('hits', [])[:30]:
        s = h.get('_source', {})
        nm = (s.get('display_names') or [''])[0]
        m = re.search(r'\(([A-Z\.\-]{1,6})\)\s*\(CIK (\d{10})\)', nm)
        hits.append({'n': re.sub(r'\s*\(.*', '', nm).strip(),
                     't': m.group(1) if m else '',
                     'cik': m.group(2) if m else '',
                     'd': s.get('file_date', ''), 'f': s.get('file_type', '')})
    return {'q': q, 'n': d.get('hits', {}).get('total', {}).get('value', 0), 'hits': hits}

def main():
    if not UA or '@' not in UA:
        print('SEC_UA 시크릿이 없거나 형식이 틀립니다 — "이름 이메일@도메인" 형태여야 합니다'); return
    t0 = time.time()
    tax = json.loads(TAX.read_text(encoding='utf-8'))
    tmap = tickers_from_tax(tax)
    cm = tax['cik']
    OUT.mkdir(parents=True, exist_ok=True)
    idx_p = OUT / 'index.json'
    idx = json.loads(idx_p.read_text(encoding='utf-8')) if idx_p.exists() else {'co': {}}
    if idx.get('ver') != VER: idx = {'co': {}}          # 형식 올리면 전량 재수집

    TOK = kis_token()
    if not TOK: print('KIS 시크릿 없음 → 주가·배수는 비운 채 재무만 수집')
    todo = sorted(tmap, key=lambda t: idx['co'].get(t, {}).get('at', ''))
    done = fail = 0
    for t in todo:
        if (time.time() - t0) / 60 > MAX: print('시간 예산 소진'); break
        cik = cm.get(t, {}).get('cik')
        if not cik: continue
        try:
            meta, rows = filings(cik)
        except Blocked as e:
            print('중단:', e); break
        time.sleep(GAP)
        if not rows: fail += 1; continue
        px = kis_px(TOK, t, meta.get('ex')) if TOK else None
        try:
            fin = financials(cik, px)
        except Blocked as e:
            print('중단:', e); break
        except Exception as e:
            fin = None; print(f'  {t} 재무 실패: {str(e)[:60]}')
        time.sleep(GAP)
        (OUT / f'{t}.json').write_text(json.dumps(
            {'t': t, 'cik': cik, 'meta': meta, 'nodes': tmap[t], 'rows': rows, 'fin': fin,
             'at': time.strftime('%Y-%m-%d %H:%M')}, ensure_ascii=False), encoding='utf-8')
        e = {'n': meta['name'], 'cik': cik, 'nodes': tmap[t],
             'last': rows[0]['d'], 'lastf': rows[0]['f'], 'n_f': len(rows),
             'at': time.strftime('%Y-%m-%d %H:%M')}
        if fin:
            # 목록·peer 비교에 쓸 요약만 인덱스에 싣는다(종목 파일은 상세용)
            e['m'] = {**{k: v for k, v in fin['v'].items() if k in ('px','mcap','per','pbr','psr','ev_ebit','ev_ebitda')},
                      **{k: v for k, v in fin['r'].items() if k in ('opm','roe','roa','debt','ar_days','nci','loss','op_neg','eq_neg')},
                      'g_rev': fin['g'].get('rev'), 'g_op': fin['g'].get('op'), 'g_ni': fin['g'].get('ni'),
                      'rev': fin['ttm'].get('rev'), 'op': fin['ttm'].get('op'), 'ni': fin['ttm'].get('ni')}
        idx['co'][t] = e
        done += 1

    # 전문검색 — 분류체계가 들고 있는 키워드
    fts = {}
    for q in tax.get('fts', [])[:25]:
        if (time.time() - t0) / 60 > MAX: break
        try: fts[q] = fulltext(q)
        except Blocked: break
        time.sleep(GAP)
    if fts: (OUT / 'fts.json').write_text(json.dumps(
        {'at': time.strftime('%Y-%m-%d %H:%M'), 'q': fts}, ensure_ascii=False), encoding='utf-8')

    # 같은 밸류체인 세부단계에 속한 기업끼리 중앙값을 낸다.
    # 섹터 전체가 아니라 '같은 일을 하는 칸' 안에서 비교해야 뜻이 있다.
    def med(v, lo=None, hi=None):
        # 적자·자본잠식에서 나오는 극단값은 중앙값을 망가뜨린다 → 범위를 벗어나면 버린다
        v = sorted(x for x in v if x is not None and (lo is None or x >= lo) and (hi is None or x <= hi))
        if not v: return None
        n = len(v)
        return round(v[n//2] if n % 2 else (v[n//2-1]+v[n//2])/2, 2)
    BOUND = {'opm': (-200, 200), 'roe': (-200, 500), 'roa': (-200, 300), 'debt': (0, 2000),
             'per': (0, 150), 'pbr': (0, 50), 'psr': (0, 100),
             'ev_ebit': (0, 200), 'ev_ebitda': (0, 200),
             'g_rev': (-100, 1000), 'g_op': (-100, 2000), 'g_ni': (-100, 2000)}
    KEYS = ('per','pbr','psr','ev_ebit','ev_ebitda','opm','roe','roa','debt','g_rev','g_op','g_ni')
    stage = {}
    for t, e in idx['co'].items():
        for nd in e.get('nodes', []):
            stage.setdefault(nd, []).append(t)
    idx['peer'] = {}
    for nd, ts in stage.items():
        ms = [idx['co'][x].get('m') or {} for x in ts]
        row = {k: med([m.get(k) for m in ms], *BOUND.get(k, (None, None))) for k in KEYS}
        row['n'] = sum(1 for m in ms if m)
        idx['peer'][nd] = row

    idx['ver'] = VER
    idx['updated'] = time.strftime('%Y-%m-%d %H:%M')
    idx['n'] = len(idx['co'])
    idx_p.write_text(json.dumps(idx, ensure_ascii=False), encoding='utf-8')
    print(f'수집 {done}건 · 실패 {fail}건 · 전문검색 {len(fts)}건 · 누적 {len(idx["co"])}종목 '
          f'· {int(time.time()-t0)}초')

if __name__ == '__main__':
    main()
