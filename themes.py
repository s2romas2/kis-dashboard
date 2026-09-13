#!/usr/bin/env python3
# 테마 섹터 지수 — 구성종목은 themes_def.json(종목명), 주가는 KIS 주봉·월봉, 시총가중 직접 계산
#
# 왜 필요한가: KIS에는 거래소 업종지수만 있고 '테스트소켓·원자력·AI반도체장비' 같은 테마 지수가 없다.
#   → 테마별 구성종목을 정의해 두고(themes_def.json), 종목 주봉/월봉을 받아 시총가중으로 지수를 만든다.
#   랭크테이블(ranktable.html)의 '테마' 뷰가 이 파일(themes.json)을 읽어 주간·월간 순위/누적수익률/신규부상을 그린다.
#
# ⚠️ 생존편향: 과거 구간도 '현재' 구성종목·'현재' 시총가중으로 계산한다.
# 필요 시크릿: KIS_APPKEY, KIS_APPSECRET
# 입력: themes_def.json(루트), public/data/products.json(이름→코드), public/data/stockvals.json(시총)
# 산출: public/data/themes.json        (테마별 주간·월간 지수 + 종목별 트레일링 수익률)
#       public/data/themeswk.json      (종목 주봉 캐시)
#       public/data/wicsmon.json       (종목 월봉 캐시 — wics.py와 공유)
import os, sys, json, time, re, datetime, urllib.request

APPKEY = os.environ.get('KIS_APPKEY', '')
APPSECRET = os.environ.get('KIS_APPSECRET', '')
BASE = 'https://openapi.koreainvestment.com:9443'
DEF = 'themes_def.json'
OUT, WK, MON = 'public/data/themes.json', 'public/data/themeswk.json', 'public/data/wicsmon.json'
PRODUCTS, SV = 'public/data/products.json', 'public/data/stockvals.json'
NWEEK = int(os.environ.get('NWEEK', '120'))    # 보관 주봉 수(52주 누적 + 52주 표시 + 여유)
NMON = int(os.environ.get('NMON', '72'))       # 보관 월봉 수
DEBUG = []

def log(s):
    DEBUG.append(str(s)[:120])
    print(s, file=sys.stderr)

def load(p, d=None):
    try:
        return json.load(open(p, encoding='utf-8'))
    except Exception:
        return d if d is not None else {}

def dump(p, obj):
    os.makedirs(os.path.dirname(p) or '.', exist_ok=True)
    json.dump(obj, open(p, 'w', encoding='utf-8'), ensure_ascii=False)

def norm(s):
    return re.sub(r'[\s&\.\-·_()（）,]', '', str(s)).lower()

def jget(url, headers, tries=3):
    for i in range(tries):
        try:
            return json.loads(urllib.request.urlopen(
                urllib.request.Request(url, headers=headers), timeout=25).read().decode('utf-8', 'ignore'))
        except Exception:
            if i == tries - 1:
                raise
            time.sleep(1.2)

def kis_token():
    for a in range(4):
        try:
            req = urllib.request.Request(BASE + '/oauth2/tokenP',
                data=json.dumps({'grant_type': 'client_credentials',
                                 'appkey': APPKEY, 'appsecret': APPSECRET}).encode(),
                headers={'content-type': 'application/json'})
            t = json.loads(urllib.request.urlopen(req, timeout=20).read().decode())
            if t.get('access_token'):
                return t['access_token']
        except Exception as e:
            log('토큰 %d: %s' % (a + 1, str(e)[:40]))
        time.sleep(65)
    return None

def candles(code, hdr, d1, d2, period):
    """종목 기간별 시세 {YYYYMMDD: close} — 1콜 최대 100봉"""
    url = (BASE + '/uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice'
           '?FID_COND_MRKT_DIV_CODE=J&FID_INPUT_ISCD=%s&FID_INPUT_DATE_1=%s&FID_INPUT_DATE_2=%s'
           '&FID_PERIOD_DIV_CODE=%s&FID_ORG_ADJ_PRC=0' % (code, d1, d2, period))
    j = jget(url, hdr)
    if not (j.get('output2') or []) and ('EGW00201' in str(j) or '초당' in str(j.get('msg1', ''))):
        time.sleep(0.8)
        j = jget(url, hdr)
    out = {}
    for r in (j.get('output2') or []):
        d, c = (r.get('stck_bsop_date') or '').strip(), r.get('stck_clpr')
        if d and c:
            try:
                v = float(c)
                if v > 0:
                    out[d] = v
            except Exception:
                pass
    return out

def ymd(days_ago):
    return (datetime.date.today() - datetime.timedelta(days=days_ago)).strftime('%Y%m%d')

