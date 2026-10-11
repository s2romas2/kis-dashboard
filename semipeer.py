#!/usr/bin/env python3
# 반도체 peer 상대밸류 — "peer보다 싼데 이익 체력은 같거나 더 좋은 기업" 찾기
#   peer 정의 : public/data/semipeer_def.json (쌍별 5기준 점수·근거 인용, tools/semipeer/merge_def.py가 생성)
#               A·B등급 쌍만 저밸류 판정에 쓰고 C등급은 참고용으로만 계산한다.
#   재무(확인값): OpenDART — 최근 4분기 합산(TTM) 매출·영업이익·순이익·자본
#               ① 다중회사 주요계정(fnlttMultiAcnt)   → 매출·영업이익·당기순이익·자본총계
#               ② 단일회사 전체재무제표(fnlttSinglAcntAll, 연결만) → 지배주주 순이익·지배주주 자본(비지배지분 제거)
#               TTM = 올해 누적 + 전년 연간 − 전년 동기 누적 (EPS 절대값은 기업 간 비교 불가 → 쓰지 않음)
#   시세        : stockvals.json(KIS 일일 수집) 시총·현재가.  우선주 상장사는 우선주 시총을 더해 보정
#   선행(증권사 추정): peg.json(소부장 맵) / 그 밖은 네이버 컨센서스(FnGuide)
#   국면·분기 추이: hege.json (투자의 定石 헤게모니 4국면, 최근 8분기 매출·영업이익)
#   공정 구분   : semipeer_def.json의 stage(전공정·후공정·전후·공통 인프라·칩 제조·설계·모듈유통)
#   표시 방식   : 합산 점수 없이 "사실 꼬리표"만 — 대표는 peer 대비 저PER/비슷/고PER, 그 밖에 PBR·PSR·ROE·영업이익률·성장률·ROA·부채비율을
#                 각각 peer(A·B등급) 중앙값과 비교해 낮음/비슷/높음으로 표시한다. 판단은 사용자가 한다.
#   기준(basis) 우선순위: TTM = DART 최근 4분기(확인값) > TTMN = 네이버(FnGuide) 최근 4분기 주당순이익·주당순자산(DART 수집 전 임시·교차확인용)
#                        > FY0 = KIS 전년 확정 실적. 쌍 비교는 두 기업이 함께 가진 가장 좋은 기준으로 맞춘다.
#   DART 고유번호 파일(corpCode.xml)이 점검 중일 때를 대비해 tools/semipeer/dartcorp.json(종목코드→고유번호)을 시드로 쓴다.
# 필요 시크릿: DART_API_KEY(권장)   결과: public/data/semipeer.json
import os, sys, json, time, re, io, zipfile, datetime, urllib.request, ssl, statistics
import xml.etree.ElementTree as ET

KEY = os.environ.get('DART_API_KEY', '')
DD = os.environ.get('DATA_DIR', 'public/data')
OUT = os.environ.get('OUT', os.path.join(DD, 'semipeer.json'))
OFFLINE = os.environ.get('OFFLINE', '') == '1'          # 네트워크 호출 없이 기존 파일만으로 계산(로컬 검증용)
REFRESH = os.environ.get('REFRESH', '') == '1'          # 재무 캐시 강제 갱신
FIN_TTL_DAYS = int(os.environ.get('FIN_TTL_DAYS', '6'))
CHUNK = int(os.environ.get('CHUNK', '50'))
UA = {'User-Agent': 'Mozilla/5.0'}
CTX = ssl.create_default_context(); CTX.check_hostname = False; CTX.verify_mode = ssl.CERT_NONE
KST = datetime.timezone(datetime.timedelta(hours=9)); NOW = datetime.datetime.now(KST); TODAY = NOW.date()
EOK = 1e8
FIN_VER = 2      # 재무 캐시 형식 버전(2: 자산총계·부채총계 추가) — 바뀌면 다음 실행에서 DART를 다시 받는다
SEED_CORP = os.environ.get('SEED_CORP', 'tools/semipeer/dartcorp.json')
DEBUG = []
# 우선주가 따로 상장된 기업: 보통주 시총만 쓰면 PER·PBR이 낮게 나오므로 우선주 시총을 더한다
PREF = {'005930': ['005935'], '009150': ['009155'], '006400': ['006405'], '007810': ['007815'], '353200': ['35320K']}

def log(s): DEBUG.append(str(s)[:300]); print(s, file=sys.stderr, flush=True)
def fetch(url, timeout=60, tries=3):
    err = None
    for i in range(tries):
        try:
            return urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout, context=CTX).read()
        except Exception as e:
            err = e; time.sleep(2 * (i + 1))
    log('fetch 실패 %s %r' % (re.sub(r'crtfc_key=[^&]+', 'crtfc_key=***', url)[:110], err)); return b''
def jget(url, **kw):
    try: return json.loads(fetch(url, **kw).decode('utf-8'))
    except Exception: return {}
def tonum(s):
    try:
        s = str(s).replace(',', '').strip()
        if s in ('', '-', 'None'): return None
        return float(s)
    except Exception: return None
def load(name, default=None):
    try: return json.load(open(os.path.join(DD, name), encoding='utf-8'))
    except Exception as e:
        log('%s 로드 실패 %r' % (name, e)); return default
def rnd(v, n=2): return None if v is None else round(v, n)
def div(a, b): return None if (a is None or b is None or b == 0) else a / b

