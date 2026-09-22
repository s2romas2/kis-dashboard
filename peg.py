#!/usr/bin/env python3
# 반도체 소부장(semimap.json 146사) PEG 밸류 일일 수집 — KIS 오픈API
#   현재가·시총·트레일링 PER : inquire-price (FHKST01010100)
#   순이익 추정 FY1·FY2      : 네이버 종목 재무 API(FnGuide 컨센서스) 우선 → 없으면 KIS 종목추정실적(한투 단일 추정)
#   PEG = 선행 PER ÷ 순이익 성장률(%)
#     · peg1 = FY1 PER(시총/올해E 순이익) ÷ 올해 순이익 성장률(FY1/FY0−1)
#     · peg2 = 12M 선행 PER ÷ 2년 순이익 CAGR(FY0→FY2)   ← 대표값(단년 급증 왜곡 완화)
#   해석(사용자 기준): <1.0 성장률 대비 저평가 · ≈1.0 적정 · ≥2.0 고평가 / 피터 린치: 0.5 매수 매력 큼, 1.5도 무난
# 필요 시크릿: KIS_APPKEY, KIS_APPSECRET   결과: public/data/peg.json
import os, sys, json, time, re, math, datetime, urllib.request, ssl

APPKEY = os.environ.get('KIS_APPKEY', ''); APPSECRET = os.environ.get('KIS_APPSECRET', '')
KIS = 'https://openapi.koreainvestment.com:9443'
OUT = os.environ.get('OUT', 'public/data/peg.json')
SRC = os.environ.get('SRC', 'public/data/semimap.json')
LIMIT = int(os.environ.get('LIMIT', '0'))
EXTRA = [c for c in os.environ.get('EXTRA', '').split(',') if re.fullmatch(r'\d{6}', c)]
UA = {'User-Agent': 'Mozilla/5.0'}
CTX = ssl.create_default_context(); CTX.check_hostname = False; CTX.verify_mode = ssl.CERT_NONE
KST = datetime.timezone(datetime.timedelta(hours=9)); TODAY = datetime.datetime.now(KST).date()
DEBUG = []

def log(s): DEBUG.append(str(s)[:300]); print(s, file=sys.stderr)
def fetch(url, headers=None, data=None, timeout=30, tries=3):
    err = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, data=data, headers=dict(UA, **(headers or {})))
            return urllib.request.urlopen(req, timeout=timeout, context=CTX).read()
        except Exception as e:
            err = e; time.sleep(2 * (i + 1))
    log('fetch 실패 %s %r' % (url[:80], err)); return b''
def jget(url, headers=None):
    try: return json.loads(fetch(url, headers).decode('utf-8'))
    except Exception: return {}
def tonum(s):
    try: return float(str(s).replace(',', '').strip())
    except Exception: return None

def kis_token():
    for attempt in range(4):
        try:
            b = fetch(KIS + '/oauth2/tokenP', {'content-type': 'application/json'},
                      json.dumps({'grant_type': 'client_credentials', 'appkey': APPKEY, 'appsecret': APPSECRET}).encode())
            tok = json.loads(b.decode()) if b else {}
        except Exception as e:
            tok = {'error': repr(e)}
        if tok.get('access_token'): return tok['access_token']
        log('토큰 시도%d 실패: %s' % (attempt + 1, str(tok)[:150])); time.sleep(65)
    return None
def kis_hdr(token, tr):
    return {'content-type': 'application/json', 'authorization': 'Bearer ' + token,
            'appkey': APPKEY, 'appsecret': APPSECRET, 'tr_id': tr, 'custtype': 'P'}
def kis_price(token, code):
    j = jget(KIS + '/uapi/domestic-stock/v1/quotations/inquire-price?fid_cond_mrkt_div_code=J&fid_input_iscd=' + code,
             kis_hdr(token, 'FHKST01010100'))
    o = j.get('output') or {}
    if not o.get('stck_prpr'): return {}
    return {'px': tonum(o.get('stck_prpr')), 'cap': tonum(o.get('hts_avls')), 'per': tonum(o.get('per')),
            'eps': tonum(o.get('eps')), 'pbr': tonum(o.get('pbr'))}
def kis_estimate(token, code):
    j = jget(KIS + '/uapi/domestic-stock/v1/quotations/estimate-perform?SHT_CD=' + code, kis_hdr(token, 'HHKST668300C0'))
    return {k: j.get(k) for k in ('rt_cd', 'msg1', 'output1', 'output2', 'output3', 'output4')}

