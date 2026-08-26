#!/usr/bin/env python3
# ⚡ 미국 전력 수요 파이프라인 수집기
# ① EIA-860M 계획 발전소(월간 공식): 연료별·가동예정연도별·주별 GW 스냅샷 (히스토리 누적)
# ② 뉴스 피드: 대형부하(데이터센터) 계통 신청 / 유틸리티 파이프라인 / 장비 백로그 / CSP 캐펙스
# 결과: public/data/power.json
import os, sys, json, time, re, io, urllib.request, urllib.parse, ssl, datetime
import xml.etree.ElementTree as ET

OUT = 'public/data/power.json'
UA = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/126'}
CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE
DEBUG = []

MONTHS = ['january', 'february', 'march', 'april', 'may', 'june',
          'july', 'august', 'september', 'october', 'november', 'december']

def fetch(url, t=90, tries=2):
    for i in range(tries):
        try:
            return urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=t, context=CTX).read()
        except Exception:
            time.sleep(2)
    return b''

def parse_860m(b):
    """엑셀 → {'total': GW, 'fuel': {tech: GW}, 'year': {yyyy: GW}, 'state': {st: GW}, 'gas': GW, 'nuke': GW, 'n': 행수}"""
    import openpyxl
    wb = openpyxl.load_workbook(io.BytesIO(b), read_only=True)
    if 'Planned' not in wb.sheetnames:
        return None
    ws = wb['Planned']
    hdr = None
    for i, r in enumerate(ws.iter_rows(min_row=1, max_row=5, values_only=True)):
        if r and any('Capacity' in str(c or '') for c in r):
            hdr = [str(c or '') for c in r]
            hdr_row = i + 1
            break
    if not hdr:
        return None
    def col(*names):
        for j, n in enumerate(hdr):
            if any(k in n for k in names):
                return j
        return None
    c_cap, c_tech, c_yr, c_st = col('Capacity'), col('Technology'), col('Planned Operation Year', 'Year'), col('Plant State', 'State')
    total = 0.0
    fuel, year, state = {}, {}, {}
    n = 0
    for r in ws.iter_rows(min_row=hdr_row + 1, values_only=True):
        try:
            cap = float(r[c_cap])
        except Exception:
            continue
        n += 1
        total += cap
        t = str(r[c_tech])[:40] if c_tech is not None and r[c_tech] else '기타'
        fuel[t] = fuel.get(t, 0) + cap
        if c_yr is not None and r[c_yr]:
            y = str(r[c_yr])[:4]
            if y.isdigit():
                year[y] = year.get(y, 0) + cap
        if c_st is not None and r[c_st]:
            s = str(r[c_st])[:2]
            state[s] = state.get(s, 0) + cap
    gw = lambda d: {k: round(v / 1000, 2) for k, v in d.items()}
    fuel = dict(sorted(gw(fuel).items(), key=lambda x: -x[1]))
    gas = sum(v for k, v in fuel.items() if 'Natural Gas' in k)
    nuke = sum(v for k, v in fuel.items() if 'Nuclear' in k)
    return {'total': round(total / 1000, 1), 'fuel': fuel,
            'year': dict(sorted(gw(year).items())),
            'state': dict(sorted(gw(state).items(), key=lambda x: -x[1])[:12]),
            'gas': round(gas, 1), 'nuke': round(nuke, 1), 'n': n}

def eia_urls():
    """최신월부터 과거로 (본 페이지 + 아카이브 경로 조합)"""
    today = datetime.date.today()
    out = []
    y, m = today.year, today.month
    for _ in range(14):
        mn = MONTHS[m - 1]
        out.append(('%04d-%02d' % (y, m), [
            'https://www.eia.gov/electricity/data/eia860m/xls/%s_generator%d.xlsx' % (mn, y),
            'https://www.eia.gov/electricity/data/eia860m/archive/xls/%s_generator%d.xlsx' % (mn, y)]))
        m -= 1
        if m == 0:
            y, m = y - 1, 12
    return out

