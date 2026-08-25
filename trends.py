#!/usr/bin/env python3
# 트렌드 지표 수집 (네이버 오픈API 종료로 키 불필요 소스로 구성) (수출 키 등록 후 재실행)
# - 검색트렌드(한국): pytrends geo=KR — 429 차단 시 성공한 섹터만 갱신(누적)
# - 뉴스 버즈: 구글뉴스 RSS 최근 7일 기사수 — 키 불필요
# - 구글트렌드(미국): pytrends geo=US — 키워드별 병합
# - 관세청 수출: HS코드별 월별 수출액 — CUSTOMS_KEY(공공데이터포털) 필요
import os, sys, json, time, re, urllib.request, urllib.parse, datetime
import xml.etree.ElementTree as ET

CUSTOMS_KEY = os.environ.get('CUSTOMS_KEY', '')
OUT = 'public/data/trends.json'
DEBUG = []
TODAY = datetime.date.today()

def prev():
    try:
        return json.load(open(OUT, encoding='utf-8'))
    except Exception:
        return {}

def datalab(keys, prev_dl):
    """검색트렌드(한국): pytrends geo=KR — 섹터당 테마 대표 키워드 최대 5개.
    429 차단된 섹터는 이전값 유지, 성공분만 갱신(매일 누적)."""
    out = dict(prev_dl or {})
    try:
        from pytrends.request import TrendReq
    except Exception as e:
        DEBUG.append('pytrends 미설치: %r' % e)
        return out
    ok = 0
    try:
        pt = TrendReq(hl='ko', tz=-540)
        for sec, themes in keys.items():
            reps = {t: kws[0] for t, kws in list(themes.items())[:5]}  # 테마당 대표 키워드 1개
            for attempt in range(2):
                try:
                    pt.build_payload(list(reps.values()), timeframe='today 5-y', geo='KR')
                    df = pt.interest_over_time()
                    got = {}
                    for t, kw in reps.items():
                        if kw in df.columns:
                            got[t] = [[d.strftime('%Y-%m-%d'), int(v)] for d, v in df[kw].items()]
                    if got:
                        out[sec] = got
                        ok += 1
                    time.sleep(12)
                    break
                except Exception as e:
                    if attempt == 1 and len(DEBUG) < 20:
                        DEBUG.append('검색트렌드 %s: %r' % (sec, str(e)[:80]))
                    time.sleep(30)
    except Exception as e:
        DEBUG.append('검색트렌드 초기화: %r' % e)
    DEBUG.append('검색트렌드 %d개 섹터 갱신' % ok)
    return out

def buzz(keys, prev_buzz):
    """뉴스 버즈: 구글뉴스 RSS 최근 7일 기사수 (키워드당 최대 ~100건 집계)"""
    out = dict(prev_buzz or {})
    done = 0
    for sec, kws in keys.items():
        total = 0
        fail = False
        for kw in kws:
            try:
                q = urllib.parse.quote('%s when:7d' % kw)
                url = 'https://news.google.com/rss/search?q=%s&hl=ko&gl=KR&ceid=KR:ko' % q
                x = urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'}),
                                           timeout=30).read().decode('utf-8', 'ignore')
                total += len(re.findall(r'<item>', x))
            except Exception as e:
                fail = True
                if len(DEBUG) < 20:
                    DEBUG.append('버즈 %s/%s: %r' % (sec, kw, e))
            time.sleep(0.5)
        if not fail or total > 0:
            ser = [x for x in out.get(sec, []) if x[0] != TODAY.isoformat()]
            ser.append([TODAY.isoformat(), total])
            out[sec] = ser[-150:]
            done += 1
    DEBUG.append('버즈 %d개 섹터 측정' % done)
    return out

def buzz_brands(prev_bb):
    """뷰티 브랜드별 뉴스 버즈 (구글뉴스 RSS 최근 7일)"""
    out = dict(prev_bb or {})
    try:
        bk = json.load(open('public/beautykeys.json', encoding='utf-8'))
    except Exception as e:
        DEBUG.append('beautykeys 로드 실패: %r' % e)
        return out
    done = 0
    for big, mids in bk.items():
        for mid, brands in mids.items():
            for b in brands:
                try:
                    q = urllib.parse.quote('%s when:7d' % b)
                    url = 'https://news.google.com/rss/search?q=%s&hl=ko&gl=KR&ceid=KR:ko' % q
                    x = urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'}),
                                               timeout=30).read().decode('utf-8', 'ignore')
                    cnt = len(re.findall(r'<item>', x))
                    ser = [v for v in out.get(b, []) if v[0] != TODAY.isoformat()]
                    ser.append([TODAY.isoformat(), cnt])
                    out[b] = ser[-150:]
                    done += 1
                except Exception as e:
                    if len(DEBUG) < 20:
                        DEBUG.append('브랜드버즈 %s: %r' % (b, e))
                time.sleep(0.45)
    DEBUG.append('브랜드버즈 %d개' % done)
    return out

