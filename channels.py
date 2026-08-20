#!/usr/bin/env python3
# 채널별 검색량·순위 수집 — 올리브영(글로벌/한국)·아마존(US/UK)·네이버·화해·글로우픽
# 각 채널 실패 시 이전 데이터 유지(부분 병합). 원격 로그 접근 불가 → debug 필드에 기록.
import json, re, time, html, urllib.request, urllib.parse

OUT = 'public/data/channels.json'
UA = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36'}
DEBUG = []

def get(url, headers=None, timeout=25):
    h = dict(UA)
    if headers:
        h.update(headers)
    return urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=timeout).read()

def prev():
    try:
        return json.load(open(OUT, encoding='utf-8'))
    except Exception:
        return {}

BRANDMAP = json.load(open('public/brandmap.json', encoding='utf-8'))
BK = json.load(open('public/beautykeys.json', encoding='utf-8'))

# 영문 브랜드명 → 한글 (아마존/올리브영 글로벌 브랜드 인식용)
EN2KR = {'cosrx': '코스알엑스', 'anua': '아누아', 'beauty of joseon': '조선미녀', 'medicube': '메디큐브',
         'tirtir': '티르티르', 'skin1004': '스킨1004', 'round lab': '라운드랩', 'torriden': '토리든',
         'biodance': '바이오던스', 'laneige': '라네즈', 'innisfree': '이니스프리', 'missha': '미샤',
         "d'alba": '달바', 'dalba': '달바', 'goodal': '구달', 'clio': '클리오', 'peripera': '페리페라',
         'rom&nd': '롬앤', 'romand': '롬앤', 'isntree': '이즈앤트리', 'abib': '아비브',
         'medipeel': '메디필', 'mediheal': '메디힐', 'numbuzin': '넘버즈인', 'sulwhasoo': '설화수',
         'ma:nyo': '마녀공장', 'manyo': '마녀공장', 'aestura': '에스트라', 'illiyoon': '일리윤',
         'aromatica': '아로마티카', 'kundal': '쿤달', 'vt cosmetics': 'VT', 'tonymoly': '토니모리',
         'the face shop': '더페이스샵', 'belif': '빌리프', 'wakemake': '웨이크메이크', 'dr.g': '닥터지',
         'hera': '헤라', 'espoir': '에스쁘아', 'etude': '에뛰드', 'dasique': '데이지크', 'unove': '어노브'}
# beautykeys의 us명도 흡수
for big in BK.values():
    for mids in big.values():
        for b, v in mids.items():
            if v.get('us'):
                EN2KR.setdefault(v['us'].lower(), b)

def kr_brand(name_en):
    if not name_en:
        return None
    return EN2KR.get(name_en.strip().lower())

def corp_of(brand_kr):
    return BRANDMAP.get(brand_kr) if brand_kr else None

CAT_RULES = [
    ('선케어', ['선크림', '선스틱', '선쿠션', '선세럼', 'sunscreen', 'sun stick', 'sun cream', 'uv ', 'spf']),
    ('마스크/팩', ['마스크', '팩', '패치', 'mask', 'patch', 'peel']),
    ('클렌징', ['클렌징', '클렌저', '폼', 'cleanser', 'cleansing', 'foam']),
    ('에센스/세럼', ['세럼', '앰플', '에센스', 'serum', 'ampoule', 'essence']),
    ('스킨/토너', ['토너', '스킨', '패드', 'toner', 'pad']),
    ('크림/로션', ['크림', '로션', '수분', 'moisturizer', 'cream', 'lotion', 'gel']),
    ('립메이크업', ['립', '틴트', 'lip', 'tint']),
    ('베이스메이크업', ['쿠션', '파운데이션', '컨실러', '파우더', 'cushion', 'foundation', 'concealer']),
    ('아이메이크업', ['아이', '브로우', '마스카라', '섀도우', 'eye', 'brow', 'mascara', 'shadow', 'liner']),
    ('헤어', ['샴푸', '트리트먼트', '헤어', '두피', 'shampoo', 'hair', 'scalp']),
    ('바디', ['바디', '핸드', '풋', 'body', 'hand cream']),
    ('향수', ['퍼퓸', '향수', 'perfume', 'fragrance']),
]

def guess_cat(name):
    low = (name or '').lower()
    for cat, kws in CAT_RULES:
        if any(k in low for k in kws):
            return cat
    return '기타'

