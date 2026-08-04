#!/usr/bin/env python3
# 시장 밸류에이션(PBR) 일일 수집 — KRX 로그인 계정 사용
# - 코스피/코스닥: KRX 정보데이터시스템 (지수 PER/PBR/배당수익률 통계)
# - S&P500/나스닥100: 대표 ETF(SPY/QQQ) 보유종목 가중 PBR (Yahoo Finance, 프록시)
# 결과: public/data/valuation.json  {series:{kospi:[[날짜,PBR],...],...}, latest:{...}}
import os, json, time, datetime, urllib.request, urllib.parse, sys, re

OUT = 'public/data/valuation.json'
BACKFILL_START = os.environ.get('BACKFILL_START', '2020-01-02')  # 이력 시작일
MAX_POINTS = 6000                                                # 시리즈 최대 보관(20년+)
DEBUG = []                                                       # 실행 진단(JSON에 포함)

def dbg(msg):
    DEBUG.append(str(msg)[:300])
    print(msg, file=sys.stderr)
KRX_URL = 'http://data.krx.co.kr/comm/bldAttendant/getJsonData.cmd'
KRX_HDR = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)',
    'Referer': 'http://data.krx.co.kr/contents/MDC/MDI/mdiLoader/index.cmd?menuId=MDC0201060103',
}

def load_prev():
    try:
        return json.load(open(OUT, encoding='utf-8'))
    except Exception:
        return {}

def tofloat(v):
    try:
        f = float(str(v).replace(',', '').strip())
        return f if f > 0 else None
    except Exception:
        return None

def krx_series(start, today, series):
    """KRX 개별지수 PER/PBR API 직접 호출 (MDCSTAT00702, 730일 청크)
    코스피=indTpCd 1/001, 코스닥=2/001. PBR 필드=WT_STKPRC_NETASST_RTO"""
    url = 'https://data.krx.co.kr/comm/bldAttendant/getJsonData.cmd'
    hdr = {'User-Agent': 'Mozilla/5.0',
           'Referer': 'https://data.krx.co.kr/contents/MDC/MDI/outerLoader/index.cmd',
           'X-Requested-With': 'XMLHttpRequest'}
    for key, (t1, t2) in (('kospi', ('1', '001')), ('kosdaq', ('2', '001'))):
        pairs = []
        s_d = start
        while s_d <= today:
            e_d = min(s_d + datetime.timedelta(days=729), today)
            data = urllib.parse.urlencode({
                'bld': 'dbms/MDC/STAT/standard/MDCSTAT00702', 'locale': 'ko_KR',
                'indTpCd': t1, 'indTpCd2': t2,
                'strtDd': s_d.strftime('%Y%m%d'), 'endDd': e_d.strftime('%Y%m%d'),
                'share': '2', 'money': '3', 'csvxls_isNo': 'false'}).encode()
            try:
                req = urllib.request.Request(url, data=data, headers=hdr)
                body = urllib.request.urlopen(req, timeout=30).read().decode('utf-8', 'ignore')
                rows = (json.loads(body).get('output')) or []
                if not rows:
                    dbg('KRX %s %s~%s 빈 응답: %r' % (key, s_d, e_d, body[:160]))
                for it in rows:
                    dd = (it.get('TRD_DD') or '').replace('/', '-')
                    v = tofloat(it.get('WT_STKPRC_NETASST_RTO'))
                    if len(dd) == 10 and v:
                        pairs.append([dd, round(v, 2)])
            except Exception as ex:
                dbg('KRX %s 청크 실패: %r' % (key, ex))
            time.sleep(1)
            s_d = e_d + datetime.timedelta(days=1)
        if len(pairs) > 30:
            series[key] = sorted(pairs)
        dbg('KRX %s: %d포인트' % (key, len(pairs)))

def naver_candles(code, n=90):
    """네이버 fchart — 지수 일봉 종가 (XML, 해외 접속 허용)"""
    req = urllib.request.Request(
        'https://fchart.stock.naver.com/sise.nhn?symbol=%s&timeframe=day&count=%d&requestType=0' % (code, n),
        headers={'User-Agent': 'Mozilla/5.0'})
    x = urllib.request.urlopen(req, timeout=20).read().decode('euc-kr', 'ignore')
    out = {}
    for item in re.findall(r'data="([^"]+)"', x):
        parts = item.split('|')
        if len(parts) >= 5 and re.fullmatch(r'\d{8}', parts[0]):
            v = tofloat(parts[4])
            if v:
                out['%s-%s-%s' % (parts[0][:4], parts[0][4:6], parts[0][6:8])] = v
    return out

def kr_estimate(series, anchor):
    """마지막 KRX 공식값(anchor) 이후를 지수 등락률로 매일 자동 추정
    (순자산·이익은 분기 단위로만 변해 지수 변동 스케일링이 근사적으로 정확)"""
    for key, code in (('kospi', 'KOSPI'), ('kosdaq', 'KOSDAQ')):
        a = (anchor or {}).get(key)
        if not a:
            continue
        try:
            candles = naver_candles(code)
        except Exception as e:
            dbg('캔들 %s 실패: %r' % (code, e))
            continue
        if a not in candles:
            dbg('%s anchor %s 종가 없음 (캔들 %d개: %s~%s)' % (
                key, a, len(candles), min(candles) if candles else '-', max(candles) if candles else '-'))
            continue
        base = candles[a]
        for skey in (key, key + '_per'):
            s2 = series.get(skey) or []
            official = [p for p in s2 if p[0] <= a]
            if not official:
                continue
            av = official[-1][1]
            est = [[dt, round(av * c / base, 2)] for dt, c in sorted(candles.items()) if dt > a]
            series[skey] = official + est
            if est:
                dbg('%s: 추정 %d포인트 (anchor %s=%.2f)' % (skey, len(est), a, av))