def collect_eia(prev_snap, backfill=False):
    snap = dict(prev_snap or {})
    fetched = 0
    for key, urls in eia_urls():
        if key in snap:
            if not backfill:
                break  # 최신이 이미 있으면 종료(과거는 이미 수집됨)
            continue
        got = None
        for u in urls:
            b = fetch(u, 120)
            if b[:2] == b'PK':
                got = b
                break
        if not got:
            continue  # 그 달 미발표(HTML 응답)
        try:
            r = parse_860m(got)
            if r and r['total'] > 50:  # 정합성: 미국 계획 발전이 50GW 미만일 수 없음
                snap[key] = r
                fetched += 1
                DEBUG.append('EIA %s: %sGW(가스 %s·원전 %s)' % (key, r['total'], r['gas'], r['nuke']))
        except Exception as e:
            DEBUG.append('EIA %s 파싱 실패 %r' % (key, str(e)[:40]))
        if not backfill and fetched:
            break
        if fetched >= 12:
            break
        time.sleep(1)
    return snap

# ── 뉴스 피드 (구글뉴스 RSS + 번역) ──
def rss(lang, query):
    if lang == 'ko':
        u = 'https://news.google.com/rss/search?q=%s&hl=ko&gl=KR&ceid=KR:ko' % urllib.parse.quote(query)
    else:
        u = 'https://news.google.com/rss/search?q=%s&hl=en-US&gl=US&ceid=US:en' % urllib.parse.quote(query)
    out = []
    try:
        root = ET.fromstring(fetch(u, 30).decode('utf-8', 'ignore'))
        for it in list(root.iter('item'))[:7]:
            t = (it.findtext('title') or '').strip()
            lk = (it.findtext('link') or '').strip()
            pd = (it.findtext('pubDate') or '')
            try:
                d = time.strftime('%Y-%m-%d', time.strptime(pd[5:16], '%d %b %Y'))
            except Exception:
                d = ''
            if t and lk:
                out.append({'d': d, 't': t[:150], 'u': lk, 'l': lang})
    except Exception:
        pass
    return out

def tr_ko(text):
    try:
        u = 'https://api.mymemory.translated.net/get?q=%s&langpair=en|ko' % urllib.parse.quote(text[:300])
        r = json.loads(fetch(u, 20, 1).decode('utf-8'))
        t = (r.get('responseData') or {}).get('translatedText') or ''
        if t and 'MYMEMORY' not in t.upper():
            return t
    except Exception:
        pass
    return None

NEWS_Q = {
 'queue': [('en', 'data center interconnection queue gigawatts'), ('en', 'ERCOT large load data center')],
 'utility': [('en', 'Dominion AEP data center pipeline gigawatts'), ('en', 'utility data center contracted load')],
 'equip': [('en', 'GE Vernova gas turbine orders backlog'), ('ko', '두산에너빌리티 가스터빈 OR SMR 수주'), ('ko', '변압기 수주 미국')],
 'capex': [('en', 'hyperscaler capex guidance data center'), ('en', 'Microsoft Google Meta Amazon capex increase')],
 'onsite': [('en', 'data center onsite power generation fuel cell'), ('en', 'nuclear SMR data center agreement')],
}

def collect_news(prev):
    out = dict(prev or {})
    budget = 10  # 번역 한도
    for k, queries in NEWS_Q.items():
        items = list(out.get(k) or [])
        seen = {re.sub(r'\W+', '', x['t'])[:60] for x in items}
        for lang, q in queries:
            for it in rss(lang, q):
                key = re.sub(r'\W+', '', it['t'])[:60]
                if key in seen:
                    continue
                seen.add(key)
                items.append(it)
            time.sleep(0.4)
        # 신규 영문 항목 번역
        for it in items:
            if budget <= 0:
                break
            if it.get('tk') or it.get('l') != 'en':
                continue
            if any('가' <= ch <= '힣' for ch in it['t']):
                continue
            t = tr_ko(it['t'])
            if t:
                it['tk'] = t[:160]
                budget -= 1
                time.sleep(0.4)
        items.sort(key=lambda x: x.get('d') or '')
        out[k] = items[-16:]
    return out

def main():
    prev = {}
    if os.path.exists(OUT):
        try:
            prev = json.load(open(OUT, encoding='utf-8'))
        except Exception:
            pass
    backfill = os.environ.get('BACKFILL') == '1'
    snap = collect_eia(prev.get('eia'), backfill)
    news = collect_news(prev.get('news'))
    if not snap and prev.get('eia'):
        snap = prev['eia']
    out = {'updated': time.strftime('%Y-%m-%d %H:%M'), 'eia': snap, 'news': news, 'debug': DEBUG[-15:]}
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(out, open(OUT, 'w', encoding='utf-8'), ensure_ascii=False)
    print('완료', DEBUG, file=sys.stderr)

if __name__ == '__main__':
    main()
