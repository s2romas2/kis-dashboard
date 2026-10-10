#!/usr/bin/env python3
# 반도체 peer 정의 병합 — tools/semipeer/raw/*.json(배치별 peer 쌍·5기준 점수·근거 인용) → public/data/semipeer_def.json
#   등급 규칙: A = 합계 8↑ & 제품 동일성 2 / B = 합계 6↑ & 제품 동일성 1↑ / C = 그 외(참고용, 저밸류 판정 제외)
#   bundle 인용(c,q)은 semidetail.json의 리포트 원문 인용(refs)과 대조해 출처(증권사·날짜·URL)를 붙인다.
#   실행: python tools/semipeer/merge_def.py   (작성 지침: tools/semipeer/SPEC.md)
import json, glob, re, os, sys, datetime
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
D = os.path.join(ROOT, 'public', 'data')
def L(f): return json.load(open(os.path.join(D, f), encoding='utf-8'))
sd = L('semidetail.json'); sm = L('semimap.json')
try: hg = {r['c']: r for r in L('hege.json')['rows']}
except Exception: hg = {}
smi = {i['c']: i for i in sm['items']}
norm = lambda s: re.sub(r'\s+', '', s or '')
KEYS = ['prod', 'cust', 'mix', 'model', 'driver']
ORDER = ['b8_memory_foundry', 'b9_fabless_ip', 'b2_frontend_equip', 'b1_parts_anneal', 'b6_metro_photo', 'b5_materials',
         'b3_test', 'b4_pkg_substrate', 'b7_infra', 'b10_offmap']

# 리포트 원문 인용 색인: 기업코드 → [(norm q, ref)]
REFS = {}
def addref(c, r):
    if r.get('q'): REFS.setdefault(c, []).append((norm(r['q']), r))
for c, v in sd['co'].items():
    for r in v.get('refs') or []: addref(c, r)
for f in sd['fields']:
    for rk in f['rank']:
        for r in rk.get('refs') or []: addref(rk['c'], r)
    for it in f.get('industry') or []:
        for r in it.get('refs') or []:
            for rk in f['rank']: addref(rk['c'], r)

def locate(c, q):
    """bundle 인용의 출처 라벨. 리포트 원문 인용과 겹치면 그 리포트, 아니면 대시보드 요약 필드."""
    nq = norm(q)
    for rq, r in REFS.get(c, []):
        if nq in rq or rq in nq:
            return {'t': r.get('t') or '', 'b': r.get('b') or '', 'd': r.get('d') or '', 'u': r.get('u') or '', 'k': r.get('k') or '원문'}
    co = sd['co'].get(c) or {}
    for kp in co.get('kpi') or []:
        if nq in norm(kp.get('k', '') + kp.get('v', '')) or nq in norm(kp.get('v', '')):
            return {'k': '요약', 'b': kp.get('s') or '', 't': '소부장 맵 기업 상세 — 핵심 지표(%s)' % kp.get('k', '')}
    for fld, lab in (('spec', '특화'), ('diff', '차별성'), ('note', '비고')):
        if nq in norm(co.get(fld) or ''): return {'k': '요약', 't': '소부장 맵 기업 상세 — %s(리포트 요약)' % lab}
    if nq in norm(' '.join(co.get('sub') or [])): return {'k': '요약', 't': '소부장 맵 기업 상세 — 세부 제품'}
    it = smi.get(c) or {}
    for fld in ('prod', 'use', 'edge'):
        if nq in norm(it.get(fld) or ''): return {'k': '요약', 't': '소부장 맵 — %s' % {'prod': '제품', 'use': '용도', 'edge': '강점'}[fld], 'b': it.get('src') or ''}
    for f in sd['fields']:
        for rk in f['rank']:
            if rk['c'] == c and (nq in norm(rk.get('why')) or nq in norm(rk.get('gap'))):
                return {'k': '요약', 't': '소부장 맵 세부분야 순위 근거 — %s' % f['name']}
        if nq in norm(f.get('dissent')): return {'k': '요약', 't': '소부장 맵 세부분야 반대 의견 — %s' % f['name']}
        for x in f.get('industry') or []:
            if nq in norm(x.get('k', '') + x.get('v', '')) or nq in norm(x.get('v', '')): return {'k': '요약', 't': '소부장 맵 산업 지표 — %s' % f['name']}
    return {'k': '요약', 't': '소부장 맵 자료'}

