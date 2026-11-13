#!/usr/bin/env python3
# 📡 주도주 신호 스캐너 — 주봉 이평선 4·13·26·52주 배열 기반
# 규칙(사용자 정의):
#  · 4>13>26>52 정배열 시작 = 첫 신호 / 13>26>52 유지 중 4-13 교차는 단기 노이즈
#  · 13-26 데드크로스 = 힘 꺾이기 시작(경고) / 4-26 데드크로스 = 완전 이탈
#  · 이익성장률(QoQ)이 꺾이기 시작하면 위험 — 분기 실적은 DART 정기보고서(hege.json: 전 상장사 분기 매출·영업이익)에서 가져옴
#    (11/13 변경: 예전엔 screener.json만 써서 조건 미충족 종목은 실적이 비었음. screener는 더 최신 분기가 있을 때만 덧붙임)
#  · 헤게모니 4국면(hege.json)과 조합: A 신규 진입+초입 / B 정배열+2국면 / C 정배열+3·4국면 / D 초입인데 정배열 아님(watch)
#  · 조합별 진입일·진입가를 public/data/leadsig_track.json에 쌓아 이후 수익률로 검증
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

def _q(lbl):
    """'2Q26' 또는 '2026Q2' → '26Q2'"""
    m = re.match(r'^(\d)Q(\d{2})$', lbl or '')
    if m: return m.group(2) + 'Q' + m.group(1)
    m = re.match(r'^20(\d{2})Q(\d)$', lbl or '')
    return (m.group(1) + 'Q' + m.group(2)) if m else (lbl or '')

def _chg(cur, prev):
    if cur is None or prev is None or prev == 0: return None
    return round((cur - prev) / abs(prev) * 100, 1)

def _lab(cur, prev):
    """부호가 바뀌거나 둘 다 적자면 %가 오해를 부르므로 말로 표시"""
    if cur is None or prev is None: return ''
    if prev <= 0 < cur: return '흑전'
    if cur < 0 <= prev: return '적전'
    if cur < 0 and prev < 0: return '적자 축소' if cur > prev else '적자 확대'
    return ''

def op_dart(hrow, quarters, sc_row):
    """DART 분기 실적(hege) → 최근 5분기 [분기, 영업이익, QoQ, 매출, 영익 YoY, 표시, QoQ 말표시, YoY 말표시] + 성장률 방향. screener에 더 최신 분기가 있으면 덧붙임"""
    ser = []
    if hrow and hrow.get('q') in quarters:
        rev, op = hrow.get('rev') or [], hrow.get('op') or []
        e = quarters.index(hrow['q']); n = len(op); labs = quarters[max(0, e - n + 1):e + 1]
        if len(labs) == n:
            for i in range(n):
                ser.append([_q(labs[i]), None if op[i] is None else round(op[i]), _chg(op[i], op[i - 1]) if i >= 1 else None,
                            None if i >= len(rev) or rev[i] is None else round(rev[i]), _chg(op[i], op[i - 4]) if i >= 4 else None, '',
                            _lab(op[i], op[i - 1]) if i >= 1 else '', _lab(op[i], op[i - 4]) if i >= 4 else ''])
    if sc_row:
        have = {s[0] for s in ser}
        for s in (sc_row.get('opqSeries') or []):
            q = _q(s.get('q'))
            if ser and q > ser[-1][0] and q not in have:      # screener가 더 최신(잠정·신규 보고서)
                tb = next((t for t in (sc_row.get('table') or []) if t.get('q') == s.get('q')), {})
                ser.append([q, s.get('op'), s.get('qoq'), tb.get('rev'), None, '신규'])
        if not ser:
            ser = [[_q(s['q']), s.get('op'), s.get('qoq'), None, None, ''] for s in (sc_row.get('opqSeries') or [])]
    ser = ser[-5:]
    if len(ser) < 2: return None
    qoqs = [s[2] for s in ser if s[2] is not None]
    trend = None
    if len(qoqs) >= 2:
        trend = 'accel' if qoqs[-1] > qoqs[-2] else ('slow' if qoqs[-1] < qoqs[-2] else 'flat')
    return {'ser': ser, 'trend': trend, 'opYoY': ser[-1][4], 'opQoQ': ser[-1][2],
            'src': 'DART' if hrow else 'screener', 'fs': (hrow or {}).get('fs')}

