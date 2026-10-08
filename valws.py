#!/usr/bin/env python3
# 밸류 워크시트 자동 채움 수집기 v3 — public/data/valws_watch.json 의 관심 종목(+피어·인접체인·해외 앵커)
#   한국 종목: 네이버 재무(연간 3년+FY1 컨센, 분기), 시세 요약, DART 전체재무제표(연결 우선)로 ROIC·FCF·순차입·이자·재고/채권,
#              DART CB·BW 발행결정(4년), 컨센 EPS 일별 히스토리(리비전 추세)
#   해외 앵커(고객·대장주): SEC EDGAR companyfacts(XBRL) TTM 순이익·매출·EPS·주식수 + Yahoo 시세 → TTM PER (미국은 SEC 공시 기준)
#   ※ 타국(일본 EDINET·대만 MOPS 등)은 anchors[].mkt 로 확장 예정
# 필요 시크릿: DART_API_KEY(선택)   결과: public/data/valws_auto.json
import os, sys, json, time, re, datetime, urllib.request, ssl, zipfile, io
import xml.etree.ElementTree as ET

KEY = os.environ.get('DART_API_KEY', '')
WATCH = os.environ.get('WATCH', 'public/data/valws_watch.json')
OUT = os.environ.get('OUT', 'public/data/valws_auto.json')
SEC_UA = os.environ.get('SEC_UA', 'kis-dashboard research ohseho57@gmail.com')
UA = {'User-Agent': 'Mozilla/5.0'}
CTX = ssl.create_default_context(); CTX.check_hostname = False; CTX.verify_mode = ssl.CERT_NONE
KST = datetime.timezone(datetime.timedelta(hours=9)); TODAY = datetime.datetime.now(KST).date()
DEBUG = []
EOK = 1e8

def log(s): DEBUG.append(str(s)[:300]); print(s, file=sys.stderr, flush=True)
def jget(url, timeout=30, tries=3, hdr=None):
    err = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers=hdr or UA)
            return json.loads(urllib.request.urlopen(req, timeout=timeout, context=CTX).read().decode('utf-8'))
        except Exception as e:
            err = e; time.sleep(1.5 * (i + 1))
    log('fetch 실패 %s %r' % (url[:90], err)); return {}
def tonum(s):
    try:
        s = str(s).replace(',', '').replace('배', '').replace('원', '').replace('%', '').strip()
        if s in ('', '-', 'N/A'): return None
        return float(s)
    except Exception: return None

# ───────── 네이버
def naver_fin(code, kind):
    j = jget('https://m.stock.naver.com/api/stock/%s/finance/%s' % (code, kind))
    fi = j.get('financeInfo') or {}
    cols = [(t['key'], t.get('isConsensus') == 'Y') for t in fi.get('trTitleList') or []]
    rows = {}
    for r in fi.get('rowList') or []:
        rows[r['title']] = {k: tonum(v.get('value')) for k, v in (r.get('columns') or {}).items()}
    return {'cols': cols, 'rows': rows}
def naver_basic(code):
    j = jget('https://m.stock.naver.com/api/stock/%s/integration' % code)
    info = {t['key']: t.get('value') for t in j.get('totalInfos') or []}
    peers = [{'c': p.get('itemCode'), 'n': p.get('stockName')} for p in j.get('industryCompareInfo') or []]
    return {'name': j.get('stockName'), 'ind': j.get('industryCode'), 'info': info, 'naver_peers': peers}

# ───────── DART
def dart_corpmap():
    if not KEY: return {}
    try:
        b = urllib.request.urlopen(urllib.request.Request('https://opendart.fss.or.kr/api/corpCode.xml?crtfc_key=' + KEY, headers=UA), timeout=90, context=CTX).read()
        z = zipfile.ZipFile(io.BytesIO(b)); xml = z.read(z.namelist()[0])
        m = {}
        for el in ET.fromstring(xml).iter('list'):
            sc = (el.findtext('stock_code') or '').strip()
            if re.fullmatch(r'\d{6}', sc): m[sc] = el.findtext('corp_code')
        return m
    except Exception as e:
        log('corpCode 실패 %r' % e); return {}

