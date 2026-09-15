#!/usr/bin/env python3
# 딥다이브 대상(qdeep_targets.json) 확장 — 대시보드의 다른 맵에 있는 종목을 자동 합류
#   소스: semidetail.json co(소부장 세부분야) · semimap.json(8대공정 맵, 있으면) · valalert.py TARGETS(밸류 알림 4종목)
#   실행: python tools/qdeep_expand.py  (저장소 루트에서) → qdeep_targets.json 갱신(기존 항목·순서 유지, 신규는 뒤에 추가)
import json, re, os, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)

def load(p):
    try: return json.load(open(p, encoding='utf-8'))
    except Exception: return None

cur = load('qdeep_targets.json') or []
have = {x['code'] for x in cur}
names = (load('public/data/products.json') or {}).get('map') or {}
add = {}

def put(code, name=''):
    code = str(code).strip()
    if not re.fullmatch(r'[0-9A-Z]{6}', code) or code in have or code in add: return
    nm = name or (names.get(code) or {}).get('n') if isinstance(names.get(code), dict) else (name or '')
    add[code] = nm or code

sd = load('public/data/semidetail.json') or {}
for c, v in (sd.get('co') or {}).items(): put(c, (v or {}).get('n', ''))
for f in (sd.get('fields') or []):
    for r in (f.get('rank') or []): put(r.get('c', ''), r.get('n', ''))
sm = load('public/data/semimap.json') or {}
for k in ('co', 'companies', 'map', 'stocks'):
    v = sm.get(k)
    if isinstance(v, dict):
        for c, x in v.items(): put(c, (x or {}).get('n', '') if isinstance(x, dict) else '')
    elif isinstance(v, list):
        for x in v:
            if isinstance(x, dict): put(x.get('c') or x.get('code') or '', x.get('n') or x.get('name') or '')
for c, n in [('278470', '에이피알'), ('086450', '동국제약'), ('0015N0', '아로마티카'), ('251970', '펌텍코리아')]: put(c, n)
# 광통신 맵(optics.html 한국 종목) — RF머트리얼즈·대한광통신·옵티코어·오이솔루션·빛과전자·이수페타시스·한국첨단소재·우리로·티에프이·LS에코에너지·
#   성호전자·대덕전자·삼성전기·레이저쎌·코위버·텔레필드·HFR·다산네트웍스·이노인스트루먼트
for c in ['327260', '010170', '380540', '138080', '069540', '007660', '062970', '046970', '425420', '229640',
          '043260', '353200', '009150', '412350', '056360', '091440', '230240', '039560', '215790']: put(c)
# 화장품·뷰티 — products.json 품목 설명에서 키워드 매칭(브랜드·ODM·용기·원료·미용기기)
COS = re.compile(r'화장품|뷰티|코스메|스킨케어|색조|더마|미용|기초화장|메이크업|선케어|헤어케어|향수')
for c, v in names.items():
    if isinstance(v, dict) and re.fullmatch(r'[0-9A-Z]{6}', c) and v.get('m') != 'N' and COS.search((v.get('p') or '') + ' ' + (v.get('n') or '')):
        put(c, v.get('n', ''))

for c, n in add.items(): cur.append({'code': c, 'name': n})
json.dump(cur, open('qdeep_targets.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
print('기존 %d + 신규 %d = %d' % (len(have), len(add), len(cur)))
print('신규:', ', '.join('%s %s' % (c, n) for c, n in list(add.items())[:60]))
