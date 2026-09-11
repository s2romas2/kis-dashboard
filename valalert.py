#!/usr/bin/env python3
# 텔레그램 밸류 알림 — 평일 09:00 KST
#   현재가·시총 : KIS 오픈API inquire-price (FHKST01010100)
#   트레일링    : DART fnlttSinglAcntAll(연결 우선) 직전 4개 분기 영업이익·순이익(지배주주 우선) 합산 → PER, P/OP
#   12M 포워드  : KIS 종목추정실적(HHKST668300C0) 연간 컨센서스 FY1·FY2를 잔여개월로 가중 → PER, P/OP
#   발송        : 텔레그램 sendMessage (TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID)
# 결과: public/data/valalert.json (대시보드·디버그용, 추정실적 원본 응답 포함)
# 원칙: 못 구한 값은 지어내지 않고 '조회 실패'로 표기. 목표주가·투자의견은 싣지 않음.
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

def parse_estimate(est):
    """추정실적 → {'FY': {'2026': {'rv','op','ni'}, ...}, 'note'}.
    output4.dt = 결산년월 목록(5개), output2 = 항목별 data1~5(매출액·영업이익·순이익 순으로 가정, 라벨 있으면 라벨 사용).
    구조가 가정과 다르면 빈 dict 반환(→ 포워드 '파싱 실패' 표기, 숫자 지어내지 않음)."""
    try:
        o4 = est.get('output4') or []
        periods = [str(r.get('dt') or '').strip() for r in o4] if isinstance(o4, list) else []
        if not periods:
            return {}, 'output4(결산년월) 없음'
        o2 = est.get('output2') or []
        if isinstance(o2, dict): o2 = [o2]
        rows = []
        for r in o2:
            vals = [tonum(r.get('data%d' % i)) for i in range(1, 6)]
            label = ''
            for k, v in r.items():
                if not str(k).startswith('data') and isinstance(v, str) and re.search(r'[가-힣A-Za-z]', v):
                    label = v; break
            rows.append((label, vals))
        want = {'rv': ('매출액', '매출'), 'op': ('영업이익',), 'ni': ('당기순이익', '순이익')}
        pick = {}
        for key, names in want.items():
            for label, vals in rows:
                if label and any(n in label.replace(' ', '') for n in names) and '률' not in label and '율' not in label:
                    pick[key] = vals; break
        note = '라벨 매칭'
        if len(pick) < 3:
            # 라벨이 없으면 KIS 문서 순서(매출액, 증감율, 영업이익, 증감율, 순이익, 증감율)로 가정
            if len(rows) >= 5 and not any(l for l, _ in rows):
                pick = {'rv': rows[0][1], 'op': rows[2][1], 'ni': rows[4][1]}; note = '위치 가정(라벨 없음) — 검증 필요'
            else:
                return {}, '항목 라벨 매칭 실패: %s' % [l for l, _ in rows][:8]
        fy = {}
        for i, p in enumerate(periods):
            m = re.search(r'(20\d\d)', p)
            if not m: continue
            y = m.group(1)
            fy[y] = {'rv': pick['rv'][i], 'op': pick['op'][i], 'ni': pick['ni'][i], 'label': p}
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
def corp_map():
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

