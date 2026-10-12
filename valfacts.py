#!/usr/bin/env python3
# 전 종목 "사실" 수집기 — 밸류 워크시트가 종목마다 빈 껍데기가 되지 않도록, 조사에 필요한 1차 자료를 자동으로 모은다.
#   대상: 반도체 peer 상대밸류 종목(semipeer.json) + 워크시트 관심 종목(valws_watch.json)
#   ① 확정 수주: DART 단일판매·공급계약 공시 원문 파싱(품목·금액·상대방·지역·기간·정정·해지)
#   ② 정기보고서 원문 발췌: 주요 제품 표 / 매출실적 표 / 수주상황 표 / 가동률 표 / 주요 매출처 문장 (해석 없이 표 그대로)
#   ③ 경영진·지배구조: 최대주주·특수관계인, 임원(특수관계인 임원), 보수, 배당 3년, 자기주식, 5% 주주, 자사주·CB·BW·EB·유증 결정
#   ④ 자동 점검 규칙(flags): 낮은 배당성향, 보수 대비 배당, 승계 전 구조, 자사주 처분, 희석, 주주행동 등
#   ⑤ 경영진 관련 뉴스 반복 언급: 구글 뉴스 RSS — 승계·증여 / 주주환원 / 주주행동 / 보수·주총 / 지배구조 / 사고·제재 / 희석 (미검증 포함, 제목·링크만)
#   ⑥ 컨센서스(네이버 연간 + FY1), 증권사 리포트 목록(reports.json)
# 결과: public/data/vf/<코드>.json (종목별) + public/data/valfacts_idx.json (목록용 요약)
# 필요 시크릿: DART_API_KEY
# 원칙: 숫자는 공시·API 값 그대로(태그 '확인'), 보도는 '보도'. 친족(자녀·손주 등) 개인 이름은 저장하지 않는다(관계만).
import os, sys, json, time, re, io, zipfile, datetime, html, threading, urllib.request, urllib.parse, ssl
from concurrent.futures import ThreadPoolExecutor

VER = 2
KEY = os.environ.get('DART_API_KEY') or os.environ.get('DART_KEY') or ''
OUTDIR = os.environ.get('OUTDIR', 'public/data/vf')
IDX = os.environ.get('IDX', 'public/data/valfacts_idx.json')
BUDGET = int(os.environ.get('BUDGET_MIN', '50')) * 60
WORKERS = int(os.environ.get('WORKERS', '3'))
GAP = float(os.environ.get('DART_GAP', '0.35'))   # DART 호출 간격(초) — 과속하면 IP가 차단돼 타임아웃이 난다
FULL = os.environ.get('FULL', '') == '1'
ONLY = [c for c in os.environ.get('ONLY', '').split(',') if c]
UA = {'User-Agent': 'Mozilla/5.0'}
CTX = ssl.create_default_context(); CTX.check_hostname = False; CTX.verify_mode = ssl.CERT_NONE
KST = datetime.timezone(datetime.timedelta(hours=9)); NOW = datetime.datetime.now(KST); TODAY = NOW.date()
T0 = time.time()
BASE = 'https://opendart.fss.or.kr/api'
DEBUG = []; STAT = {'dart': 0, 'doc': 0, 'news': 0, 'naver': 0, 'err': 0, 'limit': False, 'inc': 0}
FAILRUN = [0]
class DartFail(Exception): pass   # 네트워크·한도 실패 — '자료 없음'과 구분해서, 실패한 구간은 기존 값을 지키고 다음 실행에서 다시 받는다
_lock = threading.Lock(); _last = [0.0]

def log(s):
    s = str(s)[:300]
    with _lock: DEBUG.append(s)
    print(s, file=sys.stderr, flush=True)
def left(): return BUDGET - (time.time() - T0)
def tonum(s):
    try:
        s = str(s).replace(',', '').replace('%', '').replace('원', '').strip()
        if s in ('', '-', 'N/A'): return None
        return float(s)
    except Exception: return None
def ymd(s):
    """'2026년 07월 27일' / '2026-07-27' / '20260727' → '2026-07-27'"""
    m = re.search(r'(\d{4})\D{0,3}(\d{1,2})\D{0,3}(\d{1,2})', str(s or ''))
    return '%s-%02d-%02d' % (m.group(1), int(m.group(2)), int(m.group(3))) if m else ''

# ───────── 네트워크
def _throttle(gap):
    with _lock:
        w = _last[0] + gap - time.time()
        if w > 0: time.sleep(w)
        _last[0] = time.time()
def fetch(url, timeout=40, tries=3):
    err = None
    for i in range(tries):
        try:
            return urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout, context=CTX).read()
        except Exception as e:
            err = e; time.sleep(1.2 * (i + 1))
    raise err
def _fail(what, e):
    STAT['err'] += 1
    with _lock: FAILRUN[0] += 1; n = FAILRUN[0]
    log('DART 실패 %s %r (연속 %d)' % (what, str(e)[:70], n))
    if n >= 12: STAT['limit'] = True; log('DART 연속 실패 12회 → 이번 실행은 DART 수집 중단(다음 실행에서 이어감)')
    elif n % 4 == 0: time.sleep(45)
    raise DartFail(what)
def api(name, **kw):
    """OpenDART JSON → list(자료 없으면 []). 네트워크 실패·사용한도 초과는 DartFail"""
    if not KEY: return []
    if STAT['limit']: raise DartFail('중단됨')
    _throttle(GAP)
    try:
        j = json.loads(fetch('%s/%s.json?%s' % (BASE, name, urllib.parse.urlencode(dict(crtfc_key=KEY, **kw))), 25, 2).decode('utf-8'))
    except Exception as e:
        _fail(name, e)
    FAILRUN[0] = 0; STAT['dart'] += 1
    st = j.get('status')
    if st == '020': STAT['limit'] = True; log('DART 사용한도 초과'); raise DartFail('한도')
    if st not in ('000', '013'): log('api %s status %s %s' % (name, st, j.get('message')))
    return j.get('list') or []
def ddoc(rcept):
    """공시 원문 zip → {파일명: 텍스트}. 실패는 DartFail"""
    if not KEY: return {}
    if STAT['limit']: raise DartFail('중단됨')
    _throttle(GAP)
    try:
        b = fetch('%s/document.xml?crtfc_key=%s&rcept_no=%s' % (BASE, KEY, rcept), 90, 2)
        z = zipfile.ZipFile(io.BytesIO(b)); out = {}
        for n in z.namelist():
            raw = z.read(n)
            t = raw.decode('utf-8', 'ignore')
            if t.count('\ufffd') > 50 or (len(t) < len(raw) * 0.6): t = raw.decode('euc-kr', 'ignore')
            out[n] = t
    except Exception as e:
        _fail('원문 ' + rcept, e)
    FAILRUN[0] = 0; STAT['doc'] += 1
    return out