# ───────── 성장률(적자·흑전 처리: 흑자전환 = +500% 캡, 적자전환·확대 = −200% — hege.py와 같은 규칙)
def growth(cur, prev):
    if cur is None or prev is None: return None
    if prev == 0: return 500.0 if cur > 0 else (-200.0 if cur < 0 else None)
    if prev > 0 and cur < 0: return -200.0
    if prev < 0 and cur < 0: return -200.0 if cur < prev else min(500.0, (cur - prev) / abs(prev) * 100)
    if prev < 0 and cur >= 0: return 500.0
    return max(-200.0, min(500.0, (cur - prev) / abs(prev) * 100))

# ───────── DART
REPRT = {1: '11013', 2: '11012', 3: '11014', 4: '11011'}
def latest_quarter(today=None):
    """공시 마감 기준으로 나와 있을 최신 분기 (연, 분기)"""
    t = today or TODAY; y, md = t.year, (t.month, t.day)
    if md >= (11, 14): return (y, 3)
    if md >= (8, 14): return (y, 2)
    if md >= (5, 15): return (y, 1)
    if md >= (3, 31): return (y - 1, 4)
    return (y - 1, 3)
def reports_for(y, q):
    """TTM·전년 TTM 계산에 필요한 보고서: 올해 누적, 전년 동기, 전전년 동기, 전년 연간, 전전년 연간"""
    if q == 4: return [(y, 4), (y - 1, 4)]
    return [(y, q), (y - 1, q), (y - 2, q), (y - 1, 4), (y - 2, 4)]

def dart_corpcodes():
    b = fetch('https://opendart.fss.or.kr/api/corpCode.xml?crtfc_key=' + KEY, timeout=90)
    if not b: return {}
    try:
        z = zipfile.ZipFile(io.BytesIO(b)); xml = z.read(z.namelist()[0])
    except Exception as e:
        log('corpCode zip 실패 %r %s' % (e, b[:120])); return {}
    m = {}
    for el in ET.fromstring(xml).iter('list'):
        sc = (el.findtext('stock_code') or '').strip()
        if re.fullmatch(r'[0-9A-Z]{6}', sc): m[sc] = el.findtext('corp_code')
    log('DART 고유번호 %d개' % len(m)); return m

REV_PRI = {'매출액': 0, '수익(매출액)': 1, '매출': 2, '영업수익': 3, '순영업수익': 4, '매출및지분법손익': 5}
def acct_key(nm, sj):
    """주요계정 이름 → (키, 우선순위). 낮을수록 우선."""
    nm = (nm or '').replace(' ', '')
    if sj == 'BS':
        return {'자본총계': ('eq', 0), '자산총계': ('as', 0), '부채총계': ('li', 0)}.get(nm, (None, 9))
    if nm in REV_PRI: return ('rev', REV_PRI[nm])
    if nm.startswith('매출액') or nm.startswith('수익(매출'): return ('rev', 6)
    if nm in ('영업이익', '영업이익(손실)'): return ('op', 0)
    if nm.startswith('영업이익(') and '률' not in nm: return ('op', 1)
    if nm in ('당기순이익', '당기순이익(손실)'): return ('ni', 0)
    if nm in ('분기순이익', '분기순이익(손실)', '반기순이익', '반기순이익(손실)'): return ('ni', 1)
    if re.fullmatch(r'(연결)?(당기|분기|반기)순(이익|손익)(\(손실\))?', nm): return ('ni', 2)
    return (None, 9)

def parse_multi(rows, year, q, store):
    """fnlttMultiAcnt 응답 rows → store[corp][(year,q)][fs][key] = {'cum': 누적(손익)/기말(자본), 'pri'}"""
    for r in rows or []:
        sj = r.get('sj_div') or ''; fs = r.get('fs_div') or 'OFS'; corp = r.get('corp_code')
        key, pri = acct_key(r.get('account_nm'), sj)
        if key is None or not corp: continue
        amt = tonum(r.get('thstrm_amount')); add = tonum(r.get('thstrm_add_amount'))
        if key in ('eq', 'as', 'li'): cum = amt
        elif q == 4: cum = amt
        else: cum = add if add is not None else amt          # 분기·반기보고서 손익: 누적(add) 우선 (1분기는 3개월 = 누적)
        if cum is None: continue
        d = store.setdefault(corp, {}).setdefault((year, q), {'CFS': {}, 'OFS': {}}).setdefault(fs, {})
        if key in d and d[key]['pri'] <= pri: continue
        d[key] = {'cum': cum, 'pri': pri}

def dart_multi(corps, year, q, store):
    url = ('https://opendart.fss.or.kr/api/fnlttMultiAcnt.json?crtfc_key=%s&corp_code=%s&bsns_year=%d&reprt_code=%s'
           % (KEY, ','.join(corps), year, REPRT[q]))
    j = jget(url); st = j.get('status')
    if st == '020': log('DART 사용 한도 초과'); return 'quota'
    if st not in ('000', '013'): log('DART multi %d/%dQ status=%s %s' % (year, q, st, j.get('message'))); return 'err'
    parse_multi(j.get('list'), year, q, store); return 'ok'

