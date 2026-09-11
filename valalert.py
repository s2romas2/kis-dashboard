#!/usr/bin/env python3
# 텔레그램 밸류 알림 — 평일 09:00 KST
#   현재가·시총 : KIS 오픈API inquire-price (FHKST01010100)
#   트레일링    : DART fnlttSinglAcntAll(연결 우선) 직전 4개 분기 영업이익·순이익(지배주주 우선) 합산 → PER, P/OP
#   12M 포워드  : KIS 종목추정실적(HHKST668300C0) 연간 추정 FY1·FY2를 잔여개월로 가중 → PER, P/OP
#                 ※ 이 API는 한국투자증권 리서치(output1.name1=담당 애널리스트)의 단일 추정치이며 시장 컨센서스가 아님.
#                   KIS 리서치 미커버 종목은 output1~4가 전부 빈 값으로 옴(9/11 첫 실행: 동국제약·아로마티카·펌텍코리아).
#   발송        : 텔레그램 sendMessage (TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID)
# 결과: public/data/valalert.json (대시보드·디버그용, 추정실적 원본 응답 포함)
# 원칙: 못 구한 값은 지어내지 않고 '조회 실패'로 표기. 목표주가·투자의견은 싣지 않음.
# 9/12 수정: ① 추정실적 행 순서를 실제 응답(9/11 에이피알)으로 확정 + 증감율 행으로 런타임 검증
#            ② DART 순이익 계정명 매칭 강화(번호 접두·'지배기업소유주지분' 등) + 분기별 nip→ni 대체, 누락 분기 있으면 합산 안 함(0 취급 버그 제거)
#            ③ corp_code 상수화(corpCode.xml 다운로드 생략) + 동일 보고서 재호출 캐시 → 실행시간 단축(첫 실행 6분16초)
import os, sys, json, time, re, io, zipfile, urllib.request, urllib.parse, ssl, datetime
import xml.etree.ElementTree as ET

APPKEY = os.environ.get('KIS_APPKEY', '')
APPSECRET = os.environ.get('KIS_APPSECRET', '')
DART_KEY = os.environ.get('DART_KEY', '')
TG_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN', '')
TG_CHAT = os.environ.get('TELEGRAM_CHAT_ID', '')
KIS = 'https://openapi.koreainvestment.com:9443'
DART = 'https://opendart.fss.or.kr/api'
OUT = os.environ.get('OUT', 'public/data/valalert.json')
FORCE = os.environ.get('FORCE', '') == '1'   # 휴장일에도 발송
DEBUG = []

# 대상 종목 (코드, 이름) — 아로마티카는 신형 영문혼합 코드
TARGETS = [('278470', '에이피알'), ('086450', '동국제약'), ('0015N0', '아로마티카'), ('251970', '펌텍코리아')]
# DART 고유번호 상수 — corpCode.xml(수 MB zip) 매회 다운로드 생략용.
#   출처: 에이피알·펌텍코리아 = public/data/screener.json corp_code, 동국제약·아로마티카 = dart.fss.or.kr 회사명 검색(2026-09-12)
#   상수에 없거나 DART 조회가 전부 비면 corpCode.xml 폴백.
CORP_FIXED = {'278470': '01190568', '086450': '00114808', '0015N0': '01381805', '251970': '00761059'}
REPRT = {1: '11013', 2: '11012', 3: '11014', 4: '11011'}
UA = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126 Safari/537.36'}
CTX = ssl.create_default_context(); CTX.check_hostname = False; CTX.verify_mode = ssl.CERT_NONE
KST = datetime.timezone(datetime.timedelta(hours=9))
TODAY = datetime.datetime.now(KST).date()

def log(s):
    DEBUG.append(str(s)[:300]); print(s, file=sys.stderr)

def fetch(url, headers=None, data=None, timeout=30, tries=3):
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

def fmt_eok(v, d=0):  # 억원
    if v is None: return '조회실패'
    return ('{:,.%df}' % d).format(v) + '억'

def fmt_cap(v):  # 억원 → 조 표기
    if v is None: return '조회실패'
    return '%.2f조' % (v / 1e4) if v >= 1e4 else '{:,.0f}억'.format(v)