def dart_bonds(corp):
    out = []
    if not KEY or not corp: return out
    bgn = (TODAY - datetime.timedelta(days=365 * 4)).strftime('%Y%m%d'); end = TODAY.strftime('%Y%m%d')
    for api, kind in (('cvbdIsDecsn', 'CB'), ('bdwtIsDecsn', 'BW')):
        j = jget('https://opendart.fss.or.kr/api/%s.json?crtfc_key=%s&corp_code=%s&bgn_de=%s&end_de=%s' % (api, KEY, corp, bgn, end))
        if j.get('status') != '000': continue
        for r in j.get('list') or []:
            out.append({'kind': kind, 'tm': r.get('bd_tm'), 'knd': r.get('bd_knd'), 'amt': tonum(r.get('bd_fta')),
                        'prc': tonum(r.get('cv_prc') or r.get('ex_prc')), 'cnt': tonum(r.get('cvisstk_cnt') or r.get('ex_stk_cnt')),
                        'vs': r.get('cvisstk_tisstk_vs') or r.get('ex_stk_tisstk_vs'), 'intr': r.get('bd_intr_ex'), 'intr_mt': r.get('bd_intr_sf'),
                        'mtd': r.get('bd_mtd'), 'rcept': r.get('rcept_no'), 'date': (r.get('rcept_no') or '')[:8]})
        time.sleep(0.2)
    return out

# 전체 재무제표에서 뽑을 항목: (키, account_id 후보, 계정명 패턴)
ITEMS = [
    ('rev',    ['ifrs-full:Revenue', 'ifrs-full:RevenueFromContractsWithCustomers', 'ifrs-full:RevenueFromSaleOfGoods'], r'^(매출액|수익\(매출액\)|영업수익|매출|수익)(\(|$)'),
    ('op',     ['dart:OperatingIncomeLoss', 'ifrs-full:ProfitLossFromOperatingActivities'], r'^영업이익(\(손실\))?$'),
    ('ni',     ['ifrs-full:ProfitLoss'], r'^(당기순이익|분기순이익|반기순이익)(\(손실\))?$'),
    ('ni_p',   ['ifrs-full:ProfitLossAttributableToOwnersOfParent'], r'지배기업.*순이익|지배주주.*순이익'),
    ('intexp', ['ifrs-full:InterestExpense', 'dart:InterestExpenseFinanceCosts'], r'^이자비용'),
    ('fincost',['ifrs-full:FinanceCosts'], r'^(금융원가|금융비용)$'),
    ('tax',    ['ifrs-full:IncomeTaxExpenseContinuingOperations'], r'^법인세비용'),
    ('assets', ['ifrs-full:Assets'], r'^자산총계$'),
    ('liab',   ['ifrs-full:Liabilities'], r'^부채총계$'),
    ('equity', ['ifrs-full:Equity'], r'^자본총계$'),
    ('cash',   ['ifrs-full:CashAndCashEquivalents'], r'^현금및현금성자산$'),
    ('inv',    ['ifrs-full:Inventories'], r'^(유동)?재고자산$'),
    ('recv',   ['ifrs-full:TradeAndOtherCurrentReceivables', 'ifrs-full:CurrentTradeReceivables'], r'^(유동)?매출채권'),
    ('cfo',    ['ifrs-full:CashFlowsFromUsedInOperatingActivities'], r'^영업활동.*현금흐름$'),
    ('capex',  ['ifrs-full:PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities'], r'^유형자산의\s*취득'),
    ('capex2', ['ifrs-full:PurchaseOfIntangibleAssetsClassifiedAsInvestingActivities'], r'^무형자산의\s*취득'),
]
DEBT_PAT = r'(차입금|사채|전환사채|신주인수권부사채|리스부채)'
REPRT = {1: '11013', 2: '11012', 3: '11014', 4: '11011'}