def multpl_series(path, lo, hi):
    """multpl.com 표 파싱 (추정치 † 및 &#x2002; 구분자 대응) — 2020년부터"""
    MONTHS = {'Jan':1,'Feb':2,'Mar':3,'Apr':4,'May':5,'Jun':6,'Jul':7,'Aug':8,'Sep':9,'Oct':10,'Nov':11,'Dec':12}
    pat = r'<td>\s*([A-Z][a-z]{2})\s+(\d{1,2}),\s*(\d{4})\s*</td>\s*<td>\s*(?:<abbr[^>]*>[^<]*</abbr>|&#x2002;)?\s*([\d]+\.?[\d]*)'
    try:
        req = urllib.request.Request('https://www.multpl.com/%s' % path,
                                     headers={'User-Agent': 'Mozilla/5.0'})
        h = urllib.request.urlopen(req, timeout=25).read().decode('utf-8', 'ignore')
        out = []
        for mo, dd, yy, val in re.findall(pat, h):
            if mo not in MONTHS or not val:
                continue
            date = '%04d-%02d-%02d' % (int(yy), MONTHS[mo], int(dd))
            if date >= BACKFILL_START and lo < float(val) < hi:
                out.append([date, float(val)])
        out = sorted(dict(out).items())
        dbg('multpl %s: %d건' % (path.split('/')[0], len(out)))
        return [[d, v] for d, v in out]
    except Exception as e:
        dbg('multpl %s 실패: %r' % (path, e))
        return []

def us_pbr():
    """QQQ 보유종목 가중 PBR·PER (나스닥100 프록시). 야후는 역수로 제공 → 반전."""
    out = {}
    try:
        import yfinance as yf
    except Exception as e:
        dbg('yfinance 없음: %s' % e)
        return out
    def pick(eh, word):
        v = None
        if hasattr(eh, 'index'):
            for idx in list(eh.index):
                if word in str(idx).lower():
                    v = float(eh.loc[idx].iloc[0]); break
        elif isinstance(eh, dict):
            for kk, vv in eh.items():
                if word in str(kk).lower():
                    v = float(vv); break
        return tofloat(v)
    for key, tk in (('nasdaq100', 'QQQ'),):
        try:
            eh = yf.Ticker(tk).funds_data.equity_holdings
            pb, pe = pick(eh, 'book'), pick(eh, 'earnings')
            if pb and 0 < pb < 1:
                pb = 1.0 / pb  # 역수(북/프라이스) 반전
            if pe and 0 < pe < 1:
                pe = 1.0 / pe
            if pb and 1 < pb < 50:
                out[key] = round(pb, 2)
            if pe and 5 < pe < 100:
                out[key + '_per'] = round(pe, 2)
            dbg('%s PBR=%s PER=%s' % (tk, out.get(key), out.get(key + '_per')))
        except Exception as e:
            dbg('US 지표 실패 %s: %r' % (tk, e))
    return out

def main():
    prev = load_prev()
    series = prev.get('series') or {}
    for k in ('kospi', 'kosdaq', 'sp500', 'nasdaq100', 'sp500_per', 'nasdaq100_per'):
        series.setdefault(k, [])
    have = {k: set(d for d, _ in series[k]) for k in series}
    today = datetime.date.today()

    # ── 한국: KRX 직접 수집 시도(해외 IP 차단 시 실패) → 실패하면 네이버로 당일 값 축적 ──
    start = datetime.date.fromisoformat(BACKFILL_START)
    krx_series(start, today, series)
    kr_estimate(series, prev.get('krAnchor') or {})

    # ── 미국: S&P500 = multpl 이력(PBR 분기·PER 월별), 나스닥100 = QQQ 매일 축적 ──
    sp = multpl_series('s-p-500-price-to-book/table/by-quarter', 0.5, 20)
    if sp:
        series['sp500'] = sp
    spe = multpl_series('s-p-500-pe-ratio/table/by-month', 5, 100)
    if spe:
        series['sp500_per'] = spe
    us = us_pbr()
    ds = today.strftime('%Y-%m-%d')
    for k, v in us.items():
        have_k = set(d for d, _ in series[k])
        if ds not in have_k:
            series[k].append([ds, v])
    # 과거 오염값 정리(비정상 저값 제거)
    for k in ('sp500', 'nasdaq100', 'sp500_per', 'nasdaq100_per'):
        series[k] = [p for p in series[k] if p[1] and p[1] > 1]

    latest = {}
    for k in series:
        series[k] = sorted(series[k])[-MAX_POINTS:]
        if series[k]:
            vals = [v for _, v in series[k]]
            latest[k] = {'date': series[k][-1][0], 'pbr': series[k][-1][1],
                         'min': round(min(vals), 2), 'max': round(max(vals), 2),
                         'avg': round(sum(vals) / len(vals), 2)}

    out = {'updated': time.strftime('%Y-%m-%d %H:%M'), 'series': series, 'latest': latest,
           'krAnchor': prev.get('krAnchor') or {},
           'debug': DEBUG[-25:], 'note': '코스피·코스닥: KRX 지수 PBR(2020~, 일별) / S&P500: multpl P/B 분기·PER 월별(2020~) / 나스닥100: QQQ 보유종목 가중 PBR·PER(프록시, 2026-08부터 일별 축적)'}
    os.makedirs('public/data', exist_ok=True)
    with open(OUT, 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False)
    print('저장 완료:', {k: latest[k]['pbr'] for k in latest}, file=sys.stderr)

if __name__ == '__main__':
    main()
