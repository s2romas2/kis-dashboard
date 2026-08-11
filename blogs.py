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

ALLOWED_STYLE = ('color', 'background-color', 'font-weight', 'font-style', 'text-decoration')

def clean_par(p_html):
    """문단 HTML에서 서식(색·굵기·크기·배경)만 남기고 정화 — se-fs-fsNN 클래스는 font-size로 변환"""
    def span_repl(m):
        attrs = m.group(1)
        styles = []
        cm = re.search(r'se-fs-fs(\d+)', attrs)
        if cm:
            styles.append('font-size:%spx' % min(int(cm.group(1)), 34))
        sm = re.search(r'style="([^"]*)"', attrs)
        if sm:
            for kv in html.unescape(sm.group(1)).split(';'):
                if ':' in kv:
                    k, v = kv.split(':', 1)
                    if k.strip().lower() in ALLOWED_STYLE:
                        styles.append(k.strip().lower() + ':' + v.strip())
        return '<span style="%s">' % ';'.join(styles) if styles else '<span>'
    s = re.sub(r'<!--[\s\S]*?-->', '', p_html)  # 주석 제거
    s = re.sub(r'<span([^>]*)>', span_repl, s)
    # 허용 태그(b·strong·i·em·u·span·br) 외 전부 제거
    s = re.sub(r'</?(?!(?:b|strong|i|em|u|span|br)\b)[a-zA-Z][^>]*/?>', '', s)
    for _ in range(3):  # 빈 span 제거(중첩 대비 반복)
        s = re.sub(r'<span[^>]*>\s*</span>', '', s)
    s = re.sub(r'<span>([\s\S]*?)</span>', r'\1', s)  # 스타일 없는 span 벗기기
    return s.replace('​', '').strip()

def fetch_body(link):
    """모바일 PostView를 문서 순서대로 파싱 → blocks(문단·이미지 원래 순서, 서식 보존), body(검색용), imgs"""
    u = link.split('?')[0].replace('blog.naver.com', 'm.blog.naver.com')
    h = get(u)
    blocks = []  # {'t':'p','x','h'} | {'t':'img','u'} | {'t':'file','u','nm'} — 문서 순서 유지
    matches = []
    for m in re.finditer(r"se-text-paragraph[^>]*>([\s\S]*?)</p>", h):
        matches.append((m.start(), 'p', m.group(1)))
    for m in re.finditer(r"data-linkdata='([^']+)'", h):
        matches.append((m.start(), 'ld', m.group(1)))
    for m in re.finditer(r'data-linkdata="([^"]+)"', h):
        matches.append((m.start(), 'ld', m.group(1)))
    # 첨부파일: 스마트에디터 se-file(파일명+저장링크) 또는 문서 확장자 다운로드 앵커
    for m in re.finditer(r'class="se-file-name[^"]*"[^>]*>([^<]+)</\w+>[\s\S]{0,800}?href="([^"]+)"', h):
        matches.append((m.start(), 'file', (m.group(2), html.unescape(m.group(1)).strip()[:80])))
    for m in re.finditer(r'<a[^>]+href="(https?://[^"]+?(?:PostFileDownload\.naver[^"]*|\.(?:pdf|xlsx?|docx?|pptx?|hwpx?|zip|csv)(?:\?[^"]*)?))"[^>]*>([\s\S]{0,250}?)</a>', h):
        nm = html.unescape(re.sub(r'<[^>]+>', '', m.group(2))).replace('​', '').strip()
        matches.append((m.start(), 'file', (m.group(1), (nm or m.group(1).split('/')[-1].split('?')[0])[:80])))
    matches.sort(key=lambda x: x[0])
    n_img = n_file = 0
    seen_files = set()
    for _, kind, payload in matches:
        if kind == 'p':
            txt = html.unescape(re.sub(r'<[^>]+>', '', payload)).replace('​', '').strip()
            blocks.append({'t': 'p', 'x': txt, 'h': clean_par(payload)})
        elif kind == 'file':
            url, nm = payload
            url = html.unescape(url)
            if url.startswith('http') and url not in seen_files and n_file < 6:
                seen_files.add(url)
                blocks.append({'t': 'file', 'u': url, 'nm': nm}); n_file += 1
        else:
            try:
                d = json.loads(html.unescape(payload))
                src = d.get('src')
            except Exception:
                src = None
            if src and src.startswith('http') and n_img < 12:
                if 'pstatic.net' in src and 'type=' not in src:
                    src += '?type=w966'  # 네이버 이미지 서버는 type 파라미터 필수
                if not (blocks and blocks[-1].get('u') == src):
                    blocks.append({'t': 'img', 'u': src}); n_img += 1
    # 연속 문단 병합(텍스트는 \n, 서식 HTML은 <br>) + 빈 줄 정리 + 길이 캡
    merged, bx, bh, total = [], [], [], 0
    def flush():
        nonlocal bx, bh, total
        if bx:
            t = re.sub(r'\n{3,}', '\n\n', '\n'.join(bx)).strip()
            hh = re.sub(r'(<br>\s*){3,}', '<br><br>', '<br>'.join(bh)).strip()
            hh = re.sub(r'^(<br>\s*)+|(<br>\s*)+$', '', hh)
            if t and total < BODY_CAP:
                merged.append({'t': 'p', 'x': t[:BODY_CAP - total], 'h': hh[:BODY_CAP * 2 - total]})
            bx, bh = [], []
    for b in blocks:
        if b['t'] == 'p':
            bx.append(b['x']); bh.append(b.get('h') or ''); total += len(b['x'])
        else:
            flush(); merged.append(b)  # img·file은 그대로 순서 유지
    flush()
    body = '\n'.join(b['x'] for b in merged if b['t'] == 'p')[:BODY_CAP]
    imgs = [b['u'] for b in merged if b['t'] == 'img']
    return body, imgs, merged

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
                body, imgs, blocks = fetch_body(link)
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
                          'body': body, 'imgs': imgs, 'blocks': blocks, 'tags': tags})
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
