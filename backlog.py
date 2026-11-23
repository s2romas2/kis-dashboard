# -*- coding: utf-8 -*-
"""
반도체 peer — 수주잔고 분기 시계열(과거 12개 분기) + 분기 매출 + 잔고→매출 인식 재료
    결과: public/data/semipeer_backlog.json   (화면: public/semipeer.html 의 "📦 수주잔고" 구획)

무엇을 보려는 건가
    수주잔고는 "앞으로 매출로 바뀔 일감"이다. 한 시점의 금액만으로는 뜻이 약하다.
      ① 분기마다 잔고가 어떻게 늘고 줄었나           → s[] (분기 말 잔고)
      ② 그 잔고가 매출과 같이 움직이나               → rev{} (같은 분기의 매출, DART 주요계정)
      ③ 새 주문이 얼마나 들어왔나                    → 표에 있으면 nq(확인), 없으면 화면이 "기말 − 기초 + 매출"로 계산
      ④ 언제 매출이 되나                             → items[](잔고 표의 납기) · recog(공급계약 공시의 납기)

v1 이 한 분기만 남긴 까닭(2026-11-20 확인)
    · valfacts.ddoc() 는 {파일명: 본문} dict 를 돌려주는데 v1 은 그 dict 를 parse_biz(문자열 전용)에 그대로 넘겼다.
      → TypeError 가 `except Exception: continue` 에 묻혀 모든 보고서가 "잔고 없음"이 됐다(두 번 실행 55·59분, 분기점 0개).
    · 워크플로가 밀어 올린 커밋이 충돌해도 `|| true` 로 지나가서 실패가 드러나지 않았다.
    · 그래서 화면에는 손으로 넣은 임시본(최신 보고서 1개 시점)만 남아 있었다.

어떻게 채우나
    종목마다 정기보고서 목록(1콜)을 받아 최근 NQ(12)개 분기의 사업·반기·분기보고서 원문을 거슬러 올라가며 읽는다.
    · 분기마다 "받았음"을 done{분기: {rc, st, pv}} 에 적는다 → 같은 접수번호는 다시 받지 않는다(정정본이 나오면 접수번호가 달라져 다시 받는다).
    · 네트워크 실패(DartFail)는 done 에 적지 않는다 → 다음 실행이 이어받는다. "표에 잔고 없음"은 st 로 구분해 적는다.
    · 새로 읽은 값이 비어 있으면 기존 값을 덮어쓰지 않는다.
    · 최신 보고서에 수주 표가 없는 회사는 과거 보고서를 받지 않는다(호출 절약). 표가 생기면 그때 거슬러 올라간다.
    · 시간 예산(BL_BUDGET 초)을 넘기면 저장하고 끝낸다. 워크플로가 새 러너에서 이어 돈다.

수주상황 표 형식(회사마다 다르다) — classify() 가 머리글로 열의 뜻을 읽는다
    A  수주총액 · 기납품액 · 수주잔고      → 잔고(+총액·기납품: 진행 중 계약의 누계라 분기 신규 수주로 쓰지 않는다)
    B  기초 · 신규(증가) · 매출(감소) · 기말 → 잔고 + 신규 수주 + 매출 인식(누적이면 분기 차로 바꾼다). 행·열이 뒤집힌 표도 읽는다
    C  신규 수주 · 매출 · 기말 잔고(기초 없음) → 잔고 + 신규 수주 + 매출 인식(전기말 잔고와 맞는지 검산한 뒤에만 쓴다)
    D  잔고만(품목별 잔고)                  → 잔고
    E  계약금액 · 누적 공급액(잔고 열 없음)  → 잔고 = 계약금액 − 누적 공급액(계산 표시 cb)
    F  수주 · 매출 흐름만(잔고 없음)         → 잔고 없음(st=flow), 신규 수주·매출만 기록
    단위는 표 머리(단위 : 백만원/천원/억원/원)에서 읽어 억원으로 바꾼다. 달러 등 외화는 바꾸지 않고 sx[] 에 원문 숫자만 남긴다.

환경변수
    DART_API_KEY 또는 DART_KEY · BL_BUDGET(초, 기본 3300) · BL_NQ(분기 수, 기본 12) · ONLY(쉼표 종목코드)
    OFFLINE=1  DART 를 부르지 않고 public/data/vf/<코드>.json 에 저장된 최신 보고서의 수주 표만으로 임시본을 만든다
"""
import datetime, json, os, re, sys, time, urllib.parse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import valfacts as V                      # api · ddoc · _table · _txt · HEAD · fetch 재사용

PV = 2                                    # 파서 버전 — 올리면 다음 실행에서 원문을 다시 받는다
BASE = os.environ.get('BASE', 'public/data')
OUT = os.environ.get('BL_OUT', os.path.join(BASE, 'semipeer_backlog.json'))
NQ = int(os.environ.get('BL_NQ', '12'))
BUDGET = float(os.environ.get('BL_BUDGET', '3300'))
OFFLINE = os.environ.get('OFFLINE', '') == '1'
ONLY = [c for c in os.environ.get('ONLY', '').split(',') if c]
T0 = time.time()
DEBUG = []
STAT = {'list': 0, 'doc': 0, 'rev': 0, 'new_pts': 0, 'kept': 0, 'fail': 0}

def log(s):
    DEBUG.append(str(s)[:300]); print(s, file=sys.stderr, flush=True)
def left(): return BUDGET - (time.time() - T0)

# ════════════════════════════════════════════════════════════════════════════
# 1. 수주상황 표 파서 — 입력은 valfacts._table() 이 만드는 행 목록(셀 = '글자' 또는 ['글자', colspan, rowspan])
# ════════════════════════════════════════════════════════════════════════════
def _ct(c): return c if isinstance(c, str) else c[0]
def _sp(s): return re.sub(r'\s+', '', s or '')

_NUM = re.compile(r'^[\(\[]?[△▲−–\-]?[$＄₩￦]?\d{1,3}(,\d{3})+(\.\d+)?[\)\]]?$|^[\(\[]?[△▲−–\-]?[$＄₩￦]?\d+(\.\d+)?[\)\]]?$')
def num(s):
    """표의 숫자 칸 → float. 날짜·글자·빈칸·'-' 는 None. (1,234)·△1,234·-1,234 는 음수."""
    t = _sp(_ct(s) if not isinstance(s, str) else s)
    t = re.sub(r'(USD|원|주\d*\)|\(주\d*\)|\*+)$', '', t)
    if not t or not _NUM.match(t): return None
    neg = bool(re.match(r'^[\(\[]|^[\(\[]?[△▲−–\-]', t))
    v = float(re.sub(r'[^\d.]', '', t))
    return -v if neg else v