# ───────── ① 공급계약 공시
def cells_of(raw):
    t = re.sub(r'<(style|STYLE)[^>]*>.*?</\1>', ' ', raw, flags=re.S)
    t = re.sub(r'<title[^>]*>.*?</title>', '|', t, flags=re.S | re.I)
    t = html.unescape(re.sub(r'<[^>]+>', '|', t)).replace('\xa0', ' ')
    t = re.sub(r'[ㆍ・･∙‧]', '·', t)
    return [c for c in (re.sub(r'\s+', ' ', x).strip() for x in t.split('|')) if c]
def _after(cells, pat, start=0, n=1, stop=None, span=8):
    for i in range(start, len(cells)):
        if re.search(pat, cells[i]):
            vals = []
            for j in range(i + 1, min(i + 1 + span, len(cells))):
                if stop and re.search(stop, cells[j]): break
                vals.append(cells[j])
                if len(vals) >= n: break
            return i, vals
    return -1, []
def parse_contract(raw):
    c = cells_of(raw)
    corr = any(x.startswith('정정신고') for x in c)
    reason = ''
    if corr:
        _, v = _after(c, r'^3\.\s*정정사유'); reason = v[0] if v else ''
        idx = [i for i, x in enumerate(c) if re.match(r'^1\.\s*판매·공급계약\s*(내용|구분)', x)]
        if idx: c = c[idx[-1]:]
    i, v = _after(c, r'^-\s*세부내용', n=4, stop=r'^2\.')
    if i < 0: i, v = _after(c, r'^1\.\s*판매·공급계약\s*(내용|구분)', n=4, stop=r'^2\.')
    item = ' '.join(v)[:120]
    amt = None
    for pat in (r'^계약금액\s*총액', r'^계약금액\s*\(원\)', r'^확정\s*계약금액', r'^계약금액'):
        _, v = _after(c, pat)
        if v and tonum(v[0]) is not None: amt = tonum(v[0]); break
    _, v = _after(c, r'^최근\s*매출액'); rev = tonum(v[0]) if v else None
    _, v = _after(c, r'^매출액\s*대비'); ratio = tonum(v[0]) if v else None
    _, v = _after(c, r'^3\.\s*계약상대', n=3, stop=r'^(-|\d+\.)'); cp = re.sub(r'^\s*(주식회사|\(주\)|㈜)\s*|\s*(주식회사|\(주\)|㈜)\s*$', '', ' '.join(v)).strip()[:80]
    _, v = _after(c, r'^4\.\s*판매·공급지역'); region = (v[0] if v else '')[:40]
    k, _ = _after(c, r'^5\.\s*계약기간')
    _, v = _after(c, r'^시작일', start=max(k, 0)); d0 = ymd(v[0]) if v else ''
    _, v = _after(c, r'^종료일', start=max(k, 0)); d1 = ymd(v[0]) if v else ''
    _, v = _after(c, r'계약\(수주\)일'); cd = ymd(v[0]) if v else ''
    return {'item': item, 'amt': round(amt / 1e8, 1) if amt else None, 'rev': round(rev / 1e8, 1) if rev else None, 'ratio': ratio,
            'cp': cp, 'region': region, 'from': d0, 'to': d1, 'cd': cd, 'corr': corr, 'reason': reason[:80]}
def contracts(corp, old, months=30):
    """old: 기존 {'docs': {rcept: parsed}} → 새 공시만 원문을 받는다"""
    docs = dict((old or {}).get('docs') or {})
    bgn = (TODAY - datetime.timedelta(days=30 * months)).strftime('%Y%m%d')
    rows = []
    for pg in (1, 2, 3):
        r = api('list', corp_code=corp, bgn_de=bgn, end_de=TODAY.strftime('%Y%m%d'), pblntf_ty='I', page_count=100, page_no=pg)
        rows += r
        if len(r) < 100: break
    hits = [r for r in rows if '공급계약' in (r.get('report_nm') or '')]
    partial = False
    for r in hits:
        rc = r['rcept_no']
        if rc in docs: continue
        nm = re.sub(r'\s+', '', r.get('report_nm') or '')
        d = {'rc': rc, 'd': ymd(r.get('rcept_dt')), 'nm': nm[:40]}
        if '해지' in nm:
            d['cancel'] = True
        else:
            try: raws = ddoc(rc)
            except DartFail: partial = True; break   # 받은 데까지만 저장하고 다음 실행에서 이어감
            if not raws: continue
            try: d.update(parse_contract(max(raws.values(), key=len)))
            except Exception as e: d['perr'] = repr(e)[:80]
        docs[rc] = d
    # 같은 계약(계약일·품목·상대방)은 최신 공시 1건으로 묶고 정정 횟수를 센다
    groups = {}
    for rc in sorted(docs):
        d = docs[rc]
        if d.get('cancel') or d.get('perr'): continue
        key = (d.get('cd') or d.get('from') or d['d'], re.sub(r'\W', '', d.get('item') or '')[:16], re.sub(r'\W', '', d.get('cp') or '')[:8])
        g = groups.setdefault(key, {'n': 0, 'reasons': [], 'first': d['d']})
        g['n'] += 1 if d.get('corr') else 0; g['last'] = d
        if d.get('corr') and d.get('reason'): g['reasons'].append(d['reason'])
    lst = []
    for key, g in groups.items():
        d = dict(g['last']); d['first'] = g['first']; d['ncorr'] = g['n']; d['reasons'] = g['reasons'][-3:]
        lst.append(d)
    lst.sort(key=lambda x: x.get('cd') or x['first'], reverse=True)
    today = TODAY.isoformat(); y1 = (TODAY - datetime.timedelta(days=365)).isoformat()
    by = {}
    for d in lst:
        y = (d.get('cd') or d['first'])[:4]
        if d.get('amt'): by[y] = round(by.get(y, 0) + d['amt'], 1)
    cps = {}
    for d in lst:
        if d.get('amt') and d.get('cp'): cps[d['cp']] = round(cps.get(d['cp'], 0) + d['amt'], 1)
    summ = {'n': len(lst), 'by': by,
            'm12': round(sum(d['amt'] for d in lst if d.get('amt') and (d.get('cd') or d['first']) >= y1), 1),
            'open': round(sum(d['amt'] for d in lst if d.get('amt') and (d.get('to') or '') >= today), 1),
            'open_n': sum(1 for d in lst if d.get('amt') and (d.get('to') or '') >= today),
            'cps': sorted(cps.items(), key=lambda x: -x[1])[:5],
            'cancel': [{'rc': d['rc'], 'd': d['d'], 'nm': d['nm']} for d in docs.values() if d.get('cancel')],
            'hidden': sum(1 for d in lst if not d.get('amt'))}
    return {'docs': docs, 'list': lst[:40], 'sum': summ, 'partial': partial}, rows

