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

def get(url, timeout=25, binary=False, encoding='euc-kr'):
    r = urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout).read()
    return r if binary else r.decode(encoding, 'ignore')

def parse_date(s):
    m = re.fullmatch(r'(\d{2})\.(\d{2})\.(\d{2})', s.strip())
    return '20%s-%s-%s' % (m.group(1), m.group(2), m.group(3)) if m else None

def rows_of(html):
    return re.findall(r'<tr>([\s\S]*?)</tr>', html)

CONS = 'https://consensus.hankyung.com'
def strip_html(s):
    return re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', s)).strip()

def scrape(kind):
    """kind: 'industry' | 'company' — 한경컨센서스(consensus.hankyung.com) 목록.
    2026-09-10 네이버 금융 리서치 페이지가 신형(Next.js)으로 바뀌어 기존 파싱이 0건 → 소스 교체.
    행: 작성일 | 제목(a href=/analysis/downpdf?report_idx=N) | 투자의견 | 작성자 | 제공출처 | 차트 | 첨부.
    기업(CO)은 차트 링크 business_code=6자리, 산업(IN)은 제목 [대괄호]에서 분류 추출."""
    out = []
    rt = 'IN' if kind == 'industry' else 'CO'
    for page in range(1, 12):
        url = ('%s/analysis/list?sdate=%s&edate=%s&now_page=%d&search_text=&pagenum=80&report_type=%s'
               % (CONS, CUTOFF.isoformat(), TODAY.isoformat(), page, rt))
        try:
            h = get(url, encoding='utf-8')
        except Exception as e:
            DEBUG.append('%s p%d: %r' % (kind, page, e))
            break
        got_old = False
        n = 0
        for r in re.findall(r'<tr[^>]*>([\s\S]*?)</tr>', h):
            m = re.search(r'href="/analysis/downpdf\?report_idx=(\d+)"[^>]*>([^<]+)</a>', r)
            dt = re.search(r'>\s*(\d{4}-\d{2}-\d{2})\s*<', r)
            if not (m and dt):
                continue
            d = dt.group(1)
            if d < CUTOFF.isoformat():
                got_old = True
                continue
            tds = [strip_html(x) for x in re.findall(r'<td[^>]*>([\s\S]*?)</td>', r)]
            # 열 순서: 작성일, 제목, (목표가), 투자의견, 작성자, 제공출처, 차트, 첨부
            broker = ''
            for t in tds:
                if re.search(r'(증권|투자증권|리서치|IR협의회|자산운용|경제연구|캐피탈|Securities)$', t) or t.endswith('증권'):
                    broker = t
            if not broker and len(tds) >= 6:
                broker = tds[5] if kind == 'company' else tds[4]
            rid = m.group(1)
            title = strip_html(m.group(2))
            item = {'t': title, 'b': broker, 'd': d, 'pdf': '%s/analysis/downpdf?report_idx=%s' % (CONS, rid), 'v': 0, 'src': '한경컨센서스'}
            if kind == 'industry':
                cat = re.match(r'\s*\[([^\]]{1,20})\]', title)
                c = cat.group(1).strip() if cat else ''
                # 대괄호가 업종명일 때만(짧고 공백 없는 한글/영문/슬래시) 채택 — "[AI 홍수 속 살아남기]" 같은 제목 장식은 기타
                item['cat'] = c if (c and len(c) <= 12 and re.fullmatch(r'[가-힣A-Za-z0-9/·&]+', c)) else '기타'
                ic = re.search(r'industry_code=(\d+)', r)
                if ic: item['icode'] = ic.group(1)
            else:
                st = re.search(r'business_code=([0-9A-Z]{6})', r) or re.search(r'stockcd=([0-9A-Z]{6})', r)
                nm = re.match(r'\s*(.+?)\s*\(\s*([0-9A-Z]{6})\s*\)', title)
                if st or nm:
                    item['code'] = (st.group(1) if st else nm.group(2))
                    item['name'] = nm.group(1).strip() if nm else ''
                else:
                    continue
            out.append(item)
            n += 1
        if got_old or n == 0:
            break
        time.sleep(0.5)
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

