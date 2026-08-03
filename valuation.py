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

def naver_kr():
    """네이버 금융 지수 페이지에서 코스피·코스닥 당일 PBR (KRX 공식값 기반, 해외 접속 허용)"""
    out = {}
    for key, code in (('kospi', 'KOSPI'), ('kosdaq', 'KOSDAQ')):
        try:
            req = urllib.request.Request('https://finance.naver.com/sise/sise_index.naver?code=' + code,
                                         headers={'User-Agent': 'Mozilla/5.0'})
            h = urllib.request.urlopen(req, timeout=20).read().decode('euc-kr', 'ignore')
            m = re.search(r'PBR[^0-9]{0,20}([\d]+\.[\d]+)', h)
            if m:
                v = float(m.group(1))
                if 0.2 < v < 6:
                    out[key] = round(v, 2)
                else:
                    dbg('naver %s 이상값 %s' % (key, v))
            else:
                dbg('naver %s PBR 미발견, 응답 %d바이트' % (key, len(h)))
        except Exception as e:
            dbg('naver %s 실패: %r' % (key, e))
    return out

def sp500_multpl():
    """S&P500 월별 P/B 장기 이력 (multpl.com) — 2020년부터"""
    MONTHS = {'Jan':1,'Feb':2,'Mar':3,'Apr':4,'May':5,'Jun':6,'Jul':7,'Aug':8,'Sep':9,'Oct':10,'Nov':11,'Dec':12}
    try:
        req = urllib.request.Request('https://www.multpl.com/s-p-500-price-to-book/table/by-month',
                                     headers={'User-Agent': 'Mozilla/5.0'})
        h = urllib.request.urlopen(req, timeout=25).read().decode('utf-8', 'ignore')
        out = []
        pats = [
            r'([A-Z][a-z]{2})\s+(\d{1,2}),\s*(\d{4})\s*</td>\s*<td[^>]*>\s*(?:<[^>]*>\s*)*([\d]+\.[\d]+)',
            r'>\s*([A-Z][a-z]{2})\s+(\d{1,2}),\s*(\d{4})[\s\S]{0,120}?([\d]+\.[\d]+)',
        ]
        for pi, pat in enumerate(pats):
            n = 0
            for mo, dd, yy, val in re.findall(pat, h):
                if mo not in MONTHS:
                    continue
                date = '%04d-%02d-%02d' % (int(yy), MONTHS[mo], int(dd))
                if date >= BACKFILL_START and 0.5 < float(val) < 20:
                    out.append([date, float(val)])
                    n += 1
            dbg('multpl 패턴%d: %d건' % (pi, n))
        out = sorted(dict(out).items())
        if not out:
            m0 = re.search(r'[A-Z][a-z]{2}\s+\d{1,2},\s*\d{4}', h)
            dbg('multpl 매칭 0건, 샘플: %r' % (h[max(0, m0.start() - 120):m0.start() + 250] if m0 else h[:250]))
        return [[d, v] for d, v in out]
    except Exception as e:
        dbg('multpl 실패: %r' % e)
        return []

def us_pbr():
    """QQQ 보유종목 가중 PBR (나스닥100 프록시). 값 범위 검증(1~50배) 포함."""
    out = {}
    try:
        import yfinance as yf
    except Exception as e:
        dbg('yfinance 없음: %s' % e)
        return out
    for key, tk in (('nasdaq100', 'QQQ'),):
        pb = None
        try:
            t = yf.Ticker(tk)
            try:
                eh = t.funds_data.equity_holdings
                dbg('%s eh: %.250r' % (tk, eh))
                if hasattr(eh, 'index'):  # DataFrame: 지표명이 index 또는 컬럼
                    for idx in list(eh.index):
                        if 'book' in str(idx).lower():
                            pb = float(eh.loc[idx].iloc[0]); break
                    if pb is None:
                        for col in list(getattr(eh, 'columns', [])):
                            if 'book' in str(col).lower():
                                pb = float(eh[col].iloc[0]); break
                elif isinstance(eh, dict):
                    for kk, vv in eh.items():
                        if 'book' in str(kk).lower():
                            pb = float(vv); break
            except Exception as ex:
                dbg('funds_data 실패 %s: %r' % (tk, ex))
            pb = tofloat(pb)
            if pb and 0 < pb < 1:
                pb = round(1.0 / pb, 2)  # 야후가 역수(북/프라이스)로 주는 경우
            if pb and not (1 < pb < 50):
                dbg('%s PBR 이상값 %s 폐기' % (tk, pb))
                pb = None
            if pb:
                out[key] = round(pb, 2)
        except Exception as e:
            dbg('US PBR 실패 %s: %r' % (tk, e))
    return out

def main():
    prev = load_prev()
    series = prev.get('series') or {}
    for k in ('kospi', 'kosdaq', 'sp500', 'nasdaq100'):
        series.setdefault(k, [])
    have = {k: set(d for d, _ in series[k]) for k in series}
    today = datetime.date.today()

    # ── 한국: KRX 직접 수집 시도(해외 IP 차단 시 실패) → 실패하면 네이버로 당일 값 축적 ──
    start = datetime.date.fromisoformat(BACKFILL_START)
    krx_series(start, today, series)
    ds_today = today.strftime('%Y-%m-%d')
    if not any(d == ds_today for d, _ in series['kospi']):
        nv = naver_kr()
        for k, v in nv.items():
            if not any(d == ds_today for d, _ in series[k]):
                series[k].append([ds_today, v])
        dbg('naver 당일 보충: %s' % nv)

    # ── 미국: S&P500 = multpl 월별 장기 이력(현재월 포함), 나스닥100 = QQQ 매일 축적 ──
    sp = sp500_multpl()
    if sp:
        series['sp500'] = sp
    dbg('multpl: %d포인트' % len(sp))
    us = us_pbr()
    ds = today.strftime('%Y-%m-%d')
    for k, v in us.items():
        have_k = set(d for d, _ in series[k])
        if ds not in have_k:
            series[k].append([ds, v])
    dbg('US PBR: %s' % us)
    # 과거 오염값 정리(비정상 저값 제거)
    for k in ('sp500', 'nasdaq100'):
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
           'debug': DEBUG[-25:], 'note': '코스피·코스닥: KRX 지수 PBR(2020~, 일별) / S&P500: multpl 월별 P/B(2020~) / 나스닥100: QQQ 보유종목 가중 PBR(프록시, 일별 축적)'}
    os.makedirs('public/data', exist_ok=True)
    with open(OUT, 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False)
    print('저장 완료:', {k: latest[k]['pbr'] for k in latest}, file=sys.stderr)

if __name__ == '__main__':
    main()
