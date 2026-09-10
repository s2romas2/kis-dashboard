#!/usr/bin/env python3
# 소부장 세부분야 상세 데이터 빌드 → public/data/semidetail.json
# 입력: tools/semidetail/raw_co_*.json (기업별) + raw_rank_*.json (세부분야 순위)
# 출처 등급: 원문(증권사 PDF·한국IR협의회) / 전문매체(디일렉·전자신문·트렌드포스·SEMI·가트너·테크인사이츠·KSIA·KIPOST) / 공시(DART·KIND) / 기타(제외)
import json, glob, os, re, datetime, sys
from urllib.parse import urlparse

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
RAW = os.path.join(ROOT, 'tools', 'semidetail')
OUT = os.path.join(ROOT, 'public', 'data', 'semidetail.json')

ORIG = ['consensus.hankyung.com', 'stock.pstatic.net', 'files-scs.pstatic.net', 'ssl.pstatic.net',
        'alphasquare.co.kr', 'kiwoom.com', 'sks.co.kr', 'miraeasset.com', 'daishin.com', 'daishin.co.kr',
        'myasset.com', 'kbthink.com', 'samsungpop.com', 'shinyoung.com', 'koreainvestment.com',
        'leading.co.kr', 'hanaw.com', 'ibks.com', 'ds-sec.co.kr', 'kirs.or.kr', 'ls-sec.co.kr',
        'eugenefn.com', 'hmsec.com', 'bondweb.co.kr']
MEDIA = {'thelec.kr': '디일렉', 'etnews.com': '전자신문', 'trendforce.com': 'TrendForce', 'semi.org': 'SEMI',
         'gartner.com': 'Gartner', 'techinsights.com': 'TechInsights', 'ksia.or.kr': 'KSIA', 'kipost.net': 'KIPOST'}
DISC = ['dart.fss.or.kr', 'kind.krx.co.kr']

def host(u):
    try:
        return urlparse(u).netloc.lower()
    except Exception:
        return ''

def classify(u):
    h = host(u)
    if not h:
        return '기타'
    if any(h.endswith(d) for d in DISC):
        return '공시'
    if any(h.endswith(d) for d in ORIG):
        if 'consensus.hankyung.com' in h and 'downpdf' not in u:
            return '기타'   # 컨센서스 목록 페이지는 원문 아님
        if 'markets.hankyung.com' in h:
            return '기타'
        return '원문'
    if any(h.endswith(d) for d in MEDIA):
        return '전문매체'
    return '기타'

def clean_refs(refs):
    out, dropped, seen = [], 0, set()
    for r in refs or []:
        u = r.get('u', '')
        k = classify(u)
        if k == '기타':
            dropped += 1
            continue
        key = (u, r.get('q', ''))
        if key in seen:
            continue
        seen.add(key)
        rr = {kk: v for kk, v in r.items() if v not in (None, '')}
        rr['k'] = k
        out.append(rr)
    return out, dropped

# 표시 규칙(사용자): 목표주가·투자의견 제거 / 비상장·원문미확보 순위 제외
TP_PATTERNS = [r'\(?\s*(?:BUY|Buy|매수|HOLD|Hold|중립|Not Rated|NR)\s*(?:신규|유지|개시|하향|상향)?\s*[,·]?\s*(?:(?:TP|목표주가|적정주가)\s*[\d,]+\s*원?|[\d,]+\s*원)\s*(?:상향|하향|신규|개시|유지)?\s*\)?',
               r'(?:TP|목표주가|적정주가|목표가)\s*(?:은|는|를)?\s*[\d,]+\s*원[^.,;)/\n]*', r'\s*[—–-]\s*(?:TP|목표주가)[^.,;)\n]*']
def scrub(s):
    if not isinstance(s, str):
        return s
    for p in TP_PATTERNS:
        s = re.sub(p, '', s)
    s = re.sub(r'\(\s*[,·/\s]*\)', '', s)
    return re.sub(r'\s{2,}', ' ', s).strip(' ,·/')
def scrub_obj(o):
    if isinstance(o, dict):
        return {k: scrub_obj(v) for k, v in o.items()}
    if isinstance(o, list):
        return [scrub_obj(x) for x in o]
    return scrub(o)
def is_tp_kpi(k):
    return bool(re.search(r'목표주가|투자의견|목표가|TP\b|커버리지 상태|커버리지$', k or ''))
def valid_rank(r):
    c = str(r.get('c', '') or '')
    n = r.get('n', '') or ''
    if not re.fullmatch(r'\d{6}', c):
        return False
    if re.search(r'원문 미확보|부재|해당 없음|비상장', n) or (r.get('why', '') or '').startswith('원문 미확보'):
        return False
    return True

def grade(refs):
    o = sum(1 for r in refs if r['k'] == '원문')
    m = sum(1 for r in refs if r['k'] in ('전문매체', '공시'))
    if o >= 2: return 'A'
    if o == 1 or m >= 1: return 'B'
    return 'C'

