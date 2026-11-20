# -*- coding: utf-8 -*-
"""
반도체 peer — 수주잔고 시계열·증감율·인식 구조
    결과: public/data/semipeer_backlog.json

무엇을 보려는 건가
    수주잔고는 "앞으로 매출로 바뀔 일감"이다. 한 시점의 절대액보다
      ① 분기마다 늘고 있나 줄고 있나(QoQ·YoY)
      ② 지금 매출 속도로 몇 분기치인가(커버리지)
      ③ 그 일감이 언제 매출로 꽂히나(납기 분포)
    이 셋이 같이 보여야 뜻이 생긴다.

어떻게 모으나
    valfacts.py 가 이미 정기보고서 원문에서 '수주상황' 표를 떼어 내고 합계 행에서
    수주잔고를 뽑는 파서(parse_biz)를 갖고 있다. 그 파서를 그대로 import 해서,
    최신 보고서 하나가 아니라 **최근 3년치 정기보고서 전부**에 돌려 시계열을 만든다.
    (분기·반기·사업보고서가 각각 그 시점의 잔고 스냅숏이다)

주의
    · 회사마다 표 서식이 달라 잔고를 못 뽑는 곳이 많다 — 못 뽑으면 비워 두고 표 원문만 남긴다.
    · 단위(백만원/천원/달러)가 제각각이라 valfacts 의 환산을 그대로 쓰고, 단위가 불명확하면 버린다.
    · 수주 인식 기준은 회사가 쓴 문장(order_note)을 그대로 싣는다 — 해석하지 않는다.
    · 첫 실행 전에는 검증된 적이 없다. 반드시 첫 Actions 로그로 잔고 추출 성공 종목 수를 확인할 것.
"""
import json, os, re, sys, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import valfacts as V                      # api·ddoc·parse_biz·tonum 재사용

BASE = os.environ.get('BASE', 'public/data')
OUT  = os.path.join(BASE, 'semipeer_backlog.json')
YEARS = int(os.environ.get('BL_YEARS', '3'))
BUDGET = float(os.environ.get('BL_BUDGET', '3600'))
T0 = time.time()
DEBUG = []

def log(s):
    DEBUG.append(str(s)[:300]); print(s, file=sys.stderr)

def qlabel(y, mm):
    """보고서 (연도, 월) → 기준 분기와 기준일"""
    q = {3: 1, 6: 2, 9: 3, 12: 4}.get(mm)
    if not q: return None, None
    end = {1: '03-31', 2: '06-30', 3: '09-30', 4: '12-31'}[q]
    return '%dQ%d' % (y, q), '%d-%s' % (y, end)

def reports(corp):
    """최근 YEARS 년치 정기보고서 — (rcept_no, 연도, 월) 오름차순"""
    end = time.strftime('%Y%m%d')
    beg = time.strftime('%Y%m%d', time.localtime(time.time() - YEARS * 370 * 86400))
    out, page = [], 1
    while page <= 3:
        rows = V.api('list', corp_code=corp, bgn_de=beg, end_de=end,
                     pblntf_ty='A', page_no=page, page_count=100)
        if not rows: break
        for r in rows:
            nm = r.get('report_nm') or ''
            if '[첨부' in nm: continue
            m = re.search(r'(사업|반기|분기)보고서\s*\((\d{4})\.(\d{2})\)', nm)
            if not m: continue
            out.append((r['rcept_no'], int(m.group(2)), int(m.group(3))))
        if len(rows) < 100: break
        page += 1
    # 같은 분기에 정정본이 여러 개면 접수번호가 큰 것(나중 것)만 남긴다
    best = {}
    for rc, y, mm in out:
        best[(y, mm)] = max(best.get((y, mm), ''), rc)
    return sorted(((rc, y, mm) for (y, mm), rc in best.items()), key=lambda t: (t[1], t[2]))

def pct(cur, prev):
    if cur is None or prev in (None, 0) or prev <= 0: return None
    return round((cur / prev - 1) * 100, 1)

def recognition(vf, ttm_rev, last_eok):
    """수주가 언제 매출로 바뀌나 — 공급계약 공시의 납기 분포와 잔고 커버리지."""
    out = {}
    if ttm_rev and ttm_rev > 0 and last_eok is not None:
        out['cover_q'] = round(last_eok / (ttm_rev / 4), 2)      # 최근 분기 매출 기준 몇 분기치
        out['cover_pct'] = round(last_eok / ttm_rev * 100, 1)    # 최근 1년 매출 대비 %
    con = (vf or {}).get('con') or {}
    items = con.get('list') or []          # valfacts 의 공급계약 목록(금액 amt=억원, 기간 from~to)
    today = time.strftime('%Y-%m-%d')
    by_year, open_sum, due = {}, 0.0, []
    for it in items:
        if not isinstance(it, dict): continue
        amt = it.get('amt')
        end = (it.get('to') or '')[:10]
        if amt is None or not re.match(r'\d{4}-\d{2}-\d{2}', end or ''): continue
        if end >= today:
            open_sum += amt
            due.append({'t': (it.get('item') or '')[:30], 'eok': amt, 'end': end,
                        'cp': (it.get('cp') or '')[:18]})
        by_year[end[:4]] = round(by_year.get(end[:4], 0) + amt, 1)
    if by_year: out['by_year'] = by_year
    if due:
        due.sort(key=lambda d: d['end'])
        out['open_eok'] = round(open_sum, 1)
        out['due'] = due[:12]
    return out or None