def hg_info(hrow):
    if not hrow: return None
    return {'ph': hrow.get('ph'), 'q': hrow.get('q'), 'streak': hrow.get('streak'), 'new1': bool(hrow.get('new1')), 'entry2': bool(hrow.get('entry2')),
            'rg': hrow.get('rg'), 'og': hrow.get('og'), 'hist': hrow.get('hist')}

def combo(state, hrow):
    """A 신규 진입 + 헤게모니 초입 / B 정배열 + 2국면 / C 정배열 + 3·4국면 (D는 watch 목록)"""
    if not hrow or state not in ('new', 'hold'): return None
    early = hrow.get('new1') or hrow.get('entry2')
    if state == 'new' and early: return 'A'
    if hrow.get('ph') == 2 or early: return 'B'
    if hrow.get('ph') in (3, 4): return 'C'
    return None

def ma_flags(wk):
    """신호가 없는 종목의 현재 이평 배열: [4>13, 13>26, 26>52], 13주 수익률"""
    if len(wk) < 56: return None
    c = [x for _, x in wk]; L = len(c) - 1
    m = {n: sum(c[L - n + 1:L + 1]) / n for n in (4, 13, 26, 52)}
    return [m[4] > m[13], m[13] > m[26], m[26] > m[52]], round((c[L] / c[L - 13] - 1) * 100, 1)

