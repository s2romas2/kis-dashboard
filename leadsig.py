#!/usr/bin/env python3
# 📡 주도주 신호 스캐너 — 주봉 이평선 4·13·26·52주 배열 기반
# 규칙(사용자 정의):
#  · 4>13>26>52 정배열 시작 = 첫 신호 / 13>26>52 유지 중 4-13 교차는 단기 노이즈
#  · 13-26 데드크로스 = 힘 꺾이기 시작(경고) / 4-26 데드크로스 = 완전 이탈
#  · 이익성장률(QoQ)이 꺾이기 시작하면 위험 (screener.json opqSeries 조인)
# 대상: 시총 상위 CAP_TOP 종목(stockvals.json) / 주봉: KIS 기간별시세(수정주가) 2구간 ≈ 200주
# 결과: public/data/leadsig.json
import os, sys, json, time, re, urllib.request, datetime

APPKEY = os.environ.get('KIS_APPKEY', '')
APPSECRET = os.environ.get('KIS_APPSECRET', '')
BASE = 'https://openapi.koreainvestment.com:9443'
OUT = 'public/data/leadsig.json'
CAP_TOP = int(os.environ.get('CAP_TOP', '1000'))
LIMIT = int(os.environ.get('LIMIT', '0'))       # 테스트용
RECENT_NEW = 8    # 정배열 시작 후 N주 이내 = '신규 진입'
RECENT_EVT = 12   # 데드크로스 발생 후 N주 이내만 경고/이탈로 노출
DEBUG = []

def post_json(url, body):
    req = urllib.request.Request(url, data=json.dumps(body).encode(),
                                 headers={'content-type': 'application/json'})
    return json.loads(urllib.request.urlopen(req, timeout=20).read().decode())

def get_json(url, headers):
    req = urllib.request.Request(url, headers=headers)
    return json.loads(urllib.request.urlopen(req, timeout=20).read().decode())

def get_token():
    for attempt in range(4):  # 발급 1분 1회 제한
        try:
            tok = post_json(BASE + '/oauth2/tokenP',
                            {'grant_type': 'client_credentials', 'appkey': APPKEY, 'appsecret': APPSECRET})
        except Exception as e:
            tok = {'error': repr(e)}
        if tok.get('access_token'):
            return tok['access_token']
        DEBUG.append('토큰 시도%d 실패: %s' % (attempt + 1, str(tok)[:120]))
        time.sleep(65)
    return None

def weekly_closes(code, hdr):
    """주봉 종가(수정주가) 오름차순 [(YYYYMMDD, close)] — 2구간 조회로 ~200주"""
    today = datetime.date.today()
    ranges = [(today - datetime.timedelta(days=699), today),
              (today - datetime.timedelta(days=1440), today - datetime.timedelta(days=700))]
    rows = {}
    for (d1, d2) in ranges:
        url = (BASE + '/uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice'
               '?FID_COND_MRKT_DIV_CODE=J&FID_INPUT_ISCD=%s&FID_INPUT_DATE_1=%s&FID_INPUT_DATE_2=%s'
               '&FID_PERIOD_DIV_CODE=W&FID_ORG_ADJ_PRC=0'
               % (code, d1.strftime('%Y%m%d'), d2.strftime('%Y%m%d')))
        j = get_json(url, hdr)
        if not (j.get('output2') or []):
            if 'EGW00201' in str(j) or '초당' in str(j.get('msg1', '')):
                time.sleep(0.6)
                j = get_json(url, hdr)
        for r in (j.get('output2') or []):
            d, c = (r.get('stck_bsop_date') or '').strip(), r.get('stck_clpr')
            if d and c:
                try:
                    rows[d] = float(c)
                except Exception:
                    pass
        time.sleep(0.08)
    return sorted(rows.items())

def sma(vals, n, i):
    if i + 1 < n:
        return None
    return sum(vals[i - n + 1:i + 1]) / n

def analyze(wk):
    """wk: [(date, close)] 오름차순 → 상태·이벤트. 데이터 부족 시 None"""
    if len(wk) < 56:
        return None
    closes = [c for _, c in wk]
    dates = [d for d, _ in wk]
    N = len(closes)
    ma = {}
    for n in (4, 13, 26, 52):
        ma[n] = [sma(closes, n, i) for i in range(N)]
    # ma52가 있는 구간만 판정
    idx0 = next((i for i in range(N) if ma[52][i] is not None), None)
    if idx0 is None or idx0 > N - 2:
        return None
    core = [None] * N     # 13>26>52 (노이즈 허용 정배열)
    strict = [None] * N   # 4>13>26>52
    for i in range(idx0, N):
        core[i] = ma[13][i] > ma[26][i] > ma[52][i]
        strict[i] = core[i] and ma[4][i] > ma[13][i]
    L = N - 1
    # 크로스 이벤트 (마지막 발생 인덱스)
    def last_cross_down(a, b):
        for i in range(L, idx0, -1):
            if ma[a][i] < ma[b][i] and ma[a][i - 1] >= ma[b][i - 1]:
                return i
        return None
    dc1326, dc426 = last_cross_down(13, 26), last_cross_down(4, 26)
    if core[L]:
        run0 = L
        while run0 - 1 >= idx0 and core[run0 - 1]:
            run0 -= 1
        weeks = L - run0 + 1
        noise = sum(1 for i in range(run0, L + 1) if not strict[i])   # 4-13 노이즈 주수
        state = 'new' if weeks <= RECENT_NEW else 'hold'
        evt = {'arrStart': dates[run0], 'weeks': weeks, 'noise': noise, 'strictNow': bool(strict[L])}
    else:
        # 현재 상태까지 확인: 이탈 = 4<26 유지 중, 경고 = 13<26 유지 중(4는 회복했을 수 있음)
        if dc426 is not None and L - dc426 < RECENT_EVT and ma[4][L] < ma[26][L]:
            state, ei = 'dead', dc426
        elif dc1326 is not None and L - dc1326 < RECENT_EVT and ma[13][L] < ma[26][L]:
            state, ei = 'warn', dc1326
        else:
            return None
        # 직전에 정배열이었던 종목만 의미 있음(한 번도 주도주가 아니었던 종목의 DC는 제외)
        was_core = any(core[i] for i in range(max(idx0, ei - 26), ei))
        if not was_core:
            return None
        evt = {'evtDate': dates[ei], 'evtAgo': L - ei}
    # 차트용: 최근 80주 [date, close, ma4, ma13, ma26, ma52]
    s = max(idx0, N - 80)
    chart = [[dates[i][2:], round(closes[i]),
              round(ma[4][i]) if ma[4][i] else None, round(ma[13][i]) if ma[13][i] else None,
              round(ma[26][i]) if ma[26][i] else None, round(ma[52][i]) if ma[52][i] else None]
             for i in range(s, N)]
    return {'state': state, **evt, 'chart': chart,
            'chg13w': round((closes[L] / closes[L - 13] - 1) * 100, 1) if L >= 13 else None}

