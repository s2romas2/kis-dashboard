#!/usr/bin/env python3
# 반도체 교과서(semibook) 수집기 — 기업 쪽에 들어가는 "5년치 숫자와 이력"을 모은다.
#   대상: 반도체 peer 상대밸류 종목(semipeer.json)
#   ① 5개년 분기·연간 매출·영업이익·순이익: OpenDART 다중회사 주요계정(fnlttMultiAcnt), 각 분기 보고서의 당시 공시값 그대로
#        분기값 = 보고서의 3개월 금액, 없으면 누적 차분(4분기 = 연간 − 3분기 누적). 연결 우선, 없으면 별도.
#   ② 자금조달·인수·매각 이력(5년): 주요사항보고서 목록(pblntf_ty=B) 제목 분류 + 구조화 API로 금액·상대방 보완
#   ③ 지배구조 사건(5년): 거래소 공시(pblntf_ty=I) 제목에서 최대주주 변경·횡령·배임·불성실공시·관리종목 등
# 결과: public/data/semibook.json     필요 시크릿: DART_API_KEY
# 원칙: 숫자는 공시·API 값 그대로. 받지 못한 구간은 빈 값으로 덮지 않고 기존 값을 지킨다.
import os, sys, json, time, re, datetime, urllib.request, urllib.parse, ssl

VER = 2          # 이력(공시 목록) 규칙 버전
FV = 3           # 실적 계산 규칙 버전
KEY = os.environ.get('DART_API_KEY') or os.environ.get('DART_KEY') or ''
OUT = os.environ.get('OUT', 'public/data/semibook.json')
BUDGET = int(os.environ.get('BUDGET_MIN', '50')) * 60
GAP = float(os.environ.get('DART_GAP', '0.35'))
CHUNK = int(os.environ.get('CHUNK', '50'))
Y0 = int(os.environ.get('Y0', '2021'))            # 시작 연도(5개년)
EV_DAYS = int(os.environ.get('EV_DAYS', '7'))     # 이력은 종목별 7일 주기로 다시 받음
ONLY = [c for c in os.environ.get('ONLY', '').split(',') if c]
UA = {'User-Agent': 'Mozilla/5.0'}
CTX = ssl.create_default_context(); CTX.check_hostname = False; CTX.verify_mode = ssl.CERT_NONE
KST = datetime.timezone(datetime.timedelta(hours=9)); NOW = datetime.datetime.now(KST); TODAY = NOW.date()
T0 = time.time(); BASE = 'https://opendart.fss.or.kr/api'; EOK = 1e8
DEBUG = []; STAT = {'dart': 0, 'err': 0, 'limit': False}; FAILRUN = [0]; _last = [0.0]; KEYS = {}
class DartFail(Exception): pass
LAB = {}; OLD_LAB = {}   # 분기·연도 라벨(전 종목 공통)
NAMES = {}; RAW = {}; MISS = {}; FILL = {}; TRIED = {}   # 진단용: 계정명, 매출 원값(3개월·누적), 전체 재무제표로 보충한 칸

def log(s):
    s = str(s)[:300]; DEBUG.append(s); print(s, file=sys.stderr, flush=True)
def left(): return BUDGET - (time.time() - T0)
def tonum(s):
    try:
        s = str(s).replace(',', '').replace('%', '').replace('원', '').strip()
        if s in ('', '-', 'N/A'): return None
        return float(s)
    except Exception: return None
def fetch(url, timeout=40, tries=2):
    err = None
    for i in range(tries):
        try: return urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout, context=CTX).read()
        except Exception as e: err = e; time.sleep(1.5 * (i + 1))
    raise err
