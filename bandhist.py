# -*- coding: utf-8 -*-
"""
밸류 밴드 시계열 수집기 — 종목별 + 섹터별
    결과: public/data/band.json

왜 만드나
    peer 표는 "지금 PER 몇 배"만 보여준다. 그 배수가 이 회사 기준으로 비싼지 싼지는
    과거 분포를 봐야 안다. 그게 밴드차트다.

밴드에 쓸 수 있는 것 / 없는 것
    밴드는 "주가 = 기초체력 × 배수" 구조라야 성립한다. 따라서 **배수(multiple)** 만 밴드가 된다.
        PER = 시총 / TTM 순이익      · 흑자라야 성립
        PBR = 시총 / 자본총계         · 자본잠식이면 불가
        PSR = 시총 / TTM 매출         · 적자여도 성립 → 로봇·바이오의 유일한 선택지
    ROE 는 배수가 아니라 수익성 비율이다. ROE × BPS = EPS 이지 주가가 아니다.
    → ROE 로는 주가 밴드를 못 그린다. 대신 ① ROE 자체의 분포(펀더멘털 밴드)
       ② PBR–ROE 관계(같은 ROE 인데 PBR 이 낮으면 싸다) 로 쓴다. 둘 다 여기서 만든다.

주당 값을 쓰지 않는 이유
    EPS·BPS 를 쓰려면 과거 주식수가 필요하고, 증자·분할이 섞이면 틀린다.
    시총 기준으로 계산하면 주식수가 약분돼 사라진다. 과거 시총은
        시총(t) = 현재시총 × 수정주가(t) / 현재수정주가
    로 만든다. 수정주가가 분할·배당을 반영하므로 분할은 맞고, **대규모 증자는 오차**가 된다
    (그 경우 trust.warn 에 적는다).

밴드 선을 긋는 세 가지 방식 — 전부 저장한다
    q   분위수 10/25/50/75/90  ← 기본. 극단값 한 번에 안 흔들린다
    eq  최저~최고 균등 5분할     ← 증권사 밴드차트 관행. 비교하려면 필요하다
    sd  평균 ±1σ·±2σ           ← 분포가 정규에 가까울 때
    셋이 다르게 나오는 것 자체가 정보다. 화면에서 고르게 한다.

관측 구간이 짧으면 밴드는 '역사'가 아니다
    에이피알은 2024-02 상장인데 증권사 밴드차트는 2019 부터 선을 긋는다.
    상장 전에는 주가가 없으니 그 구간 선은 과거 배수가 아니라 산술 연장선이다.
    → 관측 개월수를 세어 trust 로 내보낸다. 36개월 미만이면 '낮음'.

환경변수
    KIS_APPKEY · KIS_APPSECRET      주가(월봉)
    DART_API_KEY | DART_KEY         분기 재무(주요계정)
    DEF   peer 정의 파일들(쉼표). 기본 semipeer_def.json,cospeer_def.json,robopeer_def.json
    YEARS 과거 연수(기본 6)
    ONLY  쉼표 종목코드 — 일부만
"""
import datetime, json, math, os, re, sys, time, urllib.parse, urllib.request

BASE_KIS = 'https://openapi.koreainvestment.com:9443'
APPKEY    = os.environ.get('KIS_APPKEY', '')
APPSECRET = os.environ.get('KIS_APPSECRET', '')
DKEY      = os.environ.get('DART_API_KEY') or os.environ.get('DART_KEY') or ''
DBASE     = 'https://opendart.fss.or.kr/api'
DD        = 'public/data'
OUT       = os.environ.get('OUT', os.path.join(DD, 'band.json'))
DEFS      = [s.strip() for s in os.environ.get(
             'DEF', 'semipeer_def.json,cospeer_def.json,robopeer_def.json').split(',') if s.strip()]
YEARS     = int(os.environ.get('YEARS', '6'))
ONLY      = [s.strip() for s in os.environ.get('ONLY', '').split(',') if s.strip()]
REPRT     = {1: '11013', 2: '11012', 3: '11014', 4: '11011'}
T0        = time.time()
LOG       = []

