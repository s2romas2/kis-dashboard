#!/usr/bin/env python3
# 종목별 일별 PBR·PER 시계열 계산 (2020~현재)
# - 주가: 네이버 fchart 일봉
# - 분기 자본총계·당기순이익: DART fnlttSinglAcnt (연결 우선)
# - 발행주식수: DART stockTotqySttus (보통주)
# - 반영 시점: 분기말 + 50일(사업보고서는 +90일) 지연 적용(공시 전 미래정보 방지)
# 결과: public/data/compare/{code}.json + index.json
import os, io, sys, json, time, zipfile, urllib.request, re, datetime
import xml.etree.ElementTree as ET

DART_KEY = os.environ.get('DART_KEY', '')
START = os.environ.get('START', '2020-01-02')
YEARS = list(range(2019, datetime.date.today().year + 1))  # TTM 계산 위해 2019부터
REPRT = {1: '11013', 2: '11012', 3: '11014', 4: '11011'}
QEND = {1: (3, 31), 2: (6, 30), 3: (9, 30), 4: (12, 31)}
BASE = 'https://opendart.fss.or.kr/api'
OUTDIR = 'public/data/compare'
LIMIT = int(os.environ.get('LIMIT', '0'))
DEBUG = []

def fetch(url, timeout=30):
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

def candles(code):
    x = fetch('https://fchart.stock.naver.com/sise.nhn?symbol=%s&timeframe=day&count=1800&requestType=0' % code).decode('euc-kr', 'ignore')
    out = []
    for item in re.findall(r'data="([^"]+)"', x):
        p = item.split('|')
        if len(p) >= 5 and re.fullmatch(r'\d{8}', p[0]):
            v = tonum(p[4])
            if v:
                out.append(('%s-%s-%s' % (p[0][:4], p[0][4:6], p[0][6:8]), v))
    return [x for x in sorted(out) if x[0] >= START]

def fin_quarters(corp):
    """분기별 {(y,q): {'eq': 자본총계, 'ni': 단일분기 순이익}}"""
    raw = {}
    for y in YEARS:
        for q, rc in REPRT.items():
            d = jget('%s/fnlttSinglAcnt.json?crtfc_key=%s&corp_code=%s&bsns_year=%d&reprt_code=%s'
                     % (BASE, DART_KEY, corp, y, rc))
            slot = {}
            for it in (d.get('list') or []):
                fs = it.get('fs_div')  # CFS 연결 / OFS 별도
                nm = (it.get('account_nm') or '').strip()
                cur = tonum(it.get('thstrm_amount'))
                cum = tonum(it.get('thstrm_add_amount'))
                if cur is None:
                    continue
                key = 'eq' if nm == '자본총계' else ('ni' if nm in ('당기순이익', '당기순이익(손실)') else None)
                if not key:
                    continue
                pref = slot.get(key + '_fs')
                if pref == 'CFS' and fs != 'CFS':
                    continue
                slot[key] = {'cur': cur, 'cum': cum if cum is not None else cur}
                slot[key + '_fs'] = fs
            if slot:
                raw[(y, q)] = slot
            time.sleep(0.06)
    out = {}
    for (y, q), s in raw.items():
        eq = s.get('eq', {}).get('cur')
        ni = None
        if 'ni' in s:
            if q in (1, 2, 3):
                ni = s['ni']['cur']
            else:  # Q4 = 연간 - 3Q누적
                fy = s['ni']['cur']
                n3 = raw.get((y, 3), {}).get('ni', {})
                nine = n3.get('cum', n3.get('cur'))
                if fy is not None and nine is not None:
                    ni = fy - nine
        out[(y, q)] = {'eq': eq, 'ni': ni}
    return out

def shares_by_year(corp):
    """연도별 보통주 발행주식수 (사업보고서 우선, 없으면 최근 분기보고서)"""
    out = {}
    for y in YEARS:
        got = None
        for rc in ('11011', '11014', '11012', '11013'):
            d = jget('%s/stockTotqySttus.json?crtfc_key=%s&corp_code=%s&bsns_year=%d&reprt_code=%s'
                     % (BASE, DART_KEY, corp, y, rc))
            for it in (d.get('list') or []):
                se = (it.get('se') or '').replace(' ', '')
                if '보통주' in se:
                    v = tonum(it.get('istc_totqy')) or tonum(it.get('now_to_isu_stock_totqy'))
                    if v and v > 0:
                        got = v
                        break
            if got:
                break
            time.sleep(0.05)
        if got:
            out[y] = got
    return out

