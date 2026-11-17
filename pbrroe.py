#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# 전 상장사 PBR–ROE 판정 — 외부 호출 없음(저장된 파일만 읽음)
#   입력: public/data/finall.json (hege.py가 DART 주요계정에서 뽑은 순이익·자본), stockvals.json(매일 시총), wics71map.json(WICS 소분류), hege.json(국면)
#   출력: public/data/pbrroe.json
# 관점(사용자 합의 11/17): 저PBR이어도 ROE가 함께 낮으면 의미 없음 / ROE가 높은데 저PBR이면 저평가 후보 /
#   '적정 ROE + 저PBR'은 칸으로 자르지 않고 같은 업종의 ROE–PBR 관계선에서 얼마나 떨어져 있는지(괴리율)로 본다.
#   PBR ÷ ROE = PER 이라 최근 4분기 ROE만 쓰면 저PER 체크와 같아지므로 ROE는 최근 3개 사업연도 + 최근 4분기의 평균(평균 ROE)을 쓴다.
import json, os, statistics, datetime

D = 'public/data/'
OUT = D + 'pbrroe.json'
TH = {'hi': 15.0, 'lo': 8.0, 'gap': 20.0, 'min_n': 10, 'coe': 10.0}
FIN_SEC = ('은행', '보험', '증권', '카드', '금융', '캐피탈', '저축')      # 금융 업종: 부채비율 경고를 붙이지 않음(레버리지가 사업 구조)
KST = datetime.timezone(datetime.timedelta(hours=9))

def load(name, default=None):
    try: return json.load(open(D + name, encoding='utf-8'))
    except Exception: return default
def rnd(v, n=2): return None if v is None else round(v, n)

def theil(pts):
    """강건 직선(기울기 = 두 점씩 이은 기울기들의 중앙값). y = a + b·x → (a, b, n). 표본이 크면 균등 추출해 계산량을 제한"""
    n = len(pts)
    if n < 5: return None
    if n > 400:
        step = n / 400.0; pts = [pts[int(i * step)] for i in range(400)]
    m = len(pts)
    sl = [(pts[j][1] - pts[i][1]) / (pts[j][0] - pts[i][0]) for i in range(m) for j in range(i + 1, m) if abs(pts[j][0] - pts[i][0]) > 0.5]
    if len(sl) < 5: return None
    b = statistics.median(sl); a = statistics.median([y - b * x for x, y in pts])
    return [round(a, 3), round(b, 4), n]