co, groups, socamm = {}, {}, None
stats = {'dropped': 0}
for f in sorted(glob.glob(os.path.join(RAW, 'raw_co_*.json'))):
    d = json.load(open(f, encoding='utf-8'))
    for k, v in d.items():
        if k == '_group':
            refs, dr = clean_refs(v.get('refs'))
            stats['dropped'] += dr
            groups[v.get('name', os.path.basename(f))] = {'summary': v.get('summary', ''), 'refs': refs}
            continue
        if k == '_socamm':
            refs, dr = clean_refs(v.get('refs'))
            stats['dropped'] += dr
            socamm = {'summary': v.get('summary', ''), 'refs': refs}
            continue
        refs, dr = clean_refs(v.get('refs'))
        stats['dropped'] += dr
        co[k] = {'n': v.get('n'), 'sub': v.get('sub', []), 'spec': v.get('spec', ''), 'diff': v.get('diff', ''),
                 'kpi': v.get('kpi', []), 'refs': refs, 'note': v.get('note', ''), 'grade': grade(refs)}

# 2차 원자료 (fields + co 통합 파일) — raw2_*.json
for f in sorted(glob.glob(os.path.join(RAW, 'raw2_*.json'))):
    try:
        d = json.load(open(f, encoding='utf-8'))
    except Exception as e:
        print('skip', f, e); continue
    for k, v in (d.get('co') or {}).items():
        refs, dr = clean_refs(v.get('refs'))
        stats['dropped'] += dr
        if k in co and co[k].get('refs'):
            continue
        co[k] = {'n': v.get('n'), 'sub': v.get('sub', []), 'spec': v.get('spec', ''), 'diff': v.get('diff', ''),
                 'kpi': v.get('kpi', []), 'refs': refs, 'note': v.get('note', ''), 'grade': grade(refs)}
    d['_is_raw2'] = True

fields, deep, unverified = [], {'optics': [], 'glass': []}, []
FIELD_META = {  # 세부분야 id, 상위 그룹, 공정코드
    'SiC': ('sic', '파츠', ['e']), 'Si 파츠': ('sipart', '파츠', ['e']), '쿼츠': ('quartz', '파츠', ['e', 'd', 'o']),
    '세라믹 히터': ('heater', '파츠', ['d']), '세정': ('clean', '파츠', ['e', 'd']),
    'HPA': ('hpa', '열처리', ['o']), '레이저 어닐링': ('laser', '열처리', ['o']),
    '웨이퍼 테스터': ('wtester', '테스트장비', ['t']), '번인': ('burnin', '테스트장비', ['t']),
    '핸들러': ('handler', '테스트장비', ['t']), 'SSD': ('ssd', '테스트장비', ['t']),
    '테스트하우스': ('house', '테스트하우스', ['t']), 'OSAT': ('osat', '테스트하우스', ['k', 't']),
    '쏘캠(SOCAMM) 모듈': ('socamm', '쏘캠', ['k']), '쏘캠·LPDDR 테스트': ('socsocket', '쏘캠', ['t']),
    '포고핀': ('pogo', '테스트부품', ['t']), '러버': ('rubber', '테스트부품', ['t']),
    'STF': ('stf', '테스트부품', ['t']), '프로브카드': ('probe', '테스트부품', ['t']),
    'TC본더': ('tcb', '패키징장비', ['k']), '리플로우': ('reflow', '패키징장비', ['k']),
    '외관/범프': ('inspect', '패키징장비', ['k', 't']), 'X-ray': ('xray', '패키징장비', ['k', 't']),
    '유리기판': ('glass', '유리기판', ['k']), 'HBM 솔더볼': ('solder', '후공정소재', ['k']),
    '노광·트랙': ('litho', '계측·포토', ['f']),
    # 2차
    'ALD': ('ald', '전공정장비', ['d']), '식각·세정 장비': ('etch', '전공정장비', ['e']), '식각·세정': ('etch', '전공정장비', ['e']),
    'RTP': ('rtp', '전공정장비', ['o']), '중고장비': ('used', '전공정장비', ['i']), '기화기': ('vapor', '전공정장비', ['d']),
    '결함': ('metro', '계측·포토', ['f', 'e']), '계측': ('metro', '계측·포토', ['f', 'e']),
    '포토레지스트': ('pr', '계측·포토', ['f']), '포토 소재': ('pr', '계측·포토', ['f']),
    '블랭크마스크': ('mask', '계측·포토', ['f']), '노광': ('litho', '계측·포토', ['f']), '트랙': ('litho', '계측·포토', ['f']),
    '웨이퍼 가공': ('wafer', '계측·포토', ['w']), '엣지': ('wafer', '계측·포토', ['w']),
    '식각액': ('chem', '소재', ['e']), '특수가스': ('gas', '소재', ['d']), '전구체': ('precursor', '소재', ['d']),
    'CMP': ('cmp', '소재', ['m']), '후공정 소재': ('pkgmat', '소재', ['k']), 'EMC': ('pkgmat', '소재', ['k']),
    '스크러버': ('scrubber', '인프라', ['i']), '진공펌프': ('pump', '인프라', ['i']), '이송': ('efem', '인프라', ['i']),
    'CCSS': ('ccss', '인프라', ['i']), '피팅': ('fitting', '인프라', ['i']),
    'FC-BGA': ('fcbga', '기판', ['k']), '비메모리 OSAT': ('osat2', '기판', ['k']), 'FOPLP': ('osat2', '기판', ['k'])}