def track(out, watch, sv):
    """조합별 진입 기록 → 이후 수익률. 과거로 되돌려 볼 주가가 없어(현재 신호 종목만 저장) 오늘부터 쌓는 방식"""
    P = 'public/data/leadsig_track.json'
    today = datetime.date.today()
    try: T = json.load(open(P, encoding='utf-8'))
    except Exception: T = {'start': today.isoformat(), 'recs': []}
    openk = {(r['c'], r['cb']) for r in T['recs'] if r.get('open')}
    cur = {}
    for x in out:
        if x.get('cb'): cur[(x['code'], x['cb'])] = x
        if x['state'] == 'new' and x.get('cb') != 'A': cur[(x['code'], 'N')] = x     # 대조군: 헤게모니 초입이 아닌 신규 진입
    for w in watch:
        cur[(w['code'], 'D')] = w
    for k, x in cur.items():
        if k not in openk and x.get('price'):
            T['recs'].append({'c': k[0], 'n': x.get('name'), 'cb': k[1], 'd0': today.isoformat(), 'p0': x['price'], 'open': True})
    for r in T['recs']:
        v = sv.get(r['c']); px = v[3] if v else None
        if not px or not r.get('p0'): continue
        days = (today - datetime.date.fromisoformat(r['d0'])).days
        ret = round((px / r['p0'] - 1) * 100, 1)
        r['last'], r['ret'], r['days'] = px, ret, days
        if days >= 28 and 'r4w' not in r: r['r4w'] = ret
        if days >= 91 and 'r13w' not in r: r['r13w'] = ret
        if r.get('open') and (r['c'], r['cb']) not in cur: r['open'] = False; r['d1'] = today.isoformat()
    T['recs'] = T['recs'][-6000:]
    def avg(v): return round(sum(v) / len(v), 1) if v else None
    summ = {}
    for cb in ('A', 'B', 'C', 'D', 'N'):
        g = [r for r in T['recs'] if r['cb'] == cb and r.get('ret') is not None]
        summ[cb] = {'n': len(g), 'open': sum(1 for r in g if r.get('open')), 'ret': avg([r['ret'] for r in g]),
                    'win': round(sum(1 for r in g if r['ret'] > 0) / len(g) * 100) if g else None,
                    'n4w': sum(1 for r in g if 'r4w' in r), 'r4w': avg([r['r4w'] for r in g if 'r4w' in r]),
                    'n13w': sum(1 for r in g if 'r13w' in r), 'r13w': avg([r['r13w'] for r in g if 'r13w' in r])}
    T['summary'] = summ; T['updated'] = time.strftime('%Y-%m-%d %H:%M')
    json.dump(T, open(P, 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'))
    DEBUG.append('추적 %d건 %s' % (len(T['recs']), {k: v['n'] for k, v in summ.items()}))

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
    try:
        hj = json.load(open('public/data/hege.json', encoding='utf-8'))
        hg = {r['c']: r for r in hj.get('rows') or []}; hq = hj.get('quarters') or []; hupd = hj.get('updated')
    except Exception:
        hg, hq, hupd = {}, [], None
    DEBUG.append('DART 분기 실적(hege) %d종목 · %s 기준 · 수집 %s' % (len(hg), hq[-1] if hq else '-', hupd))
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
    out, watch, fail = [], [], 0
    for i, (code, v) in enumerate(univ):
        try:
            wk = weekly_closes(code, hdr)
            r = analyze(wk)
            h = hg.get(code)
            info = pm.get(code) or {}
            name = (info.get('n') if isinstance(info, dict) else None) or (h or {}).get('n') or (sc.get(code) or {}).get('name') or code
            sector = (info.get('s') if isinstance(info, dict) else None) or ''
            if r:
                r.update({'code': code, 'name': name, 'sector': sector,
                          'cap': v[2], 'price': v[3], 'per': v[1], 'op': op_dart(h, hq, sc.get(code)),
                          'hg': hg_info(h), 'cb': combo(r['state'], h)})
                out.append(r)
            # D: 헤게모니 초입(1국면 신규·2국면 초입)인데 정배열이 아닌 종목 — 실적은 돌았는데 시장이 아직 안 본 관찰 목록
            if h and (h.get('new1') or h.get('entry2')) and not (r and r['state'] in ('new', 'hold')):
                mf = ma_flags(wk)
                watch.append({'code': code, 'name': name, 'sector': sector or h.get('sec') or '', 'cap': v[2], 'price': v[3],
                              'hg': hg_info(h), 'st': r['state'] if r else None, 'ma': mf[0] if mf else None, 'chg13w': mf[1] if mf else None})
        except Exception as e:
            fail += 1
            if len(DEBUG) < 8:
                DEBUG.append('%s 예외 %r' % (code, str(e)[:60]))
            time.sleep(0.4)
        if i % 100 == 0:
            print('%d/%d… 신호 %d' % (i, len(univ), len(out)), file=sys.stderr)
    DEBUG.append('신호 %d건 · 관찰 %d건 (실패 %d)' % (len(out), len(watch), fail))
    ok = _dump(out, watch, {'q': hq[-1] if hq else None, 'updated': hupd})
    if ok:
        try: track(out, watch, sv)
        except Exception as e: DEBUG.append('추적 기록 실패 %r' % e); print('track 실패', e, file=sys.stderr)

def _dump(out, watch=None, hmeta=None):
    try:
        prev = json.load(open(OUT, encoding='utf-8'))
    except Exception:
        prev = {}
    if out is None or (prev.get('list') and len(out) < max(10, len(prev['list']) // 3)):
        # 토큰 실패·대량 장애 시 기존 유지
        DEBUG.append('수집 부족 — 기존 %d건 유지' % len(prev.get('list') or []))
        out2 = dict(prev)
        out2['debug'] = DEBUG[-8:]
        ok = False
    else:
        ok = True
        order = {'new': 0, 'hold': 1, 'warn': 2, 'dead': 3}
        out.sort(key=lambda x: (order.get(x['state'], 9), -(x.get('cap') or 0)))
        watch = sorted(watch or [], key=lambda x: -(x.get('cap') or 0))
        out2 = {'updated': time.strftime('%Y-%m-%d %H:%M'), 'count': len(out),
                'capTop': CAP_TOP, 'hege': hmeta, 'debug': DEBUG[-8:], 'list': out, 'watch': watch}
    os.makedirs('public/data', exist_ok=True)
    json.dump(out2, open(OUT, 'w', encoding='utf-8'), ensure_ascii=False)
    print('저장 %d건 %s' % (len(out2.get('list') or []), DEBUG[-3:]), file=sys.stderr)
    return ok

if __name__ == '__main__':
    main()
