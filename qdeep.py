#!/usr/bin/env python3
# 종목 딥다이브 수집: 분기·반기·사업보고서 원문(사업의 내용)에서
#  - 품목별 매출(누적→분기 차감), 품목별 판가(누적평균→분기 환산), 물량 지수(매출/판가)
#  - 생산능력·생산실적·가동률, 수주잔고
# 원문 접근: DART 뷰어(키 불필요) — rcpNo는 opendart list.json(키)으로 조회
# 결과: public/data/qdeep/{code}.json + index.json
import os, io, sys, json, time, zipfile, urllib.request, re, datetime
import xml.etree.ElementTree as ET

KEY = os.environ.get('DART_KEY', '')
BASE = 'https://opendart.fss.or.kr/api'
OUTDIR = 'public/data/qdeep'
MAXRUN = int(os.environ.get('MAXRUN', '10'))
REFRESH_DAYS = 25  # 분기마다 새 보고서 반영
PV = 5  # 파서 버전 — 올리면 기존 수집분 재수집
# v5: 품목별 매출 파서를 자기검증형으로 교체. 품목 합을 원문 '합계' 행과 대조해
#     오차 2% 초과면 저장하지 않는다. 고친 것 — '-' 칸을 지워 뒤 연도 값이
#     당겨지던 열 밀림(RF머트리얼즈 2019년 매출이 21.1Q 자리로 들어감),
#     판로(내수·수출) 행이 품목으로 등록, '제품 계' 소계 2배 중복,
#     단위 표기를 표 안에서 못 찾아 1000배 틀어짐, 유형 '기타'가 '상품 기타'에
#     합쳐짐, 머리글이 2행인 표를 통째로 건너뜀.
START_YEAR = 2021
UA = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126 Safari/537.36'}
DEBUG = []

def fetch(url, timeout=40, referer=None):
    hd = dict(UA)
    if referer:
        hd['Referer'] = referer
    for i in range(3):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=hd), timeout=timeout) as r:
                return r.read()
        except Exception:
            time.sleep(1.5 * (i + 1))
    return b''

def jget(url):
    try:
        return json.loads(fetch(url).decode('utf-8'))
    except Exception:
        return {}

def tonum(s):
    s = str(s).replace(',', '').replace('△', '-').replace('(', '-').replace(')', '').strip()
    try:
        return float(s)
    except Exception:
        return None

def corp_map():
    b = fetch('%s/corpCode.xml?crtfc_key=%s' % (BASE, KEY), 90)
    z = zipfile.ZipFile(io.BytesIO(b))
    root = ET.fromstring(z.read(z.namelist()[0]))
    m = {}
    for it in root.iter('list'):
        sc = (it.findtext('stock_code') or '').strip()
        if len(sc) == 6:
            m[sc] = it.findtext('corp_code').strip()
    return m

def filings(corp):
    """정기보고서 [(rcpNo, 'YYQn', cum_q)] — cum_q: 그 보고서 누적이 커버하는 분기 수(1,2,3,4)"""
    bgn = '%d0101' % START_YEAR
    out = []
    for page in (1, 2):
        d = jget('%s/list.json?crtfc_key=%s&corp_code=%s&pblntf_ty=A&bgn_de=%s&page_count=100&page_no=%d&last_reprt_at=Y'
                 % (BASE, KEY, corp, bgn, page))
        for it in (d.get('list') or []):
            nm = it.get('report_nm') or ''
            m = re.search(r'\((\d{4})\.(\d{2})\)', nm)
            if not m:
                continue
            y, mm = int(m.group(1)), int(m.group(2))
            if y < START_YEAR:
                continue
            if '사업보고서' in nm:
                q = 4
            elif '반기보고서' in nm:
                q = 2
            elif '분기보고서' in nm:
                q = 1 if mm == 3 else 3
            else:
                continue
            out.append((it['rcept_no'], '%02dQ%d' % (y % 100, q), q, y))
        if not (d.get('list') or []):
            break
        time.sleep(0.1)
    # 같은 (연,분기) 중 최신 rcpNo만
    best = {}
    for rcp, label, q, y in out:
        k = (y, q)
        if k not in best or rcp > best[k][0]:
            best[k] = (rcp, label, q, y)
    return [best[k] for k in sorted(best)]

def doc_tree(rcp):
    h = fetch('https://dart.fss.or.kr/dsaf001/main.do?rcpNo=%s' % rcp, 40).decode('utf-8', 'ignore')
    blocks = re.findall(r"node\d+\['text'\]\s*=\s*\"([^\"]*)\"[\s\S]{0,600}?node\d+\['dcmNo'\]\s*=\s*\"(\d+)\"[\s\S]{0,200}?node\d+\['eleId'\]\s*=\s*\"(\d+)\"[\s\S]{0,200}?node\d+\['offset'\]\s*=\s*\"(\d+)\"[\s\S]{0,200}?node\d+\['length'\]\s*=\s*\"(\d+)\"", h)
    return blocks

def viewer(rcp, dcm, ele, off, ln):
    u = ('https://dart.fss.or.kr/report/viewer.do?rcpNo=%s&dcmNo=%s&eleId=%s&offset=%s&length=%s&dtd=dart3.xsd'
         % (rcp, dcm, ele, off, ln))
    return fetch(u, 40, referer='https://dart.fss.or.kr/dsaf001/main.do?rcpNo=%s' % rcp).decode('utf-8', 'ignore')

