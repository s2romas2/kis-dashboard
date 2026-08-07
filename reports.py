#!/usr/bin/env python3
# 증권사 리포트 수집 — 네이버 금융 리서치 (산업분석·종목분석) + 해외 리서치(번역)
# 최근 7일 발간분, PDF 페이지수·애널리스트 추출, 매일 갱신
# 해외: GS·MS·JPM·UBS(구글뉴스 site: 필터)·ING THINK·McKinsey 공개 리서치 — 제목·요약 한국어 번역
import json, re, time, datetime, urllib.request, urllib.parse, sys, io
import email.utils

OUT = 'public/data/reports.json'
UA = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
DEBUG = []
TODAY = datetime.date.today()
CUTOFF = TODAY - datetime.timedelta(days=7)
MAX_PDF_DL = 100  # 실행당 페이지수 측정 최대 건수

def get(url, timeout=25, binary=False):
    r = urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout).read()
    return r if binary else r.decode('euc-kr', 'ignore')

def parse_date(s):
    m = re.fullmatch(r'(\d{2})\.(\d{2})\.(\d{2})', s.strip())
    return '20%s-%s-%s' % (m.group(1), m.group(2), m.group(3)) if m else None

def rows_of(html):
    return re.findall(r'<tr>([\s\S]*?)</tr>', html)

def scrape(kind):
    """kind: 'industry' | 'company'"""
    out = []
    for page in range(1, 8):
        try:
            h = get('https://finance.naver.com/research/%s_list.naver?page=%d' % (kind, page))
        except Exception as e:
            DEBUG.append('%s p%d: %r' % (kind, page, e))
            break
        got_old = False
        n = 0
        for r in rows_of(h):
            pdf = re.search(r'href="(https?://stock\.pstatic\.net/[^"]+\.pdf)"', r)
            dt = re.search(r'class="date"[^>]*>(\d{2}\.\d{2}\.\d{2})<', r)
            title = re.search(r'href="%s_read\.naver[^"]*">([^<]+)<' % kind, r)
            broker = re.findall(r'<td>([^<]+)</td>', r)
            if not (pdf and dt and title):
                continue
            d = parse_date(dt.group(1))
            if not d:
                continue
            if d < CUTOFF.isoformat():
                got_old = True
                continue
            views = re.findall(r'class="date">(\d+)<', r)
            item = {'t': title.group(1).strip(), 'b': broker[-1].strip() if broker else '',
                    'd': d, 'pdf': pdf.group(1), 'v': int(views[-1]) if views else 0}
            if kind == 'industry':
                cat = re.search(r'<td style="padding-left:10">([^<]+)</td>', r)
                item['cat'] = cat.group(1).strip() if cat else '기타'
            else:
                st = re.search(r'code=(\d{6})"[^>]*title="([^"]+)"', r)
                if st:
                    item['code'], item['name'] = st.group(1), st.group(2)
                else:
                    continue
            out.append(item)
            n += 1
        if got_old or n == 0:
            break
        time.sleep(0.4)
    # 중복 제거 (PDF 주소 + 제목·증권사·날짜 조합)
    seen, uniq = set(), []
    for x in out:
        k1 = x['pdf']
        k2 = (x['t'], x['b'], x['d'], x.get('code', ''))
        if k1 in seen or k2 in seen:
            continue
        seen.add(k1); seen.add(k2)
        uniq.append(x)
    DEBUG.append('%s %d건' % (kind, len(uniq)))
    return uniq

AN_PAT = re.compile(r'([가-힣]{2,4})\s*(?:선임연구원|수석연구원|책임연구원|연구위원|연구원|애널리스트|Analyst)')
AN_PAT2 = re.compile(r'(?:Analyst|애널리스트)\s*[|:.\s]\s*([가-힣]{2,4})')

def extract_analysts(reader):
    names = []
    try:
        for pg in reader.pages[:2]:
            tx = pg.extract_text() or ''
            for m in AN_PAT.findall(tx) + AN_PAT2.findall(tx):
                if m not in names and m not in ('투자', '자료', '리서치', '증권사', '의료기기', '반도체', '제약',
                                                '바이오', '화장품', '인터넷', '플랫폼', '담당', '수석', '책임', '선임'):
                    names.append(m)
    except Exception:
        pass
    return names[:4]

def count_pages(items, cache, ancache):
    try:
        from pypdf import PdfReader
    except Exception as e:
        DEBUG.append('pypdf 없음: %r' % e)
        return
    dl = 0
    for x in items:
        u = x['pdf']
        if u in cache and u in ancache:
            x['pg'] = cache[u]
            if ancache[u]:
                x['an'] = ancache[u]
            continue
        if dl >= MAX_PDF_DL:
            if u in cache:
                x['pg'] = cache[u]
            continue
        try:
            b = get(u, timeout=60, binary=True)
            rd = PdfReader(io.BytesIO(b))
            x['pg'] = cache[u] = len(rd.pages)
            an = extract_analysts(rd)
            ancache[u] = an
            if an:
                x['an'] = an
        except Exception as e:
            if len(DEBUG) < 15:
                DEBUG.append('PDF %s: %r' % (u[-30:], e))
            cache.setdefault(u, None)
            ancache.setdefault(u, [])
        dl += 1
        time.sleep(0.3)
    DEBUG.append('PDF 측정 %d건 (캐시 %d)' % (dl, len(cache)))