def isdash(s):
    return _sp(_ct(s) if not isinstance(s, str) else s) in ('-', '–', '−', '—', '', 'N/A', 'n/a', '해당없음')

def grid(rows):
    """colspan·rowspan 을 풀어 네모난 격자로 만든다 — 열 위치로 뜻을 읽기 위해서."""
    out, carry = [], {}                       # carry[col] = (남은 행 수, 글자)
    for r in rows:
        line, ci, cells = [], 0, list(r)
        while True:
            if ci in carry:
                n, t = carry[ci]; line.append(t)
                if n <= 1: del carry[ci]
                else: carry[ci] = (n - 1, t)
                ci += 1; continue
            if not cells:
                if any(k > ci for k in carry): line.append(''); ci += 1; continue
                break
            c = cells.pop(0)
            t, cs, rs = (c, 1, 1) if isinstance(c, str) else (c[0], max(1, int(c[1])), max(1, int(c[2])))
            for k in range(cs):
                line.append(t)
                if rs > 1: carry[ci] = (rs - 1, t)
                ci += 1
        out.append(line)
    w = max((len(l) for l in out), default=0)
    return [l + [''] * (w - len(l)) for l in out]

FOREIGN = re.compile(r'USD|US\$|U\$|\$|＄|달러|미화|불$|EUR|유로|JPY|엔화|CNY|RMB|위안', re.I)
def unit_of(text):
    """단위 글자 → (억원 환산 배수 또는 None, 통화 또는 None, 단위 표기). 외화는 배수 None."""
    t = _sp(text)
    i = t.find('단위')
    seg = t[i:] if i >= 0 else t
    if FOREIGN.search(seg):
        m = re.search(r'(백만|천|1,000|1000|십만|만)?(USD|US\$|U\$|\$|＄|달러|불|EUR|유로|JPY|엔화|CNY|RMB|위안)', seg, re.I)
        t2 = m.group(2) if m else 'USD'
        cur = 'JPY' if re.search(r'JPY|엔', t2, re.I) else 'EUR' if re.search(r'EUR|유로', t2, re.I) else 'CNY' if re.search(r'CNY|RMB|위안', t2, re.I) else 'USD'
        return None, cur, (m.group(0) if m else 'USD')
    m = re.search(r'(조|십억|억|천만|백만|십만|만|천)?원', seg)
    if not m: return None, None, ''
    mul = {'조': 1e4, '십억': 10.0, '억': 1.0, '천만': 0.1, '백만': 0.01, '십만': 1e-3, '만': 1e-4, '천': 1e-5, None: 1e-8}[m.group(1)]
    return mul, 'KRW', (m.group(1) or '') + '원'

TOTAL = re.compile(r'합계|총계|총합|^계$|^전체$|^전사$|total', re.I)
SUBTOT = re.compile(r'^소계$|^계$|^합계$|^총계$')
def role(label):
    """열(또는 행) 머리글 → 뜻. end 기말잔고 · beg 기초잔고 · new 신규수주 · rec 기간 매출인식 · tot 수주총액 · dlv 기납품(누계) · adj 기타증감 · due 납기 · qty 수량"""
    L = _sp(label)
    if not L: return None
    if re.fullmatch(r'품목|품명|제품|제품명|구분|계약명|계약내역|내역|비고|.*처|.*고객(사|명)?|.*상대방?|.*지역', L): return None
    if re.search(r'수량|물량|면적|개수|대수|건수', L) and '금액' not in L: return 'qty'
    if re.search(r'수령|입금|선수금|청구|회수|비고|비율|%', L): return None
    if re.search(r'잔고|잔액|잔량|기말', L):
        return 'beg' if re.search(r'기초|전기|전년|전분기|전반기|직전|이월', L) else 'end'
    if re.search(r'기초|전기말|전년말|전기이월|이월', L): return 'beg'
    if re.search(r'(?<![당분반])기납품|(?<![당분반전])기매출|누적|누계', L): return 'dlv'
    if re.search(r'신규|당기수주|당분기수주|당반기수주|증가', L): return 'new'
    if re.search(r'연결범위|환율|기타증감|조정', L): return 'adj'
    if re.search(r'납기|납품기간|납품일|계약종료|종료일|인도', L): return 'due'
    if re.search(r'수주총액|수주금액|수주액|계약금액|계약총액|도급금액|도급액', L): return 'tot'
    if re.search(r'매출|수익|납품|공급|인식|감소|기성', L): return 'rec'
    return None

TYNAME = {'A': '수주총액·기납품·잔고', 'B': '기초·신규·매출·기말', 'C': '신규수주·매출·잔고', 'D': '잔고만',
          'E': '계약금액−누적 공급(계산)', 'F': '수주·매출 흐름만(잔고 없음)', 'X': '형식 미인식'}
def _due(s):
    """납기 칸 → 'YYYY-MM-DD' / 'YYYY-MM' / 'YYYY' (범위면 끝 날짜). 못 읽으면 ''"""
    t = _ct(s) if not isinstance(s, str) else s
    ms = list(re.finditer(r'(\d{4}|\d{2})\s*[.\-/년]\s*(\d{1,2})(?:\s*[.\-/월]\s*(\d{1,2}))?', t))
    if ms:
        m = ms[-1]; y = int(m.group(1)); y = y + 2000 if y < 100 else y; mo = int(m.group(2))
        if 1 <= mo <= 12 and 2000 <= y <= 2100:
            return '%d-%02d-%02d' % (y, mo, int(m.group(3))) if m.group(3) and 1 <= int(m.group(3)) <= 31 else '%d-%02d' % (y, mo)
    ys = re.findall(r'(20\d{2})\s*년', t)
    return ys[-1] if ys else ''

