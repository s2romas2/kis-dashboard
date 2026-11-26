# -*- coding: utf-8 -*-
"""통신 peer 상대밸류 수집기.
외부 API를 쓰지 않는다 — 이미 수집된 JSON만 읽어 계산한다(키 불필요, 수 초).
입력  public/data/{telnodes,finall,stockvals,qoe,bandpos,products}.json
출력  public/data/telpeer.json  +  public/data/telnodes.json(회사명·시총·사업 갱신)
"""
import json, os, datetime, statistics as st

D = os.environ.get('DATA', 'public/data')
KST = datetime.timezone(datetime.timedelta(hours=9))
NOW = datetime.datetime.now(KST)

CHEAP  = float(os.environ.get('CHEAP', '0.9'))   # 그룹 중앙값 대비 이 아래면 저평가
DEAR   = float(os.environ.get('DEAR',  '1.1'))
PERMAX = float(os.environ.get('PERMAX','150'))   # 이 위의 PER은 비교에서 뺀다
MINN   = int(os.environ.get('MINN',   '4'))      # 칸에 흑자가 이보다 적으면 비교하지 않는다
TTMX   = float(os.environ.get('TTMX',  '3'))     # TTM 순이익이 최근 3년 최대 연간치의 이 배를 넘으면 버린다

def load(name, required=True):
    p = os.path.join(D, name + '.json')
    if not os.path.exists(p):
        if required: raise SystemExit('없음: ' + p)
        return {}
    with open(p, encoding='utf-8') as f: return json.load(f)

TN   = load('telnodes')
fin  = load('finall');     FIN = fin.get('rows', {})
sv   = load('stockvals');  SV  = sv.get('map', {})
qoe  = load('qoe', False).get('co', {})
bp   = load('bandpos', False); BP = bp.get('co', {})
prod = load('products', False).get('map', {})

node_of = {}
for n in TN['nodes']:
    for row in n['ko']:
        code = row[1] if isinstance(row, list) else row
        node_of.setdefault(code, []).append(n['id'])

CO = {}
for code in sorted(node_of):
    p = prod.get(code, {}) or {}
    f = FIN.get(code) or {}
    s = SV.get(code) or [None] * 5
    pbr, per, cap, px, roe = s
    m = {'c': code, 'n': p.get('n') or f.get('n') or code,
         'p': (p.get('p') or '')[:52], 'g': node_of[code],
         'cap': cap, 'px': px, 'per': per, 'pbr': pbr, 'roe': roe,
         'fl': [], 'sec': f.get('sec'), 'q': f.get('q'), 'fs': f.get('fs')}
    ni, eq, li = f.get('ni'), f.get('eq'), f.get('li')
    yr = f.get('yr') or []
    m['yr'] = [[y[0], y[1]] for y in yr] or None
    if li is not None and eq and eq > 0:
        m['debt'] = round(li / eq * 100, 1)
    mx = max((abs(y[1]) for y in yr if y[1] is not None), default=None)
    if ni is not None and mx and abs(ni) / mx <= TTMX:
        m['ni'] = round(ni, 1)
        if cap and ni > 0:
            m['tper'] = round(cap / ni, 2)
            if per and per > 0:
                r = per / m['tper']
                if r >= 1.5 or r <= 1 / 1.5:
                    m['fl'].append('perdiff'); m['pd'] = round(r, 2)
        if ni <= 0: m['fl'].append('loss')
    elif ni is not None and mx:
        # DART TTM 순이익이 상식 범위를 벗어난 경우 — 쓰지 않고 사유만 남긴다
        m['fl'].append('ttmbad'); m['ttmr'] = round(abs(ni) / mx, 1)
    if yr and yr[-1][1] is not None and yr[-1][1] <= 0 and 'loss' not in m['fl']:
        m['fl'].append('loss')
    if len(yr) >= 2:
        a, b = yr[0][1], yr[-1][1]
        if a and b and a > 0 and b > 0:
            m['nig'] = round(((b / a) ** (1.0 / (len(yr) - 1)) - 1) * 100, 1)
    q = qoe.get(code)
    if q and q.get('ladder'):
        L = [x for x in q['ladder'] if x.get('rev') is not None][-4:]
        if len(L) == 4:
            rev = sum(x['rev'] for x in L); op = sum((x.get('op') or 0) for x in L)
            m['rev'] = round(rev, 1); m['op'] = round(op, 1)
            if rev > 0:
                m['opm'] = round(op / rev * 100, 2)
                if cap: m['psr'] = round(cap / rev, 2)
    b = BP.get(code)
    if b and b.get('use'):
        u = b['use']; now = (b.get('now') or {}).get(u) or {}
        if now.get('pct') is not None:
            m['bd'] = {'u': u, 'pct': now['pct'], 'x': now.get('x')}
    CO[code] = m

