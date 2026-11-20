# -*- coding: utf-8 -*-
"""
반도체 peer — 선행(포워드) 지표용 증권사 추정 수집기
    결과: public/data/semipeer_fwd.json

왜 따로 두나
    semipeer.py 는 DART 를 570콜 넘게 부르는 무거운 작업이라, 추정치 하나 때문에
    전체를 다시 돌릴 수 없다. 추정은 네이버(FnGuide 컨센서스) 한 곳만 보면 되므로
    가벼운 수집기로 분리하고, 화면에서 그날 시세(semipeer.json 의 cap·eq)와 묶어
    PER·PSR·PBR 을 계산한다. 그래야 주가가 바뀌면 배수도 같이 움직인다.

선행의 기준은 '내년'이다
    사용자 기준: 포워드는 당일 주가 ÷ **내년** 추정치. 그런데 공개 경로가 갈린다.
      · 네이버(FnGuide 컨센서스)는 추정 연도를 **올해(FY1) 한 해만** 공개한다 → 넓은 커버리지, 내년 없음
      · KIS 종목추정실적(HHKST668300C0)은 **올해·내년(FY1·FY2)** 을 주지만 한국투자증권 리서치
        **단일 추정**이고 커버 종목이 좁다
    그래서 둘 다 모아 두고, 화면은 **내년(FY2)을 기본**으로 쓰고 없을 때만 올해(FY1)를
    '올해 기준'이라고 못박아 보여 준다. 섞어서 한 숫자로 뭉개지 않는다.

한계(화면에도 그대로 적는다)
    · 내년 추정은 KIS 커버 종목에 한정된다 — 미커버는 내년 배수를 만들지 않는다.
    · 11월처럼 연말이 가까우면 올해(FY1)는 사실상 거의 확정된 숫자라 '선행'이 아니다.
    · 컨센서스도 KIS 추정도 확정이 아니라 추정이다 → 태그를 반드시 붙인다.
"""
import json, os, re, sys, time, urllib.request, urllib.error

BASE = os.environ.get('BASE', 'public/data')
KIS  = 'https://openapi.koreainvestment.com:9443'
OUT  = os.path.join(BASE, 'semipeer_fwd.json')
UA   = 'kis-dashboard fwdval/1.0'
DEBUG = []

def log(s):
    DEBUG.append(str(s)[:300]); print(s, file=sys.stderr)

def jget(url, tries=3):
    for i in range(tries):
        try:
            r = urllib.request.Request(url, headers={'User-Agent': UA, 'Accept': 'application/json'})
            return json.loads(urllib.request.urlopen(r, timeout=20).read())
        except urllib.error.HTTPError as e:
            if e.code == 404: return None
        except Exception:
            pass
        time.sleep(0.6 * (i + 1))
    return None

def tonum(v):
    if v in (None, '', '-', 'N/A'): return None
    try: return float(str(v).replace(',', '').strip())
    except Exception: return None

def consensus(code):
    """네이버 연간 재무 — 확정 연도들과 추정 연도(FY1)를 함께 돌려준다(억원)."""
    j = jget('https://m.stock.naver.com/api/stock/%s/finance/annual' % code)
    fi = (j or {}).get('financeInfo') or {}
    tl, rows = fi.get('trTitleList') or [], fi.get('rowList') or []
    if not tl or not rows: return None
    def row(t):
        for r in rows:
            if (r.get('title') or '').replace(' ', '') == t: return r.get('columns') or {}
        return {}
    rev, op, ni, nic = row('매출액'), row('영업이익'), row('당기순이익'), row('지배주주순이익')
    out = {}
    for t in tl:
        k = t.get('key') or ''
        m = re.match(r'(20\d\d)', k)
        if not m: continue
        v = lambda c: tonum((c.get(k) or {}).get('value'))
        n = v(nic)
        if n is None: n = v(ni)            # 지배주주 몫이 없으면 전체 순이익
        out[m.group(1)] = {'rev': v(rev), 'op': v(op), 'ni': n,
                           'est': (t.get('isConsensus') == 'Y')}
    return out or None

