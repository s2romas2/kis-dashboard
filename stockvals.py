#!/usr/bin/env python3
# 전 상장사 현재 PBR·PER·시총 일일 수집 (KIS 오픈API)
# (run: KIS 시크릿 등록 후 첫 실행)
# 필요 시크릿: KIS_APPKEY, KIS_APPSECRET
# 결과: public/data/stockvals.json {map: {code: [pbr, per, 시총(억), 현재가]}}
import os, sys, json, time, urllib.request, re

APPKEY = os.environ.get('KIS_APPKEY', '')
APPSECRET = os.environ.get('KIS_APPSECRET', '')
BASE = 'https://openapi.koreainvestment.com:9443'
OUT = 'public/data/stockvals.json'
LIMIT = int(os.environ.get('LIMIT', '0'))  # 테스트용

def post_json(url, body):
    req = urllib.request.Request(url, data=json.dumps(body).encode(),
                                 headers={'content-type': 'application/json'})
    return json.loads(urllib.request.urlopen(req, timeout=20).read().decode())

def get_json(url, headers):
    req = urllib.request.Request(url, headers=headers)
    return json.loads(urllib.request.urlopen(req, timeout=20).read().decode())

def tonum(s):
    try:
        v = float(str(s).replace(',', '').strip())
        return v
    except Exception:
        return None

def main():
    if not APPKEY or not APPSECRET:
        print('KIS_APPKEY/KIS_APPSECRET 시크릿이 없어 건너뜀 (기존 파일 유지)', file=sys.stderr)
        return
    try:
        pj = json.load(open('public/data/products.json', encoding='utf-8'))
        codes = [c for c, v in pj['map'].items()
                 if re.fullmatch(r'\d{6}', c) and (not isinstance(v, dict) or v.get('m') != 'N')]
    except Exception as e:
        print('products.json 로드 실패:', e); sys.exit(1)
    if LIMIT:
        codes = codes[:LIMIT]
    tok = post_json(BASE + '/oauth2/tokenP',
                    {'grant_type': 'client_credentials', 'appkey': APPKEY, 'appsecret': APPSECRET})
    token = tok.get('access_token')
    if not token:
        print('토큰 발급 실패:', tok); sys.exit(1)
    hdr = {'content-type': 'application/json', 'authorization': 'Bearer ' + token,
           'appkey': APPKEY, 'appsecret': APPSECRET, 'tr_id': 'FHKST01010100', 'custtype': 'P'}
    m, fail = {}, 0
    for i, code in enumerate(codes):
        try:
            j = get_json(BASE + '/uapi/domestic-stock/v1/quotations/inquire-price'
                         + '?fid_cond_mrkt_div_code=J&fid_input_iscd=' + code, hdr)
            o = j.get('output') or {}
            if not o.get('stck_prpr'):
                msg = j.get('msg1', '')
                if 'EGW00201' in str(j) or '초당' in msg:
                    time.sleep(0.6)
                    j = get_json(BASE + '/uapi/domestic-stock/v1/quotations/inquire-price'
                                 + '?fid_cond_mrkt_div_code=J&fid_input_iscd=' + code, hdr)
                    o = j.get('output') or {}
            price = tonum(o.get('stck_prpr'))
            if price:
                pbr = tonum(o.get('pbr'))
                per = tonum(o.get('per'))
                cap = tonum(o.get('hts_avls'))
                m[code] = [round(pbr, 2) if pbr and pbr > 0 else None,
                           round(per, 2) if per and per > 0 else None,
                           round(cap) if cap else None,
                           round(price)]
            else:
                fail += 1
        except Exception:
            fail += 1
            time.sleep(0.5)
        time.sleep(0.075)
        if i % 300 == 0:
            print('%d/%d…' % (i, len(codes)), file=sys.stderr)
    out = {'updated': time.strftime('%Y-%m-%d %H:%M'), 'count': len(m), 'fail': fail, 'map': m}
    os.makedirs('public/data', exist_ok=True)
    with open(OUT, 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False)
    print('저장: %d종목 (실패 %d)' % (len(m), fail))

if __name__ == '__main__':
    main()
