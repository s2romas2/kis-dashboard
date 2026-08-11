#!/usr/bin/env python3
# 실적 스크리닝 배치 — DART 재무로 3개 조건 중 하나라도 만족하는 종목 추출
# 조건1) 영업이익·매출 모두 YoY +10%↑ 그리고 QoQ +10%↑
# 조건2) 영업이익 최근 3분기 연속 증가(QoQ)
# 조건3) 최근 분기 영업이익 흑자전환(직전분기 적자→최근분기 흑자)
# 단일분기: Q1/Q2/Q3 = 당기금액(thstrm_amount, 이미 3개월치), Q4 = 연간 - 3분기누적(thstrm_add)
import os, io, sys, json, time, zipfile, urllib.request, datetime, xml.etree.ElementTree as ET

DART_KEY = os.environ.get('DART_KEY', '')
NOTE_CODES = set()  # 특장점 노트 종목(조건 미충족이어도 실적 포함) — main()에서 로드
UNIVERSE_LIMIT = int(os.environ.get('UNIVERSE_LIMIT', '0'))
UNIVERSE_OFFSET = int(os.environ.get('UNIVERSE_OFFSET', '0'))
CHUNK = int(os.environ.get('CHUNK', '50'))

def latest_period(today=None):
    # 정기보고서 제출기한이 지난 최신 분기를 자동 계산
    # Q1 분기보고서: 5/15까지, 반기보고서(Q2): 8/14까지, Q3 분기보고서: 11/14까지,
    # 사업보고서(Q4 확정): 다음해 3/31까지
    t = today or datetime.date.today()
    md = (t.month, t.day)
    if md >= (11, 15):
        return t.year, 3
    if md >= (8, 15):
        return t.year, 2
    if md >= (5, 16):
        return t.year, 1
    if md >= (4, 1):
        return t.year - 1, 4
    return t.year - 1, 3

_AY, _AQ = latest_period()
LATEST_YEAR = int(os.environ.get('LATEST_YEAR', _AY))
LATEST_Q = int(os.environ.get('LATEST_Q', _AQ))
REPRT = {1: '11013', 2: '11012', 3: '11014', 4: '11011'}
OP_NAMES = {'영업이익'}
REV_NAMES = {'매출액', '수익(매출액)', '영업수익'}
NI_NAMES = {'당기순이익', '당기순이익(손실)', '분기순이익', '반기순이익'}
EOK = 100000000.0

def http_json(url):
    for _ in range(3):
        try:
            with urllib.request.urlopen(url, timeout=20) as r:
                return json.loads(r.read().decode('utf-8'))
        except Exception:
            time.sleep(1)
    return {}

def get_listed_corps():
    with urllib.request.urlopen('https://opendart.fss.or.kr/api/corpCode.xml?crtfc_key=' + DART_KEY, timeout=60) as r:
        data = r.read()
    z = zipfile.ZipFile(io.BytesIO(data))
    root = ET.fromstring(z.read(z.namelist()[0]))
    out = []
    for it in root.iter('list'):
        sc = (it.findtext('stock_code') or '').strip()
        if len(sc) == 6 and sc.isdigit():
            out.append({'corp_code': it.findtext('corp_code').strip(),
                        'name': (it.findtext('corp_name') or '').strip(), 'stock_code': sc})
    return out

def to_num(s):
    try:
        return int(str(s).replace(',', '').strip())
    except Exception:
        return None

def fetch_report(corps, year, reprt_code):
    res = {}
    for i in range(0, len(corps), CHUNK):
        codes = ','.join(c['corp_code'] for c in corps[i:i+CHUNK])
        url = ('https://opendart.fss.or.kr/api/fnlttMultiAcnt.json?crtfc_key=%s&corp_code=%s&bsns_year=%d&reprt_code=%s'
               % (DART_KEY, codes, year, reprt_code))
        d = http_json(url)
        for it in d.get('list', []) or []:
            cc = it.get('corp_code'); nm = it.get('account_nm')
            q = to_num(it.get('thstrm_amount'))
            cum = to_num(it.get('thstrm_add_amount'))
            if cum is None:
                cum = q
            if cc is None or q is None:
                continue
            basis = 'CFS' if ('연결' in (it.get('fs_nm') or '') or it.get('fs_div') == 'CFS') else 'OFS'
            slot = res.setdefault(cc, {}).setdefault(basis, {})
            key = 'op' if nm in OP_NAMES else 'rev' if nm in REV_NAMES else 'ni' if nm in NI_NAMES else None
            if key and key not in slot:
                slot[key] = {'q': q, 'cum': cum}
        time.sleep(0.05)
    return res

def growth(cur, base):
    if cur is None or base is None or base == 0:
        return None
    return round((cur - base) / abs(base) * 100.0, 1)

def eok(v):
    return None if v is None else round(v / EOK)

