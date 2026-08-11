#!/usr/bin/env python3
# 주도 업종(섹터 로테이션) 수집 — KIS 업종지수 기간별 시세
# v2: 커밋 단계 수정 재트리거
# 일/주/월/연 등락률 순위 + 연도별 상위 업종 히스토리(책 표 1-3 스타일)
# 필요 시크릿: KIS_APPKEY, KIS_APPSECRET
import os, sys, json, time, urllib.request

APPKEY = os.environ.get('KIS_APPKEY', '')
APPSECRET = os.environ.get('KIS_APPSECRET', '')
BASE = 'https://openapi.koreainvestment.com:9443'
OUT = 'public/data/leaders.json'
HIST = 'public/data/leadershist.json'  # 업종별 월봉 캐시(연도별 표 계산용)
DEBUG = []

# KRX 업종코드 후보 (KOSPI 0xxx / KOSDAQ 1xxx) — 응답에 이름이 오는 것만 자동 채택
KOSPI_CANDS = ['%04d' % i for i in range(2, 46)]
KOSDAQ_CANDS = ['1%03d' % i for i in range(2, 46)]
SKIP_NAMES = ('대형주', '중형주', '소형주', '제조업', 'KOSPI', 'KOSDAQ', '종합', '우량', '벤처', '중견', '기술성장',
              '외국주포함', '글로벌', '150', '100', '50')

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

def candles(hdr, code, d1, d2, period):
    """업종지수 기간별 시세 → (업종명, [[YYYYMMDD, close], ...] 오름차순)"""
    u = (BASE + '/uapi/domestic-stock/v1/quotations/inquire-daily-indexchartprice'
         '?FID_COND_MRKT_DIV_CODE=U&FID_INPUT_ISCD=%s&FID_INPUT_DATE_1=%s&FID_INPUT_DATE_2=%s&FID_PERIOD_DIV_CODE=%s'
         % (code, d1, d2, period))
    h = dict(hdr); h['tr_id'] = 'FHKUP03500100'
    j = get_json(u, h)
    if j.get('rt_cd') != '0':
        return None, []
    name = (j.get('output1') or {}).get('hts_kor_isnm', '').strip()
    rows = []
    for r in (j.get('output2') or []):
        d, v = r.get('stck_bsop_date'), tonum(r.get('bstp_nmix_prpr'))
        if d and v:
            rows.append([d, v])
    rows.sort()
    return name, rows

def ret(rows, n_back):
    """rows 마지막 종가 대비 n_back개 전 종가 수익률(%)"""
    if len(rows) < n_back + 1:
        return None
    a, b = rows[-1 - n_back][1], rows[-1][1]
    return round((b / a - 1) * 100, 1) if a else None