def classify(rows, unit='', head=''):
    """수주상황 표 한 개 → {'ty','st','eok'|'raw', 'tot','dlv','beg','new','rec','adj', 'u','cur','sm','cb','items'}
    st: ok(억원 잔고) · usd(외화 — 환산하지 않음) · unit(단위를 못 읽음) · blank(잔고 칸이 비어 있음) · flow(잔고 없이 흐름만) · none(수주 표로 읽히지 않음)"""
    if not rows or len(rows) < 2: return {'ty': 'X', 'st': 'none'}
    g = grid(rows)
    nh = 1
    while nh < min(3, len(g) - 1) and not any(num(c) is not None for c in g[nh]): nh += 1
    hdr, data = g[:nh], g[nh:]
    w = len(g[0])
    labels = []
    for ci in range(w):
        parts = []
        for hr in hdr:
            t = _sp(hr[ci])
            if t and (not parts or parts[-1] != t): parts.append(t)
        labels.append('/'.join(parts))
    roles = [role(l) for l in labels]
    cols = {}
    for ci, r in enumerate(roles):
        if r and r not in ('qty',) and r not in cols: cols[r] = ci
    vals, sm, items, transposed = {}, False, [], False
    if 'end' not in cols:
        # 행·열이 뒤집힌 표(구분 | 당분기 | 전기 / 기초·신규·수익·기말 이 행으로)
        rr = {}
        for r in g:
            k = role(r[0])
            if k in ('beg', 'new', 'rec', 'end', 'adj') and k not in rr: rr[k] = r
        if 'end' in rr and len(rr) >= 2:
            vc = next((ci for ci in range(1, w) if num(rr['end'][ci]) is not None), None)
            if vc is not None:
                transposed = True
                vals = {k: num(r[vc]) for k, r in rr.items()}
                hdr = g[:1]
    if not transposed:
        vcols = {k: c for k, c in cols.items() if k not in ('due',)}
        if not vcols: return {'ty': 'X', 'st': 'none'}
        lab_cols = [ci for ci in range(w) if roles[ci] is None]
        def labs(r): return [_sp(r[ci]) for ci in lab_cols if _sp(r[ci])]
        tots = [r for r in data if any(TOTAL.search(x) for x in labs(r))]
        pick = None
        if len(tots) == 1: pick = tots[0]
        elif len(tots) > 1:
            pure = [r for r in tots if all(SUBTOT.match(x) or TOTAL.search(x) for x in labs(r))]
            if len(pure) == 1: pick = pure[0]
            else:
                key = cols.get('end', cols.get('new', cols.get('tot')))
                pick = max(pure or tots, key=lambda r: abs(num(r[key]) or 0))
        body = [r for r in data if r is not pick and not any(TOTAL.search(x) for x in labs(r))]
        if pick is None:
            subs = [r for r in data if any(x == '소계' for x in labs(r))]
            kc = cols.get('end', cols.get('new', cols.get('tot')))
            if subs: use = subs; body = [r for r in data if r not in subs]
            else:
                use = data
                # 이름 없는 합계 행: 마지막 행이 나머지의 합과 같으면 합계로 본다
                if len(data) >= 2 and kc is not None:
                    last = num(data[-1][kc]); rest = [num(r[kc]) for r in data[:-1]]; rs = sum(x for x in rest if x is not None)
                    spans = isinstance(rows[-1][0], list) and rows[-1][0][1] >= 2
                    if last is not None and rs and abs(last - rs) <= max(2.0, abs(rs) * 0.005) and (spans or sum(1 for x in rest if x) >= 2):
                        pick = data[-1]; body = data[:-1]
            if pick is None:
                sm = len(use) > 1
                for k, c in vcols.items():
                    xs = [num(r[c]) for r in use]; xs = [x for x in xs if x is not None]
                    vals[k] = sum(xs) if xs else None
                vals['_dash'] = {k for k, c in vcols.items() if all(isdash(r[c]) for r in use)}
        if pick is not None:
            for k, c in vcols.items(): vals[k] = num(pick[c])
            vals['_dash'] = {k for k, c in vcols.items() if isdash(pick[c])}
            # 합계 행의 잔고 칸이 비었는데 품목 행에는 숫자가 있으면 품목을 더한다
            if vals.get('end') is None and 'end' in vcols:
                xs = [num(r[vcols['end']]) for r in body]; xs = [x for x in xs if x is not None]
                if xs: vals['end'] = sum(xs); sm = True; vals['_dash'].discard('end')
        # 품목(계약)별 남은 잔고와 납기 — "언제 매출이 되나"의 재료
        if 'end' in vcols:
            tc = lab_cols[0] if lab_cols else None
            for r in body:
                v = num(r[vcols['end']])
                if not v or v <= 0 or any(SUBTOT.match(x) for x in labs(r)): continue
                items.append({'t': (r[tc] if tc is not None else '')[:30], 'due': _due(r[cols['due']]) if 'due' in cols else '', 'raw': v})
    dash = vals.pop('_dash', set())
    for k in ('rec', 'dlv'):
        if vals.get(k) is not None: vals[k] = abs(vals[k])          # (227,400) 처럼 괄호로 적은 차감액
    # 수주금액 + 매출금액만 있는 표(잔고·기납품 없음)는 그 기간의 수주 흐름이다
    if vals.get('tot') is not None and 'dlv' not in vals and 'end' not in vals and 'beg' not in vals and vals.get('rec') is not None and 'new' not in vals:
        vals['new'] = vals.pop('tot')
    has = lambda k: vals.get(k) is not None
    # 전기 잔고 | 수주총액 | 기납품액 | 잔고 처럼 기초 잔고가 같이 있으면, 총액·기납품은 누계가 아니라 그 기간의 수주·납품이다(기초 + 수주 − 납품 = 기말 로 검산)
    if has('beg') and has('tot') and has('dlv') and has('end') and 'new' not in vals and 'rec' not in vals \
            and abs(vals['beg'] + vals['tot'] - vals['dlv'] - vals['end']) <= max(2.0, abs(vals['end']) * 0.02):
        vals['new'] = vals.pop('tot'); vals['rec'] = vals.pop('dlv')
    cb = False
    if 'end' not in vals and has('tot') and ('dlv' in vals):
        vals['end'] = vals['tot'] - (vals.get('dlv') or 0); cb = True; ty = 'E'
    elif 'end' in vals:
        ty = 'B' if 'beg' in vals else 'C' if (has('new') or has('rec')) else 'A' if (has('tot') and 'dlv' in vals) else 'D'
    elif has('new'): ty = 'F'
    else: return {'ty': 'X', 'st': 'none'}
    # 단위: ① 머리글 칸 안의 (단위: 원) ② 표 위 단위 줄 ③ 칸에 $ 가 박혀 있으면 외화
    hu = next((c for hr in hdr for c in hr if '단위' in c), '')
    mul, cur, ulab = unit_of(hu) if hu else (None, None, '')
    if mul is None and cur is None: mul, cur, ulab = unit_of(unit or '')
    flat = ' '.join(c for r in data for c in r)
    if cur is None and re.search(r'[$＄]\s*\d', flat): mul, cur, ulab = None, 'USD', 'USD'
    out = {'ty': ty, 'u': (unit or hu or '').strip()[:40], 'cur': cur, 'ul': ulab}
    if sm: out['sm'] = 1
    if cb: out['cb'] = 1
    if transposed: out['tr'] = 1
    if re.search(r'별도', (unit or '') + ' ' + (head or '')): out['sep'] = 1
    end = vals.get('end')
    conv = (lambda v: None if v is None else round(v * mul, 1)) if mul else (lambda v: None)
    if ty == 'F': st = 'flow'
    elif end is None:
        if 'end' in dash and has('tot') and (vals.get('dlv') is not None) and abs(vals['tot'] - vals['dlv']) <= max(1.0, abs(vals['tot']) * 1e-4):
            end = 0.0; st = None                                       # 수주총액 = 기납품액 → 잔고 0 이 맞다
        else: st = 'blank'
    else: st = None
    if st is None: st = 'usd' if (cur and cur != 'KRW') else 'unit' if not mul else 'ok'
    out['st'] = st
    for k in ('tot', 'dlv', 'beg', 'new', 'rec', 'adj'):
        if has(k):
            if mul: out[k] = conv(vals[k])
            else: out['r_' + k] = vals[k]
    if end is not None:
        out['raw'] = end
        if st == 'ok': out['eok'] = conv(end)
    if items and st == 'ok':
        items.sort(key=lambda x: -x['raw'])
        out['items'] = [{'t': it['t'], 'due': it['due'], 'eok': conv(it['raw'])} for it in items[:14]]
    return out