def fmt_x(v):
    if v is None: return '—'
    if v < 0: return '적자(%.1f)' % v
    return '%.1f' % v

# ── KIS ──
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
    if not o.get('stck_prpr'):
        log('%s 시세 응답: %s' % (code, str(j)[:160])); return {}
    return {'price': tonum(o.get('stck_prpr')), 'cap': tonum(o.get('hts_avls')), 'per': tonum(o.get('per')),
            'eps': tonum(o.get('eps')), 'pbr': tonum(o.get('pbr')), 'chg': tonum(o.get('prdy_ctrt')),
            'shares': tonum(o.get('lstn_stcn'))}

def kis_holiday(token):
    """오늘이 개장일인지. 실패 시 None(→ 발송 진행)."""
    d = TODAY.strftime('%Y%m%d')
    j = jget(KIS + '/uapi/domestic-stock/v1/quotations/chk-holiday?BASS_DT=%s&CTX_AREA_NK=&CTX_AREA_FK=' % d,
             kis_hdr(token, 'CTCA0903R'))
    for r in (j.get('output') or []):
        if r.get('bass_dt') == d:
            return r.get('opnd_yn') == 'Y'
    return None

def kis_estimate(token, code):
    """종목추정실적 원본(output1~4). 구조는 valalert.json에 그대로 저장해 검증."""
    j = jget(KIS + '/uapi/domestic-stock/v1/quotations/estimate-perform?SHT_CD=' + code, kis_hdr(token, 'HHKST668300C0'))
    if j.get('rt_cd') not in ('0', 0):
        log('%s 추정실적 응답: %s' % (code, str(j)[:200]))
    return {k: j.get(k) for k in ('rt_cd', 'msg1', 'output1', 'output2', 'output3', 'output4')}

def _growth_ok(base, gr):
    """증감율 행(단위 0.1%p, 예 380.0 = +38.0%)이 값 행의 전년비와 일치하는지 — 행 순서 런타임 검증."""
    n = 0
    for i in range(1, 5):
        a, b, g = base[i - 1], base[i], gr[i]
        if a in (None, 0) or b is None or g is None: continue
        if abs((b / a - 1) * 1000 - g) > max(15, abs(g) * 0.03): return False
        n += 1
    return n >= 2

