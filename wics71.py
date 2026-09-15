#!/usr/bin/env python3
# WICS 소분류 71개 섹터 지수 — 구성종목은 네이버금융 업종 분류(WICS 소분류 체계), 주가는 wics.py의 KIS 월봉 캐시(wicsmon.json) 재사용
#   참고: judoju.kboard.workers.dev/rank (WICS 업종 · 월간 시총가중 수익률 순위). 업종 목록은 tools/wics/sectors.json(71개).
#   WISE 공개 API는 소분류 빈 응답이라 네이버 업종 페이지(sise_group.naver?type=upjong → sise_group_detail.naver)를 EUC-KR로 파싱.
#   ⚠️ 생존편향·근사: 과거 구간도 현재 구성종목, 가중치는 현재 시총(stockvals). 시총 상위 TOPN 교집합만 사용(소형주 위주 업종은 종목 수 적음).
# 필요 시크릿: KIS_APPKEY, KIS_APPSECRET (캐시에 없는 종목 월봉만 신규 수집)
# 산출: public/data/wics71.json (wics.json과 같은 구조: updated, months, idx, comp, rows, secs, note, debug)
#       public/data/wics71map.json (업종→종목 매핑 캐시, 7일)
import os, sys, json, time, re, datetime, urllib.request

APPKEY = os.environ.get('KIS_APPKEY', '')
APPSECRET = os.environ.get('KIS_APPSECRET', '')
BASE = 'https://openapi.koreainvestment.com:9443'
OUT, MAP, MON = 'public/data/wics71.json', 'public/data/wics71map.json', 'public/data/wicsmon.json'
SECTORS_FILE = 'tools/wics/sectors.json'
NAVER_LIST = 'https://finance.naver.com/sise/sise_group.naver?type=upjong'
NAVER_DETAIL = 'https://finance.naver.com/sise/sise_group_detail.naver?type=upjong&no=%s'
UA = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126 Safari/537.36',
      'Referer': 'https://finance.naver.com/sise/'}
TOPN = int(os.environ.get('TOPN', '1500'))
MAP_AGE = int(os.environ.get('MAP_AGE', '7'))
MIN_MEMBERS = 2
DEBUG = []

def get(url, tries=3):
    for i in range(tries):
        try:
            return urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=25).read()
        except Exception as e:
            if i == tries - 1:
                DEBUG.append('GET 실패 %s → %s' % (url[:70], repr(e)[:120])); raise
            time.sleep(1.5)

def jget(url, headers=None, tries=3):
    for i in range(tries):
        try:
            return json.loads(urllib.request.urlopen(urllib.request.Request(url, headers=headers or UA), timeout=25).read().decode('utf-8', 'ignore'))
        except Exception:
            if i == tries - 1: raise
            time.sleep(1.5)

def load(p, d=None):
    try: return json.load(open(p, encoding='utf-8'))
    except Exception: return d if d is not None else {}

def norm(s):
    return re.sub(r'[\s·ㆍ]', '', s).replace('，', ',').strip()

NAVER_API = 'https://m.stock.naver.com/api/stocks/industry'   # 신형 네이버 증권 모바일 API (2026-09 확인: groups[{no,name,totalCount}])

def build_map_api(sectors):
    """네이버 모바일 API: /api/stocks/industry → 업종 목록(no·name), /api/stocks/industry/{no}?page&pageSize → 구성종목(itemCode)."""
    j = json.loads(get(NAVER_API + '?page=1&pageSize=200').decode('utf-8', 'ignore'))
    groups = j.get('groups') or []
    naver = {norm(g.get('name', '')): g for g in groups if g.get('no')}
    DEBUG.append('네이버 API 업종 %d개' % len(naver))
    want = {norm(s): s for s in sectors}
    miss = [s for k, s in want.items() if k not in naver]
    if miss: DEBUG.append('미매칭 %d: %s' % (len(miss), ', '.join(miss[:10])))
    extra = [k for k in naver if k not in want]
    if extra: DEBUG.append('네이버에만 있음 %d: %s' % (len(extra), ', '.join(extra[:12])))
    m = {}
    for k, s in want.items():
        g = naver.get(k)
        if not g: continue
        codes, total, b = [], int(g.get('totalCount') or 0), ''
        for page in range(1, 8):
            try:
                b = get('%s/%s?page=%d&pageSize=100' % (NAVER_API, g['no'], page), tries=2).decode('utf-8', 'ignore')
            except Exception as e:
                DEBUG.append('%s p%d 실패 %s' % (s, page, repr(e)[:60])); break
            found = [c for c in re.findall(r'"itemCode"\s*:\s*"([0-9A-Z]{6})"', b) if c not in codes]
            if not found: break
            codes += found
            if len(codes) >= total or len(found) < 100: break
            time.sleep(0.25)
        m[s] = codes
        if len(DEBUG) < 20 and not codes: DEBUG.append('%s(no=%s) 구성종목 0 — 응답: %s' % (s, g['no'], re.sub(r'\s+', ' ', b[:200])))
        time.sleep(0.3)
    return m