def item(name, brand=None, cat=None, extra=None):
    it = {'n': name}
    if brand:
        it['b'] = brand
    it['c'] = cat or guess_cat(name)
    corp = corp_of(brand)
    if corp:
        it['corp'] = corp
    if extra:
        it['x'] = extra
    return it

CH = {}

# ---- 1) 올리브영 글로벌 (베스트셀러 100) ----
def oy_global():
    raw = get('https://global.oliveyoung.com/display/product/best-seller/order-best?dispCatNo=&isGlobal=true&showSoldoutProduct=true',
              headers={'Accept': 'application/json', 'Referer': 'https://global.oliveyoung.com/display/page/best-seller'})
    d = json.loads(raw.decode('utf-8'))
    items = []
    for p in d[:50]:
        bkr = p.get('korBrandName') or kr_brand(p.get('brandName'))
        nm = p.get('korPrdtName') or p.get('prdtName') or ''
        nm = re.sub(r'\s*\((OY단독|OY-Exclusive)[^)]*\)\s*', '', nm)
        try:
            rv = int(p.get('reviewCnt') or 0)
        except Exception:
            rv = 0
        items.append(item(nm, bkr, extra=('리뷰 {:,}'.format(rv) if rv else None)))
    return {'name': '올리브영 글로벌', 'status': 'ok',
            'note': '올리브영 글로벌몰(해외 배송) 판매 베스트셀러 순위 — 해외 소비자의 실제 구매 순위입니다.',
            'groups': [{'t': '베스트셀러 TOP 50', 'items': items}]}

# ---- 2) 올리브영 한국 ----
def oy_kr():
    raw = get('https://www.oliveyoung.co.kr/store/main/getBestList.do?dispCatNo=900000100100001&fltDispCatNo=&pageIdx=1&rowsPerPage=25',
              headers={'Referer': 'https://www.oliveyoung.co.kr/store/main/main.do'})
    h = raw.decode('utf-8', 'ignore')
    if 'Access Denied' in h or len(h) < 3000:
        raise RuntimeError('차단 응답')
    prods = re.findall(r'<span class="tx_brand">([^<]+)</span>\s*<p class="tx_name">([^<]+)</p>', h)
    if not prods:
        prods = re.findall(r'class="tx_brand">([^<]+)<[\s\S]{0,200}?class="tx_name">([^<]+)<', h)
    if not prods:
        raise RuntimeError('파싱 0건 (구조 변경 또는 차단, %d바이트)' % len(h))
    items = [item(html.unescape(n).strip(), html.unescape(b).strip()) for b, n in prods[:30]]
    return {'name': '올리브영 한국', 'status': 'ok',
            'note': '올리브영 국내몰 판매 랭킹입니다.', 'groups': [{'t': '판매 랭킹 TOP 30', 'items': items}]}

# ---- 3·4) 아마존 US/UK 자동완성 ----
AMZ_SEEDS = ['korean skincare', 'k-beauty', 'snail mucin', 'sunscreen', 'serum', 'toner',
             'moisturizer', 'cleanser', 'sheet mask', 'lip tint']

