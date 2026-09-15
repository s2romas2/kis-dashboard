#!/usr/bin/env python3
# 주도 업종(섹터 로테이션) 수집 — KIS 업종지수 기간별 시세
# v3 (2026-09-15 랭크테이블 업그레이드 A/B):
#   - 일봉 2020-01-02~ / 주봉 2018-01-02~ 딥 히스토리 백필(창을 잘게 나눠 반복, dv=2 → 최초 1회 재빌드)
#   - 봉마다 거래대금·거래량 저장: daily/weekly 행 = [YYYYMMDD, 종가, 거래대금(억원), 거래량(주)]
#   - 거래대금 축: 최근 5일 평균 ÷ 직전 60일 평균(급증 배수) → leaders.json 'money'
# 일/주/월/연 등락률 순위 + 연도별 상위 업종 히스토리(책 표 1-3 스타일)
# 필요 시크릿: KIS_APPKEY, KIS_APPSECRET
import os, sys, json, time, datetime, urllib.request

APPKEY = os.environ.get('KIS_APPKEY', '')
APPSECRET = os.environ.get('KIS_APPSECRET', '')
BASE = 'https://openapi.koreainvestment.com:9443'
OUT = 'public/data/leaders.json'
HIST = 'public/data/leadershist.json'  # 업종별 월봉(2001~)·일봉(2020~)·주봉(2018~) 캐시
DEBUG = []

# KRX 업종코드 후보 (KOSPI 0xxx / KOSDAQ 1xxx) — 응답에 이름이 오는 것만 자동 채택
KOSPI_CANDS = ['%04d' % i for i in range(2, 46)]
KOSDAQ_CANDS = ['1%03d' % i for i in range(2, 46)]
SKIP_NAMES = ('대형주', '중형주', '소형주', '제조업', 'KOSPI', 'KOSDAQ', '종합', '우량', '벤처', '중견', '기술성장',
              '외국주포함', '글로벌', '150', '100', '50')

# ---- 히스토리 캐시 버전 ----
HV = 2            # 월봉(2001~): 변경 없음 — 재수집하지 않음
DV = 2            # 일·주봉: 2 = 2020/2018 딥 백필 + 거래대금·거래량 컬럼 (버전 올리면 최초 1회 풀백필)
DAILY_START = '20200102'
WEEKLY_START = '20180102'
DAILY_CAP, WEEKLY_CAP = 1700, 450
DAILY_STEP_DAYS = 60       # 일봉 창(달력일) — 호출당 봉 수 제한(~50)을 넘지 않게 약 40거래일
WEEKLY_STEP_DAYS = 240     # 주봉 창(달력일) — 약 34주
SLEEP = 0.06               # 호출 사이 대기


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


VAL_UNIT = {'mult': None, 'src': ''}   # acml_tr_pbmn 단위(원 환산 배수) — KOSPI(0001) 샘플로 추정


def candles(hdr, code, d1, d2, period):
    """업종지수 기간별 시세 → (업종명, [[YYYYMMDD, 종가, 거래대금(억원)|None, 거래량(주)|None], ...] 오름차순)"""
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
        if not d or not v:
            continue
        raw_val = tonum(r.get('acml_tr_pbmn'))
        vol = tonum(r.get('acml_vol'))
        val = None
        if raw_val is not None and VAL_UNIT['mult']:
            val = round(raw_val * VAL_UNIT['mult'] / 1e8, 1)          # → 억원
        rows.append([d, v, val, int(vol) if vol is not None else None])
    rows.sort()
    return name, rows


def candles_retry(hdr, code, d1, d2, period):
    """실패 시 1회 재시도"""
    for attempt in range(2):
        try:
            return candles(hdr, code, d1, d2, period)
        except Exception as e:
            if attempt == 1:
                raise
            DEBUG.append('%s %s %s 재시도: %s' % (code, period, d1, str(e)[:30])) if len(DEBUG) < 40 else None
            time.sleep(1.0)
    return None, []