def latest_reports():
    """오늘 기준 공시가 나왔을 최신 보고서 목록 [(year, q)]: 최근 3개 사업보고서 + 올해 누적 분기"""
    y, md = TODAY.year, (TODAY.month, TODAY.day)
    cur = (y, 3) if md >= (11, 14) else (y, 2) if md >= (8, 14) else (y, 1) if md >= (5, 15) else None
    ann_last = y - 1 if md >= (3, 31) else y - 2
    out = [(yy, 4) for yy in range(ann_last - 2, ann_last + 1)]
    if cur: out.append(cur)
    # 전년 동기 누적(YoY 비교용)
    if cur: out.append((cur[0] - 1, cur[1]))
    return out

def dart_full(corp, year, q):
    """전체 재무제표(연결 우선) → {key: 값(억)} ; 분기보고서는 당기 누적 기준"""
    if not KEY or not corp: return None
    for fs in ('CFS', 'OFS'):
        j = jget('https://opendart.fss.or.kr/api/fnlttSinglAcntAll.json?crtfc_key=%s&corp_code=%s&bsns_year=%d&reprt_code=%s&fs_div=%s' % (KEY, corp, year, REPRT[q], fs))
        rows = j.get('list') or []
        if j.get('status') != '000' or not rows:
            time.sleep(0.15); continue
        out = {'fs': fs, 'period': '%d%s' % (year, '' if q == 4 else 'Q%d' % q)}
        debt = 0.0; debt_hit = False
        for r in rows:
            aid = (r.get('account_id') or '').strip(); nm = (r.get('account_nm') or '').replace(' ', '').strip(); sj = r.get('sj_div')
            # 손익은 누적(thstrm_add_amount) 우선, 없으면 당기
            if sj in ('IS', 'CIS'):
                v = tonum(r.get('thstrm_add_amount')); v = v if v is not None else tonum(r.get('thstrm_amount'))
            else:
                v = tonum(r.get('thstrm_amount'))
            if v is None: continue
            for key, ids, pat in ITEMS:
                if key in out: continue
                want = 'CF' if key in ('cfo', 'capex', 'capex2') else 'BS' if key in ('assets', 'liab', 'equity', 'cash', 'inv', 'recv') else 'IS'
                okdiv = (sj == want) or (want == 'IS' and sj == 'CIS')
                if (aid in ids and okdiv) or (okdiv and re.search(pat, nm)):
                    out[key] = v / EOK
            if sj == 'BS' and re.search(DEBT_PAT, nm) and not re.search(r'(상환|발행|증가|감소|이자)', nm) and 'ifrs-full:Equity' != aid:
                debt += v / EOK; debt_hit = True
        if debt_hit: out['debt'] = debt
        if 'intexp' not in out and 'fincost' in out: out['intexp'] = out['fincost']; out['intexp_src'] = '금융원가'
        if 'rev' in out or 'equity' in out:
            time.sleep(0.15); return out
        time.sleep(0.15)
    return None

# ───────── SEC (미국 앵커)
_SEC_TICK = None
def sec_cik(ticker):
    global _SEC_TICK
    if _SEC_TICK is None:
        j = jget('https://www.sec.gov/files/company_tickers.json', hdr={'User-Agent': SEC_UA})
        _SEC_TICK = {v['ticker'].upper(): ('%010d' % int(v['cik_str']), v['title']) for v in (j or {}).values()} if isinstance(j, dict) else {}
    return _SEC_TICK.get(ticker.upper())

