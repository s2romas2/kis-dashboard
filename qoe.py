#!/usr/bin/env python3
# 이익의 질(Quality of Earnings) — "순익 감소 = 사이클 끝"으로 오독하지 않기 위한 공통 근거
#
#  1단계 [계산]  손익 계단 분해: 매출 → 영업이익 → 순이익 YoY 를 나란히 놓고 꺾인 '단'을 특정
#  2단계 [확인]  꺾인 분기만 골라 DART 주석 원문에서 일회성 항목을 금액까지 추출
#                 (기타수익·기타비용 / 금융손익 / 법인세 / 판관비)
#  3단계 [판단]  비현금 여부 등은 판단으로만 표시하고 원인 미상이면 비워 둔다
#
# 원칙: 판정은 계산으로, 원인은 공시 출처로. 근거 없는 원인 추정은 쓰지 않는다.
# 원문 접근: DART 뷰어(키 불필요) — rcpNo 는 opendart list.json(키)
# 결과: public/data/qoe.json
import os, io, sys, json, time, re, zipfile, urllib.request
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import qdeep as Q                      # fetch/viewer/doc_tree/tables/tonum 재사용

KEY     = os.environ.get('DART_KEY', '')
OUT     = 'public/data/qoe.json'
CMPDIR  = 'public/data/compare'
MAXRUN  = int(os.environ.get('MAXRUN', '25'))   # 1회 실행에서 원문을 캘 종목 수
PV      = 1
DEBUG   = []

# ── 꺾임 판정 임계 ────────────────────────────────────────────────────────────
NI_DROP   = -30.0   # 순이익 YoY 이보다 나쁘면 '꺾임'으로 본다
OP_HOLD   = -10.0   # 영업이익 YoY 가 이보다 좋으면 '영업은 버팀'
REV_HOLD  =  -5.0   # 매출 YoY 가 이보다 좋으면 '외형은 버팀'
GAP_MIN   =  25.0   # 순익YoY 와 영익YoY 의 괴리(%p) 최소값

# 주석에서 일회성으로 보는 계정 (이름만으로 식별 가능한 것들)
ONEOFF = re.compile(
    r'(손상차손|처분손실|폐기손실|대손상각|충당부채전입|소송|배상|과징금|벌금|'
    r'평가손실|파생상품거래손실|기부금|구조조정|합병|청산|중단영업)')

def eok(v):            # 원 → 억원
    return None if v is None else round(v / 1e8, 1)

# ── 1단계: 계단 분해 ─────────────────────────────────────────────────────────
def ladder(code):
    """compare/{code}.json 의 분기 손익으로 YoY 계단을 만든다. [{q,rev,op,ni,revY,opY,niY,flag}]"""
    p = '%s/%s.json' % (CMPDIR, code)
    if not os.path.exists(p):
        return []
    qs = (json.load(open(p, encoding='utf-8')).get('qs') or [])
    out, by = [], {}
    for r in qs:
        if len(r) >= 4:
            by[r[0]] = (r[1], r[2], r[3])          # 억원
    for lab in sorted(by):
        y, qn = int(lab[:4]), lab[5]
        prev = '%d Q%s' % (y - 1, qn)
        prev = prev.replace(' ', '')
        rev, op, ni = by[lab]
        pr = by.get(prev)
        def yoy(c, p0):
            if c is None or p0 is None or p0 == 0:
                return None
            if p0 < 0:                              # 적자 기준 증감률은 의미가 없다
                return None
            return round((c - p0) / p0 * 100, 1)
        revY = yoy(rev, pr[0]) if pr else None
        opY  = yoy(op,  pr[1]) if pr else None
        niY  = yoy(ni,  pr[2]) if pr else None
        flag = None
        if niY is not None and niY <= NI_DROP:
            if opY is not None and opY >= OP_HOLD and (niY - opY) <= -GAP_MIN \
               and (revY is None or revY >= REV_HOLD):
                flag = 'below_op'                   # 영업 밖에서 꺾임 → 일회성 후보
            elif opY is not None and opY <= NI_DROP:
                flag = 'operating'                  # 영업단부터 꺾임
            else:
                flag = 'mixed'
        out.append({'q': lab, 'rev': rev, 'op': op, 'ni': ni,
                    'revY': revY, 'opY': opY, 'niY': niY, 'flag': flag})
    return out

# ── 2단계: 주석에서 일회성 항목 추출 ─────────────────────────────────────────
UNIT = re.compile(r'단\s*위\s*[:：]\s*([^)＜<]{1,12})')