def log(s):
    m = '%5.1fs %s' % (time.time() - T0, s)
    LOG.append(m); print(m, flush=True)

def load(name, d=None):
    try:
        with open(os.path.join(DD, name), encoding='utf-8') as f: return json.load(f)
    except Exception: return d

# ─────────────────────────────────────────────────────────────────
# 1. 모집단 — peer 정의 파일들에서 종목코드와 섹터를 모은다
# ─────────────────────────────────────────────────────────────────
def universe():
    uni = {}
    for fn in DEFS:
        d = load(fn)
        if not d: log('%s 없음 — 건너뜀' % fn); continue
        ind = d.get('industry') or fn.replace('peer_def.json', '')
        gm = {}
        for g in (d.get('groups') or []):
            for c in (g.get('members') or []): gm[c] = g
        for c, v in (d.get('co') or {}).items():
            g = gm.get(c) or {}
            uni.setdefault(c, {'n': v.get('n') or c, 'ind': ind,
                               'top': g.get('top') or '', 'seg': g.get('seg') or ''})
        log('%s → %d종목' % (fn, len(d.get('co') or {})))
    if ONLY: uni = {c: v for c, v in uni.items() if c in ONLY}
    return uni

# ─────────────────────────────────────────────────────────────────
# 2. 주가 월봉 — KIS. 1콜 100봉이므로 6년(72봉)은 한 번에 들어온다
# ─────────────────────────────────────────────────────────────────
def kis_token():
    for a in range(4):
        try:
            req = urllib.request.Request(BASE_KIS + '/oauth2/tokenP',
                data=json.dumps({'grant_type': 'client_credentials',
                                 'appkey': APPKEY, 'appsecret': APPSECRET}).encode(),
                headers={'content-type': 'application/json'})
            t = json.loads(urllib.request.urlopen(req, timeout=20).read().decode())
            if t.get('access_token'): return t['access_token']
        except Exception as e:
            log('KIS 토큰 %d회차: %s' % (a + 1, str(e)[:60]))
        time.sleep(65)
    return None

def monthly(code, hdr, d1, d2):
    """{YYYYMM: 월말 수정주가}"""
    url = (BASE_KIS + '/uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice'
           '?FID_COND_MRKT_DIV_CODE=J&FID_INPUT_ISCD=%s&FID_INPUT_DATE_1=%s&FID_INPUT_DATE_2=%s'
           '&FID_PERIOD_DIV_CODE=M&FID_ORG_ADJ_PRC=0' % (code, d1, d2))
    for a in range(3):
        try:
            j = json.loads(urllib.request.urlopen(
                urllib.request.Request(url, headers=hdr), timeout=25).read().decode('utf-8', 'ignore'))
            break
        except Exception:
            if a == 2: return {}
            time.sleep(1.2)
    out = {}
    for r in (j.get('output2') or []):
        d, c = (r.get('stck_bsop_date') or '').strip(), r.get('stck_clpr')
        if not (d and c): continue
        try:
            v = float(c)
            if v > 0: out[d[:6]] = v
        except Exception: pass
    return out

# ─────────────────────────────────────────────────────────────────
# 3. 분기 재무 — DART 다중회사 주요계정(50종목/콜)
#    매출액·당기순이익은 3개월 값(없으면 누적 차), 자본총계는 잔액이라 그대로
# ─────────────────────────────────────────────────────────────────
# DART 주요계정의 계정명은 보고서 기간에 따라 바뀐다 — 1·3분기는 "분기순이익", 2분기는 "반기순이익".
# "당기순이익" 한 가지만 찾으면 흑자 기업도 전 구간 결측이 된다(v1 에서 실제로 그랬다).
def acc_key(nm, sj):
    nm = (nm or '').replace(' ', '')
    if sj == 'BS':
        return ('eq', 0) if nm == '자본총계' else (None, 9)
    if nm in ('매출액', '수익(매출액)'): return ('rev', 0)
    if nm in ('당기순이익', '당기순이익(손실)'): return ('ni', 0)
    if nm in ('분기순이익', '분기순이익(손실)', '반기순이익', '반기순이익(손실)'): return ('ni', 1)
    if re.fullmatch(r'(연결)?(당기|분기|반기)순(이익|손익)(\(손실\))?', nm): return ('ni', 2)
    return (None, 9)