def gtrends(batches):
    out = {}
    try:
        from pytrends.request import TrendReq
    except Exception as e:
        DEBUG.append('pytrends 미설치: %r' % e)
        return out
    try:
        pt = TrendReq(hl='en-US', tz=0)
        for kws in batches:
            for attempt in range(2):  # 차단(429) 시 30초 후 1회 재시도
                try:
                    pt.build_payload(kws, timeframe='today 5-y', geo='US')
                    df = pt.interest_over_time()
                    for kw in kws:
                        if kw in df.columns:
                            out[kw] = [[d.strftime('%Y-%m-%d'), int(v)] for d, v in df[kw].items()]
                    time.sleep(8)
                    break
                except Exception as e:
                    if attempt == 1 and len(DEBUG) < 20:
                        DEBUG.append('구글트렌드 %s…: %r' % (kws[0], str(e)[:100]))
                    time.sleep(30)
    except Exception as e:
        DEBUG.append('구글트렌드 초기화: %r' % e)
    DEBUG.append('구글트렌드 %d개 키워드' % len(out))
    return out

def exports(hsmap, prev_exp):
    out = dict(prev_exp or {})
    if not CUSTOMS_KEY:
        DEBUG.append('수출: CUSTOMS_KEY 없음 → 건너뜀')
        return out
    endm = TODAY.strftime('%Y%m')
    ok = 0
    for name, hs in hsmap.items():
        try:
            q = ('/1220000/nitemtrade/getNitemtradeList?serviceKey=%s'
                 '&strtYymm=202001&endYymm=%s&hsSgn=%s' % (CUSTOMS_KEY, endm, hs))
            x = ''
            last = None
            for base in ('http://apis.data.go.kr', 'https://apis.data.go.kr', 'http://apis.data.go.kr'):
                try:
                    x = urllib.request.urlopen(base + q, timeout=110).read().decode('utf-8', 'ignore')
                    break
                except Exception as e2:
                    last = e2
                    time.sleep(3)
            if not x:
                raise last or Exception('빈 응답')
            root = ET.fromstring(x)
            ser = {}
            for it in root.iter('item'):
                ym = (it.findtext('year') or '').strip()
                v = (it.findtext('expDlr') or '').replace(',', '').strip()
                m = re.search(r'(\d{4})\.(\d{2})', ym)
                if m and re.fullmatch(r'-?\d+', v):
                    ser[m.group(1) + '-' + m.group(2)] = int(v)
            if ser:
                out[name] = sorted([[k, v] for k, v in ser.items()])
                ok += 1
            elif len(DEBUG) < 20:
                DEBUG.append('수출 %s 0건: %s' % (name, re.sub(r'\s+', ' ', x)[:150]))
        except Exception as e:
            if len(DEBUG) < 20:
                DEBUG.append('수출 %s: %r' % (name, e))
        time.sleep(0.3)
    DEBUG.append('수출 %d개 품목' % ok)
    return out

def main():
    keys = json.load(open('public/trendkeys.json', encoding='utf-8'))
    pv = prev()
    DEBUG.append('키 상태 — 관세청:%s' % ('O' if CUSTOMS_KEY else 'X'))
    dl = datalab(keys.get('datalab', {}), pv.get('datalab'))
    bz = buzz(keys.get('buzz', {}), pv.get('buzz'))
    bb = buzz_brands(pv.get('buzz_brand'))
    gt = dict(pv.get('google', {}))  # 성공한 키워드만 갱신(부분 차단 시 이전값 유지)
    allowed = {kw for batch in keys.get('google', []) for kw in batch}
    gt = {kk: vv for kk, vv in gt.items() if kk in allowed}  # 시드에서 빠진 키워드는 정리
    gt.update(gtrends(keys.get('google', [])))
    ex = exports(keys.get('export', {}), pv.get('export'))
    out = {'updated': time.strftime('%Y-%m-%d %H:%M'), 'debug': DEBUG,
           'datalab': dl, 'buzz': bz, 'buzz_brand': bb, 'google': gt, 'export': ex}
    os.makedirs('public/data', exist_ok=True)
    with open(OUT, 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False)
    print('완료:', DEBUG)

if __name__ == '__main__':
    main()
