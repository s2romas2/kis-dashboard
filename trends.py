#!/usr/bin/env python3
# 트렌드 지표 수집
# - 네이버 데이터랩: 섹터별 키워드 검색트렌드 (주간, 2023~) — NAVER_ID/NAVER_SECRET 필요
# - 네이버 뉴스: 키워드별 최근 7일 기사수(버즈) 누적 — NAVER_ID/NAVER_SECRET 필요
# - 구글트렌드: pytrends (미국 검색지수, 차단 시 이전값 유지)
# - 관세청 수출: HS코드별 월별 수출액 — CUSTOMS_KEY(공공데이터포털) 필요
# 키가 없는 항목은 건너뛰고 기존 데이터 유지
import os, sys, json, time, re, urllib.request, urllib.parse, datetime
import xml.etree.ElementTree as ET

NAVER_ID = os.environ.get('NAVER_ID', '')
NAVER_SECRET = os.environ.get('NAVER_SECRET', '')
CUSTOMS_KEY = os.environ.get('CUSTOMS_KEY', '')
OUT = 'public/data/trends.json'
DEBUG = []
TODAY = datetime.date.today()

def prev():
    try:
        return json.load(open(OUT, encoding='utf-8'))
    except Exception:
        return {}

def naver_req(url, body=None):
    headers = {'X-Naver-Client-Id': NAVER_ID, 'X-Naver-Client-Secret': NAVER_SECRET}
    data = None
    if body is not None:
        headers['Content-Type'] = 'application/json'
        data = json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, headers=headers)
    return json.loads(urllib.request.urlopen(req, timeout=30).read().decode())

def datalab(keys):
    out = {}
    if not NAVER_ID or not NAVER_SECRET:
        DEBUG.append('데이터랩: 네이버 키 없음 → 건너뜀')
        return out
    start, end = '2023-01-01', TODAY.isoformat()
    for sec, themes in keys.items():
        groups = [{'groupName': t, 'keywords': kws} for t, kws in themes.items()][:5]
        try:
            d = naver_req('https://openapi.naver.com/v1/datalab/search',
                          {'startDate': start, 'endDate': end, 'timeUnit': 'week', 'keywordGroups': groups})
            out[sec] = {r['title']: [[p['period'], p['ratio']] for p in r['data']] for r in d.get('results', [])}
        except Exception as e:
            if len(DEBUG) < 20:
                DEBUG.append('데이터랩 %s: %r' % (sec, e))
        time.sleep(0.35)
    DEBUG.append('데이터랩 %d개 섹터 수집' % len(out))
    return out

def buzz(keys, prev_buzz):
    out = dict(prev_buzz or {})
    if not NAVER_ID or not NAVER_SECRET:
        DEBUG.append('버즈: 네이버 키 없음 → 건너뜀')
        return out
    cutoff = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=7)
    done = 0
    for sec, kws in keys.items():
        total = 0
        try:
            for kw in kws:
                cnt = 0
                for startpos in range(1, 1000, 100):
                    d = naver_req('https://openapi.naver.com/v1/search/news.json?query=%s&display=100&sort=date&start=%d'
                                  % (urllib.parse.quote(kw), startpos))
                    items = d.get('items', [])
                    hit_old = False
                    for it in items:
                        try:
                            pd = datetime.datetime.strptime(it['pubDate'], '%a, %d %b %Y %H:%M:%S %z')
                            if pd >= cutoff:
                                cnt += 1
                            else:
                                hit_old = True
                        except Exception:
                            pass
                    if hit_old or len(items) < 100:
                        break
                    time.sleep(0.12)
                total += cnt
                time.sleep(0.12)
            ser = [x for x in out.get(sec, []) if x[0] != TODAY.isoformat()]
            ser.append([TODAY.isoformat(), total])
            out[sec] = ser[-150:]
            done += 1
        except Exception as e:
            if len(DEBUG) < 20:
                DEBUG.append('버즈 %s: %r' % (sec, e))
    DEBUG.append('버즈 %d개 섹터 측정' % done)
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
            url = ('https://apis.data.go.kr/1220000/itemtrade/getItemtradeList?serviceKey=%s'
                   '&strtYymm=202001&endYymm=%s&hsSgn=%s' % (CUSTOMS_KEY, endm, hs))
            x = urllib.request.urlopen(url, timeout=60).read().decode('utf-8', 'ignore')
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
    keys = json.load(open('trendkeys.json', encoding='utf-8'))
    pv = prev()
    DEBUG.append('키 상태 — 네이버:%s 관세청:%s' % ('O' if NAVER_ID else 'X', 'O' if CUSTOMS_KEY else 'X'))
    dl = datalab(keys.get('datalab', {})) or pv.get('datalab', {})
    bz = buzz(keys.get('buzz', {}), pv.get('buzz'))
    gt = dict(pv.get('google', {}))  # 성공한 키워드만 갱신(부분 차단 시 이전값 유지)
    gt.update(gtrends(keys.get('google', [])))
    ex = exports(keys.get('export', {}), pv.get('export'))
    out = {'updated': time.strftime('%Y-%m-%d %H:%M'), 'debug': DEBUG,
           'datalab': dl, 'buzz': bz, 'google': gt, 'export': ex}
    os.makedirs('public/data', exist_ok=True)
    with open(OUT, 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False)
    print('완료:', DEBUG)

if __name__ == '__main__':
    main()