def scrape_naver(kind):
    """네이버 신형 리서치 — 모바일 API 후보를 순서대로 시도해 첫 성공 패턴을 채택(2026-09 개편 대응).
    응답 JSON에서 pdf 링크·제목·날짜·증권사를 최대한 일반적으로 뽑는다. 실패하면 [] + DEBUG(진단)."""
    cat = 'industry' if kind == 'industry' else 'company'
    cands = ['https://m.stock.naver.com/api/research/%s?page=1&pageSize=50' % cat,
             'https://m.stock.naver.com/api/research/list?category=%s&page=1&pageSize=50' % cat,
             'https://m.stock.naver.com/api/research/%sList?page=1&pageSize=50' % cat,
             'https://m.stock.naver.com/api/research?type=%s&page=1&pageSize=50' % cat,
             'https://finance.naver.com/api/research/%s?page=1&pageSize=50' % cat]
    out = []
    for u in cands:
        try:
            raw = urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=20).read().decode('utf-8', 'ignore')
        except Exception as e:
            DEBUG.append('naver %s → %s' % (u.split('naver.com')[1][:60], repr(e)[:40])); continue
        if 'pdf' not in raw.lower() and 'report' not in raw.lower():
            DEBUG.append('naver %s → %d바이트, 리포트 흔적 없음: %s' % (u.split('naver.com')[1][:60], len(raw), re.sub(r'\s+', ' ', raw[:120]))); continue
        try:
            j = json.loads(raw)
        except Exception:
            DEBUG.append('naver %s → JSON 아님: %s' % (u.split('naver.com')[1][:60], re.sub(r'\s+', ' ', raw[:160]))); continue
        # 리스트 후보 탐색
        lst = None
        stack = [j]
        while stack and lst is None:
            x = stack.pop()
            if isinstance(x, list) and x and isinstance(x[0], dict) and any(k for k in x[0] if re.search(r'title|subject', k, re.I)):
                lst = x
            elif isinstance(x, dict):
                stack.extend(x.values())
            elif isinstance(x, list):
                stack.extend(x)
        if not lst:
            DEBUG.append('naver %s → 목록 키 미확인: %s' % (u.split('naver.com')[1][:60], list(j.keys())[:8] if isinstance(j, dict) else type(j).__name__)); continue
        DEBUG.append('naver 채택 %s → %d건, 키: %s' % (u.split('naver.com')[1][:60], len(lst), list(lst[0].keys())[:14]))
        for x in lst:
            def pick(*names):
                for k, v in x.items():
                    if any(re.search(n, k, re.I) for n in names) and v not in (None, ''):
                        return v
                return None
            title = pick('^title$', 'subject', 'title')
            pdf = pick('pdf', 'fileUrl', 'attach', 'file')
            d = pick('date', 'writeDate', 'regDate', 'createdAt')
            broker = pick('broker', 'company', 'secur', 'org', 'source')
            if not (title and d):
                continue
            ds = re.sub(r'[^0-9]', '', str(d))[:8]
            if len(ds) == 8:
                ds = '%s-%s-%s' % (ds[:4], ds[4:6], ds[6:8])
            elif len(ds) == 6:
                ds = '20%s-%s-%s' % (ds[:2], ds[2:4], ds[4:6])
            else:
                continue
            if ds < CUTOFF.isoformat():
                continue
            item = {'t': str(title).strip(), 'b': str(broker or '').strip(), 'd': ds, 'pdf': str(pdf or ''), 'v': int(pick('read', 'view', 'hit') or 0), 'src': '네이버'}
            if kind == 'industry':
                c = pick('category', 'industry', 'upjong', 'sector')
                item['cat'] = str(c).strip() if c else (re.match(r'\s*\[([^\]]{1,20})\]', item['t']).group(1) if re.match(r'\s*\[([^\]]{1,20})\]', item['t']) else '기타')
            else:
                code = pick('itemCode', 'stockCode', 'code')
                name = pick('itemName', 'stockName', 'name')
                if not code:
                    continue
                item['code'], item['name'] = str(code), str(name or '')
            if item['pdf']:
                out.append(item)
        break
    DEBUG.append('naver %s %d건' % (kind, len(out)))
    return out