def fix_ev(ev):
    if 'u' in ev:
        u = ev['u']
        # 출처 분류: 공시 / 리포트 원문(증권사·IR협의회 PDF) / 전문매체 / 일반 뉴스(보조 근거)
        if 'dart.fss.or.kr' in u or 'kind.krx' in u: k = '공시'
        elif any(h in u for h in ('stock.pstatic.net', 'ssl.pstatic.net', 'alphasquare.co.kr', 'consensus.hankyung.com', 'kirs.or.kr', 'samsungpop.com', 'sks.co.kr', 'ls-sec.co.kr', 'kiwoom.com', 'miraeasset.com')): k = '원문'
        elif any(h in u for h in ('thelec.kr', 'etnews.com', 'zdnet.co.kr', 'kipost.net', 'ddaily.co.kr', 'trendforce.com')): k = '전문매체'
        else: k = '일반 뉴스'
        return {'q': ev['q'], 'u': u, 't': ev.get('t', ''), 'b': ev.get('b', ''), 'd': ev.get('d', ''), 'k': k}
    o = {'q': ev['q'], 'c': ev['c']}; o.update(locate(ev['c'], ev['q']))
    if o.get('k') == '요약':
        via = []
        for r in (sd['co'].get(ev['c']) or {}).get('refs') or []:
            if r.get('u') and r.get('b') and not any(v['u'] == r['u'] for v in via): via.append({'b': r['b'], 'd': r.get('d') or '', 'u': r['u']})
            if len(via) >= 2: break
        if via: o['via'] = via
    return o

def grade(sc):
    tot = sum(v for v in sc.values() if isinstance(v, int)); p = sc.get('prod') or 0
    if tot >= 8 and p == 2: return 'A', tot
    if tot >= 6 and p >= 1: return 'B', tot
    return 'C', tot

TOP = {'메모리': '메모리·파운드리', '파운드리': '메모리·파운드리',
       '전공정장비': '전공정 장비·계측', '열처리': '전공정 장비·계측', '계측·포토': '전공정 장비·계측',
       '파츠': '소재·부품', '소재': '소재·부품', '후공정소재': '소재·부품',
       '테스트장비': '후공정·테스트·기판', '테스트하우스': '후공정·테스트·기판', '테스트부품': '후공정·테스트·기판', '쏘캠': '후공정·테스트·기판',
       '패키징장비': '후공정·테스트·기판', '유리기판': '후공정·테스트·기판', '기판': '후공정·테스트·기판', '인프라': '인프라', '기타': '기타'}
PROC = {k: v for k, v in sm.get('procs') or []}
STAGE_NAME = {'pre': '전공정', 'post': '후공정', 'both': '전·후공정', 'infra': '공통 인프라',
              'chip': '칩 제조(IDM·파운드리)', 'design': '설계(팹리스·디자인하우스·IP)', 'dist': '모듈·유통', 'etc': '기타'}
STAGE_EXTRA = {
    # 칩 제조: 설계부터 전·후공정까지 직접 하는 종합반도체(IDM)와 웨이퍼 위탁생산(파운드리)
    '005930': 'chip', '000660': 'chip', '000990': 'chip', '092220': 'chip', '429270': 'chip',
    # 설계: 공장 없이 칩·IP를 설계(팹리스·디자인하우스·IP)
    '080220': 'design', '032580': 'design', '440110': 'design', '399720': 'design', '200710': 'design', '445090': 'design',
    '117670': 'design', '045970': 'design', '394280': 'design', '094360': 'design', '432720': 'design', '396270': 'design',
    '087600': 'design', '054450': 'design', '094170': 'design', '303030': 'design', '464500': 'design', '108320': 'design',
    '452430': 'design', '418420': 'design', '102120': 'design', '052860': 'design',
    # 모듈·유통: 완성된 칩을 모듈·SSD로 조립하거나 유통
    '226590': 'dist', '078350': 'dist', '093520': 'dist', '077500': 'dist', '142210': 'dist', '254490': 'dist',
    # 맵 밖 소부장
    '388210': 'pre', '482630': 'pre', '417500': 'pre',                      # 식각 실리콘 파츠 / 포토레지스트 원료 / 증착 전구체
    '119830': 'post', '219130': 'post', '323350': 'post', '036710': 'post', '355150': 'post',   # 테스트 대행 / 프로브카드 PCB / 프로브카드 본딩 장비 / 기판 지주 / 패키지 부품
    '348350': 'infra',                                                    # 클린룸 오염 모니터링
    '007660': 'etc',                                                      # AI 서버·네트워크 장비용 기판(반도체 공정 밖)
}
names = {}
def nm(c):
    if c in names: return names[c]
    n = (smi.get(c) or {}).get('n') or (hg.get(c) or {}).get('n') or (sd['co'].get(c) or {}).get('n') or c
    n = re.sub(r'\s*\((現|구|자회사|디지털|SK엔|미코|열처리).*?\)', '', n).strip()
    names[c] = n; return n

groups = []; pairs = []; co = {}; gids = set(); seen = set()
PR = {'high': 3, 'mid': 2, 'low': 1, 'unknown': 0}
files = sorted(glob.glob(os.path.join(ROOT, 'tools', 'semipeer', 'raw', '*.json')),
               key=lambda f: ORDER.index(os.path.basename(f)[:-5]) if os.path.basename(f)[:-5] in ORDER else 99)
