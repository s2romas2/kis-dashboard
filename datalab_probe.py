#!/usr/bin/env python3
# 네이버 데이터랩 웹 요청 형식 진단 (공식 API 종료 대응)
# trendSearch 페이지와 JS 번들에서 qcHash 요청 파라미터 구성을 추출해 커밋
import json, re, time, urllib.request, urllib.parse

OUT = 'public/data/datalab_probe.json'
UA = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36'}
R = {'steps': []}

def fetch(url, headers=None, data=None):
    req = urllib.request.Request(url, data=data, headers=dict(UA, **(headers or {})))
    return urllib.request.urlopen(req, timeout=30).read().decode('utf-8', 'ignore')

try:
    h = fetch('https://datalab.naver.com/keyword/trendSearch.naver')
    R['steps'].append('페이지 %d바이트' % len(h))
    scripts = re.findall(r'<script[^>]+src="([^"]+)"', h)
    R['scripts'] = scripts
    # 히든 인풋 전부
    R['hidden'] = re.findall(r'<input type="hidden"[^>]*id="([^"]+)"[^>]*value="([^"]*)"', h)
    # 인라인 스크립트에서 qcHash 주변
    R['inline_qc'] = [m[:400] for m in re.findall(r'[^\n]{0,200}qcHash[^\n]{0,200}', h)]
    # JS 번들에서 qcHash/queryGroups 주변 추출
    R['js_qc'] = []
    for s in scripts[:8]:
        u = s if s.startswith('http') else ('https://datalab.naver.com' + s)
        try:
            js = fetch(u)
            for pat in ('qcHash', 'queryGroups', 'trendSearch'):
                for m in re.findall(r'.{0,250}' + pat + r'.{0,250}', js)[:4]:
                    R['js_qc'].append({'src': u.split('/')[-1][:40], 'pat': pat, 'ctx': m})
        except Exception as e:
            R['js_qc'].append({'src': u[:60], 'err': repr(e)})
        time.sleep(0.5)
except Exception as e:
    R['steps'].append('실패: %r' % e)

R['updated'] = time.strftime('%Y-%m-%d %H:%M')
with open(OUT, 'w', encoding='utf-8') as f:
    json.dump(R, f, ensure_ascii=False)
print('완료', R['steps'])
