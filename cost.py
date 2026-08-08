#!/usr/bin/env python3
# 기업 비용구조 수집 (5개년 연간) — 변동비형/고정비형 판별용
# DART 전체 재무제표(fnlttSinglAcntAll)에서 매출액·매출원가·판관비·영업이익·순이익·감가상각 추출
# 대상: 밴드와 동일(시총 300+주요종목), 주 1회 순환. 결과: public/data/cost/{code}.json
import os, io, sys, json, time, zipfile, urllib.request, re, datetime
import xml.etree.ElementTree as ET

DART_KEY = os.environ.get('DART_KEY', '')
BASE = 'https://opendart.fss.or.kr/api'
OUTDIR = 'public/data/cost'
LIMIT = int(os.environ.get('LIMIT', '0'))
MAXRUN = int(os.environ.get('MAXRUN', '80'))
DEBUG = []
TODAY = datetime.date.today()
YEARS = list(range(TODAY.year - 6, TODAY.year))  # 최근 5~6개 사업연도

def fetch(url, timeout=40):
    for _ in range(3):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'}), timeout=timeout) as r:
                return r.read()
        except Exception:
            time.sleep(1)
    return b''

def jget(url):
    try:
        return json.loads(fetch(url).decode('utf-8'))
    except Exception:
        return {}

def tonum(s):
    try:
        return float(str(s).replace(',', '').strip())
    except Exception:
        return None

def corp_map():
    b = fetch('%s/corpCode.xml?crtfc_key=%s' % (BASE, DART_KEY), 90)
    z = zipfile.ZipFile(io.BytesIO(b))
    root = ET.fromstring(z.read(z.namelist()[0]))
    m = {}
    for it in root.iter('list'):
        sc = (it.findtext('stock_code') or '').strip()
        if len(sc) == 6:
            m[sc] = it.findtext('corp_code').strip()
    return m

def pick(items, sj, pats, avoid=None):
    """계정과목 매칭: sj_div 목록 + 이름 정규식 목록(우선순위순)"""
    for pat in pats:
        for it in items:
            if it.get('sj_div') not in sj:
                continue
            nm = re.sub(r'\s', '', it.get('account_nm') or '')
            if avoid and re.search(avoid, nm):
                continue
            if re.fullmatch(pat, nm):
                v = tonum(it.get('thstrm_amount'))
                if v is not None:
                    return v
    return None

def year_fin(corp, y):
    for fs in ('CFS', 'OFS'):
        d = jget('%s/fnlttSinglAcntAll.json?crtfc_key=%s&corp_code=%s&bsns_year=%d&reprt_code=11011&fs_div=%s'
                 % (BASE, DART_KEY, corp, y, fs))
        items = d.get('list') or []
        if not items:
            continue
        IS = ('IS', 'CIS')
        rev = pick(items, IS, [r'매출액', r'매출', r'영업수익', r'수익\(매출액\)', r'수익'])
        cogs = pick(items, IS, [r'매출원가', r'영업비용'] if rev else [r'매출원가'])
        sga = pick(items, IS, [r'판매비와관리비', r'판매비및관리비', r'판매관리비'])
        op = pick(items, IS, [r'영업이익\(손실\)', r'영업이익', r'영업손실'])
        ni = pick(items, IS, [r'당기순이익\(손실\)', r'당기순이익', r'당기순손실', r'연결당기순이익'])
        dep = None
        cf = [it for it in items if it.get('sj_div') == 'CF']
        s = 0.0
        found = False
        for it in cf:
            nm = re.sub(r'\s', '', it.get('account_nm') or '')
            if re.search(r'감가상각비|상각비', nm) and '환입' not in nm:
                v = tonum(it.get('thstrm_amount'))
                if v:
                    s += abs(v)
                    found = True
        if found:
            dep = s
        if rev:
            return {'y': y, 'rev': rev, 'cogs': cogs, 'sga': sga, 'op': op, 'ni': ni, 'dep': dep, 'fs': fs}
    return None

