#!/usr/bin/env python3
# 상장법인 주요제품/서비스 목록 (KRX KIND) → public/data/products.json
import urllib.request, re, json, html, sys, time

URL = 'https://kind.krx.co.kr/corpgeneral/corpList.do?method=download&searchType=13'

def clean(s):
    return html.unescape(re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', '', s))).strip()

h = ''
try:
    req = urllib.request.Request(URL, headers={'User-Agent': 'Mozilla/5.0'})
    h = urllib.request.urlopen(req, timeout=90).read().decode('euc-kr', 'ignore')
except Exception as e:
    print('KIND 다운로드 실패:', repr(e), file=sys.stderr)

m = {}
# 열 구조: [회사명, 시장구분, 종목코드, 업종, 주요제품, 상장일, 결산월, 대표자명, 홈페이지, 지역]
for row in re.findall(r'<tr[^>]*>(.*?)</tr>', h, re.S | re.I):
    cells = [clean(c) for c in re.findall(r'<td[^>]*>(.*?)</td>', row, re.S | re.I)]
    if len(cells) >= 5 and re.fullmatch(r'[0-9A-Z]{6}', cells[2] or ''):
        prod = cells[4][:90]
        if prod and prod != '-':
            m[cells[2]] = prod

out = {'updated': time.strftime('%Y-%m-%d %H:%M'), 'count': len(m), 'map': m}
if not m:
    out['error'] = 'KIND 표 파싱 실패'
    i = h.lower().find('<tr')
    out['debug'] = {'bytes': len(h), 'tr_count': len(re.findall(r'<tr', h, re.I)),
                    'sample': re.sub(r'\s+', ' ', h[i:i + 1500]) if i >= 0 else h[:400]}
import os
os.makedirs('public/data', exist_ok=True)
with open('public/data/products.json', 'w', encoding='utf-8') as f:
    json.dump(out, f, ensure_ascii=False)
print('주요제품 %d개' % len(m))
