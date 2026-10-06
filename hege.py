#!/usr/bin/env python3
# 헤게모니 4국면 분류기 — 동부 스몰캡 『투자의 定石』(2011·2016) 계량 기준
#   데이터: OpenDART 다중회사 주요계정(fnlttMultiAcnt) → 전 상장사 분기 매출액·영업이익(연결 우선, 없으면 별도)
#           네이버 모바일 업종 리스트 → 종목명·시장·업종·시총
#   국면(분기 YoY 기준, 적전·적자확대 = -200%, 흑전·500%↑ = 500% 캡):
#     1국면  매출 증가(최근 8분기 최대 매출 or 직전 하락기 뒤 턴어라운드)인데 영업이익은 못 따라옴 — 수요 회복 초기
#     2국면  매출↑·영업이익↑ 그리고 영업이익 증가율 > 매출 증가율 — 영업레버리지(헤게모니 보유)
#     3국면  매출은 늘어도 영업이익 증가율 < 매출 증가율 — 헤게모니 상실 신호(2국면 뒤)
#     4국면  매출·영업이익 모두 감소
#     0      매출 감소 + 영업이익 증가(비용절감형 생존, Ver.2의 1-1/2-1국면)
#   플래그: new1(1국면 신규 진입) entry2(2국면 초입: 직전 분기 ≠2 → 2) streak(2국면 연속 분기) slow(2국면이지만 영익 증가율 둔화)
#           q4(최근 분기가 4Q — 인센티브 등 일회성 비용으로 3국면 오판 주의)
# 필요 시크릿: DART_API_KEY   결과: public/data/hege.json
import os, sys, json, time, re, io, zipfile, datetime, urllib.request, urllib.parse, ssl
import xml.etree.ElementTree as ET

KEY = os.environ.get('DART_API_KEY', '')
OUT = os.environ.get('OUT', 'public/data/hege.json')
LIMIT = int(os.environ.get('LIMIT', '0'))          # 테스트용: 종목 수 제한
CHUNK = int(os.environ.get('CHUNK', '50'))         # DART 다중회사 호출당 종목 수(100이면 응답 느림)
ONLY = [c for c in os.environ.get('ONLY', '').split(',') if re.fullmatch(r'\d{6}', c)]
NQ = 13                                            # 수집 분기 수(YoY 계산 후 9분기 국면)
UA = {'User-Agent': 'Mozilla/5.0'}
CTX = ssl.create_default_context(); CTX.check_hostname = False; CTX.verify_mode = ssl.CERT_NONE
KST = datetime.timezone(datetime.timedelta(hours=9)); TODAY = datetime.datetime.now(KST).date()
DEBUG = []

def log(s): DEBUG.append(str(s)[:300]); print(s, file=sys.stderr, flush=True)
def fetch(url, timeout=60, tries=3):
    err = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers=UA)
            return urllib.request.urlopen(req, timeout=timeout, context=CTX).read()
        except Exception as e:
            err = e; time.sleep(2 * (i + 1))
    log('fetch 실패 %s %r' % (url[:90], err)); return b''
def jget(url):
    try: return json.loads(fetch(url).decode('utf-8'))
    except Exception: return {}
def tonum(s):
    try:
        s = str(s).replace(',', '').strip()
        if s in ('', '-'): return None
        return float(s)
    except Exception: return None

# ───────── 1. 종목 유니버스 (네이버 업종 리스트: 이름·시장·업종·시총)
def naver_universe():
    groups = []
    for pg in range(1, 10):                                   # 업종 79개, 페이지당 20개
        g = jget('https://m.stock.naver.com/api/stocks/industry?page=%d' % pg)
        gs = g.get('groups') or []
        groups += gs
        if len(gs) < 20: break
    uni = {}
    for grp in groups:
        no, name = grp.get('no'), grp.get('name')
        page = 1
        while True:
            j = jget('https://m.stock.naver.com/api/stocks/industry/%s?page=%d&pageSize=100' % (no, page))
            st = j.get('stocks') or []
            for s in st:
                if s.get('stockEndType') != 'stock': continue
                code = s.get('itemCode', '')
                if not re.fullmatch(r'\d{6}', code): continue
                if code[-1] != '0': continue                      # 우선주 등 제외(보통주는 끝자리 0)
                mv = tonum(s.get('marketValue'))                   # 억원
                uni[code] = {'name': s.get('stockName'), 'mkt': 'KOSDAQ' if s.get('sosok') == '1' else 'KOSPI',
                             'sec': name, 'cap': mv}
            if len(st) < 100: break
            page += 1
            time.sleep(0.05)
        time.sleep(0.05)
    log('네이버 유니버스 %d종목 / 업종 %d' % (len(uni), len(groups)))
    return uni