def merge_reports(a, b):
    """두 소스 병합 — 같은 날짜+증권사+제목(공백·괄호 정규화)이면 중복. 한경 항목을 우선."""
    def key(x):
        t = re.sub(r'[\s\[\]\(\)【】·,.\-_]', '', x.get('t', '')).lower()[:40]
        return (x.get('d'), re.sub(r'(투자)?증권|㈜|\s', '', x.get('b', '')), t)
    seen, out = set(), []
    for x in list(a) + list(b):
        k = key(x)
        if k in seen or x.get('pdf') in seen:
            continue
        seen.add(k); seen.add(x.get('pdf'))
        out.append(x)
    return out

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

def gn_resolve(link):
    """구글뉴스 리다이렉트 → 실제 기사 URL (batchexecute 해독)"""
    try:
        art_id = link.split('/articles/')[1].split('?')[0]
        h = urllib.request.urlopen(urllib.request.Request(link, headers=UA), timeout=20).read().decode('utf-8', 'ignore')
        sg = re.search(r'data-n-a-sg="([^"]+)"', h)
        ts = re.search(r'data-n-a-ts="([^"]+)"', h)
        if not (sg and ts):
            return None
        inner = json.dumps(["garturlreq", [["X", "X", ["X", "X"], None, None, 1, 1, "US:en", None, 1,
                            None, None, None, None, None, 0, 1], "X", "X", 1, [1, 1, 1], 1, 1, None, 0, 0, None, 0],
                            art_id, int(ts.group(1)), sg.group(1)])
        freq = json.dumps([[["Fbv4je", inner, None, "generic"]]])
        body = urllib.parse.urlencode({'f.req': freq}).encode()
        req = urllib.request.Request('https://news.google.com/_/DotsSplashUi/data/batchexecute',
                                     data=body, headers=dict(UA, **{'Content-Type': 'application/x-www-form-urlencoded;charset=UTF-8'}))
        r = urllib.request.urlopen(req, timeout=20).read().decode('utf-8', 'ignore')
        seg = r.split('garturlres')[-1] if 'garturlres' in r else r
        m = re.search(r'"(https?://[^"\\]+)', seg)
        return m.group(1) if m else None
    except Exception:
        return None