def dnum(s):
    try: return float(re.sub(r'[^\d\.\-]', '', str(s)))
    except Exception: return None

def dart_quarter(corps, y, q, store):
    """주요계정 1콜(50종목). 손익은 **누적액(thstrm_add_amount)** 을 우선 쓴다 —
       thstrm_amount 는 분기 3개월치일 수도, 누적일 수도 있어 섞이면 TTM 이 틀어진다."""
    url = '%s/fnlttMultiAcnt.json?%s' % (DBASE, urllib.parse.urlencode(
        dict(crtfc_key=DKEY, corp_code=','.join(corps), bsns_year=y, reprt_code=REPRT[q])))
    try:
        j = json.loads(urllib.request.urlopen(url, timeout=40).read().decode('utf-8'))
    except Exception as e:
        log('DART %d/%dQ 실패 %s' % (y, q, str(e)[:50])); return False
    if j.get('status') == '020': log('DART 사용한도 초과'); return None
    for r in (j.get('list') or []):
        key, pri = acc_key(r.get('account_nm'), r.get('sj_div') or '')
        cp = r.get('corp_code')
        if key is None or not cp: continue
        fs = r.get('fs_div') or 'OFS'                 # CFS(연결) 우선
        amt, add = dnum(r.get('thstrm_amount')), dnum(r.get('thstrm_add_amount'))
        if key == 'eq' or q == 4:                     # 재무상태표는 잔액, 사업보고서 손익은 연간
            cum = amt
        elif add is not None:                          # 분기·반기 손익은 누적액을 쓴다
            cum = add
        else:
            cum = amt if q == 1 else None              # 누적이 없으면 1분기만 인정
        if cum is None: continue
        d = store.setdefault(cp, {}).setdefault(fs, {}).setdefault((y, q), {})
        if key in d and d[key][1] <= pri: continue
        d[key] = (cum, pri)
    return True

def ttm(series, y, q, key):
    """최근 4분기 합. 주요계정은 누적이므로 분기값으로 바꾼 뒤 더한다"""
    def val(yy, qq):
        t = (series.get((yy, qq)) or {}).get(key)
        return None if t is None else t[0]
    def one(yy, qq):
        cum = val(yy, qq)
        if cum is None: return None
        if qq == 1: return cum
        pv = val(yy, qq - 1)
        return None if pv is None else cum - pv
    vals, yy, qq = [], y, q
    for _ in range(4):
        v = one(yy, qq)
        if v is None: return None
        vals.append(v)
        qq -= 1
        if qq == 0: yy, qq = yy - 1, 4
    return sum(vals)

# ─────────────────────────────────────────────────────────────────
# 4. 밴드 계산 — 여기가 핵심. 세 방식 전부 만든다
# ─────────────────────────────────────────────────────────────────
def pct(sorted_v, x):
    """x 가 분포의 몇 백분위인가 (0~100)"""
    if not sorted_v: return None
    lo = sum(1 for v in sorted_v if v < x)
    return round(lo / len(sorted_v) * 100)

def quantile(sv, p):
    if not sv: return None
    i = (len(sv) - 1) * p
    lo, hi = int(math.floor(i)), int(math.ceil(i))
    return sv[lo] if lo == hi else sv[lo] + (sv[hi] - sv[lo]) * (i - lo)