def amazon_us_brands():
    """추적 뷰티 브랜드별 아마존 미국 자동완성 — 브랜드에 대해 미국 소비자가 실제 검색하는 키워드"""
    keys = json.load(open('public/beautykeys.json', encoding='utf-8'))
    try:
        gtus = (json.load(open('public/data/beauty.json', encoding='utf-8')).get('gt') or {}).get('US') or {}
    except Exception:
        gtus = {}
    def interest(usname):
        s = gtus.get(usname)
        if not s:
            return -1
        seg = s[-4:]
        return sum(v for _, v in seg) / max(1, len(seg))
    brands, seen = [], set()
    for big, mids in keys.items():
        for mid, bs in mids.items():
            for b, v in bs.items():
                if v.get('us') and b not in seen:
                    seen.add(b)
                    brands.append((b, v['us'], big))
    groups = {}
    ok = 0
    for b, us, big in brands:
        try:
            u = ('https://completion.amazon.com/api/2017/suggestions?limit=6&prefix=%s'
                 '&suggestion-type=KEYWORD&alias=aps&site-variant=desktop&version=3'
                 '&event=onKeyPress&wc=&lop=en_US&mid=ATVPDKIKX0DER&plain-mid=1&client-info=amazon-search-ui'
                 % urllib.parse.quote(us.lower()))
            d = json.loads(get(u, timeout=15).decode('utf-8'))
            sugs = [s.get('value') for s in d.get('suggestions', []) if s.get('value')][:5]
        except Exception:
            sugs = []
        time.sleep(0.45)
        if not sugs:
            continue
        it = {'n': b, 'c': big, 'x': ' · '.join(sugs)}
        corp = corp_of(b)
        if corp:
            it['corp'] = corp
        groups.setdefault(big, []).append((interest(us), it))
        ok += 1
    if ok < 5:
        raise RuntimeError('브랜드 자동완성 %d개뿐' % ok)
    gs = []
    for big in ['화장품', '뷰티디바이스·시술']:
        arr = groups.get(big)
        if arr:
            arr.sort(key=lambda x: -x[0])
            gs.append({'t': '%s — 브랜드별 인기 검색어 (미국 구글 관심도 순)' % big, 'items': [a[1] for a in arr]})
    return {'name': '아마존 USA', 'status': 'ok',
            'note': '<b>추적 뷰티 브랜드별</b> 아마존 미국 검색창 자동완성입니다 — 각 줄의 회색 검색어가 그 브랜드에 대해 미국 소비자가 실제로 입력하는 검색어 순위(왼쪽이 1순위). 브랜드 정렬은 구글트렌드 미국 관심도 순.',
            'groups': gs}

def amazon(dom, mid, lop):
    groups = []
    for seed in AMZ_SEEDS:
        try:
            u = ('https://completion.%s/api/2017/suggestions?limit=10&prefix=%s&suggestion-type=KEYWORD&alias=aps'
                 '&site-variant=desktop&version=3&event=onKeyPress&wc=&lop=%s&mid=%s&plain-mid=1&client-info=amazon-search-ui'
                 % (dom, urllib.parse.quote(seed), lop, mid))
            d = json.loads(get(u, timeout=15).decode('utf-8'))
            sugs = [s.get('value') for s in d.get('suggestions', []) if s.get('value')]
            if sugs:
                items = []
                for s in sugs:
                    bkr = next((EN2KR[e] for e in EN2KR if e in s.lower()), None)
                    items.append(item(s, bkr))
                groups.append({'t': '"%s" 연관 검색어' % seed, 'items': items})
        except Exception:
            pass
        time.sleep(0.5)
    if not groups:
        raise RuntimeError('전체 시드 응답 없음')
    return groups

def amazon_us():
    return amazon_us_brands()  # 뷰티 브랜드별 검색어 (사용자 요청으로 일반 시드 방식에서 교체)

def amazon_uk():
    g = amazon('amazon.co.uk', 'A1F83G8C2ARO7P', 'en_GB')
    return {'name': '아마존 UK', 'status': 'ok',
            'note': '아마존 영국 검색창 자동완성 순위 = 영국 소비자의 실제 검색 수요 순서입니다.',
            'groups': g}

# ---- 8) 네이버 자동완성 ----
NV_SEEDS = ['선크림', '토너', '앰플', '세럼', '쿠션', '립틴트', '샴푸', '클렌징폼', '마스크팩', '수분크림']

def naver():
    groups = []
    kr_brands = set(BRANDMAP.keys())
    for big in BK.values():
        for mids in big.values():
            kr_brands.update(mids.keys())
    for seed in NV_SEEDS:
        try:
            u = ('https://ac.search.naver.com/nx/ac?q=%s&con=1&frm=nv&ans=2&r_format=json&r_enc=UTF-8'
                 '&r_unicode=0&t_koreng=1&run=2&rev=4&q_enc=UTF-8&st=100' % urllib.parse.quote(seed))
            d = json.loads(get(u, timeout=15).decode('utf-8'))
            sugs = [x[0] for arr in d.get('items', []) for x in arr if x and x[0] != seed]
            if sugs:
                items = []
                for s in sugs[:10]:
                    bkr = next((b for b in kr_brands if b in s), None)
                    items.append(item(s, bkr, cat=guess_cat(seed)))
                groups.append({'t': '"%s" 연관 검색어' % seed, 'items': items})
        except Exception:
            pass
        time.sleep(0.4)
    if not groups:
        raise RuntimeError('전체 시드 응답 없음')
    return {'name': '네이버', 'status': 'ok',
            'note': '네이버 검색창 자동완성 순위 = 국내 소비자의 실제 검색 수요 순서입니다(공식 검색량 API는 종료되어 자동완성 순위로 대체).',
            'groups': groups}

