#!/usr/bin/env python3
# 비용 세부 분석 수집 (공시자료 우선)
# - 원재료 구성: 사업보고서 원문 'II. 사업의 내용 > 원재료' 표 발췌 (매출원가의 주요 구성)
# - 연구개발비용: 사업보고서 '연구개발활동' 표에서 매출액 대비 비율
# - 인건비: DART 직원현황(empSttus) 연간급여총액
# - 개발비 자산화: 전체 재무제표(fnlttSinglAcntAll) 무형자산 '개발비' 잔액
# 결과: public/data/costdetail.json {updated, debug, map:{code:{raw,rnd,labor,dev,y,gen}}}
import os, io, sys, json, time, zipfile, urllib.request, re, datetime
import xml.etree.ElementTree as ET

KEY = os.environ.get('DART_KEY', '')
BASE = 'https://opendart.fss.or.kr/api'
OUT = 'public/data/costdetail.json'
MAXRUN = int(os.environ.get('MAXRUN', '40'))
REFRESH_DAYS = 90  # 사업보고서는 연 1회 — 분기마다 재확인
PV = 2  # 파서 버전 — 올리면 기존 수집분도 재수집
DEBUG = []

def fetch(url, timeout=60):
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
    b = fetch('%s/corpCode.xml?crtfc_key=%s' % (BASE, KEY), 90)
    z = zipfile.ZipFile(io.BytesIO(b))
    root = ET.fromstring(z.read(z.namelist()[0]))
    m = {}
    for it in root.iter('list'):
        sc = (it.findtext('stock_code') or '').strip()
        if len(sc) == 6:
            m[sc] = it.findtext('corp_code').strip()
    return m

def latest_annual_rcp(corp):
    # list.json은 기본 조회기간이 최근 3개월 → 사업보고서(3월 제출)를 놓치므로 bgn_de 필수
    bgn = (datetime.date.today() - datetime.timedelta(days=540)).strftime('%Y%m%d')
    d = jget('%s/list.json?crtfc_key=%s&corp_code=%s&pblntf_detail_ty=A001&bgn_de=%s&page_count=20&last_reprt_at=Y' % (BASE, KEY, corp, bgn))
    for it in (d.get('list') or []):
        if '사업보고서' in (it.get('report_nm') or ''):
            return it.get('rcept_no'), (it.get('report_nm') or '')
    return None, ''

def doc_text(rcp):
    b = fetch('%s/document.xml?crtfc_key=%s&rcept_no=%s' % (BASE, KEY, rcp), 120)
    try:
        z = zipfile.ZipFile(io.BytesIO(b))
    except Exception:
        return ''
    txts = []
    for n in z.namelist():
        raw = z.read(n)
        for enc in ('utf-8', 'cp949'):
            try:
                t = raw.decode(enc)
                if '사업' in t or '재무' in t:
                    txts.append(t)
                    break
            except Exception:
                continue
    return '\n'.join(txts)

def strip_cells(tr_html):
    cells = re.findall(r'<T[DEH][^>]*>([\s\S]*?)</T[DEH]>', tr_html, re.I)
    out = []
    for c in cells:
        t = re.sub(r'<[^>]+>', ' ', c)
        t = re.sub(r'\s+', ' ', t).strip()
        out.append(t)
    return out

def parse_table_rows(txt, anchor_words, window=20000, max_rows=7):
    """앵커 단어 근처의 첫 표에서 의미 있는 행 추출 (베스트에포트)"""
    for aw in anchor_words:
        for m in re.finditer(re.escape(aw), txt):
            seg = txt[m.start(): m.start() + window]
            trs = re.findall(r'<TR[^>]*>([\s\S]*?)</TR>', seg, re.I)
            rows = []
            for tr in trs[:40]:
                cells = strip_cells(tr)
                cells = [c for c in cells if c]
                if len(cells) >= 2 and any(re.search(r'\d', c) for c in cells):
                    row = ' | '.join(cells[:6])[:120]
                    if row not in rows:
                        rows.append(row)
                if len(rows) >= max_rows:
                    break
            if len(rows) >= 2:
                return rows
    return []

def parse_rnd_ratio(txt):
    """연구개발비용 표에서 '매출액 대비 비율' 추출"""
    for m in re.finditer(r'연구개발비', txt):
        seg = txt[m.start(): m.start() + 15000]
        r = re.search(r'매출액\s*대비[\s\S]{0,300}?(\d{1,2}(?:\.\d{1,2})?)\s*%', seg)
        if not r:
            r = re.search(r'(?:연구개발비\s*/\s*매출액|매출액\s*중\s*연구개발)[\s\S]{0,200}?(\d{1,2}(?:\.\d{1,2})?)\s*%', seg)
        if r:
            v = tonum(r.group(1))
            if v is not None and 0 <= v <= 60:
                return v
    return None

def labor_cost(corp, year):
    """직원현황: 연간급여총액 합(원)"""
    for y in (year, year - 1):
        d = jget('%s/empSttus.json?crtfc_key=%s&corp_code=%s&bsns_year=%d&reprt_code=11011' % (BASE, KEY, corp, y))
        tot = 0
        for it in (d.get('list') or []):
            v = tonum(it.get('fyer_salary_totamt'))
            if v:
                tot += v
        if tot > 0:
            return tot, y
        time.sleep(0.05)
    return None, None

