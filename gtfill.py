#!/usr/bin/env python3
# 구글트렌드 결측 채우기 — 매시간 소량 시도 (429 차단 대응: 실행 IP가 매번 바뀜)
# 우선순위: 미국 키워드 → 한국 섹터 → 뷰티 브랜드(KR 비교→US 비교→제품)
import json, time, os, sys

TRENDS = 'public/data/trends.json'
BEAUTY = 'public/data/beauty.json'
MAX_PAYLOADS = int(os.environ.get('MAX_PAYLOADS', '12'))
TIME_LIMIT = 12 * 60
START = time.time()

def load(p, default):
    try:
        return json.load(open(p, encoding='utf-8'))
    except Exception:
        return default

tk = load('public/trendkeys.json', {})
bk = load('public/beautykeys.json', {})
T = load(TRENDS, {})
B = load(BEAUTY, {})
T.setdefault('google', {}); T.setdefault('datalab', {})
B.setdefault('gt', {}); B['gt'].setdefault('KR', {}); B['gt'].setdefault('US', {})

jobs = []  # (kind, geo, kws, meta)
for batch in tk.get('google', []):
    if any(k not in T['google'] for k in batch):
        jobs.append(('us_google', 'US', batch, None))
for sec, themes in tk.get('datalab', {}).items():
    if sec not in T['datalab']:
        reps = {t: kws[0] for t, kws in list(themes.items())[:5]}
        jobs.append(('kr_sector', 'KR', list(reps.values()), (sec, reps)))
for big, mids in bk.items():
    for mid, brands in mids.items():
        names = list(brands.keys())
        for i in range(0, len(names), 5):
            chunk = names[i:i + 5]
            if any(b not in B['gt']['KR'] for b in chunk):
                jobs.append(('bt_kr', 'KR', chunk, None))
        us = [v['us'] for v in brands.values() if v.get('us')]
        for i in range(0, len(us), 5):
            chunk = us[i:i + 5]
            if any(k not in B['gt']['US'] for k in chunk):
                jobs.append(('bt_us', 'US', chunk, None))
for big, mids in bk.items():
    for mid, brands in mids.items():
        for b, v in brands.items():
            kws = ([b] + (v.get('products') or []))[:5]
            if len(kws) > 1 and any(k not in B['gt']['KR'] for k in kws[1:]):
                jobs.append(('bt_kr', 'KR', kws, None))

print('결측 작업 %d개' % len(jobs), file=sys.stderr)
done = 0
changedT = changedB = False
try:
    from pytrends.request import TrendReq
    pt = TrendReq(hl='ko', tz=-540)
    for kind, geo, kws, meta in jobs:
        if done >= MAX_PAYLOADS or time.time() - START > TIME_LIMIT:
            break
        ok = False
        for attempt in range(2):
            try:
                pt.build_payload(kws, timeframe='today 5-y', geo=geo)
                df = pt.interest_over_time()
                ser = {k: [[d.strftime('%Y-%m-%d'), int(v)] for d, v in df[k].items()]
                       for k in kws if k in df.columns}
                if ser:
                    ok = True
                    if kind == 'us_google':
                        T['google'].update(ser); changedT = True
                    elif kind == 'kr_sector':
                        sec, reps = meta
                        T['datalab'][sec] = {t: ser[kw] for t, kw in reps.items() if kw in ser}
                        changedT = True
                    elif kind == 'bt_kr':
                        B['gt']['KR'].update(ser); changedB = True
                    else:
                        B['gt']['US'].update(ser); changedB = True
                    done += 1
                time.sleep(10)
                break
            except Exception:
                time.sleep(25)
        print('%s %s %s' % (kind, kws[0], 'OK' if ok else 'FAIL'), file=sys.stderr)
except Exception as e:
    print('pytrends 오류: %r' % e, file=sys.stderr)

if changedT:
    T['updated'] = time.strftime('%Y-%m-%d %H:%M')
    json.dump(T, open(TRENDS, 'w', encoding='utf-8'), ensure_ascii=False)
if changedB:
    B['updated'] = time.strftime('%Y-%m-%d %H:%M')
    json.dump(B, open(BEAUTY, 'w', encoding='utf-8'), ensure_ascii=False)
print('이번 실행 성공 %d개' % done)