def op_trend(sc_map, code):
    """screener opqSeries → 최근 분기 OP·QoQ 나열 + 성장률 방향"""
    x = sc_map.get(code)
    if not x:
        return None
    ser = (x.get('opqSeries') or [])[-5:]
    if len(ser) < 2:
        return None
    qoqs = [s.get('qoq') for s in ser if s.get('qoq') is not None]
    trend = None
    if len(qoqs) >= 2:
        trend = 'accel' if qoqs[-1] > qoqs[-2] else ('slow' if qoqs[-1] < qoqs[-2] else 'flat')
    return {'ser': [[s['q'][2:].replace('Q', 'Q'), s.get('op'), s.get('qoq')] for s in ser],
            'trend': trend, 'opYoY': x.get('opYoY'), 'opQoQ': x.get('opQoQ')}

def main():
    if not APPKEY or not APPSECRET:
        print('KIS 키 없음 — 건너뜀(기존 유지)', file=sys.stderr)
        return
    sv = json.load(open('public/data/stockvals.json', encoding='utf-8'))['map']
    try:
        pm = json.load(open('public/data/products.json', encoding='utf-8'))['map']
    except Exception:
        pm = {}
    try:
        sc = {x['code']: x for x in json.load(open('public/data/screener.json', encoding='utf-8'))['list']}
    except Exception:
        sc = {}
    univ = sorted([(c, v) for c, v in sv.items() if v and v[2]], key=lambda x: -x[1][2])[:CAP_TOP]
    if LIMIT:
        univ = univ[:LIMIT]
    DEBUG.append('대상 %d종목(시총컷 %s억)' % (len(univ), format(univ[-1][1][2], ',') if univ else '-'))
    token = get_token()
    if not token:
        _dump(None)
        return
    hdr = {'content-type': 'application/json', 'authorization': 'Bearer ' + token,
           'appkey': APPKEY, 'appsecret': APPSECRET, 'tr_id': 'FHKST03010100', 'custtype': 'P'}
    out, fail = [], 0
    for i, (code, v) in enumerate(univ):
        try:
            wk = weekly_closes(code, hdr)
            r = analyze(wk)
            if r:
                info = pm.get(code) or {}
                name = info.get('n') if isinstance(info, dict) else None
                r.update({'code': code, 'name': name or (sc.get(code) or {}).get('name') or code,
                          'sector': (info.get('s') if isinstance(info, dict) else None) or '',
                          'cap': v[2], 'price': v[3], 'per': v[1], 'op': op_trend(sc, code)})
                out.append(r)
        except Exception as e:
            fail += 1
            if len(DEBUG) < 8:
                DEBUG.append('%s 예외 %r' % (code, str(e)[:60]))
            time.sleep(0.4)
        if i % 100 == 0:
            print('%d/%d… 신호 %d' % (i, len(univ), len(out)), file=sys.stderr)
    DEBUG.append('신호 %d건 (실패 %d)' % (len(out), fail))
    _dump(out)

def _dump(out):
    try:
        prev = json.load(open(OUT, encoding='utf-8'))
    except Exception:
        prev = {}
    if out is None or (prev.get('list') and len(out) < max(10, len(prev['list']) // 3)):
        # 토큰 실패·대량 장애 시 기존 유지
        DEBUG.append('수집 부족 — 기존 %d건 유지' % len(prev.get('list') or []))
        out2 = dict(prev)
        out2['debug'] = DEBUG[-8:]
    else:
        order = {'new': 0, 'hold': 1, 'warn': 2, 'dead': 3}
        out.sort(key=lambda x: (order.get(x['state'], 9), -(x.get('cap') or 0)))
        out2 = {'updated': time.strftime('%Y-%m-%d %H:%M'), 'count': len(out),
                'capTop': CAP_TOP, 'debug': DEBUG[-8:], 'list': out}
    os.makedirs('public/data', exist_ok=True)
    json.dump(out2, open(OUT, 'w', encoding='utf-8'), ensure_ascii=False)
    print('저장 %d건 %s' % (len(out2.get('list') or []), DEBUG[-3:]), file=sys.stderr)

if __name__ == '__main__':
    main()