def ttm_from(store_corp, y, q):
    """연결 우선(없으면 별도)으로 TTM·전년 TTM·자본을 계산. 반환 dict(단위 억) 또는 None"""
    for fs in ('CFS', 'OFS'):
        def g(yy, qq, k):
            v = (((store_corp.get((yy, qq)) or {}).get(fs) or {}).get(k) or {}).get('cum')
            return v
        out = {'fs': fs}
        ok = 0
        for k in ('rev', 'op', 'ni'):
            if q == 4:
                cur, prev = g(y, 4, k), g(y - 1, 4, k)
            else:
                a, b, c = g(y, q, k), g(y - 1, 4, k), g(y - 1, q, k)
                cur = None if None in (a, b, c) else a + b - c
                a2, b2, c2 = c, g(y - 2, 4, k), g(y - 2, q, k)
                prev = None if None in (a2, b2, c2) else a2 + b2 - c2
            out[k] = None if cur is None else cur / EOK
            out[k + '_prev'] = None if prev is None else prev / EOK
            if cur is not None: ok += 1
        eq = g(y, q, 'eq'); eq0 = g(y - 1, q, 'eq')
        out['eq'] = None if eq is None else eq / EOK
        out['eq_prev'] = None if eq0 is None else eq0 / EOK
        for k in ('as', 'li'):                                   # 자산총계·부채총계(기말) — ROA·부채비율용
            v = g(y, q, k); out[k] = None if v is None else v / EOK
        if ok >= 2 and out['rev'] is not None and out['rev'] > 0:
            return out
    return None

# 전체재무제표에서 지배주주 몫만 뽑는다(account_id는 ifrs-full_… / ifrs-full:… 두 표기 모두 허용)
def _aid(a): return (a or '').replace(':', '_').strip()
NIP_IDS = {'ifrs-full_ProfitLossAttributableToOwnersOfParent'}
EQP_IDS = {'ifrs-full_EquityAttributableToOwnersOfParent'}
NIP_PAT = re.compile(r'지배(기업|회사|주주)')
EQP_PAT = re.compile(r'^지배(기업|회사|주주).*(지분|자본)')
def parse_full(rows, q):
    """fnlttSinglAcntAll rows → {'ni_p': 누적 지배주주 순이익, 'eq_p': 지배주주 자본} (원)"""
    out = {}
    for r in rows or []:
        sj = r.get('sj_div') or ''; aid = _aid(r.get('account_id')); nm = (r.get('account_nm') or '').replace(' ', '')
        if sj in ('IS', 'CIS'):
            if 'ni_p' in out or 'ComprehensiveIncome' in aid: continue
            add = tonum(r.get('thstrm_add_amount')); amt = tonum(r.get('thstrm_amount'))
            v = amt if q == 4 else (add if add is not None else amt)
            if v is None: continue
            if aid in NIP_IDS: out['ni_p'] = v
            elif ('비지배' not in nm and '포괄' not in nm and '주당' not in nm and NIP_PAT.search(nm)
                  and any(k in nm for k in ('순이익', '순손익', '귀속', '소유주', '지분'))):
                out['ni_p'] = v
        elif sj == 'BS':
            if 'eq_p' in out: continue
            v = tonum(r.get('thstrm_amount'))
            if v is None: continue
            if aid in EQP_IDS or ('비지배' not in nm and EQP_PAT.search(nm)): out['eq_p'] = v
    return out
def dart_full(corp, year, q):
    j = jget('https://opendart.fss.or.kr/api/fnlttSinglAcntAll.json?crtfc_key=%s&corp_code=%s&bsns_year=%d&reprt_code=%s&fs_div=CFS'
             % (KEY, corp, year, REPRT[q]))
    st = j.get('status')
    if st == '020': return 'quota'
    if st != '000': return None
    return parse_full(j.get('list'), q)

