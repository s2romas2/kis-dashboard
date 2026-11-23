# -*- coding: utf-8 -*-
"""화장품 peer — 시세 기반 씨앗 데이터(cospeer.json).
   semipeer.py(DART 수집)를 돌리기 전에도 화면이 PER·PBR·ROE·시총을 보여주도록 만든다.
   채우는 값 : 시총·PER·PBR·ROE  (stockvals.json)
   못 채우는 값: PSR·OPM·분기 매출·성장률 → `DEF=cospeer_def.json OUT=public/data/cospeer.json python semipeer.py`
   덮어쓰기 규칙: 기존 cospeer.json 에 분기 자료(ql)가 있으면 그 종목은 건드리지 않는다.
"""
import json, os, datetime

BASE = os.environ.get('BASE', 'public/data')
DEFP = os.path.join(BASE, os.environ.get('DEF', 'cospeer_def.json'))
OUT  = os.path.join(BASE, os.environ.get('OUT_NAME', 'cospeer.json'))

def load(p, d=None):
    try: return json.load(open(p, encoding='utf-8'))
    except Exception: return d

DEF = load(DEFP)
if not DEF: raise SystemExit('%s 없음' % DEFP)
sv  = (load(os.path.join(BASE, 'stockvals.json'), {}) or {}).get('map') or {}
fin = (load(os.path.join(BASE, 'finall.json'), {}) or {}).get('rows') or {}
prev = (load(OUT, {}) or {})
pco  = prev.get('co') or {}
GM = {g['id']: g for g in DEF['groups']}

co, miss = {}, []
for c, d in DEF['co'].items():
    if (pco.get(c) or {}).get('ql'):            # DART 수집본이 있으면 보존
        co[c] = pco[c]; continue
    g0 = GM.get((d.get('gids') or [None])[0]) or {}
    r = {'n': d['n'], 'pure': d.get('pure'), 'gids': d.get('gids') or [],
         'top': g0.get('top'), 'seg': g0.get('seg'), 'flags': ['씨앗 데이터 — PSR·OPM·분기매출은 DART 수집 후 채워집니다']}
    v = sv.get(c)
    if not v or len(v) < 3 or not v[2]:
        r['flags'].append('시세 없음'); miss.append(d['n']); co[c] = r; continue
    r['kpbr'], r['kper'], r['cap'], r['px'] = v[0], v[1], v[2], (v[3] if len(v) > 3 else None)
    if len(v) > 4 and v[4] is not None: r['roe'] = v[4]
    elif r.get('kpbr') and r.get('kper'): r['roe'] = round(r['kpbr'] / r['kper'] * 100, 1)
    f = fin.get(c) or {}
    if f:
        r['asof'] = f.get('q'); r['fs'] = f.get('fs')
        if f.get('ni') is not None: r['ni'] = f['ni']
        if f.get('eq') is not None: r['eq'] = f['eq']
        if f.get('li') is not None and f.get('eq'): r['debt'] = round(f['li'] / f['eq'] * 100, 1)
    co[c] = r

out = {'updated': datetime.datetime.now().strftime('%Y-%m-%d %H:%M'),
       'price_updated': (load(os.path.join(BASE, 'stockvals.json'), {}) or {}).get('updated'),
       'seed': True, 'n': len(co), 'co': co,
       'groups': DEF['groups'], 'pairs': DEF.get('pairs') or [],
       'debug': ['씨앗 %d종목 · 시세 없음 %d (%s)' % (len(co), len(miss), ', '.join(miss[:8]))]}
os.makedirs(os.path.dirname(OUT), exist_ok=True)
json.dump(out, open(OUT, 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'))
print('저장 %s · 종목 %d · 시세 없음 %d: %s' % (OUT, len(co), len(miss), ', '.join(miss)))
