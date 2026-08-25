#!/usr/bin/env python3
# 반도체 P→Q 사이클 추적 수집기
# 국내: ① 관세청 수출 단가(P)·물량(Q) 분해(반도체 8542·메모리 854232)
#       ② 감시 종목군 분기 매출·영업이익(fnlttSinglAcnt, 연결 우선)
#       ③ 장비주 계약부채(fnlttSinglAcntAll — Q의 선행)
# 글로벌: 트렌드포스(DRAM 현물가)·SIA(WSTS 월간 매출)·구글뉴스(SEMI 빌링·TSMC 월매출·ASML 수주)
# 결과: public/data/pq.json (히스토리 누적 — 기존 값 보존)
import os, sys, json, time, re, io, zipfile, urllib.request, urllib.parse, ssl, datetime
import xml.etree.ElementTree as ET

DART_KEY = os.environ.get('DART_KEY', '')
CUSTOMS_KEY = os.environ.get('CUSTOMS_KEY', '')
BASE = 'https://opendart.fss.or.kr/api'
OUT = 'public/data/pq.json'
UA = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126 Safari/537.36'}
DEBUG = []
CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE

# 감시 종목군(분기 매출·영업이익) — 사이클 단계별
GROUPS = [
    ('유통사 (P 최전선)', [('031330', '에스에이엠티'), ('254490', '미래반도체')]),
    ('레거시 팹리스 (P 2차)', [('080220', '제주반도체'), ('032580', '피델릭스')]),
    ('OSAT·테스트 (Q 1차)', [('172670', '에이엘티'), ('131970', '두산테스나'), ('330860', '네패스아크'), ('061970', '엘비세미콘')]),
    ('팹 인프라 (Q 2차)', [('045100', '한양이엔지'), ('011560', '세보엠이씨'), ('029460', '케이씨'), ('396470', '워트'), ('445180', '퓨릿'), ('083450', 'GST'), ('417840', '저스템')]),
    ('전공정 장비 (Q 3차)', [('240810', '원익IPS'), ('084370', '유진테크'), ('095610', '테스')]),
]
# 계약부채(선수금) 추적 — 장비 발주 선행
CL_CODES = [('240810', '원익IPS'), ('084370', '유진테크'), ('095610', '테스'),
            ('042700', '한미반도체'), ('319660', '피에스케이'), ('039030', '이오테크닉스')]
REPRT = {1: '11013', 2: '11012', 3: '11014', 4: '11011'}
YEARS = list(range(2023, datetime.date.today().year + 1))

def fetch(url, timeout=60, tries=3):
    for i in range(tries):
        try:
            return urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout, context=CTX).read()
        except Exception:
            time.sleep(2 * (i + 1))
    return b''

def jget(url):
    try:
        return json.loads(fetch(url).decode('utf-8'))
    except Exception:
        return {}

def tonum(s):
    try:
        return float(str(s).replace(',', '').strip())
    except Exception:
        return None

# ── ① 관세청 수출 P/Q ──
def customs(prev):
    out = dict(prev or {})
    if not CUSTOMS_KEY:
        DEBUG.append('customs: 키 없음')
        return out
    endm = datetime.date.today().strftime('%Y%m')
    for name, hs in [('반도체', '8542'), ('메모리', '854232')]:
        try:
            q = ('/1220000/itemtrade/getItemtradeList?serviceKey=%s&strtYymm=202001&endYymm=%s&hsSgn=%s'
                 % (CUSTOMS_KEY, endm, hs))
            x = ''
            last = None
            # trends.py와 동일한 호출 방식(UA·SSL컨텍스트 없이) — data.go.kr는 기본 urlopen이 안정적
            for base in ('http://apis.data.go.kr', 'https://apis.data.go.kr', 'http://apis.data.go.kr'):
                try:
                    x = urllib.request.urlopen(base + q, timeout=110).read().decode('utf-8', 'ignore')
                    if x:
                        break
                except Exception as e2:
                    last = e2
                    time.sleep(3)
            if not x:
                raise last or Exception('빈 응답')
            root = ET.fromstring(x)
            ser = dict(out.get(name) or {})
            for it in root.iter('item'):
                ym = (it.findtext('year') or '').strip()
                dlr = tonum(it.findtext('expDlr'))
                wgt = tonum(it.findtext('expWgt'))
                m = re.search(r'(\d{4})\.(\d{2})', ym)
                if m and dlr:
                    ser['%s-%s' % (m.group(1), m.group(2))] = [round(dlr / 1e6, 1), round((wgt or 0) / 1e3, 1)]  # 백만$, 톤
            if ser:
                out[name] = ser
                DEBUG.append('customs %s %d개월' % (name, len(ser)))
        except Exception as e:
            DEBUG.append('customs %s 실패 %r' % (name, str(e)[:50]))
        time.sleep(1)
    return out

