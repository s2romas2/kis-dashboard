#!/usr/bin/env python3
# 증권사 리포트 수집 — 네이버 금융 리서치 (산업분석·종목분석)
# 최근 7일 발간분, PDF 페이지수 측정(심층 리포트 정렬용), 매일 갱신
# 출처: 각 증권사 원문 PDF (네이버 리서치 공개 링크)
import json, re, time, datetime, urllib.request, sys, io

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
    # 중복 제거(pdf 기준)
    seen, uniq = set(), []
    for x in out:
        if x['pdf'] not in seen:
            seen.add(x['pdf'])
            uniq.append(x)
    DEBUG.append('%s %d건' % (kind, len(uniq)))
    return uniq

def count_pages(items, cache):
    try:
        from pypdf import PdfReader
    except Exception as e:
        DEBUG.append('pypdf 없음: %r' % e)
        return
    dl = 0
    for x in items:
        u = x['pdf']
        if u in cache:
            x['pg'] = cache[u]
            continue
        if dl >= MAX_PDF_DL:
            continue
        try:
            b = get(u, timeout=60, binary=True)
            pg = len(PdfReader(io.BytesIO(b)).pages)
            x['pg'] = cache[u] = pg
        except Exception as e:
            if len(DEBUG) < 15:
                DEBUG.append('PDF %s: %r' % (u[-30:], e))
            cache[u] = None
        dl += 1
        time.sleep(0.3)
    DEBUG.append('PDF 측정 %d건 (캐시 %d)' % (dl, len(cache)))

def main():
    try:
        prev = json.load(open(OUT, encoding='utf-8'))
    except Exception:
        prev = {}
    cache = {k: v for k, v in (prev.get('pagecache') or {}).items() if v}
    ind = scrape('industry')
    cmp_ = scrape('company')
    count_pages(ind, cache)
    count_pages(cmp_, cache)
    for arr in (ind, cmp_):
        arr.sort(key=lambda x: (-(x.get('pg') or 0), x['d']), reverse=False)
        arr.sort(key=lambda x: (x.get('pg') or 0), reverse=True)
    out = {'updated': time.strftime('%Y-%m-%d %H:%M'), 'debug': DEBUG,
           'industry': ind, 'company': cmp_,
           'pagecache': {k: v for k, v in cache.items() if v}}
    import os
    os.makedirs('public/data', exist_ok=True)
    with open(OUT, 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False)
    print('완료:', DEBUG)

if __name__ == '__main__':
    main()
