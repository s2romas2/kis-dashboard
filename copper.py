#!/usr/bin/env python3
# 구리 가격 추적 + 광통신 상관 계산 (Yahoo Finance 차트 API, 키 불필요)
# 결과: public/data/copper.json
#   {updated, spot:{...}, stats:{...}, hist:{d:[],cu:[],opt:[]}, corr:[...], rel:[...], debug:[]}
# ※ 구리 가격은 "광 전환의 선행지표"가 아니라 전력 인프라·원자재 사이클 게이지로 쓸 것.
#    실제 상관은 시장 전체 상관보다도 낮다는 점을 corr에 실측으로 남긴다.
import os, sys, json, time, math, datetime, urllib.request, urllib.parse
import statistics as st

OUT = os.environ.get('OUT', 'public/data/copper.json')
UA = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126 Safari/537.36'}
Y = 'https://query1.finance.yahoo.com/v8/finance/chart/%s?range=%s&interval=1d'
DEBUG = []

# 광통신 바스켓 — 미국 상장 순수 광부품/광전송 4사 동일가중
BASKET = [('LITE', '루멘텀'), ('COHR', '코히런트'), ('CIEN', '시에나'), ('GLW', '코닝')]
# 상관 비교 대상 (k: 표시명, t: 티커, ref: 비교용 기준선인지)
CORR = [('루멘텀', 'LITE', 0), ('코히런트', 'COHR', 0), ('시에나', 'CIEN', 0), ('코닝', 'GLW', 0),
        ('브로드컴', 'AVGO', 0), ('엔비디아', 'NVDA', 0),
        ('대한광통신', '010170.KQ', 0), ('RF머트리얼즈', '327260.KQ', 0),
        ('S&P500 (시장 기준선)', '^GSPC', 1), ('금 (안전자산 기준선)', 'GC=F', 1),
        ('Freeport (구리광산 기준선)', 'FCX', 1)]
# 함께 보는 원자재·매크로
REL = [('구리 COMEX 선물', 'HG=F', 'USD/lb'), ('알루미늄', 'ALI=F', 'USD/t'),
       ('은', 'SI=F', 'USD/oz'), ('WTI 원유', 'CL=F', 'USD/bbl'),
       ('미국 10년물', '^TNX', '%'), ('원/달러', 'KRW=X', '원')]

def ser(sym, rng='3y'):
    u = Y % (urllib.parse.quote(sym), rng)
    j = json.loads(urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=30).read().decode())
    r = j['chart']['result'][0]
    ts, cl = r['timestamp'], r['indicators']['quote'][0]['close']
    s = {datetime.datetime.utcfromtimestamp(t).strftime('%Y-%m-%d'): c
         for t, c in zip(ts, cl) if c is not None}
    return s, (r.get('meta') or {})

def logret(s):
    ks = sorted(s)
    return {ks[i]: math.log(s[ks[i]] / s[ks[i-1]]) for i in range(1, len(ks))
            if s[ks[i-1]] and s[ks[i-1]] > 0 and s[ks[i]] > 0}

def pearson(a, b, days=None):
    ks = sorted(set(a) & set(b))
    if days:
        ks = ks[-days:]
    if len(ks) < 60:
        return None
    x = [a[k] for k in ks]; y = [b[k] for k in ks]
    mx, my = st.mean(x), st.mean(y)
    num = sum((xi - mx) * (yi - my) for xi, yi in zip(x, y))
    den = math.sqrt(sum((xi - mx) ** 2 for xi in x) * sum((yi - my) ** 2 for yi in y))
    return round(num / den, 3) if den else None