def sec_ttm(facts, keys):
    """10-Q/10-K 값에서 분기 시계열 복원(Q4 = FY − Q1~Q3) → 최근 4분기 합 TTM. 여러 태그 중 가장 최신 데이터가 있는 태그 사용"""
    def days(a, b):
        try: return (datetime.date.fromisoformat(b) - datetime.date.fromisoformat(a)).days
        except Exception: return None
    best = None
    for k in keys:
        f = (facts.get('us-gaap') or {}).get(k)
        if not f: continue
        units = list(f['units'].values())[0]
        qtr = {}; ann = {}
        for x in sorted(units, key=lambda x: (x.get('end', ''), x.get('filed', ''))):
            if not x.get('start') or not x.get('end'): continue
            d = days(x['start'], x['end'])
            if d is None: continue
            if 75 <= d <= 100: qtr[x['end']] = (x['start'], x['val'])
            elif 350 <= d <= 380: ann[x['end']] = (x['start'], x['val'])
        for end, (st, v) in ann.items():
            if end in qtr: continue
            inside = [vv for e2, (s2, vv) in qtr.items() if s2 and st <= s2 and e2 <= end]
            if len(inside) == 3:
                q4 = v - sum(inside)
                if abs(q4) > 4 * max(1.0, max(abs(i) for i in inside)) and (q4 < 0) != (sum(inside) < 0):
                    qtr[end] = (st, None)                                       # 비정상(일회성 거액 손상 등) → 결측 처리
                else: qtr[end] = (st, q4)
        ends = sorted(qtr)
        if len(ends) < 4: continue
        if best is None or ends[-1] > best['ends'][-1]: best = {'key': k, 'qtr': qtr, 'ends': ends}
    if not best: return None
    qtr, ends = best['qtr'], best['ends']; last = ends[-4:]
    vals = [qtr[e][1] for e in last]; miss = [e for e, v in zip(last, vals) if v is None]
    ok = [v for v in vals if v is not None]
    ttm = sum(ok) * (4 / len(ok)) if ok and len(ok) >= 3 else None            # 결측 1개면 3분기 연율화
    return {'ttm': ttm, 'frames': last, 'key': best['key'], 'anomaly': miss, 'q': [[e, qtr[e][1]] for e in ends[-8:]]}

def sec_anchor(ticker):
    ck = sec_cik(ticker)
    if not ck: return {'t': ticker, 'err': 'CIK 없음'}
    cik, title = ck
    j = jget('https://data.sec.gov/api/xbrl/companyfacts/CIK%s.json' % cik, hdr={'User-Agent': SEC_UA})
    if not j: return {'t': ticker, 'cik': cik, 'err': 'companyfacts 실패'}
    facts = j.get('facts') or {}
    ni = sec_ttm(facts, ['NetIncomeLoss', 'ProfitLoss'])
    rev = sec_ttm(facts, ['RevenueFromContractWithCustomerExcludingAssessedTax', 'Revenues', 'SalesRevenueNet'])
    eps = sec_ttm(facts, ['EarningsPerShareDiluted', 'EarningsPerShareBasic'])
    sh = None
    dei = (facts.get('dei') or {}).get('EntityCommonStockSharesOutstanding')
    if dei:
        u = list(dei['units'].values())[0]; u = sorted(u, key=lambda x: x.get('end', ''))
        if u: sh = u[-1]['val']
    y = jget('https://query1.finance.yahoo.com/v8/finance/chart/%s?range=5d&interval=1d' % ticker)
    meta = ((y.get('chart') or {}).get('result') or [{}])[0].get('meta') or {}
    px = meta.get('regularMarketPrice'); cur = meta.get('currency')
    eps_ttm = (ni['ttm'] / sh) if (ni and sh) else (eps['ttm'] if eps else None)
    per = (px / eps_ttm) if (px and eps_ttm and eps_ttm > 0) else None
    # 매출 YoY(TTM vs 1년 전 TTM)
    rev_g = None
    if rev and len(rev['q']) >= 8:
        a = [v for _, v in rev['q'][-4:]]; b = [v for _, v in rev['q'][:4]]
        if all(v is not None for v in a + b) and sum(b): rev_g = (sum(a) / sum(b) - 1) * 100
    return {'t': ticker, 'cik': cik, 'name': title, 'px': px, 'cur': cur, 'shares': sh, 'ni_ttm': ni and ni['ttm'], 'rev_ttm': rev and rev['ttm'],
            'eps_ttm': eps_ttm, 'per_ttm': per, 'rev_yoy': rev_g, 'frames': ni and ni['frames'], 'anomaly': (ni and ni.get('anomaly')) or [], 'src': 'SEC EDGAR companyfacts (%s) + Yahoo 시세' % (ni and ni['key'] or '-'),
            'url': 'https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK=%s' % cik}