def api(name, _full=False, **kw):
    """OpenDART JSON → list(없으면 []). 네트워크 실패·한도 초과는 DartFail"""
    if not KEY: return {} if _full else []
    if STAT['limit']: raise DartFail('중단됨')
    w = _last[0] + GAP - time.time()
    if w > 0: time.sleep(w)
    _last[0] = time.time()
    try:
        j = json.loads(fetch('%s/%s.json?%s' % (BASE, name, urllib.parse.urlencode(dict(crtfc_key=KEY, **kw))), 60 if name == 'fnlttMultiAcnt' else 25).decode('utf-8'))
    except Exception as e:
        STAT['err'] += 1; FAILRUN[0] += 1; log('DART 실패 %s %r (연속 %d)' % (name, str(e)[:70], FAILRUN[0]))
        if FAILRUN[0] >= 10: STAT['limit'] = True; log('DART 연속 실패 10회 → 이번 실행은 중단(다음 시도에서 이어감)')
        elif FAILRUN[0] % 4 == 0: time.sleep(40)
        raise DartFail(name)
    FAILRUN[0] = 0; STAT['dart'] += 1
    st = j.get('status')
    if st == '020': STAT['limit'] = True; log('DART 사용한도 초과'); raise DartFail('한도')
    if st not in ('000', '013'): log('api %s status %s %s' % (name, st, j.get('message')))
    return j if _full else (j.get('list') or [])

# ───────── ① 5개년 분기·연간 실적
REPRT = {1: '11013', 2: '11012', 3: '11014', 4: '11011'}
REV_PRI = {'매출액': 0, '수익(매출액)': 1, '매출': 2, '영업수익': 3, '순영업수익': 4, '매출및지분법손익': 5}
def acct_key(nm):
    nm = (nm or '').replace(' ', '')
    if nm in REV_PRI: return ('rev', REV_PRI[nm])
    if nm.startswith('매출액') or nm.startswith('수익(매출'): return ('rev', 6)
    if nm in ('영업이익', '영업이익(손실)'): return ('op', 0)
    if nm.startswith('영업이익(') and '률' not in nm: return ('op', 1)
    if nm in ('당기순이익', '당기순이익(손실)'): return ('ni', 0)
    if nm in ('분기순이익', '분기순이익(손실)', '반기순이익', '반기순이익(손실)'): return ('ni', 1)
    if re.fullmatch(r'(연결)?(당기|분기|반기)순(이익|손익)(\(손실\))?', nm): return ('ni', 2)
    return (None, 9)
def latest_quarter():
    y, md = TODAY.year, (TODAY.month, TODAY.day)
    if md >= (11, 14): return (y, 3)
    if md >= (8, 14): return (y, 2)
    if md >= (5, 15): return (y, 1)
    if md >= (3, 31): return (y - 1, 4)
    return (y - 1, 3)
def periods():
    ly, lq = latest_quarter(); out = []
    for y in range(Y0, ly + 1):
        for q in (1, 2, 3, 4):
            if (y, q) <= (ly, lq): out.append((y, q))
    return out
def parse_multi(rows, year, q, store):
    """store[corp][(year,q)][fs][key] = {'q': 3개월(있을 때), 'cum': 누적, 'pri'} (원)"""
    for r in rows or []:
        if (r.get('sj_div') or '') == 'BS': continue
        key, pri = acct_key(r.get('account_nm'))
        corp = r.get('corp_code'); fs = r.get('fs_div') or 'OFS'
        if corp: NAMES.setdefault((corp, year, q, fs), []).append((r.get('account_nm') or '').replace(' ', '')[:14])
        if key is None or not corp: continue
        amt = tonum(r.get('thstrm_amount')); add = tonum(r.get('thstrm_add_amount'))
        if amt is None and add is None: continue
        if key == 'rev': RAW.setdefault(corp, {})[(year, q, fs)] = (amt, add)
        if q == 4: cum, qv = amt, None                      # 사업보고서: 연간
        elif q == 1: cum, qv = (add if add is not None else amt), (amt if amt is not None else add)
        elif add is None: cum, qv = amt, None               # 누적 칸이 없으면 그 값을 누적으로 본다
        elif amt is None or amt == add: cum, qv = add, None  # 3개월 칸이 누적과 같으면(신규 상장 첫 보고서 등) 3개월값으로 쓰지 않는다
        else: cum, qv = add, amt
        d = store.setdefault(corp, {}).setdefault((year, q), {}).setdefault(fs, {})
        if key in d and d[key]['pri'] <= pri: continue
        d[key] = {'q': qv, 'cum': cum, 'pri': pri}