def unit_mult(h, pos):
    seg = h[max(0, pos - 1200):pos]
    m = None
    for m in UNIT.finditer(seg):
        pass
    if not m:
        return 1.0
    u = m.group(1)
    if '백만' in u: return 1e6
    if '천'  in u: return 1e3
    if '억'  in u: return 1e8
    return 1.0

PERIOD = re.compile(r'(당반기|전반기|당분기|전분기|당기|전기)')

def parse_note_pairs(h):
    """주석 표 → {계정명: {'cur':원, 'prev':원}}

    같은 주석 안에 '당반기' 표와 '전반기' 표가 따로 실린다. 둘을 짝지어 두면
    계정명 사전에 기대지 않고 '전년 동기 대비 얼마가 튀었나'로 일회성을 집어낼 수 있다.
    """
    cur, prev = {}, {}
    for m in re.finditer(r'<TABLE[\s\S]*?</TABLE>', h, re.I):
        tb = Q.tables(m.group(0))[0]
        if not tb or len(tb) < 3:
            continue
        mult = unit_mult(h, m.start())
        seg = h[max(0, m.start() - 1500):m.start()]
        labs = PERIOD.findall(re.sub(r'<[^>]+>', ' ', seg))
        side = prev if (labs and labs[-1] in ('전반기', '전분기', '전기')) else cur
        # 머리글에 '3개월'이 있으면 그 열(분기 단독), 없으면 첫 숫자 열
        col = 0
        for r in tb[:4]:
            cells = [c.replace(' ', '') for c in r]
            if '3개월' in cells:
                col = 0
                break
            if '누적' in cells:
                col = 0
        for r in tb:
            txt  = [c.strip() for c in r if not Q._is_numlike(c)]
            nums = [Q.tonum(c.replace(' ', '')) for c in r if Q._is_numlike(c)]
            nums = [n for n in nums if n is not None]
            if not txt or not nums:
                continue
            name = txt[-1][:28]
            if not name or name in ('장부금액', '공시금액', '3개월', '누적'):
                continue
            side.setdefault(name, nums[min(col, len(nums) - 1)] * mult)
    return {k: {'cur': cur.get(k), 'prev': prev.get(k)} for k in set(cur) | set(prev)}

NOTE_WANT = {
    'other': re.compile(r'기타수익.*기타비용|기타손익'),
    'fin'  : re.compile(r'금융손익|금융수익.*금융비용|금융수익.*금융원가'),
    'tax'  : re.compile(r'법인세비용'),
    'sga'  : re.compile(r'판매비와?관리비'),
}

def notes_of(rcp):
    """정기보고서 1건에서 주석 4종을 뽑는다 (연결 우선)"""
    tree = Q.doc_tree(rcp)
    if not tree:
        return {}
    picked, out = {}, {}
    for txt, dcm, ele, off, ln in tree:
        t = txt.replace(' ', '')
        for k, rx in NOTE_WANT.items():
            if rx.search(t):
                conso = '(연결)' in txt
                if k not in picked or (conso and not picked[k][0]):
                    picked[k] = (conso, (dcm, ele, off, ln))
    for k, (_, loc) in picked.items():
        h = Q.viewer(rcp, *loc)
        if h:
            out[k] = parse_note_pairs(h)
        time.sleep(0.3)
    return out

def oneoffs(notes, ni_swing_won=None):
    """전년 동기 대비 증감이 큰 손익 항목 — 계정명 사전에 의존하지 않는다.

    ni_swing_won: 순이익 YoY 변동폭(원). 주어지면 그 10% 이상 움직인 항목만 남긴다.
    """
    floor = 5e8
    if ni_swing_won:
        floor = max(floor, abs(ni_swing_won) * 0.10)
    hits = []
    for sec in ('other', 'fin', 'sga'):
        for name, v in (notes.get(sec) or {}).items():
            c, p = v.get('cur'), v.get('prev')
            if c is None:
                continue
            n = name.replace(' ', '')
            if n.startswith(('기타이익', '기타손실', '금융수익', '금융원가', '금융비용', '합계', '소계')):
                continue                      # 소계 행 제외
            d = c - (p or 0)
            if abs(d) < floor:
                continue
            hits.append({'name': name, 'cur': eok(c), 'prev': eok(p), 'chg': eok(d), 'note': sec,
                         'cash': 'noncash' if re.search(r'손상차손|평가손실|대손상각|주식보상|감가상각', n) else 'cash',
                         'named': bool(ONEOFF.search(n))})
    hits.sort(key=lambda x: abs(x['chg'] or 0), reverse=True)
    return hits[:8]