# ───────── ② 정기보고서 원문 발췌
def _txt(s): return re.sub(r'\s+', ' ', html.unescape(re.sub(r'<[^>]+>', ' ', s)).replace('\xa0', ' ')).strip()
def _table(tb, maxr=28, maxc=10):
    rows = []
    for tr in re.findall(r'<TR[^>]*>(.*?)</TR>', tb, flags=re.S | re.I):
        row = []
        for m in re.finditer(r'<(TD|TH|TE|TU)([^>]*)>(.*?)</\1>', tr, flags=re.S | re.I):
            a = m.group(2); t = _txt(m.group(3))[:48]
            cs = re.search(r'COLSPAN="(\d+)"', a, re.I); rs = re.search(r'ROWSPAN="(\d+)"', a, re.I)
            cs = int(cs.group(1)) if cs else 1; rs = int(rs.group(1)) if rs else 1
            row.append(t if cs == 1 and rs == 1 else [t, cs, rs])
        if row: rows.append(row[:maxc])
    return rows[:maxr]
def _isdata(rows):
    if len(rows) < 2: return False
    flat = ' '.join(c if isinstance(c, str) else c[0] for r in rows for c in r)
    return len(re.findall(r'\d', flat)) >= 4 and max(len(r) for r in rows) >= 2
def _blocks(seg):
    out = []
    for m in re.finditer(r'<P[^>]*>(.*?)</P>|<TABLE[^>]*>.*?</TABLE>', seg, flags=re.S | re.I):
        if m.group(0)[:2].upper() == '<P':
            t = _txt(m.group(1))
            if t: out.append(('p', t))
        else:
            rows = _table(m.group(0))
            flat = ' '.join(c if isinstance(c, str) else c[0] for r in rows for c in r)
            if len(rows) <= 2 and '단위' in flat and len(flat) < 60: out.append(('u', flat))
            elif rows: out.append(('t', rows))
    return out
HEAD = re.compile(r'^(\(?[가-하]\)?\.|\(\d+\)|\d+\)|[①-⑩]|\[.{2,20}\]$|[■□▶◆●-]\s*\S)')
def parse_biz(raw):
    """사업의 내용에서 표를 '그대로' 발췌. 반환 {'prod','sales','order','util': {u,r,h}, 'order_note','cust'}"""
    ts = [(m.start(), m.end(), _txt(m.group(1))) for m in re.finditer(r'<TITLE[^>]*>(.*?)</TITLE>', raw, flags=re.S | re.I)]
    def section(pat, stop):
        s = next((i for i, t in enumerate(ts) if re.search(pat, t[2])), -1)
        if s < 0: return ''
        e = next((ts[i][0] for i in range(s + 1, len(ts)) if re.search(stop, ts[i][2])), None)
        return raw[ts[s][1]: e if e else ts[s][1] + 300000]
    NEXT = r'^\d+\.\s|^(I|V|X|Ⅰ|Ⅱ|Ⅲ|Ⅳ|Ⅴ)+\.'
    out = {}
    def grab(seg, want):
        """want: [(키, 소제목 패턴)] — 소제목 뒤 첫 데이터 표. 소제목이 없으면 구간의 첫 데이터 표를 첫 키에"""
        bl = _blocks(seg); head = ''; unit = ''; notes = {}
        for kind, v in bl:
            if kind == 'p':
                if len(v) > 45 and HEAD.search(v) and re.search(r'수주|매출\s*실적|가동률|생산능력', v[:16]):
                    head = v[:16]; unit = ''
                    for k, pat in want:
                        if re.search(pat, head) and k not in out: notes[k] = v[:300]
                elif len(v) <= 45 and HEAD.search(v): head = v; unit = ''
                elif '단위' in v and len(v) < 40: unit = v
                else:
                    for k, pat in want:
                        if re.search(pat, head) and k not in out and len(notes.get(k, '')) < 260: notes[k] = (notes.get(k, '') + ' ' + v).strip()[:300]
                continue
            if kind == 'u': unit = v; continue
            if not _isdata(v): continue
            for k, pat in want:
                if k not in out and re.search(pat, head):
                    out[k] = {'h': head[:40], 'u': unit[:30], 'r': v}; break
        for k, t in notes.items():
            if k not in out and t: out[k + '_note'] = t
            elif k == 'order' and t: out['order_note'] = t[:200]
        return bl
    s2 = section(r'주요\s*제품\s*및\s*서비스|주요\s*제품', NEXT)
    if s2:
        bl = _blocks(s2); unit = ''
        for kind, v in bl:
            if kind == 'u' or (kind == 'p' and '단위' in v and len(v) < 40): unit = v
            elif kind == 't' and _isdata(v): out['prod'] = {'h': '주요 제품 등의 현황', 'u': unit[:30], 'r': v}; break
    s3 = section(r'원재료\s*및\s*생산설비', NEXT)
    if s3: grab(s3, [('util', r'가동률'), ('capa', r'생산능력')])
    s4 = section(r'매출\s*및\s*수주상황|매출에\s*관한\s*사항', NEXT)
    if s4:
        bl = grab(s4, [('sales', r'매출\s*실적'), ('order', r'수주')])
        for kind, v in bl:
            if kind == 'p' and re.search(r'주요\s*(매출처|고객|거래처)', v) and len(v) > 20:
                out['cust'] = v[:300]; break
        if 'order' not in out and 'order_note' not in out:
            for kind, v in bl:
                if kind == 'p' and '수주' in v and re.search(r'해당|없습니다|없음', v): out['order_note'] = v[:200]; break
    # 수주상황 표의 합계 행 마지막 숫자 = 수주잔고 금액(표 그대로 함께 보여 주므로 화면에서 대조 가능)
    o = out.get('order')
    if o:
        hdr = ' '.join(c if isinstance(c, str) else c[0] for r in o['r'][:2] for c in r)
        if '잔고' in hdr:
            tot = next((r for r in reversed(o['r']) if re.search(r'합\s*계|^계$|총\s*계', ' '.join(c if isinstance(c, str) else c[0] for c in r))), None)
            if tot:
                nums = [tonum(c if isinstance(c, str) else c[0]) for c in tot]
                nums = [x for x in nums if x is not None]
                if nums:
                    u = o.get('u') or ''
                    mul = 1e-8 if re.search(r'단위\s*[:：]?\s*원', u) else 1e-5 if '천원' in u else 0.01 if '백만원' in u else 1 if '억원' in u else None
                    out['backlog'] = {'raw': nums[-1], 'u': u, 'eok': round(nums[-1] * mul, 1) if mul else None}
    return out