def build_series(code, name, corp):
    px = candles(code)
    if len(px) < 100:
        return None
    fq = fin_quarters(corp)
    sh = shares_by_year(corp)
    if not fq or not sh:
        return None
    # 분기 스냅샷: 반영일(eff) 기준 정렬 [(eff, bps, eps_ttm)]
    snaps = []
    for (y, q), v in sorted(fq.items()):
        qe = datetime.date(y, QEND[q][0], QEND[q][1])
        eff = qe + datetime.timedelta(days=90 if q == 4 else 50)
        shares = sh.get(y) or sh.get(y - 1) or (sorted(sh.items())[-1][1] if sh else None)
        if not shares:
            continue
        bps = (v['eq'] / shares) if v.get('eq') else None
        # TTM 순이익: 해당 분기 포함 직전 4개 단일분기
        seq = sorted(fq.items())
        idx = seq.index(((y, q), v))
        last4 = [x[1].get('ni') for x in seq[max(0, idx - 3): idx + 1]]
        eps = (sum(last4) / shares) if (len(last4) == 4 and all(n is not None for n in last4)) else None
        snaps.append((eff.isoformat(), bps, eps))
    if not snaps:
        return None
    pbr, per, roe = [], [], []
    si = -1
    cur_bps = cur_eps = None
    for d, close in px:
        while si + 1 < len(snaps) and snaps[si + 1][0] <= d:
            si += 1
            cur_bps = snaps[si][1] or cur_bps
            cur_eps = snaps[si][2] if snaps[si][2] is not None else cur_eps
        if cur_bps and cur_bps > 0:
            pbr.append([d, round(close / cur_bps, 2)])
        if cur_eps and cur_eps > 0:
            per.append([d, round(close / cur_eps, 2)])
            if cur_bps and cur_bps > 0:
                roe.append([d, round(cur_eps / cur_bps * 100, 2)])
    if len(pbr) < 50:
        return None
    return {'code': code, 'name': name, 'pbr': pbr, 'per': per, 'roe': roe}

def main():
    if not DART_KEY:
        print('DART_KEY 필요'); sys.exit(1)
    targets = {}  # code -> name
    try:
        kt = json.load(open('public/ktop10.json', encoding='utf-8'))
        for items in kt['stocks'].values():
            for x in items:
                targets[x[0]] = x[1]
    except Exception as e:
        print('ktop10 로드 실패:', e, file=sys.stderr)
    try:
        extra = json.load(open('compare_extra.json', encoding='utf-8'))
        for x in extra:
            targets[x['code']] = x.get('name', x['code'])
    except Exception:
        pass
    if LIMIT:
        targets = dict(list(targets.items())[:LIMIT])
    try:
        cmap = corp_map()
        DEBUG.append('corp_map %d개' % len(cmap))
    except Exception as e:
        DEBUG.append('corp_map 실패: %r' % e)
        cmap = {}
    os.makedirs(OUTDIR, exist_ok=True)
    index, ok, fail = {}, 0, 0
    for code, name in targets.items():
        corp = cmap.get(code)
        if not corp:
            fail += 1
            continue
        try:
            r = build_series(code, name, corp)
        except Exception as e:
            print('%s 실패: %r' % (code, e), file=sys.stderr)
            if len(DEBUG) < 10:
                DEBUG.append('%s 예외: %r' % (code, e))
            r = None
        if not r and len(DEBUG) < 10:
            try:
                px = candles(code)
                fq = fin_quarters(corp)
                sh = shares_by_year(corp)
                DEBUG.append('%s 진단: 주가 %d일, 재무분기 %d개, 주식수연도 %d개' % (code, len(px), len(fq), len(sh)))
            except Exception as e2:
                DEBUG.append('%s 진단 실패: %r' % (code, e2))
        if r:
            with open('%s/%s.json' % (OUTDIR, code), 'w', encoding='utf-8') as f:
                json.dump(r, f, ensure_ascii=False)
            index[code] = name
            ok += 1
        else:
            fail += 1
        print('%s %s %s' % (code, name, 'OK' if r else 'SKIP'), file=sys.stderr)
    with open('%s/index.json' % OUTDIR, 'w', encoding='utf-8') as f:
        json.dump({'updated': time.strftime('%Y-%m-%d %H:%M'), 'count': ok, 'codes': index, 'debug': DEBUG}, f, ensure_ascii=False)
    print('완료: %d성공 / %d실패' % (ok, fail))

if __name__ == '__main__':
    main()