# ───────── 2. DART 고유번호 매핑
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
        if re.fullmatch(r'\d{6}', sc): m[sc] = el.findtext('corp_code')
    log('DART 고유번호 %d개' % len(m))
    return m

# ───────── 3. 분기 손익 수집
REPRT = {1: '11013', 2: '11012', 3: '11014', 4: '11011'}       # 1Q·반기·3Q·사업보고서
def quarters_needed():
    # 공시 마감 기준으로 "나올 수 있는" 최신 분기: 1Q→5/15, 2Q→8/14, 3Q→11/14, 4Q→익년 3/31
    y, md = TODAY.year, (TODAY.month, TODAY.day)
    if md >= (11, 14): last = (y, 3)
    elif md >= (8, 14): last = (y, 2)
    elif md >= (5, 15): last = (y, 1)
    elif md >= (3, 31): last = (y - 1, 4)
    else: last = (y - 1, 3)
    qs = []; yy, qq = last
    for _ in range(NQ):
        qs.append((yy, qq)); qq -= 1
        if qq == 0: yy -= 1; qq = 4
    return qs[::-1]

def is_rev(nm):
    nm = nm.replace(' ', '')
    return nm in ('매출액', '수익(매출액)', '영업수익', '매출', '매출및지분법손익', '순영업수익', '이자수익') or nm.startswith('매출액') or nm.startswith('수익(매출')
def is_op(nm):
    nm = nm.replace(' ', '')
    return nm == '영업이익' or nm == '영업이익(손실)' or nm.startswith('영업이익(') and '률' not in nm

def dart_batch(corps, year, q, store):
    """store[corp][(year,q)] = {'rev':3개월, 'op':3개월, 'rev_cum':누적, 'op_cum':누적, 'fs':'CFS'|'OFS'}"""
    url = ('https://opendart.fss.or.kr/api/fnlttMultiAcnt.json?crtfc_key=%s&corp_code=%s&bsns_year=%d&reprt_code=%s'
           % (KEY, ','.join(corps), year, REPRT[q]))
    j = jget(url)
    st = j.get('status')
    if st == '020': log('DART 사용 한도 초과'); return 'quota'
    if st not in ('000', '013'): log('DART %d/%dQ status=%s %s' % (year, q, st, j.get('message'))); return 'err'
    for r in j.get('list') or []:
        nm = r.get('account_nm', ''); fs = r.get('fs_div', 'OFS'); corp = r.get('corp_code')
        if not (is_rev(nm) or is_op(nm)): continue
        k = 'rev' if is_rev(nm) else 'op'
        d = store.setdefault(corp, {}).setdefault((year, q), {'CFS': {}, 'OFS': {}})[fs]
        amt = tonum(r.get('thstrm_amount')); add = tonum(r.get('thstrm_add_amount'))
        if q == 4: cum = amt; qv = None                      # 사업보고서: 연간 → 4Q = 연간 − 3Q 누적
        else:
            cum = add if add is not None else amt
            qv = amt if add is not None else (amt if q == 1 else None)
        if k in d and d[k].get('q') is not None: continue   # 매출액 항목 중복 시 첫 번째(상위) 유지
        d[k] = {'q': qv, 'cum': cum}
    return 'ok'

