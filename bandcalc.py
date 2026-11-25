# -*- coding: utf-8 -*-
"""
밴드 판정 레이어 — public/data/compare/*.json 을 읽어 요약만 만든다.
    결과: public/data/bandpos.json

왜 따로 두나
    compare.py 가 일별 PBR·PER·PSR·ROE 시계열을 이미 쌓고 있다(10개년).
    그런데 peer 표에서 110종목을 훑을 때 차트를 하나씩 열 수는 없다.
    "지금 배수가 과거 분포의 몇 분위인가"를 **한 칸 숫자**로 줄여야 쓸 수 있다.

    이 스크립트는 **API 를 한 번도 부르지 않는다.** 이미 받아둔 파일만 읽는다.
    그래서 어디서든 돌고, 검증도 로컬에서 끝난다.

밴드에 쓸 수 있는 것 / 없는 것
    PER·PBR·PSR 은 **배수**라 밴드가 된다.
    ROE 는 배수가 아니라 수익성 비율이다 — ROE × BPS = EPS 이지 주가가 아니다.
    → ROE 는 밴드가 아니라 **분포**만 낸다. 대신 PER 분위와 짝지어 '이익 고점' 판정에 쓴다.

세 방식을 다 낸다
    q   분위수 5/20/40/60/80/95   ← 선 사이 관측 수가 같다. 기본
    eq  최저~최고 균등 6단계       ← 증권사·NICE 밴드차트 관행
    pc  5~95% 로 자른 뒤 균등      ← 극단값만 쳐낸 중간 방식
    셋이 다르게 나오는 것 자체가 정보다.
"""
import datetime, json, math, os, sys, glob

DD   = 'public/data'
SRC  = os.path.join(DD, 'compare')
OUT  = os.environ.get('OUT', os.path.join(DD, 'bandpos.json'))
DEFS = [s.strip() for s in os.environ.get(
        'DEF', 'semipeer_def.json,cospeer_def.json,robopeer_def.json').split(',') if s.strip()]
YEARS = float(os.environ.get('YEARS', '10'))
LOG = []

def log(s):
    LOG.append(s); print(s, flush=True)

def load(p, d=None):
    try:
        with open(p, encoding='utf-8') as f: return json.load(f)
    except Exception: return d

# ── 통계 ────────────────────────────────────────────────────────
def quantile(sv, p):
    if not sv: return None
    i = (len(sv) - 1) * p
    lo, hi = int(math.floor(i)), int(math.ceil(i))
    return sv[lo] if lo == hi else sv[lo] + (sv[hi] - sv[lo]) * (i - lo)

def pctile(sv, x):
    """x 가 분포의 몇 백분위인가 (0~100)"""
    if not sv or x is None: return None
    return round(sum(1 for v in sv if v < x) / len(sv) * 100)

def lines(sv, ndays=0):
    """세 방식의 6개 선. ndays = 같은 기간의 주가 관측일 — 적자 구간 비중을 재려고 받는다"""
    if len(sv) < 30: return None
    p5, p95 = quantile(sv, 0.05), quantile(sv, 0.95)
    rnd = (lambda v: round(v, 0 if p95 >= 100 else (1 if p95 >= 10 else 2)))
    q  = [rnd(quantile(sv, p)) for p in (0.05, 0.20, 0.40, 0.60, 0.80, 0.95)]
    lo, hi = sv[0], sv[-1]
    eq = [rnd(lo + (hi - lo) * i / 5) for i in range(6)]
    pc = [rnd(p5 + (p95 - p5) * i / 5) for i in range(6)]
    return {'q': q, 'eq': eq, 'pc': pc, 'n': len(sv),
            # 분모가 양수였던 날의 비율. PER 은 적자면 값이 없어 빠진다.
            # 0.3 이면 그 10년 중 3년만 흑자였고 밴드는 그 3년으로 만든 것이다.
            'cov': round(len(sv) / ndays, 2) if ndays else None,
            'min': rnd(lo), 'max': rnd(hi), 'med': rnd(quantile(sv, 0.5)),
            # 균등분할이 극단값에 얼마나 끌려갔나 — 1에 가까울수록 멀쩡하다
            'skew': round(hi / p95, 2) if p95 else None}

# ── 섹터별로 어느 배수를 먼저 보나 ──────────────────────────────
import re
# 앞서 한글 정규식만 뒀더니 ind 코드가 영문(robo/cos/semi)이라 전부 PER 로 떨어졌다.
# 레인보우로보틱스 PER 35,262배가 '기준'으로 잡혔다 — 코드도 같이 본다.
PREF = [
    (re.compile(r'은행|보험|증권|금융|지주|철강|조선|건설|해운|화학'), ['pbr', 'per', 'psr']),
    (re.compile(r'바이오|제약|로봇|신재생|우주|액츄에이터|^robo$|\brobo\b'), ['psr', 'pbr', 'per']),
]
def prefer(tags):
    t = ' '.join(x for x in tags if x)
    for rx, order in PREF:
        if rx.search(t): return order
    return ['per', 'psr', 'pbr']