# ════════════════════════════════════════════════════════════════════════════
# 2. 정기보고서 원문 → 수주상황 표 후보들
# ════════════════════════════════════════════════════════════════════════════
NEXT = r'^\d+\.\s|^(I|V|X|Ⅰ|Ⅱ|Ⅲ|Ⅳ|Ⅴ)+\.'
ORDHEAD = re.compile(r'수주|계약\s*잔액|계약잔고')
OTHERHEAD = re.compile(r'매출\s*실적|매출\s*현황|판매\s*(경로|방법|전략|조건)|주요\s*(매출처|고객|거래처)|가격')
def order_tables(raw):
    """원문(문자열)에서 '매출 및 수주상황' 구간의 수주 표 후보를 순서대로 → ([(소제목, 단위, 행)], 회사 설명 문장)"""
    ts = [(m.start(), m.end(), V._txt(m.group(1))) for m in re.finditer(r'<TITLE[^>]*>(.*?)</TITLE>', raw, flags=re.S | re.I)]
    s = next((i for i, t in enumerate(ts) if re.search(r'매출\s*및\s*수주상황|매출에\s*관한\s*사항|수주\s*상황', t[2])), -1)
    if s < 0: return [], '', False
    e = next((ts[i][0] for i in range(s + 1, len(ts)) if re.search(NEXT, ts[i][2])), None)
    seg = raw[ts[s][1]: e if e else ts[s][1] + 300000]
    cands, head, unit, note, inord = [], '', '', '', False
    for m in re.finditer(r'<P[^>]*>(.*?)</P>|<TABLE[^>]*>.*?</TABLE>', seg, flags=re.S | re.I):
        if m.group(0)[:2].upper() == '<P':
            v = V._txt(m.group(1))
            if not v: continue
            ishead = (len(v) <= 45 and bool(V.HEAD.search(v))) or (len(v) > 45 and bool(V.HEAD.search(v)) and bool(re.search(r'수주|매출\s*실적|판매', v[:16]))) \
                     or (len(v) <= 30 and bool(re.search(r'수주\s*(상황|현황|잔고|계약|에\s*관한)', v)) and not v.endswith('다.'))
            if ishead:
                hv = v[:20] if len(v) > 45 else v
                if ORDHEAD.search(hv):
                    inord = True; head = v[:40]; unit = ''
                    if len(v) > 45: note = note or v[:300]
                elif re.match(r'^\(?[가-하]\)?\.', v) or OTHERHEAD.search(hv): inord = False; head = v[:40]; unit = ''
                else: unit = ''                                  # 수주 구간 안의 하위 소제목(사업부 이름 등)
            elif '단위' in v and len(v) < 60: unit = v
            elif inord and len(note) < 260: note = (note + ' ' + v).strip()[:300]
            continue
        rows = V._table(m.group(0), 400, 16)
        flat = ' '.join(_ct(c) for r in rows for c in r)
        if len(rows) <= 2 and '단위' in flat and len(flat) < 80: unit = flat; continue
        if not rows or not inord: continue
        if not V._isdata(rows): continue
        cands.append((head[:40], unit[:60], rows))
    if not note:
        for m in re.finditer(r'<P[^>]*>(.*?)</P>', seg, flags=re.S | re.I):
            v = V._txt(m.group(1))
            if '수주' in v and re.search(r'해당|없습니다|없음', v): note = v[:200]; break
    return cands, note, True

RANK = {'ok': 0, 'usd': 1, 'unit': 2, 'blank': 3, 'flow': 4, 'none': 9}
def pick_table(cands):
    """후보 가운데 잔고가 읽히는 첫 표. 없으면 가장 나은 것."""
    best = None
    for i, (head, unit, rows) in enumerate(cands):
        try: r = classify(rows, unit, head)
        except Exception as e:
            log('  표 해석 예외 %r' % (str(e)[:80],)); continue
        if r['st'] == 'none': continue
        r['_i'] = i; r['_head'] = head; r['_unit'] = unit; r['_rows'] = rows
        if r['st'] == 'ok': return r
        if best is None or RANK[r['st']] < RANK[best['st']]: best = r
    return best

# ════════════════════════════════════════════════════════════════════════════
# 3. 분기 라벨·보고서 목록
# ════════════════════════════════════════════════════════════════════════════
def qlabel(y, mm):
    q = {3: 1, 6: 2, 9: 3, 12: 4}.get(mm)
    if not q: return None, None
    return '%dQ%d' % (y, q), '%d-%s' % (y, {1: '03-31', 2: '06-30', 3: '09-30', 4: '12-31'}[q])
