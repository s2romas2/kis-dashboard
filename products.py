#!/usr/bin/env python3
# 상장법인 주요제품/업종 목록 (KRX KIND) + 11개 섹터 분류 → public/data/products.json
# map 형식: {종목코드: {"p": 주요제품, "s": 섹터명}}
import urllib.request, re, json, html, sys, time, os

URL = 'https://kind.krx.co.kr/corpgeneral/corpList.do?method=download&searchType=13'

def clean(s):
    return html.unescape(re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', '', s))).strip()

# 업종명(KSIC)+주요제품 키워드 → 11개 섹터. 순서 중요(먼저 매칭되는 규칙 우선)
SECTOR_RULES = [
    ('헬스케어', r'의약|제약|의료|바이오|병원|보건|진단|백신|임상'),
    ('유틸리티', r'전기업|가스 공급|수도사업|증기|냉온수|발전업|집단에너지|도시가스'),
    ('에너지', r'석유 정제|원유|연료용|석탄|코크스|주유소|LPG|석유류'),
    ('금융', r'은행|보험|증권|금융|투자 회사|여신|신탁|자산운용|캐피탈|지주회사|리스업'),
    ('부동산', r'부동산|리츠|주택 건설\b'),
    ('커뮤니케이션', r'전기 통신업|위성 통신|방송업|프로그램 공급|영화|게임|포털|인터넷 정보|광고|출판|엔터테인먼트|음반|공연|콘텐츠|만화|웹툰|드라마'),
    ('정보기술', r'반도체|전자부품|컴퓨터|소프트웨어|프로그래밍|시스템 통합|정보 서비스|통신 및 방송 장비|영상 및 음향|사무용 기계|측정.*기기|제어.*기기|광학|디스플레이|자료 처리|2차전지|이차전지|전지 제조|PCB|기판'),
    ('필수소비재', r'식료품|음료|담배|곡물|낙농|육류|수산|과실|채소|사료|화장품|비누|세제|위생용품|농업|어업|축산|제분|제당|라면|장류'),
    ('임의소비재', r'자동차|섬유|의복|봉제|가죽|신발|가방|가구|악기|완구|스포츠|교육|학원|여행|숙박|음식점|카지노|레저|소매업|백화점|면세|홈쇼핑|타이어|모터사이클|패션|침구'),
    ('산업재', r'건설|건축|토목|기계|장비 제조|조선|선박|항공|철도|운송|물류|창고|택배|해운|엔진|터빈|방위|무기|전동기|전기장비|배전|전선|금속 가공|구조용 금속|경비|시설관리|종합상사|무역|플랜트|중공업|크레인|베어링|밸브|펌프'),
    ('소재', r'화학|철강|제철|1차 금속|비금속|시멘트|콘크리트|유리|제지|펄프|종이|고무|플라스틱|광업|합금|도금|염료|안료|비료|농약|잉크|페인트|알루미늄|동제련'),
]

def classify(ind, prod):
    t = (ind or '') + ' ' + (prod or '')
    for name, pat in SECTOR_RULES:
        if re.search(pat, t):
            return name
    return '기타'

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
        ind, prod = cells[3], cells[4][:90]
        mk = cells[1].replace(' ', '')
        entry = {'s': classify(ind, prod), 'n': cells[0][:40],
                 'm': 'K' if '유가' in mk else ('Q' if '코스닥' in mk else 'N')}
        if prod and prod != '-':
            entry['p'] = prod
        m[cells[2]] = entry

# 대시보드 KTOP10(108종목)은 수동 분류를 우선 적용
try:
    kt = json.load(open('public/ktop10.json', encoding='utf-8'))
    SEC_KO = {'XLK': '정보기술', 'XLC': '커뮤니케이션', 'XLF': '금융', 'XLV': '헬스케어',
              'XLY': '임의소비재', 'XLP': '필수소비재', 'XLI': '산업재', 'XLB': '소재',
              'XLE': '에너지', 'XLU': '유틸리티', 'XLRE': '부동산'}
    for t, items in kt['stocks'].items():
        for x in items:
            code = x[0]
            m.setdefault(code, {})['s'] = SEC_KO.get(t, '기타')
            if len(x) > 2 and 'p' not in m[code]:
                m[code]['p'] = x[2]
except Exception as e:
    print('ktop10 오버라이드 실패:', e, file=sys.stderr)

cnt = {}
for v in m.values():
    cnt[v['s']] = cnt.get(v['s'], 0) + 1
print('섹터 분포:', json.dumps(cnt, ensure_ascii=False), file=sys.stderr)

out = {'updated': time.strftime('%Y-%m-%d %H:%M'), 'count': len(m), 'sectors': cnt, 'map': m}
if not m:
    out['error'] = 'KIND 수집 실패'
os.makedirs('public/data', exist_ok=True)
with open('public/data/products.json', 'w', encoding='utf-8') as f:
    json.dump(out, f, ensure_ascii=False)
print('주요제품·섹터 %d개' % len(m))