def dart_quarter(corp, y, qn):
    """해당 분기 3개월 [영업이익, 당기순이익, 지배주주순이익] (원). 연결(CFS) 우선, 없으면 별도(OFS).
    Q1~Q3: thstrm_amount=3개월, Q4: 사업보고서 연간 − 3Q 누적."""
    def pull(rc, fs):
        d = jget('%s/fnlttSinglAcntAll.json?crtfc_key=%s&corp_code=%s&bsns_year=%d&reprt_code=%s&fs_div=%s'
                 % (DART, DART_KEY, corp, y, rc, fs))
        rows = d.get('list') or []
        got = {}
        for r in rows:
            if r.get('sj_div') not in ('IS', 'CIS'): continue
            nm = (r.get('account_nm') or '').replace(' ', ''); aid = r.get('account_id') or ''
            cur, cum = tonum(r.get('thstrm_amount')), tonum(r.get('thstrm_add_amount'))
            if cur is None: continue
            key = None
            if aid == 'ifrs-full_ProfitLossAttributableToOwnersOfParent' or (('지배' in nm) and ('순이익' in nm or '당기순손익' in nm) and '비지배' not in nm):
                key = 'nip'
            elif aid == 'ifrs-full_ProfitLoss' or nm in ('당기순이익', '당기순이익(손실)', '당기순손익', '분기순이익', '분기순이익(손실)', '반기순이익', '반기순이익(손실)', '연결당기순이익'):
                key = 'ni'
            elif nm in ('영업이익', '영업이익(손실)', '영업손익'):
                key = 'op'
            if key and key not in got:
                got[key] = (cur, cum if cum is not None else cur)
        return got
    def get(rc):
        for fs in ('CFS', 'OFS'):
            g = pull(rc, fs); time.sleep(0.15)
            if g: return g, fs
        return {}, None
    g, fs = get(REPRT[qn])
    if not g: return None
    if qn in (1, 2, 3):
        return {k: v[0] for k, v in g.items()}, fs
    p3, _ = get(REPRT[3])
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
    s = {'op': 0, 'ni': 0, 'nip': 0, 'nip_ok': True}
    for _, r, _ in got:
        s['op'] += r.get('op') or 0
        s['ni'] += r.get('ni') if r.get('ni') is not None else 0
        if r.get('nip') is None: s['nip_ok'] = False
        else: s['nip'] += r['nip']
    return {'quarters': [g[0] for g in got][::-1], 'fs': got[0][2],
            'op': s['op'] / 1e8, 'ni': s['ni'] / 1e8, 'nip': (s['nip'] / 1e8) if s['nip_ok'] else None,
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
        ni = tr['nip'] if tr['nip'] is not None else tr['ni']
        L.append('[트레일링 %s~%s%s] 영업이익 %s / 순이익 %s%s' % (
            tr['quarters'][0], tr['quarters'][-1], '' if tr['fs'] == 'CFS' else '·별도', fmt_eok(tr['op']), fmt_eok(ni),
            '' if tr['nip'] is not None else '(전체)'))
        L.append('  PER %s · P/OP %s' % (fmt_x(ratio(cap, ni)), fmt_x(ratio(cap, tr['op']))))
    else:
        L.append('[트레일링] DART 분기 실적 4개 확보 실패')
    if fw and fw.get('op') is not None:
        L.append('[12M Fwd %sE %d%%+%sE %d%%] 영업이익 %s / 순이익 %s' % (
            fw['fy1'][2:], round(fw['w1'] * 100), fw['fy2'][2:], round((1 - fw['w1']) * 100), fmt_eok(fw['op']), fmt_eok(fw['ni'])))
        L.append('  PER %s · P/OP %s%s' % (fmt_x(ratio(cap, fw['ni'])), fmt_x(ratio(cap, fw['op'])),
                                          (' (' + fw['note'] + ')') if fw.get('note') else ''))
    else:
        L.append('[12M Fwd] 컨센서스 조회 실패 — %s' % (fnote or '추정치 없음'))
    if px and px.get('per'):
        L.append('  참고 KIS PER %s' % fmt_x(px['per']))
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
    corps = corp_map() if DART_KEY else {}
    log('DART corp_map %d' % len(corps))
    res, blocks = {}, []
    for code, name in TARGETS:
        px = kis_price(token, code) if token else {}
        est = kis_estimate(token, code) if token else {}
        fy, fnote = parse_estimate(est) if est else ({}, 'KIS 토큰 없음')
        fw = forward12(fy) if fy else None
        corp = corps.get(code)
        tr = None
        if corp:
            try: tr = trailing(corp)
            except Exception as e: log('%s 트레일링 예외 %r' % (name, e))
        else:
            log('%s DART corp_code 없음' % name)
        res[code] = {'name': name, 'price': px, 'trailing': tr, 'fy': fy, 'fwd12': fw, 'fnote': fnote, 'estimate_raw': est}
        blocks.append(build_block(name, code, px, tr, fw, fnote))
        time.sleep(0.3)
    head = '📊 밸류 체크 %s (09:00 KST)%s' % (TODAY.isoformat(), '' if open_day is not False else ' — 휴장일(전 거래일 종가)')
    tail = ('※ 트레일링=DART 직전 4개 분기 합산(연결·지배주주 순이익 우선), 12M Fwd=KIS 종목추정실적 컨센서스 FY1·FY2 잔여기간 가중. '
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