def periodic(rows_a):
    """정기공시 목록에서 최신 보고서 → (rcept, 이름, 사업연도, reprt_code), 최신 사업보고서 연도"""
    latest = None; annual = None
    for r in sorted(rows_a, key=lambda x: x.get('rcept_no', ''), reverse=True):
        nm = r.get('report_nm') or ''
        m = re.search(r'(사업|반기|분기)보고서\s*\((\d{4})\.(\d{2})\)', nm)
        if not m or '[첨부' in nm: continue
        kind, y, mm = m.group(1), int(m.group(2)), int(m.group(3))
        code = '11011' if kind == '사업' else '11012' if kind == '반기' else '11014' if mm >= 8 else '11013'
        if not latest: latest = (r['rcept_no'], re.sub(r'\s+', ' ', nm).strip(), y, code)
        if kind == '사업' and not annual: annual = (r['rcept_no'], y)
        if latest and annual: break
    return latest, annual

# ───────── ③ 경영진·지배구조
CORP_PAT = re.compile(r'\(주\)|㈜|주식회사|유한회사|재단|조합|펀드|투자|홀딩스|\bInc\b|Ltd|LLC|Corp|CO\.|은행|증권|자산운용|공단|연금', re.I)
KID = re.compile(r'자녀|^자$|子|女|아들|딸|손자|손녀|손주|직계비속|^제$|^매$')
def governance(corp, latest, annual):
    g = {}
    y_a = annual[1] if annual else TODAY.year - 1
    # 최대주주·특수관계인: 최신 보고서 → 없으면 사업보고서
    hy = api('hyslrSttus', corp_code=corp, bsns_year=str(latest[2]), reprt_code=latest[3]) if latest else []
    hy_src = latest[0] if latest and hy else None
    if not hy and annual: hy = api('hyslrSttus', corp_code=corp, bsns_year=str(y_a), reprt_code='11011'); hy_src = annual[0]
    holders = []; total = None
    for r in hy:
        if (r.get('stock_knd') or '') not in ('보통주', '의결권 있는 주식', '의결권있는주식'): continue
        rel = re.sub(r'\s+', '', r.get('relate') or ''); nm = re.sub(r'\s+', '', r.get('nm') or ''); pct = tonum(r.get('trmend_posesn_stock_qota_rt'))
        if not rel or nm in ('계', '합계', '소계'):
            if pct is not None: total = pct
            continue
        if pct is None: continue
        is_corp = bool(CORP_PAT.search(nm)); self_ = rel in ('본인', '최대주주')
        keep = self_ or is_corp or re.search(r'임원|계열|관계회사|법인|재단', rel)
        holders.append({'nm': nm if keep else '(' + rel + ')', 'rel': rel, 'pct': pct, 'corp': is_corp, 'self': self_, 'kid': bool(KID.search(rel)) and not is_corp})
    holders.sort(key=lambda x: -x['pct'])
    if holders:
        g['holders'] = holders[:12]; g['hsum'] = total if total is not None else round(sum(h['pct'] for h in holders), 2)
        g['kid_pct'] = round(sum(h['pct'] for h in holders if h['kid']), 2); g['kid_n'] = sum(1 for h in holders if h['kid'])
        g['h_asof'] = (hy[0].get('stlm_dt') or ''); g['h_rc'] = hy_src
    if not annual: return g
    A = dict(corp_code=corp, bsns_year=str(y_a), reprt_code='11011'); g['a_rc'] = annual[0]; g['a_y'] = y_a
    r = api('mrhlSttus', **A)
    if r: g['minor'] = tonum(r[0].get('hold_stock_rate'))
    # 배당 3년
    r = api('alotMatter', **A)
    def row(pats, knd=None):
        for p in pats:
            for x in r:
                if re.search(p, re.sub(r'\s+', '', x.get('se') or '')) and (knd is None or (x.get('stock_knd') or '-') in knd):
                    v = [tonum(x.get(k)) for k in ('thstrm', 'frmtrm', 'lwfr')]
                    if any(a is not None for a in v): return v
        return [None, None, None]
    if r:
        dps = row([r'주당현금배당금'], ('보통주',)); pay = row([r'\(연결\)현금배당성향', r'현금배당성향']); yld = row([r'현금배당수익률'], ('보통주',))
        tot = row([r'현금배당금총액']); ni = row([r'\(연결\)당기순이익', r'당기순이익'])
        g['div'] = [{'y': y_a - i, 'dps': dps[i], 'payout': pay[i], 'yield': yld[i], 'tot': round(tot[i] / 100, 1) if tot[i] is not None else None,
                     'ni': round(ni[i] / 100, 1) if ni[i] is not None else None} for i in range(3)]
    # 보수
    r = api('hmvAuditAllSttus', **A)
    if r:
        t = tonum(r[0].get('mendng_totamt')); g['pay'] = {'n': tonum(r[0].get('nmpr')), 'tot': round(t / 1e8, 2) if t else None}
    r = api('hmvAuditIndvdlBySttus', **A)
    ind = [{'nm': x.get('nm'), 'pos': re.sub(r'\s+', '', x.get('ofcps') or ''), 'amt': round(tonum(x.get('mendng_totamt')) / 1e8, 2)} for x in r if tonum(x.get('mendng_totamt'))]
    if ind: g.setdefault('pay', {})['ind'] = sorted(ind, key=lambda x: -x['amt'])[:5]
    # 임원: 최대주주 본인 생년, 특수관계인 임원(이름 없이 직위·생년)
    r = api('exctvSttus', **A)
    fam = []
    for x in r:
        rel = re.sub(r'\s+', '', x.get('mxmm_shrholdr_relate') or ''); by = re.search(r'(\d{4})', x.get('birth_ym') or '')
        if rel == '본인' and by and 'top_birth' not in g: g['top_birth'] = int(by.group(1)); g['top_pos'] = re.sub(r'\s+', '', x.get('ofcps') or '')
        elif rel and rel not in ('-', '본인', '해당없음', '없음', '해당사항없음', '임원', '등기임원', '계열회사임원', '계열사임원'):
            fam.append({'rel': rel, 'pos': re.sub(r'\s+', '', x.get('ofcps') or ''), 'reg': re.sub(r'\s+', '', x.get('rgist_exctv_at') or ''), 'by': int(by.group(1)) if by else None})
    if r: g['exec_n'] = len(r)
    if fam: g['fam'] = fam[:8]
    # 자기주식(사업보고서 기말) + 발행주식
    r = api('tesstkAcqsDspsSttus', **A)
    for x in r:
        if (x.get('acqs_mth1') or '').strip() == '총계' and (x.get('stock_knd') or '') == '보통주':
            g['tstk'] = {'bgn': tonum(x.get('bsis_qy')), 'acq': tonum(x.get('change_qy_acqs')), 'dsp': tonum(x.get('change_qy_dsps')), 'ret': tonum(x.get('change_qy_incnr')), 'end': tonum(x.get('trmend_qy'))}
    r = api('stockTotqySttus', **A)
    for x in r:
        tot = tonum(x.get('istc_totqy'))
        if tot and re.search(r'보통주|의결권\s*있는', x.get('se') or ''):
            g['shares'] = tot; ts = tonum(x.get('tesstk_co')) or 0
            g.setdefault('tstk', {})['pct'] = round(ts / tot * 100, 2); g['tstk'].setdefault('end', ts); break
    return g