def series(sc, ps):
    """한 회사의 분기·연간 시계열(억). 연결 우선, 그 분기에 연결값이 없으면 별도."""
    def val(fs, y, q, k):
        x = (((sc.get((y, q)) or {}).get(fs) or {}).get(k)) or {}
        if q == 4:
            ann = x.get('cum'); p = ((((sc.get((y, 3)) or {}).get(fs) or {}).get(k)) or {}).get('cum')
            return None if (ann is None or p is None) else ann - p
        if x.get('q') is not None: return x['q']
        cum = x.get('cum')
        if cum is None: return None
        if q == 1: return cum
        p = ((((sc.get((y, q - 1)) or {}).get(fs) or {}).get(k)) or {}).get('cum')
        return None if p is None else cum - p
    def ann(fs, y, k): return ((((sc.get((y, 4)) or {}).get(fs) or {}).get(k)) or {}).get('cum')
    r = lambda v: None if v is None else round(v / EOK, 1)
    out = {'ql': [], 'rq': [], 'oq': [], 'nq': [], 'fq': [], 'ay': [], 'ar': [], 'ao': [], 'an': [], 'fa': []}
    for (y, q) in ps:
        pick = None
        for fs in ('CFS', 'OFS'):
            v = [val(fs, y, q, k) for k in ('rev', 'op', 'ni')]
            if v[0] is not None and v[0] <= 0: v[0] = None
            if v[0] is not None or v[1] is not None: pick = (fs, v); break
        out['ql'].append('%dQ%02d' % (q, y % 100))
        fs, v = pick or (None, [None, None, None])
        out['rq'].append(r(v[0])); out['oq'].append(r(v[1])); out['nq'].append(r(v[2])); out['fq'].append({'CFS': 'C', 'OFS': 'O'}.get(fs))
    for y in sorted({y for (y, q) in ps if q == 4}):
        pick = None
        for fs in ('CFS', 'OFS'):
            v = [ann(fs, y, k) for k in ('rev', 'op', 'ni')]
            if v[0] is not None or v[1] is not None: pick = (fs, v); break
        fs, v = pick or (None, [None, None, None])
        out['ay'].append(y); out['ar'].append(r(v[0])); out['ao'].append(r(v[1])); out['an'].append(r(v[2])); out['fa'].append({'CFS': 'C', 'OFS': 'O'}.get(fs))
    # 단위 오류 등 터무니없는 값 제거: 분기 매출이 다른 분기 중앙값의 30배를 넘으면 그 분기는 비운다
    vals = sorted(v for v in out['rq'] if v is not None and v > 0)
    if len(vals) >= 4:
        med = vals[len(vals) // 2]
        for i, v in enumerate(out['rq']):
            if v is not None and med > 0 and v > med * 30:
                out['rq'][i] = out['oq'][i] = out['nq'][i] = None; out.setdefault('drop', []).append(out['ql'][i])
    return out
def merge_series(new, old):
    """새로 받지 못한 칸(None)은 기존 값을 지킨다(라벨 기준)."""
    if not old: return new
    for lab, keys, f in (('ql', ('rq', 'oq', 'nq'), 'fq'), ('ay', ('ar', 'ao', 'an'), 'fa')):
        om = {l: i for i, l in enumerate(old.get(lab) or [])}
        for i, l in enumerate(new[lab]):
            j = om.get(l)
            if j is None: continue
            for k in keys:
                if new[k][i] is None and j < len(old.get(k) or []) and old[k][j] is not None:
                    new[k][i] = old[k][j]
                    if new[f][i] is None and j < len(old.get(f) or []) and old[f][j] in ('C', 'O'): new[f][i] = old[f][j]
    return new
def collect_fin(corp_of, olds):
    ps = periods(); store = {}; corps = sorted(set(corp_of.values())); failed = 0
    for (y, q) in ps:
        log('실적 %d년 %d분기 보고서 받는 중 (%.0f초 경과)' % (y, q, time.time() - T0))
        for i in range(0, len(corps), CHUNK):
            if STAT['limit'] or left() < 240: failed += 1; continue
            try: parse_multi(api('fnlttMultiAcnt', corp_code=','.join(corps[i:i + CHUNK]), bsns_year=y, reprt_code=REPRT[q]), y, q, store)
            except DartFail: failed += 1
    # 주요계정 API에 매출·영업이익 중 한쪽이 빠진 기간은 전체 재무제표(fnlttSinglAcntAll)에서 표준 계정 ID로 보충한다
    IDMAP = {'ifrs-full_Revenue': '매출액', 'dart_OperatingIncomeLoss': '영업이익', 'ifrs-full_ProfitLoss': '당기순이익'}
    nfill = 0
    for code, corp in corp_of.items():
        sc = store.get(corp) or {}
        if not sc: continue
        for (y, q) in ps:
            if nfill >= 60 or STAT['limit'] or left() < 200: continue
            per = sc.get((y, q)) or {}
            fs = next((f for f in ('CFS', 'OFS') if 'rev' in (per.get(f) or {}) or 'op' in (per.get(f) or {})), None)   # 그 기간에 실제로 쓰이는 재무제표
            if not fs: continue
            d = per.get(fs) or {}
            if ('rev' in d) == ('op' in d): continue      # 둘 다 있으면 보충할 것이 없다
            lab = '%dQ%02d' % (q, y % 100)
            if lab in (TRIED.get(code) or []) and (y, q) not in ps[-2:]: continue   # 지난 실행에서 이미 보충을 시도한 칸(값은 기존 파일에서 이어받음)
            TRIED.setdefault(code, []); TRIED[code].append(lab) if lab not in TRIED[code] else None
            try: rows = api('fnlttSinglAcntAll', corp_code=corp, bsns_year=y, reprt_code=REPRT[q], fs_div=fs)
            except DartFail: failed += 1; continue
            nfill += 1; add = []; log('보충 %s %s (%.0f초 경과)' % (code, lab, time.time() - T0))
            for r in rows:
                if (r.get('sj_div') or '') not in ('IS', 'CIS'): continue
                nm = IDMAP.get((r.get('account_id') or '').strip())
                if not nm and acct_key(r.get('account_nm'))[0]: nm = r.get('account_nm')   # 표준 계정 ID가 없으면 계정명으로
                if not nm: continue
                add.append(dict(r, account_nm=nm, corp_code=corp, fs_div=fs, sj_div='IS'))
            tmp = {}; parse_multi(add, y, q, tmp)
            got = ((tmp.get(corp) or {}).get((y, q)) or {}).get(fs) or {}
            tgt = store.setdefault(corp, {}).setdefault((y, q), {}).setdefault(fs, {})
            for k, v in got.items():
                if k not in tgt: tgt[k] = v; FILL.setdefault(code, []).append('%dQ%02d %s' % (q, y % 100, k))
    out = {}
    for code, corp in corp_of.items():
        s = series(store.get(corp) or {}, ps)
        of = (olds.get(code) or {}).get('fin')
        if of: of = dict(of, ql=OLD_LAB.get('ql') or [], ay=OLD_LAB.get('ay') or [], fq=list(of.get('fq') or ''), fa=list(of.get('fa') or ''))
        out[code] = merge_series(s, of)
        # 진단: 매출·영업이익 중 한쪽만 잡힌 기간의 계정명, 첫 분기가 1분기가 아닌 종목의 매출 원값
        sc = store.get(corp) or {}; first = next((i for i, v in enumerate(s['rq']) if v is not None or s['oq'][i] is not None), None)
        if first is not None:
            for i in range(first, len(ps)):
                if (s['rq'][i] is None) != (s['oq'][i] is None) and len(MISS) < 60:
                    y, q = ps[i]; MISS.setdefault(code, {})[s['ql'][i]] = {fs: '|'.join(NAMES.get((corp, y, q, fs)) or [])[:160] for fs in ('CFS', 'OFS') if NAMES.get((corp, y, q, fs))}
            if first > 0 and ps[first][1] != 1:
                y, q = ps[first]; MISS.setdefault(code, {})['first ' + s['ql'][first]] = {fs: RAW.get(corp, {}).get((y, q, fs)) for fs in ('CFS', 'OFS') if RAW.get(corp, {}).get((y, q, fs))}
    log('실적: 기간 %d개 × 묶음 %d · 실패 %d · 회사 %d' % (len(ps), (len(corps) + CHUNK - 1) // CHUNK, failed, len(store)))
    return out, failed, ps

# ───────── ②③ 이력(주요사항보고서·거래소 공시)
CATS = [   # (분류, 제목 패턴)
    ('fund', r'전환사채권발행결정|신주인수권부사채권발행결정|교환사채권발행결정|유상증자결정|유무상증자결정|조건부자본증권발행결정'),
    ('cap', r'무상증자결정|감자결정|주식분할결정|주식병합결정'),
    ('ma', r'타법인주식및출자증권양수결정|타법인주식및출자증권양도결정|회사합병결정|회사분할결정|회사분할합병결정|영업양수결정|영업양도결정|주식교환.{0,2}이전결정|유형자산양수결정|유형자산양도결정|자산양수도|주권관련사채권양수결정|주권관련사채권양도결정'),
    ('tstk', r'자기주식취득결정|자기주식처분결정|자기주식취득신탁계약|자기주식소각'),
    ('risk', r'소송등의제기|부도발생|영업정지|회생절차|해산사유|채권은행|파산'),
]
I_PAT = [   # 거래소 공시 제목
    ('ctrl', r'최대주주변경(?!을수반하는주식담보)|최대주주의변경|경영권'),
    ('risk', r'횡령|배임|불성실공시|관리종목|상장폐지|실질심사|회계처리기준위반|감사의견|소송등의제기|벌금|과징금|제재'),
]
DETAIL = {   # 제목 → 구조화 API
    '전환사채권발행결정': 'cvbdIsDecsn', '신주인수권부사채권발행결정': 'bdwtIsDecsn', '교환사채권발행결정': 'exbdIsDecsn', '유상증자결정': 'piicDecsn', '유무상증자결정': 'pifricDecsn',
    '타법인주식및출자증권양수결정': 'otcprStkInvscrInhDecsn', '타법인주식및출자증권양도결정': 'otcprStkInvscrTrfDecsn', '회사합병결정': 'cmpMgDecsn', '회사분할결정': 'cmpDvDecsn',
    '회사분할합병결정': 'cmpDvmgDecsn', '영업양수결정': 'bsnInhDecsn', '영업양도결정': 'bsnTrfDecsn', '유형자산양수결정': 'tgastInhDecsn', '유형자산양도결정': 'tgastTrfDecsn',
}
WHO = ('iscmp_cmpnm', 'mgptncmp_cmpnm', 'dlptn_cmpnm', 'dvfcmp_cmpnm', 'extr_tgcmp_cmpnm', 'ast_nm', 'inh_bsn', 'trf_bsn')
AMT = ('bd_fta', 'inhdtl_inhprc', 'trfdtl_trfprc', 'inh_prc', 'trf_prc')
WHY = ('inh_pp', 'trf_pp', 'mg_pp', 'dv_pp', 'fdpp_pp')
PCT = ('atinh_eqrt', 'attrf_eqrt')
def _clean(s): return re.sub(r'\s+', ' ', str(s or '')).strip()
def inner(nm):
    """'[기재정정]주요사항보고서(유상증자결정)' → ('유상증자결정', True)"""
    nm = re.sub(r'\s+', '', nm or ''); fix = nm.startswith('[')
    nm = re.sub(r'^(\[[^\]]*\])+', '', nm)
    m = re.match(r'주요사항보고서\((.+)\)$', nm)
    return (m.group(1) if m else nm), fix
def list_all(corp, ty, bgn, maxp):
    rows = []
    for p in range(1, maxp + 1):
        j = api('list', _full=True, corp_code=corp, bgn_de=bgn, end_de=TODAY.strftime('%Y%m%d'), pblntf_ty=ty, page_count=100, page_no=p)
        rows += j.get('list') or []
        if p >= int(j.get('total_page') or 1): break
    return rows
def events(corp):
    bgn = '%d0101' % Y0; ev = []; need = set()
    for r in list_all(corp, 'B', bgn, 5):
        t, fix = inner(r.get('report_nm'))
        cat = next((c for c, p in CATS if re.search(p, t)), None)
        if not cat: continue
        e = {'d': '%s-%s-%s' % (r['rcept_dt'][:4], r['rcept_dt'][4:6], r['rcept_dt'][6:]), 'c': cat, 'k': t, 'rc': r.get('rcept_no')}
        if fix: e['fix'] = 1
        ev.append(e)
        if t in DETAIL: need.add(DETAIL[t])
    more = False
    rows_i = list_all(corp, 'I', bgn, 6)
    if len(rows_i) >= 600: more = True
    for r in rows_i:
        nm = re.sub(r'\s+', '', r.get('report_nm') or ''); fix = nm.startswith('['); t = re.sub(r'^(\[[^\]]*\])+', '', nm)
        cat = next((c for c, p in I_PAT if re.search(p, t)), None)
        if not cat: continue
        e = {'d': '%s-%s-%s' % (r['rcept_dt'][:4], r['rcept_dt'][4:6], r['rcept_dt'][6:]), 'c': cat, 'k': t[:60], 'rc': r.get('rcept_no')}
        if fix: e['fix'] = 1
        ev.append(e)
    det = {}; bykind = {}
    for nm in sorted(need):
        for x in api(nm, corp_code=corp, bgn_de='%d0101' % (Y0 - 2), end_de=TODAY.strftime('%Y%m%d')):
            if nm not in KEYS: KEYS[nm] = sorted(k for k, v in x.items() if _clean(v) not in ('', '-'))[:60]
            d = {}
            who = next((_clean(x.get(k)) for k in WHO if _clean(x.get(k)) not in ('', '-')), None)
            if who: d['who'] = who[:40]
            a = next((tonum(x.get(k)) for k in AMT if tonum(x.get(k))), None)
            if nm in ('piicDecsn', 'pifricDecsn'):
                a = sum(tonum(x.get(f)) or 0 for f in ('fdpp_fclt', 'fdpp_bsninh', 'fdpp_op', 'fdpp_dtrp', 'fdpp_ocsa', 'fdpp_etc')) or None
                if x.get('ic_mthn'): d['how'] = _clean(x.get('ic_mthn'))[:20]
            if a: d['amt'] = round(a / EOK, 1)
            why = next((_clean(x.get(k)) for k in WHY if _clean(x.get(k)) not in ('', '-')), None)
            if why: d['why'] = why[:50]
            pct = next((tonum(x.get(k)) for k in PCT if tonum(x.get(k))), None)
            if pct: d['pct'] = pct
            prc = tonum(x.get('cv_prc') or x.get('ex_prc'))
            if prc: d['prc'] = prc
            if d: det[x.get('rcept_no')] = d; bykind.setdefault(nm, []).append((x.get('rcept_no') or '', d))
    for e in ev:
        if e['rc'] in det: e.update(det[e['rc']]); continue
        rows = bykind.get(DETAIL.get(e['k']) or '') or []      # 정정 공시는 접수번호가 달라 직접 맞지 않는다 → 같은 종류 중 날짜가 가장 가까운(400일 이내) 공시의 내용을 붙인다
        if rows and e.get('rc'):
            try:
                ed = datetime.date(int(e['rc'][:4]), int(e['rc'][4:6]), int(e['rc'][6:8]))
                best = min(rows, key=lambda r: abs((datetime.date(int(r[0][:4]), int(r[0][4:6]), int(r[0][6:8])) - ed).days))
                if abs((datetime.date(int(best[0][:4]), int(best[0][4:6]), int(best[0][6:8])) - ed).days) <= 400:
                    e.update(best[1]); e['dref'] = best[0]
            except Exception: pass
    ev.sort(key=lambda e: e['rc'] or '', reverse=True)
    return ev, more

def main():
    sp = json.load(open('public/data/semipeer.json', encoding='utf-8'))
    names = {c: v.get('n') for c, v in (sp.get('co') or {}).items()}; corpmap = dict(sp.get('corpmap') or {})
    try: old = json.load(open(OUT, encoding='utf-8'))
    except Exception: old = {}
    olds = old.get('co') or {}
    OLD_LAB.update({'ql': old.get('ql') or [], 'ay': old.get('ay') or []}); LAB.update(OLD_LAB)
    if old.get('fv') == FV: TRIED.update(old.get('tried') or {}); FILL.update(old.get('fill') or {})
    if old.get('fv') != FV:                       # 계산 규칙이 바뀌면 예전 실적 값으로 빈칸을 메우지 않는다
        for c in olds: olds[c].pop('fin', None); olds[c].pop('fin_at', None)
    codes = [c for c in names if (not ONLY or c in ONLY) and corpmap.get(c)]
    miss = [c for c in names if not corpmap.get(c)]
    if miss: log('고유번호 없음(건너뜀): %s' % ','.join(miss))
    if KEY:   # 러너에 따라 OpenDART가 응답하지 않는 경우가 있어 먼저 한 번 확인
        ok = False
        for i in range(2):
            try:
                json.loads(fetch('%s/list.json?%s' % (BASE, urllib.parse.urlencode(dict(crtfc_key=KEY, corp_code='00126380', bgn_de=(TODAY - datetime.timedelta(days=5)).strftime('%Y%m%d'), end_de=TODAY.strftime('%Y%m%d'), page_count=1))), 20, 1).decode('utf-8')); ok = True; break
            except Exception as e: log('DART 연결 점검 실패 %d회 %r' % (i + 1, str(e)[:60])); time.sleep(8)
        if not ok: STAT['limit'] = True; log('이 러너에서는 OpenDART에 연결되지 않음 → 다음 시도에서 이어감')
    else: STAT['limit'] = True; log('DART 키 없음')
    co = {c: dict(olds.get(c) or {}) for c in codes}
    for c in codes: co[c]['n'] = names[c] or co[c].get('n') or c
    # ① 실적
    fin_failed = None; ps = periods()
    if not STAT['limit']:
        fin, fin_failed, ps = collect_fin({c: corpmap[c] for c in codes}, olds)
        for c in codes:
            f = fin[c]; LAB['ql'] = f.pop('ql'); LAB['ay'] = f.pop('ay')
            if not f.get('drop'): f.pop('drop', None)
            f['fq'] = ''.join(x or '-' for x in f['fq']); f['fa'] = ''.join(x or '-' for x in f['fa'])
            co[c]['fin'] = f
        if fin_failed == 0:
            for c in codes: co[c]['fin_at'] = NOW.strftime('%Y-%m-%d')
    # ②③ 이력 — 없거나 오래된 종목부터
    cut = (TODAY - datetime.timedelta(days=EV_DAYS)).isoformat()
    todo = sorted([c for c in codes if (co[c].get('ev_at') or '') < cut or co[c].get('ev_v') != VER], key=lambda c: co[c].get('ev_at') or '')
    n_ev = 0
    for c in todo:
        if STAT['limit'] or left() < 90: break
        try:
            ev, more = events(corpmap[c])
            co[c]['ev'] = ev; co[c]['ev_at'] = NOW.strftime('%Y-%m-%d'); co[c]['ev_v'] = VER
            if more: co[c]['ev_more'] = 1
            else: co[c].pop('ev_more', None)
            n_ev += 1
        except DartFail: pass
        except Exception as e: STAT['err'] += 1; log('이력 실패 %s %r' % (c, str(e)[:120]))
    rest = [c for c in codes if (co[c].get('ev_at') or '') < cut or co[c].get('ev_v') != VER]
    fin_ok = sum(1 for c in codes if any(v is not None for v in ((co[c].get('fin') or {}).get('rq') or [])))
    done = (fin_failed == 0) and not rest
    ly, lq = latest_quarter()
    res = {'v': VER, 'fv': FV, 'updated': NOW.strftime('%Y-%m-%d %H:%M'), 'asof': '%dQ%02d' % (lq, ly % 100), 'y0': Y0, 'n': len(codes), 'fin_ok': fin_ok,
           'ql': LAB.get('ql') or [], 'ay': LAB.get('ay') or [], 'fin_failed': fin_failed, 'ev_rest': len(rest), 'done': bool(done), 'stat': STAT, 'miss': MISS, 'fill': FILL, 'tried': TRIED, 'debug': DEBUG[-40:], 'co': co}
    os.makedirs(os.path.dirname(OUT) or '.', exist_ok=True)
    json.dump(res, open(OUT, 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'))
    log('완료: 종목 %d · 실적 있는 종목 %d · 이번 실행 이력 %d · 남은 이력 %d · DART %d콜 · 실패 %d · %.0f초' % (len(codes), fin_ok, n_ev, len(rest), STAT['dart'], STAT['err'], time.time() - T0))
    gh = os.environ.get('GITHUB_OUTPUT')
    if gh: open(gh, 'a').write('done=%s\n' % ('1' if done else '0'))

if __name__ == '__main__':
    main()