def meta_for(name):
    for key, m in sorted(FIELD_META.items(), key=lambda kv: -len(kv[0])):
        if key in name:
            return m
    return (re.sub(r'\W+', '', name)[:10].lower(), '기타', [])

RANK_FILES = sorted(glob.glob(os.path.join(RAW, 'raw_rank_*.json'))) + sorted(glob.glob(os.path.join(RAW, 'raw2_*.json')))
for f in RANK_FILES:
    try:
        d = json.load(open(f, encoding='utf-8'))
    except Exception as e:
        print('skip', f, e); continue
    for fd in d.get('fields', []):
        name = re.sub(r'^[A-Z]\.\s*', '', fd['field'])
        fid, grp, procs = meta_for(name)
        rank = []
        for r in fd.get('rank', []):
            if not valid_rank(r):
                continue
            refs, dr = clean_refs(r.get('refs'))
            stats['dropped'] += dr
            rank.append({'r': r['r'], 'c': r.get('c', ''), 'n': r.get('n', ''), 'why': r.get('why', ''),
                         'gap': r.get('gap', ''), 'refs': refs})
        ind = []
        for x in fd.get('industry', []):
            refs, dr = clean_refs(x.get('refs'))
            stats['dropped'] += dr
            ind.append({'k': x['k'], 'v': x['v'], 'refs': refs})
        members = [r['c'] for r in rank if r.get('c') and r['c'].isdigit()]
        fields.append({'id': fid, 'name': name, 'grp': grp, 'procs': procs, 'rank': rank,
                       'dissent': fd.get('dissent', ''), 'industry': ind, 'members': members})
    for k in ('optics', 'glass'):
        for x in (d.get('deep_reports') or {}).get(k, []):
            if classify(x.get('u', '')) == '원문' or host(x.get('u', '')).endswith('miraeasset.com'):
                deep[k].append(x)
    unverified += d.get('unverified', [])

# 세부분야 멤버십 → 기업 sub 태그 보강 (필터용)
for fd in fields:
    for c in fd['members']:
        if c in co:
            co[c].setdefault('fields', []).append(fd['id'])
        else:
            co[c] = {'n': next((r['n'] for r in fd['rank'] if r['c'] == c), c), 'sub': [], 'spec': '', 'diff': '',
                     'kpi': [], 'refs': [], 'note': '', 'grade': 'C', 'fields': [fd['id']]}
for c, v in co.items():
    v.setdefault('fields', [])
    v['fields'] = sorted(set(v['fields']))
# 기업 단독 조사 없이 순위에만 등장한 기업 → 순위 근거·출처를 상세로 승계
for fd in fields:
    for r in fd['rank']:
        c = r.get('c')
        if not (c and c in co):
            continue
        v = co[c]
        if not v['refs'] and r['refs']:
            v['refs'] = list(r['refs'])
        else:
            seen = {(x['u'], x.get('q', '')) for x in v['refs']}
            v['refs'] += [x for x in r['refs'] if (x['u'], x.get('q', '')) not in seen]
        if not v['diff'] and r.get('why'):
            v['diff'] = r['why'] + ((' ↔ ' + r['gap']) if r.get('gap') and r['gap'] != '원문 미확보' else '')
        if not v['sub']:
            v['sub'] = [fd['name'].replace('(', ' (').split(' (')[0]]
        v['grade'] = grade(v['refs'])

blog_notes = None
bn = os.path.join(RAW, 'blogger_notes.md')
if os.path.exists(bn):
    blog_notes = open(bn, encoding='utf-8').read()

# 순위 재번호(빈 자리 없이) + 목표주가·투자의견 제거
for fd in fields:
    for i, r in enumerate(fd['rank']):
        r['r'] = i + 1
    fd['members'] = [r['c'] for r in fd['rank']]
for c, v in co.items():
    v['kpi'] = [k for k in v.get('kpi', []) if not is_tp_kpi(k.get('k', ''))]
fields = scrub_obj(fields)
co = scrub_obj(co)
groups = scrub_obj(groups)
if socamm: socamm = scrub_obj(socamm)

out = {'updated': datetime.date.today().isoformat(), 'stats': {'companies': len(co), 'fields': len(fields),
       'dropped_refs': stats['dropped']}, 'legend': {'원문': '증권사·한국IR협의회 리포트 원문 PDF',
       '전문매체': '디일렉·전자신문·TrendForce·SEMI·Gartner·TechInsights·KSIA·KIPOST', '공시': 'DART·KIND'},
       'fields': fields, 'co': co, 'groups': groups, 'socamm': socamm, 'deep_reports': deep,
       'unverified': unverified, 'blog_notes': blog_notes}
os.makedirs(os.path.dirname(OUT), exist_ok=True)
json.dump(out, open(OUT, 'w', encoding='utf-8'), ensure_ascii=False)
print('semidetail.json:', out['stats'], '| fields:', [f['id'] for f in fields])
