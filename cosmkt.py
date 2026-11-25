#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
마케팅비(광고선전비·판매촉진비) 시계열 수집 — 화장품 peer 용

왜 따로 만드나
    cost.py 는 판관비 '총액'만, 그것도 연간만 모은다.
    브랜드 기업은 광고선전비가 판관비의 20~40%를 차지하고, 그 증감이 곧 전략 변화다.
    총액만 보면 "판관비가 늘었다"까지만 알고 왜 늘었는지를 모른다.

어디에 있나 — 이것이 이 수집기의 핵심 질문
    광고선전비는 손익계산서 본문에 없다. 판매비와관리비 '주석' 표에 있다.
    그래서 XBRL 재무제표 API(fnlttSinglAcntAll)로는 못 가져온다.
    정기보고서 원문(document.xml) 을 받아 그 표를 직접 찾아야 한다.
    분기보고서 주석은 요약본이라 이 표가 빠지는 곳이 있다 — PROBE 로 먼저 확인한다.

PROBE 모드
    PROBE=1 CODES=090430,278470 python cosmkt.py
    → 파싱하지 않고 '무엇이 보이는지'만 public/data/cosmkt_probe.json 에 적는다.
      표가 어떤 모양인지 눈으로 본 뒤 파서를 확정하려는 것이다.