def decisions(corp):
    """자사주 취득·처분·신탁, CB·BW·EB, 유상증자 결정(최근 3년)"""
    out = []; bgn = (TODAY - datetime.timedelta(days=365 * 3)).strftime('%Y%m%d'); end = TODAY.strftime('%Y%m%d')
    P = dict(corp_code=corp, bgn_de=bgn, end_de=end)
    eok = lambda v: round(tonum(v) / 1e8, 1) if tonum(v) else None
    for x in api('tsstkAqDecsn', **P):
        out.append({'k': '자기주식 취득 결정', 'lv': 'ok', 'rc': x.get('rcept_no'), 'amt': eok(x.get('aqpln_prc_ostk')), 'qty': tonum(x.get('aqpln_stk_ostk')), 'why': _txt(x.get('aq_pp') or '')[:60]})
    for x in api('tsstkAqTrctrCnsDecsn', **P):
        out.append({'k': '자기주식 취득 신탁계약', 'lv': 'ok', 'rc': x.get('rcept_no'), 'amt': eok(x.get('ctr_prc')), 'why': _txt(x.get('ctr_pp') or '')[:60], 'to': ymd(x.get('ctr_pd_edd'))})
    for x in api('tsstkDpDecsn', **P):
        how = '시간외대량매매' if tonum(x.get('dp_m_ovtm')) else '장내' if tonum(x.get('dp_m_mkt')) else '장외' if tonum(x.get('dp_m_otc')) else '기타'
        out.append({'k': '자기주식 처분 결정', 'lv': 'warn', 'rc': x.get('rcept_no'), 'amt': eok(x.get('dppln_prc_ostk')), 'qty': tonum(x.get('dppln_stk_ostk')), 'prc': tonum(x.get('dpstk_prc_ostk')), 'how': how, 'why': _txt(x.get('dp_pp') or '')[:60]})
    for nm, k in (('cvbdIsDecsn', '전환사채(CB) 발행'), ('bdwtIsDecsn', '신주인수권부사채(BW) 발행'), ('exbdIsDecsn', '교환사채(EB) 발행')):
        for x in api(nm, **P):
            out.append({'k': k, 'lv': 'warn', 'rc': x.get('rcept_no'), 'amt': eok(x.get('bd_fta')), 'prc': tonum(x.get('cv_prc') or x.get('ex_prc')), 'vs': x.get('cvisstk_tisstk_vs') or x.get('ex_stk_tisstk_vs') or x.get('extg_tisstk_vs')})
    for x in api('piicDecsn', **P):
        amt = sum(tonum(x.get(f)) or 0 for f in ('fdpp_fclt', 'fdpp_bsninh', 'fdpp_op', 'fdpp_dtrp', 'fdpp_ocsa', 'fdpp_etc'))
        out.append({'k': '유상증자 결정', 'lv': 'warn', 'rc': x.get('rcept_no'), 'amt': round(amt / 1e8, 1) if amt else None, 'qty': tonum(x.get('nstk_ostk_cnt')), 'how': x.get('ic_mthn')})
    for o in out: o['d'] = ymd((o.get('rc') or '')[:8])
    out.sort(key=lambda x: x.get('rc') or '', reverse=True)
    return out
def majors(corp, top_nm):
    best = {}
    for x in api('majorstock', corp_code=corp):
        nm = re.sub(r'\s+', '', x.get('repror') or ''); d = x.get('rcept_dt') or ''
        if nm not in best or d > best[nm]['d']:
            best[nm] = {'nm': nm, 'pct': tonum(x.get('stkrt')), 'd': d, 'why': _txt(x.get('report_resn') or '')[:40], 'rc': x.get('rcept_no')}
    out = [v for k, v in best.items() if v['pct'] and v['pct'] >= 5 and k != re.sub(r'\s+', '', top_nm or '') and v['d'] >= (TODAY - datetime.timedelta(days=365 * 3)).isoformat()]
    for v in out:
        if not CORP_PAT.search(v['nm']): v['nm'] = '(개인 5% 주주)'
    return sorted(out, key=lambda x: -x['pct'])[:6]