# ── 보고서 ↔ 분기 매칭 ───────────────────────────────────────────────────────
def filings(corp):
    """정기보고서 [(rcpNo, 'YYYYQn')] — 그 보고서가 '당분기'로 다루는 분기"""
    out = []
    for page in (1, 2):
        d = Q.jget('%s/list.json?crtfc_key=%s&corp_code=%s&bgn_de=20200101&page_no=%d'
                   '&page_count=100&pblntf_ty=A' % (Q.BASE, KEY, corp, page))
        for it in (d.get('list') or []):
            nm = it.get('report_nm') or ''
            m = re.search(r'\((\d{4})\.(\d{2})\)', nm)
            if not m or '보고서' not in nm:
                continue
            y, mm = int(m.group(1)), int(m.group(2))
            qn = {3: 1, 6: 2, 9: 3, 12: 4}.get(mm)
            if qn:
                out.append((it['rcept_no'], '%dQ%d' % (y, qn)))
        if len(d.get('list') or []) < 100:
            break
    # 같은 분기에 여러 건(기재정정)이면 최신 접수 우선
    best = {}
    for rcp, lab in sorted(out):
        best[lab] = rcp
    return best

def run():
    corp = Q.corp_map()
    names = {}
    for f in os.listdir(CMPDIR):
        if f.endswith('.json') and f != 'index.json':
            try:
                d = json.load(open('%s/%s' % (CMPDIR, f), encoding='utf-8'))
                names[d.get('code') or f[:-5]] = d.get('name') or ''
            except Exception:
                pass
    old = {}
    if os.path.exists(OUT):
        try:
            old = (json.load(open(OUT, encoding='utf-8')).get('co') or {})
        except Exception:
            old = {}
    co, done = dict(old), 0
    for code in sorted(names):
        lad = ladder(code)
        if not lad:
            continue
        prev = co.get(code) or {}
        rec = {'name': names[code], 'ladder': lad, 'ev': dict(prev.get('ev') or {}), 'pv': PV}
        # 원문이 필요한 분기 = 영업 밖에서 꺾인 분기 중 아직 안 캔 것
        need = [r['q'] for r in lad if r['flag'] == 'below_op' and r['q'] not in rec['ev']]
        need = need[-4:]                       # 최근 4개 분기까지만
        if need and done < MAXRUN and corp.get(code):
            fl = filings(corp[code])
            for q in need:
                rcp = fl.get(q)
                if not rcp:
                    rec['ev'][q] = {'rcp': None, 'items': [], 'why': 'no_report'}
                    continue
                try:
                    nt = notes_of(rcp)
                    sw = next((r for r in lad if r['q'] == q), None)
                    swing = ((sw['ni'] - sw['ni'] / (1 + sw['niY'] / 100)) * 1e8) if (sw and sw.get('niY') not in (None, -100)) else None
                    rec['ev'][q] = {'rcp': rcp, 'items': oneoffs(nt, swing),
                                    'tax': eok((nt.get('tax') or {}).get('법인세비용(수익) 합계'))}
                except Exception as e:
                    rec['ev'][q] = {'rcp': rcp, 'items': [], 'why': str(e)[:60]}
                time.sleep(0.4)
            done += 1
        co[code] = rec
    n_flag = sum(1 for c in co.values() for r in c['ladder'] if r['flag'] == 'below_op')
    n_ev   = sum(1 for c in co.values() for v in (c.get('ev') or {}).values() if v.get('items'))
    json.dump({'updated': time.strftime('%Y-%m-%d %H:%M'), 'pv': PV,
               'note': '순익 꺾임의 발생 단(段)을 계산으로 특정하고, 영업 밖에서 꺾인 분기만 '
                       'DART 주석 원문에서 일회성 항목을 금액까지 확인한다. 원인 미상이면 비워 둔다.',
               'rule': {'NI_DROP': NI_DROP, 'OP_HOLD': OP_HOLD, 'REV_HOLD': REV_HOLD, 'GAP_MIN': GAP_MIN},
               'stat': {'co': len(co), 'below_op': n_flag, 'with_evidence': n_ev},
               'debug': DEBUG, 'co': co},
              open(OUT, 'w', encoding='utf-8'), ensure_ascii=False)
    print('종목 %d · 영업밖 꺾임 %d분기 · 공시근거 확보 %d분기 → %s' % (len(co), n_flag, n_ev, OUT))

if __name__ == '__main__':
    run()