def qprev(lab, n=1):
    y, q = int(lab[:4]), int(lab[5]); k = y * 4 + (q - 1) - n
    return '%dQ%d' % (k // 4, k % 4 + 1)
def qfrom_short(s):
    """semipeer.json 의 '3Q26' → '2026Q3'"""
    m = re.match(r'^(\d)Q(\d{2})$', s or '')
    return '20%sQ%s' % (m.group(2), m.group(1)) if m else None

def reports(corp):
    """최근 NQ 분기의 정기보고서 → [(접수번호, 연, 월, 종류)] 오름차순. 같은 분기의 정정본은 접수번호가 가장 큰(마지막) 것."""
    end = time.strftime('%Y%m%d')
    beg = time.strftime('%Y%m%d', time.localtime(time.time() - (NQ * 92 + 200) * 86400))
    out, page = [], 1
    while page <= 3:
        rows = V.api('list', corp_code=corp, bgn_de=beg, end_de=end, pblntf_ty='A', page_no=page, page_count=100)
        STAT['list'] += 1
        if not rows: break
        for r in rows:
            nm = r.get('report_nm') or ''
            if '[첨부' in nm: continue
            m = re.search(r'(사업|반기|분기)보고서\s*\((\d{4})\.(\d{2})\)', nm)
            if m: out.append((r['rcept_no'], int(m.group(2)), int(m.group(3)), m.group(1)))
        if len(rows) < 100: break
        page += 1
    return pick_reports(out)
def pick_reports(out):
    best = {}
    for rc, y, mm, kind in out:
        if (y, mm) not in best or rc > best[(y, mm)][0]: best[(y, mm)] = (rc, kind)
    lst = sorted(((rc, y, mm, kind) for (y, mm), (rc, kind) in best.items()), key=lambda t: (t[1], t[2]))
    lst = [t for t in lst if qlabel(t[1], t[2])[0]]
    return lst[-NQ:]
KIND = {'사업': 'A', '반기': 'H', '분기': 'Q'}
def fiscal_q(kind, mm, fy_end):
    """보고서 종류 → 회계연도 안에서 몇 번째 분기 말인가(사업 4 · 반기 2 · 분기 1 또는 3)"""
    if kind == '사업': return 4
    if kind == '반기': return 2
    return 1 if (mm - fy_end) % 12 == 3 else 3

# ════════════════════════════════════════════════════════════════════════════
# 4. 시계열 다듬기 — QoQ·YoY, 누적 흐름을 분기 값으로
# ════════════════════════════════════════════════════════════════════════════
def pct(cur, prev):
    if cur is None or prev is None or prev <= 0: return None
    return round((cur / prev - 1) * 100, 1)
def _close(a, b):
    return a is not None and b is not None and abs(a - b) <= max(0.6, abs(b) * 0.02)

def finish_series(ser):
    """ser: 분기 라벨 오름차순 점 목록. QoQ·YoY 는 '바로 앞 분기'·'꼭 4분기 전' 라벨이 있을 때만.
    B·C 형식의 신규 수주(new)·매출 인식(rec)은 보고서가 누적(연초부터)으로 적는 경우가 많다 → 기초 잔고가 전기말 잔고와 맞으면 누적으로 보고 분기 차를 낸다."""
    by = {p['q']: p for p in ser}
    for p in ser:
        a, b = by.get(qprev(p['q'])), by.get(qprev(p['q'], 4))
        p['qoq'] = pct(p.get('eok'), a.get('eok')) if a else None
        p['yoy'] = pct(p.get('eok'), b.get('eok')) if b else None
        for k in ('nq', 'rq', 'fb'): p.pop(k, None)
    for p in ser:
        if p.get('new') is None and p.get('rec') is None: continue
        fq = p.get('fq') or int(p['q'][5])
        prevq = by.get(qprev(p['q'])); pye = by.get(qprev(p['q'], fq))
        nw, rc, adj, end = p.get('new'), p.get('rec'), p.get('adj') or 0, p.get('eok')
        if fq == 1: fb = 'q'
        elif p.get('beg') is not None:
            fb = 'ytd' if (pye and _close(p['beg'], pye.get('eok'))) else 'q' if (prevq and _close(p['beg'], prevq.get('eok'))) else None
            if fb is None and not pye and not prevq: fb = None
        elif nw is not None and rc is not None and end is not None:
            fb = 'ytd' if (pye and _close(pye.get('eok', 0) + nw - rc + adj, end)) else 'q' if (prevq and _close(prevq.get('eok', 0) + nw - rc + adj, end)) else None
        else: fb = None
        if not fb: continue
        p['fb'] = fb
    for p in ser:
        fb = p.get('fb')
        if not fb: continue
        fq = p.get('fq') or int(p['q'][5])
        if fb == 'q' or fq == 1:
            if p.get('new') is not None: p['nq'] = p['new']
            if p.get('rec') is not None: p['rq'] = p['rec']
            continue
        a = by.get(qprev(p['q']))
        if not a or not a.get('fb'): continue
        afq = a.get('fq') or int(a['q'][5])
        if a['fb'] == 'ytd' or afq == 1:
            if p.get('new') is not None and a.get('new') is not None: p['nq'] = round(p['new'] - a['new'], 1)
            if p.get('rec') is not None and a.get('rec') is not None: p['rq'] = round(p['rec'] - a['rec'], 1)
    return ser

def recognition(vf, ttm_rev, last_eok, today=None):
    """공급계약 공시(valfacts 가 모아 둔 vf.con.list)로 본 납기 분포·분기별 신규 계약, 잔고 커버리지."""
    out = {}
    if ttm_rev and ttm_rev > 0 and last_eok is not None:
        out['cover_q'] = round(last_eok / (ttm_rev / 4), 2)
        out['cover_pct'] = round(last_eok / ttm_rev * 100, 1)
    con = (vf or {}).get('con') or {}
    items = con.get('list') or []
    today = today or time.strftime('%Y-%m-%d')
    by_year, open_sum, due, cq, cqn, dates = {}, 0.0, [], {}, {}, []
    for it in items:
        if not isinstance(it, dict): continue
        amt = it.get('amt')
        if amt is None: continue
        cd = (it.get('cd') or it.get('first') or it.get('d') or '')[:10]
        if re.match(r'\d{4}-\d{2}-\d{2}', cd):
            lab = '%sQ%d' % (cd[:4], (int(cd[5:7]) - 1) // 3 + 1)
            cq[lab] = round(cq.get(lab, 0) + amt, 1); cqn[lab] = cqn.get(lab, 0) + 1; dates.append(cd)
        end = (it.get('to') or '')[:10]
        if not re.match(r'\d{4}-\d{2}-\d{2}', end or ''): continue
        if end >= today:
            open_sum += amt
            due.append({'t': (it.get('item') or '')[:30], 'eok': amt, 'end': end, 'cp': (it.get('cp') or '')[:18]})
        by_year[end[:4]] = round(by_year.get(end[:4], 0) + amt, 1)
    if by_year: out['by_year'] = by_year
    if due:
        due.sort(key=lambda d: d['end'])
        out['open_eok'] = round(open_sum, 1); out['due'] = due[:12]
    if cq:
        out['cq'] = cq; out['cq_n'] = cqn; out['cq_from'] = min(dates)
        out['cq_hidden'] = (con.get('sum') or {}).get('hidden') or 0
        out['cq_cancel'] = len((con.get('sum') or {}).get('cancel') or [])
    return out or None

# ════════════════════════════════════════════════════════════════════════════
# 5. 분기 매출(억원) — OpenDART 다중회사 주요계정. hege.py 와 같은 규칙(연결 우선, 3개월 값 우선·없으면 누적 차)
# ════════════════════════════════════════════════════════════════════════════
REPRT = {1: '11013', 2: '11012', 3: '11014', 4: '11011'}
REV_PRI = {'매출액': 0, '수익(매출액)': 1, '매출': 2, '영업수익': 3, '순영업수익': 4, '매출및지분법손익': 5}
def rev_pri(nm):
    nm = _sp(nm)
    if nm in REV_PRI: return REV_PRI[nm]
    if nm.startswith('매출액') or nm.startswith('수익(매출'): return 6
    return None
def rev_parse(rows, year, q, store):
    """fnlttMultiAcnt rows → store[corp][(year,q)][fs] = {'q': 3개월 값, 'cum': 누적, 'pri'}"""
    for r in rows or []:
        pri = rev_pri(r.get('account_nm') or ''); corp = r.get('corp_code')
        if pri is None or not corp: continue
        fs = r.get('fs_div') or 'OFS'
        amt = V.tonum(r.get('thstrm_amount')); add = V.tonum(r.get('thstrm_add_amount'))
        if amt is None and add is None: continue
        if q == 4: cum, qv = amt, None
        else:
            cum = add if add is not None else amt
            qv = amt if add is not None else (amt if q == 1 else None)
        d = store.setdefault(corp, {}).setdefault((year, q), {})
        if fs in d and d[fs]['pri'] <= pri: continue
        d[fs] = {'q': qv, 'cum': cum, 'pri': pri}
def rev_series(sc, quarters):
    """한 회사의 store → ({'2026Q3': 억원}, 'CFS'|'OFS'). 연결이 6개 분기 이상 있으면 연결."""
    best = ({}, None)
    for fs in ('CFS', 'OFS'):
        ser = {}
        for (y, q) in quarters:
            x = (sc.get((y, q)) or {}).get(fs)
            if not x: continue
            v = x.get('q')
            if v is None:
                cum = x.get('cum')
                if cum is None: continue
                if q == 1: v = cum
                else:
                    pv = (sc.get((y, q - 1)) or {}).get(fs) or {}
                    pc = pv.get('cum')
                    if pc is None: continue
                    v = cum - pc
            if v is None or v <= 0: continue
            ser['%dQ%d' % (y, q)] = round(v / 1e8, 1)
        if len(ser) >= 6: return ser, fs
        if len(ser) > len(best[0]): best = (ser, fs)
    return best
def rev_quarters(last):
    """마지막 분기 라벨에서 거슬러 NQ+1 분기를 덮는 (연, 분기) — 누적 차를 내려면 그 해 1분기부터 필요하다"""
    y1, q1 = int(last[:4]), int(last[5]); first = qprev(last, NQ); y0 = int(first[:4])
    return [(y, q) for y in range(y0, y1 + 1) for q in (1, 2, 3, 4) if (y, q) <= (y1, q1)]
def rev_fetch(corpmap, codes, last):
    """{code: ({라벨: 억원}, fs)} — 호출 수 = (연·분기 수) × ceil(종목 수 / 50)"""
    quarters = rev_quarters(last); store = {}
    corps = [corpmap[c] for c in codes]
    for i in range(0, len(corps), 50):
        batch = corps[i:i + 50]
        for (y, q) in quarters:
            if left() < 60 or V.STAT['limit']: break
            V._throttle(V.GAP)
            try:
                j = json.loads(V.fetch('%s/fnlttMultiAcnt.json?%s' % (V.BASE, urllib.parse.urlencode(
                    dict(crtfc_key=V.KEY, corp_code=','.join(batch), bsns_year=y, reprt_code=REPRT[q]))), 40, 2).decode('utf-8'))
            except Exception as e:
                log('매출 %d/%dQ 실패 %r' % (y, q, str(e)[:60])); STAT['fail'] += 1; continue
            STAT['rev'] += 1
            if j.get('status') == '020': V.STAT['limit'] = True; log('DART 사용한도 초과(매출)'); break
            rev_parse(j.get('list'), y, q, store)
    out = {}
    for c in codes:
        ser, fs = rev_series(store.get(corpmap[c]) or {}, quarters)
        if ser: out[c] = (ser, fs)
    return out

# ════════════════════════════════════════════════════════════════════════════
# 6. 종목 1개
# ════════════════════════════════════════════════════════════════════════════
def point_from(res, q, d, rc, fq, kind):
    """classify 결과 → (s 에 넣을 점 | None, sx 에 넣을 점 | None)"""
    base = {'q': q, 'd': d, 'rcept': rc, 'ty': res['ty'], 'fq': fq, 'k': kind, 'u': res.get('u') or ''}
    for k in ('sm', 'cb', 'sep', 'tr'):
        if res.get(k): base[k] = 1
    if res['st'] == 'ok':
        p = dict(base, eok=res['eok'])
        for k in ('tot', 'dlv', 'beg', 'new', 'rec', 'adj'):
            if res.get(k) is not None: p[k] = res[k]
        return p, None
    x = dict(base, st=res['st'], cur=res.get('cur'), ul=res.get('ul') or '')
    if res.get('raw') is not None: x['raw'] = res['raw']
    for k in ('tot', 'dlv', 'beg', 'new', 'rec'):
        if res.get(k) is not None: x[k] = res[k]
        if res.get('r_' + k) is not None: x['r_' + k] = res['r_' + k]
    return None, x

def apply_result(rec, res, note, q, d, rc, fq, kind, latest, src=None):
    """한 분기의 해석 결과를 종목 기록에 반영. 빈 결과로 기존 값을 덮어쓰지 않는다. 반환 = done 에 적을 상태"""
    pts = {p['q']: p for p in rec.get('s') or []}; xs = {p['q']: p for p in rec.get('sx') or []}
    st = res['st'] if res else 'notab'
    if res:
        p, x = point_from(res, q, d, rc, fq, kind)
        if src:
            for o in (p, x):
                if o is not None: o['prelim'] = 1
        if p is not None:
            pts[q] = p; xs.pop(q, None); STAT['new_pts'] += 1
        elif x is not None:
            if q in pts and pts[q].get('eok') is not None:
                STAT['kept'] += 1; log('  %s 새 보고서(%s)에서 잔고를 못 읽음(%s) — 기존 값 유지' % (q, rc, st))
            else: xs[q] = x
    elif q in pts and pts[q].get('eok') is not None:
        STAT['kept'] += 1; log('  %s 새 보고서(%s)에 수주 표가 없음 — 기존 값 유지' % (q, rc))
    if latest:
        if note: rec['note'] = note[:300]
        if res:
            rec['table'] = {'h': res.get('_head') or '', 'u': res.get('_unit') or res.get('u') or '', 'r': [r[:12] for r in (res.get('_rows') or [])[:30]], 'q': q}
            rec['ty'] = res['ty']
            if res.get('items'): rec['items'] = res['items']
            else: rec.pop('items', None)
        rec['st'] = st
    rec['s'] = [pts[k] for k in sorted(pts)]
    if xs: rec['sx'] = [xs[k] for k in sorted(xs)]
    else: rec.pop('sx', None)
    return st

def one(code, corp, old, has_hint):
    """반환 (rec, complete). complete=False 면 다음 실행에서 이어받는다."""
    rec = dict(old or {}); done = dict(rec.get('done') or {})
    reps = reports(corp)                                   # DartFail 은 위로
    if not reps: rec['done'] = done; return rec, True
    fy_end = next((mm for rc, y, mm, kind in reversed(reps) if kind == '사업'), rec.get('fy') or 12)
    rec['fy'] = fy_end
    complete = True
    full = has_hint or bool(rec.get('s')) or bool(rec.get('sx'))
    for idx, (rc, y, mm, kind) in enumerate(reversed(reps)):   # 최신 보고서부터
        q, d = qlabel(y, mm); latest = idx == 0
        dn = done.get(q) or {}
        if dn.get('rc') == rc and dn.get('pv') == PV and not dn.get('src'): continue
        if not latest and not full: break                       # 최신 보고서에 수주 표가 없는 회사 — 과거는 받지 않는다
        if left() < 45: complete = False; break
        try: raws = V.ddoc(rc)
        except V.DartFail:
            complete = False; STAT['fail'] += 1
            if V.STAT['limit']: break
            continue
        STAT['doc'] += 1
        if not raws:
            done[q] = {'rc': rc, 'st': 'nodoc', 'pv': PV}; continue
        try:
            cands, note, found = order_tables(max(raws.values(), key=len))
            res = pick_table(cands)
        except Exception as e:
            log('%s %s 파싱 실패 %r' % (code, q, str(e)[:100])); complete = False; STAT['fail'] += 1; continue
        st = apply_result(rec, res, note, q, d, rc, fiscal_q(kind, mm, fy_end), KIND[kind], latest)
        done[q] = {'rc': rc, 'st': st if (res or found) else 'nosec', 'pv': PV}
        if latest and res: full = True
    rec['done'] = done
    return rec, complete

def offline_one(code, old, vf):
    """DART 없이 vf/<코드>.json 의 최신 보고서 수주 표만으로 — 임시본·DART 장애 때의 보충"""
    rec = dict(old or {}); done = dict(rec.get('done') or {})
    biz = (vf or {}).get('biz') or {}; src = (vf or {}).get('biz_src') or {}
    m = re.search(r'(사업|반기|분기)보고서\s*\((\d{4})\.(\d{2})\)', src.get('nm') or '')
    if not m: return rec
    q, d = qlabel(int(m.group(2)), int(m.group(3)))
    if not q: return rec
    dn = done.get(q) or {}
    if dn.get('rc') == src.get('rc') and not dn.get('src'): return rec      # 이미 원문으로 받은 분기는 건드리지 않는다
    o = biz.get('order'); res = None
    if o:
        try:
            res = classify(o.get('r') or [], o.get('u') or '', o.get('h') or '')
            if res['st'] == 'none': res = None
            else: res['_head'] = o.get('h') or ''; res['_unit'] = o.get('u') or ''; res['_rows'] = o.get('r') or []
        except Exception as e: log('%s vf 표 해석 실패 %r' % (code, str(e)[:80]))
    fy = rec.get('fy') or 12
    st = apply_result(rec, res, biz.get('order_note') or '', q, d, src.get('rc'), fiscal_q(m.group(1), int(m.group(3)), fy), KIND[m.group(1)], True, src='vf')
    done[q] = {'rc': src.get('rc'), 'st': st, 'pv': PV, 'src': 'vf'}
    rec['done'] = done
    return rec

def finalize(code, rec, x, vf, revs):
    """시계열 정리 + 매출 + 인식 재료. x = semipeer.json 의 종목 행"""
    ser = finish_series(rec.get('s') or [])
    rec['s'] = ser
    rev = dict(rec.get('rev') or {})
    if code in revs and (rec.get('fy') or 12) == 12:
        rev.update(revs[code][0]); rec['rev_fs'] = revs[code][1]
    for lab, v in zip(x.get('ql') or [], x.get('rq') or []):          # 화면의 "분기 매출" 그림과 같은 값(hege = DART 주요계정)을 우선
        L = qfrom_short(lab)
        if L and v is not None: rev[L] = v
    if rev and (ser or rec.get('sx')):
        keep = sorted(rev)[-(NQ + 2):]; rec['rev'] = {k: rev[k] for k in keep}
        if x.get('fs') and 'rev_fs' not in rec: rec['rev_fs'] = x.get('fs')
    else: rec.pop('rev', None)
    last = ser[-1] if ser else None
    ttm = None
    if last and rev:
        qs = [qprev(last['q'], k) for k in range(4)]
        if all(rev.get(k) is not None for k in qs): ttm = sum(rev[k] for k in qs)
    if ttm is None: ttm = x.get('rev')
    r = recognition(vf, ttm, last['eok'] if last else None)
    if r: rec['recog'] = r
    else: rec.pop('recog', None)
    if last and ttm and ttm > 0 and last['eok'] > ttm * 20: rec['sus'] = 1      # 단위 표기 오류 의심(잔고가 연매출의 20배 초과)
    else: rec.pop('sus', None)
    return rec

# ════════════════════════════════════════════════════════════════════════════
def load_vf(code):
    p = os.path.join(BASE, 'vf', code + '.json')
    if not os.path.exists(p): return None
    try: return json.load(open(p, encoding='utf-8'))
    except Exception: return None

def main():
    sp = json.load(open(os.path.join(BASE, 'semipeer.json'), encoding='utf-8'))
    co_sp = sp.get('co') or {}
    corpmap = dict(sp.get('corpmap') or {})
    if not corpmap:
        try: corpmap = json.load(open('tools/semipeer/dartcorp.json', encoding='utf-8'))
        except Exception: corpmap = {}
    prevj = {}
    if os.path.exists(OUT):
        try: prevj = json.load(open(OUT, encoding='utf-8')) or {}
        except Exception: prevj = {}
    prev = prevj.get('co') or {}
    if prevj.get('v') != PV:                               # v1(임시본) 기록은 형식이 다르다 — 설명·인식 재료만 넘겨받고 점은 다시 만든다
        prev = {c: {k: v[k] for k in ('note',) if k in v} for c, v in prev.items()}
    codes = [c for c in co_sp if (not ONLY or c in ONLY)]
    vfs = {c: load_vf(c) for c in codes}
    online = bool(V.KEY) and not OFFLINE
    if online:                                             # 러너에 따라 OpenDART 가 아예 응답하지 않는 날이 있다 — 먼저 한 번 찔러 본다
        ok = False
        for i in range(2):
            try:
                json.loads(V.fetch('%s/list.json?%s' % (V.BASE, urllib.parse.urlencode(dict(crtfc_key=V.KEY, corp_code='00126380',
                    bgn_de=time.strftime('%Y%m%d', time.localtime(time.time() - 5 * 86400)), end_de=time.strftime('%Y%m%d'), page_count=1))), 20, 1).decode('utf-8'))
                ok = True; break
            except Exception as e:
                log('DART 연결 점검 실패 %d회 %r' % (i + 1, str(e)[:60])); time.sleep(8)
        if not ok: online = False; log('이 러너에서는 OpenDART 에 연결되지 않음 → vf 의 최신 표로만 보충하고 끝냄(다음 시도에서 이어감)')
    dart_down = bool(V.KEY) and not OFFLINE and not online
    log('대상 %d종목 · 방식 %s · 목표 %d개 분기 · 기존 기록 %d' % (len(codes), 'DART 원문' if online else 'vf 최신 표(임시)', NQ, len(prev)))

    hint = {c: bool(((vfs[c] or {}).get('biz') or {}).get('order')) or bool((prev.get(c) or {}).get('s')) or bool((prev.get(c) or {}).get('sx')) for c in codes}
    order = sorted(codes, key=lambda c: (0 if hint[c] else 1, c))
    co, pending = {}, []
    for i, c in enumerate(order):
        old = prev.get(c) or {}
        if online and corpmap.get(c) and not V.STAT['limit']:
            if left() < 60: pending.append(c); co[c] = old; continue
            try:
                rec, comp = one(c, corpmap[c], old, hint[c])
                if not comp: pending.append(c)
            except V.DartFail:
                rec = old; pending.append(c); STAT['fail'] += 1
            except Exception as e:
                rec = old; pending.append(c); STAT['fail'] += 1; log('%s 실패 %r' % (c, str(e)[:120]))
        else:
            rec = offline_one(c, old, vfs[c])
            if dart_down or (online and corpmap.get(c)): pending.append(c)
        co[c] = rec
        if (i + 1) % 20 == 0:
            log('  %d/%d · 원문 %d · 새 분기점 %d · 실패 %d (%ds)' % (i + 1, len(order), STAT['doc'], STAT['new_pts'], STAT['fail'], time.time() - T0))

    revs = {}
    if online and not V.STAT['limit'] and left() > 90:
        want = [c for c in codes if corpmap.get(c) and ((co.get(c) or {}).get('s') or (co.get(c) or {}).get('sx'))]
        lasts = [p['q'] for c in want for p in (co[c].get('s') or [])[-1:]] or [qfrom_short(sp.get('hege_q') or '') or '']
        last = max(l for l in lasts if l) if any(lasts) else None
        if want and last:
            try: revs = rev_fetch(corpmap, want, last)
            except Exception as e: log('매출 수집 실패 %r' % (str(e)[:100],))
            log('분기 매출 %d종목 (호출 %d)' % (len(revs), STAT['rev']))
    out_co, n_series, n_pts, hist = {}, 0, 0, {}
    for c in codes:
        rec = finalize(c, co.get(c) or {}, co_sp.get(c) or {}, vfs[c], revs)
        if not rec: continue
        if rec.get('s'):
            n_series += 1; n_pts += len(rec['s']); hist[len(rec['s'])] = hist.get(len(rec['s']), 0) + 1
        out_co[c] = rec
    for c, v in (prevj.get('co') or {}).items():
        if c not in out_co and c not in codes and prevj.get('v') == PV: out_co[c] = v
    old_series = sum(1 for v in (prevj.get('co') or {}).values() if v.get('s'))
    if n_series == 0 and old_series:
        log('이번 실행에서 잔고를 하나도 못 읽음 — 기존 파일 유지'); _done(False); return 1
    prelim = not any((p.get('rc') and not p.get('src')) for v in out_co.values() for p in (v.get('done') or {}).values())
    out = {'v': PV, 'updated': datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=9))).strftime('%Y-%m-%d %H:%M'),
           'n': len(out_co), 'n_series': n_series, 'n_points': n_pts, 'nq': NQ, 'hist': hist, 'pending': len(pending),
           'stat': dict(STAT, dart=V.STAT.get('dart', 0), dart_doc=V.STAT.get('doc', 0), limit=bool(V.STAT.get('limit'))),
           'note': ('정기보고서(사업·반기·분기)의 수주상황 표에서 읽은 분기 말 수주잔고와 같은 분기의 매출(DART 주요계정). '
                    '회사마다 표 형식이 달라 잔고를 못 읽는 곳이 있고, 그런 곳은 이유(st)를 적었다. 달러 표기는 환산하지 않았다.'),
           'co': out_co, 'debug': DEBUG[-60:]}
    if prelim: out['prelim'] = 1
    os.makedirs(os.path.dirname(OUT) or '.', exist_ok=True)
    json.dump(out, open(OUT, 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'))
    log('저장 %s — %d종목 · 잔고 시계열 %d종목 · 분기점 %d · 분기 수 분포 %s · 남은 종목 %d · 원문 %d·목록 %d·매출 %d콜 · %ds'
        % (OUT, len(out_co), n_series, n_pts, json.dumps(hist, sort_keys=True), len(pending), STAT['doc'], STAT['list'], STAT['rev'], time.time() - T0))
    _done(online and not pending)
    return 0
def _done(flag):
    try:
        if os.environ.get('GITHUB_OUTPUT'): open(os.environ['GITHUB_OUTPUT'], 'a').write('done=%s\n' % ('1' if flag else '0'))
    except Exception: pass

if __name__ == '__main__':
    sys.exit(main())