def build_map(sectors):
    """네이버 업종 → {업종명(우리 표기): [코드…]} — 신형 API 우선, 실패 시 구형 HTML 파싱"""
    try:
        m = build_map_api(sectors)
        if sum(len(v) for v in m.values()) > 800: return m
        DEBUG.append('API 매핑 부족(%d) → 구형 HTML 시도' % sum(len(v) for v in m.values()))
    except Exception as e:
        DEBUG.append('API 매핑 예외 %s → 구형 HTML 시도' % repr(e)[:80])
    raw = get(NAVER_LIST)
    html = raw.decode('euc-kr', 'ignore')
    if 'sise_group_detail' not in html:
        html = raw.decode('utf-8', 'ignore')
    links = re.findall(r'sise_group_detail\.naver\?type=upjong&(?:amp;)?no=(\d+)["\'][^>]*>\s*([^<]+?)\s*<', html)
    naver = {norm(n): no for no, n in links}
    DEBUG.append('네이버 업종 %d개 (응답 %d바이트)' % (len(naver), len(raw)))
    if not naver:
        DEBUG.append('네이버 목록 파싱 0 — 응답 앞부분: ' + re.sub(r'\s+', ' ', html[:300]))
        # 신형(Next.js) 페이지 진단: 업종 관련 토큰 주변 덤프 + 후보 API 응답
        for kw in ('upjong', 'industry', 'Industry', 'sise_group', '반도체와반도체장비', 'no=', 'itemCode', 'upjongCode'):
            for m in list(re.finditer(re.escape(kw), html))[:2]:
                DEBUG.append('[%s] …%s…' % (kw, re.sub(r'\s+', ' ', html[max(0, m.start() - 150):m.start() + 200])))
        for u in ('https://m.stock.naver.com/api/stocks/industry?page=1&pageSize=100',
                  'https://m.stock.naver.com/api/stocks/industry/list',
                  'https://finance.naver.com/api/sise/upjong.naver',
                  'https://m.stock.naver.com/api/stock/278470/basic'):
            try:
                b = get(u, tries=1); DEBUG.append('API %s → %d바이트: %s' % (u, len(b), re.sub(r'\s+', ' ', b.decode('utf-8', 'ignore')[:300])))
            except Exception as e:
                DEBUG.append('API %s → 실패 %s' % (u, repr(e)[:80]))
    want = {norm(s): s for s in sectors}
    miss = [s for k, s in want.items() if k not in naver]
    if miss: DEBUG.append('미매칭 %d: %s' % (len(miss), ', '.join(miss[:10])))
    extra = [k for k in naver if k not in want]
    if extra: DEBUG.append('네이버에만 있음 %d: %s' % (len(extra), ', '.join(extra[:12])))
    m = {}
    for k, s in want.items():
        no = naver.get(k)
        if not no: continue
        try:
            h = get(NAVER_DETAIL % no).decode('euc-kr', 'ignore')
            codes = []
            for c in re.findall(r'/item/main\.naver\?code=([0-9A-Z]{6})', h):
                if c not in codes: codes.append(c)
            m[s] = codes
        except Exception as e:
            DEBUG.append('%s 상세 실패 %s' % (s, str(e)[:40]))
        time.sleep(0.4)
    return m