def main():
    if not APPKEY or not APPSECRET:
        print('KIS 키 없음 — 건너뜀', file=sys.stderr); return
    token = get_token()
    DEBUG.append('토큰: %s' % ('OK' if token else '실패'))
    if not token:
        raise RuntimeError('KIS 토큰 실패')
    hdr = {'content-type': 'application/json', 'authorization': 'Bearer ' + token,
           'appkey': APPKEY, 'appsecret': APPSECRET, 'custtype': 'P'}
    today = time.strftime('%Y%m%d', time.gmtime(time.time() + 9 * 3600))

    # 월봉 히스토리 캐시 (연도별 표용) — 없거나 60일 지난 업종만 풀수집
    try:
        hist = json.load(open(HIST, encoding='utf-8'))
    except Exception:
        hist = {'sectors': {}}

    sectors = {}   # code -> {name, mkt, daily:[[d,v],...]}
    found = 0
    for code in KOSPI_CANDS + KOSDAQ_CANDS:
        mkt = 'KOSPI' if code.startswith('0') else 'KOSDAQ'
        try:
            name, rows = candles(hdr, code, '20250601', today, 'D')
        except Exception as e:
            DEBUG.append('%s 조회 오류 %s' % (code, str(e)[:30]))
            time.sleep(0.5); continue
        time.sleep(0.25)
        if not name or not rows or any(s in name for s in SKIP_NAMES):
            continue
        sectors[code] = {'name': name, 'mkt': mkt, 'daily': rows[-70:]}
        found += 1
        # 월봉(2001~) 캐시: 최초 1회 또는 월 단위 갱신
        hc = hist['sectors'].get(code)
        need_full = not hc or not hc.get('monthly')
        if need_full:
            monthly = []
            for (a, b) in [('20010101', '20090101'), ('20090102', '20170101'), ('20170102', '20250101')]:
                try:
                    _, mrows = candles(hdr, code, a, b, 'M')
                    monthly += mrows
                except Exception:
                    pass
                time.sleep(0.25)
            hist['sectors'][code] = {'name': name, 'mkt': mkt, 'monthly': monthly}
        # 최근 월봉은 매번 갱신(최근 2년 창)
        try:
            _, recent = candles(hdr, code, '20250102', today, 'M')
            hc = hist['sectors'][code]
            have = {r[0] for r in hc['monthly']}
            hc['monthly'] = sorted(hc['monthly'] + [r for r in recent if r[0] not in have])
        except Exception:
            pass
        time.sleep(0.2)
    DEBUG.append('업종 %d개 인식' % found)
    if found < 10:
        raise RuntimeError('업종 인식 %d개 — API 응답 확인 필요' % found)

    # 지수(코스피 0001, 코스닥 1001) 연도별 수익률
    idx_hist = {}
    for code, label in [('0001', 'kospi'), ('1001', 'kosdaq')]:
        monthly = []
        for (a, b) in [('20010101', '20090101'), ('20090102', '20170101'), ('20170102', today)]:
            try:
                _, mrows = candles(hdr, code, a, b, 'M')
                monthly += mrows
            except Exception:
                pass
            time.sleep(0.25)
        idx_hist[label] = monthly

    # ---- 기간별 순위 (일=1, 주=5, 월=21, 연=YTD) ----
    def ytd(rows):
        year = today[:4]
        prev = [r for r in rows if r[0] < year + '0101']
        base = prev[-1][1] if prev else None
        if not base:  # daily가 6월부터라 YTD는 월봉 사용
            return None
        return round((rows[-1][1] / base - 1) * 100, 1)
    periods = {'d': [], 'w': [], 'm': [], 'y': []}
    for code, s in sectors.items():
        rows = s['daily']
        mon = hist['sectors'].get(code, {}).get('monthly', [])
        entry = {'n': s['name'], 'mkt': s['mkt']}
        r_d, r_w, r_m = ret(rows, 1), ret(rows, 5), ret(rows, 21)
        # 연초 대비: 월봉에서 작년 12월 종가
        r_y = None
        prev_dec = [r for r in mon if r[0] < today[:4] + '0101']
        if prev_dec and rows:
            r_y = round((rows[-1][1] / prev_dec[-1][1] - 1) * 100, 1)
        for k, v in [('d', r_d), ('w', r_w), ('m', r_m), ('y', r_y)]:
            if v is not None:
                periods[k].append({**entry, 'r': v})
    for k in periods:
        periods[k].sort(key=lambda x: -x['r'])

    # ---- 연도별 히스토리 표 (각 연도: 지수 수익률 + 상위 5업종) ----
    def year_close(monthly, year):
        rows = [r for r in monthly if r[0] <= '%s1231' % year]
        return rows[-1][1] if rows else None
    years = []
    cur_year = int(today[:4])
    for y in range(2002, cur_year + 1):
        row = {'year': y}
        for label in ('kospi', 'kosdaq'):
            a, b = year_close(idx_hist[label], y - 1), year_close(idx_hist[label], y)
            row[label] = round((b / a - 1) * 100, 1) if a and b else None
        tops = []
        for code, hc in hist['sectors'].items():
            a, b = year_close(hc['monthly'], y - 1), year_close(hc['monthly'], y)
            if a and b:
                tops.append({'n': hc['name'], 'mkt': hc['mkt'], 'r': round((b / a - 1) * 100, 1)})
        tops.sort(key=lambda x: -x['r'])
        row['top'] = tops[:5]
        if row['top']:
            years.append(row)
    # 올해 행은 YTD 표기
    if years and years[-1]['year'] == cur_year:
        years[-1]['ytd'] = True

    out = {'updated': time.strftime('%Y-%m-%d %H:%M', time.gmtime(time.time() + 9 * 3600)) + ' KST',
           'debug': DEBUG, 'periods': periods, 'history': years}
    os.makedirs('public/data', exist_ok=True)
    json.dump(out, open(OUT, 'w', encoding='utf-8'), ensure_ascii=False)
    json.dump(hist, open(HIST, 'w', encoding='utf-8'), ensure_ascii=False)
    print('완료:', DEBUG)

if __name__ == '__main__':
    try:
        main()
    except Exception:
        import traceback
        json.dump({'at': time.strftime('%Y-%m-%d %H:%M'), 'trace': traceback.format_exc()[-2500:]},
                  open('public/data/leaders_error.json', 'w', encoding='utf-8'), ensure_ascii=False)
        raise