# 기준 배수로 쓰려면 통과해야 하는 조건.
# ① 분모가 양수였던 날이 절반은 넘어야 한다 — 62일로 만든 PER 밴드는 분포가 아니다
# ② 절대 수준이 이 선을 넘으면 분모가 0 에 가까운 것이라 분위가 뜻을 잃는다
MINCOV = float(os.environ.get('MINCOV', '0.5'))
CAP = {'per': 60.0, 'pbr': 10.0, 'psr': 20.0}
def usable(k, band, now):
    if not band or not band.get('ok'): return False, '분포 없음'
    c = band.get('cov')
    if c is not None and c < MINCOV:
        return False, '분모가 양수인 날이 %d%%뿐' % round(c * 100)
    x = (now or {}).get('x')
    if x is not None and x > CAP[k]:
        return False, '현재 %g배 — %g배를 넘어 분모가 0 에 가깝다' % (x, CAP[k])
    return True, ''

def main():
    # 모집단 — peer 정의에서 종목·섹터
    uni = {}
    for fn in DEFS:
        d = load(os.path.join(DD, fn))
        if not d: log('%s 없음' % fn); continue
        ind = fn.replace('peer_def.json', '')
        gm = {}
        for g in (d.get('groups') or []):
            for c in (g.get('members') or []): gm[c] = g
        for c, v in (d.get('co') or {}).items():
            g = gm.get(c) or {}
            uni[c] = {'n': v.get('n') or c, 'ind': ind,
                      'top': g.get('top') or '', 'seg': g.get('seg') or '', 'gid': g.get('id') or ''}
        log('%s → %d종목' % (fn, len(d.get('co') or {})))

    cut = (datetime.date.today() - datetime.timedelta(days=int(YEARS * 365.25))).isoformat()
    recs, miss = {}, []
    for c, meta in uni.items():
        src = load(os.path.join(SRC, '%s.json' % c))
        if not src: miss.append(c); continue
        rec = {'n': meta['n'], 'ind': meta['ind'], 'top': meta['top'], 'gid': meta['gid'],
               'bands': {}, 'now': {}, 'flag': []}
        # 관측 구간 — 상장이 짧으면 '역사적 밴드'가 아니다
        px = src.get('px') or []
        if px:
            d0, d1 = px[0][0], px[-1][0]
            mo = (int(d1[:4]) - int(d0[:4])) * 12 + int(d1[5:7]) - int(d0[5:7])
            rec['obs'] = {'from': d0, 'to': d1, 'months': mo,
                          'level': '높음' if mo >= 60 else ('보통' if mo >= 36 else '낮음')}
        nday = len([1 for d, v in px if d >= cut]) or len(px)
        for k in ('per', 'pbr', 'psr'):
            ser = [v for d, v in (src.get(k) or []) if d >= cut and v and v > 0]
            L = lines(sorted(ser), nday)
            cur = next((v for d, v in reversed(src.get(k) or []) if v and v > 0), None)
            rec['bands'][k] = L or {'ok': False}
            if L:
                rec['bands'][k]['ok'] = True
                rec['now'][k] = {'x': round(cur, 2) if cur else None, 'pct': pctile(sorted(ser), cur)}
            else:
                rec['bands'][k]['why'] = ('관측 %d일 — 30일 미만이거나 전 구간 적자' % len(ser))
        # ROE 는 배수가 아니다 — 분포만
        rser = sorted(v for d, v in (src.get('roe') or []) if d >= cut and v is not None)
        rcur = next((v for d, v in reversed(src.get('roe') or []) if v is not None), None)
        if len(rser) >= 30:
            rec['roe'] = {'q': [round(quantile(rser, p), 1) for p in (0.1, 0.25, 0.5, 0.75, 0.9)],
                          'x': rcur, 'pct': pctile(rser, rcur),
                          'note': 'ROE 는 배수가 아니라 주가 밴드가 없다. 분포만 본다.'}
        rec['pref'] = prefer([meta['ind'], meta['top'], meta['seg']])
        rec['use'], rec['why_use'], skipped = None, '', []
        for k in rec['pref']:
            ok, why = usable(k, rec['bands'].get(k), rec['now'].get(k))
            if ok:
                rec['use'] = k
                if skipped:
                    rec['why_use'] = '%s 를 기준으로 쓴다 — %s' % (k.upper(),
                        ', '.join('%s 는 %s' % (a.upper(), b) for a, b in skipped))
                break
            skipped.append((k, why))
        if rec['use'] is None and skipped:
            rec['no_use'] = ', '.join('%s 는 %s' % (a.upper(), b) for a, b in skipped)
        # 적자 구간이 많다는 것 자체가 봐야 할 사실이다
        pc_ = (rec['bands'].get('per') or {}).get('cov')
        if pc_ is not None and pc_ < MINCOV:
            rec['flag'].append({'k': 'loss', 'm':
                '최근 %g년 중 분기 흑자였던 날이 %d%%뿐이다. PER 밴드는 그 구간만으로 만들어져 "과거 분포"로 읽으면 안 된다.'
                % (YEARS, round(pc_ * 100))})

        # 깃발 — 돌려보고 알게 된 것들
        pp = (rec['now'].get('per') or {}).get('pct')
        bp = (rec['now'].get('pbr') or {}).get('pct')
        rp = (rec.get('roe') or {}).get('pct')
        if pp is not None and rp is not None and pp <= 20 and rp >= 80:
            rec['flag'].append({'k': 'peak', 'm':
                'PER %d분위(싸 보임)인데 ROE 가 %d분위(역사적 고점)다. 이익이 꼭대기라 PER 이 눌린 것일 수 있다 — 사이클 업종의 가장 흔한 함정.' % (pp, rp)})
        if pp is not None and bp is not None and abs(pp - bp) >= 50:
            rec['flag'].append({'k': 'split', 'm':
                '같은 주가인데 PER 은 %d분위, PBR 은 %d분위다. 분모를 뭘 쓰느냐로 결론이 갈린다.' % (pp, bp)})
        o = rec.get('obs') or {}
        if o.get('level') == '낮음':
            rec['flag'].append({'k': 'short', 'm':
                '관측 %d개월(%s~). 36개월 미만이라 이 밴드는 "역사적 분포"가 아니라 "최근 구간의 변동폭"이다.' % (o['months'], o['from'])})
        # 분위가 하단인데 절대 배수는 비싼 경우 — 분위만 보면 "싸다"로 읽힌다.
        # 두산로보틱스 PSR 48배가 0분위로 뜬다. 과거 자기 이력이 더 비쌌을 뿐이다.
        ABS = {'per': 40, 'pbr': 6, 'psr': 8}
        for k, lim in ABS.items():
            nw = rec['now'].get(k) or {}
            if nw.get('pct') is not None and nw.get('x') and nw['pct'] <= 30 and nw['x'] >= lim:
                rec['flag'].append({'k': 'rich', 'm':
                    '%s %s배는 과거 분포로는 %d분위(하단)지만 절대 수준이 %d배를 넘는다. 과거 자기 이력이 더 비쌌을 뿐이고 싼 것이 아니다.'
                    % (k.upper(), nw['x'], nw['pct'], lim)})
                break
        sk = (rec['bands'].get(rec['use']) or {}).get('skew')
        if sk and sk >= 2:
            rec['flag'].append({'k': 'ext', 'm':
                '최댓값이 95분위의 %.1f배다. 균등분할 밴드는 그 한 번에 선 전체가 밀리니 분위수 모드로 봐야 한다.' % sk})
        recs[c] = rec

    # 섹터 밴드 — 구성 종목의 중앙값. 시총가중을 쓰면 대장주 하나가 섹터를 지배한다
    sec = {}
    grp = {}
    for c, r in recs.items():
        for key in (r['ind'], '%s|%s' % (r['ind'], r['top'] or '-')):
            grp.setdefault(key, []).append(r)
    for key, rs in grp.items():
        if len(rs) < int(os.environ.get('SEC_MIN', '3')): continue
        e = {'n': len(rs), 'now': {}}
        for k in ('per', 'pbr', 'psr'):
            vs = sorted((r['now'].get(k) or {}).get('x') for r in rs
                        if (r['now'].get(k) or {}).get('x'))
            ps = sorted((r['now'].get(k) or {}).get('pct') for r in rs
                        if (r['now'].get(k) or {}).get('pct') is not None)
            if len(vs) >= 3:
                e['now'][k] = {'med': round(quantile(vs, 0.5), 2),
                               'medpct': round(quantile(ps, 0.5)) if ps else None,
                               'n': len(vs)}
        e['note'] = '구성 %d곳의 중앙값. 시총가중을 쓰면 대장주 한 곳이 섹터를 지배해 사실상 그 종목 밴드가 된다.' % len(rs)
        sec[key] = e

    out = {'updated': datetime.datetime.now().strftime('%Y-%m-%d %H:%M KST'),
           'years': YEARS, 'n': len(recs), 'co': recs, 'sector': sec,
           'miss': miss,
           'note': ('compare/ 일별 시계열에서 뽑은 밴드 위치 요약. API 호출 없음. '
                    '선은 분위수(q)·균등분할(eq)·5~95%%자른균등(pc) 세 벌. '
                    'ROE 는 배수가 아니라 밴드가 아니고 분포만 담았다. '
                    '%d종목은 compare/ 에 아직 자료가 없다 — compare.py 가 채우면 다음 실행에서 들어온다.' % len(miss)),
           'log': LOG[-30:]}
    with open(OUT, 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, separators=(',', ':'))
    log('완료 %d종목 / 섹터 %d / 미보유 %d → %s' % (len(recs), len(sec), len(miss), OUT))
    return 0

if __name__ == '__main__':
    sys.exit(main())