def fetch_body_ko(url):
    """기사 본문 추출 → 한국어 번역 (문단 그룹 단위). 실패 시 None"""
    try:
        h = urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=25).read().decode('utf-8', 'ignore')
    except Exception:
        return None
    ps = [re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', '', p)).strip()
          for p in re.findall(r'<p[^>]*>([\s\S]*?)</p>', h)]
    ps = [p for p in ps if len(p) > 80 and '.' in p and 'cookie' not in p.lower() and 'browser' not in p.lower()]
    if not ps:
        return None
    ps = ps[:22]
    # ~1600자 단위 청크로 묶어 번역
    chunks, cur = [], ''
    for p in ps:
        if len(cur) + len(p) > 1600 and cur:
            chunks.append(cur)
            cur = p
        else:
            cur = (cur + ' ' + p).strip()
    if cur:
        chunks.append(cur)
    out = []
    for c in chunks[:6]:
        try:
            u = ('https://translate.googleapis.com/translate_a/single?client=gtx&sl=en&tl=ko&dt=t&q='
                 + urllib.parse.quote(c))
            raw = urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=25).read().decode('utf-8')
            out.append(''.join(s[0] for s in json.loads(raw)[0]).strip())
        except Exception:
            break
        time.sleep(0.3)
    return '\n\n'.join(out) if out else None

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
            if prev_x and prev_x.get('t_en') == title and prev_x.get('body'):  # 본문 번역까지 완료 → 재사용
                out.append(prev_x)
                n += 1
                continue
            summ = strip_tags(ds.group(1))[:220] if ds else ''
            item = prev_x if (prev_x and prev_x.get('t_en') == title) else {
                'src': src, 'd': d or TODAY.isoformat(), 'link': link,
                't_en': title, 't': translate_ko(title)}
            if summ and src in ('ING THINK', 'McKinsey') and not item.get('s'):
                item['s'] = translate_ko(summ)
            out.append(item)
            n += 1
            time.sleep(0.25)
            if n >= 20:
                break
        DEBUG.append('해외 %s %d건' % (src, n))
    # 본문 통번역 (실행당 최대 25건 — 나머지는 다음 실행에서)
    done_body = 0
    for x in out:
        if x.get('body') or done_body >= 25:
            continue
        real = x.get('url')
        if not real:
            real = x['link'] if 'news.google.com' not in x['link'] else gn_resolve(x['link'])
            if real:
                x['url'] = real
        if real:
            b = fetch_body_ko(real)
            if b and len(b) > 300:
                x['body'] = b[:7000]
        done_body += 1
        time.sleep(0.5)
    DEBUG.append('해외 본문 번역 %d건 시도, 보유 %d건' % (done_body, sum(1 for x in out if x.get('body'))))
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
    try:   # 네이버 신형 리서치(모바일 API) 병합 — 실패해도 한경 결과는 유지
        ind = merge_reports(ind, scrape_naver('industry'))
        cmp_ = merge_reports(cmp_, scrape_naver('company'))
    except Exception as e:
        DEBUG.append('naver 병합 예외 %r' % e)
    ind.sort(key=lambda x: x['d'], reverse=True); cmp_.sort(key=lambda x: x['d'], reverse=True)
    DEBUG.append('병합 후 industry %d · company %d' % (len(ind), len(cmp_)))
    count_pages(ind, cache, ancache)
    count_pages(cmp_, cache, ancache)
    gl = scrape_global(prev.get('global'))
    for arr in (ind, cmp_):
        arr.sort(key=lambda x: (-(x.get('pg') or 0), x['d']), reverse=False)
        arr.sort(key=lambda x: (x.get('pg') or 0), reverse=True)
    live = set(x['pdf'] for x in ind + cmp_)
    # 📚 아카이브: 50페이지 이상 심층 리포트는 무기한 누적 (7일 창에서 빠져도 보존)
    archive = {x['pdf']: x for x in (prev.get('archive') or []) if x.get('pdf')}
    for kind, arr in (('industry', ind), ('company', cmp_)):
        for x in arr:
            if (x.get('pg') or 0) >= 50:
                y = dict(x); y['kind'] = kind
                old = archive.get(x['pdf']) or {}
                if not old or (y.get('v') or 0) >= (old.get('v') or 0):
                    archive[x['pdf']] = {**old, **y}
    # 📌 수동 시드(광통신·유리기판 등 심층 리포트) 병합 — public/data/report_seeds.json
    try:
        seeds = json.load(open('public/data/report_seeds.json', encoding='utf-8')).get('items') or []
        for s in seeds:
            if s.get('pdf'):
                old = archive.get(s['pdf']) or {}
                archive[s['pdf']] = {**old, **s, 'seed': True}
        DEBUG.append('시드 %d건' % len(seeds))
    except Exception as e:
        DEBUG.append('시드 병합 실패: %r' % e)
    arch_list = sorted(archive.values(), key=lambda x: (x.get('d') or '', x.get('pg') or 0), reverse=True)
    DEBUG.append('아카이브 %d건' % len(arch_list))
    out = {'updated': time.strftime('%Y-%m-%d %H:%M'), 'debug': DEBUG,
           'industry': ind, 'company': cmp_, 'global': gl, 'archive': arch_list,
           'pagecache': {k: v for k, v in cache.items() if v and k in live},
           'ancache': {k: v for k, v in ancache.items() if k in live}}
    import os
    os.makedirs('public/data', exist_ok=True)
    with open(OUT, 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False)
    print('완료:', DEBUG)

if __name__ == '__main__':
    main()
