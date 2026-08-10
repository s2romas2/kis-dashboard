#!/usr/bin/env python3
# 뷰티 트렌드 수집 (화장품·의료기기/시술 브랜드)
# - 구글트렌드 KR: 중분류별 브랜드 비교(최대 5개) + 브랜드별 [브랜드+제품] 검색지수
# - 구글트렌드 US: 중분류별 브랜드 비교 (us 이름 있는 브랜드만)
# - 아마존 US 자동완성: 브랜드별 인기 검색어(실제 아마존 검색 수요 순위)
# 429 차단 시 성공분만 갱신(누적). 100분 경과 시 남은 작업은 다음 실행으로.
import os, sys, json, time, re, html, urllib.request, urllib.parse

OUT = 'public/data/beauty.json'
DEBUG = []
START_T = time.time()
TIME_LIMIT = 100 * 60

def prev():
    try:
        return json.load(open(OUT, encoding='utf-8'))
    except Exception:
        return {}

def timeup():
    return time.time() - START_T > TIME_LIMIT

def amazon_sug(brand_us):
    url = ('https://completion.amazon.com/api/2017/suggestions?limit=11&prefix=%s'
           '&suggestion-type=KEYWORD&alias=aps&site-variant=desktop&version=3'
           '&event=onKeyPress&wc=&lop=en_US&mid=ATVPDKIKX0DER&plain-mid=1&client-info=amazon-search-ui'
           % urllib.parse.quote(brand_us.lower()))
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'})
    d = json.loads(urllib.request.urlopen(req, timeout=15).read().decode())
    return [s.get('value') for s in d.get('suggestions', []) if s.get('value')]

REDDIT_SUBS = ['AsianBeauty', 'KoreanBeauty', 'SkincareAddiction', '30PlusSkinCare']

def translate_ko(text):
    """구글 번역 gtx (무키). 실패 시 원문 유지. 반드시 UTF-8 디코드."""
    try:
        u = ('https://translate.googleapis.com/translate_a/single?client=gtx&sl=en&tl=ko&dt=t&q='
             + urllib.parse.quote(text[:300]))
        raw = urllib.request.urlopen(urllib.request.Request(
            u, headers={'User-Agent': 'Mozilla/5.0'}), timeout=20).read().decode('utf-8')
        return ''.join(seg[0] for seg in json.loads(raw)[0]).strip()
    except Exception:
        return text

def reddit_posts(prev_rd):
    """레딧 뷰티 서브레딧 주간 인기글 (RSS — JSON API는 클라우드 차단, RSS는 허용 확인됨)"""
    prev_tr = {}
    for arr in (prev_rd or {}).values():
        if isinstance(arr, list):
            for p in arr:
                prev_tr[p.get('link')] = p
    out = {}
    for sub in REDDIT_SUBS:
        try:
            x = urllib.request.urlopen(urllib.request.Request(
                'https://www.reddit.com/r/%s/top/.rss?t=week' % sub,
                headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}), timeout=25).read().decode('utf-8', 'ignore')
            posts = []
            for e in re.findall(r'<entry>([\s\S]*?)</entry>', x)[:8]:
                t = re.search(r'<title>([^<]*)</title>', e)
                l = re.search(r'<link href="([^"]+)"', e)
                d = re.search(r'<updated>([^<]+)</updated>', e)
                if not (t and l):
                    continue
                title = html.unescape(t.group(1)).strip()
                link = html.unescape(l.group(1))
                pv = prev_tr.get(link)
                ko = pv['t'] if (pv and pv.get('t_en') == title and pv.get('t')) else translate_ko(title)
                posts.append({'t': ko, 't_en': title, 'link': link, 'd': (d.group(1)[:10] if d else '')})
                time.sleep(0.25)
            out[sub] = posts
            DEBUG.append('레딧 %s %d건' % (sub, len(posts)))
        except Exception as e:
            DEBUG.append('레딧 %s: %r' % (sub, str(e)[:60]))
            if prev_rd and sub in prev_rd:
                out[sub] = prev_rd[sub]
        time.sleep(0.5)
    return out

def main():
    keys = json.load(open('public/beautykeys.json', encoding='utf-8'))
    pv = prev()
    gt = {'KR': dict((pv.get('gt') or {}).get('KR') or {}), 'US': dict((pv.get('gt') or {}).get('US') or {})}
    amazon = dict(pv.get('amazon') or {})

    # ---- 수집 작업 목록 구성 ----
    jobs = []  # (geo, [keywords])
    for big, mids in keys.items():
        for mid, brands in mids.items():
            kr_names = list(brands.keys())
            for i in range(0, len(kr_names), 5):  # KR 중분류 브랜드 비교
                jobs.append(('KR', kr_names[i:i+5]))
            us_names = [v['us'] for v in brands.values() if v.get('us')]
            for i in range(0, len(us_names), 5):  # US 중분류 브랜드 비교
                jobs.append(('US', us_names[i:i+5]))
            for b, v in brands.items():          # KR 브랜드+제품 (제품 4개씩 묶음, 개수 제한 없음)
                prods = v.get('products') or []
                for ci in range(0, len(prods), 4):
                    jobs.append(('KR', [b] + prods[ci:ci + 4]))

    # ---- 구글트렌드 ----
    ok = skip = 0
    try:
        from pytrends.request import TrendReq
        pt = TrendReq(hl='ko', tz=-540)
        for geo, kws in jobs:
            if timeup():
                skip += 1
                continue
            # 이번 실행에서 이미 갱신됐으면 생략(중복 키워드)
            fresh = [k for k in kws if not gt[geo].get('_run_' + k)]
            if not fresh:
                continue
            for attempt in range(2):
                try:
                    pt.build_payload(kws, timeframe='today 5-y', geo=geo)
                    df = pt.interest_over_time()
                    for kw in kws:
                        if kw in df.columns:
                            gt[geo][kw] = [[d.strftime('%Y-%m-%d'), int(v)] for d, v in df[kw].items()]
                            gt[geo]['_run_' + kw] = 1
                    ok += 1
                    time.sleep(13)
                    break
                except Exception as e:
                    if attempt == 1:
                        skip += 1
                        if len(DEBUG) < 12:
                            DEBUG.append('GT %s %s: %s' % (geo, kws[0], str(e)[:60]))
                    time.sleep(30)
    except Exception as e:
        DEBUG.append('pytrends: %r' % e)
    for geo in gt:  # 실행 표시 제거
        gt[geo] = {k: v for k, v in gt[geo].items() if not k.startswith('_run_')}
    DEBUG.append('구글트렌드 성공 %d / 실패·이월 %d (총 %d작업)' % (ok, skip, len(jobs)))

    # ---- 아마존 자동완성 ----
    a_ok = 0
    for big, mids in keys.items():
        for mid, brands in mids.items():
            for b, v in brands.items():
                us = v.get('us')
                if not us:
                    continue
                try:
                    sug = amazon_sug(us)
                    if sug:
                        amazon[b] = sug
                        a_ok += 1
                except Exception as e:
                    if len(DEBUG) < 15:
                        DEBUG.append('아마존 %s: %r' % (b, e))
                time.sleep(0.6)
    DEBUG.append('아마존 %d개 브랜드' % a_ok)

    rd = reddit_posts(pv.get('reddit'))
    out = {'updated': time.strftime('%Y-%m-%d %H:%M'), 'debug': DEBUG, 'gt': gt, 'amazon': amazon, 'reddit': rd}
    os.makedirs('public/data', exist_ok=True)
    with open(OUT, 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False)
    print('완료:', DEBUG)

if __name__ == '__main__':
    main()