def parse_estimate(est):
    """KIS 종목추정실적 → ({'2026': {'rv','op','ni','label'}, ...}, note). 단위 억원.
    실제 응답 구조(2026-09-11 에이피알 A278470, valalert.json estimate_raw 보존):
      output4 = [{'dt': '2023.12'}, {'dt': '2024.12'}, {'dt': '2025.12'}, {'dt': '2026.12E'}, {'dt': '2027.12E'}]  ← data1~5 순서
      output2 = 라벨 없는 6행: [0]매출액 [1]매출액증감율 [2]영업이익 [3]영업이익증감율 [4]순이익 [5]순이익증감율
        근거: [4]의 2025 값 2897 ≈ KIS inquire-price eps 7704원 × 상장주식 3,744만주 = 2,884억(직전 결산 연간 순이익) → [4]=순이익 확정.
              [2]의 2025 값 3655 는 DART 분기 영업이익(25Q3 961·25Q4 1303억)과 규모 정합, 순이익보다 큼 → 영업이익.
              증감율 행은 0.1%p 단위: [1] 2024=380.0 ↔ 7228/5238−1=+38.0%, [3] 2025=1979 ↔ 3655/1227−1=+197.9%.
      output3 = 3행: [0]EBITDA [1]EPS(원) [2]EPS증감율 — EPS는 액면분할 전 기준으로 보임(KIS eps 7704의 10배) → 사용 안 함.
    증감율 행이 값 행과 맞지 않으면(구조 변경) 빈 dict 반환 → '조회 실패' 표기, 숫자 지어내지 않음."""
    try:
        o4 = est.get('output4') or []
        periods = [str(r.get('dt') or '').strip() for r in o4] if isinstance(o4, list) else []
        o2 = est.get('output2') or []
        if isinstance(o2, dict): o2 = [o2]
        if not periods or not o2:
            o1 = est.get('output1') or {}
            if isinstance(o1, dict) and not (o1.get('sht_cd') or '').strip():
                return {}, 'KIS 리서치 미커버(추정실적 없음)'
            return {}, 'output4(결산년월)/output2 없음'
        rows = []
        for r in o2:
            vals = [tonum(r.get('data%d' % i)) for i in range(1, 6)]
            label = ''
            for k, v in r.items():
                if not str(k).startswith('data') and isinstance(v, str) and re.search(r'[가-힣A-Za-z]', v):
                    label = v; break
            rows.append((label, vals))
        pick, note = {}, ''
        if any(l for l, _ in rows):   # 라벨이 생기면 라벨 우선
            want = {'rv': ('매출액', '매출'), 'op': ('영업이익',), 'ni': ('당기순이익', '순이익')}
            for key, names in want.items():
                for label, vals in rows:
                    if any(n in label.replace(' ', '') for n in names) and '률' not in label and '율' not in label:
                        pick[key] = vals; break
            note = '라벨 매칭'
        if len(pick) < 3:
            if len(rows) < 6:
                return {}, 'output2 행 수 %d(6 기대)' % len(rows)
            rv, rvg, op, opg, ni, nig = [r[1] for r in rows[:6]]
            if not (_growth_ok(rv, rvg) and _growth_ok(op, opg)):
                return {}, 'output2 행 순서 검증 실패(증감율 불일치) — 구조 변경 의심'
            if not all(r is None or o is None or r >= o for r, o in zip(rv, op)):
                return {}, 'output2 행 순서 검증 실패(매출액<영업이익) — 구조 변경 의심'
            pick = {'rv': rv, 'op': op, 'ni': ni}
            note = '행 순서 검증(증감율 일치)' + ('' if _growth_ok(ni, nig) else '·순이익 증감율 불일치')
        fy = {}
        for i, p in enumerate(periods[:5]):
            m = re.search(r'(20\d\d)', p)
            if not m: continue
            fy[m.group(1)] = {'rv': pick['rv'][i], 'op': pick['op'][i], 'ni': pick['ni'][i], 'label': p}
        return fy, note
    except Exception as e:
        return {}, '파싱 예외 %r' % e

def forward12(fy):
    """12개월 선행 = FY1×(잔여일/365) + FY2×(1-잔여일/365). 12월 결산 가정."""
    y1 = str(TODAY.year); y2 = str(TODAY.year + 1)
    a, b = fy.get(y1), fy.get(y2)
    if not a and not b: return None
    rem = (datetime.date(TODAY.year, 12, 31) - TODAY).days / 365.0
    out = {'w1': round(rem, 2), 'fy1': y1, 'fy2': y2}
    for k in ('op', 'ni', 'rv'):
        v1 = a.get(k) if a else None; v2 = b.get(k) if b else None
        if v1 is not None and v2 is not None: out[k] = v1 * rem + v2 * (1 - rem)
        elif v1 is not None: out[k] = v1; out['note'] = 'FY2 없음 → FY1 사용'
        elif v2 is not None: out[k] = v2; out['note'] = 'FY1 없음 → FY2 사용'
        else: out[k] = None
    return out

# ── DART ──
_CORP_FB = None
def corp_map():
    global _CORP_FB
    if _CORP_FB is not None: return _CORP_FB
    _CORP_FB = _corp_map_dl()
    return _CORP_FB

def _corp_map_dl():
    b = b''
    for i in range(4):
        b = fetch('%s/corpCode.xml?crtfc_key=%s' % (DART, DART_KEY), timeout=90)
        if b[:2] == b'PK': break
        time.sleep(5 * (i + 1))
    if b[:2] != b'PK': return {}
    z = zipfile.ZipFile(io.BytesIO(b)); root = ET.fromstring(z.read(z.namelist()[0]))
    m = {}
    for it in root.iter('list'):
        sc = (it.findtext('stock_code') or '').strip()
        if len(sc) == 6: m[sc] = it.findtext('corp_code').strip()
    return m

_PULL_CACHE = {}   # (corp, y, rc, fs) → got  (Q4 계산 시 3Q 보고서 재호출 방지)
_NM_STRIP = re.compile(r'^[ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩIVX0-9]+[.)]\s*')   # 'Ⅸ.반기순이익' 같은 번호 접두 제거