def collect_fin(codes, prev_fin, prev_corp=None):
    """DART에서 재무를 모아 {code: fin} 반환. 실패한 종목은 이전 캐시 유지."""
    y, q = latest_quarter()
    corpmap = {}
    try: corpmap.update(json.load(open(SEED_CORP, encoding='utf-8')))
    except Exception as e: log('고유번호 시드 없음 %r' % e)
    corpmap.update(prev_corp or {})
    fresh = dart_corpcodes()
    if fresh: corpmap.update({c: fresh[c] for c in codes if c in fresh})
    else: log('corpCode.xml 실패(점검 등) — 시드·캐시 고유번호 %d개로 진행' % len(corpmap))
    if not corpmap: log('DART 고유번호 없음 — 재무 캐시 유지'); return prev_fin, None, {}
    todo = [c for c in codes if c in corpmap]
    log('DART 대상 %d/%d종목, 기준 분기 %d년 %dQ' % (len(todo), len(codes), y, q))
    store = {}; calls = 0; quota = False; T0 = time.time()
    for i in range(0, len(todo), CHUNK):
        batch = [corpmap[c] for c in todo[i:i + CHUNK]]
        for (yy, qq) in reports_for(y, q):
            r = dart_multi(batch, yy, qq, store); calls += 1
            if r == 'quota': quota = True; break
            time.sleep(0.2)
        if quota: break
    fin = dict(prev_fin); n_ok = 0; n_p = 0
    asof = '%dQ%02d' % (q, y % 100)
    for c in todo:
        t = ttm_from(store.get(corpmap[c], {}), y, q)
        if not t: continue
        t['asof'] = asof; t['src'] = 'DART'
        pf = prev_fin.get(c) or {}                              # ② 결과는 같은 분기면 다시 받지 않는다(종목당 3콜 절약)
        if pf.get('asof') == asof and pf.get('fs') == t['fs'] and (pf.get('b') or 'ni_p' in pf):
            for k in ('ni_p', 'eq_p'):
                if k in pf: t[k] = pf[k]
            t['b'] = 1
        fin[c] = t; n_ok += 1
    log('① 주요계정 TTM 산출 %d종목 (호출 %d, %ds)' % (n_ok, calls, time.time() - T0))
    # ② 지배주주 몫 — 연결 재무제표를 쓰는 종목만
    if not quota:
        for c in todo:
            t = fin.get(c)
            if not t or t.get('asof') != asof or t.get('fs') != 'CFS': continue
            if t.get('b'):
                if 'ni_p' in t: n_p += 1
                continue
            corp = corpmap[c]; got = {}
            for (yy, qq) in ([(y, 4)] if q == 4 else [(y, q), (y - 1, 4), (y - 1, q)]):
                r = dart_full(corp, yy, qq); calls += 1; time.sleep(0.2)
                if r == 'quota': quota = True; break
                if r is None: got = None; break
                got[(yy, qq)] = r
            if quota: log('DART 한도 초과 — 지배주주 몫 수집 중단'); break
            t['b'] = 1
            if not got: continue
            if q == 4: nip = got[(y, 4)].get('ni_p')
            else:
                a, b, d = got[(y, q)].get('ni_p'), got[(y - 1, 4)].get('ni_p'), got[(y - 1, q)].get('ni_p')
                nip = None if None in (a, b, d) else a + b - d
            eqp = got[(y, q)].get('eq_p')
            # 지배주주 몫이 전체보다 터무니없이 다르면(계정 오인) 버린다
            if nip is not None and t.get('ni') not in (None, 0):
                ratio = (nip / EOK) / t['ni']
                if 0.2 <= ratio <= 1.25: t['ni_p'] = nip / EOK
            if eqp is not None and t.get('eq') not in (None, 0):
                ratio = (eqp / EOK) / t['eq']
                if 0.2 <= ratio <= 1.02: t['eq_p'] = eqp / EOK
            if 'ni_p' in t: n_p += 1
        log('② 지배주주 순이익 산출 %d종목 (누적 호출 %d, %ds)' % (n_p, calls, time.time() - T0))
    if n_ok < max(10, len(todo) // 3):
        log('DART 산출 종목이 너무 적음(%d) — 이전 재무 캐시 유지' % n_ok); return prev_fin, None, corpmap
    return fin, {'asof': asof, 'calls': calls, 'ok': n_ok, 'ctrl': n_p, 'quota': quota, 'date': TODAY.isoformat(), 'ver': FIN_VER}, {c: corpmap[c] for c in codes if c in corpmap}

# ───────── 네이버(증권사 추정·우선주 시총) — 선행 지표는 "증권사 추정" 태그로만 표시
def naver_consensus(code):
    j = jget('https://m.stock.naver.com/api/stock/%s/finance/annual' % code, timeout=20, tries=2)
    fi = (j or {}).get('financeInfo') or {}
    tl = fi.get('trTitleList') or []; rows = fi.get('rowList') or []
    if not tl or not rows: return {}
    def row(title):
        for r in rows:
            if (r.get('title') or '').replace(' ', '') == title: return r.get('columns') or {}
        return {}
    op, ni, nic = row('영업이익'), row('당기순이익'), row('지배주주순이익')
    fy = {}
    for t in tl:
        k = t.get('key') or ''; m = re.match(r'(20\d\d)', k)
        if not m: continue
        v = lambda col: tonum((col.get(k) or {}).get('value'))
        n = v(nic); n = n if n is not None else v(ni)
        fy[m.group(1)] = {'op': v(op), 'ni': n, 'est': (t.get('isConsensus') == 'Y')}
    return fy
def cap_str(s):
    """'2조 4,560억' → 24560.0(억)"""
    if not s: return None
    s = str(s).replace(',', '').replace(' ', ''); m = re.fullmatch(r'(?:(\d+)조)?(?:(\d+)억)?', s)
    if not m or not (m.group(1) or m.group(2)): return None
    return float(m.group(1) or 0) * 10000 + float(m.group(2) or 0)
def _nnum(v):
    return tonum(re.sub(r'[배원%]', '', str(v or '')).replace('N/A', ''))
def naver_basic(code):
    """네이버 종목 요약: 최근 4분기 주당순이익 기준 PER·EPS, 최근 분기 BPS 기준 PBR (FnGuide)"""
    j = jget('https://m.stock.naver.com/api/stock/%s/integration' % code, timeout=20, tries=2)
    o = {}
    for t in j.get('totalInfos') or []:
        c = t.get('code')
        if c in ('per', 'pbr', 'eps', 'bps'): o[c] = _nnum(t.get('value'))
    return o if any(v is not None for v in o.values()) else {}
def naver_cap(code):
    j = jget('https://m.stock.naver.com/api/stock/%s/integration' % code, timeout=20, tries=2)
    for t in j.get('totalInfos') or []:
        if t.get('key') in ('시총', '시가총액') or t.get('code') == 'marketValue': return cap_str(t.get('value'))
    return None
def fwd_from_fy(fy, cap):
    """컨센 fy dict → 12M 선행 PER·2년 순이익 CAGR. 단위 억."""
    if not fy or not cap: return {}
    y0, y1, y2 = str(TODAY.year - 1), str(TODAY.year), str(TODAY.year + 1)
    a0, a1, a2 = fy.get(y0) or {}, fy.get(y1) or {}, fy.get(y2) or {}
    if not a1.get('est') or a1.get('ni') is None: return {}
    ni0, ni1, ni2 = a0.get('ni'), a1.get('ni'), a2.get('ni') if a2.get('est') else None
    rem = (datetime.date(TODAY.year, 12, 31) - TODAY).days / 365.0
    nif = ni1 * rem + ni2 * (1 - rem) if ni2 is not None else ni1
    o = {'src': '네이버 컨센서스(FnGuide)', 'ni0': ni0, 'ni1': ni1, 'ni2': ni2}
    o['per_f12'] = rnd(cap / nif) if nif and nif > 0 else None
    o['g1'] = rnd((ni1 / ni0 - 1) * 100, 1) if (ni0 and ni0 > 0 and ni1 and ni1 > 0) else None
    o['cagr2'] = rnd(((ni2 / ni0) ** 0.5 - 1) * 100, 1) if (ni0 and ni0 > 0 and ni2 and ni2 > 0) else None
    return o

# ───────── peer 대비 꼬리표(사실 표시) — 합산 점수는 만들지 않는다
CHEAP = 0.9    # 멀티플·부채비율: peer의 90% 이하면 "낮음", 110% 이상이면 "높음"
DEAR = 1.1
TOL = {'roe': 1.0, 'opm': 1.0, 'roa': 1.0, 'g': 5.0}   # 이익 체력: peer와의 차이(%p)가 이 안이면 "비슷"
G_CAP = 300    # 성장률 비교 상한(%) — 흑자전환·기저효과로 부풀려진 성장률끼리는 우열을 가리지 않는다
PER_MAX = 150  # PER이 이보다 크면 이익이 너무 작은 상태 — PER 비교에서 뺀다
def tag_ratio(ratios):
    """내 값 ÷ peer 값의 중앙값으로 낮음/비슷/높음"""
    if not ratios: return None
    m = statistics.median(ratios)
    return 'low' if m <= CHEAP else 'high' if m >= DEAR else 'mid'
def tag_diff(diffs, tol):
    """내 값 − peer 값(%p)의 중앙값으로 높음/비슷/낮음"""
    if not diffs: return None
    m = statistics.median(diffs)
    return 'high' if m >= tol else 'low' if m <= -tol else 'mid'
def cmp_pair(mine, theirs):
    """한 쌍에서 지표별 (비율 또는 차이, 상대 값). mine/theirs는 같은 기준으로 맞춘 dict"""
    o = {}
    for k in ('per', 'pbr', 'psr', 'debt'):
        a, b = mine.get(k), theirs.get(k)
        if a is None or b is None or a <= 0 or b <= 0: continue
        if k == 'per' and (a > PER_MAX or b > PER_MAX): continue
        o[k] = (a / b, b)
    for k in ('roe', 'opm', 'roa'):
        a, b = mine.get(k), theirs.get(k)
        if a is None or b is None: continue
        o[k] = (a - b, b)
    gk = 'g_ni' if (mine.get('g_ni') is not None and theirs.get('g_ni') is not None) else 'g_op'
    a, b = mine.get(gk), theirs.get(gk)
    if a is not None and b is not None: o['g'] = (min(a, G_CAP) - min(b, G_CAP), b)
    return o

def main():
    DEF = load('semipeer_def.json')
    if not DEF: log('semipeer_def.json 없음'); sys.exit(1)
    sv = (load('stockvals.json', {}) or {}).get('map') or {}
    pegj = load('peg.json', {}) or {}
    peg = {r['c']: r for r in pegj.get('rows') or []}
    hegj = load('hege.json', {}) or {}
    hege = {r['c']: r for r in hegj.get('rows') or []}
    prev = load('semipeer.json', {}) or {}
    codes = sorted(DEF['co'].keys())

    # 1) 재무 캐시
    fin = prev.get('fin') or {}; fin_meta = prev.get('fin_meta') or {}; corpcache = prev.get('corpmap') or {}
    need = REFRESH or not fin_meta.get('date') or fin_meta.get('ver') != FIN_VER
    if not need:
        try: need = (TODAY - datetime.date.fromisoformat(fin_meta['date'])).days >= FIN_TTL_DAYS
        except Exception: need = True
        if fin_meta.get('asof') != '%dQ%02d' % (latest_quarter()[1], latest_quarter()[0] % 100): need = True
    if need and KEY and not OFFLINE:
        fin, meta, cm = collect_fin(codes, fin, corpcache)
        if meta: fin_meta = meta
        if cm: corpcache = cm
    elif need: log('DART 키 없음/오프라인 — 재무는 기존 캐시(%s) 또는 KIS·hege 대체값 사용' % (fin_meta.get('date') or '없음'))

    # 2) 선행(증권사 추정)·우선주 시총
    fwd = prev.get('fwd') or {}; prefcap = prev.get('prefcap') or {}; nv = prev.get('nv') or {}
    if not isinstance(nv, dict): nv = {}
    if not OFFLINE:
        n = 0
        for c in codes:
            o = naver_basic(c); time.sleep(0.1)
            if o: o['date'] = TODAY.isoformat(); nv[c] = o; n += 1
        log('네이버 요약(PER·PBR) 수집 %d종목' % n)
        n = 0
        for c in codes:
            if c in peg and peg[c].get('status') == 'ok': continue
            fy = naver_consensus(c); time.sleep(0.12)
            if fy: fwd[c] = {'fy': fy, 'date': TODAY.isoformat()}; n += 1
        log('네이버 컨센 수집 %d종목' % n)
        for c, ps in PREF.items():
            if c not in DEF['co']: continue
            tot = 0.0; ok = True
            for p in ps:
                v = naver_cap(p); time.sleep(0.12)
                if v is None: ok = False; break
                tot += v
            if ok: prefcap[c] = {'cap': tot, 'date': TODAY.isoformat()}
        log('우선주 시총 %s' % {k: v['cap'] for k, v in prefcap.items()})

    # 3) 종목별 지표
    GMAP = {g['id']: g for g in DEF['groups']}
    co = {}
    for c in codes:
        d = DEF['co'][c]; v = sv.get(c); f = fin.get(c) or {}; h = hege.get(c) or {}; pg = peg.get(c) or {}
        g0 = GMAP.get((d.get('gids') or [None])[0]) or {}
        r = {'n': d['n'], 'pure': d.get('pure'), 'gids': d.get('gids') or [], 'top': g0.get('top'), 'seg': g0.get('seg'), 'map': bool(d.get('map')), 'stage': d.get('stage') or 'etc', 'procs': d.get('procs') or [], 'flags': []}
        if not v or not v[2]:
            r['flags'].append('시세 없음'); co[c] = r; continue
        kpbr, kper, cap0, px = v[0], v[1], v[2], v[3]
        kroe = v[4] if len(v) > 4 else None
        cap = cap0
        if c in PREF:
            if c in prefcap: cap = cap0 + prefcap[c]['cap']; r['pref'] = rnd(prefcap[c]['cap'], 0)
            else: r['flags'].append('우선주 시총 미반영 — PER·PBR이 실제보다 낮게 보일 수 있음')
        r.update({'px': px, 'cap': rnd(cap, 0), 'kper': kper, 'kpbr': kpbr})
        # 매출·영업이익 TTM: DART 캐시 우선, 없으면 hege(같은 DART 주요계정, 주 1회)
        rev = f.get('rev'); op = f.get('op'); rev0 = f.get('rev_prev'); op0 = f.get('op_prev'); asof = f.get('asof')
        if rev is None and h.get('rev'):
            rv, ov = h['rev'], h['op']
            if len(rv) >= 4 and all(x is not None for x in rv[-4:] + ov[-4:]):
                rev, op = sum(rv[-4:]), sum(ov[-4:]); asof = h.get('q')
                if len(rv) >= 8 and all(x is not None for x in rv[-8:-4] + ov[-8:-4]): rev0, op0 = sum(rv[-8:-4]), sum(ov[-8:-4])
        ni_tot = f.get('ni'); ni = f.get('ni_p', ni_tot); eq = f.get('eq_p', f.get('eq'))
        r['asof'] = asof; r['fs'] = f.get('fs') or h.get('fs')
        r['rev'] = rnd(rev, 0); r['op'] = rnd(op, 0)
        r['rev0'] = rnd(rev0, 0); r['op0'] = rnd(op0, 0)                 # 1년 전 같은 기간(직전 4분기 합산)
        # 분기 추이(최근 8분기 매출·영업이익, hege.json = DART 주요계정)
        if h.get('rev') and h.get('ql'):
            k = min(8, len(h['ql']), len(h['rev']), len(h['op']))
            r['ql'] = h['ql'][-k:]; r['rq'] = h['rev'][-k:]; r['oq'] = h['op'][-k:]
        r['psr'] = rnd(div(cap, rev)) if rev and rev > 0 else None
        r['por'] = rnd(div(cap, op)) if op and op > 0 else None
        r['opm'] = rnd(div(op, rev) * 100, 1) if (rev and rev > 0 and op is not None) else None
        r['g_op'] = rnd(growth(op, op0), 1); r['g_rev'] = rnd(growth(rev, rev0), 1)
        bv = {}
        if ni is not None and eq:
            r['ni'] = rnd(ni, 0); r['eq'] = rnd(eq, 0)
            r['ni_t'] = rnd(ni_tot, 0); r['ni0'] = rnd(f.get('ni_prev'), 0)   # 연결 순이익 전체(비지배 포함)와 1년 전 값
            bv['TTM'] = [rnd(cap / ni) if ni > 0 else None, rnd(cap / eq) if eq > 0 else None,
                         rnd(ni / eq * 100, 1) if eq > 0 else None]      # ROE = 최근 4분기 순이익 ÷ 기말 자본
            r['npm'] = rnd(ni / rev * 100, 1) if rev and rev > 0 else None
            r['g_ni'] = rnd(growth(ni_tot, f.get('ni_prev')), 1)
            if f.get('as') and ni_tot is not None: r['roa'] = rnd(ni_tot / f['as'] * 100, 1)        # 연결 순이익 전체 ÷ 자산총계
            if f.get('li') is not None and f.get('eq'): r['debt'] = rnd(f['li'] / f['eq'] * 100, 0)   # 부채총계 ÷ 자본총계
            if 'ni_p' in f and ni_tot: r['ctrl'] = rnd(ni / ni_tot * 100, 0)
            elif f.get('fs') == 'CFS': r['flags'].append('지배주주 몫 미확인 — 연결 순이익 전체(비지배지분 포함) 기준')
            if ni <= 0: r['flags'].append('최근 4분기 순손실 — PER 계산 불가')
        n_ = nv.get(c) or {}
        if n_.get('pbr') or n_.get('per'):
            nroe = rnd(n_['eps'] / n_['bps'] * 100, 1) if (n_.get('eps') is not None and n_.get('bps')) else None
            bv['TTMN'] = [n_['per'] if (n_.get('per') or 0) > 0 else None, n_['pbr'] if (n_.get('pbr') or 0) > 0 else None, nroe]
        bv['FY0'] = [kper if (kper and kper > 0) else None, kpbr if (kpbr and kpbr > 0) else None, kroe]
        r['basis'] = 'TTM' if 'TTM' in bv else 'TTMN' if 'TTMN' in bv else 'FY0'
        r['bv'] = bv
        r['per'], r['pbr'], r['roe'] = bv[r['basis']]
        if r['basis'] == 'TTMN':
            r['flags'].append('DART 최근 4분기 수집 전 — PER·PBR·ROE는 네이버(FnGuide)의 최근 4분기 주당순이익·주당순자산 기준')
            if r['per'] is None: r['flags'].append('PER 없음 — 최근 4분기 순손실')
        elif r['basis'] == 'FY0':
            r['flags'].append('최근 4분기 순이익 미수집 — PER·PBR·ROE는 전년 확정 실적(KIS) 기준')
            if r['per'] is None: r['flags'].append('PER 없음 — 전년 순손실이거나 KIS가 값을 주지 않음')
        elif bv.get('TTMN') and bv['TTMN'][0] and r['per']:
            dv = r['per'] / bv['TTMN'][0] - 1
            if abs(dv) > 0.2: r['flags'].append('PER 교차확인: DART 기준 %.1f배 vs 네이버(FnGuide) %.1f배 — 20%%↑ 차이(일회성 손익·주식 수 변동·지배주주 몫 확인 필요)' % (r['per'], bv['TTMN'][0]))
        # 선행(증권사 추정)
        if pg.get('status') == 'ok':
            r['fwd'] = {'per_f12': pg.get('per_f12'), 'cagr2': pg.get('cagr2'), 'g1': pg.get('g1'), 'peg': pg.get('peg2'), 'src': pg.get('src')}
        elif c in fwd:
            o = fwd_from_fy(fwd[c].get('fy'), cap)
            if o.get('per_f12'):
                gg = o.get('cagr2') if o.get('cagr2') is not None else o.get('g1')
                o['peg'] = rnd(o['per_f12'] / gg) if gg and gg > 0 else None
                r['fwd'] = {k: o.get(k) for k in ('per_f12', 'cagr2', 'g1', 'peg', 'src')}
        # 국면
        if h:
            r['ph'] = h.get('ph'); r['hq'] = h.get('q'); r['streak'] = h.get('streak')
            r['new1'] = bool(h.get('new1')); r['entry2'] = bool(h.get('entry2')); r['slow'] = bool(h.get('slow'))
            r['rg'] = h.get('rg'); r['og'] = h.get('og'); r['hist'] = h.get('hist')
        # 신뢰도 경고
        if r.get('ni') is not None and op and op > 0 and r['ni'] > 0:
            k = r['ni'] / op
            if k > 1.3: r['flags'].append('순이익이 영업이익의 %.1f배 — 영업외 이익(일회성 가능) 영향이 커 PER이 낮게 보일 수 있음. P/OP 함께 확인' % k)
            elif k < 0.5: r['flags'].append('순이익이 영업이익의 절반 미만 — 영업외 비용 영향. P/OP 함께 확인')
        if r.get('per') and r['per'] > PER_MAX: r['flags'].append('PER %d배↑ — 이익이 매우 작은 상태라 PER 비교에서 제외' % PER_MAX)
        if r.get('g_ni') is not None and r['g_ni'] >= G_CAP: r['flags'].append('순이익 증가율이 기저효과로 과장(300%↑ 또는 흑자전환) — 비교할 때 300%로 봄')
        elif r.get('g_ni') is None and r.get('g_op') is not None and r['g_op'] >= G_CAP: r['flags'].append('영업이익 증가율이 기저효과로 과장(300%↑ 또는 흑자전환) — 비교할 때 300%로 봄')
        if d.get('pure') == 'low': r['flags'].append('반도체가 전사 매출의 일부 — 전사 멀티플이 반도체 사업 가치를 그대로 반영하지 않음')
        if r.get('ctrl') is not None and r['ctrl'] < 85: r['flags'].append('비지배지분 몫 %d%% 제외(지배주주 순이익 기준)' % (100 - r['ctrl']))
        co[c] = r

    # 4) 쌍 비교 — A·B등급 peer에 대해서만 지표별 비율·차이를 모은다(C등급은 화면에서 숫자만 나란히 보여 준다)
    pairs = []; agg = {c: {'nA': 0, 'nB': 0, 'nC': 0, 'v': {}, 'pm': {}} for c in codes}
    for p in DEF['pairs']:
        a, b, g = p['a'], p['b'], p['grade']
        x, y = co.get(a) or {}, co.get(b) or {}
        bx, by = x.get('bv') or {}, y.get('bv') or {}
        bs = next((k for k in ('TTM', 'TTMN', 'FY0') if k in bx and k in by), None)
        def at(r, k):
            if not k or 'bv' not in r: return r
            v = r['bv'][k]; return dict(r, per=v[0], pbr=v[1], roe=v[2], g_ni=(r.get('g_ni') if k == 'TTM' else None))
        fx, fy_ = at(x, bs), at(y, bs)
        capr = None
        if x.get('cap') and y.get('cap'): capr = max(x['cap'], y['cap']) / min(x['cap'], y['cap'])
        pairs.append({'a': a, 'b': b, 'g': g, 'sum': p['sum'], 'gid': p['gid'], 'bs': bs, 'capr': rnd(capr, 1)})
        for me, mine, theirs in ((a, fx, fy_), (b, fy_, fx)):
            A = agg[me]; A['n' + g] += 1
            if g not in ('A', 'B') or 'cap' not in mine or 'cap' not in theirs: continue
            for k, (v, pv) in cmp_pair(mine, theirs).items():
                A['v'].setdefault(k, []).append(v); A['pm'].setdefault(k, []).append(pv)

    # 5) 종목별 꼬리표 — PER 꼬리표가 대표 표시(sig), 나머지는 독립 꼬리표
    for c in codes:
        r = co[c]; A = agg[c]
        r['nA'], r['nB'], r['nC'] = A['nA'], A['nB'], A['nC']
        if 'cap' not in r: r['sig'] = 'nodata'; continue
        if A['nA'] + A['nB'] == 0: r['sig'] = 'nopeer'; continue
        # 근거 강도: A등급 peer가 있고 peer가 둘 이상이면 3, A가 하나 있거나 B가 둘 이상이면 2, B 하나뿐이면 1
        r['conf'] = 3 if (A['nA'] >= 1 and A['nA'] + A['nB'] >= 2) else 2 if (A['nA'] >= 1 or A['nB'] >= 2) else 1
        tags = {}
        for k in ('per', 'pbr', 'psr', 'debt'):
            t = tag_ratio(A['v'].get(k))
            if t: tags[k] = t
        for k in ('roe', 'opm', 'roa', 'g'):
            t = tag_diff(A['v'].get(k), TOL[k])
            if t: tags[k] = t
        r['tags'] = tags
        r['pm'] = {k: rnd(statistics.median(v), 1 if k in ('roe', 'opm', 'roa', 'g', 'debt') else 2) for k, v in A['pm'].items() if v}
        if A['v'].get('per'): r['disc'] = rnd((statistics.median(A['v']['per']) - 1) * 100, 0)   # 쌍마다 같은 기준으로 맞춘 PER 비율의 중앙값
        loss = (r.get('op') is not None and r['op'] <= 0) or (r.get('basis') == 'TTM' and r.get('ni') is not None and r['ni'] <= 0) or r.get('per') is None
        thin = bool(r.get('per') and r['per'] > PER_MAX)
        if loss or thin: r['sig'] = 'loss'                  # 적자·이익 미미 — PER 꼬리표를 붙이지 않는다
        elif 'per' not in tags: r['sig'] = 'noper'          # peer 쪽이 적자·이익 미미라 PER을 비교할 수 없음
        else: r['sig'] = {'low': 'lowper', 'mid': 'midper', 'high': 'highper'}[tags['per']]
        # 저PER을 그대로 믿기 전에 볼 것(짧은 경고 코드 — 화면에서 문구로 풀어 쓴다)
        w = []
        gq = r.get('g_ni') if r.get('g_ni') is not None else r.get('g_op')
        if gq is not None and gq >= G_CAP: w.append('peak')                                   # 이익 급증(흑전·300%↑) — 호황 정점일 수 있음
        if r.get('ni') and r.get('op') and r['op'] > 0 and r['ni'] / r['op'] > 1.3: w.append('nonop')   # 영업외 이익 영향
        if r.get('ph') in (3, 4): w.append('ph34')                                              # 3·4국면
        if r['conf'] == 1: w.append('one')                                                      # 비교 상대가 B등급 하나뿐
        if r.get('pure') == 'low': w.append('pure')                                             # 반도체 비중 작음
        if any('교차확인' in f for f in r['flags']): w.append('xchk')                             # DART vs 네이버 PER 20%↑ 차이
        r['warn'] = w

    # 6) 그룹 중앙값(참고 — 등급과 무관하게 같은 묶음 전체)
    groups = []
    for g in DEF['groups']:
        ms = [m for m in g['members'] if m in co and 'cap' in co[m]]
        def med(k):
            vs = [co[m][k] for m in ms if co[m].get(k) is not None and co[m][k] > 0]
            return rnd(statistics.median(vs)) if len(vs) >= 2 else None
        groups.append({'id': g['id'], 'name': g['name'], 'seg': g['seg'], 'top': g.get('top'), 'n': len(ms), 'per': med('per'), 'pbr': med('pbr'), 'psr': med('psr')})

    cnt = {}
    for r in co.values(): cnt[r.get('sig')] = cnt.get(r.get('sig'), 0) + 1
    nb = sum(1 for r in co.values() if r.get('basis') == 'TTM'); nbn = sum(1 for r in co.values() if r.get('basis') == 'TTMN')
    out = {'updated': NOW.strftime('%Y-%m-%d %H:%M'), 'price_updated': (load('stockvals.json', {}) or {}).get('updated'),
           'hege_q': hegj.get('asof_quarter'), 'fin_meta': fin_meta, 'n': len(co), 'n_ttm': nb, 'n_ttmn': nbn, 'count': cnt,
           'th': {'cheap': CHEAP, 'dear': DEAR, 'tol': TOL, 'gcap': G_CAP, 'permax': PER_MAX},
           'rule': {'tag': 'A·B등급 peer와 쌍마다 비교해 (내 값 ÷ peer 값)의 중앙값이 0.9 이하면 낮음, 1.1 이상이면 높음(PER·PBR·PSR·부채비율). ROE·영업이익률·ROA는 1%p, 성장률은 5%p 넘게 차이 나면 높음/낮음',
                    'per': '대표 표시는 PER 꼬리표 하나(저PER·비슷·고PER). 최근 4분기 영업적자·순손실이거나 PER 150배 초과면 붙이지 않음. 성장률은 300% 상한으로 비교',
                    'basis': 'TTM = DART 최근 4분기 합산(확인값). TTMN = 네이버(FnGuide) 최근 4분기 주당순이익·주당순자산(DART 수집 전 임시). FY0 = KIS 전년 확정 실적'},
           'co': co, 'pairs': pairs, 'groups': groups, 'fin': fin, 'fwd': fwd, 'prefcap': prefcap, 'nv': nv, 'corpmap': corpcache, 'debug': DEBUG[-40:]}
    # 빈 결과 가드: 시세가 붙은 종목이 기존의 1/3 미만이면 덮어쓰지 않는다
    n_new = sum(1 for r in co.values() if 'cap' in r); n_old = sum(1 for r in (prev.get('co') or {}).values() if 'cap' in r)
    if n_old and n_new < n_old / 3:
        log('시세 붙은 종목 %d < 기존 %d의 1/3 — 저장 생략' % (n_new, n_old)); return
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(out, open(OUT, 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'))
    log('저장 %s 종목 %d (DART TTM %d · 네이버 TTM %d) 판정 %s' % (OUT, len(co), nb, nbn, cnt))

if __name__ == '__main__': main()