# ── DART 공통 ──
def corp_map():
    b = fetch('%s/corpCode.xml?crtfc_key=%s' % (BASE, DART_KEY), 90)
    z = zipfile.ZipFile(io.BytesIO(b))
    root = ET.fromstring(z.read(z.namelist()[0]))
    m = {}
    for it in root.iter('list'):
        sc = (it.findtext('stock_code') or '').strip()
        if len(sc) == 6:
            m[sc] = it.findtext('corp_code').strip()
    return m

def q_financials(corp):
    """분기 [매출, 영업이익] (억원). fnlttSinglAcnt: Q1~Q3(반기 포함) thstrm_amount=해당 3개월 단일분기,
    사업보고서(Q4)만 연간 누적 → Q4 = 연간 - 3Q누적(thstrm_add_amount)."""
    raw = {}
    for y in YEARS:
        for qn, rc in REPRT.items():
            d = jget('%s/fnlttSinglAcnt.json?crtfc_key=%s&corp_code=%s&bsns_year=%d&reprt_code=%s'
                     % (BASE, DART_KEY, corp, y, rc))
            slot = {}
            for r in (d.get('list') or []):
                fs = r.get('fs_div')
                nm = (r.get('account_nm') or '').replace(' ', '')
                cur = tonum(r.get('thstrm_amount'))
                cum = tonum(r.get('thstrm_add_amount'))
                if cur is None:
                    continue
                key = ('rv' if nm in ('매출액', '수익(매출액)', '영업수익')
                       else 'op' if nm in ('영업이익', '영업이익(손실)') else None)
                if not key:
                    continue
                if slot.get(key + '_fs') == 'CFS' and fs != 'CFS':
                    continue
                slot[key] = {'cur': cur, 'cum': cum if cum is not None else cur}
                slot[key + '_fs'] = fs
            if slot:
                raw[(y, qn)] = slot
            time.sleep(0.1)
    out = {}
    for (y, qn), s in sorted(raw.items()):
        def single(key):
            if key not in s:
                return None
            if qn in (1, 2, 3):
                return s[key]['cur']
            fy = s[key]['cur']
            p3 = raw.get((y, 3), {}).get(key, {})
            nine = p3.get('cum', p3.get('cur'))
            return (fy - nine) if (fy is not None and nine is not None) else None
        rv, op = single('rv'), single('op')
        if rv is not None:
            out['%02dQ%d' % (y % 100, qn)] = [round(rv / 1e8, 0), round(op / 1e8, 0) if op is not None else None]
    return out

def contract_liab(corp):
    """계약부채(유동+비유동) 분기말 잔액 → {'23Q1': 억원}"""
    out = {}
    for y in YEARS:
        for qn, rc in REPRT.items():
            d = jget('%s/fnlttSinglAcntAll.json?crtfc_key=%s&corp_code=%s&bsns_year=%d&reprt_code=%s&fs_div=CFS'
                     % (BASE, DART_KEY, corp, y, rc))
            rows = d.get('list') or []
            if not rows:
                d = jget('%s/fnlttSinglAcntAll.json?crtfc_key=%s&corp_code=%s&bsns_year=%d&reprt_code=%s&fs_div=OFS'
                         % (BASE, DART_KEY, corp, y, rc))
                rows = d.get('list') or []
            s = 0
            found = False
            for r in rows:
                nm = (r.get('account_nm') or '').replace(' ', '')
                if '계약부채' in nm or '선수금' in nm:
                    v = tonum(r.get('thstrm_amount'))
                    if v:
                        s += v
                        found = True
            if found:
                out['%02dQ%d' % (y % 100, qn)] = round(s / 1e8, 0)
            time.sleep(0.15)
    return out

# ── 글로벌 ──
def html(url, t=30):
    return fetch(url, t).decode('utf-8', 'ignore')

def g_trendforce(prev):
    items = list(prev or [])
    seen = {x['u'] for x in items}
    try:
        h = html('https://www.trendforce.com/presscenter/news/')
        for m in re.finditer(r'href=["\'](/presscenter/news/\d{8}-\d+\.html)["\'][^>]*>([\s\S]{0,300}?)</a>', h):
            u = 'https://www.trendforce.com' + m.group(1)
            t = re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', '', m.group(2))).strip()
            if re.search(r'DRAM|NAND|Memory|HBM', t, re.I) and u not in seen:
                items.append({'d': time.strftime('%Y-%m-%d'), 't': t, 'u': u})
                seen.add(u)
        DEBUG.append('TF %d건' % len(items))
    except Exception as e:
        DEBUG.append('TF 실패 %r' % str(e)[:40])
    return items[-30:]

