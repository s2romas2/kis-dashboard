#!/usr/bin/env python3
# WICS 중분류(산업그룹) 섹터 지수 — 구성종목은 WISE, 주가는 KIS 월봉
#
# 왜 직접 계산하나:
#   WISE 공개 API(GetIndexComponets)는 구성종목·시총은 주지만 과거 조회가 3개월 남짓이고,
#   시총 합계는 편입/편출·증자로 흔들려 수익률 대용으로 쓸 수 없다.
#   그래서 "구성종목만 WISE에서 받고, 수익률은 종목 월봉으로 시총가중 계산"한다.
#
# ⚠️ 생존편향: 과거 구간도 '현재' 구성종목으로 계산한다. 상장폐지·편출 종목이 빠져 과거가 실제보다 좋아 보일 수 있다.
#
# 필요 시크릿: KIS_APPKEY, KIS_APPSECRET
# 산출: public/data/wics.json      (섹터별 월봉 지수 + 기간 수익률)
#       public/data/wicsmap.json  (종목→섹터 매핑 캐시)
#       public/data/wicsmon.json  (종목 월봉 캐시)
import os, sys, json, time, datetime, urllib.request

APPKEY = os.environ.get('KIS_APPKEY', '')
APPSECRET = os.environ.get('KIS_APPSECRET', '')
BASE = 'https://openapi.koreainvestment.com:9443'
OUT, MAP, MON = 'public/data/wics.json', 'public/data/wicsmap.json', 'public/data/wicsmon.json'
WISE = 'https://www.wiseindex.com/Index/GetIndexComponets?ceil_yn=0&dt=%s&sec_cd=%s'
UA = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126 Safari/537.36'}
TOPN = int(os.environ.get('TOPN', '900'))      # 시총 상위 N종목만 지수 계산에 사용
MAP_AGE = int(os.environ.get('MAP_AGE', '7'))  # 매핑 캐시 유효일
DEBUG = []

SECS = {  # WICS 중분류 27개 (2026-09 실측 확인)
 'G1010':'에너지','G1510':'소재','G2010':'자본재','G2020':'상업서비스와공급품','G2030':'운송',
 'G2510':'자동차와부품','G2520':'내구소비재와의류','G2530':'호텔·레스토랑·레저','G2550':'소매(유통)',
 'G2560':'교육서비스','G3010':'식품과기본식료품소매','G3020':'식품·음료·담배','G3030':'가정용품과개인용품',
 'G3510':'건강관리장비와서비스','G3520':'제약과생물공학','G4010':'은행','G4020':'증권',
 'G4030':'다각화된금융','G4040':'보험','G4050':'부동산','G4510':'소프트웨어와서비스',
 'G4520':'기술하드웨어와장비','G4530':'반도체와반도체장비','G4540':'디스플레이',
 'G5010':'전기통신서비스','G5020':'미디어와엔터테인먼트','G5510':'유틸리티'}

def jget(url, headers=None, tries=3):
    for i in range(tries):
        try:
            return json.loads(urllib.request.urlopen(
                urllib.request.Request(url, headers=headers or UA), timeout=25).read().decode('utf-8', 'ignore'))
        except Exception:
            if i == tries - 1:
                raise
            time.sleep(1.5)

def load(p, d=None):
    try:
        return json.load(open(p, encoding='utf-8'))
    except Exception:
        return d if d is not None else {}

def build_map():
    """WISE에서 중분류별 구성종목 → {종목코드: 섹터코드}"""
    dt = datetime.date.today().strftime('%Y%m%d')
    m, meta = {}, {}
    for c, nm in SECS.items():
        ok = False
        for back in range(0, 6):                      # 휴장일 대비 최대 5일 소급
            d = (datetime.date.today() - datetime.timedelta(days=back)).strftime('%Y%m%d')
            try:
                r = jget(WISE % (d, c))
            except Exception as e:
                DEBUG.append('%s %s' % (c, repr(e)[:40])); break
            if (r.get('info') or {}).get('CNT'):
                for x in r['list']:
                    m[x['CMP_CD']] = c
                meta[c] = {'n': nm, 'cnt': r['info']['CNT'], 'dt': d}
                ok = True
                break
            time.sleep(0.3)
        if not ok and len(DEBUG) < 12:
            DEBUG.append('%s(%s) 구성종목 0' % (c, nm))
        time.sleep(0.35)
    return {'built': dt, 'map': m, 'meta': meta}

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
            DEBUG.append('토큰 %d: %s' % (a + 1, str(e)[:40]))
        time.sleep(65)
    return None

def monthly(code, hdr):
    """월봉 종가(수정주가) {YYYYMM: close} — 1콜 100봉 ≈ 8년"""
    today = datetime.date.today()
    d1 = (today - datetime.timedelta(days=8 * 365)).strftime('%Y%m%d')
    url = (BASE + '/uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice'
           '?FID_COND_MRKT_DIV_CODE=J&FID_INPUT_ISCD=%s&FID_INPUT_DATE_1=%s&FID_INPUT_DATE_2=%s'
           '&FID_PERIOD_DIV_CODE=M&FID_ORG_ADJ_PRC=0' % (code, d1, today.strftime('%Y%m%d')))
    j = jget(url, hdr)
    if not (j.get('output2') or []) and ('EGW00201' in str(j) or '초당' in str(j.get('msg1', ''))):
        time.sleep(0.7)
        j = jget(url, hdr)
    out = {}
    for r in (j.get('output2') or []):
        d, c = (r.get('stck_bsop_date') or '').strip(), r.get('stck_clpr')
        if d and c:
            try:
                out[d[:6]] = float(c)
            except Exception:
                pass
    return out