G = {}
for n in TN['nodes']:
    codes = [(r[1] if isinstance(r, list) else r) for r in n['ko']]
    ms = [CO[c] for c in codes if c in CO]
    def med(k, pos=True):
        v = [x[k] for x in ms if x.get(k) is not None and (not pos or x[k] > 0)]
        return round(st.median(v), 2) if v else None
    G[n['id']] = {'t': n['t'], 'b': n['b'], 'ic': n['ic'], 'e': n['e'], 'n': len(ms),
                  'per': med('per'), 'pbr': med('pbr'), 'psr': med('psr'),
                  'roe': med('roe', False), 'opm': med('opm', False),
                  'debt': med('debt', False), 'cap': med('cap'),
                  'codes': [x['c'] for x in ms],
                  'nper': len([x for x in ms if x.get('per') and x['per'] > 0]),
                  'nloss': len([x for x in ms if 'loss' in x['fl']])}

for m in CO.values():
    tg = []
    for gid in m['g']:
        g = G[gid]
        if g['nper'] < MINN: continue          # 중앙값이 한두 곳에 끌려다니면 비교하지 않는다
        if m.get('per') and g['per'] and 0 < m['per'] <= PERMAX and 'loss' not in m['fl']:
            r = m['per'] / g['per']
            tg.append([gid, 'per', round(r, 2), 'low' if r <= CHEAP else ('high' if r >= DEAR else 'mid')])
        if m.get('pbr') and g['pbr'] and m['pbr'] > 0:
            r = m['pbr'] / g['pbr']
            tg.append([gid, 'pbr', round(r, 2), 'low' if r <= CHEAP else ('high' if r >= DEAR else 'mid')])
        if m.get('roe') is not None and g['roe'] is not None:
            d = m['roe'] - g['roe']
            tg.append([gid, 'roe', round(d, 2), 'high' if d >= 1 else ('low' if d <= -1 else 'mid')])
    m['tg'] = tg
    per = [t for t in tg if t[1] == 'per']; roe = [t for t in tg if t[1] == 'roe']
    lo = bool(per) and all(t[3] == 'low' for t in per)
    hr = bool(roe) and all(t[3] == 'high' for t in roe)
    if 'loss' in m['fl']:                    m['sig'] = 'loss'
    elif not m.get('per') or m['per'] <= 0:  m['sig'] = 'noper'
    elif not per:                            m['sig'] = 'nopeer'
    elif lo and hr:                          m['sig'] = 'edge'
    elif lo:                                 m['sig'] = 'lowper'
    elif all(t[3] == 'high' for t in per):   m['sig'] = 'highper'
    else:                                    m['sig'] = 'midper'

cnt = {}
for m in CO.values(): cnt[m['sig']] = cnt.get(m['sig'], 0) + 1

out = {'updated': NOW.strftime('%Y-%m-%d %H:%M'),
       'price_updated': sv.get('updated'), 'fin_updated': fin.get('updated'),
       'fin_q': fin.get('asof_quarter'), 'band_updated': bp.get('updated'),
       'n': len(CO), 'count': cnt,
       'th': {'cheap': CHEAP, 'dear': DEAR, 'permax': PERMAX, 'minn': MINN, 'ttmx': TTMX},
       'co': CO, 'g': G}
with open(os.path.join(D, 'telpeer.json'), 'w', encoding='utf-8') as f:
    json.dump(out, f, ensure_ascii=False, separators=(',', ':'))

# 분류 파일의 회사명·시총·사업 한 줄을 같은 값으로 맞춘다(교과서 09장이 이 파일만 읽는다)
for n in TN['nodes']:
    rows = []
    for r in n['ko']:
        c = r[1] if isinstance(r, list) else r
        m = CO.get(c) or {}
        rows.append([m.get('n') or (r[0] if isinstance(r, list) else c), c, m.get('cap'), m.get('p') or ''])
    n['ko'] = sorted(rows, key=lambda x: -(x[2] or 0))
TN['updated'] = out['updated']
TN['nco'] = len(CO)
with open(os.path.join(D, 'telnodes.json'), 'w', encoding='utf-8') as f:
    json.dump(TN, f, ensure_ascii=False, separators=(',', ':'))

nb = sum(1 for m in CO.values() if 'ttmbad' in m['fl'])
print('종목 %d · 칸 %d · 비교성립 %d칸' % (len(CO), len(G), sum(1 for g in G.values() if g['nper'] >= MINN)))
print('신호', cnt)
print('PER %d · PBR %d · PSR %d · 밴드 %d · DART TTM 폐기 %d · 괴리 %d'
      % (sum(1 for m in CO.values() if m.get('per')), sum(1 for m in CO.values() if m.get('pbr')),
         sum(1 for m in CO.values() if m.get('psr')), sum(1 for m in CO.values() if m.get('bd')),
         nb, sum(1 for m in CO.values() if 'pd' in m)))