def main():
    global NOTE_CODES
    if not DART_KEY:
        print('DART_KEY 필요'); sys.exit(1)
    try:  # 특장점 노트 종목: 조건 미충족이어도 실적 데이터 포함
        _sn = json.load(open('public/stocknotes.json', encoding='utf-8'))
        NOTE_CODES = {s['code'] for g in _sn.get('industries', []) for s in g.get('stocks', [])}
    except Exception:
        NOTE_CODES = set()
    corps = get_listed_corps()
    if UNIVERSE_OFFSET: corps = corps[UNIVERSE_OFFSET:]
    if UNIVERSE_LIMIT: corps = corps[:UNIVERSE_LIMIT]
    print('대상 상장사 %d개' % len(corps), file=sys.stderr)
    py = LATEST_YEAR - 1
    need = [(LATEST_YEAR, q) for q in range(1, LATEST_Q + 1)] + [(py, q) for q in range(1, 5)]
    data = {}
    for (yr, q) in need:
        data[(yr, q)] = fetch_report(corps, yr, REPRT[q])
        print('  수집 %dQ%d' % (yr, q), file=sys.stderr)

    def get(cc, yr, q, key, basis, field):
        node = data.get((yr, q), {}).get(cc, {}).get(basis, {}).get(key)
        return node.get(field) if node else None

    def single(cc, yr, q, key, basis):
        if q in (1, 2, 3):
            return get(cc, yr, q, key, basis, 'q')
        fy = get(cc, yr, 4, key, basis, 'q')
        nine = get(cc, yr, 3, key, basis, 'cum')
        if fy is None or nine is None:
            return None
        return fy - nine

    matches = []
    for c in corps:
        cc = c['corp_code']
        latest = data.get((LATEST_YEAR, LATEST_Q), {}).get(cc, {})
        basis = 'CFS' if ('CFS' in latest and 'op' in latest['CFS']) else 'OFS'
        plan = [(py, q) for q in range(1, 5)] + [(LATEST_YEAR, q) for q in range(1, LATEST_Q + 1)]
        labels, ops, revs, nis = [], [], [], []
        for (yr, q) in plan:
            labels.append('%dQ%d' % (yr, q))
            ops.append(single(cc, yr, q, 'op', basis))
            revs.append(single(cc, yr, q, 'rev', basis))
            nis.append(single(cc, yr, q, 'ni', basis))
        if len(ops) < 5 or ops[-1] is None or revs[-1] is None:
            continue
        lop, pop, yop = ops[-1], ops[-2], ops[-5]
        lrev, prevv, yrev = revs[-1], revs[-2], revs[-5]
        lni = nis[-1]
        conds = []
        g_opy, g_revy, g_opq, g_revq = growth(lop, yop), growth(lrev, yrev), growth(lop, pop), growth(lrev, prevv)
        if None not in (g_opy, g_revy, g_opq, g_revq) and yop > 0 and yrev > 0 and pop > 0 and prevv > 0:
            if g_opy >= 10 and g_revy >= 10 and g_opq >= 10 and g_revq >= 10:
                conds.append(1)
        last4 = ops[-4:]
        if None not in last4 and last4[1] > last4[0] and last4[2] > last4[1] and last4[3] > last4[2]:
            conds.append(2)
        if pop is not None and lop > 0 and pop < 0:
            conds.append(3)
        if not conds and c['stock_code'] not in NOTE_CODES:
            continue  # 특장점 노트 종목은 조건 미충족이어도 실적 표기용으로 포함(conds=[])
        validops = [o for o in ops if o is not None]
        year_high = bool(validops) and lop == max(validops)
        opq_series = [{'q': labels[i], 'op': eok(ops[i]), 'qoq': growth(ops[i], ops[i-1])} for i in range(1, len(ops))]
        table = [{'q': labels[i], 'rev': eok(revs[i]), 'op': eok(ops[i]), 'ni': eok(nis[i])} for i in range(len(labels))]
        matches.append({
            'code': c['stock_code'], 'name': c['name'], 'corp_code': cc,
            'period': '%dQ%d' % (LATEST_YEAR, LATEST_Q), 'conds': conds, 'basis': basis,
            'rev': eok(lrev), 'op': eok(lop), 'ni': eok(lni),
            'revYoY': g_revy, 'revQoQ': g_revq, 'opYoY': g_opy, 'opQoQ': g_opq,
            'niYoY': growth(lni, nis[-5]), 'niQoQ': growth(lni, nis[-2]),
            'opm': round(lop / lrev * 100, 1) if lrev else None,
            'npm': round(lni / lrev * 100, 1) if (lni is not None and lrev) else None,
            'yearHigh': year_high, 'opAnnual': eok(lop * 4), 'niAnnual': eok(lni * 4) if lni is not None else None,
            'opqSeries': opq_series, 'table': table,
        })
    # ── 잠정실적 오버레이: 정기보고서가 아직 없는 다음 분기를 잠정 공시로 선반영 ──
    # (반기·분기보고서가 나와 LATEST_Q가 넘어가면 해당 분기는 확정치로 자동 대체됨)
    try:
        fl = json.load(open('public/data/flash.json', encoding='utf-8'))
        ny, nq = (LATEST_YEAR + 1, 1) if LATEST_Q == 4 else (LATEST_YEAR, LATEST_Q + 1)
        tag = '%d Q%d' % (ny, nq)

        def infer_q(date8):  # 공시월로 대상 분기 추정 (잠정공시는 분기말 직후 발표)
            try:
                y, mth = int(date8[:4]), int(date8[4:6])
            except Exception:
                return None
            return {1: (y - 1, 4), 2: (y - 1, 4), 4: (y, 1), 5: (y, 1),
                    7: (y, 2), 8: (y, 2), 10: (y, 3), 11: (y, 3)}.get(mth)
        fmap = {}
        for it in fl.get('list', []):
            p = (it.get('period') or '').strip()
            tq = None
            if p:
                m2 = None
                import re as _re
                m2 = _re.match(r'(\d{4})\s*Q(\d)', p)
                if m2:
                    tq = (int(m2.group(1)), int(m2.group(2)))
            else:
                tq = infer_q(it.get('date', ''))
            if tq != (ny, nq):
                continue
            if it['code'] not in fmap or (it.get('date') or '') > (fmap[it['code']].get('date') or ''):
                fmap[it['code']] = it
        byc = {m['code']: m for m in matches}
        n_upd = n_new = 0
        for code, it in fmap.items():
            row = {'period': '%dQ%d' % (ny, nq), 'flash': True, 'basis': '잠정',
                   'rev': it.get('rev'), 'op': it.get('op'), 'ni': it.get('ni'),
                   'revYoY': it.get('revYoY'), 'revQoQ': it.get('revQoQ'),
                   'opYoY': it.get('opYoY'), 'opQoQ': it.get('opQoQ'),
                   'niYoY': it.get('niYoY'), 'niQoQ': it.get('niQoQ'),
                   'opm': round(it['op'] / it['rev'] * 100, 1) if (it.get('rev') and it.get('op') is not None) else None,
                   'npm': round(it['ni'] / it['rev'] * 100, 1) if (it.get('rev') and it.get('ni') is not None) else None,
                   'link': it.get('link'), 'rptNm': '영업(잠정)실적 공시', 'rceptDt': it.get('date', '')}
            g = [row.get(k) for k in ('opYoY', 'revYoY', 'opQoQ', 'revQoQ')]
            cond1 = (None not in g) and all(x >= 10 for x in g) and (row.get('op') or 0) > 0
            if code in byc:
                m = byc[code]
                m.update(row)
                if cond1 and 1 not in m['conds']:
                    m['conds'] = sorted(set(m['conds'] + [1]))
                n_upd += 1
            elif cond1:
                matches.append(dict(row, code=code, name=it.get('name', code), corp_code='',
                                    conds=[1], yearHigh=False, opAnnual=round((it.get('op') or 0) * 4),
                                    niAnnual=None, opqSeries=[], table=[]))
                n_new += 1
        print('잠정 오버레이 %s: 교체 %d건, 신규 %d건 (잠정풀 %d)' % (tag, n_upd, n_new, len(fmap)), file=sys.stderr)
    except Exception as e:
        print('잠정 오버레이 실패: %r' % e, file=sys.stderr)

    # 각 매칭 종목의 최신 정기보고서 공시링크
    if os.environ.get('FETCH_LINKS', '1') == '1':
        yend = time.strftime('%Y%m%d'); ybgn = str(int(time.strftime('%Y')) - 1) + time.strftime('%m%d')
        for m in matches:
            if m.get('flash'):  # 잠정 행은 공시 링크가 이미 있음
                continue
            u = ('https://opendart.fss.or.kr/api/list.json?crtfc_key=%s&corp_code=%s&bgn_de=%s&end_de=%s&pblntf_ty=A&page_count=1&sort=date&sort_mth=desc'
                 % (DART_KEY, m['corp_code'], ybgn, yend))
            d = http_json(u); lst = d.get('list') or []
            m['link'] = ('https://dart.fss.or.kr/dsaf001/main.do?rcpNo=' + lst[0].get('rcept_no', '')) if lst else 'https://dart.fss.or.kr'
            m['rptNm'] = lst[0].get('report_nm', '').strip() if lst else ''
            m['rceptDt'] = lst[0].get('rcept_dt', '') if lst else ''
            time.sleep(0.03)
    matches.sort(key=lambda m: (m['opQoQ'] if m['opQoQ'] is not None else -9999), reverse=True)
    kst = time.strftime('%Y-%m-%d %H:%M', time.gmtime(time.time() + 9 * 3600))
    out = {'updated': kst, 'period': '%dQ%d' % (LATEST_YEAR, LATEST_Q),
           'universe': len(corps), 'count': sum(1 for m in matches if m['conds']), 'list': matches}
    os.makedirs('public/data', exist_ok=True)
    with open('public/data/screener.json', 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False)
    print('매칭 %d / 대상 %d' % (len(matches), len(corps)), file=sys.stderr)
    for m in matches[:25]:
        print('%s %-13s 조건%s 매출%s(YoY%s/QoQ%s) 영업%s(YoY%s/QoQ%s)%s' % (
            m['code'], m['name'][:11], m['conds'], m['rev'], m['revYoY'], m['revQoQ'],
            m['op'], m['opYoY'], m['opQoQ'], ' [연중최고]' if m['yearHigh'] else ''))

if __name__ == '__main__':
    main()