def classify(rows):
    """변동비형/고정비형 판별 + 근거"""
    rs = [r for r in rows if r.get('rev')]
    if len(rs) < 3:
        return {'type': '판별불가', 'why': '데이터 부족'}
    cogs_r = [r['cogs'] / r['rev'] for r in rs if r.get('cogs') and r['rev']]
    fixed_r = [((r.get('sga') or 0) + (r.get('dep') or 0)) / r['rev'] for r in rs if r['rev']]
    avg_cogs = sum(cogs_r) / len(cogs_r) if cogs_r else 0
    avg_fixed = sum(fixed_r) / len(fixed_r) if fixed_r else 0
    # 영업레버리지: 매출 변화율 대비 영업이익 변화율
    lev = []
    for a, b in zip(rs, rs[1:]):
        if a.get('op') and b.get('op') and a['rev'] and a['op'] != 0:
            dr = (b['rev'] - a['rev']) / abs(a['rev'])
            do = (b['op'] - a['op']) / abs(a['op'])
            if abs(dr) > 0.02:
                lev.append(do / dr)
    avg_lev = (sum(lev) / len(lev)) if lev else None
    score = 0  # +변동비형 / -고정비형
    if avg_cogs > 0.65: score += 2
    elif avg_cogs > 0.5: score += 1
    elif avg_cogs and avg_cogs < 0.35: score -= 1
    if avg_fixed > 0.35: score -= 2
    elif avg_fixed > 0.25: score -= 1
    if avg_lev is not None:
        if avg_lev > 2.5: score -= 1
        elif 0 < avg_lev < 1.5: score += 1
    t = '변동비형' if score >= 2 else ('고정비형' if score <= -2 else '혼합형')
    why = '매출원가율 평균 %.0f%%, 고정성 비용(판관비+상각) 비중 %.0f%%' % (avg_cogs * 100, avg_fixed * 100)
    if avg_lev is not None:
        why += ', 영업레버리지 %.1f배(매출 1%% 변동 시 영업이익 %.1f%% 변동)' % (avg_lev, avg_lev)
    return {'type': t, 'why': why, 'cogsR': round(avg_cogs, 3), 'fixedR': round(avg_fixed, 3),
            'lev': round(avg_lev, 2) if avg_lev is not None else None}

def main():
    if not DART_KEY:
        print('DART_KEY 필요'); sys.exit(1)
    targets = {}
    try:
        kt = json.load(open('public/ktop10.json', encoding='utf-8'))
        for items in kt['stocks'].values():
            for x in items:
                targets[x[0]] = x[1]
    except Exception:
        pass
    try:
        for x in json.load(open('compare_extra.json', encoding='utf-8')):
            targets[x['code']] = x.get('name', x['code'])
    except Exception:
        pass
    try:
        sv = json.load(open('public/data/stockvals.json', encoding='utf-8'))['map']
        pj = json.load(open('public/data/products.json', encoding='utf-8'))['map']
        for c, _ in sorted(((c, v) for c, v in sv.items() if v and v[2]), key=lambda x: -x[1][2])[:300]:
            if c not in targets:
                e = pj.get(c)
                targets[c] = (e.get('n') if isinstance(e, dict) else None) or c
    except Exception as e:
        print('top300 실패:', e, file=sys.stderr)
    if LIMIT:
        targets = dict(list(targets.items())[:LIMIT])
    cutoff = (TODAY - datetime.timedelta(days=7)).isoformat()
    try:
        cmap = corp_map()
    except Exception as e:
        DEBUG.append('corp_map 실패: %r' % e)
        cmap = {}
    os.makedirs(OUTDIR, exist_ok=True)
    index, ok, ran = {}, 0, 0
    for code, name in targets.items():
        try:
            old = json.load(open('%s/%s.json' % (OUTDIR, code), encoding='utf-8'))
            if (old.get('gen') or '') >= cutoff:
                index[code] = name
                ok += 1
                continue
        except Exception:
            pass
        if ran >= MAXRUN:
            if os.path.exists('%s/%s.json' % (OUTDIR, code)):
                index[code] = name
                ok += 1
            continue
        corp = cmap.get(code)
        if not corp:
            continue
        ran += 1
        rows = []
        for y in YEARS:
            r = year_fin(corp, y)
            if r:
                rows.append(r)
            time.sleep(0.08)
        rows = rows[-5:]
        if len(rows) >= 3:
            out = {'code': code, 'name': name, 'rows': rows, 'cls': classify(rows),
                   'gen': TODAY.isoformat()}
            with open('%s/%s.json' % (OUTDIR, code), 'w', encoding='utf-8') as f:
                json.dump(out, f, ensure_ascii=False)
            index[code] = name
            ok += 1
        elif len(DEBUG) < 10:
            DEBUG.append('%s %s: 연간 %d개' % (code, name, len(rows)))
        print('%s %s %d년' % (code, name, len(rows)), file=sys.stderr)
    DEBUG.append('계산 %d종목 (한도 %d)' % (ran, MAXRUN))
    with open('%s/index.json' % OUTDIR, 'w', encoding='utf-8') as f:
        json.dump({'updated': time.strftime('%Y-%m-%d %H:%M'), 'count': ok, 'codes': index, 'debug': DEBUG}, f, ensure_ascii=False)
    print('완료:', ok, DEBUG[:5])

if __name__ == '__main__':
    main()