# ───────── ④ 자동 점검 규칙
def flags(g, dec, maj, con, news):
    f = []; add = lambda lv, k, v, tag='확인', rc=None: f.append({'lv': lv, 'k': k, 'v': v, 'tag': tag, 'rc': rc})
    a_rc = g.get('a_rc'); div = g.get('div') or []
    pays = [d['payout'] for d in div if d.get('payout') is not None and (d.get('ni') or 0) > 0]
    prof = [d for d in div if (d.get('ni') or 0) > 0]
    txt = ' · '.join('%d년 %s' % (d['y'], ('%.1f%%' % d['payout']) if d.get('payout') is not None else '무배당') for d in div if d.get('ni') is not None)
    if prof and not pays and all(not d.get('dps') for d in prof):
        add('bad', '배당', '흑자인데 배당 없음 (%s)' % txt, rc=a_rc)
    elif pays:
        avg = sum(pays) / len(pays)
        if avg < 5: add('bad', '배당', '배당성향 매우 낮음 — %s (흑자 연도 평균 %.1f%%)' % (txt, avg), rc=a_rc)
        elif avg < 10: add('warn', '배당', '배당성향 낮음 — %s (평균 %.1f%%)' % (txt, avg), rc=a_rc)
        elif avg >= 25: add('ok', '배당', '배당성향 %s (평균 %.1f%%)' % (txt, avg), rc=a_rc)
        else: add('info', '배당', '배당성향 %s (평균 %.1f%%)' % (txt, avg), rc=a_rc)
    ind = (g.get('pay') or {}).get('ind') or []
    if ind and div and div[0].get('tot'):
        top = ind[0]; r = top['amt'] / div[0]['tot'] * 100
        if r >= 50: add('bad' if r >= 100 else 'warn', '보수 대 배당', '%s %s 보수 %.1f억 = 그해 배당총액 %.1f억의 %.0f%%' % (top['pos'], top['nm'], top['amt'], div[0]['tot'], r), rc=a_rc)
    elif ind and div and not div[0].get('tot'):
        add('warn', '보수 대 배당', '5억 이상 보수 수령자 있음(%s %.1f억) · 그해 배당 없음' % (ind[0]['pos'], ind[0]['amt']), rc=a_rc)
    hs = g.get('holders') or []; top = next((h for h in hs if h['self']), hs[0] if hs else None)
    if top:
        g['top'] = {'nm': top['nm'], 'pct': top['pct'], 'corp': top['corp']}
        if not top['corp']:
            by = g.get('top_birth'); kid = g.get('kid_pct') or 0; fam = g.get('fam') or []
            if by and by <= TODAY.year - 65 and (top['pct'] >= 10 or (g.get('hsum') or 0) >= 25) and kid < 1:
                add('warn', '승계 전 구조', '최대주주 %d년생·본인 지분 %.2f%%, 자녀 등 지분 %.2f%%%s — 증여·상속이 아직 남아 있어 주가·승계 관련 이야기가 나오기 쉬운 조건(사실 여부와 별개로 지분 이동을 추적)' % (by, top['pct'], kid, ', 특수관계인 임원 %d명' % len(fam) if fam else ''), rc=g.get('h_rc'))
            elif kid >= 1:
                add('info', '자녀 지분', '자녀 등 %d명 합 %.2f%% (최대주주 %.2f%%%s)' % (g.get('kid_n') or 0, kid, top['pct'], ', %d년생' % by if by else ''), rc=g.get('h_rc'))
        if g.get('hsum') is not None and g['hsum'] < 20: add('info', '지배력', '최대주주·특수관계인 합 %.2f%% — 지분이 낮아 경영권 분쟁·주주행동에 열려 있음' % g['hsum'], rc=g.get('h_rc'))
    if g.get('fam'):
        add('info', '가족 임원', '최대주주 특수관계인 임원 %d명: %s' % (len(g['fam']), ', '.join('%s(%s%s)' % (x['pos'], '%d년생·' % x['by'] if x.get('by') else '', x['reg']) for x in g['fam'][:4])), rc=a_rc)
    cut = (TODAY - datetime.timedelta(days=730)).isoformat()
    for d in dec:
        if (d.get('d') or '') < cut: continue
        if d['k'] == '자기주식 처분 결정':
            add('warn', '자기주식 처분', '%s %s주%s%s, %s — 소각 아님. 목적: %s' % (d['d'], '{:,.0f}'.format(d.get('qty') or 0), ' · 주당 {:,.0f}원'.format(d['prc']) if d.get('prc') else '', ' · %.1f억' % d['amt'] if d.get('amt') else '', d.get('how') or '', d.get('why') or '-'), rc=d.get('rc'))
        elif d['lv'] == 'ok':
            add('ok', d['k'], '%s%s%s' % (d['d'], ' · %.0f억' % d['amt'] if d.get('amt') else '', ' · ' + d['why'] if d.get('why') else ''), rc=d.get('rc'))
        else:
            add('warn', '희석', '%s %s%s%s' % (d['d'], d['k'], ' %.0f억' % d['amt'] if d.get('amt') else '', ' · 발행주식 대비 %s%%' % d['vs'] if d.get('vs') and d['vs'] != '-' else ''), rc=d.get('rc'))
    t = g.get('tstk') or {}
    if t.get('ret'): add('ok', '자기주식 소각', '%d 사업연도 %s주 소각' % (g.get('a_y') or 0, '{:,.0f}'.format(t['ret'])), rc=a_rc)
    if (t.get('pct') or 0) >= 5 and not t.get('ret'): add('info', '자기주식 보유', '발행주식의 %.1f%% 보유 · 소각 이력(직전 사업연도) 없음' % t['pct'], rc=a_rc)
    for m in maj:
        act = re.search(r'보유목적|경영참|일반투자', m.get('why') or '')
        add('warn' if act else 'info', '5% 주주', '%s %.2f%% (%s%s)' % (m['nm'], m['pct'], m['d'], ' · ' + m['why'] if m.get('why') else ''), rc=m.get('rc'))
    for d in (con or {}).get('list') or []:
        if d.get('ncorr', 0) >= 2: add('info', '계약 정정 반복', '%s %s — 정정 %d회(%s)' % (d.get('cd') or d['first'], (d.get('item') or '')[:24], d['ncorr'], ', '.join(d.get('reasons') or [])[:40]), rc=d.get('rc'))
    if (con or {}).get('sum', {}).get('cancel'): add('warn', '계약 해지', '공급계약 해지 공시 %d건' % len(con['sum']['cancel']), rc=con['sum']['cancel'][0]['rc'])
    kc = (news or {}).get('kc') or {}
    for b, lv, th in (('사고·제재', 'bad', 1), ('승계·증여', 'warn', 1), ('주주행동', 'warn', 2), ('보수·주총', 'warn', 3), ('소송·분쟁', 'info', 1), ('희석·자금조달', 'info', 2), ('지배구조·경영권', 'info', 2), ('주주환원', 'info', 3)):
        if kc.get(b, 0) >= th:
            ex = next((x['t'] for x in news['items'] if b in x['b']), '')
            add(lv, '뉴스: ' + b, '최근 1년 관련 기사 %d건 — 예: "%s" (사실 여부는 기사·공시로 확인 필요)' % (kc[b], ex[:60]), tag='보도')
    order = {'bad': 0, 'warn': 1, 'info': 2, 'ok': 3}
    f.sort(key=lambda x: order.get(x['lv'], 9))
    return f

