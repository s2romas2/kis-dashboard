#!/usr/bin/env python3
# 업종별 견인 종목 수집 — KIS 업종별 구성종목 시세
# 랭크테이블에서 섹터 클릭 시 그 업종을 견인하는 종목(등락률·시총)을 표시하기 위한 데이터.
# 업종 코드·이름은 leadershist.json(이미 leaders.py가 채움)에서 그대로 재사용 → 이름이 랭크테이블과 100% 일치.
# 필요 시크릿: KIS_APPKEY, KIS_APPSECRET
import math, os, sys, json, time, urllib.request, urllib.parse

APPKEY = os.environ.get('KIS_APPKEY', '')
APPSECRET = os.environ.get('KIS_APPSECRET', '')
BASE = 'https://openapi.koreainvestment.com:9443'
HIST = 'public/data/leadershist.json'   # 업종코드→이름/시장 소스
SCREENER = 'public/data/screener.json'  # 종목별 실적·YoY 성장률 소스
MAPFILE = 'public/data/sectormap.json'  # 종목→KRX업종 매핑 캐시(재수집 최소화)
OUT = 'public/data/sectorstocks.json'
TOPN = 15                                 # 업종당 저장할 최대 종목수(등락률 상위)
GROWN = 10                                # 업종당 실적 성장주 최대 개수
GROW_CAP = 6000                           # 증가율 상한(%) — 전년 적자發 극단치 제외
GROW_OP = 6                               # 영업이익 성장 축에서 뽑는 수
GROW_REV = 5                              # 매출 성장 축에서 뽑는 수
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


IDX_CODE_KEYS = ['idx_bztp_scls_cd', 'idx_bztp_mcls_cd', 'idx_bztp_lcls_cd']  # 소>중>대 업종코드
STD_NAME_KEYS = ['std_idst_clsf_cd_name', 'idst_clsf_cd_name']               # 표준산업분류명(폴백)
# 표준산업분류명 키워드 → KRX 지수업종명 폴백(업종코드가 빈값인 종목용: 에이피알·코스맥스 등)
KW2KRX = [
    ('화장품', '화학'), ('화학', '화학'), ('석유', '화학'), ('고무', '화학'), ('플라스틱', '화학'),
    ('의약', '제약'), ('제약', '제약'), ('바이오', '제약'),
    ('반도체', '전기·전자'), ('전자부품', '전기·전자'), ('전자집적', '전기·전자'), ('디스플레이', '전기·전자'), ('전기장비', '전기·전자'),
    ('자동차', '운송장비·부품'), ('운송장비', '운송장비·부품'), ('선박', '운송장비·부품'), ('항공기', '운송장비·부품'),
    ('식료품', '음식료·담배'), ('음료', '음식료·담배'), ('담배', '음식료·담배'),
    ('섬유', '섬유·의류'), ('의복', '섬유·의류'), ('의류', '섬유·의류'), ('가죽', '섬유·의류'),
    ('건설', '건설'), ('토목', '건설'),
    ('은행', '금융'), ('금융지주', '금융'), ('여신', '금융'),
    ('보험', '보험'), ('증권', '증권'), ('금융투자', '증권'),
    ('소프트웨어', 'IT 서비스'), ('정보서비스', 'IT 서비스'), ('컴퓨터프로그', 'IT 서비스'), ('자료처리', 'IT 서비스'),
    ('기계', '기계·장비'), ('장비', '기계·장비'),
    ('1차 금속', '금속'), ('금속가공', '금속'), ('철강', '금속'),
    ('도매', '유통'), ('소매', '유통'), ('상품 중개', '유통'),
    ('운수', '운송·창고'), ('창고', '운송·창고'), ('물류', '운송·창고'),
    ('통신', '통신'), ('부동산', '부동산'),
    ('종이', '종이·목재'), ('펄프', '종이·목재'), ('목재', '종이·목재'),
    ('비금속', '비금속'), ('시멘트', '비금속'), ('요업', '비금속'),
    ('전기, 가스', '전기·가스'), ('전기업', '전기·가스'), ('가스', '전기·가스'),
    ('의료용', '의료·정밀기기'), ('정밀기기', '의료·정밀기기'), ('측정', '의료·정밀기기'),
    ('출판', '출판·매체복제'), ('영상', '오락·문화'), ('방송', '오락·문화'), ('오락', '오락·문화'), ('게임', '오락·문화'),
]


def stock_industry(hdr, code):
    """종목 기본정보 → (업종코드 후보[소,중,대], 시장, 표준산업분류명). 첫 성공 응답 키를 DEBUG에 1회."""
    u = BASE + '/uapi/domestic-stock/v1/quotations/search-stock-info?PRDT_TYPE_CD=300&PDNO=' + code
    h = dict(hdr); h['tr_id'] = 'CTPF1002R'
    j = get_json(u, h)
    o = j.get('output') or {}
    if o and not stock_industry._logged:
        DEBUG.append('기본정보 키: ' + ','.join(list(o.keys())[:32]))
        stock_industry._logged = True
    codes = [str(o.get(k)).strip() for k in IDX_CODE_KEYS]
    std = next((str(o.get(k)).strip() for k in STD_NAME_KEYS if o.get(k)), '')
    mkt = _mkt_of(next((o.get(k) for k in MKT_KEYS if o.get(k)), ''))
    return codes, mkt, std


stock_industry._logged = False


