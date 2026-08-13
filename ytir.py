#!/usr/bin/env python3
# 그로쓰리서치 유튜브 기업탐방 영상 수집
# - 채널 videos 탭 ytInitialData → 목록(제목·상대날짜·조회수·스니펫)
# - watch 페이지 접근 가능하면 정확한 게시일·전체 설명으로 업그레이드(막히면 스니펫 유지, approx 표시)
# - 종목 태그: 특장점 노트 + 전체 상장사명(3자 이상) 매칭
# 결과: public/data/ytir.json {updated, videos:[{id,ch,t,d,desc,tags,views,approx?}]}
import json, re, time, urllib.request, os, sys, datetime

CHANNELS = [('그로쓰리서치', 'https://www.youtube.com/@growthresearch/videos')]
OUT = 'public/data/ytir.json'
UA = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126 Safari/537.36',
      'Accept-Language': 'ko-KR,ko;q=0.9'}
MAX_KEEP = 100
NEW_CAP = 20      # 실행당 신규 상한
UPGRADE_CAP = 10  # 실행당 approx→정밀 업그레이드 상한
DEBUG = []

def get(url, timeout=25):
    return urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout).read().decode('utf-8', 'ignore')

def rel2date(txt):
    """'3주 전' 등 상대시각 → 근사 날짜"""
    if not txt:
        return ''
    m = re.search(r'(\d+)\s*(분|시간|일|주|개월|년)', txt)
    if not m:
        return ''
    n, unit = int(m.group(1)), m.group(2)
    days = {'분': 0, '시간': 0, '일': n, '주': n * 7, '개월': n * 30, '년': n * 365}[unit]
    return (datetime.date.today() - datetime.timedelta(days=days)).isoformat()

def list_videos(url):
    """videos 탭 → [{'id','t','rel','views','snip'}] 최신순"""
    h = get(url)
    m = re.search(r'var ytInitialData = (\{[\s\S]*?\});</script>', h)
    out, seen = [], set()
    if m:
        try:
            data = json.loads(m.group(1))
            def texts(o, acc):
                if isinstance(o, dict):
                    for k, x in o.items():
                        if k == 'content' and isinstance(x, str):
                            acc.append(x)
                        else:
                            texts(x, acc)
                elif isinstance(o, list):
                    for x in o:
                        texts(x, acc)
            def walk(o):
                if isinstance(o, dict):
                    if 'videoRenderer' in o:  # 구형 렌더러
                        v = o['videoRenderer']
                        try:
                            vid = v['videoId']
                            if vid not in seen:
                                seen.add(vid)
                                snip = ''
                                try:
                                    snip = ''.join(r.get('text', '') for r in v['descriptionSnippet']['runs'])
                                except Exception:
                                    pass
                                out.append({'id': vid,
                                            't': v['title']['runs'][0]['text'],
                                            'rel': (v.get('publishedTimeText') or {}).get('simpleText', ''),
                                            'views': (v.get('viewCountText') or {}).get('simpleText', ''),
                                            'snip': snip})
                        except Exception:
                            pass
                    if 'lockupViewModel' in o:  # 신형 렌더러(2025~)
                        v = o['lockupViewModel']
                        try:
                            vid = v.get('contentId')
                            if vid and len(vid) == 11 and vid not in seen:
                                seen.add(vid)
                                acc = []
                                texts(v.get('metadata') or {}, acc)
                                title = acc[0] if acc else ''
                                views = next((s for s in acc if '조회수' in s or 'view' in s.lower()), '')
                                rel = next((s for s in acc if s.endswith('전') or 'ago' in s), '')
                                out.append({'id': vid, 't': title, 'rel': rel, 'views': views, 'snip': ''})
                        except Exception:
                            pass
                    for x in o.values():
                        walk(x)
                elif isinstance(o, list):
                    for x in o:
                        walk(x)
            walk(data)
        except Exception as e:
            DEBUG.append('ytInitialData 파싱 실패: %r' % e)
    return out[:30]

