#!/usr/bin/env python3
# 구독 블로거 글 수집 — RSS로 새 글 확인 → 모바일 PostView에서 본문·이미지 추출
# 블로거 추가: public/blogkeys.json 에 {"id": "블로그ID"} 추가만 하면 됨 (닉네임은 RSS에서 자동)
import json, re, time, html, urllib.request, sys, os

OUT = 'public/data/blogs.json'
UA = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126 Safari/537.36'}
MAX_POSTS = 25       # 블로거당 보관 글 수
NEW_FETCH_CAP = 12   # 실행당 블로거별 본문 신규 수집 상한
BODY_CAP = 20000
DEBUG = []

def get(url, timeout=20):
    return urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout).read().decode('utf-8', 'ignore')

def fetch_body(link):
    """모바일 PostView에서 본문 문단 + 이미지 URL 추출"""
    u = link.split('?')[0].replace('blog.naver.com', 'm.blog.naver.com')
    h = get(u)
    paras = re.findall(r'se-text-paragraph[^>]*>([\s\S]*?)</p>', h)
    body = '\n'.join(html.unescape(re.sub(r'<[^>]+>', '', p)).replace('​', '').strip() for p in paras)
    body = re.sub(r'\n{3,}', '\n\n', body).strip()[:BODY_CAP]
    imgs = []
    for m in re.findall(r"data-linkdata='([^']+)'", h) + re.findall(r'data-linkdata="([^"]+)"', h):
        try:
            d = json.loads(html.unescape(m))
            src = d.get('src')
            if src and src.startswith('http') and src not in imgs:
                imgs.append(src)
        except Exception:
            pass
    return body, imgs[:12]

def main():
    keys = json.load(open('public/blogkeys.json', encoding='utf-8'))
    try:
        prev = json.load(open(OUT, encoding='utf-8'))
    except Exception:
        prev = {}
    bloggers = dict(prev.get('bloggers') or {})
    # 종목 태그: 특장점 노트 종목명 매칭
    try:
        sn = json.load(open('public/stocknotes.json', encoding='utf-8'))
        stocks = [(s['name'], s['code']) for g in sn['industries'] for s in g['stocks']]
    except Exception:
        stocks = []

    for b in keys.get('bloggers', []):
        bid = b['id']
        try:
            x = get('https://rss.blog.naver.com/%s.xml' % bid)
        except Exception as e:
            DEBUG.append('%s RSS 실패: %s' % (bid, str(e)[:50]))
            continue
        nm = re.search(r'<channel>[\s\S]*?<title><!\[CDATA\[([^\]]+)\]\]></title>', x)
        name = b.get('name') or (nm.group(1).strip() if nm else bid)
        cur = bloggers.get(bid) or {'name': name, 'posts': []}
        cur['name'] = name
        known = {p['u'] for p in cur['posts']}
        items = re.findall(r'<item>([\s\S]*?)</item>', x)
        new_cnt = 0
        fresh = []
        for it in items:
            g = re.search(r'<guid>(https://blog\.naver\.com/[^<]+)</guid>', it)
            t = re.search(r'<title><!\[CDATA\[([\s\S]*?)\]\]></title>', it)
            d = re.search(r'<pubDate>([^<]+)</pubDate>', it)
            c = re.search(r'<category><!\[CDATA\[([\s\S]*?)\]\]></category>', it)
            if not (g and t):
                continue
            link = g.group(1)
            if link in known:
                continue
            if new_cnt >= NEW_FETCH_CAP:
                break
            try:
                body, imgs = fetch_body(link)
            except Exception as e:
                DEBUG.append('%s 본문 실패 %s: %s' % (bid, link[-12:], str(e)[:40]))
                continue
            # 날짜: RFC822 → YYYY-MM-DD
            date = ''
            if d:
                try:
                    import email.utils
                    dt = email.utils.parsedate_to_datetime(d.group(1))
                    date = dt.strftime('%Y-%m-%d')
                except Exception:
                    date = d.group(1)[:16]
            tags = sorted({name_ for name_, code in stocks
                           if name_ in t.group(1) or name_ in body[:4000]})[:6]
            fresh.append({'t': html.unescape(t.group(1)).strip(), 'u': link, 'd': date,
                          'cat': html.unescape(c.group(1)).strip() if c else '',
                          'body': body, 'imgs': imgs, 'tags': tags})
            new_cnt += 1
            time.sleep(0.6)
        cur['posts'] = sorted(fresh + cur['posts'], key=lambda p: p['d'], reverse=True)[:MAX_POSTS]
        bloggers[bid] = cur
        DEBUG.append('%s(%s) 신규 %d · 보관 %d' % (bid, name, new_cnt, len(cur['posts'])))

    out = {'updated': time.strftime('%Y-%m-%d %H:%M'), 'debug': DEBUG, 'bloggers': bloggers}
    os.makedirs('public/data', exist_ok=True)
    json.dump(out, open(OUT, 'w', encoding='utf-8'), ensure_ascii=False)
    print('완료:', DEBUG)

if __name__ == '__main__':
    main()