def classify_account(nm, aid):
    """손익계산서 계정 → 'op' | 'ni' | 'nip' | None.
    9/11 첫 실행에서 펌텍코리아가 보고서마다 순이익 계정이 잡히다 말다 함(Q3 ni만, Q1·Q2 nip만, 사업보고서 없음) → 매칭 강화:
      · 번호 접두(Ⅸ. 등) 제거, 표준계정 ID 우선
      · ni : '(당기|분기|반기|연결)?순(이익|손실|손익)' 포함, 지배·주당·포괄·계속영업·중단영업·귀속 제외
      · nip: 표준 ID ProfitLossAttributableToOwnersOfParent 또는 '지배' 포함(비지배·포괄·주당 제외) — '지배기업의소유주지분'처럼 '순이익' 단어가 없어도 인정
             (손익계산서에서 당기순이익의 귀속이 총포괄손익의 귀속보다 먼저 나오므로 첫 매칭이 순이익 귀속분)"""
    nm = _NM_STRIP.sub('', (nm or '').replace(' ', ''))
    aid = aid or ''
    if 'ComprehensiveIncome' in aid or '포괄' in nm or '주당' in nm: return None
    if aid == 'ifrs-full_ProfitLossAttributableToOwnersOfParent': return 'nip'
    if aid == 'ifrs-full_ProfitLoss': return 'ni'
    if aid == 'dart_OperatingIncomeLoss': return 'op'
    if '비지배' in nm: return None
    if '지배' in nm: return 'nip'
    if re.search(r'(당기|분기|반기|연결)?순(이익|손실|손익)', nm) and not any(x in nm for x in ('계속영업', '중단영업', '귀속', '세전', '법인세')):
        return 'ni'
    if nm in ('영업이익', '영업이익(손실)', '영업손익', '영업손실'):
        return 'op'
    return None

def dart_quarter(corp, y, qn):
    """해당 분기 3개월 {'op','ni','nip'} (원). 연결(CFS) 우선, 없으면 별도(OFS).
    Q1~Q3: thstrm_amount=3개월, Q4: 사업보고서 연간 − 3Q 누적(thstrm_add_amount)."""
    def pull(rc, fs):
        ck = (corp, y, rc, fs)
        if ck in _PULL_CACHE: return _PULL_CACHE[ck]
        d = jget('%s/fnlttSinglAcntAll.json?crtfc_key=%s&corp_code=%s&bsns_year=%d&reprt_code=%s&fs_div=%s'
                 % (DART, DART_KEY, corp, y, rc, fs))
        rows = d.get('list') or []
        got, names = {}, []
        for r in rows:
            if r.get('sj_div') not in ('IS', 'CIS'): continue
            cur, cum = tonum(r.get('thstrm_amount')), tonum(r.get('thstrm_add_amount'))
            if cur is None: continue
            key = classify_account(r.get('account_nm'), r.get('account_id'))
            if key and key not in got:
                got[key] = (cur, cum if cum is not None else cur); names.append('%s=%s' % (key, r.get('account_nm')))
        if rows and 'ni' not in got and 'nip' not in got:
            log('%s %d/%s/%s 순이익 계정 미매칭: %s' % (corp, y, rc, fs, [r.get('account_nm') for r in rows if r.get('sj_div') in ('IS', 'CIS')][:12]))
        _PULL_CACHE[ck] = got; time.sleep(0.15)
        return got
    def get(rc):
        for fs in ('CFS', 'OFS'):
            g = pull(rc, fs)
            if g: return g, fs
        return {}, None
    g, fs = get(REPRT[qn])
    if not g: return None
    if qn in (1, 2, 3):
        return {k: v[0] for k, v in g.items()}, fs
    p3 = pull(REPRT[3], fs)   # 같은 재무제표 구분(연결/별도)의 3Q 누적
    out = {}
    for k, v in g.items():
        nine = p3.get(k, (None, None))[1] if p3 else None
        out[k] = (v[0] - nine) if nine is not None else None
    return out, fs