def video_detail(vid):
    """watch 페이지 → (uploadDate, description, viewCount) — 차단 시 예외"""
    h = get('https://www.youtube.com/watch?v=' + vid)
    d = re.search(r'"uploadDate":"(\d{4}-\d{2}-\d{2})', h)
    ds = re.search(r'"shortDescription":"((?:[^"\\]|\\.)*)"', h)
    vc = re.search(r'"viewCount":"(\d+)"', h)
    def unesc(s):
        try:
            return json.loads('"' + s + '"')
        except Exception:
            return s.replace('\\n', '\n')
    if not (d or ds):
        raise RuntimeError('메타 없음(차단 추정)')
    return (d.group(1) if d else '', unesc(ds.group(1))[:1500] if ds else '',
            int(vc.group(1)) if vc else None)

def main():
    try:
        prev = json.load(open(OUT, encoding='utf-8'))
    except Exception:
        prev = {}
    videos = {v['id']: v for v in (prev.get('videos') or [])}
    names = {}
    try:
        sn = json.load(open('public/stocknotes.json', encoding='utf-8'))
        for g in sn['industries']:
            for s in g['stocks']:
                names[s['name']] = s['code']
    except Exception:
        pass
    try:
        pj = json.load(open('public/data/products.json', encoding='utf-8'))['map']
        for c, e in pj.items():
            nm = e.get('n') if isinstance(e, dict) else None
            if nm and len(nm) >= 3 and re.fullmatch(r'\d{6}', c):
                names.setdefault(nm, c)
    except Exception:
        pass
    def tag(hay):
        hit = {nm: cd for nm, cd in names.items() if nm in hay}
        # 다른 매칭 종목명의 부분 문자열이면 제외 (예: 'SK하이닉스' 매칭 시 '이닉스' 오탐 제거)
        keep = {nm: cd for nm, cd in hit.items()
                if not any(nm != nm2 and nm in nm2 for nm2 in hit)}
        return [[a, b] for a, b in sorted(keep.items())[:6]]

    blocked = False
    for chname, churl in CHANNELS:
        try:
            lst = list_videos(churl)
        except Exception as e:
            DEBUG.append('%s 목록 실패: %r' % (chname, e))
            continue
        new = 0
        for it in lst:
            vid = it['id']
            if vid in videos or new >= NEW_CAP:
                continue
            ent = {'id': vid, 'ch': chname, 't': it['t'], 'views': it['views']}
            if not blocked:
                try:
                    d, desc, vc = video_detail(vid)
                    ent.update({'d': d, 'desc': desc})
                    if vc:
                        ent['views'] = '조회수 {:,}회'.format(vc)
                    time.sleep(1.2)
                except Exception:
                    blocked = True
            if blocked or 'd' not in ent or not ent.get('d'):
                ent.update({'d': rel2date(it['rel']), 'desc': it['snip'], 'approx': True})
            ent['tags'] = tag(ent['t'] + '\n' + (ent.get('desc') or ''))
            videos[vid] = ent
            new += 1
        # 이전에 approx로 저장된 항목 업그레이드 시도
        up = 0
        if not blocked:
            for vid, v in list(videos.items()):
                if v.get('approx') and up < UPGRADE_CAP:
                    try:
                        d, desc, vc = video_detail(vid)
                        v.update({'d': d or v['d'], 'desc': desc or v['desc']})
                        if vc:
                            v['views'] = '조회수 {:,}회'.format(vc)
                        v.pop('approx', None)
                        v['tags'] = tag(v['t'] + '\n' + (v.get('desc') or ''))
                        up += 1
                        time.sleep(1.2)
                    except Exception:
                        blocked = True
                        break
        DEBUG.append('%s: 목록 %d, 신규 %d, 업그레이드 %d, 차단 %s' % (chname, len(lst), new, up, blocked))
    out_videos = sorted(videos.values(), key=lambda v: v.get('d') or '', reverse=True)[:MAX_KEEP]
    os.makedirs('public/data', exist_ok=True)
    json.dump({'updated': time.strftime('%Y-%m-%d %H:%M'), 'debug': DEBUG, 'videos': out_videos},
              open(OUT, 'w', encoding='utf-8'), ensure_ascii=False)
    print('완료:', DEBUG)

if __name__ == '__main__':
    main()