def main():
    try: w = json.load(open(WATCH, encoding='utf-8'))
    except Exception as e: log('watch 파일 없음 %r' % e); w = {}
    codes = [c for c in w.get('codes') or [] if re.fullmatch(r'\d{6}', c)]
    peers = {k: [p for p in v if re.fullmatch(r'\d{6}', p)] for k, v in (w.get('peers') or {}).items()}
    chain = {k: [p for p in v if re.fullmatch(r'\d{6}', p)] for k, v in (w.get('chain') or {}).items()}
    anchors = w.get('anchors') or {}
    allc = list(dict.fromkeys(codes + [p for v in peers.values() for p in v] + [p for v in chain.values() for p in v]))
    try: prev = json.load(open(OUT, encoding='utf-8'))
    except Exception: prev = {}
    hist = prev.get('hist') or {}
    corpmap = dart_corpmap()
    reps = latest_reports()
    out = {}
    for c in allc:
        b = naver_basic(c); a = naver_fin(c, 'annual'); q = naver_fin(c, 'quarter')
        d = {'name': b['name'], 'ind': b['ind'], 'info': b['info'], 'naver_peers': b['naver_peers'][:8], 'annual': a, 'quarter': q}
        if c in codes:
            d['bonds'] = dart_bonds(corpmap.get(c))
            fin = []
            for (yy, qq) in reps:
                r = dart_full(corpmap.get(c), yy, qq)
                if r: fin.append(r)
            d['fin'] = fin
            # 컨센 히스토리
            fy1 = next((k for k, cons in a['cols'] if cons), None)
            if fy1:
                g = lambda row: (a['rows'].get(row) or {}).get(fy1)
                h = hist.setdefault(c, [])
                today = TODAY.isoformat()
                if not h or h[-1][0] != today:
                    h.append([today, g('EPS'), g('매출액'), g('영업이익'), fy1])
                hist[c] = h[-400:]
        out[c] = d; log('%s %s ok fin=%d' % (c, b['name'], len(d.get('fin', [])))); time.sleep(0.3)
    anc = {}
    for c, lst in anchors.items():
        anc[c] = []
        for it in lst:
            t = it.get('t'); mkt = (it.get('mkt') or 'US').upper()
            if mkt == 'US': r = sec_anchor(t)
            else: r = {'t': t, 'err': '%s 공시 수집 미구현(확장 예정)' % mkt}
            r['role'] = it.get('role', ''); r['mkt'] = mkt; anc[c].append(r); time.sleep(0.4)
            log('anchor %s %s PER=%s' % (c, t, r.get('per_ttm')))
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump({'updated': datetime.datetime.now(KST).strftime('%Y-%m-%d %H:%M'), 'codes': codes, 'peers': peers, 'chain': chain, 'anchors': anc,
               'map': out, 'hist': hist, 'reports': ['%d%s' % (y, '' if q == 4 else 'Q%d' % q) for y, q in reps], 'debug': DEBUG[-40:]},
              open(OUT, 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'))
    log('저장 %s %d종목 anchors=%d' % (OUT, len(out), sum(len(v) for v in anc.values())))

if __name__ == '__main__': main()
