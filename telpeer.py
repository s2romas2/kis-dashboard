# -*- coding: utf-8 -*-
"""통신 peer 상대밸류 수집기.
외부 API를 쓰지 않는다 — 이미 수집된 JSON만 읽어 계산한다(키 불필요, 수 초).
입력  public/data/{telnodes,finall,stockvals,qoe,bandpos,products}.json
출력  public/data/telpeer.json  +  public/data/telnodes.json(회사명·시총·사업 갱신)

기준(2026-11-26 교정):
  PER·PBR·ROE 의 본값은 DART 최근 4분기(TTM)다 — finall.json(hege.py 수집).
  stockvals.json 의 per/pbr/roe 는 KIS 현재가 API 값이고 **직전 결산(전년) 확정 EPS·BPS 기준**이라
  2026년 메모리 슈퍼사이클 같은 급변기에는 실제와 크게 어긋난다(삼성전자 KIS PER 25배 vs TTM 4.6배).
  그래서 KIS 값은 교차검증 열(kper·kpbr·kroe)로만 두고, 1.5배 이상 벌어지면 사유와 함께 표시한다.
"""
import json, os, datetime, statistics as st

D = os.environ.get('DATA', 'public/data')
KST = datetime.timezone(datetime.timedelta(hours=9))
NOW = datetime.datetime.now(KST)

CHEAP  = float(os.environ.get('CHEAP', '0.9'))   # 그룹 중앙값 대비 이 아래면 저평가
DEAR   = float(os.environ.get('DEAR',  '1.1'))
PERMAX = float(os.environ.get('PERMAX','150'))   # 이 위의 PER은 비교에서 뺀다
MINN   = int(os.environ.get('MINN',   '4'))      # 칸에 흑자가 이보다 적으면 비교하지 않는다
KGAP   = float(os.environ.get('KGAP',  '1.5'))   # KIS(전년 확정)와 TTM 이 이 배 이상 벌어지면 표시

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
    kpbr, kper, cap, px, kroe = s
    m = {'c': code, 'n': p.get('n') or f.get('n') or code,
         'p': (p.get('p') or '')[:52], 'g': node_of[code],
         'cap': cap, 'px': px, 'kper': kper, 'kpbr': kpbr, 'kroe': kroe,
         'fl': [], 'sec': f.get('sec'), 'q': f.get('q'), 'fs': f.get('fs')}
    ni, eq, li = f.get('ni'), f.get('eq'), f.get('li')
    yr = f.get('yr') or []
    m['yr'] = [[y, y2] for y, y2 in ((x[0], x[1]) for x in yr)] or None
    m['ni'] = None if ni is None else round(ni, 1)
    m['eq'] = None if eq is None else round(eq, 1)
    # ── 본값: DART 최근 4분기(TTM) ─────────────────────────────
    if cap and ni is not None and ni > 0: m['per'] = round(cap / ni, 2)
    if cap and eq and eq > 0:             m['pbr'] = round(cap / eq, 2)
    if ni is not None and eq and eq > 0:  m['roe'] = round(ni / eq * 100, 2)
    if li is not None and eq and eq > 0:  m['debt'] = round(li / eq * 100, 1)
    if ni is not None and ni <= 0: m['fl'].append('loss')
    if ni is None: m['fl'].append('nofin')
    # ── 교차검증: KIS 전년 확정 ────────────────────────────────
    if m.get('per') and kper and kper > 0:
        r = kper / m['per']
        if r >= KGAP or r <= 1 / KGAP:
            m['fl'].append('kgap'); m['kg'] = round(r, 2)
    if len(yr) >= 2:
        a, b = yr[0][1], yr[-1][1]
        if a and b and a > 0 and b > 0:
            m['nig'] = round(((b / a) ** (1.0 / (len(yr) - 1)) - 1) * 100, 1)
    # TTM 이 최근 3년 최대 연간치의 몇 배인지 — 버리지 않고 급증 신호로만 기록
    mx = max((abs(x[1]) for x in yr if x[1] is not None), default=None)
    if ni is not None and mx and mx > 0:
        m['ttmr'] = round(ni / mx, 1)
        if m['ttmr'] >= 3: m['fl'].append('surge')
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
    elif 'nofin' in m['fl']:                 m['sig'] = 'nofin'
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
       'basis': 'PER·PBR·ROE = DART 최근 4분기(TTM) 연결 전체. KIS 값은 직전 결산 기준이라 교차검증에만 씀',
       'th': {'cheap': CHEAP, 'dear': DEAR, 'permax': PERMAX, 'minn': MINN, 'kgap': KGAP},
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

nb = sum(1 for m in CO.values() if 'surge' in m['fl'])
print('종목 %d · 칸 %d · 비교성립 %d칸' % (len(CO), len(G), sum(1 for g in G.values() if g['nper'] >= MINN)))
print('신호', cnt)
print('PER %d · PBR %d · PSR %d · 밴드 %d · 이익 급증(3배+) %d · KIS 괴리 %d'
      % (sum(1 for m in CO.values() if m.get('per')), sum(1 for m in CO.values() if m.get('pbr')),
         sum(1 for m in CO.values() if m.get('psr')), sum(1 for m in CO.values() if m.get('bd')),
         nb, sum(1 for m in CO.values() if 'kg' in m)))
