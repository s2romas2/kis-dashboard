#!/usr/bin/env python3
# 섹터 흐름 맵 — 섹터별 글로벌 뉴스 피드 (구글뉴스 RSS, 국·영문) → public/data/sectornews.json
import json, time, re, urllib.request, urllib.parse, ssl
import xml.etree.ElementTree as ET

OUT = 'public/data/sectornews.json'
UA = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/126'}
CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE

Q = {
 'semi': [('en', 'HBM memory supply shortage'), ('en', 'transformer lead time power grid AI'),
          ('en', 'AI data center electricity backlash'), ('en', 'DRAM price increase'),
          ('ko', 'HBM 수주 OR 증설'), ('ko', '변압기 수주 미국'), ('ko', '데이터센터 전력')],
 'beauty': [('en', 'K-beauty US market share'), ('en', 'Korean cosmetics exports'),
            ('ko', '화장품 수출 미국'), ('ko', 'K뷰티 아마존 OR 세포라 OR 울타')],
 'food': [('en', 'Korean food exports ramen'), ('en', 'Samyang buldak OR Nongshim US'),
          ('ko', '라면 수출'), ('ko', 'K푸드 미국 OR 유럽')],
 'ship': [('en', 'shipbuilding orders LNG carrier Korea China'), ('en', 'USTR port fee Chinese ships'),
          ('ko', '조선 수주 LNG선'), ('ko', '신조선가 OR 수주잔량')],
 'def': [('en', 'South Korea defense exports contract'), ('en', 'Hanwha OR KAI defense deal'),
         ('ko', '방산 수출 수주'), ('ko', 'K방산 폴란드 OR 중동 OR 캐나다')],
 'optics': [('en', '448G SerDes'), ('en', 'ConnectX-10 OR "3.2T" NIC scale-out bandwidth'),
            ('en', 'co-packaged optics CPO switch NVIDIA OR Broadcom'), ('en', '1.6T optical transceiver ramp'),
            ('en', 'EML laser shortage InP'), ('ko', '광트랜시버 OR CPO 수주'), ('ko', '광통신 데이터센터')],
}

def rss(lang, query):
    if lang == 'ko':
        u = 'https://news.google.com/rss/search?q=%s&hl=ko&gl=KR&ceid=KR:ko' % urllib.parse.quote(query)
    else:
        u = 'https://news.google.com/rss/search?q=%s&hl=en-US&gl=US&ceid=US:en' % urllib.parse.quote(query)
    try:
        x = urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=30, context=CTX).read()
        root = ET.fromstring(x.decode('utf-8', 'ignore'))
        out = []
        for it in list(root.iter('item'))[:8]:
            t = (it.findtext('title') or '').strip()
            lk = (it.findtext('link') or '').strip()
            pd = (it.findtext('pubDate') or '')
            src = ''
            se = it.find('{https://news.google.com/rss}source')
            if se is None:
                se = it.find('source')
            if se is not None:
                src = (se.text or '').strip()
            # pubDate → YYYY-MM-DD
            try:
                d = time.strftime('%Y-%m-%d', time.strptime(pd[5:16], '%d %b %Y'))
            except Exception:
                d = ''
            if t and lk:
                out.append({'d': d, 't': t[:150], 'u': lk, 's': src, 'l': lang})
        return out
    except Exception:
        return []

def main():
    prev = {}
    try:
        prev = json.load(open(OUT, encoding='utf-8'))
    except Exception:
        pass
    sec = {}
    for k, queries in Q.items():
        items = []
        seen = set()
        for lang, q in queries:
            for it in rss(lang, q):
                key = re.sub(r'\W+', '', it['t'])[:60]
                if key in seen:
                    continue
                seen.add(key)
                items.append(it)
            time.sleep(0.5)
        items.sort(key=lambda x: x['d'], reverse=True)
        if items:
            sec[k] = items[:16]
        elif prev.get('sec', {}).get(k):
            sec[k] = prev['sec'][k]  # 실패 시 이전 유지
    out = {'updated': time.strftime('%Y-%m-%d %H:%M'), 'sec': sec}
    json.dump(out, open(OUT, 'w', encoding='utf-8'), ensure_ascii=False)
    print('완료:', {k: len(v) for k, v in sec.items()})

if __name__ == '__main__':
    main()