def week_key(d):
    """YYYYMMDD → ISO 주 키 'YYYYWww' (같은 주는 같은 키)"""
    try:
        y, w, _ = datetime.date(int(d[:4]), int(d[4:6]), int(d[6:8])).isocalendar()
        return '%04dW%02d' % (y, w)
    except Exception:
        return None

# ---------- 1) 정의 로드 · 이름→코드 해석 ----------
def resolve_all(defn, pmap):
    alias = defn.get('alias') or {}
    byname = {}
    for c, v in pmap.items():
        if not re.match(r'^\d{6}$', c):
            continue
        k = norm(v.get('n') or '')
        if k and k not in byname:
            byname[k] = c
    unresolved = []
    themes = []
    for t in defn.get('themes') or []:
        codes, names = [], {}
        for ent in t.get('s') or []:
            parts = str(ent).split('|')
            nm, code = parts[0].strip(), (parts[1].strip() if len(parts) > 1 else None)
            key = norm(alias.get(nm, nm))
            c = byname.get(key)
            if not c and code and code in pmap:
                c = code
            if not c:
                unresolved.append('%s:%s' % (t.get('n'), nm))
                continue
            if c not in codes:
                codes.append(c)
                names[c] = (pmap.get(c) or {}).get('n') or nm
        themes.append({'id': t['id'], 'n': t['n'], 'g': t.get('g', ''), 'codes': codes, 'names': names})
    return themes, unresolved

# ---------- 2) 시세 수집 ----------
def fetch_weekly(codes, hdr, wk):
    px = wk.setdefault('px', {})
    today = datetime.date.today().strftime('%Y%m%d')
    cur_wk = week_key(today)
    got = 0
    for c in codes:
        have = px.get(c) or {}
        last = max(have) if have else ''
        try:
            if have and last and week_key(last) == cur_wk and len(have) >= 60:
                continue                                    # 이번 주 봉 이미 있음
            if have and len(have) >= 60:
                new = candles(c, hdr, ymd(70), today, 'W')  # 증분: 최근 10주
            else:
                new = candles(c, hdr, ymd(1150), ymd(580), 'W')
                time.sleep(0.09)
                new.update(candles(c, hdr, ymd(590), today, 'W'))
            if new:
                have.update(new)
                px[c] = dict(sorted(have.items())[-NWEEK:])
                got += 1
        except Exception as e:
            if len(DEBUG) < 30:
                log('%s 주봉 %s' % (c, str(e)[:30]))
        time.sleep(0.09)
    wk['built'] = time.strftime('%Y-%m-%d %H:%M')
    log('주봉 신규/갱신 %d · 캐시 %d종목' % (got, len(px)))

def fetch_monthly(codes, hdr, mon):
    px = mon.setdefault('px', {})
    today = datetime.date.today()
    cur = today.strftime('%Y%m')
    got = 0
    for c in codes:
        have = px.get(c) or {}
        if have and cur in have:
            continue
        try:
            d1 = (today - datetime.timedelta(days=8 * 365)).strftime('%Y%m%d')
            raw = candles(c, hdr, d1, today.strftime('%Y%m%d'), 'M')
            m = {}
            for d, v in sorted(raw.items()):
                m[d[:6]] = v                                # 같은 달은 마지막 봉
            if m:
                have.update(m)
                px[c] = dict(sorted(have.items())[-100:])
                got += 1
        except Exception as e:
            if len(DEBUG) < 30:
                log('%s 월봉 %s' % (c, str(e)[:30]))
        time.sleep(0.09)
    mon['built'] = time.strftime('%Y-%m-%d %H:%M')
    log('월봉 신규/갱신 %d · 캐시 %d종목' % (got, len(px)))

# ---------- 3) 지수 계산 ----------
def build_index(members, series, periods, caps):
    """members: [code], series: {code:{period:close}}, periods: 정렬된 기간키 → 지수 리스트(100 시작)"""
    mem = [c for c in members if c in series]
    if len(mem) < 3:
        return None
    ser = []
    for i, p in enumerate(periods):
        if i == 0:
            ser.append(100.0); continue
        num = den = 0.0
        for c in mem:
            a, b = series[c].get(periods[i - 1]), series[c].get(p)
            if a and b and a > 0:
                w = caps.get(c) or 0
                if w <= 0:
                    continue
                num += w * (b / a - 1); den += w
        ser.append(round(ser[-1] * (1 + (num / den if den else 0)), 2))
    return ser

def trailing(closes_sorted, n):
    """정렬된 [(key, close)] 마지막 대비 n칸 전 수익률(%)"""
    if len(closes_sorted) <= n:
        return None
    a, b = closes_sorted[-1 - n][1], closes_sorted[-1][1]
    return round((b / a - 1) * 100, 1) if a else None