def main():
    # 1) 종목→섹터 매핑 (주 1회)
    mp = load(MAP)
    stale = True
    if mp.get('built'):
        try:
            age = (datetime.date.today() - datetime.date(int(mp['built'][:4]), int(mp['built'][4:6]), int(mp['built'][6:8]))).days
            stale = age >= MAP_AGE
        except Exception:
            stale = True
    if stale or not mp.get('map'):
        nm = build_map()
        if len(nm.get('map') or {}) > 500:
            mp = nm
            json.dump(mp, open(MAP, 'w', encoding='utf-8'), ensure_ascii=False)
        else:
            DEBUG.append('매핑 수집 부족(%d) — 기존 유지' % len(nm.get('map') or {}))
    if not mp.get('map'):
        DEBUG.append('매핑 없음 — 중단')
        json.dump({'updated': time.strftime('%Y-%m-%d %H:%M'), 'debug': DEBUG}, open(OUT, 'w', encoding='utf-8'), ensure_ascii=False)
        return

    # 2) 대상 종목 = 매핑 ∩ 시총 상위 TOPN
    sv = (load('public/data/stockvals.json') or {}).get('map') or {}
    names = (load('public/data/products.json') or {}).get('map') or {}
    cand = [(c, (sv.get(c) or [None, None, 0])[2] or 0) for c in mp['map'] if c in sv]
    cand.sort(key=lambda x: -x[1])
    codes = [c for c, _ in cand[:TOPN]]
    caps = {c: v for c, v in cand[:TOPN]}
    DEBUG.append('매핑 %d · 시총교집합 %d · 대상 %d' % (len(mp['map']), len(cand), len(codes)))

    # 3) 월봉 캐시 (없는 종목만 신규 수집 + 최근분 갱신)
    mon = load(MON, {'v': 1, 'px': {}})
    px = mon.get('px') or {}
    if not APPKEY or not APPSECRET:
        DEBUG.append('KIS 시크릿 없음 — 월봉 수집 건너뜀(기존 캐시로 계산)')
        hdr = None
    else:
        tok = kis_token()
        hdr = None if not tok else {'content-type': 'application/json', 'authorization': 'Bearer ' + tok,
                                    'appkey': APPKEY, 'appsecret': APPSECRET,
                                    'tr_id': 'FHKST03010100', 'custtype': 'P'}
        if not hdr:
            DEBUG.append('토큰 실패 — 기존 캐시로 계산')
    cur = datetime.date.today().strftime('%Y%m')
    need = [c for c in codes if c not in px or cur not in (px.get(c) or {})]
    got = 0
    if hdr:
        for c in need:
            try:
                m = monthly(c, hdr)
                if m:
                    px[c] = m; got += 1
            except Exception as e:
                if len(DEBUG) < 14:
                    DEBUG.append('%s 월봉 %s' % (c, str(e)[:30]))
            time.sleep(0.09)
    mon['px'] = px
    mon['built'] = time.strftime('%Y-%m-%d %H:%M')
    json.dump(mon, open(MON, 'w', encoding='utf-8'), ensure_ascii=False)
    DEBUG.append('월봉 신규/갱신 %d · 캐시 %d종목' % (got, len(px)))

    # 4) 섹터별 시총가중 월별 지수
    months = sorted({m for c in codes if c in px for m in px[c]})
    months = months[-97:]                      # 최근 8년
    idx, comp = {}, {}
    for sc, snm in SECS.items():
        mem = [c for c in codes if mp['map'].get(c) == sc and c in px]
        if len(mem) < 3:
            continue
        top = sorted(mem, key=lambda x: -caps.get(x, 0))[:10]
        comp[sc] = {'n': snm, 'cnt': len(mem),
                    'top': [{'c': c, 'n': (names.get(c) or {}).get('n') or c,
                             'cap': caps.get(c, 0)} for c in top]}
        ser = []
        for i, m in enumerate(months):
            if i == 0:
                ser.append(100.0); continue
            num = den = 0.0
            for c in mem:
                a, b = px[c].get(months[i-1]), px[c].get(m)
                if a and b and a > 0:
                    w = caps.get(c, 0) or 0
                    num += w * (b / a - 1); den += w
            ser.append(round(ser[-1] * (1 + (num / den if den else 0)), 2))
        idx[sc] = ser
    DEBUG.append('섹터 %d개 · 월 %d개' % (len(idx), len(months)))

    def ret(sc, n):
        s = idx.get(sc) or []
        if len(s) <= n or not s[-1 - n]:
            return None
        return round((s[-1] / s[-1 - n] - 1) * 100, 2)

    rows = []
    for sc, s in idx.items():
        rows.append({'c': sc, 'n': SECS[sc], 'cnt': comp[sc]['cnt'],
                     'm1': ret(sc, 1), 'm3': ret(sc, 3), 'm6': ret(sc, 6),
                     'y1': ret(sc, 12), 'y3': ret(sc, 36)})
    out = {'updated': time.strftime('%Y-%m-%d %H:%M'), 'months': months,
           'idx': idx, 'comp': comp, 'rows': rows, 'secs': SECS,
           'note': '구성종목은 WISE WICS 중분류, 수익률은 KIS 월봉 시총가중 직접 계산. 과거 구간도 현재 구성종목 기준이라 생존편향이 있음.',
           'debug': DEBUG}
    prev = load(OUT)
    if not idx and prev.get('idx'):
        prev['debug'] = DEBUG + ['계산 실패 — 기존 유지']
        json.dump(prev, open(OUT, 'w', encoding='utf-8'), ensure_ascii=False)
        return
    json.dump(out, open(OUT, 'w', encoding='utf-8'), ensure_ascii=False)
    print('저장 %s — 섹터 %d · 월 %d' % (OUT, len(idx), len(months)), file=sys.stderr)

if __name__ == '__main__':
    main()