def naver_consensus(code):
    """네이버 모바일 종목 재무(연간) API — FnGuide 컨센서스(다수 추정). → fy dict (억원, est=컨센 여부)"""
    j = jget('https://m.stock.naver.com/api/stock/%s/finance/annual' % code)
    fi = (j or {}).get('financeInfo') or {}
    tl = fi.get('trTitleList') or []; rows = fi.get('rowList') or []
    if not tl or not rows: return {}
    def row(title):
        for r in rows:
            if (r.get('title') or '').replace(' ', '') == title: return r.get('columns') or {}
        return {}
    rv, op, ni, nic = row('매출액'), row('영업이익'), row('당기순이익'), row('지배주주순이익')
    fy = {}
    for t in tl:
        k = t.get('key') or ''; m = re.match(r'(20\d\d)', k)
        if not m: continue
        def v(col):
            c = (col.get(k) or {}).get('value'); x = tonum(c)
            return x
        n = v(nic); n = n if n is not None else v(ni)   # 지배주주순이익 우선(없으면 당기순이익)
        fy[m.group(1)] = {'rv': v(rv), 'op': v(op), 'ni': n, 'est': (t.get('isConsensus') == 'Y')}
    return fy

# ── 추정실적 파싱 (valalert.py와 동일 로직·검증) ──
def _growth_ok(base, gr):
    n = 0
    for i in range(1, 5):
        a, b, g = base[i - 1], base[i], gr[i]
        if a in (None, 0) or b is None or g is None: continue
        if abs((b / a - 1) * 1000 - g) > max(15, abs(g) * 0.03): return False
        n += 1
    return n >= 2

def parse_estimate(est):
    """→ ({'2025': {'rv','op','ni','est':False}, '2026': {..., 'est':True}, ...}, note). 단위 억원."""
    try:
        o4 = est.get('output4') or []
        periods = [str(r.get('dt') or '').strip() for r in o4] if isinstance(o4, list) else []
        o2 = est.get('output2') or []
        if isinstance(o2, dict): o2 = [o2]
        if not periods or not o2:
            o1 = est.get('output1') or {}
            if isinstance(o1, dict) and not (o1.get('sht_cd') or '').strip():
                return {}, '미커버'
            return {}, '추정 구조 없음'
        rows = []
        for r in o2:
            vals = [tonum(r.get('data%d' % i)) for i in range(1, 6)]
            label = ''
            for k, v in r.items():
                if not str(k).startswith('data') and isinstance(v, str) and re.search(r'[가-힣A-Za-z]', v):
                    label = v; break
            rows.append((label, vals))
        pick = {}
        if any(l for l, _ in rows):
            want = {'rv': ('매출액', '매출'), 'op': ('영업이익',), 'ni': ('당기순이익', '순이익')}
            for key, names in want.items():
                for label, vals in rows:
                    if any(n in label.replace(' ', '') for n in names) and '률' not in label and '율' not in label:
                        pick[key] = vals; break
        note = '라벨'
        if len(pick) < 3:
            if len(rows) < 6: return {}, '행 수 %d' % len(rows)
            rv, rvg, op, opg, ni, nig = [r[1] for r in rows[:6]]
            if not (_growth_ok(rv, rvg) and _growth_ok(op, opg)): return {}, '행 순서 검증 실패'
            if not all(r is None or o is None or r >= o for r, o in zip(rv, op)): return {}, '매출<영업이익'
            pick = {'rv': rv, 'op': op, 'ni': ni}; note = '검증'
        fy = {}
        for i, p in enumerate(periods[:5]):
            m = re.search(r'(20\d\d)', p)
            if not m: continue
            fy[m.group(1)] = {'rv': pick['rv'][i], 'op': pick['op'][i], 'ni': pick['ni'][i], 'est': 'E' in p.upper()}
        o1 = est.get('output1') or {}
        return fy, note + '|' + str(o1.get('estdate') or '') + '|' + str(o1.get('rcmd_name') or '')
    except Exception as e:
        return {}, '파싱 예외 %r' % e

def pct(a, b):  # b/a-1 (%)
    if a is None or b is None or a <= 0 or b <= 0: return None
    return round((b / a - 1) * 100, 1)
def cagr(a, b, yrs):
    if a is None or b is None or a <= 0 or b <= 0: return None
    return round(((b / a) ** (1.0 / yrs) - 1) * 100, 1)
def div(a, b, nd=2):
    if a is None or b is None or b <= 0: return None
    return round(a / b, nd)