# ───────── ⑤ 뉴스(경영진·지배구조 반복 언급)
BUCKETS = [
    ('승계·증여', r'승계|증여|상속|2세|3세|오너\s*일가|자녀|아들|딸|주가\s*누르기'),
    ('주주환원', r'주주환원|배당|자사주|자기주식|소각|밸류업|기업가치\s*제고'),
    ('주주행동', r'행동주의|주주제안|소액주주|표\s*대결|위임장|주주연대|주주행동|의결권|주주\s*홀대|공개\s*서한'),
    ('보수·주총', r'보수|연봉|주총|주주총회|부결|황금낙하산'),
    ('지배구조·경영권', r'지배구조|경영권|최대주주|지분\s*매각|오너'),
    ('사고·제재', r'횡령|배임|분식|제재|과징금|압수수색|검찰|기소|불성실공시|주가조작|미공개\s*정보|상장폐지|거래정지|감사의견'),
    ('소송·분쟁', r'소송|분쟁|가처분|특허\s*침해'),
    ('희석·자금조달', r'유상증자|전환사채|교환사채|신주인수권|\bCB\b|\bBW\b|\bEB\b|물적분할|쪼개기'),
]
Q1 = '승계 OR 증여 OR 상속 OR "주가 누르기" OR 주주환원 OR 자사주 OR 행동주의 OR 소액주주 OR 주주제안 OR 보수 OR 주총 OR 경영권 OR 지배구조 OR 최대주주'
Q2 = '횡령 OR 배임 OR 제재 OR 과징금 OR 소송 OR 불성실공시 OR 유상증자 OR 전환사채 OR 교환사채 OR 물적분할 OR 검찰 OR 주가조작'
PART = r'[은는이가의에도와과를을로만,·…\s\]\)\'"”’‘“!?:\-]'
NEWS_FAIL = [0]
def name_hit(name, title):
    if len(name) >= 4 and not re.fullmatch(r'[A-Za-z]+', name): return name in title
    return bool(re.search(r'(?<![가-힣A-Za-z0-9])' + re.escape(name) + r'(?=' + PART + r'|$)', title))
def news(name, old):
    if NEWS_FAIL[0] >= 4: return old
    seen = {x['t']: x for x in (old or {}).get('items') or []}
    after = (TODAY - datetime.timedelta(days=365)).isoformat()
    for q in (Q1, Q2):
        u = 'https://news.google.com/rss/search?q=%s&hl=ko&gl=KR&ceid=KR:ko' % urllib.parse.quote('"%s" (%s) after:%s' % (name, q, after))
        try:
            x = fetch(u, 30, 2).decode('utf-8', 'ignore'); STAT['news'] += 1; NEWS_FAIL[0] = 0
        except Exception as e:
            NEWS_FAIL[0] += 1; log('news 실패 %s %r' % (name, str(e)[:60])); time.sleep(3); continue
        for it in re.findall(r'<item>(.*?)</item>', x, re.S):
            t = re.search(r'<title>(.*?)</title>', it, re.S); l = re.search(r'<link>(.*?)</link>', it, re.S)
            d = re.search(r'<pubDate>(.*?)</pubDate>', it, re.S); s = re.search(r'<source[^>]*>(.*?)</source>', it, re.S)
            if not t or not l: continue
            src = html.unescape(s.group(1)).strip() if s else ''
            title = html.unescape(re.sub(r'<!\[CDATA\[|\]\]>', '', t.group(1))).strip()
            if src and title.endswith(' - ' + src): title = title[:-len(src) - 3].strip()
            if not name_hit(name, title): continue
            bs = [b for b, pat in BUCKETS if re.search(pat, title)]
            if not bs: continue
            try: dt = datetime.datetime.strptime(d.group(1)[5:16], '%d %b %Y').date().isoformat()
            except Exception: dt = ''
            seen[title] = {'t': title[:110], 'u': html.unescape(l.group(1)).strip(), 's': src[:20], 'd': dt, 'b': bs}
        time.sleep(1.0)
    cut = (TODAY - datetime.timedelta(days=548)).isoformat()
    items = sorted((x for x in seen.values() if (x.get('d') or '9') >= cut), key=lambda x: x.get('d') or '', reverse=True)
    # 같은 날 같은 제목 앞 18자 중복 제거
    out = []; keys = set()
    for x in items:
        k = re.sub(r'\W', '', x['t'])[:14]
        if k in keys: continue
        keys.add(k); out.append(x)
    y1 = (TODAY - datetime.timedelta(days=365)).isoformat(); kc = {}
    for x in out:
        if (x.get('d') or '') >= y1:
            for b in x['b']: kc[b] = kc.get(b, 0) + 1
    return {'items': out[:36], 'kc': kc, 'n': len(out), 'at': TODAY.isoformat()}

# ───────── ⑥ 컨센서스·리포트
def naver_annual(code):
    try:
        j = json.loads(fetch('https://m.stock.naver.com/api/stock/%s/finance/annual' % code, 20, 2).decode('utf-8')); STAT['naver'] += 1
    except Exception: return None
    fi = j.get('financeInfo') or {}
    cols = [[t['key'][:4] + '.' + t['key'][4:6], t.get('isConsensus') == 'Y'] for t in fi.get('trTitleList') or []]
    rows = {}
    for r in fi.get('rowList') or []:
        rows[r['title']] = {k[:4] + '.' + k[4:6]: tonum(v.get('value')) for k, v in (r.get('columns') or {}).items()}
    return {'cols': cols, 'rows': rows} if cols else None
def load_reports():
    try: r = json.load(open('public/data/reports.json', encoding='utf-8'))
    except Exception: return {}
    m = {}
    for x in (r.get('company') or []) + [a for a in (r.get('archive') or []) if a.get('code')]:
        c = x.get('code')
        if not c: continue
        m.setdefault(c, {})[(x.get('d'), x.get('t'))] = {'d': x.get('d'), 'b': x.get('b'), 't': (x.get('t') or '')[:80], 'u': x.get('pdf') or x.get('link') or ''}
    return {c: sorted(v.values(), key=lambda z: z['d'] or '', reverse=True)[:8] for c, v in m.items()}