"""
import os, io, sys, json, time, zipfile, urllib.request, re, datetime

KEY    = os.environ.get('DART_KEY', '')
BASE   = 'https://opendart.fss.or.kr/api'
OUT    = os.environ.get('OUT', 'public/data/cosmkt.json')
PROBE  = os.environ.get('PROBE', '') not in ('', '0')
POUT   = os.environ.get('POUT', 'public/data/cosmkt_probe.json')
DEF    = os.environ.get('DEF', 'public/data/cospeer_def.json')
MAXRUN = int(os.environ.get('MAXRUN', '12'))
KST    = datetime.timezone(datetime.timedelta(hours=9))
NOW    = datetime.datetime.now(KST)
TODAY  = NOW.date()
DEBUG  = []

def log(s):
    DEBUG.append(s); print(s, flush=True)

def fetch(url, timeout=90):
    last = ''
    for i in range(3):
        try:
            rq = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(rq, timeout=timeout) as r:
                return r.read()
        except Exception as e:
            last = repr(e); time.sleep(1.5 * (i + 1))
    log('fetch 실패 %s … %s' % (url.split('?')[0], last[:70]))
    return b''

def jget(url):
    try:
        return json.loads(fetch(url, 40).decode('utf-8'))
    except Exception:
        return {}

def corp_map():
    """종목코드 → DART 고유번호"""
    import xml.etree.ElementTree as ET
    b = fetch('%s/corpCode.xml?crtfc_key=%s' % (BASE, KEY), 120)
    z = zipfile.ZipFile(io.BytesIO(b))
    root = ET.fromstring(z.read(z.namelist()[0]))
    m = {}
    for it in root.iter('list'):
        sc = (it.findtext('stock_code') or '').strip()
        if len(sc) == 6:
            m[sc] = (it.findtext('corp_code') or '').strip()
    return m

# ── 정기보고서 목록 ───────────────────────────────────────────
RPT = {'A001': '사업', 'A002': '반기', 'A003': '분기'}

def reports(corp, years=6):
    """최근 N년치 정기보고서 — (접수번호, 종류, 보고서명, 접수일)"""
    bgn = (TODAY - datetime.timedelta(days=int(years * 365.25))).strftime('%Y%m%d')
    out = []
    for ty in ('A001', 'A002', 'A003'):
        for pg in (1, 2):
            d = jget('%s/list.json?crtfc_key=%s&corp_code=%s&pblntf_detail_ty=%s'
                     '&bgn_de=%s&end_de=%s&page_count=100&page_no=%d&last_reprt_at=Y'
                     % (BASE, KEY, corp, ty, bgn, TODAY.strftime('%Y%m%d'), pg))
            ls = d.get('list') or []
            for it in ls:
                nm = it.get('report_nm') or ''
                if '보고서' not in nm:
                    continue
                out.append({'rcp': it.get('rcept_no'), 'ty': ty, 'nm': nm,
                            'dt': it.get('rcept_dt')})
            if len(ls) < 100:
                break
    # 접수일 내림차순
    out.sort(key=lambda x: x['dt'] or '', reverse=True)
    return out

def doc_text(rcp):
    b = fetch('%s/document.xml?crtfc_key=%s&rcept_no=%s' % (BASE, KEY, rcp), 180)
    if not b:
        return ''
    try:
        z = zipfile.ZipFile(io.BytesIO(b))
    except Exception:
        return ''
    txts = []
    for n in z.namelist():
        try:
            raw = z.read(n)
        except Exception:
            continue
        for enc in ('utf-8', 'cp949', 'euc-kr'):
            try:
                txts.append(raw.decode(enc)); break
            except Exception:
                continue
    return '\n'.join(txts)

# ── 표 파싱 ───────────────────────────────────────────────────
def cells_of(tr):
    out = []
    for c in re.findall(r'<T[DEH][^>]*>([\s\S]*?)</T[DEH]>', tr, re.I):
        t = re.sub(r'<[^>]+>', ' ', c)
        t = t.replace('&nbsp;', ' ').replace('&amp;', '&')
        out.append(re.sub(r'\s+', ' ', t).strip())
    return out

def tables_near(txt, words, window=60000, limit=6):
    """앵커 단어 뒤 window 안의 <TABLE> 들을 행 단위로 돌려준다"""
    seen, out = set(), []
    for w in words:
        for m in re.finditer(re.escape(w), txt):
            seg = txt[m.start(): m.start() + window]
            for tm in re.finditer(r'<TABLE[^>]*>([\s\S]*?)</TABLE>', seg, re.I):
                key = (m.start() + tm.start())
                if key in seen:
                    continue
                seen.add(key)
                rows = [cells_of(tr) for tr in
                        re.findall(r'<TR[^>]*>([\s\S]*?)</TR>', tm.group(1), re.I)]
                rows = [r for r in rows if any(x for x in r)]
                if rows:
                    out.append({'at': key, 'rows': rows})
                if len(out) >= limit:
                    return out
    return out

AD = re.compile(r'광고(선전|비)|선전비|광고및선전|판매촉진|판촉비|마케팅')

# ── 판관비 명세표 찾기 ───────────────────────────────────────
# 처음엔 '판매비와관리비' 를 앵커로 그 뒤 표를 훑었는데, 그 단어가 한 보고서에 20~50번 나온다.
# 요약재무정보·손익계산서에서 먼저 걸려 명세 주석에 닿기 전에 한도를 다 썼다 — 광고표 0개.
# 앵커를 버리고 **표 안에 광고 계정이 있는지로 직접** 고른다.
def sga_tables(txt, limit=6):
    out = []
    for tm in re.finditer(r'<TABLE[^>]*>([\s\S]*?)</TABLE>', txt, re.I):
        body = tm.group(1)
        if not AD.search(body):
            continue
        rows = [cells_of(tr) for tr in re.findall(r'<TR[^>]*>([\s\S]*?)</TR>', body, re.I)]
        rows = [r for r in rows if any(x for x in r)]
        if len(rows) < 4:
            continue
        lab = ' '.join((r[0] if r else '') for r in rows)
        if not AD.search(lab):          # 첫 열(계정명)에 있어야 명세표다
            continue
        # 판관비 명세다운가 — 인건비·수수료·합계가 같이 있으면 명세일 가능성이 높다.
        # 공시 표는 '합 계'처럼 글자 사이에 공백을 넣는다 — 지우고 비교해야 잡힌다.
        labx = re.sub(r'\s', '', lab)
        score = sum(1 for k in ('급여', '인건비', '합계', '수수료', '감가상각', '운반비', '임차료',
                                '복리후생', '세금과공과', '소모품')
                    if k in labx)
        out.append({'at': tm.start(), 'rows': rows, 'score': score, 'nrow': len(rows)})
    out.sort(key=lambda x: (-x['score'], -x['nrow']))
    return out[:limit]



# ── 판관비 명세 파서 ──────────────────────────────────────────
# 「광고선전비」 한 줄만 보면 틀린다 — 회사마다 계정명이 다르다.
#   에이피알  인건비/광고선전비/지급수수료/운반비/감가상각비/기타
#   달바      지급수수료 자리에 '판매수수료'
#   한국콜마·코스메카  '연구개발비'가 따로
# 그래서 명세 전체를 떠서 성격별로 묶고, 광고만/광고+판촉 둘 다 낸다.
BUCKET = [
    # 아모레퍼시픽은 '광고선전비 및 판매촉진비' 를 한 줄로 낸다.
    # 이걸 ad 로 담으면 광고만 따로 내는 회사와 나란히 못 둔다 — 합산 항목은 따로 표시한다.
    ('admix', r'광고선전비?및판매촉진비?|광고선전및판촉|광고및판매촉진'),
    ('ad',   r'광고선전비?|광고비|선전비|광고및선전비?'),
    ('prom', r'판매촉진비?|판촉비|판매부대비|샘플비|견본비'),
    ('comm', r'지급수수료|판매수수료|수수료'),
    ('pay',  r'급여|임금|인건비|상여|퇴직급여|복리후생비?'),
    ('ship', r'운반비|운송비|물류비|보관료'),
    ('rnd',  r'경상연구개발비?|연구개발비?'),
    ('dep',  r'감가상각비|무형자산상각비|사용권자산상각비'),
    ('rent', r'지급임차료|임차료'),
]
BUCKET = [(k, re.compile(p)) for k, p in BUCKET]
TOTAL  = re.compile(r'^(합\s*계|계|총\s*계|판매비와\s*관리비|판매비및관리비)$')

def bucket_of(nm):
    n = re.sub(r'\s', '', nm or '')
    if TOTAL.match(n):
        return 'total'
    for k, rx in BUCKET:
        if rx.search(n):
            return k
    return 'etc'

def tonum(s):
    """(1,234) → -1234 / '-' → None. 괄호는 음수 표기다."""
    t = re.sub(r'[\s,]', '', str(s or ''))
    if not t or t in ('-', '—', '–'):
        return None
    neg = t.startswith('(') and t.endswith(')')
    t = re.sub(r'[^\d.\-]', '', t)
    if not t or t == '-':
        return None
    try:
        v = float(t)
    except Exception:
        return None
    return -v if neg else v

# 표마다 천원·백만원이 섞여 있다. 놓치면 1,000배 틀린다 — 모르면 추정하지 않는다.
UNIT = [(r'단위\s*[:：]?\s*백만\s*원', 1e6), (r'\(백만\s*원\)', 1e6),
        (r'단위\s*[:：]?\s*천\s*원', 1e3), (r'\(천\s*원\)', 1e3),
        (r'단위\s*[:：]?\s*원', 1.0)]

def unit_near(txt, at, back=1200):
    seg = txt[max(0, at - back): at + 300]
    for p, m in UNIT:
        if re.search(p, seg):
            return m
    return None

def xbrl_sga(corp, year, reprt):
    """XBRL 재무제표의 판매비와관리비 (원 단위, 권위 있는 값).
       주석 표의 단위를 이걸로 검산한다 — 기재 텍스트만 믿으면 1,000배가 틀어진다."""
    for fs in ('CFS', 'OFS'):
        d = jget('%s/fnlttSinglAcntAll.json?crtfc_key=%s&corp_code=%s&bsns_year=%s'
                 '&reprt_code=%s&fs_div=%s' % (BASE, KEY, corp, year, reprt, fs))
        for it in (d.get('list') or []):
            if it.get('sj_div') not in ('IS', 'CIS'):
                continue
            nm = re.sub(r'\s', '', it.get('account_nm') or '')
            if re.fullmatch(r'판매비와관리비|판매비및관리비|판매관리비|판매비와일반관리비|판매비및일반관리비', nm):
                v = tonum(it.get('thstrm_amount'))
                if v:
                    return abs(v)
    return None

UNIT_STEPS = (1.0, 1e3, 1e6)

def settle_unit(parsed_total, xbrl, said):
    """주석 합계 × 단위 ≈ XBRL 판관비 가 되는 단위를 고른다.
       맞는 단위가 없으면 None — 추정해서 채우지 않는다."""
    if not parsed_total or not xbrl:
        return (said, '기재' if said else '미확인')
    best, bestd = None, None
    for u in UNIT_STEPS:
        r = (parsed_total * u) / xbrl
        d = abs(r - 1.0)
        if bestd is None or d < bestd:
            best, bestd = u, d
    if bestd is not None and bestd <= 0.08:        # 8% 이내면 같은 값으로 본다
        return (best, '검산' if best == said else '검산(기재와 다름)')
    return (None, '검산 실패 — 합계가 XBRL 판관비와 맞지 않는다')

def parse_sga(rows):
    """표 행들 → {계정: [숫자들]} + 성격별 합. 숫자 열이 여럿이면(당기/전기) 그대로 둔다."""
    out, lines = {}, []
    for r in rows:
        if not r:
            continue
        nm = r[0]
        if not nm or not re.search(r'[가-힣A-Za-z]', nm):
            continue
        nums = [tonum(x) for x in r[1:]]
        nums = [x for x in nums if x is not None]
        if not nums:
            continue
        b = bucket_of(nm)
        lines.append({'nm': nm[:28], 'b': b, 'v': nums[:4]})
        out.setdefault(b, []).append(nums[0])
    agg = {k: sum(v) for k, v in out.items()}
    # '판매비와관리비' 가 머리글과 본문에 두 번 잡히면 합이 두 배가 된다 — 최댓값을 쓴다
    if 'total' in out:
        agg['total'] = max(out['total'])
    ad, prom, mix = agg.get('ad'), agg.get('prom'), agg.get('admix')
    if mix is not None:
        # 합산 항목만 있는 회사 — 광고만 따로는 알 수 없다. mkt 에만 담고 ad 는 비운다.
        agg['mkt'] = mix + (ad or 0) + (prom or 0)
        agg['mkt_kind'] = '광고+판촉 합산'
    elif ad is not None or prom is not None:
        agg['mkt'] = (ad or 0) + (prom or 0)
        agg['mkt_kind'] = '광고' + ('+판촉' if prom is not None else '만')
    else:
        agg['mkt'] = None
    return {'lines': lines[:28], 'agg': agg, 'head': (rows[0] if rows else [])[:6]}


# ── 종속회사 소재지 ──────────────────────────────────────────
# 타법인 출자현황에는 소재국 열이 없어 이름으로만 미국 법인을 가려야 했다.
# 그래서 COSMAX WEST(미국)·HuM&C Vina(베트남)가 똑같이 '소재국 미확인'으로 묶였다.
# 사업보고서의 「연결대상 종속회사 현황」 표에는 소재지 열이 있다 — 같은 원문이니 여기서 같이 뽑는다.
LOCUS = re.compile(r'미국|U\.?S\.?A?\b|UNITED\s*STATES|아메리카', re.I)
LOCHD = re.compile(r'소재지|소재국|국가|본점|주소')
NAMHD = re.compile(r'상호|회사명|법인명|명칭|기업명')

def subs_loc(txt):
    """종속회사 표에서 (회사명, 소재지, 주요사업) 을 뽑는다. 헤더에서 열 위치를 찾아 쓴다 —
       열 순서를 가정하면 회사마다 달라 틀린다."""
    out, seen = [], set()
    for tb in tables_near(txt, ['연결대상 종속회사', '종속회사 현황', '종속기업 현황',
                                '연결대상종속회사', '종속회사에 관한 사항'], window=40000, limit=8):
        rows = tb['rows']
        if len(rows) < 2:
            continue
        # 헤더 행 찾기
        hi = ci = ni = None
        for k, r in enumerate(rows[:4]):
            c1 = [i for i, c in enumerate(r) if LOCHD.search(c or '')]
            c2 = [i for i, c in enumerate(r) if NAMHD.search(c or '')]
            if c1 and c2:
                hi, ci, ni = k, c1[0], c2[0]; break
        if hi is None:
            continue
        for r in rows[hi + 1:]:
            if len(r) <= max(ci, ni):
                continue
            nm = (r[ni] or '').strip()
            lc = (r[ci] or '').strip()
            if not nm or not lc or nm == lc:
                continue
            key = nm[:40]
            if key in seen:
                continue
            seen.add(key)
            out.append({'nm': nm[:48], 'loc': lc[:24], 'us': bool(LOCUS.search(lc))})
        if out:
            break
    return out

def probe_one(code, name, corp):
    rs = reports(corp)
    kinds = {}
    for r in rs:
        kinds.setdefault(r['ty'], []).append(r)
    rec = {'n': name, 'corp': corp, 'n_reports': len(rs),
           'by_type': {RPT[k]: len(v) for k, v in kinds.items()}, 'seen': []}
    # 사업보고서 1건 + 분기/반기보고서 1건씩만 열어 본다
    pick = []
    for ty in ('A001', 'A003', 'A002'):
        if kinds.get(ty):
            pick.append(kinds[ty][0])
    for r in pick:
        txt = doc_text(r['rcp'])
        e = {'ty': RPT[r['ty']], 'nm': r['nm'], 'dt': r['dt'], 'chars': len(txt)}
        if not txt:
            e['err'] = '원문 비어 있음'; rec['seen'].append(e); continue
        e['has_판관비_단어'] = len(re.findall(r'판매비와\s*관리비|판매비및관리비', txt))
        e['has_광고_단어']   = len(AD.findall(txt))
        tbs = sga_tables(txt)
        e['표_후보'] = len(tbs)
        # 이 보고서의 XBRL 판관비 — 주석 표 단위를 검산할 기준값
        RC = {'A001': '11011', 'A002': '11012', 'A003': None}
        yy = re.search(r'\((\d{4})\.(\d{2})\)', r['nm'])
        by = yy.group(1) if yy else str(TODAY.year - 1)
        mm = yy.group(2) if yy else '12'
        rc = RC.get(r['ty']) or ('11013' if mm in ('03', '04') else '11014')
        xb = xbrl_sga(corp, by, rc)
        e['xbrl_판관비'] = xb
        hit = []
        for tb in tbs:
            pr = parse_sga(tb['rows'])
            said = unit_near(txt, tb['at'])
            u, usrc = settle_unit((pr['agg'] or {}).get('total'), xb, said)
            hit.append({'행수': len(tb['rows']), '점수': tb['score'],
                        '단위_기재': said, '단위_확정': u, '단위_근거': usrc,
                        '앞10행': [' | '.join(x[:5])[:110] for x in tb['rows'][:10]],
                        '파싱': pr})
        e['광고행_포함표'] = hit[:2]
        if not hit:
            # 표를 못 찾았으면 '왜 못 찾았는지' 를 보려고 원문 조각을 그대로 담는다.
            m0 = re.search(r'광고선전비|광고비|선전비', txt)
            e['못찾음_원문조각'] = (txt[max(0, m0.start() - 700): m0.start() + 700]
                              if m0 else '광고 계정 단어가 원문에 없다')
        if r['ty'] == 'A001':          # 종속회사 표는 사업보고서에 있다
            sb = subs_loc(txt)
            e['종속회사'] = {'n': len(sb), '미국': [x for x in sb if x['us']][:6],
                          '앞8개': [('%s @ %s' % (x['nm'][:28], x['loc'])) for x in sb[:8]]}
        rec['seen'].append(e)
        time.sleep(0.4)
    return rec

def main():
    if not KEY:
        print('DART_KEY 필요', file=sys.stderr); return 1
    cmap = corp_map()
    log('corp_map %d건' % len(cmap))
    if PROBE:
        codes = [c.strip() for c in os.environ.get(
            'CODES', '090430,278470,237880,257720,214150').split(',') if c.strip()]
        dd = {}
        try:
            dd = (json.load(open(DEF, encoding='utf-8')).get('co') or {})
        except Exception:
            pass
        out = {'updated': NOW.strftime('%Y-%m-%d %H:%M KST'), 'probe': True, 'co': {}}
        for c in codes:
            corp = cmap.get(c)
            if not corp:
                out['co'][c] = {'err': 'DART 고유번호 없음'}; continue
            try:
                out['co'][c] = probe_one(c, (dd.get(c) or {}).get('n') or c, corp)
                log('%s %s OK' % (c, out['co'][c]['n']))
            except Exception as e:
                out['co'][c] = {'err': repr(e)[:160]}
                log('%s 실패 %r' % (c, e))
        out['debug'] = DEBUG[-40:]
        os.makedirs(os.path.dirname(POUT), exist_ok=True)
        json.dump(out, open(POUT, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
        print('프로브 → %s' % POUT)
        return 0
    print('본수집은 프로브 결과 확인 뒤에 붙인다', file=sys.stderr)
    return 0

if __name__ == '__main__':
    sys.exit(main())