def main():
    fin = load('finall.json') or {}
    rows = fin.get('rows') or {}
    if len(rows) < 300:
        print('finall.json 없음/부족(%d) — 건너뜀' % len(rows)); return
    sv = load('stockvals.json') or {}; svm = sv.get('map') or {}
    wm = (load('wics71map.json') or {}).get('map') or {}
    sec_of = {c: s for s, cs in wm.items() for c in cs}
    hg = {r['c']: r for r in (load('hege.json') or {}).get('rows') or []}
    S = {}
    for c, f in rows.items():
        v = svm.get(c) or []
        cap = v[2] if len(v) > 2 and v[2] else (hg.get(c) or {}).get('cap')
        eq = f.get('eq')
        if not cap or not eq or eq <= 0: continue
        hist = [[y, rnd(ni / e * 100, 1)] for y, ni, e in f.get('yr') or [] if e and e > 0]
        roe_t = rnd(f['ni'] / eq * 100, 1) if f.get('ni') is not None else None
        vals = [x[1] for x in hist] + ([roe_t] if roe_t is not None else [])
        if not vals: continue
        S[c] = {'c': c, 'n': f.get('n') or (hg.get(c) or {}).get('n') or c, 'sec': sec_of.get(c) or f.get('sec') or '기타', 'cap': cap,
                'pbr': rnd(cap / eq), 'roe_t': roe_t, 'hist': hist, 'roe_n': rnd(sum(vals) / len(vals), 1), 'roe_min': rnd(min(vals), 1),
                'debt': rnd(f['li'] / eq * 100, 0) if f.get('li') is not None else None, 'fs': f.get('fs'), 'q': f.get('q'),
                'ph': (hg.get(c) or {}).get('ph'), 'e': bool((hg.get(c) or {}).get('new1') or (hg.get(c) or {}).get('entry2'))}
    ok = lambda r, k: r.get(k) is not None and 0 < r[k] <= 80 and 0 < r['pbr'] <= 30
    # 관계선: 시장 전체 + 업종별(평균 ROE 기준 n, 최근 4분기 ROE 기준 t)
    mk = {k: theil(sorted((r[key], r['pbr']) for r in S.values() if ok(r, key))) for k, key in (('n', 'roe_n'), ('t', 'roe_t'))}
    secs = {}
    for r in S.values(): secs.setdefault(r['sec'], []).append(r)
    SL = {}
    for s, lst in secs.items():
        d = {'L': {}}
        for k, key in (('n', 'roe_n'), ('t', 'roe_t')):
            pts = [(r[key], r['pbr']) for r in lst if ok(r, key)]
            if len(pts) >= TH['min_n']:
                L = theil(pts)
                if L and L[1] > 0: d['L'][k] = L       # 기울기가 음수(ROE가 높을수록 PBR이 낮게 나오는 표본)면 쓰지 않고 시장 선으로
        pb = [r['pbr'] for r in lst if r['pbr'] > 0]; ro = [r['roe_n'] for r in lst if r.get('roe_n') is not None]
        d['pbr_med'] = rnd(statistics.median(pb)) if pb else None; d['roe_med'] = rnd(statistics.median(ro), 1) if ro else None
        d['n'] = len(lst); SL[s] = d
    def fair(r, k, key):
        v = r.get(key)
        if v is None or v <= 0: return None, None, None
        L = SL[r['sec']]['L'].get(k); src = 's'
        if not L: L = mk.get(k); src = 'm'
        if not L: return None, None, None
        f = max(L[0] + L[1] * v, 0.2)
        return rnd(f), rnd((r['pbr'] / f - 1) * 100, 0), src
    cnt = {}
    for r in S.values():
        rn = r['roe_n']; t = r['roe_t']; pbr = r['pbr']
        r['lvl'] = 'loss' if rn <= 0 else 'high' if rn >= TH['hi'] else 'mid' if rn >= TH['lo'] else 'low'
        r['fair'], r['gap'], r['src'] = fair(r, 'n', 'roe_n')
        r['fair_t'], r['gap_t'], _ = fair(r, 't', 'roe_t')
        fm = None
        if mk.get('n') and rn > 0: fm = max(mk['n'][0] + mk['n'][1] * rn, 0.2)
        r['gap_m'] = rnd((pbr / fm - 1) * 100, 0) if fm else None       # 시장 전체 선 대비(업종 전체가 싸거나 비쌀 때 참고)
        med = SL[r['sec']].get('pbr_med'); g = r['gap']
        if r['lvl'] == 'loss' or (t is not None and t <= 0): cls = 'loss'
        elif g is None: cls = 'loss'
        elif g <= -TH['gap']: cls = 'trap' if r['lvl'] == 'low' else 'cheap'
        elif g >= TH['gap']: cls = 'rich' if r['lvl'] == 'high' else 'over'
        else: cls = 'trap' if (r['lvl'] == 'low' and med and pbr < med * 0.8) else 'fair'
        r['cls'] = cls; cnt[cls] = cnt.get(cls, 0) + 1
        fl = []; h = r['hist']; isfin = any(k in r['sec'] for k in FIN_SEC)
        if rn > 0 and t is not None and t - rn >= 8 and t >= rn * 1.5: fl.append('peak34' if r['ph'] in (3, 4) else 'peakroe')
        if h and t is not None and t <= h[-1][1] - 3: fl.append('down')
        if not isfin and r['debt'] is not None and r['debt'] >= 150 and rn >= TH['hi']: fl.append('lev')
        if rn >= TH['coe'] and pbr < 1: fl.append('abs')
        if r['lvl'] == 'low' and g is not None and g <= -TH['gap'] and not isfin and r['debt'] is not None and r['debt'] < 50: fl.append('asset')
        if len(h) < 3: fl.append('short')
        if pbr < 0.15 or (g is not None and g <= -85): fl.append('chk')      # 값이 비정상적으로 낮음 — 자본·시총 불일치(감자·합병·우선주 등) 가능
        if isfin: fl.append('fin')
        r['fl'] = fl
    seclist = []
    for s, lst in secs.items():
        d = SL[s]; c = {}
        for r in lst: c[r['cls']] = c.get(r['cls'], 0) + 1
        seclist.append({'name': s, 'n': d['n'], 'line': d['L'].get('n'), 'line_t': d['L'].get('t'), 'pbr_med': d['pbr_med'], 'roe_med': d['roe_med'], 'cnt': c})
    seclist.sort(key=lambda x: -x['n'])
    # 종목 행은 배열로(파일 크기): [코드, 이름, 업종, 시총, PBR, 최근4분기ROE, 평균ROE, 최저ROE, 연도별ROE, 적정PBR, 괴리, 판정, ROE수준, 표시, 국면, 초입, 4분기기준 적정, 4분기기준 괴리, 시장선 괴리, 부채비율, 연결/별도, 선 종류]
    out_rows = [[r['c'], r['n'], r['sec'], round(r['cap']), r['pbr'], r['roe_t'], r['roe_n'], r['roe_min'], r['hist'], r['fair'], r['gap'], r['cls'], r['lvl'],
                 r['fl'], r['ph'], 1 if r['e'] else 0, r['fair_t'], r['gap_t'], r['gap_m'], r['debt'], r['fs'], r['src']]
                for r in sorted(S.values(), key=lambda x: -x['cap'])]
    out = {'updated': datetime.datetime.now(KST).strftime('%Y-%m-%d %H:%M'), 'fin_updated': fin.get('updated'), 'fin_q': fin.get('asof_quarter'),
           'price_updated': sv.get('updated'), 'n': len(out_rows), 'th': TH, 'count': cnt, 'market': mk, 'sectors': seclist,
           'cols': ['c', 'n', 'sec', 'cap', 'pbr', 'roe_t', 'roe_n', 'roe_min', 'hist', 'fair', 'gap', 'cls', 'lvl', 'fl', 'ph', 'e', 'fair_t', 'gap_t', 'gap_m', 'debt', 'fs', 'src'],
           'rule': '평균 ROE = 최근 3개 사업연도 ROE(순이익 ÷ 기말 자본)와 최근 4분기 ROE의 평균. 관계선 = 같은 업종(WICS 소분류) 기업들의 (평균 ROE, 현재 PBR)을 강건 직선(Theil–Sen)으로 맞춘 것 — 업종 표본이 10개 미만이거나 기울기가 음수면 시장 전체 선. 괴리율 = 현재 PBR ÷ 관계선이 주는 PBR − 1, ±20% 안이면 제값. 순이익·자본은 DART 주요계정의 연결 전체 기준(비지배지분 포함)이라 자회사 소수지분이 큰 지주사는 ROE·PBR이 실제 주주 몫과 다를 수 있음',
           'rows': out_rows}
    json.dump(out, open(OUT, 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'))
    print('저장 %s %d종목 · 업종 %d · 판정 %s · 시장선 %s' % (OUT, len(out_rows), len(seclist), cnt, mk.get('n')))

if __name__ == '__main__':
    main()
