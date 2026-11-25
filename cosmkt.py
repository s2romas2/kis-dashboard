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
        tbs = tables_near(txt, ['판매비와관리비', '판매비와 관리비', '판매비및관리비'], limit=8)
        e['표_후보'] = len(tbs)
        hit = []
        for t in tbs:
            lab = [r2[0] if r2 else '' for r2 in t['rows']]
            if any(AD.search(x or '') for x in lab):
                hit.append({'행수': len(t['rows']),
                            '앞10행': [' | '.join(x[:5])[:110] for x in t['rows'][:10]]})
        e['광고행_포함표'] = hit[:2]
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