def kis_token():
    for a in range(4):
        try:
            req = urllib.request.Request(BASE + '/oauth2/tokenP',
                data=json.dumps({'grant_type': 'client_credentials', 'appkey': APPKEY, 'appsecret': APPSECRET}).encode(),
                headers={'content-type': 'application/json'})
            t = json.loads(urllib.request.urlopen(req, timeout=20).read().decode())
            if t.get('access_token'): return t['access_token']
        except Exception as e:
            DEBUG.append('토큰 %d: %s' % (a + 1, str(e)[:40]))
        time.sleep(65)
    return None

def monthly(code, hdr):
    today = datetime.date.today()
    d1 = (today - datetime.timedelta(days=8 * 365)).strftime('%Y%m%d')
    url = (BASE + '/uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice'
           '?FID_COND_MRKT_DIV_CODE=J&FID_INPUT_ISCD=%s&FID_INPUT_DATE_1=%s&FID_INPUT_DATE_2=%s'
           '&FID_PERIOD_DIV_CODE=M&FID_ORG_ADJ_PRC=0' % (code, d1, today.strftime('%Y%m%d')))
    j = jget(url, hdr)
    if not (j.get('output2') or []) and ('EGW00201' in str(j) or '초당' in str(j.get('msg1', ''))):
        time.sleep(0.7); j = jget(url, hdr)
    out = {}
    for r in (j.get('output2') or []):
        d, c = (r.get('stck_bsop_date') or '').strip(), r.get('stck_clpr')
        if d and c:
            try: out[d[:6]] = float(c)
            except Exception: pass
    return out