def bands(vals):
    """vals = 시점별 배수 리스트(결측 제외). 세 방식의 5개 선을 돌려준다"""
    sv = sorted(v for v in vals if v is not None and v > 0 and math.isfinite(v))
    if len(sv) < 12: return None                      # 1년(12개월) 미만이면 분포로 못 쓴다
    q = [round(quantile(sv, p), 2) for p in (0.10, 0.25, 0.50, 0.75, 0.90)]
    lo, hi = sv[0], sv[-1]
    eq = [round(lo + (hi - lo) * i / 4, 2) for i in range(5)]
    m = sum(sv) / len(sv)
    sd = math.sqrt(sum((v - m) ** 2 for v in sv) / len(sv))
    sdb = [round(m + k * sd, 2) for k in (-2, -1, 0, 1, 2)]
    return {'q': q, 'eq': eq, 'sd': sdb, 'n': len(sv),
            'min': round(lo, 2), 'max': round(hi, 2), 'med': q[2]}

# 섹터별로 어떤 배수를 먼저 보나 — 자산이 무거운 곳은 PBR, 적자가 많은 곳은 PSR
PREF = [
    (re.compile(r'은행|보험|증권|금융|지주|철강|조선|건설|해운|화학'), ['pbr', 'per', 'psr']),
    (re.compile(r'바이오|제약|로봇|신재생|우주'),                      ['psr', 'pbr', 'per']),
]
def prefer(ind, top, seg):
    t = '%s %s %s' % (ind, top, seg)
    for rx, order in PREF:
        if rx.search(t): return order
    return ['per', 'psr', 'pbr']

def usable(key, vals, n_obs):
    """그 배수를 이 종목에 쓸 수 있나 — 못 쓰면 이유를 돌려준다"""
    ok = [v for v in vals if v is not None and v > 0 and math.isfinite(v)]
    if n_obs == 0: return False, '관측 없음'
    rate = len(ok) / n_obs
    if key == 'per' and rate < 0.6:
        return False, '적자 구간이 %d%% — PER 밴드는 끊긴다' % round((1 - rate) * 100)
    if key == 'pbr' and rate < 0.9:
        return False, '자본총계가 비거나 음수인 구간이 있다'
    if len(ok) < 12: return False, '관측 %d개월 — 12개월 미만' % len(ok)
    return True, None

# ─────────────────────────────────────────────────────────────────
# 5. 종목 1개의 시계열 조립
# ─────────────────────────────────────────────────────────────────
def months_back(n):
    t = datetime.date.today().replace(day=1)
    out = []
    for _ in range(n):
        out.append('%04d%02d' % (t.year, t.month))
        t = (t.replace(day=1) - datetime.timedelta(days=1)).replace(day=1)
    return list(reversed(out))

def q_of(ym):
    y, m = int(ym[:4]), int(ym[4:])
    return y, (m - 1) // 3 + 1

def qshift(y, q, k):
    """k분기 뒤로"""
    n = y * 4 + (q - 1) - k
    return n // 4, n % 4 + 1