def build_series(store_corp, qs):
    """분기 (rev, op) 시계열. 연결 우선, 없으면 별도. 4Q = 연간 − 3Q누적, 2Q·3Q 3개월값 없으면 누적 차분."""
    out = {}
    for fs in ('CFS', 'OFS'):
        ser = {}
        for (y, q) in qs:
            d = (store_corp.get((y, q)) or {}).get(fs) or {}
            rv, op = d.get('rev') or {}, d.get('op') or {}
            def val(x, key):
                v = x.get('q')
                if v is not None: return v
                cum = x.get('cum')
                if cum is None: return None
                if q == 1: return cum
                prev = ((store_corp.get((y, q - 1)) or {}).get(fs) or {}).get(key) or {}
                pc = prev.get('cum')
                if pc is None and q == 2: pc = prev.get('q')
                return None if pc is None else cum - pc
            ser[(y, q)] = (val(rv, 'rev'), val(op, 'op'))
        n_ok = sum(1 for v in ser.values() if v[0] is not None and v[1] is not None)
        if n_ok >= 6: return ser, fs
        if fs == 'CFS': out = (ser, fs)
    return out if out else ({}, None)

# ───────── 4. 국면 분류
def growth(cur, prev):
    if cur is None or prev is None: return None
    if prev == 0: return 500.0 if cur > 0 else (-200.0 if cur < 0 else None)
    if prev > 0 and cur < 0: return -200.0                     # 적자전환
    if prev < 0 and cur < 0: return -200.0 if cur < prev else min(500.0, (cur - prev) / abs(prev) * 100)  # 적자확대 / 적자축소
    if prev < 0 and cur >= 0: return 500.0                      # 흑자전환
    return max(-200.0, min(500.0, (cur - prev) / abs(prev) * 100))

def classify(rev, op, rg, og):
    """rev/op: 시계열(억), rg/og: YoY 증가율 시계열(None 가능). 반환 phases 리스트(0~4 or None)."""
    n = len(rev); ph = [None] * n
    for t in range(n):
        g1, g2 = rg[t], og[t]
        if g1 is None or g2 is None or rev[t] is None or op[t] is None: continue
        prev = next((ph[k] for k in range(t - 1, -1, -1) if ph[k] is not None), None)
        if g1 < 0 and g2 < 0: ph[t] = 4; continue
        if g1 < 0 and g2 >= 0: ph[t] = 0; continue
        # 여기부터 매출 증가(g1 >= 0)
        if op[t] > 0 and g2 > 0 and g2 > g1: ph[t] = 2; continue
        # 영업이익이 매출을 못 따라옴 → 1(턴어라운드 초기) vs 3(헤게모니 상실)
        win = [v for v in rev[max(0, t - 7):t + 1] if v is not None]
        rec_high = len(win) >= 4 and rev[t] >= max(win)
        pr = [g for g in rg[max(0, t - 4):t] if g is not None]
        weak_before = (len(pr) >= 2 and sum(pr) / len(pr) <= 0) or prev in (4, 0, 1, None)
        if op[t] <= 0: ph[t] = 1 if (rec_high or weak_before) else 4
        elif rec_high and weak_before: ph[t] = 1
        elif prev == 1 and rec_high: ph[t] = 1
        else: ph[t] = 3
    return ph