def translate_ko(text):
    """구글 번역 비공식 엔드포인트 (무키). 실패 시 원문 유지."""
    try:
        u = ('https://translate.googleapis.com/translate_a/single?client=gtx&sl=en&tl=ko&dt=t&q='
             + urllib.parse.quote(text[:400]))
        raw = urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=20).read().decode('utf-8')
        r = json.loads(raw)
        return ''.join(s[0] for s in r[0]).strip()
    except Exception:
        return text

GLOBAL_FEEDS = [
    ('Goldman Sachs', 'https://news.google.com/rss/search?q=' + urllib.parse.quote('site:goldmansachs.com/insights when:7d') + '&hl=en-US&gl=US&ceid=US:en'),
    ('Morgan Stanley', 'https://news.google.com/rss/search?q=' + urllib.parse.quote('site:morganstanley.com/insights when:7d') + '&hl=en-US&gl=US&ceid=US:en'),
    ('J.P. Morgan', 'https://news.google.com/rss/search?q=' + urllib.parse.quote('site:jpmorgan.com/insights when:7d') + '&hl=en-US&gl=US&ceid=US:en'),
    ('UBS', 'https://news.google.com/rss/search?q=' + urllib.parse.quote('site:ubs.com when:7d research OR outlook OR CIO') + '&hl=en-US&gl=US&ceid=US:en'),
    ('ING THINK', 'https://think.ing.com/rss'),
    ('McKinsey', 'https://www.mckinsey.com/insights/rss'),
]

def strip_tags(s):
    return re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', '', s or '')).strip()

def scrape_global(prev_items):
    prev_tr = {x.get('link'): x for x in (prev_items or [])}
    out = []
    for src, feed in GLOBAL_FEEDS:
        try:
            x = urllib.request.urlopen(urllib.request.Request(feed, headers=UA), timeout=25).read().decode('utf-8', 'ignore')
        except Exception as e:
            DEBUG.append('해외 %s: %r' % (src, e))
            continue
        n = 0
        for it in re.findall(r'<item>([\s\S]*?)</item>', x):
            tt = re.search(r'<title>(?:<!\[CDATA\[)?([\s\S]*?)(?:\]\]>)?</title>', it)
            lk = re.search(r'<link>(?:<!\[CDATA\[)?([\s\S]*?)(?:\]\]>)?</link>', it)
            pd = re.search(r'<pubDate>([^<]+)</pubDate>', it)
            ds = re.search(r'<description>(?:<!\[CDATA\[)?([\s\S]*?)(?:\]\]>)?</description>', it)
            if not (tt and lk):
                continue
            title = strip_tags(tt.group(1))
            title = re.sub(r'\s*-\s*(Goldman Sachs|Morgan Stanley|J\.?P\.? ?Morgan(?: Chase)?(?: & Co\.?)?|UBS)\s*$', '', title, flags=re.I)
            d = None
            if pd:
                try:
                    d = email.utils.parsedate_to_datetime(pd.group(1)).date().isoformat()
                except Exception:
                    pass
            if d and d < CUTOFF.isoformat():
                continue
            link = lk.group(1).strip()
            prev_x = prev_tr.get(link)
            if prev_x and prev_x.get('t_en') == title:  # 이미 번역됨 → 재사용
                out.append(prev_x)
                n += 1
                continue
            summ = strip_tags(ds.group(1))[:220] if ds else ''
            item = {'src': src, 'd': d or TODAY.isoformat(), 'link': link,
                    't_en': title, 't': translate_ko(title)}
            if summ and src in ('ING THINK', 'McKinsey'):
                item['s'] = translate_ko(summ)
            out.append(item)
            n += 1
            time.sleep(0.25)
            if n >= 20:
                break
        DEBUG.append('해외 %s %d건' % (src, n))
    out.sort(key=lambda x: x['d'], reverse=True)
    return out[:90]

def main():
    try:
        prev = json.load(open(OUT, encoding='utf-8'))
    except Exception:
        prev = {}
    cache = {k: v for k, v in (prev.get('pagecache') or {}).items() if v}
    ancache = dict(prev.get('ancache') or {})
    ind = scrape('industry')
    cmp_ = scrape('company')
    count_pages(ind, cache, ancache)
    count_pages(cmp_, cache, ancache)
    gl = scrape_global(prev.get('global'))
    for arr in (ind, cmp_):
        arr.sort(key=lambda x: (-(x.get('pg') or 0), x['d']), reverse=False)
        arr.sort(key=lambda x: (x.get('pg') or 0), reverse=True)
    live = set(x['pdf'] for x in ind + cmp_)
    out = {'updated': time.strftime('%Y-%m-%d %H:%M'), 'debug': DEBUG,
           'industry': ind, 'company': cmp_, 'global': gl,
           'pagecache': {k: v for k, v in cache.items() if v and k in live},
           'ancache': {k: v for k, v in ancache.items() if k in live}}
    import os
    os.makedirs('public/data', exist_ok=True)
    with open(OUT, 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False)
    print('완료:', DEBUG)

if __name__ == '__main__':
    main()
