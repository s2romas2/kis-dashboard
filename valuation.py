#!/usr/bin/env python3
# 시장 밸류에이션(PBR) 일일 수집
# - 코스피/코스닥: KRX 정보데이터시스템 (지수 PER/PBR/배당수익률 통계)
# - S&P500/나스닥100: 대표 ETF(SPY/QQQ) 보유종목 가중 PBR (Yahoo Finance, 프록시)
# 결과: public/data/valuation.json  {series:{kospi:[[날짜,PBR],...],...}, latest:{...}}
import os, json, time, datetime, urllib.request, urllib.parse, sys

OUT = 'public/data/valuation.json'
BACKFILL_DAYS = int(os.environ.get('BACKFILL_DAYS', '400'))   # 최초 백필 범위(달력일)
MAX_POINTS = 800                                              # 시리즈 최대 보관 개수(~3년)
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

def krx_post(payload):
    data = urllib.parse.urlencode(payload).encode()
    req = urllib.request.Request(KRX_URL, data=data, headers=KRX_HDR)
    with urllib.request.urlopen(req, timeout=25) as r:
        return json.loads(r.read().decode('utf-8'))

def krx_day(ymd):
    """특정일 전체지수 PER/PBR — 코스피·코스닥 행만 추출"""
    for bld in ('dbms/MDC/STAT/standard/MDCSTAT00701', 'dbms/MDC/STAT/standard/MDCSTAT00702'):
        try:
            j = krx_post({'bld': bld, 'locale': 'ko_KR', 'searchType': '1',
                          'trdDd': ymd, 'idxIndMidclssCd': '01', 'money': '1', 'csvxls_isNo': 'false'})
            rows = j.get('output') or j.get('OutBlock_1') or j.get('block1') or []
            res = {}
            for it in rows:
                nm = (it.get('IDX_NM') or it.get('IDX_IND_NM') or '').strip()
                pbr = tofloat(it.get('PBR'))
                per = tofloat(it.get('PER'))
                if pbr is None:
                    continue
                if nm == '코스피':
                    res['kospi'] = {'pbr': pbr, 'per': per}
                elif nm == '코스닥':
                    res['kosdaq'] = {'pbr': pbr, 'per': per}
            if res:
                return res, bld
        except Exception as e:
            print('KRX %s %s 실패: %s' % (bld, ymd, e), file=sys.stderr)
    return {}, None

def us_pbr():
    """SPY/QQQ 보유종목 가중 PBR (프록시). 실패해도 나머지는 진행."""
    out = {}
    try:
        import yfinance as yf
    except Exception as e:
        print('yfinance 없음:', e, file=sys.stderr)
        return out
    for key, tk in (('sp500', 'SPY'), ('nasdaq100', 'QQQ')):
        try:
            t = yf.Ticker(tk)
            pb = None
            try:  # 신버전: funds_data
                fd = t.funds_data
                eh = getattr(fd, 'equity_holdings', None)
                if eh is not None:
                    if hasattr(eh, 'loc'):  # DataFrame
                        for idx in ('priceToBook', 'Price/Book'):
                            try:
                                pb = float(eh.loc[idx].iloc[0]); break
                            except Exception:
                                pass
                    elif isinstance(eh, dict):
                        pb = eh.get('priceToBook')
            except Exception:
                pass
            if not pb:  # 구버전/대체 경로
                info = getattr(t, 'info', {}) or {}
                pb = info.get('priceToBook')
            pb = tofloat(pb)
            if pb:
                out[key] = round(pb, 2)
            time.sleep(1)
        except Exception as e:
            print('US PBR 실패 %s: %s' % (tk, e), file=sys.stderr)
    return out

def main():
    prev = load_prev()
    series = prev.get('series') or {}
    for k in ('kospi', 'kosdaq', 'sp500', 'nasdaq100'):
        series.setdefault(k, [])
    have = {k: set(d for d, _ in series[k]) for k in series}
    today = datetime.date.today()

    # ── 한국: 백필(비어있을 때) 또는 최근 7일 증분 ──
    need_backfill = len(series['kospi']) < 30
    span = BACKFILL_DAYS if need_backfill else 7
    used_bld = None
    got = 0
    for i in range(span, -1, -1):
        d = today - datetime.timedelta(days=i)
        if d.weekday() >= 5:
            continue
        ds = d.strftime('%Y-%m-%d')
        if ds in have['kospi']:
            continue
        res, bld = krx_day(d.strftime('%Y%m%d'))
        used_bld = used_bld or bld
        for k in ('kospi', 'kosdaq'):
            if k in res:
                series[k].append([ds, res[k]['pbr']])
                have[k].add(ds)
                got += 1
        time.sleep(0.35)
    print('KRX 수집 %d포인트 (bld=%s)' % (got, used_bld), file=sys.stderr)

    # ── 미국: 오늘 값 1포인트 (이력은 매일 쌓임) ──
    us = us_pbr()
    ds = today.strftime('%Y-%m-%d')
    for k, v in us.items():
        if ds not in have[k]:
            series[k].append([ds, v])
    print('US PBR:', us, file=sys.stderr)

    latest = {}
    for k in series:
        series[k] = sorted(series[k])[-MAX_POINTS:]
        if series[k]:
            vals = [v for _, v in series[k]]
            latest[k] = {'date': series[k][-1][0], 'pbr': series[k][-1][1],
                         'min': round(min(vals), 2), 'max': round(max(vals), 2),
                         'avg': round(sum(vals) / len(vals), 2)}

    out = {'updated': time.strftime('%Y-%m-%d %H:%M'), 'series': series, 'latest': latest,
           'note': '코스피·코스닥: KRX 지수 PBR / S&P500·나스닥100: SPY·QQQ 보유종목 가중 PBR(프록시)'}
    os.makedirs('public/data', exist_ok=True)
    with open(OUT, 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False)
    print('저장 완료:', {k: latest[k]['pbr'] for k in latest}, file=sys.stderr)

if __name__ == '__main__':
    main()