def g_sia(prev):
    items = list(prev or [])
    seen = {x['u'] for x in items}
    try:
        h = html('https://www.semiconductors.org/news-events/latest-news/')
        for m in re.finditer(r'<a[^>]+href=["\'](https://www\.semiconductors\.org/[^"\']+)["\'][^>]*>([\s\S]{0,300}?)</a>', h):
            u = m.group(1)
            t = re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', '', m.group(2))).strip()
            if re.search(r'Semiconductor Sales', t, re.I) and u not in seen:
                pct = re.search(r'(\d+(?:\.\d+)?)%', t)
                items.append({'d': time.strftime('%Y-%m-%d'), 't': t, 'u': u, 'pct': float(pct.group(1)) if pct else None})
                seen.add(u)
        DEBUG.append('SIA %d건' % len(items))
    except Exception as e:
        DEBUG.append('SIA 실패 %r' % str(e)[:40])
    return items[-24:]

def g_news(query, prev, pat=None):
    items = list(prev or [])
    seen = {x['u'] for x in items}
    try:
        u = 'https://news.google.com/rss/search?q=%s&hl=en-US&gl=US&ceid=US:en' % urllib.parse.quote(query)
        x = fetch(u, 30).decode('utf-8', 'ignore')
        root = ET.fromstring(x)
        for it in list(root.iter('item'))[:10]:
            t = (it.findtext('title') or '').strip()
            lk = (it.findtext('link') or '').strip()
            pd = (it.findtext('pubDate') or '')[:16]
            if lk and lk not in seen and (not pat or re.search(pat, t, re.I)):
                items.append({'d': pd, 't': t[:160], 'u': lk})
                seen.add(lk)
    except Exception as e:
        DEBUG.append('news(%s) 실패 %r' % (query[:20], str(e)[:40]))
    return items[-20:]

def main():
    prev = {}
    if os.path.exists(OUT):
        try:
            prev = json.load(open(OUT, encoding='utf-8'))
        except Exception:
            prev = {}
    out = {'updated': time.strftime('%Y-%m-%d %H:%M')}
    # ① 수출 P/Q
    out['exp'] = customs(prev.get('exp'))
    # ②③ DART
    qs = dict(prev.get('qs') or {})
    cl = dict(prev.get('cl') or {})
    if DART_KEY:
        try:
            cmap = corp_map()
            todo = [(c, n) for _, mem in GROUPS for c, n in mem]
            for c, n in todo:
                try:
                    r = q_financials(cmap[c])
                    if r:
                        qs[c] = {'n': n, 'q': r}
                        print(c, n, 'qs', len(r), file=sys.stderr)
                except Exception as e:
                    DEBUG.append('qs %s %r' % (c, str(e)[:40]))
            for c, n in CL_CODES:
                try:
                    r = contract_liab(cmap[c])
                    if r:
                        cl[c] = {'n': n, 'q': r}
                        print(c, n, 'cl', len(r), file=sys.stderr)
                except Exception as e:
                    DEBUG.append('cl %s %r' % (c, str(e)[:40]))
        except Exception as e:
            DEBUG.append('DART %r' % str(e)[:60])
    else:
        DEBUG.append('DART_KEY 없음')
    out['qs'] = qs
    out['cl'] = cl
    out['groups'] = [[g, [c for c, _ in mem]] for g, mem in GROUPS]
    # ④ 글로벌
    g = dict(prev.get('global') or {})
    g['tf'] = g_trendforce(g.get('tf'))
    g['sia'] = g_sia(g.get('sia'))
    g['semi'] = g_news('SEMI North America semiconductor equipment billings', g.get('semi'), r'billing')
    g['tsmc'] = g_news('TSMC monthly revenue', g.get('tsmc'), r'revenue')
    g['asml'] = g_news('ASML bookings orders quarterly', g.get('asml'), r'booking|order')
    out['global'] = g
    out['debug'] = DEBUG[-20:]
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    # 빈 결과 덮어쓰기 방지: 이전보다 심하게 줄면 이전 유지
    if prev and not out['exp'] and not qs and prev.get('qs'):
        print('수집 실패 — 기존 유지', file=sys.stderr)
        sys.exit(0)
    json.dump(out, open(OUT, 'w', encoding='utf-8'), ensure_ascii=False)
    print('완료', DEBUG, file=sys.stderr)

if __name__ == '__main__':
    main()