def trailing(corp):
    """직전 4개 확정 분기 합산. 최신 분기부터 거슬러 최대 8분기 탐색."""
    y, q = TODAY.year, (TODAY.month - 1) // 3 + 1  # 현재 분기
    cands = []
    for _ in range(8):
        q -= 1
        if q == 0: q = 4; y -= 1
        cands.append((y, q))
    got = []
    for (yy, qq) in cands:
        r = dart_quarter(corp, yy, qq)
        if r and r[0].get('op') is not None:
            got.append(('%02dQ%d' % (yy % 100, qq), r[0], r[1]))
        if len(got) == 4: break
    if len(got) < 4:
        return None
    # 분기별 순이익 = 지배주주(nip) 우선, 없으면 전체(ni). 한 분기라도 둘 다 없으면 합산하지 않음(None) — 0 취급 금지
    op = sum(r.get('op') for _, r, _ in got)
    nq, basis = [], []
    for _, r, _ in got:
        v = r.get('nip') if r.get('nip') is not None else r.get('ni')
        nq.append(v); basis.append('nip' if r.get('nip') is not None else ('ni' if r.get('ni') is not None else None))
    ni_used = sum(nq) if all(v is not None for v in nq) else None
    ni_basis = '지배주주' if all(b == 'nip' for b in basis) else ('전체' if all(b == 'ni' for b in basis) else ('혼합' if ni_used is not None else '누락'))
    nip_all = sum(r['nip'] for _, r, _ in got) if all(r.get('nip') is not None for _, r, _ in got) else None
    ni_all = sum(r['ni'] for _, r, _ in got) if all(r.get('ni') is not None for _, r, _ in got) else None
    return {'quarters': [g[0] for g in got][::-1], 'fs': got[0][2],
            'op': op / 1e8, 'ni': (ni_all / 1e8) if ni_all is not None else None, 'nip': (nip_all / 1e8) if nip_all is not None else None,
            'ni_used': (ni_used / 1e8) if ni_used is not None else None, 'ni_basis': ni_basis,
            'detail': {g[0]: {k: round(v / 1e8, 1) for k, v in g[1].items() if v is not None} for g in got}}

# ── 메시지 ──
def ratio(cap, v):
    if cap is None or v is None or v == 0: return None
    return cap / v

def build_block(name, code, px, tr, fw, fnote):
    L = ['■ %s(%s)' % (name, code)]
    if px:
        L.append('현재가 {:,.0f}원 ({:+.1f}%) / 시총 {}'.format(px['price'], px.get('chg') or 0, fmt_cap(px['cap'])))
    else:
        L.append('현재가·시총 조회 실패')
    cap = px['cap'] if px else None
    if tr:
        ni = tr.get('ni_used')
        tag = {'지배주주': '', '전체': '(전체)', '혼합': '(지배/전체 혼합)'}.get(tr.get('ni_basis'), '')
        L.append('[트레일링 %s~%s%s] 영업이익 %s / 순이익 %s%s' % (
            tr['quarters'][0], tr['quarters'][-1], '' if tr['fs'] == 'CFS' else '·별도', fmt_eok(tr['op']),
            fmt_eok(ni) if ni is not None else '조회실패(분기 누락)', tag))
        L.append('  PER %s · P/OP %s' % (fmt_x(ratio(cap, ni)), fmt_x(ratio(cap, tr['op']))))
    else:
        L.append('[트레일링] DART 분기 실적 4개 확보 실패')
    if fw and fw.get('op') is not None:
        L.append('[12M Fwd·KIS리서치 %sE %d%%+%sE %d%%] 영업이익 %s / 순이익 %s' % (
            fw['fy1'][2:], round(fw['w1'] * 100), fw['fy2'][2:], round((1 - fw['w1']) * 100), fmt_eok(fw['op']), fmt_eok(fw['ni'])))
        L.append('  PER %s · P/OP %s%s' % (fmt_x(ratio(cap, fw['ni'])), fmt_x(ratio(cap, fw['op'])),
                                          (' (' + fw['note'] + ')') if fw.get('note') else ''))
    else:
        L.append('[12M Fwd] %s' % (fnote or '추정치 없음'))
    if px and px.get('per'):
        L.append('  참고 KIS PER %s(직전 결산 EPS 기준)' % fmt_x(px['per']))
    return '\n'.join(L)