def main():
    sectors = (load(SECTORS_FILE) or {}).get('sectors') or []
    if not sectors:
        DEBUG.append('sectors.json 없음 — 중단'); json.dump({'updated': time.strftime('%Y-%m-%d %H:%M'), 'debug': DEBUG}, open(OUT, 'w', encoding='utf-8'), ensure_ascii=False); return
    secs = {'W%02d' % (i + 1): s for i, s in enumerate(sectors)}
    code_of = {s: k for k, s in secs.items()}

    # 1) 매핑(7일 캐시)
    mp = load(MAP); stale = True
    if mp.get('built'):
        try:
            b = mp['built']; stale = (datetime.date.today() - datetime.date(int(b[:4]), int(b[4:6]), int(b[6:8]))).days >= MAP_AGE
        except Exception: stale = True
    if stale or not mp.get('map'):
        try:
            nm = build_map(sectors)
        except Exception as e:
            nm = {}; DEBUG.append('네이버 매핑 실패 %s' % str(e)[:60])
        if sum(len(v) for v in nm.values()) > 800:
            mp = {'built': datetime.date.today().strftime('%Y%m%d'), 'map': nm}
            json.dump(mp, open(MAP, 'w', encoding='utf-8'), ensure_ascii=False)
        else:
            DEBUG.append('매핑 수집 부족 — 기존 유지')
    if not mp.get('map'):
        DEBUG.append('매핑 없음 — 중단'); json.dump({'updated': time.strftime('%Y-%m-%d %H:%M'), 'debug': DEBUG}, open(OUT, 'w', encoding='utf-8'), ensure_ascii=False); return
    sec_of = {}
    for s, codes in mp['map'].items():
        for c in codes: sec_of.setdefault(c, s)

    # 2) 대상 = 매핑 ∩ stockvals 시총 상위 TOPN
    sv = (load('public/data/stockvals.json') or {}).get('map') or {}
    names = (load('public/data/products.json') or {}).get('map') or {}
    cand = [(c, (sv.get(c) or [None, None, 0])[2] or 0) for c in sec_of if c in sv]
    cand.sort(key=lambda x: -x[1])
    codes = [c for c, _ in cand[:TOPN]]; caps = {c: v for c, v in cand[:TOPN]}
    DEBUG.append('매핑 %d종목/%d업종 · 시총교집합 %d · 대상 %d' % (len(sec_of), len(mp['map']), len(cand), len(codes)))

    # 3) 월봉 캐시(wics.py와 공유) — 없는 종목만 신규
    mon = load(MON, {'v': 1, 'px': {}}); px = mon.get('px') or {}
    cur = datetime.date.today().strftime('%Y%m')
    need = [c for c in codes if c not in px or cur not in (px.get(c) or {})]
    hdr = None
    if APPKEY and APPSECRET and need:
        tok = kis_token()
        hdr = None if not tok else {'content-type': 'application/json', 'authorization': 'Bearer ' + tok,
                                    'appkey': APPKEY, 'appsecret': APPSECRET, 'tr_id': 'FHKST03010100', 'custtype': 'P'}
    got = 0
    if hdr:
        for c in need:
            try:
                m = monthly(c, hdr)
                if m: px[c] = m; got += 1
            except Exception as e:
                if len(DEBUG) < 14: DEBUG.append('%s 월봉 %s' % (c, str(e)[:30]))
            time.sleep(0.09)
        mon['px'] = px; mon['built'] = time.strftime('%Y-%m-%d %H:%M')
        json.dump(mon, open(MON, 'w', encoding='utf-8'), ensure_ascii=False)
    DEBUG.append('월봉 필요 %d · 신규 %d · 캐시 %d' % (len(need), got, len(px)))

    # 4) 섹터별 시총가중 월별 지수
    months = sorted({m for c in codes if c in px for m in px[c]})[-97:]
    idx, comp = {}, {}
    for sc, snm in secs.items():
        mem = [c for c in codes if sec_of.get(c) == snm and c in px]
        if len(mem) < MIN_MEMBERS: continue
        top = sorted(mem, key=lambda x: -caps.get(x, 0))[:10]
        comp[sc] = {'n': snm, 'cnt': len(mem), 'all': len(mp['map'].get(snm) or []),
                    'top': [{'c': c, 'n': (names.get(c) or {}).get('n') or c, 'cap': caps.get(c, 0)} for c in top]}
        ser = []
        for i, m in enumerate(months):
            if i == 0: ser.append(100.0); continue
            num = den = 0.0
            for c in mem:
                a, b = px[c].get(months[i - 1]), px[c].get(m)
                if a and b and a > 0:
                    w = caps.get(c, 0) or 0; num += w * (b / a - 1); den += w
            ser.append(round(ser[-1] * (1 + (num / den if den else 0)), 2))
        idx[sc] = ser
    skipped = [s for k, s in secs.items() if k not in idx]
    DEBUG.append('섹터 %d개 · 월 %d개 · 제외(종목<%d) %d: %s' % (len(idx), len(months), MIN_MEMBERS, len(skipped), ', '.join(skipped[:10])))

    def ret(sc, n):
        s = idx.get(sc) or []
        if len(s) <= n or not s[-1 - n]: return None
        return round((s[-1] / s[-1 - n] - 1) * 100, 2)
    rows = [{'c': sc, 'n': secs[sc], 'cnt': comp[sc]['cnt'], 'm1': ret(sc, 1), 'm3': ret(sc, 3), 'm6': ret(sc, 6),
             'y1': ret(sc, 12), 'y3': ret(sc, 36)} for sc in idx]
    out = {'updated': time.strftime('%Y-%m-%d %H:%M'), 'months': months, 'idx': idx, 'comp': comp, 'rows': rows,
           'secs': {k: v for k, v in secs.items() if k in idx},
           'note': '구성종목은 네이버금융 업종(WICS 소분류) 분류, 수익률은 KIS 월봉을 현재 시총으로 가중해 직접 계산. 과거 구간도 현재 구성종목·현재 시총 기준(생존편향·근사). 참고: judoju.kboard.workers.dev/rank',
           'debug': DEBUG}
    prev = load(OUT)
    if not idx and prev.get('idx'):
        prev['debug'] = DEBUG + ['계산 실패 — 기존 유지']; json.dump(prev, open(OUT, 'w', encoding='utf-8'), ensure_ascii=False); return
    json.dump(out, open(OUT, 'w', encoding='utf-8'), ensure_ascii=False)
    print('저장 %s — 섹터 %d · 월 %d' % (OUT, len(idx), len(months)), file=sys.stderr)

if __name__ == '__main__':
    try:
        main()
    finally:
        print('DEBUG:', json.dumps(DEBUG, ensure_ascii=False), file=sys.stderr)