def payout(code):
    """최근 흑자 연도들의 배당성향 중앙값(%) — 선행 BPS 를 추정할 때 쓴다."""
    p = os.path.join(BASE, 'vf', code + '.json')
    if not os.path.exists(p): return None
    try:
        d = json.load(open(p, encoding='utf-8'))
    except Exception:
        return None
    vs = [r['payout'] for r in ((d.get('gov') or {}).get('div') or [])
          if r.get('payout') is not None and r.get('ni') and r['ni'] > 0]
    if not vs: return None
    vs.sort(); n = len(vs)
    return round(vs[n // 2] if n % 2 else (vs[n // 2 - 1] + vs[n // 2]) / 2, 1)

def kis_token():
    k, sec = os.environ.get('KIS_APPKEY'), os.environ.get('KIS_APPSECRET')
    if not k or not sec: return None
    body = json.dumps({'grant_type': 'client_credentials', 'appkey': k, 'appsecret': sec}).encode()
    for i in range(3):
        try:
            r = urllib.request.Request(KIS + '/oauth2/tokenP', data=body,
                                       headers={'content-type': 'application/json'})
            return json.loads(urllib.request.urlopen(r, timeout=20).read()).get('access_token')
        except Exception as e:
            log('토큰 실패(%d) %r — 65초 대기' % (i + 1, e)); time.sleep(65)   # 발급은 1분 1회 제한
    return None

def kis_est(tok, code):
    """KIS 종목추정실적 — 올해·내년 추정(매출·영업이익·순이익, 억원)."""
    h = {'authorization': 'Bearer ' + tok, 'appkey': os.environ['KIS_APPKEY'],
         'appsecret': os.environ['KIS_APPSECRET'], 'tr_id': 'HHKST668300C0', 'custtype': 'P'}
    try:
        r = urllib.request.Request(KIS + '/uapi/domestic-stock/v1/quotations/estimate-perform?SHT_CD=' + code,
                                   headers=h)
        j = json.loads(urllib.request.urlopen(r, timeout=20).read())
    except Exception:
        return None
    o4 = j.get('output4') or []
    o2 = j.get('output2') or []
    if isinstance(o2, dict): o2 = [o2]
    periods = [str(x.get('dt') or '').strip() for x in o4] if isinstance(o4, list) else []
    if not periods or len(o2) < 6: return None
    rows = [[tonum(r.get('data%d' % i)) for i in range(1, 6)] for r in o2]
    # output2 는 라벨 없이 매출·증감율·영업이익·증감율·순이익·증감율 6행 순서로 온다.
    rv, rvg, op, opg, ni, nig = rows[:6]
    def ok(v, g):   # 증감율 행이 실제로 값 행의 증감율인지로 순서를 검증한다
        n = 0
        for i in range(1, 5):
            if None in (v[i], v[i-1], g[i]) or v[i-1] <= 0: continue
            if abs((v[i]/v[i-1] - 1) * 100 - g[i]) <= max(3.0, abs(g[i]) * 0.1): n += 1
        return n >= 2
    if not (ok(rv, rvg) and ok(op, opg)): return None
    out = {}
    for i, p in enumerate(periods[:5]):
        m = re.search(r'(20\d\d)', p)
        if not m: continue
        out[m.group(1)] = {'rev': rv[i], 'op': op[i], 'ni': ni[i], 'est': 'E' in p.upper()}
    return out or None

def main():
    sp = json.load(open(os.path.join(BASE, 'semipeer.json'), encoding='utf-8'))
    codes = list((sp.get('co') or {}).keys())
    log('대상 %d종목' % len(codes))
    co, n_est, n_rev = {}, 0, 0
    t0 = time.time()
    for i, c in enumerate(codes):
        fy = consensus(c)
        time.sleep(0.15)
        if not fy: continue
        ys = sorted(fy)
        est = [y for y in ys if fy[y]['est']]
        if not est:
            continue                                  # 추정 연도가 없으면 담지 않는다
        y1 = est[0]
        prev = [y for y in ys if y < y1]
        y0 = prev[-1] if prev else None
        r = {'fy': y1, 'src': '네이버 컨센서스(FnGuide)'}
        for k in ('rev', 'op', 'ni'): r[k] = fy[y1].get(k)
        if y0:
            r['fy0'] = y0
            for k in ('rev', 'op', 'ni'): r[k + '0'] = fy[y0].get(k)
        po = payout(c)
        if po is not None: r['payout'] = po
        r = {'n1': r}                                   # 올해(FnGuide 컨센서스)
        if r['n1'].get('ni') is not None: n_est += 1
        if r['n1'].get('rev') is not None: n_rev += 1
        co[c] = r
        if (i + 1) % 40 == 0:
            log('  %d/%d (%ds)' % (i + 1, len(codes), time.time() - t0))
    # ── 내년(FY2): KIS 종목추정실적. 키가 없으면 건너뛰고 올해 추정만 남긴다.
    tok = kis_token()
    n_fy2 = 0
    if tok:
        log('KIS 추정 수집 시작')
        for i, c in enumerate(codes):
            if c not in co: continue
            fy = kis_est(tok, c)
            time.sleep(0.08)
            if not fy: continue
            est = sorted(y for y in fy if fy[y]['est'])
            if len(est) < 2: continue                     # 내년이 없으면 쓰지 않는다
            y2 = est[1]
            prev = sorted(y for y in fy if y < y2)
            r2 = {'fy': y2, 'src': '한투 리서치(KIS 단일 추정)'}
            for k in ('rev', 'op', 'ni'): r2[k] = fy[y2].get(k)
            if prev:
                r2['fy0'] = prev[-1]
                for k in ('rev', 'op', 'ni'): r2[k + '0'] = fy[prev[-1]].get(k)
            if co[c]['n1'].get('payout') is not None: r2['payout'] = co[c]['n1']['payout']
            if r2.get('ni') is not None or r2.get('rev') is not None:
                co[c]['n2'] = r2; n_fy2 += 1
            if (i + 1) % 50 == 0: log('  KIS %d/%d · 내년 %d' % (i + 1, len(codes), n_fy2))
        log('KIS 내년 추정 %d종목' % n_fy2)
    else:
        log('KIS 시크릿 없음 → 내년(FY2) 추정 생략, 올해(FY1)만 저장')
    if len(co) < len(codes) // 3:
        log('수집이 너무 적음(%d) — 기존 파일 유지' % len(co)); return 1
    out = {'updated': time.strftime('%Y-%m-%d %H:%M'), 'n': len(co),
           'n_ni': n_est, 'n_rev': n_rev, 'n_fy2': n_fy2,
           'note': ('선행 배수의 기준은 내년(FY2)이다. 내년 추정은 KIS 종목추정실적(한국투자증권 '
                    '리서치 단일 추정)만 공개하므로 커버 종목에 한정된다. 올해(FY1)는 네이버 '
                    'FnGuide 컨센서스(다수 추정 평균)로 커버리지가 넓지만, 연말이 가까우면 사실상 '
                    '확정값이라 선행으로서의 뜻이 약하다. 둘 다 확정이 아니라 추정이다.'),
           'co': co, 'debug': DEBUG[-60:]}
    os.makedirs(BASE, exist_ok=True)
    json.dump(out, open(OUT, 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'))
    log('저장 %s — %d종목 (순이익 추정 %d · 매출 추정 %d) %ds'
        % (OUT, len(co), n_est, n_rev, time.time() - t0))
    return 0

if __name__ == '__main__':
    sys.exit(main())
