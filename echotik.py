#!/usr/bin/env python3
# 틱톡샵(미국) 실판매 랭킹 수집 — EchoTik 공개 API (비로그인 한도: 전체 TOP 20)
# - 일간·주간 TOP 20 → 뷰티 필터 + 한국 브랜드 감지 + 한국 브랜드 일별 히스토리 누적
# 결과: public/data/tiktokshop.json
import json, time, urllib.request, gzip, os, re, datetime

OUT = 'public/data/tiktokshop.json'
UA = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126 Safari/537.36',
      'Accept': 'application/json', 'Referer': 'https://echotik.live/products/leaderboard/top-sold',
      'Accept-Encoding': 'gzip'}
BASE = 'https://echotik.live/api/v1/data/products/leaderboard/top-sold?region=US&per_page=20&page=1&period_type='
DEBUG = []

KR_BRANDS = {  # 소문자 매칭 → (표기, 기업)
    'medicube': ('메디큐브', '에이피알(278470)'),
    'biodance': ('바이오댄스', '비상장'),
    'melaxin': ('닥터멜락신', '비상장'),
    'anua': ('아누아', '더파운더즈(비상장)'),
    'tirtir': ('티르티르', '구다이글로벌(비상장)'),
    'skin1004': ('스킨1004', '구다이글로벌 산하 크레이버(비상장)'),
    'cosrx': ('코스알엑스', '아모레퍼시픽(090430) 자회사'),
    'beauty of joseon': ('조선미녀', '구다이글로벌(비상장)'),
    'mixsoon': ('믹순', '비상장'),
    'torriden': ('토리든', '비상장'),
    'round lab': ('라운드랩', '구다이글로벌 산하 서린컴퍼니(비상장)'),
    'roundlab': ('라운드랩', '구다이글로벌 산하 서린컴퍼니(비상장)'),
    'laneige': ('라네즈', '아모레퍼시픽(090430)'),
    'innisfree': ('이니스프리', '아모레퍼시픽(090430)'),
    'mediheal': ('메디힐', '엘앤피코스메틱(비상장)'),
    'abib': ('아비브', '비상장'),
    'numbuzin': ('넘버즈인', '비상장'),
    'goodal': ('구달', '클리오(237880)'),
    'clio': ('클리오', '클리오(237880)'),
    'rom&nd': ('롬앤', '아이패밀리에스씨(114840)'),
    'romand': ('롬앤', '아이패밀리에스씨(114840)'),
    'peripera': ('페리페라', '클리오(237880)'),
    'sulwhasoo': ('설화수', '아모레퍼시픽(090430)'),
    'd\'alba': ('달바', '달바글로벌(483650)'),
    'dalba': ('달바', '달바글로벌(483650)'),
    'ma:nyo': ('마녀공장', '마녀공장(439090)'),
    'manyo': ('마녀공장', '마녀공장(439090)'),
    'vt cosmetics': ('브이티', '브이티(018290)'),
    'isntree': ('이즈앤트리', '비상장'),
    'celimax': ('셀리맥스', '비상장'),
    'medipeel': ('메디필', '스킨이데아(비상장)'),
    'medi-peel': ('메디필', '스킨이데아(비상장)'),
}

def get(url):
    r = urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=25)
    b = r.read()
    try:
        t = gzip.decompress(b).decode('utf-8', 'ignore')
    except Exception:
        t = b.decode('utf-8', 'ignore')
    return json.loads(t)

def kr_match(name, seller):
    hay = (name + ' ' + seller).lower()
    for k, (br, corp) in KR_BRANDS.items():
        if k in hay:
            return br, corp
    if 'korean' in hay or 'korea' in hay:
        return '한국(브랜드 미매핑)', ''
    return None, None

def fnum(v):
    try:
        v = float(v)
    except Exception:
        return ''
    if v >= 1e6:
        return '%.1fM' % (v / 1e6)
    if v >= 1e3:
        return '%.1fK' % (v / 1e3)
    return '%d' % v

def snap(period):
    d = get(BASE + period)
    items = []
    for i, x in enumerate(d.get('data') or []):
        name = (x.get('product_name') or '')[:90]
        seller = (x.get('seller') or {}).get('seller_name', '') if isinstance(x.get('seller'), dict) else str(x.get('seller') or '')
        br, corp = kr_match(name, seller)
        items.append({
            'rk': i + 1, 'n': name, 'cat': x.get('category') or '',
            'price': x.get('avg_price') or x.get('real_price') or '',
            'sale': fnum(x.get('sale_cnt')), 'gmv': fnum(x.get('total_gmv_amt')),
            'cum': fnum(x.get('total_sale_cnt')), 'seller': seller[:30],
            'kr': bool(br), 'brand': br or '', 'corp': corp or ''})
    return items

def main():
    try:
        prev = json.load(open(OUT, encoding='utf-8'))
    except Exception:
        prev = {}
    out = {'hist': prev.get('hist') or []}
    ok = 0
    for period in ('daily', 'weekly'):
        try:
            out[period] = snap(period)
            ok += 1
            DEBUG.append('%s %d개 (뷰티 %d, 한국 %d)' % (period, len(out[period]),
                         sum(1 for x in out[period] if 'Beauty' in x['cat']),
                         sum(1 for x in out[period] if x['kr'])))
        except Exception as e:
            DEBUG.append('%s 실패: %s' % (period, str(e)[:80]))
            if prev.get(period):
                out[period] = prev[period]
                out[period + '_stale'] = True
        time.sleep(2)
    # 한국 브랜드 일별 히스토리 (일간 기준)
    today = datetime.date.today().isoformat()
    if out.get('daily') and not out.get('daily_stale'):
        krs = [{'rk': x['rk'], 'brand': x['brand'], 'n': x['n'][:50], 'gmv': x['gmv']}
               for x in out['daily'] if x['kr']]
        hist = [h for h in out['hist'] if h[0] != today]
        hist.append([today, krs])
        out['hist'] = sorted(hist)[-90:]
    if ok == 0 and not prev:
        raise SystemExit('전체 실패')
    out['updated'] = time.strftime('%Y-%m-%d %H:%M')
    out['debug'] = DEBUG
    os.makedirs('public/data', exist_ok=True)
    json.dump(out, open(OUT, 'w', encoding='utf-8'), ensure_ascii=False)
    print('완료:', DEBUG)

if __name__ == '__main__':
    main()
