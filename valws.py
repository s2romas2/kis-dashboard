#!/usr/bin/env python3
# 밸류 워크시트 자동 채움 수집기 — public/data/valws_watch.json 의 관심 종목(+피어)에 대해
#   네이버 종목 재무(연간 3년 + FY1 컨센, 분기 5개), 시세 요약(시총·52주·추정 EPS/PER),
#   DART 전환사채(CB)·신주인수권부사채(BW) 발행결정(최근 4년) → 잠재 희석 참고
# 필요 시크릿: DART_API_KEY(선택)   결과: public/data/valws_auto.json
import os, sys, json, time, re, datetime, urllib.request, ssl

KEY = os.environ.get('DART_API_KEY', '')
WATCH = os.environ.get('WATCH', 'public/data/valws_watch.json')
OUT = os.environ.get('OUT', 'public/data/valws_auto.json')
UA = {'User-Agent': 'Mozilla/5.0'}
CTX = ssl.create_default_context(); CTX.check_hostname = False; CTX.verify_mode = ssl.CERT_NONE
KST = datetime.timezone(datetime.timedelta(hours=9)); TODAY = datetime.datetime.now(KST).date()
DEBUG = []

def log(s): DEBUG.append(str(s)[:300]); print(s, file=sys.stderr, flush=True)
def jget(url, timeout=30, tries=3):
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers=UA)
            return json.loads(urllib.request.urlopen(req, timeout=timeout, context=CTX).read().decode('utf-8'))
        except Exception as e:
            err = e; time.sleep(1.5 * (i + 1))
    log('fetch 실패 %s %r' % (url[:90], err)); return {}
def tonum(s):
    try:
        s = str(s).replace(',', '').replace('배', '').replace('원', '').replace('%', '').strip()
        if s in ('', '-', 'N/A'): return None
        return float(s)
    except Exception: return None

def naver_fin(code, kind):
    j = jget('https://m.stock.naver.com/api/stock/%s/finance/%s' % (code, kind))
    fi = j.get('financeInfo') or {}
    cols = [(t['key'], t.get('isConsensus') == 'Y') for t in fi.get('trTitleList') or []]
    rows = {}
    for r in fi.get('rowList') or []:
        rows[r['title']] = {k: tonum(v.get('value')) for k, v in (r.get('columns') or {}).items()}
    return {'cols': cols, 'rows': rows}

def naver_basic(code):
    j = jget('https://m.stock.naver.com/api/stock/%s/integration' % code)
    info = {t['key']: t.get('value') for t in j.get('totalInfos') or []}
    peers = [{'c': p.get('itemCode'), 'n': p.get('stockName')} for p in j.get('industryCompareInfo') or []]
    return {'name': j.get('stockName'), 'ind': j.get('industryCode'), 'info': info, 'naver_peers': peers}

def dart_corpmap():
    if not KEY: return {}
    import zipfile, io, xml.etree.ElementTree as ET
    try:
        b = urllib.request.urlopen(urllib.request.Request('https://opendart.fss.or.kr/api/corpCode.xml?crtfc_key=' + KEY, headers=UA), timeout=90, context=CTX).read()
        z = zipfile.ZipFile(io.BytesIO(b)); xml = z.read(z.namelist()[0])
        m = {}
        for el in ET.fromstring(xml).iter('list'):
            sc = (el.findtext('stock_code') or '').strip()
            if re.fullmatch(r'\d{6}', sc): m[sc] = el.findtext('corp_code')
        return m
    except Exception as e:
        log('corpCode 실패 %r' % e); return {}

def dart_bonds(corp):
    out = []
    if not KEY or not corp: return out
    bgn = (TODAY - datetime.timedelta(days=365 * 4)).strftime('%Y%m%d'); end = TODAY.strftime('%Y%m%d')
    for api, kind in (('cvbdIsDecsn', 'CB'), ('bdwtIsDecsn', 'BW')):
        j = jget('https://opendart.fss.or.kr/api/%s.json?crtfc_key=%s&corp_code=%s&bgn_de=%s&end_de=%s' % (api, KEY, corp, bgn, end))
        if j.get('status') not in ('000',): continue
        for r in j.get('list') or []:
            out.append({'kind': kind, 'tm': r.get('bd_tm'), 'knd': r.get('bd_knd'), 'amt': tonum(r.get('bd_fta')),
                        'prc': tonum(r.get('cv_prc') or r.get('ex_prc')), 'cnt': tonum(r.get('cvisstk_cnt') or r.get('ex_stk_cnt')),
                        'vs': r.get('cvisstk_tisstk_vs') or r.get('ex_stk_tisstk_vs'),
                        'from': r.get('cv_rqpd_bgd') or r.get('ex_rqpd_bgd'), 'to': r.get('cv_rqpd_edd') or r.get('ex_rqpd_edd'),
                        'mtd': r.get('bd_mtd'), 'rcept': r.get('rcept_no'), 'date': (r.get('rcept_no') or '')[:8]})
        time.sleep(0.2)
    return out

def main():
    try: w = json.load(open(WATCH, encoding='utf-8'))
    except Exception as e: log('watch 파일 없음 %r' % e); w = {'codes': [], 'peers': {}}
    codes = [c for c in w.get('codes') or [] if re.fullmatch(r'\d{6}', c)]
    peers = {k: [p for p in v if re.fullmatch(r'\d{6}', p)] for k, v in (w.get('peers') or {}).items()}
    allc = list(dict.fromkeys(codes + [p for v in peers.values() for p in v]))
    corpmap = dart_corpmap()
    out = {}
    for c in allc:
        b = naver_basic(c)
        a = naver_fin(c, 'annual'); q = naver_fin(c, 'quarter')
        d = {'name': b['name'], 'ind': b['ind'], 'info': b['info'], 'naver_peers': b['naver_peers'][:8], 'annual': a, 'quarter': q}
        if c in codes: d['bonds'] = dart_bonds(corpmap.get(c))
        out[c] = d; log('%s %s ok' % (c, b['name'])); time.sleep(0.3)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump({'updated': datetime.datetime.now(KST).strftime('%Y-%m-%d %H:%M'), 'codes': codes, 'peers': peers, 'map': out, 'debug': DEBUG[-30:]},
              open(OUT, 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'))
    log('저장 %s %d종목' % (OUT, len(out)))

if __name__ == '__main__': main()