def tables(h):
    out = []
    for t in re.findall(r'<TABLE[\s\S]*?</TABLE>', h, re.I):
        rows = []
        for tr in re.findall(r'<TR[\s\S]*?</TR>', t, re.I):
            cells = [re.sub(r'&nbsp;?', ' ', re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', c))).strip()
                     for c in re.findall(r'<T[DH][^>]*>([\s\S]*?)</T[DH]>', tr, re.I)]
            rows.append(cells)
        out.append(rows)
    return out


TYPE_WORDS = {'제품', '상품', '용역', '기타', '제품기타', '상품기타', '제품등', '상품등', '임대', '서비스',
              '수출', '내수', '국내', '해외', '합계', '계', '총계', '소계', '매출', '제상품'}

def _is_numlike(c):
    cc = c.replace(' ', '')
    return cc in ('-', '') or tonum(cc) is not None

def _norm(s): return re.sub(r'\s+', '', s or '')

# ── 합계·소계 판정 ──────────────────────────────────────────────
# '계'로 끝나는 말 중 소계인 것만 잡는다. '시계·온도계·중계' 같은 품목명을
# 합계로 오인하면 품목이 통째로 사라지므로 접두어를 화이트리스트로 둔다.
_TOT_EXACT = {'계', '합계', '총계', '소계', '누계', '총합계', '합계액', '전체'}
_TOT_PREFIX = {'', '합', '소', '총', '누', '제품', '상품', '용역', '공사', '임대', '서비스',
               '기타', '부문', '전체', '당기', '전기', '당분기', '당반기', '내수', '수출',
               '국내', '해외', '제상품', '제품상품', '매출'}
def _is_total(s):
    n = _norm(s)
    if not n: return False
    if n in _TOT_EXACT: return True
    if any(w in n for w in ('합계', '총계', '소계', '누계')): return True
    if n.endswith('계') and n[:-1] in _TOT_PREFIX: return True
    return False

# 매출 '유형' 라벨 — 품목명이 아니라 분류
SALE_TYPES = ('제품', '상품', '용역', '제상품', '제품등', '상품등', '임대', '서비스', '공사',
              '기타', '제품매출', '상품매출', '용역매출', '기타매출', '임대매출', '공사매출',
              '제품및상품', '제품상품')
# 유형 추적용 — '기타'처럼 품목으로도 쓰이는 말은 제외한다
TYPE_SETTERS = ('제품', '상품', '용역', '공사', '임대', '서비스', '제상품',
                '제품매출', '상품매출', '용역매출', '임대매출', '공사매출')
# 판로 라벨 — 이 행은 '앞선 품목'에 더해야 하고, 품목이 되면 안 된다
CHAN_WORDS = ('수출', '내수', '국내', '해외', '수출액', '내수액', '로컬', '로칼', '직수출',
              '내수매출', '수출매출', 'local', 'LOCAL', '아시아', '미주', '유럽', '중국')
HDR_WORDS = ('구분', '사업부문', '부문', '매출유형', '품목', '주요상표', '구체적용도', '용도',
             '매출액', '금액', '비율', '비중', '단위', '판매경로', '제품명')
# 품목이 아닌 조정 행 — 더하면 합계가 어긋나고 품목 목록을 더럽힌다
ADJ_RE = re.compile(r'(연결\s*조정|내부거래|상계|제거|내부\s*매출)')

UNITS = (('십억원', 1e9), ('백만원', 1e6), ('억원', 1e8), ('천만원', 1e7),
         ('만원', 1e4), ('천원', 1e3), ('원', 1.0))
def unit_mult(h, pos):
    """표 바로 앞의 마지막 '(단위 : X)' 표기로 배수를 정한다.
    앞쪽 다른 표의 단위 문구를 집으면 값이 1000배 틀어진다(대주전자재료)."""
    seg = h[max(0, pos - 3000):pos]
    ms = list(re.finditer(r'단\s*위\s*[:：]\s*([^)＜<]{1,24})', seg))
    if ms:
        u = _norm(ms[-1].group(1))
        for w, mu in UNITS:
            if w in u: return mu
    for w, mu in UNITS[:-1]:
        if w in _norm(seg[-400:]): return mu
    return 1.0

def unit_from_rows(rows):
    """표 자체의 앞 2행에 '(단위 : 백만원)' 이 들어 있는 서식이 많다.
    문맥만 보면 이 표기를 놓쳐 값이 100만배 틀어진다(이수페타시스·대주전자재료)."""
    head = ' '.join(' '.join(r) for r in rows[:2])
    m = list(re.finditer(r'단\s*위\s*[:：]\s*([^)＜<]{1,24})', head))
    if m:
        u = _norm(m[-1].group(1))
        for w, mu in UNITS:
            if w in u: return mu
    return None

def sales_mult(h, pos, rows):
    """표 안의 단위 표기를 우선하고, 없으면 표 앞 문맥을 본다."""
    return unit_from_rows(rows) or unit_mult(h, pos)

def _tonum(c):
    c = _norm(c).replace(',', '')
    if c in ('', '-', '­', '–', '—', '해당사항없음'): return None
    neg = c.startswith('(') and c.endswith(')')
    if neg: c = c[1:-1]
    if not re.fullmatch(r'-?\d+(\.\d+)?', c): return None
    v = float(c)
    return -v if neg else v

def _lead(row):
    """첫 '값 자리' 앞의 텍스트 셀들. '-' 는 값 자리의 시작일 수도 있어
    뒤에 숫자가 하나라도 있으면 값으로 본다."""
    out = []
    for i, c in enumerate(row):
        if _tonum(c) is not None: break
        n = _norm(c)
        if n in DASH:
            if any(_tonum(x) is not None for x in row[i + 1:]): break
            continue
        if n: out.append(c.strip())
    return out

DASH = ('-', '–', '—', '­', '', '해당사항없음', 'N/A', '-')
def _vals(row):
    """선행 텍스트 셀 뒤의 '값 자리'를 순서대로 돌려준다.
    '-' 는 0 으로 자리를 지킨다 — 빼버리면 뒤쪽 기간 값이 앞으로 당겨진다."""
    out, started = [], False
    for c in row:
        v = _tonum(c)
        if v is not None:
            out.append(v); started = True; continue
        n = _norm(c)
        if n in DASH:
            if started or out: out.append(0.0)
            else: out.append(0.0); started = True
            continue
        if started: break            # 값 구간 뒤의 주석 셀 — 끝
    return out

def _period_count(rows):
    """머리글에서 기간 열 수와 '당기' 위치 → (k, nper)"""
    best = []
    for r in rows[:3]:
        ys = []
        for c in r:
            m = re.search(r'(20\d{2})\s*년', c)
            if m: ys.append(int(m.group(1))); continue
            m = re.search(r'제\s*(\d{1,3})\s*기', c)
            if m: ys.append(int(m.group(1)))
        if len(ys) >= 2 and len(ys) > len(best): best = ys
    if not best: return 0, 1
    return best.index(max(best)), len(best)

# ── 표 선별 ────────────────────────────────────────────────────
GOOD_CTX = re.compile(r'(매출\s*실적|매출\s*현황|매출액?\s*추이|품목별\s*매출|부문별\s*매출)')
BAD_CTX  = re.compile(r'(판매\s*경로|판매\s*전략|가격\s*변동|판매\s*가격|주요\s*제품\s*등?의?\s*현황'
                      r'|수주\s*상황|생산\s*실적|생산\s*능력|원재료|재무상태|현금흐름|주식|배당)')
def table_is_sales(rows, ctx):
    """매출실적 표인지 — 문맥 + 머리글로 판정.
    머리글이 1행이 아닌 표가 많다('(단위 : 백만원)' 가 첫 행인 경우) → 앞 3행을 본다."""
    if BAD_CTX.search(ctx or '') and not GOOD_CTX.search(ctx or ''): return False
    head = _norm(' '.join(' '.join(r) for r in rows[:3]))
    if '판매경로' in head or '판매가격' in head: return False
    has_type = any(w in head for w in ('매출유형', '사업부문', '부문', '매출유형'))
    has_item = any(w in head for w in ('품목', '품 목', '제품', '품명', '제조장비'))
    good = bool(GOOD_CTX.search(ctx or ''))
    if good and (has_type or has_item or '구분' in head): return True
    return has_type and has_item

# ── 본체 ──────────────────────────────────────────────────────
def pick_best(tabs):
    """한 섹션의 여러 표 중 진짜 매출실적 표를 고른다.
    품목 수가 많은 표를 고르면 지주회사 배당수익 표 같은 것이 뽑힌다(심텍).
    재구성 합계가 가장 큰 표가 전사 매출실적 표다."""
    best = None
    for t in tabs:
        r, why = parse_sales_table(t['rows'], t['mult'], t.get('ctx', ''))
        if not r: continue
        tot = sum(abs(v) for v in r.values())
        if best is None or tot > best[0]: best = (tot, r, why)
    return (best[1], best[2]) if best else (None, 'no-table')

def parse_sales_table(rows, mult, ctx=''):
    if len(rows) < 3: return None, 'rows<3'
    if not table_is_sales(rows, ctx): return None, 'not-a-sales-table'
    k, nper = _period_count(rows)

    # 전사 합계 후보를 모두 모은다. 일진전기처럼 합계 묶음이
    # 내수/수출/계 3행으로 쪼개진 표에서는 '계' 행이 진짜 합계다.
    tot_cands = []
    for idx, r in enumerate(rows):
        lead = _lead(r); nv = _vals(r)
        if not lead or not nv: continue
        if any(w in _norm(c) for c in lead for w in ('합계', '총계')):
            tot_cands.append(nv)
            for r2 in rows[idx + 1:]:                  # 합계 묶음의 하위 행(내수·수출·계)
                l2 = _lead(r2); v2 = _vals(r2)
                if not l2 or not v2: break
                n2 = [_norm(c) for c in l2]
                if len(n2) == 1 and (n2[0] in set(_norm(w) for w in CHAN_WORDS) or _is_total(n2[0])):
                    tot_cands.append(v2)
                else: break
    if not tot_cands:
        for r in reversed(rows):
            lead = _lead(r)
            if lead and _vals(r) and _is_total(lead[-1]): tot_cands.append(_vals(r)); break
    if not tot_cands: return None, 'no-total-row'

    m0 = len(tot_cands[0]) // nper if nper and len(tot_cands[0]) % nper == 0 else 1
    pinned = nper >= 2                                  # 머리글에서 기간을 읽었다
    cands = []
    for tn in tot_cands:
        js = [k * m0, k] if pinned else ([k * m0, k, 0] + list(range(len(tn))))
        for j in js:
            if 0 <= j < len(tn) and (id(tn), j) not in [(id(a), b) for a, b in cands]:
                cands.append((tn, j))

    DROP = set(_norm(w) for w in SALE_TYPES) | set(_norm(w) for w in CHAN_WORDS) \
         | set(_norm(w) for w in HDR_WORDS)
    SETTERS = set(_norm(w) for w in TYPE_SETTERS)
    CHANS = set(_norm(w) for w in CHAN_WORDS)

    best = None
    for tn, j in cands:
        total = tn[j]
        if not total or abs(total) < 1: continue
        items, cur_type, cur_item, in_total = {}, None, None, False
        keymap = {}                                     # 공백 제거 키 → 대표 표기
        type_items = 0                                  # 현재 유형 그룹에서 담은 품목 수
        for r in rows[1:]:
            lead = _lead(r)
            nums = _vals(r)
            norm = [_norm(c) for c in lead]
            # 합계 그룹 진입/이탈 — 합계 묶음 안의 내수·수출 행까지 건너뛴다.
            # 단 '상품 계'처럼 그 유형에서 담은 품목이 하나도 없으면 소계가 아니라
            # 그 유형의 유일한 매출이므로 품목으로 받는다(한솔케미칼 상품 28,614).
            if lead and any(_is_total(c) for c in norm):
                sub = [c for c, n in zip(lead, norm) if _is_total(n)]
                only_sub = (_norm(sub[-1]) not in ('합계', '총계', '총합계')
                            and not _norm(sub[-1]).startswith(('합계', '총계')))
                if only_sub and type_items == 0 and j < len(nums):
                    nm2 = re.sub(r'\s+', ' ', sub[-1]).strip()[:24]
                    items[nm2] = items.get(nm2, 0) + nums[j]
                    cur_item = nm2; type_items += 1
                    continue
                if not (len(norm) == 1 and norm[0] in CHANS): in_total = True
                continue
            if lead and len(norm) == 1 and norm[0] in CHANS and in_total:
                continue
            if lead and not (len(norm) == 1 and norm[0] in CHANS):
                in_total = False
            if not lead or j >= len(nums): continue
            val = nums[j]
            if val is None: continue
            if norm and norm[-1] in set(_norm(w) for w in HDR_WORDS): continue
            if norm and norm[0] in SETTERS:
                if lead[0].strip() != cur_type: type_items = 0
                cur_type = lead[0].strip()
            cand_names = [c for c, n in zip(lead, norm) if n not in DROP]
            if cand_names:
                name = cand_names[-1]
            elif len(norm) == 1 and norm[0] in CHANS and cur_item:
                name = cur_item                       # 판로 행은 앞선 품목에 더한다
            elif len(norm) == 1 and norm[0] in CHANS:
                continue                              # 앞선 품목이 없는 판로 행은 버린다
            elif len(lead) >= 2:
                # ['상품','기타'] / ['기타','기타'] — 행 안에 유형과 품목이 다 있다.
                # cur_type 을 끌어오면 '기타 기타'가 '상품 기타'에 합쳐진다.
                a, b = lead[0].strip(), lead[-1].strip()
                name = a if _norm(a) == _norm(b) else (a + ' ' + b)
            else:
                name = lead[-1]
                if _norm(name) == '기타' and cur_type: name = cur_type + ' 기타'
            name = re.sub(r'\s+', ' ', name).strip()[:24]
            if not name: continue
            if ADJ_RE.search(name): continue          # 연결조정 행은 품목이 아니다
            key = _norm(name)
            if key not in keymap:
                keymap[key] = name; type_items += 1
            cur_item = keymap[key]
            items[keymap[key]] = items.get(keymap[key], 0) + val
        if not items: continue
        s = sum(items.values())
        err = abs(s - total) / abs(total)
        if best is None or err < best[0]: best = (err, j, items, total, s)
        if err <= 0.005: break

    if best is None: return None, 'no-candidate'
    err, j, items, total, s = best
    if err > 0.02:
        return None, 'mismatch col%d sum=%.0f total=%.0f err=%.1f%%' % (j, s, total, err * 100)
    scaled = s * mult
    if scaled > 5e14 or (0 < abs(scaled) < 1e7):
        # 500조원 초과 / 1,000만원 미만 = 단위 표기를 잘못 읽은 것.
        # 역산해 고치면 추정치가 되므로 저장하지 않고 비운다.
        return None, 'unit-suspect total=%.3g원 (mult=%g)' % (scaled, mult)
    return ({k2: v * mult for k2, v in items.items()},
            'ok col%d err=%.2f%% n=%d' % (j, err * 100, len(items)))

# ── 품목별 매출 (v2, 자기검증형) ────────────────────────────────
def parse_sales(h):
    """품목별 매출 누적 {품목: 원}.
    표의 합계 행과 품목 합을 대조해 맞지 않으면 아무것도 돌려주지 않는다.
    틀린 값을 저장하는 것보다 비어 있는 것이 낫다."""
    r, _ = parse_sales_qc(h)
    return r or {}

def parse_sales_qc(h):
    """(결과, 사유) — 사유는 대시보드에 '왜 비었는지' 표시하기 위한 것"""
    tabs = []
    for m in re.finditer(r'<TABLE[\s\S]*?</TABLE>', h, re.I):
        rows = tables(m.group(0))[0]
        if not rows or len(rows) < 3:
            continue
        ctx = re.sub(r'\s+', ' ', re.sub('<[^>]+>', ' ', h[max(0, m.start() - 400):m.start()]))
        tabs.append({'rows': rows,
                     'mult': unit_from_rows(rows) or unit_mult(h, m.start()),
                     'ctx': ctx})
    if not tabs:
        return None, 'no-table'
    return pick_best(tabs)

def parse_price(h):
    """품목별 판가(누적평균): {품목: (값, 단위문자)}"""
    out = {}
    for m in re.finditer(r'<TABLE[\s\S]*?</TABLE>', h, re.I):
        pos = m.start()
        seg = h[max(0, pos - 800):pos]
        um = re.search(r'단\s*위\s*[:：]\s*([^)＜<]{1,14})', seg)
        t = tables(m.group(0))[0]
        if not t or len(t) < 2:
            continue
        head = ' '.join(t[0])
        if not ('품' in head and ('기' in head or '분기' in head)):
            continue
        # 가격 표 추정: 행이 [품목, 숫자...]이고 근처에 '가격' 또는 단위가 원/…
        near = h[max(0, pos - 2500):pos]
        if '가격변동' not in near and '판매가격' not in near and '가격' not in near:
            continue
        for r in t[1:]:
            if len(r) >= 2 and tonum(r[0]) is None:
                v = tonum(r[1])
                if v is not None and v > 0:
                    out[r[0].strip()[:20]] = (v, (um.group(1).strip() if um else ''))
        if out:
            break
    return out

def parse_prod(h):
    """생산능력·생산실적·가동률(누적): {품목: {'cap':, 'act':, 'util':%}} — 헤더 열 위치 기반"""
    res = {}
    for m in re.finditer(r'<TABLE[\s\S]*?</TABLE>', h, re.I):
        t = tables(m.group(0))[0]
        if not t or len(t) < 2:
            continue
        head = [c.replace(' ', '') for c in t[0]]
        flat = ' '.join(head)
        if '가동률' not in flat and not ('생산능력' in flat and '생산실적' in flat):
            continue
        def hidx(word):
            return next((i for i, c in enumerate(head) if word in c), None)
        iu, ic, ia = hidx('가동률'), hidx('생산능력'), hidx('생산실적')
        ncol = len(head)
        for r in t[1:]:
            if not r or re.fullmatch(r'[\d,.\-△()% ]*', r[0] or ''):
                continue
            name = r[0].strip()[:20]
            if name.replace(' ', '') in ('계', '합계', '총계'):
                name = '전체'
            # rowspan으로 앞열이 병합된 행은 끝에서 정렬
            off = ncol - len(r)
            def cell(i):
                if i is None:
                    return None
                j = i - off
                return r[j] if 0 <= j < len(r) else None
            util = None
            cu = cell(iu)
            if cu:
                try:
                    util = float(re.sub(r'[%, ]', '', cu))
                except Exception:
                    util = None
            cap = tonum(cell(ic)) if ic is not None else None
            act = tonum(cell(ia)) if ia is not None else None
            if any(x is not None for x in (cap, act, util)):
                res[name] = {'cap': cap, 'act': act, 'util': util}
        if res:
            break
    return res

FINW = re.compile(r'자산|부채|자본|손익|이익|비용|원가|충당|차입|사채|리스|공정가치|법인세|배당|환율|외화'
                  r'|현금|인식|측정|평가|보증|예수|미수|미지급|선급|선수|재고|미착|반제품|누적|기말|기초'
                  r'|미성공사|공사수익|공사원가|상각|급여|수수료|보험료|판관비|복리|공과|선전비|운반|소모품|대손|접대|유동'
                  r'|주식수|주당|신주|액면|증자|조달|거래처수|매출액|이전대가|취득|처분|소계'
                  r'|상여|판매비|관리비|수익에대한|합계$|상환|유예|규모|감사|투입'
                  r'|^국내$|^해외$|^수출$|^내수$|^지역$|^기타$'
                  r'|^[IVXⅠⅡⅢⅣ]+\.|USD|JPY|EUR|CNY|비$|료$')

def parse_customers(h):
    """재무제표 주석 '매출 10% 이상 외부고객' 표: {고객명(A사 등): 원(당기 누적/단일 — 보고서 기재값)}
    검증: 고객 표는 행 수가 적고(≤10) 행 이름이 재무제표 계정과목이 아니어야 함 —
    앵커 뒤 창에 잡힌 비용·재무상태 주석 표를 배제."""
    for m in re.finditer(r'매출[^<]{0,40}10%[^<]{0,80}?(?:외부\s*고객|고객)', h):
        seg = h[m.start(): m.start() + 10000]
        mult = 1e3 if '천원' in seg[:1200] else (1e6 if '백만원' in seg[:1200] else 1e3)
        for tm in re.finditer(r'<TABLE[\s\S]*?</TABLE>', seg, re.I):
            t = tables(tm.group(0))[0]
            out = {}
            fin = tot = 0
            for r in t:
                if len(r) >= 2 and not _is_numlike(r[0]):
                    nm = r[0].strip()
                    key = nm.replace(' ', '')
                    if key in ('구분', '합계', '계', '총계', '(단위:천원)', '(단위:백만원)') or '고객' in nm or '단위' in nm:
                        continue
                    tot += 1
                    if FINW.search(key):
                        fin += 1
                        continue
                    v = None
                    for c in r[1:]:
                        v = tonum(c.replace(' ', ''))
                        if v is not None:
                            break
                    if v is not None and v > 0:
                        out[nm[:16]] = v * mult
            if out and len(out) <= 10 and (tot == 0 or fin / tot <= 0.5):
                return out
    return {}

BL_KEYS = ('수주잔고', '수주잔액', '수주잔량', '수주총액')

def parse_backlog(h):
    """수주잔고 합계(원): 수주상황 표의 '합계' 행 마지막 금액.
    방산 대형사 대응: 표 헤더에 키워드가 없고 표 직전 서술문에만 있는 경우(KAI),
    '수주잔액' 표기(LIG), 기(期)별 행 표(합계 없이 당기 1행)도 인식."""
    for m in re.finditer(r'<TABLE[\s\S]*?</TABLE>', h, re.I):
        t = tables(m.group(0))[0]
        if not t:
            continue
        flat = ' '.join(' '.join(r) for r in t[:2]).replace(' ', '')
        prose = re.sub(r'<[^>]+>', ' ', h[max(0, m.start() - 500):m.start()]).replace(' ', '')
        if not any(k in flat for k in BL_KEYS) and not any(k in prose for k in BL_KEYS):
            continue
        mult = unit_mult(h, m.start())
        best = None
        for r in t[1:]:
            joined = [c.replace(' ', '') for c in r]
            nums = [tonum(c) for c in r if tonum(c) is not None]
            if nums and any(j in ('합계', '계', '총계') for j in joined[:2]):
                best = nums[-1] * mult
        if best is None:  # 합계행 없음
            rows = []
            for r in t[1:]:
                nums = [tonum(c) for c in r if tonum(c) is not None]
                if nums:
                    rows.append((r[0].replace(' ', ''), nums))
            if not rows:
                continue
            if all(re.search(r'제?\d+기|20\d\d', lb) for lb, _ in rows):
                # 기(期)별 행 표(LIG형): 첫 행=당기 잔액 — 합산하면 전기와 중복
                best = rows[0][1][-1] * mult
            else:  # 부문별 행 표(KAI형): 부문 합
                best = sum(ns[-1] for _, ns in rows) * mult
        if best and best >= 1e8:  # 1억 미만은 잡음
            return best
    return None

def contracts(corp):
    """수주 공시(단일판매·공급계약체결) 최근 3년: [{d,t,amt,ratio,party,until}]"""
    out = []
    bgn = (datetime.date.today() - datetime.timedelta(days=1095)).strftime('%Y%m%d')
    d = jget('%s/list.json?crtfc_key=%s&corp_code=%s&pblntf_ty=I&bgn_de=%s&page_count=100&last_reprt_at=Y'
             % (BASE, KEY, corp, bgn))
    for it in (d.get('list') or []):
        nm = it.get('report_nm') or ''
        if '공급계약' not in nm and '수주' not in nm:
            continue
        rcp = it['rcept_no']
        ent = {'d': '%s-%s-%s' % (it['rcept_dt'][:4], it['rcept_dt'][4:6], it['rcept_dt'][6:8]),
               't': re.sub(r'\s+', ' ', nm).strip(), 'rcp': rcp}
        try:
            # 거래소 공시는 원문 zip(document.xml API)으로 — 표 태그 구조 동일
            b = fetch('%s/document.xml?crtfc_key=%s&rcept_no=%s' % (BASE, KEY, rcp), 60)
            h = ''
            try:
                z = zipfile.ZipFile(io.BytesIO(b))
                for n in z.namelist():
                    raw = z.read(n)
                    for enc in ('utf-8', 'cp949'):
                        try:
                            h += raw.decode(enc)
                            break
                        except Exception:
                            continue
            except Exception:
                pass
            if h:
                rows = []
                for t in tables(h):
                    rows += t
                def find(*words):
                    for r in rows:
                        for i, c in enumerate(r):
                            cc = c.replace(' ', '')
                            if any(w in cc for w in words) and i + 1 < len(r):
                                for c2 in r[i + 1:]:
                                    if c2.strip():
                                        return c2.strip()
                    return None
                amt = tonum(find('계약금액', '공급계약금액'))
                if amt and amt > 1e6:
                    ent['amt'] = round(amt / 1e8, 1)  # 억원
                rt = find('매출액대비', '최근매출액대비')
                if rt:
                    m2 = re.search(r'[\d.]+', rt.replace(',', ''))
                    if m2:
                        ent['ratio'] = float(m2.group(0))
                ent['party'] = (find('계약상대방', '계약상대') or '')[:30]
                ent['until'] = (find('종료일') or '')[:10]
        except Exception:
            pass
        out.append(ent)
        time.sleep(0.3)
        if len(out) >= 30:
            break
    return out

def collect(code, name, corp):
    fl = filings(corp)
    if len(fl) < 4:
        return None
    cum = {}  # label -> {'sales':{item:원},'price':{item:(v,u)},'prod':[...],'backlog':원}
    for rcp, label, q, y in fl:
        tree = doc_tree(rcp)
        if not tree:
            continue
        sec = {}
        biz = None
        for txt, dcm, ele, off, ln in tree:
            tt = txt.replace(' ', '')
            if tt.endswith('사업의내용'):
                biz = (dcm, ele, off, ln)
            if '주요제품' in tt or ('제품및서비스' in tt):
                sec['prd'] = (dcm, ele, off, ln)
            elif '생산설비' in tt or '원재료및생산' in tt:
                sec['fac'] = (dcm, ele, off, ln)
            elif '매출및수주' in tt or ('수주상황' in tt) or (tt.startswith('4.매출') if tt else False):
                sec['sal'] = (dcm, ele, off, ln)
            elif tt.endswith('연결재무제표주석'):
                sec['nt'] = (dcm, ele, off, ln)
            elif tt.endswith('재무제표주석'):
                sec['nt2'] = (dcm, ele, off, ln)
        if biz and ('sal' not in sec or 'prd' not in sec or 'fac' not in sec):
            # 구서식: 사업의 내용이 단일 섹션 — 전체를 각 파서에 사용
            for k in ('sal', 'prd', 'fac'):
                sec.setdefault(k, biz)
        slot = {}
        if 'sal' in sec:
            h = viewer(rcp, *sec['sal'])
            slot['sales'], slot['sales_qc'] = parse_sales_qc(h)
            slot['sales'] = slot['sales'] or {}
            slot['backlog'] = parse_backlog(h)
        if 'prd' in sec:
            h = viewer(rcp, *sec['prd'])
            slot['price'] = parse_price(h)
            if not slot.get('sales'):
                r2, qc2 = parse_sales_qc(h)
                if r2: slot['sales'], slot['sales_qc'] = r2, qc2
        if 'fac' in sec:
            h = viewer(rcp, *sec['fac'])
            slot['prod'] = parse_prod(h)
        for k in ('nt', 'nt2'):  # 주요 고객(10%↑) — 연결 주석 우선, 없으면 별도 주석
            if k in sec and not slot.get('cust'):
                h = viewer(rcp, *sec[k])
                slot['cust'] = parse_customers(h)
        cum[label] = slot
        time.sleep(0.4)
    if not cum:
        return None
    # 분기 차감: label 정렬(연도·분기), 연내 이전 누적과 차감
    labels = sorted(cum.keys())
    def prev_label(lb):
        y, q = int(lb[:2]), int(lb[-1])
        return '%02dQ%d' % (y, q - 1) if q > 1 else None
    items = sorted({it for lb in labels for it in (cum[lb].get('sales') or {})})
    pitems = sorted({it for lb in labels for it in (cum[lb].get('prod') or {})})
    citems = sorted({it for lb in labels for it in (cum[lb].get('cust') or {})})
    quarters = []
    sales_q = {i: [] for i in items}
    price_q = {i: [] for i in items}
    vol_q = {i: [] for i in items}
    util_q = {i: [] for i in pitems}
    cust_q = {i: [] for i in citems}
    backlog = []
    for lb in labels:
        quarters.append('%s.%sQ' % (lb[:2], lb[-1]))
        pl = prev_label(lb)
        for it in items:
            c1 = (cum[lb].get('sales') or {}).get(it)
            c0 = (cum.get(pl, {}).get('sales') or {}).get(it) if pl else 0
            sq = (c1 - c0) if (c1 is not None and c0 is not None) else None
            sales_q[it].append(round(sq / 1e8, 1) if sq is not None else None)
            # 물량·판가: 누적물량 = 누적매출/누적평균판가, 분기 차감 [산출]
            p1 = ((cum[lb].get('price') or {}).get(it) or (None,))[0]
            p0 = ((cum.get(pl, {}).get('price') or {}).get(it) or (None,))[0] if pl else None
            v1 = (c1 / p1) if (c1 and p1) else None
            v0 = (c0 / p0) if (c0 and p0) else (0 if pl is None else None)
            vq = (v1 - v0) if (v1 is not None and v0 is not None) else None
            vol_q[it].append(round(vq / 1e6, 1) if vq is not None else None)  # 판가단위 kg 가정 → 천톤
            pq = (sq / vq) if (sq and vq and vq > 0) else (p1 if (lb.endswith('1') and p1) else None)
            price_q[it].append(round(pq, 1) if pq is not None else None)
        bl = cum[lb].get('backlog')
        backlog.append(round(bl / 1e8, 1) if bl else None)
        # 주요 고객: 보고서 기재값을 누적으로 보고 연내 차감 (분기보고서가 3개월 단일 기재인 회사는 Q1·Q3에 오차 가능 — [산출] 표기)
        for it in citems:
            c1 = (cum[lb].get('cust') or {}).get(it)
            c0 = (cum.get(pl, {}).get('cust') or {}).get(it) if pl else 0
            cv = None
            if c1 is not None and c0 is not None:
                cv = c1 - c0
                if cv < 0 and lb.endswith(('3',)):  # 3Q 보고서가 단일분기 기재인 케이스 추정
                    cv = c1
            elif c1 is not None and lb.endswith('1'):
                cv = c1
            cust_q[it].append(round(cv / 1e8, 2) if cv is not None else None)
        # 가동률: 누적 생산실적/능력 차감 → 분기 가동률
        for it in pitems:
            g1 = (cum[lb].get('prod') or {}).get(it) or {}
            g0 = (cum.get(pl, {}).get('prod') or {}).get(it) if pl else {'cap': 0, 'act': 0}
            u = None
            if g0 is not None and g1.get('cap') is not None and g1.get('act') is not None \
               and (g0.get('cap') is not None and g0.get('act') is not None):
                dc = g1['cap'] - (g0.get('cap') or 0)
                da = g1['act'] - (g0.get('act') or 0)
                if dc and dc > 0:
                    u = round(da / dc * 100, 1)
            if u is None and lb.endswith('1'):
                u = g1.get('util')
            util_q[it].append(u)
    # 단위 교차검증(DartV22Builder 기법): 품목 매출 합 ≈ 재무제표 분기 매출인지 — 1000배 오류 자동 보정
    try:
        cq = json.load(open('public/data/compare/%s.json' % code, encoding='utf-8')).get('qs') or []
        fin = {r[0][2:].replace('Q', '.') + 'Q': r[1] for r in cq if r[1]}
        ratios = []
        for qi, lb in enumerate(quarters):
            ssum = sum(v for it in items for v in [sales_q[it][qi]] if v)
            fv = fin.get(lb)
            if ssum and fv and ssum > 0:
                ratios.append(fv / ssum)
        if ratios:
            ratios.sort()
            med = ratios[len(ratios) // 2]
            scale = 1000 if 300 < med < 3000 else (0.001 if 0.0003 < med < 0.003 else 1)
            if scale != 1:
                DEBUG.append('%s 매출 단위 보정 ×%s (중앙 배율 %.1f)' % (code, scale, med))
                for it in items:
                    sales_q[it] = [round(v * scale, 1) if v is not None else None for v in sales_q[it]]
                    vol_q[it] = [round(v * scale, 1) if v is not None else None for v in vol_q[it]]
    except Exception:
        pass
    # 판가 단위 표기
    punit = ''
    for lb in reversed(labels):
        for it, pv_ in (cum[lb].get('price') or {}).items():
            if pv_[1]:
                punit = pv_[1]
                break
        if punit:
            break
    return {'code': code, 'name': name, 'quarters': quarters, 'items': items,
            'sales': sales_q, 'price': price_q, 'vol': vol_q, 'backlog': backlog, 'util': util_q,
            'cust': cust_q, 'contracts': contracts(corp), 'punit': punit, 'pv': PV,
            'gen': datetime.date.today().isoformat()}

def main():
    if not KEY:
        print('DART_KEY 필요'); sys.exit(1)
    targets = {}
    try:
        extra = json.load(open('qdeep_targets.json', encoding='utf-8'))
        for x in extra:
            targets[x['code']] = x['name']
    except Exception:
        pass
    try:
        sn = json.load(open('public/stocknotes.json', encoding='utf-8'))
        for g in sn['industries']:
            for s in g['stocks']:
                if re.fullmatch(r'\d{6}', s['code']):
                    targets.setdefault(s['code'], s['name'])
    except Exception as e:
        DEBUG.append('stocknotes 실패: %r' % e)
    os.makedirs(OUTDIR, exist_ok=True)
    cutoff = (datetime.date.today() - datetime.timedelta(days=REFRESH_DAYS)).isoformat()
    try:
        cmap = corp_map()
    except Exception as e:
        DEBUG.append('corp_map 실패: %r' % e)
        cmap = {}
    index, ran = {}, 0
    for code, name in targets.items():
        fp = '%s/%s.json' % (OUTDIR, code)
        try:
            old = json.load(open(fp, encoding='utf-8'))
            if old.get('pv') == PV and (old.get('gen') or '') >= cutoff:
                index[code] = name
                continue
        except Exception:
            pass
        if ran >= MAXRUN:
            if os.path.exists(fp):
                index[code] = name
            continue
        corp = cmap.get(code)
        if not corp:
            continue
        ran += 1
        try:
            r = collect(code, name, corp)
        except Exception as e:
            DEBUG.append('%s 예외: %r' % (code, str(e)[:60]))
            r = None
        has_any = r and (r.get('items') or any(x is not None for x in r.get('backlog') or [])
                         or r.get('contracts') or r.get('cust'))
        if has_any:
            json.dump(r, open(fp, 'w', encoding='utf-8'), ensure_ascii=False)
            index[code] = name
            print('%s %s OK 품목%d 분기%d 수주표%s 계약%d' % (code, name, len(r['items']), len(r['quarters']),
                  'Y' if any(x is not None for x in r.get('backlog') or []) else 'N', len(r.get('contracts') or [])), file=sys.stderr)
        else:
            DEBUG.append('%s 품목·수주 없음' % code)
    DEBUG.append('이번 실행 %d (한도 %d, 대상 %d)' % (ran, MAXRUN, len(targets)))
    json.dump({'updated': time.strftime('%Y-%m-%d %H:%M'), 'debug': DEBUG, 'codes': index},
              open('%s/index.json' % OUTDIR, 'w', encoding='utf-8'), ensure_ascii=False)
    print('완료:', DEBUG)

if __name__ == '__main__':
    try:
        main()
    except Exception:
        import traceback
        os.makedirs('public/data', exist_ok=True)
        json.dump({'error': traceback.format_exc(), 'ts': time.strftime('%Y-%m-%d %H:%M')},
                  open('public/data/qdeep_error.json', 'w', encoding='utf-8'), ensure_ascii=False)
        raise