def main():
    defn = load(DEF)
    if not defn.get('themes'):
        log('themes_def.json 없음/비어있음 — 중단'); return
    pmap = (load(PRODUCTS) or {}).get('map') or {}
    if len(pmap) < 500:
        log('products.json 부족(%d) — 중단' % len(pmap)); return
    sv = (load(SV) or {}).get('map') or {}
    themes, unresolved = resolve_all(defn, pmap)
    all_codes = sorted({c for t in themes for c in t['codes']})
    caps = {}
    nocap = 0
    for c in all_codes:
        cap = 0
        try:
            cap = (sv.get(c) or [None, None, 0])[2] or 0
        except Exception:
            cap = 0
        caps[c] = cap
        if not cap:
            nocap += 1
    log('테마 %d · 종목 %d · 미해석 %d · 시총없음 %d' % (len(themes), len(all_codes), len(unresolved), nocap))
    if unresolved:
        log('미해석: ' + ', '.join(unresolved[:40]))

    wk = load(WK, {'v': 1, 'px': {}})
    mon = load(MON, {'v': 1, 'px': {}})
    if not APPKEY or not APPSECRET:
        log('KIS 시크릿 없음 — 캐시로만 계산')
        hdr = None
    else:
        tok = kis_token()
        hdr = None if not tok else {'content-type': 'application/json', 'authorization': 'Bearer ' + tok,
                                    'appkey': APPKEY, 'appsecret': APPSECRET,
                                    'tr_id': 'FHKST03010100', 'custtype': 'P'}
        if not hdr:
            log('토큰 실패 — 캐시로만 계산')
    if hdr:
        fetch_weekly(all_codes, hdr, wk)
        dump(WK, wk)
        fetch_monthly(all_codes, hdr, mon)
        dump(MON, mon)

    # 주봉: ISO 주 키로 정렬(종목마다 주 라벨 일자가 달라도 같은 주로 묶임)
    wpx, wlabel = {}, {}
    for c in all_codes:
        d = (wk.get('px') or {}).get(c) or {}
        m = {}
        for day, v in sorted(d.items()):
            k = week_key(day)
            if k:
                m[k] = v
                wlabel[k] = max(wlabel.get(k, ''), day)
        if m:
            wpx[c] = m
    weeks = sorted({k for c in wpx for k in wpx[c]})[-NWEEK:]
    # 월봉
    mpx = {c: ((mon.get('px') or {}).get(c) or {}) for c in all_codes}
    mpx = {c: v for c, v in mpx.items() if v}
    months = sorted({k for c in mpx for k in mpx[c]})[-NMON:]

    widx, midx, out_themes = {}, {}, []
    for t in themes:
        ws = build_index(t['codes'], wpx, weeks, caps)
        ms = build_index(t['codes'], mpx, months, caps)
        if ws:
            widx[t['id']] = ws
        if ms:
            midx[t['id']] = ms
        out_themes.append({'id': t['id'], 'n': t['n'], 'g': t['g'], 'cnt': len(t['codes']),
                           'members': t['codes']})
    log('주간 지수 %d테마 · 주 %d개 / 월간 지수 %d테마 · 월 %d개' % (len(widx), len(weeks), len(midx), len(months)))

    stocks = {}
    ytd_base = str(datetime.date.today().year - 1) + '12'
    for c in all_codes:
        nm = (pmap.get(c) or {}).get('n') or c
        e = {'n': nm, 'cap': caps.get(c) or 0}
        w = sorted((wpx.get(c) or {}).items())
        m = sorted((mpx.get(c) or {}).items())
        e['w4'], e['w13'], e['w26'], e['w52'] = trailing(w, 4), trailing(w, 13), trailing(w, 26), trailing(w, 52)
        e['m3'], e['m6'], e['m12'] = trailing(m, 3), trailing(m, 6), trailing(m, 12)
        base = dict(m).get(ytd_base)
        e['ytd'] = round((m[-1][1] / base - 1) * 100, 1) if (m and base) else None
        stocks[c] = e

    out = {'updated': time.strftime('%Y-%m-%d %H:%M'),
           'groups': sorted({t['g'] for t in themes if t['g']}),
           'themes': out_themes,
           'weeks': [wlabel.get(k, k) for k in weeks], 'widx': widx,
           'months': months, 'midx': midx,
           'stocks': stocks,
           'note': '구성종목은 themes_def.json(수동 정의), 수익률은 KIS 주봉·월봉 시총가중 직접 계산. 과거 구간도 현재 구성종목·현재 시총 기준이라 생존편향이 있음.',
           'debug': DEBUG}
    prev = load(OUT)
    if not widx and prev.get('widx'):
        prev['debug'] = DEBUG + ['계산 실패 — 기존 유지']
        dump(OUT, prev)
        return
    dump(OUT, out)
    print('저장 %s — 테마 %d · 주 %d · 월 %d' % (OUT, len(out_themes), len(weeks), len(months)), file=sys.stderr)

if __name__ == '__main__':
    main()