def build_one(code, meta, px, fin, cap_now, px_now):
    """px={YYYYMM:주가}, fin={(y,q):{rev,ni,eq}} → 밴드 레코드"""
    ms = [m for m in months_back(YEARS * 12) if m in px]
    if len(ms) < 12: return None
    ser = {'per': [], 'pbr': [], 'psr': [], 'roe': []}
    keep = []
    for m in ms:
        y, q = q_of(m)
        # 그 달에 '이미 공시된' 가장 최근 분기 — 분기말 + 45일 지연을 가정한다
        yy, qq = qshift(y, q, 1)
        _e = (fin.get((yy, qq)) or {}).get('eq'); eq = _e[0] if _e else None
        ni = ttm(fin, yy, qq, 'ni')
        rv = ttm(fin, yy, qq, 'rev')
        mcap = cap_now * (px[m] / px_now) if (cap_now and px_now) else None
        if not mcap: continue
        keep.append(m)
        ser['per'].append(mcap / ni if (ni and ni > 0) else None)
        ser['pbr'].append(mcap / eq if (eq and eq > 0) else None)
        ser['psr'].append(mcap / rv if (rv and rv > 0) else None)
        ser['roe'].append(round(ni / eq * 100, 2) if (ni and eq and eq > 0) else None)
    if len(keep) < 12: return None
    n_obs = len(keep)
    rec = {'n': meta['n'], 'ind': meta['ind'], 'top': meta['top'], 'seg': meta['seg'],
           'm': keep, 'px': [round(px[m]) for m in keep],
           'bands': {}, 'now': {}, 'roe': ser['roe']}
    for k in ('per', 'pbr', 'psr'):
        ok, why = usable(k, ser[k], n_obs)
        b = bands(ser[k]) if ok else None
        cur = next((v for v in reversed(ser[k]) if v), None)
        rec['bands'][k] = {'ok': bool(b), 'why': why, 'v': [None if v is None else round(v, 2) for v in ser[k]]}
        if b:
            rec['bands'][k].update(b)
            sv = sorted(v for v in ser[k] if v)
            rec['now'][k] = {'x': round(cur, 2) if cur else None, 'pct': pct(sv, cur) if cur else None}
    rec['pref'] = prefer(meta['ind'], meta['top'], meta['seg'])
    rec['use'] = next((k for k in rec['pref'] if rec['bands'].get(k, {}).get('ok')), None)
    # 관측 구간 신뢰도 — 상장이 짧으면 '역사적 밴드'가 아니다
    lvl = '높음' if n_obs >= 60 else ('보통' if n_obs >= 36 else '낮음')
    rec['trust'] = {'months': n_obs, 'level': lvl,
                    'why': ('관측 %d개월(약 %.1f년). 36개월 미만이라 이 밴드는 "역사적 분포"가 아니라 '
                            '"최근 구간의 변동폭"이다 — 상장이 짧은 종목이 여기 걸린다.' % (n_obs, n_obs / 12))
                           if lvl == '낮음' else '관측 %d개월(약 %.1f년)' % (n_obs, n_obs / 12)}
    # ⚠️ 이익 고점 함정 — 시험 실행에서 드러난 것
    #   삼성전자 PER 4.86배(0분위)인데 PBR 은 83분위, ROE 는 97분위였다.
    #   이익이 역사적 고점이면 PER 은 자동으로 역사적 최저가 된다. "싸다"가 아니라
    #   "이익이 꼭대기"라는 뜻일 수 있다. 반도체·소재처럼 사이클이 큰 업종에서 특히 그렇다.
    #   → PER 이 하위 20분위인데 ROE 가 상위 80분위면 깃발을 세운다.
    rec['flag'] = []
    pp = (rec['now'].get('per') or {}).get('pct')
    rp = (rec.get('roeband') or {}).get('pct') if False else None
    # roeband 는 아래에서 만들어지므로 여기서는 자리만 잡고 뒤에서 채운다

    # ROE 는 배수가 아니다 — 분포만 따로 낸다
    rv = [v for v in ser['roe'] if v is not None]
    if len(rv) >= 12:
        s = sorted(rv)
        rec['roeband'] = {'q': [round(quantile(s, p), 2) for p in (0.10, 0.25, 0.50, 0.75, 0.90)],
                          'now': rv[-1], 'pct': pct(s, rv[-1]),
                          'note': 'ROE 는 배수가 아니라 수익성 비율이라 주가 밴드가 아니다. 분포만 본다.'}
    # 깃발 — roeband 가 만들어진 뒤에 판정한다
    pp = (rec['now'].get('per') or {}).get('pct')
    rp = (rec.get('roeband') or {}).get('pct')
    bp = (rec['now'].get('pbr') or {}).get('pct')
    if pp is not None and rp is not None and pp <= 20 and rp >= 80:
        rec['flag'].append({'k': 'peak',
            'm': 'PER %d분위(싸 보임)인데 ROE 가 %d분위(역사적 고점)다. 이익이 꼭대기라 PER 이 눌린 것일 수 있다 — '
                 '사이클이 큰 업종에서 가장 흔한 함정이다.' % (pp, rp)})
    if pp is not None and bp is not None and abs(pp - bp) >= 50:
        rec['flag'].append({'k': 'split',
            'm': '같은 주가인데 PER 은 %d분위, PBR 은 %d분위다. 어느 분모를 쓰느냐로 결론이 갈린다 — '
                 '한쪽만 보고 "역사적 저평가"라고 하면 안 된다.' % (pp, bp)})
    if rec['trust']['level'] == '낮음':
        rec['flag'].append({'k': 'short', 'm': rec['trust']['why']})
    return rec