def grade(p):
    if p is None: return ''
    if p < 0.5: return 'A'   # 매우 저평가(린치 매수 매력)
    if p < 1.0: return 'B'   # 저평가
    if p <= 1.5: return 'C'  # 적정(1.0 전후 · 1.5 무난)
    if p < 2.0: return 'D'   # 다소 고평가
    return 'E'               # 고평가

def build(code, name, meta, px, est, nfy=None):
    row = {'c': code, 'n': name, 'cat': meta.get('cat'), 'g': meta.get('g'), 'p': meta.get('p'),
           'px': px.get('px'), 'cap': px.get('cap'), 'per_t': px.get('per'), 'pbr': px.get('pbr')}
    y1 = str(TODAY.year)
    kfy, note = parse_estimate(est)
    fy = {}; src = ''
    if nfy and nfy.get(y1) and nfy[y1].get('ni') is not None:
        fy = nfy; src = '네이버 컨센서스(FnGuide)'
    elif kfy and kfy.get(y1) and kfy[y1].get('ni') is not None:
        fy = kfy; src = '한투 리서치(KIS 단일 추정)'
    row['note'] = note; row['src'] = src
    if kfy and kfy.get(y1) and nfy and nfy.get(y1) and kfy[y1].get('ni') and nfy[y1].get('ni'):
        row['kis_ni1'] = kfy[y1]['ni']   # 교차확인용: 한투 단일 추정 올해 순이익
    if not fy:
        row['status'] = '미커버' if (note.startswith('미커버') and not nfy) else '추정 없음'; return row
    y1, y2 = str(TODAY.year), str(TODAY.year + 1)
    y0 = str(TODAY.year - 1)
    a0, a1, a2 = fy.get(y0), fy.get(y1), fy.get(y2)
    ni0 = a0 and a0.get('ni'); ni1 = a1 and a1.get('ni'); ni2 = a2 and a2.get('ni')
    op0 = a0 and a0.get('op'); op1 = a1 and a1.get('op'); op2 = a2 and a2.get('op')
    fy2note = ''
    if ni2 is None and kfy and kfy.get(y1) and kfy.get(y2):   # 컨센에 내년 추정이 없으면 한투 단일추정의 내년 성장률만 차용
        k1, k2 = kfy[y1].get('ni'), kfy[y2].get('ni')
        if ni1 and k1 and k2 and k1 > 0 and k2 > 0:
            ni2 = ni1 * (k2 / k1); fy2note = 'FY2=한투 추정 성장률(%+.0f%%) 적용' % ((k2 / k1 - 1) * 100)
        ko1, ko2 = kfy[y1].get('op'), kfy[y2].get('op')
        if op2 is None and op1 and ko1 and ko2 and ko1 > 0 and ko2 > 0: op2 = op1 * (ko2 / ko1)
    row.update({'fy0': y0, 'ni0': ni0, 'ni1': ni1, 'ni2': ni2, 'op0': op0, 'op1': op1, 'op2': op2,
                'actual0': bool(a0 and not a0.get('est'))})
    cap = px.get('cap')
    rem = (datetime.date(TODAY.year, 12, 31) - TODAY).days / 365.0
    ni_f12 = ni1 * rem + ni2 * (1 - rem) if (ni1 is not None and ni2 is not None) else ni1
    op_f12 = op1 * rem + op2 * (1 - rem) if (op1 is not None and op2 is not None) else op1
    row['per_f1'] = div(cap, ni1)            # FY1 PER
    row['per_f12'] = div(cap, ni_f12)        # 12M 선행 PER
    row['pop_f12'] = div(cap, op_f12)        # 12M 선행 P/OP(POR)
    row['g1'] = pct(ni0, ni1)                # 올해 순이익 성장률
    row['g2'] = pct(ni1, ni2)                # 내년 순이익 성장률
    row['cagr2'] = cagr(ni0, ni2, 2)         # 2년 CAGR
    row['og1'] = pct(op0, op1); row['ocagr2'] = cagr(op0, op2, 2)
    row['peg1'] = div(row['per_f1'], row['g1'])
    row['peg2'] = div(row['per_f12'], row['cagr2'])
    if row['peg2'] is None and ni2 is None and row['peg1'] is not None:
        row['peg2'] = row['peg1']; row['peg2_fallback'] = 'FY2 추정 없음 → FY1 기준'
    row['peg_op'] = div(row['pop_f12'], row['ocagr2'])   # 영업이익 기준 PEG(참고)
    row['grade'] = grade(row['peg2'] if row['peg2'] is not None else row['peg1'])
    flags = []
    if row.get('peg2_fallback'): flags.append(row['peg2_fallback'])
    if fy2note: flags.append(fy2note)
    if row.get('kis_ni1') and ni1 and abs(row['kis_ni1'] / ni1 - 1) > 0.3: flags.append('한투 단일추정과 30%%↑ 괴리(%s억)' % int(row['kis_ni1']))
    if ni0 is not None and ni0 <= 0: flags.append('FY0 적자→성장률 산출 불가(턴어라운드)')
    if ni1 is not None and ni1 <= 0: flags.append('FY1 적자')
    if row['cagr2'] is not None and row['cagr2'] < 0: flags.append('순이익 역성장→PEG 무의미')
    gused = row['cagr2'] if (row['cagr2'] is not None and not row.get('peg2_fallback')) else row['g1']
    if gused is not None and gused > 100: flags.append('성장률 100%↑ — 저PEG 과신 금지(기저효과)')
    if not row['actual0']: flags.append('FY0 확정치 아님')
    row['flags'] = flags
    row['status'] = 'ok' if (row['peg2'] is not None or row['peg1'] is not None) else 'PEG 산출 불가'
    return row

