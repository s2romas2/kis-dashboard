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
OUT = 'public/data/sectorstocks.json'
TOPN = 15                                 # 업종당 저장할 최대 종목수(등락률 상위)
DEBUG = []


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
        'fid_input_price_1': '',
        'fid_input_price_2': '',
        'fid_vol_cnt': '',
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
        chg = tonum(pick(r, CHG_KEYS))
        prc = tonum(pick(r, PRC_KEYS))
        cap = tonum(pick(r, CAP_KEYS))
        out.append({'c': str(c).zfill(6), 'n': str(n).strip(),
                    'chg': chg, 'prc': prc, 'cap': cap})
    return out, ''


category_stocks._logged = False


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