def main():
    if not KEY: log('DART_API_KEY 필요'); sys.exit(1)
    qs = quarters_needed(); log('수집 분기: %s ~ %s' % (qs[0], qs[-1]))
    uni = naver_universe()
    corpmap = dart_corpcodes()
    if not uni or not corpmap: log('유니버스/고유번호 실패'); sys.exit(1)
    codes = [c for c in uni if c in corpmap]
    if ONLY: codes = [c for c in codes if c in ONLY]
    codes.sort(key=lambda c: -(uni[c]['cap'] or 0))
    if LIMIT: codes = codes[:LIMIT]
    log('대상 %d종목' % len(codes))
    corp2code = {corpmap[c]: c for c in codes}
    store = {}; calls = 0; quota = False; T0 = time.time()
    years = sorted({y for y, q in qs})
    for i in range(0, len(codes), CHUNK):
        batch = [corpmap[c] for c in codes[i:i + CHUNK]]
        for (y, q) in qs:
            r = dart_batch(batch, y, q, store); calls += 1
            if r == 'quota': quota = True; break
            time.sleep(0.15)
        if quota: break
        log('배치 %d/%d 완료 (호출 %d, %ds)' % (i // CHUNK + 1, (len(codes) + CHUNK - 1) // CHUNK, calls, time.time() - T0))
    rows = []; cnt = {0: 0, 1: 0, 2: 0, 3: 0, 4: 0}
    for corp, code in corp2code.items():
        ser, fs = build_series(store.get(corp, {}), qs)
        if not ser: continue
        rev = [None if ser[k][0] is None else ser[k][0] / 1e8 for k in qs]
        op = [None if ser[k][1] is None else ser[k][1] / 1e8 for k in qs]
        rg = [None] * len(qs); og = [None] * len(qs)
        for t in range(4, len(qs)):
            rg[t] = growth(rev[t], rev[t - 4]); og[t] = growth(op[t], op[t - 4])
        ph = classify(rev, op, rg, og)
        # 최신 유효 분기
        last = next((t for t in range(len(qs) - 1, -1, -1) if ph[t] is not None), None)
        if last is None: continue
        hist = ph[max(0, last - 7):last + 1]
        prevs = [p for p in ph[:last] if p is not None]
        prev = prevs[-1] if prevs else None
        cur = ph[last]
        streak = 0
        for t in range(last, -1, -1):
            if ph[t] == cur: streak += 1
            elif ph[t] is None: continue
            else: break
        prev_og = next((og[t] for t in range(last - 1, -1, -1) if og[t] is not None), None)
        slow = cur == 2 and prev_og is not None and og[last] < prev_og
        y, q = qs[last]
        u = uni[code]
        rows.append({'c': code, 'n': u['name'], 'mkt': u['mkt'], 'sec': u['sec'], 'cap': u['cap'], 'fs': fs,
                     'q': '%dQ%02d' % (q, y % 100), 'ph': cur, 'prev': prev, 'streak': streak,
                     'new1': cur == 1 and prev != 1, 'entry2': cur == 2 and prev != 2, 'slow': bool(slow), 'q4': q == 4,
                     'rg': None if rg[last] is None else round(rg[last], 1), 'og': None if og[last] is None else round(og[last], 1),
                     'rev': [None if v is None else round(v, 1) for v in rev[last - 8:last + 1]] if last >= 8 else [None if v is None else round(v, 1) for v in rev[:last + 1]],
                     'op': [None if v is None else round(v, 1) for v in op[last - 8:last + 1]] if last >= 8 else [None if v is None else round(v, 1) for v in op[:last + 1]],
                     'rgs': [None if v is None else round(v, 1) for v in rg[max(4, last - 7):last + 1]],
                     'ogs': [None if v is None else round(v, 1) for v in og[max(4, last - 7):last + 1]],
                     'hist': hist, 'ql': ['%dQ%02d' % (qq, yy % 100) for (yy, qq) in qs[max(0, last - 7):last + 1]]})
        cnt[cur] = cnt.get(cur, 0) + 1
    order = {1: 0, 2: 1, 3: 2, 0: 3, 4: 4}
    rows.sort(key=lambda r: (order.get(r['ph'], 9), -(r['cap'] or 0)))
    out = {'updated': datetime.datetime.now(KST).strftime('%Y-%m-%d %H:%M'), 'asof_quarter': '%dQ%02d' % (qs[-1][1], qs[-1][0] % 100),
           'quarters': ['%dQ%02d' % (q, y % 100) for (y, q) in qs], 'n': len(rows), 'universe': len(codes), 'dart_calls': calls, 'quota_hit': quota,
           'count': cnt, 'source': 'OpenDART 다중회사 주요계정(연결 우선) + 네이버 업종/시총',
           'legend': {'1': '매출 증가·영업이익 미반영(턴어라운드 초기)', '2': '영업이익 증가율 > 매출 증가율(영업레버리지·헤게모니)',
                      '3': '매출 증가하나 영업이익 증가율 < 매출 증가율(헤게모니 상실 신호)', '4': '매출·영업이익 모두 감소', '0': '매출 감소·영업이익 증가(비용절감형)'},
           'rows': rows, 'debug': DEBUG[-40:]}
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(out, open(OUT, 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'))
    log('저장 %s rows=%d count=%s calls=%d' % (OUT, len(rows), cnt, calls))

if __name__ == '__main__': main()
