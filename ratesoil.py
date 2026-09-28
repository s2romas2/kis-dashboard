#!/usr/bin/env python3
# 미국채 10년물 vs 브렌트 유가 — "유가로 설명되는 적정 10년물" 추적 (팀더윤쎈 Call No.158 관점)
#   10년물(DGS10)·기대인플레(T10YIE)·실질금리(DFII10): FRED CSV (키 불필요)
#   브렌트 근월 선물(BZ=F)·10년물 당일 보정(^TNX): Yahoo Finance chart API
#   1년(252영업일) 롤링 회귀: 10년물 = a + b·ln(브렌트)  →  적정치·괴리(bp)·잔차 σ·z·상관계수
#   판정: z ≥ +2 지나치게 앞서감 / +1~+2 앞서는 편 / −1~+1 상관대로 / −1~−2 뒤처지는 편 / ≤ −2 지나치게 못 따라감
# 결과: public/data/ratesoil.json
import os, sys, json, math, time, datetime, urllib.request, ssl

OUT = os.environ.get('OUT', 'public/data/ratesoil.json')
WIN = 252
UA = {'User-Agent': 'Mozilla/5.0'}
CTX = ssl.create_default_context(); CTX.check_hostname = False; CTX.verify_mode = ssl.CERT_NONE
KST = datetime.timezone(datetime.timedelta(hours=9))
DEBUG = []
def log(s): DEBUG.append(str(s)[:200]); print(s, file=sys.stderr)

def fetch(url, timeout=40, tries=3, ua=None):
    err = None
    for i in range(tries):
        try:
            return urllib.request.urlopen(urllib.request.Request(url, headers=ua or UA), timeout=timeout, context=CTX).read()
        except Exception as e:
            err = e; time.sleep(2 * (i + 1))
    log('fetch 실패 %s %r' % (url[:70], err)); return b''

def fred(sid, start):
    out = {}
    txt = fetch('https://fred.stlouisfed.org/graph/fredgraph.csv?id=%s&cosd=%s' % (sid, start), ua={'User-Agent': 'curl/8.5.0', 'Accept': '*/*'}).decode('utf-8', 'ignore')  # FRED는 브라우저 UA 요청을 지연시킴
    for ln in txt.splitlines()[1:]:
        p = ln.split(',')
        if len(p) >= 2 and p[1] not in ('.', ''):
            try: out[p[0]] = float(p[1])
            except Exception: pass
    log('FRED %s %d개 (최근 %s)' % (sid, len(out), max(out) if out else '-'))
    return out

def yahoo(sym, rng='3y'):
    out = {}
    try:
        j = json.loads(fetch('https://query1.finance.yahoo.com/v8/finance/chart/%s?range=%s&interval=1d' % (sym, rng)).decode())
        r = j['chart']['result'][0]; ts = r['timestamp']; cl = r['indicators']['quote'][0]['close']
        for t, c in zip(ts, cl):
            if c is None: continue
            d = datetime.datetime.fromtimestamp(t, datetime.timezone.utc).astimezone(datetime.timezone(datetime.timedelta(hours=-4))).strftime('%Y-%m-%d')
            out[d] = float(c)
    except Exception as e:
        log('yahoo %s 실패 %r' % (sym, e))
    log('Yahoo %s %d개 (최근 %s)' % (sym, len(out), max(out) if out else '-'))
    return out

def ols(xs, ys):
    n = len(xs); mx = sum(xs) / n; my = sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs); sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys)); syy = sum((y - my) ** 2 for y in ys)
    if sxx <= 0 or syy <= 0: return None
    b = sxy / sxx; a = my - b * mx; r = sxy / math.sqrt(sxx * syy)
    resid = [y - (a + b * x) for x, y in zip(xs, ys)]
    sd = math.sqrt(sum(e * e for e in resid) / (n - 2))
    return a, b, r, sd

