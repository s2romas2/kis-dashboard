#!/usr/bin/env python3
# 아마존 US 뷰티 베스트셀러 — 타깃 브랜드 순위 일일 추적
# 노드 목록: public/amazonnodes.json (REFRESH=1 로 재탐색)
# 브랜드:    public/amazonbrands.json
# 결과:      public/data/amazon.json  {updated, groups, cats, items, sum, hist, debug}
#
# ⚠️ 아마존은 검색(/s)·상품페이지(/dp)를 봇 차단한다. 베스트셀러(/zgbs)만 열린다.
#    따라서 "브랜드 순위 조회"가 아니라 "베스트셀러 목록에 있으면 포착"하는 방식이다.
#    페이지당 30개만 서버 렌더(나머지는 스크롤 로딩) → pg=1 은 1~30위, pg=2 는 51~80위.
#    즉 31~50위·81~100위는 구조적으로 수집되지 않는다. "미포착"이 "랭킹 밖"을 뜻하지 않음에 주의.
import os, sys, json, re, time, gzip, html, random, urllib.request, datetime

OUT = os.environ.get('OUT', 'public/data/amazon.json')
NODES = 'public/amazonnodes.json'
BRANDS = 'public/amazonbrands.json'
HIST_DAYS = 120
PAGES = int(os.environ.get('PAGES', '2'))
LIMIT = int(os.environ.get('LIMIT', '0'))      # 테스트용 카테고리 수 제한
SLEEP = float(os.environ.get('SLEEP', '1.7'))
DEBUG = []
UA = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36',
      'Accept-Language': 'en-US,en;q=0.9', 'Accept': 'text/html,application/xhtml+xml',
      'Accept-Encoding': 'gzip'}

def get(u, tries=2):
    last = None
    for i in range(tries):
        try:
            r = urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=30)
            raw = r.read()
            if r.headers.get('Content-Encoding') == 'gzip':
                raw = gzip.decompress(raw)
            h = raw.decode('utf-8', 'ignore')
            if 'captcha' in h.lower() and len(h) < 20000:
                last = 'captcha'; time.sleep(4 + i * 4); continue
            return h
        except Exception as e:
            last = repr(e)[:60]; time.sleep(3 + i * 3)
    raise RuntimeError(last or 'fail')

def parse(h):
    out = []
    for b in re.findall(r'id="gridItemRoot"[\s\S]{0,4000}?</div></div></div>', h):
        rk = re.search(r'zg-bdg-text[^>]*>#(\d+)', b)
        a = re.search(r'data-asin="([A-Z0-9]{10})"', b)
        t = re.search(r'<img alt="([^"]{3,300})"', b)
        if rk and a:
            out.append({'r': int(rk.group(1)), 'a': a.group(1),
                        't': html.unescape(t.group(1)).strip() if t else ''})
    return out

def main():
    nodes = json.load(open(NODES, encoding='utf-8'))['nodes']
    brands = json.load(open(BRANDS, encoding='utf-8'))['brands']
    try:
        prev = json.load(open(OUT, encoding='utf-8'))
    except Exception:
        prev = {}
    today = datetime.date.today().isoformat()
    prev_items = {f"{i['b']}|{i['c']}|{i['a']}": i['r'] for i in (prev.get('items') or [])}

    items, cats, fail = [], [], 0
    ids = list(nodes.items())
    if LIMIT:
        ids = ids[:LIMIT]
    for nid, nd in ids:
        got = []
        for pg in range(1, PAGES + 1):
            u = nd['u'] + ('' if pg == 1 else '?pg=%d' % pg)
            try:
                got += parse(get(u))
            except Exception as e:
                fail += 1
                if len(DEBUG) < 12:
                    DEBUG.append('%s p%d %s' % (nd['n'][:24], pg, str(e)[:40]))
            time.sleep(SLEEP + random.random() * 0.6)
        if not got:
            continue
        cats.append({'id': nid, 'n': nd['n'], 'g': nd['g'], 'cnt': len(got)})
        seen = set()
        for x in got:
            tl = x['t'].lower()
            for b in brands:
                if b.get('off'):
                    continue
                if any(p.lower() in tl for p in b['pat']):
                    key = (b['k'], nid, x['a'])
                    if key in seen:
                        continue
                    seen.add(key)
                    pr = prev_items.get('%s|%s|%s' % (b['k'], nid, x['a']))
                    items.append({'b': b['k'], 'c': nid, 'a': x['a'], 't': x['t'][:150],
                                  'r': x['r'], 'pr': pr,
                                  'd': (pr - x['r']) if pr else None})
                    break

    # 브랜드 요약
    summ = []
    for b in brands:
        if b.get('off'):
            continue
        mine = [i for i in items if i['b'] == b['k']]
        best = min(mine, key=lambda i: i['r']) if mine else None
        gs = sorted({(next((c['g'] for c in cats if c['id'] == i['c']), '?')) for i in mine})
        summ.append({'k': b['k'], 'nm': b.get('nm', b['k']), 'co': b.get('co', ''),
                     'n': len(mine), 'gs': gs,
                     'best': best['r'] if best else None,
                     'bestc': (next((c['n'] for c in cats if c['id'] == best['c']), '') if best else ''),
                     'bestt': best['t'][:90] if best else ''})
    summ.sort(key=lambda s: (s['best'] is None, s['best'] or 999, -s['n']))

    # 이력 — 브랜드별 "최고 순위"만 날짜별로 보관
    hist = dict(prev.get('hist') or {})
    hist[today] = {s['k']: s['best'] for s in summ}
    for d in sorted(hist)[:-HIST_DAYS]:
        hist.pop(d, None)

    out = {'updated': time.strftime('%Y-%m-%d %H:%M'), 'date': today,
           'cats': cats, 'items': items, 'sum': summ, 'hist': hist,
           'groups': sorted({c['g'] for c in cats}),
           'debug': DEBUG + ['카테고리 %d · 포착 %d건 · 실패 %d' % (len(cats), len(items), fail)]}
    if not cats and prev:                     # 전면 실패 시 기존 파일 보존
        prev['debug'] = DEBUG + ['수집 전면 실패 — 기존 데이터 유지']
        json.dump(prev, open(OUT, 'w', encoding='utf-8'), ensure_ascii=False)
        return
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(out, open(OUT, 'w', encoding='utf-8'), ensure_ascii=False)
    print('저장 %s — 카테고리 %d · 포착 %d건' % (OUT, len(cats), len(items)), file=sys.stderr)

if __name__ == '__main__':
    main()
