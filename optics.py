#!/usr/bin/env python3
# 광통신 마인드맵 — 해외 대장주·밸류체인 종목 시세 일일 수집 (KIS 해외주식 현재가상세)
# 필요 시크릿: KIS_APPKEY, KIS_APPSECRET
# 결과: public/data/optics_quotes.json
#   {updated, ok, fail, debug, map:{TICKER:{n,ex,cur,px,chg,mcap,per,pbr,eps,h52,l52}}}
#   mcap 단위: 백만(현지통화) — KIS tomv가 백만 단위
# 비상장(하쿠산·US Conec·SENKO·Micas 등)은 대상 아님 — 맵에서 정적 노드로만 표기
import os, sys, json, time, urllib.request

APPKEY = os.environ.get('KIS_APPKEY', '')
APPSECRET = os.environ.get('KIS_APPSECRET', '')
BASE = 'https://openapi.koreainvestment.com:9443'
OUT = os.environ.get('OUT', 'public/data/optics_quotes.json')
DEBUG = []

# (티커, 거래소, 표시명)  EXCD: NAS 나스닥 / NYS 뉴욕 / AMS 아멕스 / TSE 도쿄 / SZS 심천 / SHS 상해 / HKS 홍콩
# ※ 대만(Browave 3163 등)은 KIS 해외주식 미지원 → 수집 대상 제외
TICKERS = [
    # 대장주 6
    ('AVGO', 'NAS', 'Broadcom'),
    ('MRVL', 'NAS', 'Marvell'),
    ('GLW',  'NYS', 'Corning'),
    ('LITE', 'NAS', 'Lumentum'),
    ('COHR', 'NYS', 'Coherent'),
    ('CIEN', 'NYS', 'Ciena'),
    # 밸류체인 상류·인접
    ('AXTI', 'NAS', 'AXT (InP 기판)'),
    ('FN',   'NYS', 'Fabrinet (조립)'),
    ('INTC', 'NAS', 'Intel (SiPh 1위)'),
    ('CSCO', 'NAS', 'Cisco (SiPh 2위)'),
    ('TSM',  'NYS', 'TSMC (COUPE)'),
    ('GFS',  'NAS', 'GlobalFoundries (SiPh 파운드리)'),
    ('NVDA', 'NAS', 'NVIDIA (수요 발원지)'),
    ('CLS',  'NYS', 'Celestica (ODM)'),
    # 일본
    ('6503', 'TSE', 'Mitsubishi Electric (EML)'),
    ('5802', 'TSE', 'Sumitomo Electric (CW-DFB)'),
    ('5801', 'TSE', 'Furukawa Electric (펌프)'),
    ('6702', 'TSE', 'Fujitsu (TFLN)'),
    # 중국
    ('300308', 'SZS', 'Innolight 中际旭创'),
    ('300502', 'SZS', 'Eoptolink 新易盛'),
    ('300394', 'SZS', 'TFC 天孚通信'),
    ('300620', 'SZS', '光库科技 (TFLN)'),
    ('300456', 'SZS', '赛微电子 (Silex 모회사)'),
    ('601869', 'SHS', 'YOFC 长飞 (광섬유)'),
]

def post_json(url, body):
    req = urllib.request.Request(url, data=json.dumps(body).encode(),
                                 headers={'content-type': 'application/json'})
    return json.loads(urllib.request.urlopen(req, timeout=20).read().decode())

def get_json(url, headers):
    req = urllib.request.Request(url, headers=headers)
    return json.loads(urllib.request.urlopen(req, timeout=20).read().decode())

def num(s):
    try:
        v = float(str(s).replace(',', '').strip())
        return v if v != 0 else None
    except Exception:
        return None

def dump(m, fail):
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    prev = {}
    if not m:   # 전면 실패 시 기존 파일 보존
        try:
            prev = json.load(open(OUT, encoding='utf-8')).get('map', {})
        except Exception:
            pass
    json.dump({'updated': time.strftime('%Y-%m-%d %H:%M'),
               'ok': len(m or prev), 'fail': fail, 'debug': DEBUG[:12],
               'map': m or prev},
              open(OUT, 'w', encoding='utf-8'), ensure_ascii=False)
    print('저장 %s — 성공 %d / 실패 %d' % (OUT, len(m or prev), fail), file=sys.stderr)

def main():
    if not APPKEY or not APPSECRET:
        print('KIS_APPKEY/KIS_APPSECRET 없음 → 기존 파일 유지', file=sys.stderr)
        DEBUG.append('시크릿 없음')
        dump({}, 0)
        return
    token = None
    for a in range(4):      # 토큰 발급 1분 1회 제한
        try:
            tok = post_json(BASE + '/oauth2/tokenP',
                            {'grant_type': 'client_credentials', 'appkey': APPKEY, 'appsecret': APPSECRET})
        except Exception as e:
            tok = {'error': repr(e)}
        token = tok.get('access_token')
        if token:
            break
        DEBUG.append('토큰 시도%d: %s' % (a + 1, str(tok)[:120]))
        time.sleep(65)
    if not token:
        DEBUG.append('토큰 최종 실패')
        dump({}, 0)
        return
    hdr = {'content-type': 'application/json', 'authorization': 'Bearer ' + token,
           'appkey': APPKEY, 'appsecret': APPSECRET,
           'tr_id': 'HHDFS76200200', 'custtype': 'P'}
    try:
        prev = json.load(open(OUT, encoding='utf-8')).get('map', {})
    except Exception:
        prev = {}
    m, fail = {}, 0
    for tk, ex, nm in TICKERS:
        url = (BASE + '/uapi/overseas-price/v1/quotations/price-detail'
               + '?AUTH=&EXCD=' + ex + '&SYMB=' + tk)
        o = {}
        for attempt in range(2):
            try:
                o = (get_json(url, hdr) or {}).get('output') or {}
            except Exception as e:
                if len(DEBUG) < 10:
                    DEBUG.append('%s %s' % (tk, repr(e)[:80]))
                o = {}
            if o.get('last'):
                break
            time.sleep(0.7)
        px = num(o.get('last'))
        if not px:
            fail += 1
            if prev.get(tk):
                m[tk] = prev[tk]          # 직전 값 유지
            if len(DEBUG) < 10:
                DEBUG.append('%s 시세 없음' % tk)
            time.sleep(0.35)
            continue
        base = num(o.get('base'))
        eps, bps = num(o.get('epsx')), num(o.get('bpsx'))
        roe = round(eps / bps * 100, 1) if (eps and bps and bps > 0) else None
        m[tk] = {
            'n': nm, 'ex': ex, 'cur': (o.get('curr') or '').strip() or None,
            'px': round(px, 2),
            'chg': round((px - base) / base * 100, 2) if base else None,
            'mcap': num(o.get('tomv')),      # 백만(현지통화)
            'per': num(o.get('perx')), 'pbr': num(o.get('pbrx')),
            'eps': eps, 'roe': roe,
            'h52': num(o.get('h52p')), 'l52': num(o.get('l52p')),
        }
        if prev.get(tk, {}).get('fpe') is not None:   # 선행PER은 느리게 변하므로 승계
            m[tk]['fpe'] = prev[tk]['fpe']
        time.sleep(0.35)
    DEBUG.append('대상 %d · 성공 %d · 실패 %d' % (len(TICKERS), len(m), fail))
    dump(m, fail)

if __name__ == '__main__':
    main()