def verdict(z):
    if z is None: return ('', '')
    if z >= 2: return ('앞서감(과열)', '금리가 유가 설명치보다 지나치게 앞서감 — 유가 외 요인(AI 투자수요·재정·연준 우려) 반영, 오버슈팅 가능성')
    if z >= 1: return ('앞서는 편', '유가보다 금리가 다소 앞서감 — 추가 요인 점검')
    if z > -1: return ('상관대로', '유가와 금리가 상관관계대로 움직이는 중 — 유가만 보면 됨')
    if z > -2: return ('뒤처지는 편', '유가 상승이 금리에 덜 반영 — 따라잡기 상승 여지 또는 시장이 유가를 일시적으로 보는 중')
    return ('못 따라감(괴리)', '금리가 유가를 크게 못 따라감 — 유가 급등을 시장이 일시적으로 보거나 금리 반영 지연')

def main():
    start = (datetime.date.today() - datetime.timedelta(days=3 * 365 + 30)).isoformat()
    d10 = fred('DGS10', start); bei = fred('T10YIE', start); tips = fred('DFII10', start)
    brent = yahoo('BZ=F'); tnx = yahoo('^TNX')
    # 10년물: FRED 우선, FRED 미반영 최근 영업일은 Yahoo ^TNX로 보정
    y10 = dict(d10)
    for d, v in tnx.items():
        if d not in y10 and d10 and d > max(d10): y10[d] = round(v, 2); DEBUG.append('TNX 보정 %s %.2f' % (d, v))
    dates = sorted(set(y10) & set(brent))
    if len(dates) < WIN + 30:
        print('데이터 부족', len(dates)); sys.exit(1)
    xs = [math.log(brent[d]) for d in dates]; ys = [y10[d] for d in dates]
    series = []
    for i in range(WIN - 1, len(dates)):
        f = ols(xs[i - WIN + 1:i + 1], ys[i - WIN + 1:i + 1])
        if not f: continue
        a, b, r, sd = f
        fit = a + b * xs[i]; gap = ys[i] - fit; z = gap / sd if sd > 0 else None
        f60 = ols(xs[max(0, i - 59):i + 1], ys[max(0, i - 59):i + 1])
        series.append({'d': dates[i], 'y10': round(ys[i], 2), 'brent': round(brent[dates[i]], 2), 'fit': round(fit, 2),
                       'gap': round(gap * 100, 1), 'z': round(z, 2) if z is not None else None, 'r': round(r, 2), 'r60': round(f60[2], 2) if f60 else None,
                       'b10': round(b * math.log(1.1) * 100, 1),   # 유가 +10% 당 10년물 bp
                       'sd': round(sd * 100, 1),
                       'bei': bei.get(dates[i]), 'tips': tips.get(dates[i])})
    last = series[-1]
    v, vd = verdict(last['z'])
    # 최근 30일 판정 분포
    recent = series[-30:]
    dist = {}
    for s in recent:
        k = verdict(s['z'])[0]; dist[k] = dist.get(k, 0) + 1
    out = {'updated': datetime.datetime.now(KST).strftime('%Y-%m-%d %H:%M'), 'win': WIN,
           'latest': dict(last, verdict=v, verdict_desc=vd,
                          bei_latest=(bei[max(bei)] if bei else None), tips_latest=(tips[max(tips)] if tips else None),
                          bei_date=(max(bei) if bei else None)),
           'dist30': dist, 'legend': {
               'fit': '1년 롤링 회귀 10년물 = a + b·ln(브렌트)로 구한 유가 설명치', 'gap': '실제 − 설명치 (bp)', 'z': '괴리 ÷ 잔차 표준편차(1년)',
               'verdict': 'z ≥ +2 앞서감(과열) · +1~+2 앞서는 편 · −1~+1 상관대로 · −1~−2 뒤처지는 편 · ≤ −2 못 따라감'},
           'source': '10년물·기대인플레·실질금리 FRED(DGS10·T10YIE·DFII10), 브렌트 근월 선물 Yahoo(BZ=F), 당일 10년물 보정 ^TNX',
           'debug': DEBUG[-20:], 'series': series[-520:]}
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(out, open(OUT, 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'))
    print('완료 %s: 10y %.2f brent %.2f fit %.2f gap %+.0fbp z %+.2f r %.2f → %s' % (last['d'], last['y10'], last['brent'], last['fit'], last['gap'], last['z'], last['r'], v))

if __name__ == '__main__':
    main()