def main():
    try:
        sm = json.load(open(SRC, encoding='utf-8'))
    except Exception as e:
        print('semimap 로드 실패', e); sys.exit(1)
    metas = {it['c']: it for it in sm.get('items', []) if re.fullmatch(r'\d{6}', str(it.get('c', '')))}
    for c in EXTRA: metas.setdefault(c, {'c': c, 'n': c, 'cat': '기타'})
    codes = list(metas.keys())
    if LIMIT: codes = codes[:LIMIT]
    prev = {}
    try: prev = {r['c']: r for r in json.load(open(OUT, encoding='utf-8')).get('rows', [])}
    except Exception: pass
    if not APPKEY or not APPSECRET:
        print('KIS 시크릿 없음 — 기존 파일 유지'); return
    token = kis_token()
    if not token:
        print('토큰 실패 — 기존 파일 유지'); return
    rows = []; ok = 0; nocov = 0
    for i, c in enumerate(codes):
        px = kis_price(token, c); time.sleep(0.12)
        est = kis_estimate(token, c); time.sleep(0.12)
        try: nfy = naver_consensus(c)
        except Exception as e: nfy = {}; log('%s 네이버 컨센 실패 %r' % (c, e))
        time.sleep(0.15)
        if not px:
            log('%s 시세 실패' % c)
            if c in prev: rows.append(prev[c]); continue
        r = build(c, metas[c].get('n', c), metas[c], px, est, nfy)
        if r.get('status') == 'ok': ok += 1
        elif r.get('status') in ('미커버', '추정 없음'): nocov += 1
        rows.append(r)
        if (i + 1) % 25 == 0: print('%d/%d' % (i + 1, len(codes)), file=sys.stderr)
    rows.sort(key=lambda r: (r.get('peg2') is None, r.get('peg2') if r.get('peg2') is not None else 9e9))
    out = {'updated': datetime.datetime.now(KST).strftime('%Y-%m-%d %H:%M'), 'n': len(rows), 'ok': ok, 'nocov': nocov,
           'source': '시세·트레일링PER=KIS / 추정=네이버 컨센서스(FnGuide, 다수 추정) 우선, 없으면 한투 리서치(KIS 단일 추정)',
           'legend': {'peg2': '12M 선행 PER ÷ 2년 순이익 CAGR(FY0→FY2)', 'peg1': 'FY1 PER ÷ 올해 순이익 성장률',
                      'peg_op': '12M 선행 P/OP ÷ 2년 영업이익 CAGR',
                      'grade': {'A': '<0.5 매우 저평가(린치: 매수 매력 큼)', 'B': '0.5~1.0 성장률 대비 저평가',
                                'C': '1.0~1.5 적정(1.0 전후 그럭저럭·1.5도 무난)', 'D': '1.5~2.0 다소 고평가', 'E': '≥2.0 고평가'}},
           'debug': DEBUG[-30:], 'rows': rows}
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(out, open(OUT, 'w', encoding='utf-8'), ensure_ascii=False, indent=0)
    print('완료: %d종목, PEG 산출 %d, 미커버 %d' % (len(rows), ok, nocov))

if __name__ == '__main__':
    main()