# ─────────────────────────────────────────────────────────────────
# 6. 섹터 밴드 — 종목 밴드를 중앙값으로 묶는다
#    시총가중을 쓰면 반도체는 사실상 삼성전자 밴드가 된다 → 중앙값
# ─────────────────────────────────────────────────────────────────
def sector_bands(recs):
    grp = {}
    for c, r in recs.items():
        for key in [('%s' % r['ind']), ('%s|%s' % (r['ind'], r['top'] or '-'))]:
            grp.setdefault(key, []).append(r)
    out = {}
    for key, rs in grp.items():
        if len(rs) < int(os.environ.get('SEC_MIN', '3')): continue
        ms = sorted({m for r in rs for m in r['m']})
        rec = {'n': len(rs), 'm': ms, 'bands': {}, 'now': {}}
        for k in ('per', 'pbr', 'psr'):
            med = []
            for m in ms:
                vs = []
                for r in rs:
                    b = r['bands'].get(k) or {}
                    if not b.get('ok'): continue
                    try: i = r['m'].index(m)
                    except ValueError: continue
                    v = (b.get('v') or [None] * len(r['m']))[i]
                    if v: vs.append(v)
                med.append(round(sorted(vs)[len(vs) // 2], 2) if len(vs) >= 3 else None)
            b = bands(med)
            rec['bands'][k] = {'ok': bool(b), 'v': med}
            if b:
                rec['bands'][k].update(b)
                cur = next((v for v in reversed(med) if v), None)
                sv = sorted(v for v in med if v)
                rec['now'][k] = {'x': round(cur, 2) if cur else None, 'pct': pct(sv, cur) if cur else None}
        rec['use'] = next((k for k in ('per', 'pbr', 'psr') if rec['bands'][k]['ok']), None)
        rec['note'] = ('구성 종목 %d곳의 **중앙값**이다. 시총가중을 쓰면 대장주 한 곳이 섹터를 지배해 '
                       '사실상 그 종목 밴드가 된다.' % len(rs))
        out[key] = rec
    return out

# ─────────────────────────────────────────────────────────────────
# 7. 실행
# ─────────────────────────────────────────────────────────────────
def corpcode_all():
    """DART 전체 고유번호(corpCode.xml.zip) → {종목코드: corp_code}. 상장사만 남긴다"""
    import io, zipfile, xml.etree.ElementTree as ET
    try:
        raw = urllib.request.urlopen(
            '%s/corpCode.xml?crtfc_key=%s' % (DBASE, DKEY), timeout=60).read()
        with zipfile.ZipFile(io.BytesIO(raw)) as z:
            xml = z.read(z.namelist()[0])
    except Exception as e:
        log('corpCode 내려받기 실패 %s' % str(e)[:60]); return {}
    out = {}
    for el in ET.fromstring(xml).iter('list'):
        sc = (el.findtext('stock_code') or '').strip()
        cc = (el.findtext('corp_code') or '').strip()
        if sc and cc and sc != ' ': out[sc] = cc
    log('corpCode 전체 %d종목' % len(out))
    return out

def main():
    uni = universe()
    if not uni: log('모집단 없음'); return 1
    log('모집단 %d종목' % len(uni))
    sv = (load('stockvals.json') or {}).get('map') or load('stockvals.json') or {}
    # DART corp_code 매핑 — 기존 수집기와 같은 출처를 쓴다
    corpmap = {}
    try:
        with open('tools/semipeer/dartcorp.json', encoding='utf-8') as f: corpmap.update(json.load(f))
    except Exception: pass
    for fn in ('semipeer.json', 'cospeer.json', 'robopeer.json'):
        for k, v in ((load(fn) or {}).get('corpmap') or {}).items(): corpmap.setdefault(k, v)
    miss = [c for c in uni if c not in corpmap]
    if miss:
        got = corpcode_all()                      # 기존 매핑은 반도체뿐 — 화장품·로봇은 여기서 채운다
        for c in miss:
            if c in got: corpmap[c] = got[c]
    if not corpmap: log('DART corp_code 매핑을 찾지 못했다'); return 1
    log('corp_code 매핑 %d종목 (보강 %d)' % (len(corpmap), len(miss)))
    if not (APPKEY and APPSECRET): log('KIS 키 없음'); return 1
    if not DKEY: log('DART 키 없음'); return 1

    tok = kis_token()
    if not tok: log('KIS 토큰 실패'); return 1
    hdr = {'authorization': 'Bearer ' + tok, 'appkey': APPKEY, 'appsecret': APPSECRET,
           'tr_id': 'FHKST03010100', 'custtype': 'P'}
    today = datetime.date.today()
    d2 = today.strftime('%Y%m%d')
    d1 = (today - datetime.timedelta(days=int(YEARS * 372))).strftime('%Y%m%d')

    # ① 분기 재무 — 50종목 묶음
    codes = [c for c in uni if c in corpmap]
    log('DART 매핑 %d / %d' % (len(codes), len(uni)))
    store, y0 = {}, today.year - YEARS
    quarters = [(y, q) for y in range(y0, today.year + 1) for q in (1, 2, 3, 4)]
    for i in range(0, len(codes), 50):
        batch = [corpmap[c] for c in codes[i:i + 50]]
        for (y, q) in quarters:
            time.sleep(0.35)
            r = dart_quarter(batch, y, q, store)
            if r is None: break
        log('재무 %d/%d' % (min(i + 50, len(codes)), len(codes)))

    # ② 주가 + 조립
    recs, skip = {}, {}
    for i, c in enumerate(codes, 1):
        time.sleep(0.12)
        px = monthly(c, hdr, d1, d2)
        if not px: skip[c] = '주가 없음'; continue
        pxn = px[sorted(px)[-1]]
        cap = (sv.get(c) or [None] * 3)[2]
        if not cap: skip[c] = '시총 없음'; continue
        fin = {}
        cp = corpmap[c]
        for fsd in ('CFS', 'OFS'):                    # 연결 우선
            s = (store.get(cp) or {}).get(fsd) or {}
            if len(s) > len(fin): fin = s
        if not fin: skip[c] = '재무 없음'; continue
        r = build_one(c, uni[c], px, fin, cap * 1e8, pxn)
        if r: recs[c] = r
        else: skip[c] = '관측 12개월 미만'
        if i % 50 == 0: log('조립 %d/%d' % (i, len(codes)))

    out = {'updated': datetime.datetime.now().strftime('%Y-%m-%d %H:%M KST'),
           'years': YEARS, 'n': len(recs), 'co': recs,
           'sector': sector_bands(recs), 'skip': skip,
           'note': ('밸류 밴드 시계열. 배수는 시총 기준으로 계산해 주식수를 약분했다 — '
                    '과거 시총은 현재시총 × 수정주가비로 만들었으므로 분할·배당은 맞고 대규모 증자는 오차다. '
                    'ROE 는 배수가 아니라 주가 밴드가 없다(분포만). '
                    '밴드 선은 분위수(q)·균등분할(eq)·평균±σ(sd) 세 벌을 전부 담았다 — 방식이 다르면 결론도 다르다.'),
           'log': LOG[-40:]}
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, 'w', encoding='utf-8') as f: json.dump(out, f, ensure_ascii=False, separators=(',', ':'))
    log('완료 %d종목 / 섹터 %d / 제외 %d → %s' % (len(recs), len(out['sector']), len(skip), OUT))
    return 0

if __name__ == '__main__':
    sys.exit(main())