def send_telegram(text):
    if not TG_TOKEN or not TG_CHAT:
        log('TELEGRAM_BOT_TOKEN/CHAT_ID 없음 → 발송 생략'); return False
    ok = True
    for i in range(0, len(text), 3900):
        chunk = text[i:i + 3900]
        for attempt in range(3):
            b = fetch('https://api.telegram.org/bot%s/sendMessage' % TG_TOKEN, None,
                      urllib.parse.urlencode({'chat_id': TG_CHAT, 'text': chunk, 'disable_web_page_preview': 'true'}).encode())
            try: j = json.loads(b.decode())
            except Exception: j = {}
            if j.get('ok'): break
            log('텔레그램 전송 실패(%d): %s' % (attempt + 1, str(j)[:150])); time.sleep(5)
        else:
            ok = False
    log('텔레그램 전송 %s' % ('OK' if ok else '실패'))
    return ok

def main():
    if not APPKEY or not APPSECRET: log('KIS 키 없음'); sys.exit(1)
    if not DART_KEY: log('DART_KEY 없음')
    token = kis_token()
    if not token: log('KIS 토큰 실패')
    open_day = kis_holiday(token) if token else None
    log('개장일: %s' % open_day)
    corps = dict(CORP_FIXED)   # corpCode.xml 은 상수 누락/조회 실패 시에만 폴백
    res, blocks = {}, []
    t0 = time.time()
    for code, name in TARGETS:
        px = kis_price(token, code) if token else {}
        est = kis_estimate(token, code) if token else {}
        fy, fnote = parse_estimate(est) if est else ({}, 'KIS 토큰 없음')
        fw = forward12(fy) if fy else None
        corp = corps.get(code)
        tr = None
        if DART_KEY:
            for attempt in (1, 2):
                if corp:
                    try: tr = trailing(corp)
                    except Exception as e: log('%s 트레일링 예외 %r' % (name, e))
                if tr or attempt == 2: break
                log('%s corp_code %s 로 DART 분기 확보 실패 → corpCode.xml 폴백' % (name, corp))
                fb = corp_map(); log('DART corp_map %d' % len(fb))
                corp = fb.get(code) or corp
        # 검증: 계산 PER(시총÷트레일링 순이익) vs KIS PER(직전 결산 EPS) 괴리 30% 초과면 debug 기록 (고성장·계정 누락 진단용)
        chk = None
        if px and px.get('per') and tr and tr.get('ni_used'):
            my = ratio(px['cap'], tr['ni_used'])
            if my: chk = round(my / px['per'] - 1, 3)
            if chk is not None and abs(chk) > 0.3:
                log('%s PER 괴리 %.0f%% (계산 %.1f vs KIS %.1f, 순이익 기준 %s)' % (name, chk * 100, my, px['per'], tr.get('ni_basis')))
        res[code] = {'name': name, 'corp_code': corp, 'price': px, 'trailing': tr, 'fy': fy, 'fwd12': fw, 'fnote': fnote,
                     'per_gap_vs_kis': chk, 'estimate_raw': est}
        blocks.append(build_block(name, code, px, tr, fw, fnote))
        time.sleep(0.3)
    log('종목 처리 %.0f초' % (time.time() - t0))
    now = datetime.datetime.now(KST)
    head = '📊 밸류 체크 %s %s KST%s' % (TODAY.isoformat(), now.strftime('%H:%M'), '' if open_day is not False else ' — 휴장일(전 거래일 종가)')
    tail = ('※ 트레일링=DART 직전 4개 분기 합산(연결·지배주주 순이익 우선), 12M Fwd=KIS 종목추정실적(한국투자증권 리서치 단일 추정, 컨센서스 아님) FY1·FY2 잔여기간 가중. '
            'PER=시총÷순이익, P/OP=시총÷영업이익. 조회 실패 항목은 표기 그대로(추정치로 채우지 않음).')
    text = head + '\n\n' + '\n\n'.join(blocks) + '\n\n' + tail
    print(text)
    sent = False
    if open_day is False and not FORCE:
        log('휴장일 → 발송 생략')
    else:
        sent = send_telegram(text)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump({'updated': datetime.datetime.now(KST).strftime('%Y-%m-%d %H:%M'), 'open_day': open_day, 'sent': sent,
               'message': text, 'debug': DEBUG, 'items': res}, open(OUT, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)

if __name__ == '__main__':
    main()