def guess_val_unit(hdr, today):
    """KOSPI(0001) 최근 일봉의 acml_tr_pbmn 크기로 단위 추정.
    코스피 일 거래대금은 3조~40조원 → 원 단위면 1e12~4e13, 백만원 단위면 1e6~4e7, 천원 단위면 1e9~4e10."""
    try:
        d1 = (datetime.date.today() - datetime.timedelta(days=20)).strftime('%Y%m%d')
        u = (BASE + '/uapi/domestic-stock/v1/quotations/inquire-daily-indexchartprice'
             '?FID_COND_MRKT_DIV_CODE=U&FID_INPUT_ISCD=0001&FID_INPUT_DATE_1=%s&FID_INPUT_DATE_2=%s&FID_PERIOD_DIV_CODE=D'
             % (d1, today))
        h = dict(hdr); h['tr_id'] = 'FHKUP03500100'
        j = get_json(u, h)
        vals = [tonum(r.get('acml_tr_pbmn')) for r in (j.get('output2') or [])]
        vals = [v for v in vals if v]
        if not vals:
            DEBUG.append('거래대금 단위 추정 실패: 0001 응답에 acml_tr_pbmn 없음 — 거래대금 미저장')
            return
        v = sorted(vals)[len(vals) // 2]
        if v >= 1e11:
            mult, unit = 1, '원'
        elif v >= 1e8:
            mult, unit = 1e3, '천원'
        else:
            mult, unit = 1e6, '백만원'
        VAL_UNIT['mult'] = mult
        VAL_UNIT['src'] = '0001 중앙값 %.0f → %s 단위 가정' % (v, unit)
        DEBUG.append('거래대금 단위: ' + VAL_UNIT['src'])
    except Exception as e:
        DEBUG.append('거래대금 단위 추정 오류 %s' % str(e)[:40])


def ret(rows, n_back):
    """rows 마지막 종가 대비 n_back개 전 종가 수익률(%)"""
    if len(rows) < n_back + 1:
        return None
    a, b = rows[-1 - n_back][1], rows[-1][1]
    return round((b / a - 1) * 100, 1) if a else None


def dedupe_monthly(rows):
    best = {}
    for r in rows:
        d, v = r[0], r[1]
        ym = d[:6]
        if ym not in best or d > best[ym][0]:
            best[ym] = [d, v]
    return [best[k] for k in sorted(best)]


def merge_series(hc, key, rows, cap):
    """날짜 기준 병합 — 새 행이 거래대금 컬럼을 갖고 있으면 우선, 없으면 기존 행 유지"""
    byd = {}
    for r in (hc.get(key) or []):
        byd[r[0]] = list(r)
    for r in rows:
        old = byd.get(r[0])
        if old and len(old) >= 4 and (len(r) < 4 or r[2] is None):
            old[1] = r[1]            # 종가만 갱신
            continue
        byd[r[0]] = list(r)
    hc[key] = [byd[d] for d in sorted(byd)][-cap:]


def date_windows(start, today, step_days):
    """start~today 를 step_days 달력일 창으로 분할(오름차순) — 과거를 무제한 가져오기 위한 반복 창"""
    out = []
    cur = datetime.datetime.strptime(start, '%Y%m%d').date()
    end = datetime.datetime.strptime(today, '%Y%m%d').date()
    while cur <= end:
        nxt = min(cur + datetime.timedelta(days=step_days - 1), end)
        out.append((cur.strftime('%Y%m%d'), nxt.strftime('%Y%m%d')))
        cur = nxt + datetime.timedelta(days=1)
    return out


def deep_ok(rows, thresh):
    """딥 백필 완료 여부: 첫 행이 thresh 이전이고 거래대금 컬럼(4원소)을 갖고 있으면 완료로 본다"""
    return bool(rows) and rows[0][0] <= thresh and len(rows[0]) >= 4


def save_hist(hist):
    os.makedirs('public/data', exist_ok=True)
    json.dump(hist, open(HIST, 'w', encoding='utf-8'), ensure_ascii=False)


def money_axis(rows, skip_date=None):
    """거래대금 축: 최근 5봉 평균 ÷ 직전 60봉 평균 (rows = daily [[d, close, val, vol], ...]).
    skip_date = 장중 미완성 봉(오늘) — 평균을 희석하지 않도록 제외"""
    vals = [(r[0], r[2]) for r in rows if len(r) >= 3 and r[2] and r[0] != skip_date]
    if len(vals) < 25:
        return None
    last5 = [v for _, v in vals[-5:]]
    prev = [v for _, v in vals[-65:-5]]
    if not prev:
        return None
    a5 = sum(last5) / len(last5)
    a60 = sum(prev) / len(prev)
    if a60 <= 0:
        return None
    return {'v5': round(a5, 1), 'v60': round(a60, 1), 'x': round(a5 / a60, 2),
            'd1': vals[-1][1], 'asof': vals[-1][0]}


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
    guess_val_unit(hdr, today)

    # 월봉 히스토리 캐시 (연도별 표용) — hv 동일하면 재수집 없음(2001~ 캐시 그대로 활용)
    try:
        hist = json.load(open(HIST, encoding='utf-8'))
    except Exception:
        hist = {'sectors': {}}
    hist.setdefault('sectors', {})
    rebuild_all = hist.get('hv') != HV
    # 일·주봉 딥 백필은 업종별로 완료 여부(deep_ok)를 보고 필요한 업종만 수행 + 업종마다 캐시 저장(타임아웃돼도 진행분 보존)
    DAILY_THRESH, WEEKLY_THRESH = '20200301', '20180301'
    if hist.get('dv') != DV:
        DEBUG.append('일·주봉 딥 백필(dv=%d): 일봉 %s~ %d일창, 주봉 %s~ %d일창 — 업종별 미완료분만' % (DV, DAILY_START, DAILY_STEP_DAYS, WEEKLY_START, WEEKLY_STEP_DAYS))
    n_backfilled = 0

    def month_ranges():
        out, y = [], 2001
        while y <= int(today[:4]):
            out.append(('%d0101' % y, min('%d1231' % (y + 3), today)))
            y += 4
        return out

    sectors = {}   # code -> {name, mkt, daily:[[d,v,val,vol],...]}
    found = 0
    n_calls = 0
    t0 = time.time()
    recent_d1 = (datetime.date.today() - datetime.timedelta(days=90)).strftime('%Y%m%d')
    for code in KOSPI_CANDS + KOSDAQ_CANDS:
        mkt = 'KOSPI' if code.startswith('0') else 'KOSDAQ'
        try:
            name, rows = candles_retry(hdr, code, recent_d1, today, 'D')
            n_calls += 1
        except Exception as e:
            DEBUG.append('%s 조회 오류 %s' % (code, str(e)[:30]))
            time.sleep(0.5); continue
        time.sleep(SLEEP)
        if not name or not rows or any(s in name for s in SKIP_NAMES):
            continue
        found += 1
        # 월봉(2001~) 캐시: 최초 1회(또는 hv 버전업 시) 4년 단위 풀백필 — 현재 hv 유지 → 기존 캐시 재사용
        hc = hist['sectors'].get(code)
        need_full = rebuild_all or not hc or not hc.get('monthly')
        if need_full:
            monthly = []
            for (a, b) in month_ranges():
                try:
                    _, mrows = candles_retry(hdr, code, a, b, 'M')
                    monthly += mrows
                except Exception:
                    pass
                time.sleep(0.25)
            hist['sectors'][code] = {'name': name, 'mkt': mkt, 'monthly': dedupe_monthly(monthly)}
        hc = hist['sectors'][code]
        hc['name'], hc['mkt'] = name, mkt
        # 최근 월봉은 매번 갱신(최근 2년 창) — 같은 달은 최신 일자로 교체
        try:
            _, recent = candles_retry(hdr, code, '20250102', today, 'M')
            hc['monthly'] = dedupe_monthly(hc['monthly'] + recent)
        except Exception:
            pass
        time.sleep(SLEEP)
        # 일봉(2020~)·주봉(2018~) 히스토리 — 랭크테이블 일별/주별 보기 + 거래대금 축
        need_w = not deep_ok(hc.get('weekly'), WEEKLY_THRESH)
        need_d = not deep_ok(hc.get('daily'), DAILY_THRESH)
        try:
            if need_w:
                for (a, b) in date_windows(WEEKLY_START, today, WEEKLY_STEP_DAYS):
                    _, wr = candles_retry(hdr, code, a, b, 'W')
                    n_calls += 1
                    merge_series(hc, 'weekly', wr, WEEKLY_CAP)
                    time.sleep(SLEEP)
            else:                                   # 증분: 최근 3개월만
                _, wr = candles_retry(hdr, code, (datetime.date.today() - datetime.timedelta(days=90)).strftime('%Y%m%d'), today, 'W')
                merge_series(hc, 'weekly', wr, WEEKLY_CAP)
                time.sleep(SLEEP)
            if need_d:
                for (a, b) in date_windows(DAILY_START, today, DAILY_STEP_DAYS):
                    _, dr = candles_retry(hdr, code, a, b, 'D')
                    n_calls += 1
                    merge_series(hc, 'daily', dr, DAILY_CAP)
                    time.sleep(SLEEP)
            else:
                merge_series(hc, 'daily', rows, DAILY_CAP)   # 위에서 받은 최근 90일 창 재사용
        except Exception as e:
            if len(DEBUG) < 40:
                DEBUG.append('%s 일/주봉 %r' % (code, str(e)[:30]))
        if need_w or need_d:
            n_backfilled += 1
            try:
                save_hist(hist)                     # 업종 단위 중간 저장 — 타임아웃 시에도 진행분 커밋(if: always)
            except Exception:
                pass
        # 순위 계산용 최근 일봉은 병합된 캐시에서(창 분할 덕에 최신까지 연속)
        sectors[code] = {'name': name, 'mkt': mkt, 'daily': (hc.get('daily') or rows)[-70:]}
    DEBUG.append('업종 %d개 인식 · 호출 %d회 · %.0f초' % (found, n_calls, time.time() - t0))
    if found < 10:
        raise RuntimeError('업종 인식 %d개 — API 응답 확인 필요' % found)
    lens = [(len(hc.get('daily') or []), len(hc.get('weekly') or [])) for hc in hist['sectors'].values()]
    n_deep = sum(1 for hc in hist['sectors'].values() if deep_ok(hc.get('daily'), DAILY_THRESH) and deep_ok(hc.get('weekly'), WEEKLY_THRESH))
    if lens:
        DEBUG.append('딥 백필 이번 실행 %d업종 · 완료 %d/%d · 일봉 최소 %d/최대 %d, 주봉 최소 %d/최대 %d' % (
            n_backfilled, n_deep, len(hist['sectors']), min(x[0] for x in lens), max(x[0] for x in lens), min(x[1] for x in lens), max(x[1] for x in lens)))
    rebuild_dw_ok = n_deep == len(hist['sectors'])   # 전 업종 완료 시에만 dv 기록(정보용 — 실제 판단은 업종별 deep_ok)

    # 지수(코스피 0001, 코스닥 1001) 연도별 수익률
    idx_hist = {}
    for code, label in [('0001', 'kospi'), ('1001', 'kosdaq')]:
        monthly = []
        for (a, b) in month_ranges():
            try:
                _, mrows = candles_retry(hdr, code, a, b, 'M')
                monthly += mrows
            except Exception:
                pass
            time.sleep(0.25)
        idx_hist[label] = dedupe_monthly(monthly)

    # ---- 기간별 순위 (일=1, 주=5, 월=21, 연=YTD) ----
    periods = {'d': [], 'w': [], 'm': [], 'y': []}
    for code, s in sectors.items():
        rows = s['daily']
        mon = hist['sectors'].get(code, {}).get('monthly', [])
        entry = {'n': s['name'], 'mkt': s['mkt'], 'code': code}
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

    # ---- 거래대금 축: 업종별 최근 5일 평균 ÷ 직전 60일 평균 (급증 배수) + 시장 내 점유율 ----
    money = {}
    kst_hm = time.strftime('%H%M', time.gmtime(time.time() + 9 * 3600))
    skip_today = today if kst_hm < '1540' else None      # 장중이면 오늘 봉(미완성) 제외
    for code, hc in hist['sectors'].items():
        if code not in sectors:
            continue
        m = money_axis(hc.get('daily') or [], skip_today)
        if m:
            m.update({'n': hc['name'], 'mkt': hc['mkt']})
            money[code] = m
    for mkt in ('KOSPI', 'KOSDAQ'):
        tot = sum(m['v5'] for m in money.values() if m['mkt'] == mkt)
        for m in money.values():
            if m['mkt'] == mkt and tot > 0:
                m['share'] = round(m['v5'] / tot * 100, 1)
    money_top = sorted(money.values(), key=lambda m: -m['x'])[:10]
    DEBUG.append('거래대금 축 %d업종 (단위: %s)' % (len(money), VAL_UNIT['src'] or '미확인'))

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
           'debug': DEBUG, 'periods': periods, 'history': years,
           'money': money, 'money_top': money_top,
           'money_note': '거래대금 = KIS 업종지수 일봉 acml_tr_pbmn(억원 환산, 단위 추정: %s). x = 최근 5일 평균 ÷ 직전 60일 평균, 🔥 = 1.8배 이상' % (VAL_UNIT['src'] or '미확인')}
    os.makedirs('public/data', exist_ok=True)
    json.dump(out, open(OUT, 'w', encoding='utf-8'), ensure_ascii=False)
    hist['hv'] = HV
    if rebuild_dw_ok:
        hist['dv'] = DV
    hist['dv_note'] = 'daily/weekly 행 = [YYYYMMDD, 종가, 거래대금(억원), 거래량(주)] · 일봉 %s~ cap %d · 주봉 %s~ cap %d' % (DAILY_START, DAILY_CAP, WEEKLY_START, WEEKLY_CAP)
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