for fp in files:
    b = os.path.basename(fp)[:-5]; O = json.load(open(fp, encoding='utf-8'))
    for g in O['groups']:
        gid = g['id']
        if gid in gids: gid = gid + '_' + b.split('_')[0]
        gids.add(gid)
        mem = [m for m in g.get('members') or [] if re.fullmatch(r'\d{6}', m)]
        groups.append({'id': gid, 'name': g['name'], 'seg': g['seg'], 'top': TOP.get(g['seg'], '팹리스·IP·유통'), 'basis': g['basis'], 'caution': g['caution'], 'members': mem,
                       'nopeer': [{'c': x['c'], 'why': x['why']} for x in g.get('nopeer') or []], 'src': b})
        for m in mem: co.setdefault(m, {'n': nm(m), 'gids': []})['gids'].append(gid)
        for x in g.get('nopeer') or []:
            e0 = co.setdefault(x['c'], {'n': nm(x['c']), 'gids': []})
            if gid not in e0['gids']: e0['gids'].append(gid)
            e0['nopeer'] = x['why']
        for p in g['pairs']:
            key = tuple(sorted((p['a'], p['b'])))
            if key in seen: print('중복 쌍 건너뜀', key, file=sys.stderr); continue
            seen.add(key)
            gr, tot = grade(p['score'])
            pairs.append({'a': p['a'], 'b': p['b'], 'gid': gid, 'score': p['score'], 'sum': tot, 'grade': gr,
                          'nul': sum(1 for v in p['score'].values() if v is None),
                          'why': p['why'], 'ev': [fix_ev(e) for e in p['ev']], 'verdict': p['verdict'], 'premium': p.get('premium') or ''})
    for x in O.get('companies') or []:
        c = x['c']; e = co.setdefault(c, {'n': nm(c), 'gids': []})
        if 'pure' not in e or PR[x['pure']] > PR[e['pure']]:
            e['pure'] = x['pure']; e['main'] = x['main']
            if x.get('ev'): e['ev'] = fix_ev(x['ev'])
    for x in O.get('global_peers') or []:
        e = co.setdefault(x['c'], {'n': nm(x['c']), 'gids': []})
        e['global'] = sorted(set((e.get('global') or []) + list(x['names'])))
        if x.get('ev') and 'gev' not in e: e['gev'] = fix_ev(x['ev'])
for c, e in co.items():
    e.setdefault('pure', 'unknown'); e.setdefault('main', '')
    it = smi.get(c)
    if it: e['cat'] = it.get('cat'); e['prod'] = it.get('prod')
    e['map'] = c in smi
    # 공정 구분: 소부장 맵 기업은 맵의 전/후/양/공 분류를 그대로, 맵 밖 기업은 STAGE_EXTRA(사업 내용 기준 수기 분류)
    if it:
        e['stage'] = {'전': 'pre', '후': 'post', '양': 'both', '공': 'infra'}.get(it.get('g'), 'etc')
        e['procs'] = [PROC.get(x, x) for x in it.get('p') or []]
    else:
        e['stage'] = STAGE_EXTRA.get(c, 'etc')
pairs.sort(key=lambda p: (-p['sum'], p['gid']))
out = {'updated': datetime.date.today().isoformat(),
       'criteria': [
           {'id': 'prod', 'name': '제품 동일성', 'd': '2 같은 제품을 같은 용도로 팔아 서로 대체되는 직접 경쟁 / 1 같은 제품군이지만 방식·세대·용도가 다름 / 0 다른 제품'},
           {'id': 'cust', 'name': '고객 중복', 'd': '2 주요 고객사가 실명으로 겹침 / 1 같은 고객군이지만 주력 고객이 다름 / 0 고객군이 다름'},
           {'id': 'mix', 'name': '매출 비중', 'd': '2 양사 모두 이 제품이 매출의 과반 / 1 한쪽만 주력 / 0 양쪽 다 부수 사업이거나 대기업·지주사'},
           {'id': 'model', 'name': '사업모델·단계', 'd': '2 판매 구조와 사업 단계가 같음 / 1 일부 다름 / 0 다름(양산 vs 진입 단계, 캡티브 vs 외판 등)'},
           {'id': 'driver', 'name': '실적 드라이버', 'd': '2 실적을 움직이는 전방 변수가 같음 / 1 일부 겹침 / 0 다름'}],
       'grade_rule': {'A': '합계 8점 이상이고 제품 동일성 2점 — 멀티플 직접 비교 가능', 'B': '합계 6점 이상이고 제품 동일성 1점 이상 — 차이를 감안한 조건부 비교',
                      'C': '그 외 — 참고용. 저밸류 판정에 쓰지 않음', 'null': '점수가 비어 있으면 자료에서 확인하지 못한 항목(0점으로 계산)'},
       'stage_name': STAGE_NAME,
       'stats': {'groups': len(groups), 'pairs': len(pairs), 'companies': len(co),
                 'A': sum(1 for p in pairs if p['grade'] == 'A'), 'B': sum(1 for p in pairs if p['grade'] == 'B'), 'C': sum(1 for p in pairs if p['grade'] == 'C')},
       'groups': groups, 'pairs': pairs, 'co': co}
json.dump(out, open(os.path.join(D, 'semipeer_def.json'), 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'))
print('저장 semipeer_def.json', out['stats'], os.path.getsize(os.path.join(D, 'semipeer_def.json')) // 1024, 'KB')
