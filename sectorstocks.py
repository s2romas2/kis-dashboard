#!/usr/bin/env python3
# 업종별 견인 종목 수집 — KIS 업종별 구성종목 시세
# 랭크테이블에서 섹터 클릭 시 그 업종을 견인하는 종목(등락률·시총)을 표시하기 위한 데이터.
# 업종 코드·이름은 leadershist.json(이미 leaders.py가 채움)에서 그대로 재사용 → 이름이 랭크테이블과 100% 일치.
# 필요 시크릿: KIS_APPKEY, KIS_APPSECRET
import os, sys, json, time, urllib.request, urllib.parse

APPKEY = os.environ.get('KIS_APPKEY', '')
APPSECRET = os.environ.get('KIS_APPSECRET', '')
BASE = 'https://openapi.koreainvestment.com:9443'
HIST = 'public/data/leadershist.json'   # 업종코드→이름/시장 소스
SCREENER = 'public/data/screener.json'  # 종목별 실적·YoY 성장률 소스
MAPFILE = 'public/data/sectormap.json'  # 종목→KRX업종 매핑 캐시(재수집 최소화)
OUT = 'public/data/sectorstocks.json'
TOPN = 15                                 # 업종당 저장할 최대 종목수(등락률 상위)
GROWN = 8                                 # 업종당 실적 성장주 최대 개수
MAP_TTL = 20 * 86400                      # 업종 매핑 캐시 유효기간(20일)
DEBUG = []
# search-stock-info(CTPF1002R) 업종명 후보 필드(소분류>중분류>대분류) — KRX 지수업종명과 매칭
IND_KEYS = ['idx_bztp_scls_cd_name', 'idx_bztp_mcls_cd_name', 'idx_bztp_lcls_cd_name', 'std_idst_clsf_cd_name']
MKT_KEYS = ['mket_id_cd', 'mrkt_id_cd', 'rprs_mrkt_kor_name', 'excg_dvsn_cd']


def post_json(url, body):
    req = urllib.request.Request(url, data=json.dumps(body).encode(),
                                 headers={'content-type': 'application/json'})
    return json.loads(urllib.request.urlopen(req, timeout=20).read().decode())


def get_json(url, headers):
    return json.loads(urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=20).read().decode())


def tonum(s):
    try:
        return float(str(s).replace(',', ''))
    except Exception:
        return None


def get_token():
    for attempt in range(4):
        try:
            tok = post_json(BASE + '/oauth2/tokenP',
                            {'grant_type': 'client_credentials', 'appkey': APPKEY, 'appsecret': APPSECRET})
            if tok.get('access_token'):
                return tok['access_token']
        except Exception as e:
            DEBUG.append('토큰 시도 %d: %s' % (attempt + 1, str(e)[:40]))
        time.sleep(65)
    return None


# 응답 필드명이 문서/버전마다 달라 방어적으로 후보를 훑는다.
CODE_KEYS = ['stck_shrn_iscd', 'mksc_shrn_iscd', 'shrn_iscd', 'stnd_iscd', 'iscd']
NAME_KEYS = ['hts_kor_isnm', 'kor_isnm', 'prdt_name', 'isnm']
CHG_KEYS = ['prdy_ctrt', 'prdy_ctrt_rate', 'ctrt']
PRC_KEYS = ['stck_prpr', 'prpr', 'stck_clpr']
CAP_KEYS = ['hts_avls', 'stck_avls', 'mrkt_val', 'avls', 'lstn_avls']
VAL_KEYS = ['acml_tr_pbmn', 'tr_pbmn', 'acml_tr_pbmn_amt']   # 누적 거래대금(원) — 없으면 vol*prc로 추정
VOL_KEYS = ['acml_vol', 'vol', 'acml_vol_qty']              # 누적 거래량(주)


def pick(d, keys):
    for k in keys:
        if k in d and d[k] not in ('', None):
            return d[k]
    return None