def build_sectormap(hdr, scodes, code2name, probe=()):
    """screener 종목 code→(업종명,시장). idx_bztp 업종코드를 leadershist 코드(code2name)에 직접 매칭.
    어느 레벨(소/중/대)이 맞는지 자동 선택. probe 종목은 코드값을 DEBUG에 남겨 진단."""
    # leadershist 코드는 KOSPI 0xxx / KOSDAQ 1xxx. idx_bztp 코드 포맷이 달라도 zfill/뒤3자리로 맞춰 시도
    name_by_full = dict(code2name)                                  # '0008' -> '화학'
    name_by_tail = {}                                               # '008' -> '화학'(시장 무시 보조)
    for c, nm in code2name.items():
        name_by_tail[c.lstrip('0')[-3:].zfill(3) if c.lstrip('0') else c] = nm
    raw = {}
    for code in scodes:
        try:
            cands, mkt, std = stock_industry(hdr, code)
            raw[code] = {'cands': cands, 'mkt': mkt, 'std': std}
            if code in probe:
                DEBUG.append('probe %s: idx=%s std=%s mkt=%s' % (code, cands, std, mkt))
        except Exception as e:
            if len(DEBUG) < 22:
                DEBUG.append('info %s 오류 %s' % (code, str(e)[:22]))
        time.sleep(0.12)

    def resolve(cands, mkt, std):
        pref = '1' if mkt == 'KOSDAQ' else '0'
        for cd in cands:
            if not cd or cd in ('None', ''):
                continue
            for cand_full in (cd, cd.zfill(4), pref + cd[-3:].zfill(3), '0' + cd[-3:].zfill(3), '1' + cd[-3:].zfill(3)):
                if cand_full in name_by_full:
                    return name_by_full[cand_full]
            tail = cd.lstrip('0')[-3:].zfill(3) if cd.lstrip('0') else cd
            if tail in name_by_tail:
                return name_by_tail[tail]
        # 업종코드 빈값/미매칭 → 표준산업분류명 키워드 폴백
        if std:
            for kw, krx in KW2KRX:
                if kw in std and krx in set(code2name.values()):
                    return krx
        return None

    mp = {}
    for code, v in raw.items():
        sec = resolve(v['cands'], v['mkt'], v.get('std', ''))
        if sec:
            mp[code] = {'sec': sec, 'mkt': v['mkt']}
    DEBUG.append('업종매핑: %d종목 조회 → %d종목 매칭' % (len(raw), len(mp)))
    return {'v': 3, 'built': time.time(), 'map': mp}


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
        code2name = {code: name for code, name, mkt in codes}   # leadershist 업종코드→이름
        screener = json.load(open(SCREENER, encoding='utf-8')).get('list', [])
        scodes = [x['code'] for x in screener if x.get('code')]
        # 업종 매핑 캐시 로드/재생성 (v2)
        smap = None
        try:
            cache = json.load(open(MAPFILE, encoding='utf-8'))
            if cache.get('v') == 3 and (time.time() - cache.get('built', 0)) < MAP_TTL and cache.get('map'):
                smap = cache; DEBUG.append('업종매핑 캐시 사용(%d종목)' % len(cache['map']))
        except Exception:
            pass
        if smap is None:
            smap = build_sectormap(hdr, scodes, code2name, probe=('278470', '192820', '005930'))
            json.dump(smap, open(MAPFILE, 'w', encoding='utf-8'), ensure_ascii=False)
        mp = smap['map']
        # 업종별 성장주 수집: rev>=300억 & opYoY 상위, 이미 견인 top에 있으면 제외
        by_sec = {}
        sd = {x['code']: x for x in screener}
        for code, m in mp.items():
            x = sd.get(code)
            if not x:
                continue
            if (x.get('rev') or 0) < 500:          # 분기 매출 500억 미만 제외(미니캡 노이즈)
                continue
            if (x.get('op') or 0) <= 0:            # 적자 기업 제외
                continue
            oy, ry = x.get('opYoY'), x.get('revYoY')
            ok_op = oy is not None and 20 <= oy <= GROW_CAP
            ok_rev = ry is not None and 25 <= ry <= GROW_CAP
            if not (ok_op or ok_rev):              # 영업이익·매출 어느 쪽도 성장 신호가 없으면 제외
                continue
            key = '%s|%s' % (m['sec'], m['mkt'])
            by_sec.setdefault(key, []).append(x)
        grown = 0
        for key, lst in by_sec.items():
            if key not in sectors:
                sectors[key] = {'name': m['sec'], 'mkt': key.split('|')[1], 'n': 0, 'top': []}
            have = {t['c'] for t in sectors[key].get('top', [])}
            # opYoY 우선, 없으면 revYoY 로 정렬(비정상 초대형치 방지 위해 상한 clip)
            # 점수 = log(증가율) x log(매출) — 미니베이스 수천%가 대형 실적주를 밀어내지 않게 완충
            def sc(v, rev):
                return 0.0 if v is None or v < 0 else math.log10(1 + v) * math.log10(max(rev or 500, 500))
            lst = [x for x in lst if x['code'] not in have]
            byop = sorted([x for x in lst if (x.get('opYoY') or -1) >= 20],
                          key=lambda x: sc(x.get('opYoY'), x.get('rev')), reverse=True)[:GROW_OP]
            byrev = sorted([x for x in lst if (x.get('revYoY') or -1) >= 25],
                           key=lambda x: sc(x.get('revYoY'), x.get('rev')), reverse=True)[:GROW_REV]
            seen, merged = set(), []
            for x in byop + byrev:                 # 영업이익 성장 우선 + 매출 성장 축을 따로 보강
                if x['code'] in seen:
                    continue
                seen.add(x['code']); merged.append(x)
            grow = [{'c': x['code'], 'n': x['name'],
                     'revYoY': x.get('revYoY'), 'opYoY': x.get('opYoY'), 'niYoY': x.get('niYoY'),
                     'rev': x.get('rev'), 'op': x.get('op')} for x in merged[:GROWN]]
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