# ---- 9a) 화해 급상승 랭킹 ----
def hwahae():
    h = get('https://www.hwahae.co.kr/rankings').decode('utf-8', 'ignore')
    items = []
    for m in re.findall(r'<script type="application/ld\+json">([\s\S]*?)</script>', h):
        try:
            d = json.loads(m)
        except Exception:
            continue
        if d.get('@type') == 'ItemList':
            for it in d.get('itemListElement', []):
                b = (it.get('brand') or {}).get('name')
                items.append(item(it.get('name', ''), b))
    if not items:
        raise RuntimeError('ItemList 없음')
    return {'name': '화해', 'status': 'ok',
            'note': '화해 앱 급상승 제품 랭킹 — 국내 사용자 관심이 빠르게 오르는 제품입니다.',
            'groups': [{'t': '급상승 제품 TOP %d' % len(items), 'items': items}]}

# ---- 9b) 글로우픽 카테고리별 1~5위 ----
GP_CATS = [(1, '스킨/토너'), (3, '에센스/세럼'), (4, '크림'), (41, '선크림'), (32, '페이셜클렌저'),
           (37, '시트마스크'), (7, '파운데이션'), (15, '립틴트/라커'), (23, '마스카라'), (60, '샴푸')]

def glowpick():
    groups = []
    err1 = None
    for cid, cname in GP_CATS:
        for attempt in range(2):
            try:
                h = get('https://www.glowpick.com/categories/%d' % cid, timeout=20).decode('utf-8', 'ignore')
                break
            except Exception as e:
                err1 = err1 or str(e)[:60]
                h = None
                time.sleep(3)
        if not h:
            continue
        try:
            items = []
            for m in re.findall(r'<script type="application/ld\+json">([\s\S]*?)</script>', h):
                try:
                    d = json.loads(m)
                except Exception:
                    continue
                if d.get('@type') == 'ItemList':
                    for it in d.get('itemListElement', [])[:5]:
                        nm = (it.get('item') or {}).get('name', '')
                        mm = re.match(r'\d+위\s*(.+?)\s*\|\s*(.+)', nm)
                        if mm:
                            items.append(item(mm.group(2).strip(), mm.group(1).strip(), cat=cname))
            if items:
                groups.append({'t': cname + ' TOP %d' % len(items), 'items': items})
        except Exception as e:
            err1 = err1 or str(e)[:60]
        time.sleep(1.2)
    if not groups:
        raise RuntimeError('전체 카테고리 응답 없음 (첫 오류: %s)' % err1)
    return {'name': '글로우픽', 'status': 'ok',
            'note': '글로우픽 소비자 평가 기반 카테고리별 랭킹입니다.', 'groups': groups}

def run(key, fn):
    try:
        CH[key] = fn()
        DEBUG.append('%s OK (%d그룹)' % (key, len(CH[key].get('groups', []))))
    except Exception as e:
        DEBUG.append('%s 실패: %s' % (key, str(e)[:80]))
        pv = (prev().get('channels') or {}).get(key)
        if pv and pv.get('manual'):
            CH[key] = pv  # 수동(브라우저) 수집 데이터는 stale 표시 없이 유지
        elif pv and pv.get('status') == 'ok':
            CH[key] = pv
            CH[key]['stale'] = True
        else:
            CH[key] = {'name': key, 'status': 'fail', 'err': str(e)[:120]}

def main():
    run('oy_global', oy_global)
    run('oy_kr', oy_kr)
    run('amazon_us', amazon_us)
    run('amazon_uk', amazon_uk)
    run('naver', naver)
    run('hwahae', hwahae)
    run('glowpick', glowpick)
    # 수집 목록에 없는 수동(브라우저) 채널은 보존 — 예: tiktok_us(크리에이티브 센터)
    for k, v in (prev().get('channels') or {}).items():
        if k not in CH and isinstance(v, dict) and v.get('manual'):
            CH[k] = v
    out = {'updated': time.strftime('%Y-%m-%d %H:%M'), 'debug': DEBUG, 'channels': CH}
    json.dump(out, open(OUT, 'w', encoding='utf-8'), ensure_ascii=False)
    print('완료:', DEBUG)

if __name__ == '__main__':
    main()