def category_stocks(hdr, code):
    """업종 등락률순위 → 그 업종에서 오른 순으로 종목 리스트 [{c,n,chg,prc,cap}].
    KIS 국내주식 등락률순위(FHPST01700000)를 업종코드로 스코프. 첫 성공 응답 키를 DEBUG에 1회 남김."""
    params = {
        'fid_cond_mrkt_div_code': 'J',
        'fid_cond_scr_div_code': '20170',
        'fid_input_iscd': code,            # 업종코드(0005 등)로 그 업종만
        'fid_rank_sort_cls_code': '0',     # 0=상승률순
        'fid_input_cnt_1': '0',
        'fid_prc_cls_code': '0',
        'fid_input_price_1': '1000',       # 최소 주가 1,000원(동전주 제외)
        'fid_input_price_2': '',
        'fid_vol_cnt': '30000',            # 최소 거래량 3만주(유동성 하한)
        'fid_trgt_cls_code': '0',
        'fid_trgt_exls_cls_code': '0',
        'fid_div_cls_code': '0',
        'fid_rsfl_rate1': '',
        'fid_rsfl_rate2': '',
    }
    u = BASE + '/uapi/domestic-stock/v1/ranking/fluctuation?' + urllib.parse.urlencode(params)
    h = dict(hdr); h['tr_id'] = 'FHPST01700000'
    j = get_json(u, h)
    if j.get('rt_cd') != '0':
        return None, (j.get('msg1', '') or '')[:40]
    rows = j.get('output') or j.get('output1') or j.get('output2') or []
    if rows and not category_stocks._logged:
        DEBUG.append('등락률순위 응답 키: ' + ','.join(list(rows[0].keys())[:24]))
        category_stocks._logged = True
    out = []
    for r in rows:
        c = pick(r, CODE_KEYS); n = pick(r, NAME_KEYS)
        if not c or not n:
            continue
        c = str(c).zfill(6)
        if not c.endswith('0'):            # 보통주만(우선주 코드 끝자리 5/7/9/K 제외)
            continue
        chg = tonum(pick(r, CHG_KEYS))
        prc = tonum(pick(r, PRC_KEYS))
        cap = tonum(pick(r, CAP_KEYS))
        val = tonum(pick(r, VAL_KEYS))     # 거래대금(원) — 미제공 시 거래량*현재가로 추정
        if val is None:
            vol = tonum(pick(r, VOL_KEYS))
            if vol is not None and prc is not None:
                val = vol * prc
        out.append({'c': c, 'n': str(n).strip(),
                    'chg': chg, 'prc': prc, 'cap': cap, 'val': val})
    return out, ''


category_stocks._logged = False


def _mkt_of(v):
    s = str(v or '')
    if 'KSQ' in s or '코스닥' in s or s == 'Q':
        return 'KOSDAQ'
    return 'KOSPI'


def stock_industry(hdr, code):
    """종목 기본정보 → {업종 후보명들, 시장}. 첫 성공 응답 키를 DEBUG에 1회 남김."""
    u = BASE + '/uapi/domestic-stock/v1/quotations/search-stock-info?PRDT_TYPE_CD=300&PDNO=' + code
    h = dict(hdr); h['tr_id'] = 'CTPF1002R'
    j = get_json(u, h)
    o = j.get('output') or {}
    if o and not stock_industry._logged:
        DEBUG.append('기본정보 응답 키: ' + ','.join(list(o.keys())[:30]))
        DEBUG.append('업종후보 예시(%s): ' % code + ' / '.join('%s=%s' % (k, o.get(k)) for k in IND_KEYS if o.get(k)))
        stock_industry._logged = True
    cands = [str(o.get(k)).strip() for k in IND_KEYS if o.get(k)]
    mkt = _mkt_of(next((o.get(k) for k in MKT_KEYS if o.get(k)), ''))
    return cands, mkt


stock_industry._logged = False


def build_sectormap(hdr, codes, krx_names):
    """screener 종목 code→(업종명, 시장) 매핑 생성. 여러 업종필드 후보 중 KRX명과 겹치는 게 가장 많은 걸 채택."""
    raw = {}  # code -> {cands:[...], mkt}
    for i, code in enumerate(codes):
        try:
            cands, mkt = stock_industry(hdr, code)
            raw[code] = {'cands': cands, 'mkt': mkt}
        except Exception as e:
            if len(DEBUG) < 20:
                DEBUG.append('info %s 오류 %s' % (code, str(e)[:24]))
        time.sleep(0.12)
    # 후보 슬롯(0=소분류…)별로 KRX명과 매칭되는 수를 세어 최적 슬롯 선택
    best_slot, best_hit = 0, -1
    for slot in range(len(IND_KEYS)):
        hit = sum(1 for v in raw.values() if len(v['cands']) > slot and v['cands'][slot] in krx_names)
        if hit > best_hit:
            best_hit, best_slot = hit, slot
    DEBUG.append('업종매핑: %d종목 조회, 슬롯%d 채택(매칭 %d)' % (len(raw), best_slot, best_hit))
    mp = {}
    for code, v in raw.items():
        sec = None
        # 최적 슬롯이 KRX명과 매칭되면 사용, 아니면 후보 중 KRX명에 있는 첫 값
        if len(v['cands']) > best_slot and v['cands'][best_slot] in krx_names:
            sec = v['cands'][best_slot]
        else:
            sec = next((c for c in v['cands'] if c in krx_names), None)
        if sec:
            mp[code] = {'sec': sec, 'mkt': v['mkt']}
    return {'v': 1, 'built': time.time(), 'map': mp}