def main():
    sp = json.load(open(os.path.join(BASE, 'semipeer.json'), encoding='utf-8'))
    co_sp = sp.get('co') or {}
    corpmap = sp.get('corpmap') or {}
    if not corpmap:
        try: corpmap = json.load(open('tools/semipeer/dartcorp.json', encoding='utf-8'))
        except Exception: corpmap = {}
    codes = [c for c in co_sp if corpmap.get(c)]
    log('대상 %d종목 (고유번호 있음 / 전체 %d)' % (len(codes), len(co_sp)))

    prev = {}
    if os.path.exists(OUT):
        try: prev = (json.load(open(OUT, encoding='utf-8')) or {}).get('co') or {}
        except Exception: prev = {}

    co, n_series, n_pts = {}, 0, 0
    for i, c in enumerate(codes):
        if time.time() - T0 > BUDGET:
            log('시간 예산 소진 — %d종목에서 중단(다음 실행에서 이어감)' % i); break
        old = prev.get(c) or {}
        seen = {p['q']: p for p in (old.get('s') or [])}
        try:
            reps = reports(corpmap[c])
        except Exception as e:
            log('%s 목록 실패 %r' % (c, e)); co[c] = old; continue
        rec = dict(old)
        pts = dict(seen)
        for rc, y, mm in reps:
            q, d = qlabel(y, mm)
            if not q: continue
            if q in pts and pts[q].get('rcept') == rc: continue   # 이미 같은 접수번호로 받음
            try:
                raw = V.ddoc(rc)
            except Exception:
                continue
            if not raw: continue
            try:
                b = V.parse_biz(raw)
            except Exception:
                continue
            bl = (b or {}).get('backlog') or {}
            if bl.get('eok') is None: continue
            pts[q] = {'q': q, 'd': d, 'eok': bl['eok'], 'u': bl.get('u'), 'rcept': rc}
            if (b or {}).get('order_note'): rec['note'] = b['order_note']
            if (b or {}).get('order'): rec['table'] = b['order']
        ser = [pts[k] for k in sorted(pts)]
        for j, p in enumerate(ser):
            p['qoq'] = pct(p['eok'], ser[j-1]['eok']) if j >= 1 else None
            p['yoy'] = pct(p['eok'], ser[j-4]['eok']) if j >= 4 else None
        if ser:
            rec['s'] = ser; n_series += 1; n_pts += len(ser)
            x = co_sp.get(c) or {}
            vfp = os.path.join(BASE, 'vf', c + '.json')
            vf = None
            if os.path.exists(vfp):
                try: vf = json.load(open(vfp, encoding='utf-8'))
                except Exception: vf = None
            r = recognition(vf, x.get('rev'), ser[-1]['eok'])
            if r: rec['recog'] = r
        if rec: co[c] = rec
        if (i + 1) % 20 == 0:
            log('  %d/%d · 잔고 시계열 %d종목 (%ds)' % (i + 1, len(codes), n_series, time.time() - T0))

    if n_series == 0 and prev:
        log('이번 실행에서 하나도 못 뽑음 — 기존 파일 유지'); return 1
    for c, v in prev.items():
        if c not in co: co[c] = v                         # 이번에 못 돈 종목은 기존 값 보존
    out = {'updated': time.strftime('%Y-%m-%d %H:%M'), 'n': len(co), 'n_series': n_series,
           'n_points': n_pts,
           'note': ('정기보고서(분기·반기·사업)의 수주상황 표 합계 행에서 뽑은 수주잔고. '
                    '회사마다 표 서식이 달라 못 뽑는 곳이 있고, 그런 곳은 비어 있다. '
                    '수주 인식 기준 문장은 회사가 쓴 그대로이며 해석하지 않았다.'),
           'co': co, 'debug': DEBUG[-60:]}
    os.makedirs(BASE, exist_ok=True)
    json.dump(out, open(OUT, 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'))
    log('저장 %s — %d종목 · 시계열 %d · 분기점 %d · %ds'
        % (OUT, len(co), n_series, n_pts, time.time() - T0))
    return 0

if __name__ == '__main__':
    sys.exit(main())