# ───────── 종목 1개
def one(code, name, corp, old, rpts):
    full = FULL or not old or old.get('v') != VER or bool(old.get('inc')) or (int(code) + TODAY.toordinal()) % 7 == 0
    o = {'v': VER, 'code': code, 'name': name, 'corp': corp, 'at': NOW.strftime('%Y-%m-%d %H:%M')}
    same = bool(old) and old.get('v') == VER   # 형식이 바뀌면 DART 구간은 새로 받는다(뉴스·컨센서스는 이어 씀)
    for k in ('con', 'biz', 'biz_src', 'gov', 'dec', 'maj', 'full_at'):
        if same and k in old: o[k] = old[k]
    for k in ('news', 'annual', 'rpt'):
        if old and k in old: o[k] = old[k]
    inc = []
    if corp and KEY:
        try:
            con, _ = contracts(corp, (old or {}).get('con'))
            o['con'] = con
            if con.pop('partial', False): inc.append('con')
        except DartFail: inc.append('con')
        latest = annual = None; newrep = False
        try:
            rows_a = api('list', corp_code=corp, bgn_de=(TODAY - datetime.timedelta(days=500)).strftime('%Y%m%d'), end_de=TODAY.strftime('%Y%m%d'), pblntf_ty='A', page_count=30)
            latest, annual = periodic(rows_a)
            newrep = bool(latest and (o.get('biz_src') or {}).get('rc') != latest[0])
            if latest and (newrep or 'biz' not in o):
                raws = ddoc(latest[0])
                if raws:
                    try: o['biz'] = parse_biz(max(raws.values(), key=len)); o['biz_src'] = {'rc': latest[0], 'nm': latest[1]}
                    except Exception as e: log('biz 파싱 실패 %s %r' % (code, str(e)[:80]))
        except DartFail: inc.append('biz')
        try:
            if latest is None and 'gov' not in o: raise DartFail('정기공시 목록 없음')
            rec = [] if full else api('list', corp_code=corp, bgn_de=(TODAY - datetime.timedelta(days=10)).strftime('%Y%m%d'), end_de=TODAY.strftime('%Y%m%d'), page_count=100)
            hot = any(re.search(r'자기주식|전환사채|신주인수권|교환사채|유상증자|대량보유|최대주주', r.get('report_nm') or '') for r in rec)
            if full or newrep or 'gov' not in o:
                g = governance(corp, latest, annual); d = decisions(corp); m = majors(corp, ((g.get('holders') or [{}])[0]).get('nm'))
                o['gov'] = g; o['dec'] = d; o['maj'] = m; o['full_at'] = TODAY.isoformat()
            elif hot:
                d = decisions(corp); m = majors(corp, ((o['gov'].get('holders') or [{}])[0]).get('nm'))
                o['dec'] = d; o['maj'] = m
        except DartFail: inc.append('gov')
    if inc: o['inc'] = inc; STAT['inc'] += 1
    a = naver_annual(code)
    if a: o['annual'] = a
    if rpts.get(code): o['rpt'] = rpts[code]
    return o
def finish(o):
    o['flags'] = flags(o.get('gov') or {}, o.get('dec') or [], o.get('maj') or [], o.get('con'), o.get('news'))
    return o
def idx_row(o):
    s = (o.get('con') or {}).get('sum') or {}; b = (o.get('biz') or {}).get('backlog') or {}
    fy1 = next((c[0] for c in (o.get('annual') or {}).get('cols') or [] if c[1]), None)
    return {'n': o.get('name'), 'cn': s.get('n', 0), 'm12': s.get('m12'), 'open': s.get('open'), 'bl': b.get('eok'),
            'fl': [[f['lv'], f['k']] for f in (o.get('flags') or []) if f['lv'] in ('bad', 'warn')][:8],
            'nw': (o.get('news') or {}).get('kc') or {}, 'fy1': fy1, 'at': o.get('at'), 'inc': o.get('inc') or []}

def main():
    sp = json.load(open('public/data/semipeer.json', encoding='utf-8'))
    names = {c: v.get('n') for c, v in (sp.get('co') or {}).items()}; corpmap = dict(sp.get('corpmap') or {})
    try:
        w = json.load(open('public/data/valws_watch.json', encoding='utf-8'))
        for c in w.get('codes') or []: names.setdefault(c, None)
    except Exception: pass
    try:
        hg = json.load(open('public/data/hege.json', encoding='utf-8'))
        hn = {r['c']: r['n'] for r in hg.get('rows') or []}
        for c in names:
            if not names[c]: names[c] = hn.get(c) or c
    except Exception: pass
    codes = [c for c in names if not ONLY or c in ONLY]
    if any(c not in corpmap for c in codes) and KEY:
        try:
            import xml.etree.ElementTree as ET
            z = zipfile.ZipFile(io.BytesIO(fetch(BASE + '/corpCode.xml?crtfc_key=' + KEY, 90)))
            for el in ET.fromstring(z.read(z.namelist()[0])).iter('list'):
                scd = (el.findtext('stock_code') or '').strip()
                if scd in names: corpmap.setdefault(scd, el.findtext('corp_code'))
        except Exception as e: log('corpCode 실패 %r' % e)
    os.makedirs(OUTDIR, exist_ok=True)
    olds = {}
    for c in codes:
        try: olds[c] = json.load(open('%s/%s.json' % (OUTDIR, c), encoding='utf-8'))
        except Exception: olds[c] = None
    rpts = load_reports()
    # 파일이 없거나 오래된 종목부터
    codes.sort(key=lambda c: (0 if (not olds[c] or olds[c].get('inc') or olds[c].get('v') != VER) else 1, (olds[c] or {}).get('at') or ''))
    log('대상 %d종목 · 키 %s · 기존 파일 %d' % (len(codes), '있음' if KEY else '없음', sum(1 for c in codes if olds[c])))
    done = {}
    def work(c):
        if left() < 120: return
        try:
            done[c] = one(c, names[c], corpmap.get(c), olds[c], rpts)
        except Exception as e:
            STAT['err'] += 1; log('종목 실패 %s %r' % (c, str(e)[:120]))
    def news_loop():
        for c in codes:
            if left() < 90: break
            try:
                r = news(names[c], (olds[c] or {}).get('news'))
                if r is not None: NEWS[c] = r
            except Exception as e: log('news 예외 %s %r' % (c, str(e)[:80]))
    NEWS = {}
    th = threading.Thread(target=news_loop, daemon=True); th.start()
    with ThreadPoolExecutor(max_workers=WORKERS) as ex: list(ex.map(work, codes))
    th.join(timeout=max(5, left() - 30))
    idx = {}
    try: idx = (json.load(open(IDX, encoding='utf-8')).get('map')) or {}
    except Exception: pass
    for c in codes:
        o = done.get(c) or olds.get(c)
        if not o: continue
        if c in NEWS: o['news'] = NEWS[c]
        finish(o)
        json.dump(o, open('%s/%s.json' % (OUTDIR, c), 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'))
        idx[c] = idx_row(o)
    json.dump({'updated': NOW.strftime('%Y-%m-%d %H:%M'), 'n': len(idx), 'stat': STAT, 'debug': DEBUG[-60:], 'map': idx}, open(IDX, 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'))
    log('완료 %d/%d종목(미완 %d) · DART %d콜·원문 %d·실패 %d · 뉴스 %d · %.0f초' % (len(done), len(codes), STAT['inc'], STAT['dart'], STAT['doc'], STAT['err'], STAT['news'], time.time() - T0))

if __name__ == '__main__':
    main()