def dev_asset(corp, year):
    """무형자산 중 '개발비' 잔액(원) — 전체 재무제표 BS"""
    for y in (year, year - 1):
        for fs in ('CFS', 'OFS'):
            d = jget('%s/fnlttSinglAcntAll.json?crtfc_key=%s&corp_code=%s&bsns_year=%d&reprt_code=11011&fs_div=%s' % (BASE, KEY, corp, y, fs))
            for it in (d.get('list') or []):
                nm = (it.get('account_nm') or '').replace(' ', '')
                if it.get('sj_div') == 'BS' and ('개발비' in nm and '연구' not in nm):
                    v = tonum(it.get('thstrm_amount'))
                    if v and v > 0:
                        return v, y
            time.sleep(0.05)
        if d.get('list'):
            break
    return None, None

def main():
    if not KEY:
        print('DART_KEY 필요'); sys.exit(1)
    # 대상: 특장점 노트 종목 + ktop10 (우선순위 높은 종목부터)
    targets = {}
    try:
        sn = json.load(open('public/stocknotes.json', encoding='utf-8'))
        for g in sn['industries']:
            for s in g['stocks']:
                if re.fullmatch(r'\d{6}', s['code']):
                    targets[s['code']] = s['name']
    except Exception as e:
        DEBUG.append('stocknotes 실패: %r' % e)
    try:
        kt = json.load(open('public/ktop10.json', encoding='utf-8'))
        for items in kt['stocks'].values():
            for x in items:
                targets.setdefault(x[0], x[1])
    except Exception as e:
        DEBUG.append('ktop10 실패: %r' % e)
    # 시총 상위 300 (비용구조 패널과 동일 대상 — 노트·ktop10 뒤 순위로 순차 수집)
    try:
        sv = json.load(open('public/data/stockvals.json', encoding='utf-8'))['map']
        pj = json.load(open('public/data/products.json', encoding='utf-8'))['map']
        top = sorted(((c, v) for c, v in sv.items() if v and v[2]), key=lambda x: -x[1][2])[:300]
        for c, _ in top:
            e = pj.get(c)
            nm = (e.get('n') if isinstance(e, dict) else None) or c
            targets.setdefault(c, nm)
    except Exception as e:
        DEBUG.append('top300 실패: %r' % e)
    try:
        prev = json.load(open(OUT, encoding='utf-8'))
        pmap = prev.get('map') or {}
    except Exception:
        pmap = {}
    cutoff = (datetime.date.today() - datetime.timedelta(days=REFRESH_DAYS)).isoformat()
    try:
        cmap = corp_map()
    except Exception as e:
        DEBUG.append('corp_map 실패: %r' % e)
        cmap = {}
    ran = 0
    for code, name in targets.items():
        old = pmap.get(code)
        if old and old.get('pv') == PV and (old.get('gen') or '') >= cutoff:
            continue
        if ran >= MAXRUN:
            break
        corp = cmap.get(code)
        if not corp:
            continue
        ran += 1
        ent = {'gen': datetime.date.today().isoformat(), 'pv': PV}
        try:
            rcp, rnm = latest_annual_rcp(corp)
            year = datetime.date.today().year - 1
            m = re.search(r'\((\d{4})\.', rnm)
            if m:
                year = int(m.group(1))
            ent['y'] = year
            if rcp:
                txt = doc_text(rcp)
                if txt:
                    ent['raw'] = parse_table_rows(txt, ['주요 원재료', '원재료 및 생산설비', '원재료의 명칭', '원재료 등의 현황', '나. 원재료', '원재료 현황'])
                    rr = parse_rnd_ratio(txt)
                    if rr is not None:
                        ent['rnd'] = rr
            lab, ly = labor_cost(corp, year)
            if lab:
                ent['labor'] = round(lab / 1e8)  # 억원
            dv, dy = dev_asset(corp, year)
            if dv:
                ent['dev'] = round(dv / 1e8)  # 억원
        except Exception as e:
            if len(DEBUG) < 10:
                DEBUG.append('%s 예외: %r' % (code, e))
        pmap[code] = ent
        print('%s %s raw:%d rnd:%s labor:%s dev:%s' % (code, name, len(ent.get('raw') or []), ent.get('rnd'), ent.get('labor'), ent.get('dev')), file=sys.stderr)
        time.sleep(0.3)
    DEBUG.append('이번 실행 %d종목 (한도 %d, 전체 대상 %d)' % (ran, MAXRUN, len(targets)))
    os.makedirs('public/data', exist_ok=True)
    with open(OUT, 'w', encoding='utf-8') as f:
        json.dump({'updated': time.strftime('%Y-%m-%d %H:%M'), 'debug': DEBUG, 'map': pmap}, f, ensure_ascii=False)
    print('완료:', DEBUG)

if __name__ == '__main__':
    try:
        main()
    except Exception:
        import traceback
        os.makedirs('public/data', exist_ok=True)
        json.dump({'error': traceback.format_exc(), 'ts': time.strftime('%Y-%m-%d %H:%M')},
                  open('public/data/costdetail_error.json', 'w', encoding='utf-8'), ensure_ascii=False)
        raise