def main():
    try:
        cu, meta = ser('HG=F')
    except Exception as e:
        DEBUG.append('구리 시세 실패: %s' % repr(e)[:80])
        prev = {}
        try:
            prev = json.load(open(OUT, encoding='utf-8'))
        except Exception:
            pass
        if prev:                       # 빈 결과로 덮어쓰지 않음
            prev['debug'] = DEBUG
            json.dump(prev, open(OUT, 'w', encoding='utf-8'), ensure_ascii=False)
        return
    ks = sorted(cu)
    cur = cu[ks[-1]]
    prev_px = cu[ks[-2]] if len(ks) > 1 else cur
    lo, hi = min(cu.values()), max(cu.values())

    def back(n):
        return cu[ks[max(0, len(ks) - 1 - n)]]

    spot = {'px': round(cur, 4), 'unit': 'USD/lb', 'ex': meta.get('fullExchangeName', 'COMEX'),
            'name': meta.get('shortName', 'Copper'),
            'chg': round(cur - prev_px, 4),
            'chgp': round((cur / prev_px - 1) * 100, 2) if prev_px else None,
            'asof': ks[-1]}
    stats = {'d20': round((cur / back(20) - 1) * 100, 1), 'm3': round((cur / back(62) - 1) * 100, 1),
             'm6': round((cur / back(125) - 1) * 100, 1), 'y1': round((cur / back(250) - 1) * 100, 1),
             'y3': round((cur / cu[ks[0]] - 1) * 100, 1),
             'lo3': round(lo, 3), 'hi3': round(hi, 3),
             'pos': round((cur - lo) / (hi - lo) * 100) if hi > lo else None}

    # 광통신 바스켓 — 각 종목을 3년 전 100으로 정규화한 뒤 동일가중 평균
    norm, got = [], []
    for tk, nm in BASKET:
        try:
            s, _ = ser(tk)
            b = s[sorted(s)[0]]
            norm.append({k: v / b * 100 for k, v in s.items()}); got.append(nm)
        except Exception as e:
            DEBUG.append('%s 실패 %s' % (tk, repr(e)[:50]))
        time.sleep(0.3)
    days = sorted(set.intersection(*[set(n) for n in norm])) if norm else []
    optidx = {d: sum(n[d] for n in norm) / len(norm) for d in days}
    cub = cu[ks[0]]
    cuidx = {k: v / cub * 100 for k, v in cu.items()}
    # 주 1회로 솎아 파일 크기 축소
    hd = [d for i, d in enumerate(days) if i % 5 == 0 or d == days[-1]]
    hist = {'d': hd,
            'cu': [round(cuidx.get(d, cuidx[min(cuidx, key=lambda x: abs((datetime.date.fromisoformat(x) - datetime.date.fromisoformat(d)).days))]), 1) for d in hd],
            'opt': [round(optidx[d], 1) for d in hd],
            'basket': got}

    # 상관계수 — 구리 일간 로그수익률 대비
    cur_r = logret(cu)
    corr = []
    for nm, tk, ref in CORR:
        try:
            s, _ = ser(tk)
            r = logret(s)
            corr.append({'n': nm, 't': tk, 'ref': ref,
                         'r1': pearson(cur_r, r, 250), 'r3': pearson(cur_r, r)})
        except Exception as e:
            DEBUG.append('corr %s 실패 %s' % (tk, repr(e)[:40]))
        time.sleep(0.3)

    # 함께 보는 지표
    rel = []
    for nm, tk, un in REL:
        try:
            s, m = ser(tk, '1y')
            k2 = sorted(s); c = s[k2[-1]]; p = s[k2[-2]] if len(k2) > 1 else c
            rel.append({'n': nm, 't': tk, 'u': un, 'px': round(c, 3),
                        'chgp': round((c / p - 1) * 100, 2) if p else None,
                        'y1': round((c / s[k2[max(0, len(k2) - 250)]] - 1) * 100, 1)})
        except Exception as e:
            DEBUG.append('rel %s 실패 %s' % (tk, repr(e)[:40]))
        time.sleep(0.3)

    DEBUG.append('구리 %d일 · 바스켓 %d사 · 상관 %d건 · 관련지표 %d건' % (len(ks), len(got), len(corr), len(rel)))
    out = {'updated': time.strftime('%Y-%m-%d %H:%M'), 'spot': spot, 'stats': stats,
           'hist': hist, 'corr': corr, 'rel': rel, 'debug': DEBUG}
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(out, open(OUT, 'w', encoding='utf-8'), ensure_ascii=False)
    print('저장 %s — 구리 $%.3f (%s)' % (OUT, cur, ks[-1]), file=sys.stderr)

if __name__ == '__main__':
    main()