def main():
    if not APPKEY or not APPSECRET:
        print('KIS 키 없음 — 건너뜀', file=sys.stderr); return
    try:
        hist = json.load(open(HIST, encoding='utf-8'))
    except Exception as e:
        raise RuntimeError('leadershist.json 필요(leaders.py 먼저 실행): %s' % e)
    codes = [(code, v.get('name'), v.get('mkt')) for code, v in hist['sectors'].items()
             if v.get('name') and v.get('mkt')]
    DEBUG.append('업종 %d개 대상' % len(codes))

    token = get_token()
    DEBUG.append('토큰: %s' % ('OK' if token else '실패'))
    if not token:
        raise RuntimeError('KIS 토큰 실패')
    hdr = {'content-type': 'application/json', 'authorization': 'Bearer ' + token,
           'appkey': APPKEY, 'appsecret': APPSECRET, 'custtype': 'P'}

    sectors, ok = {}, 0
    for code, name, mkt in codes:
        try:
            lst, msg = category_stocks(hdr, code)
        except Exception as e:
            if len(DEBUG) < 16:
                DEBUG.append('%s(%s) 오류 %s' % (code, name, str(e)[:30]))
            time.sleep(0.4); continue
        time.sleep(0.3)
        if not lst:
            if msg and len(DEBUG) < 16:
                DEBUG.append('%s(%s) 빈응답 %s' % (code, name, msg))
            continue
        # API가 이미 상승률순(견인 상위)으로 반환 → 그 순서 유지, 상위 TOPN 저장
        sectors['%s|%s' % (name, mkt)] = {
            'name': name, 'mkt': mkt, 'n': len(lst), 'top': lst[:TOPN]}
        ok += 1
    DEBUG.append('구성종목 확보 업종 %d개' % ok)

    # ---- 실적 성장주: screener 종목을 KRX업종에 매핑 후, 업종별 YoY 성장 상위 ----
    try:
        krx_names = set(name for _, name, _ in codes)
        screener = json.load(open(SCREENER, encoding='utf-8')).get('list', [])
        scodes = [x['code'] for x in screener if x.get('code')]
        # 업종 매핑 캐시 로드/재생성
        smap = None
        try:
            cache = json.load(open(MAPFILE, encoding='utf-8'))
            if cache.get('v') == 1 and (time.time() - cache.get('built', 0)) < MAP_TTL and cache.get('map'):
                smap = cache; DEBUG.append('업종매핑 캐시 사용(%d종목)' % len(cache['map']))
        except Exception:
            pass
        if smap is None:
            smap = build_sectormap(hdr, scodes, krx_names)
            json.dump(smap, open(MAPFILE, 'w', encoding='utf-8'), ensure_ascii=False)
        mp = smap['map']
        # 업종별 성장주 수집: rev>=300억 & opYoY 상위, 이미 견인 top에 있으면 제외
        by_sec = {}
        sd = {x['code']: x for x in screener}
        for code, m in mp.items():
            x = sd.get(code)
            if not x:
                continue
            if (x.get('rev') or 0) < 300:          # 매출 300억 미만 제외(미니캡 노이즈)
                continue
            key = '%s|%s' % (m['sec'], m['mkt'])
            by_sec.setdefault(key, []).append(x)
        grown = 0
        for key, lst in by_sec.items():
            if key not in sectors:
                sectors[key] = {'name': m['sec'], 'mkt': key.split('|')[1], 'n': 0, 'top': []}
            have = {t['c'] for t in sectors[key].get('top', [])}
            # opYoY 우선, 없으면 revYoY 로 정렬(비정상 초대형치 방지 위해 상한 clip)
            def gkey(x):
                return (x.get('opYoY') if x.get('opYoY') is not None else (x.get('revYoY') or -999))
            lst = [x for x in lst if x['code'] not in have]
            lst.sort(key=gkey, reverse=True)
            grow = [{'c': x['code'], 'n': x['name'],
                     'revYoY': x.get('revYoY'), 'opYoY': x.get('opYoY'), 'niYoY': x.get('niYoY'),
                     'rev': x.get('rev'), 'op': x.get('op')} for x in lst[:GROWN]]
            if grow:
                sectors[key]['grow'] = grow
                grown += 1
        DEBUG.append('성장주 부착 업종 %d개' % grown)
    except Exception as e:
        DEBUG.append('성장주 단계 오류: %s' % str(e)[:60])

    out = {'updated': time.strftime('%Y-%m-%d %H:%M', time.gmtime(time.time() + 9 * 3600)) + ' KST',
           'debug': DEBUG, 'sectors': sectors}
    os.makedirs('public/data', exist_ok=True)
    json.dump(out, open(OUT, 'w', encoding='utf-8'), ensure_ascii=False)
    print('완료:', DEBUG)


if __name__ == '__main__':
    try:
        main()
    except Exception as e:
        DEBUG.append('치명: %s' % str(e)[:80])
        try:
            json.dump({'updated': time.strftime('%Y-%m-%d %H:%M', time.gmtime(time.time() + 9 * 3600)) + ' KST',
                       'debug': DEBUG, 'sectors': {}, 'error': str(e)[:200]},
                      open(OUT, 'w', encoding='utf-8'), ensure_ascii=False)
        except Exception:
            pass
        print('오류:', DEBUG, file=sys.stderr)
        sys.exit(0)
