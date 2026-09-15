#!/usr/bin/env python3
# 업종 밸류 축 — KRX 정보데이터시스템 "전체지수 PER/PBR/배당수익률"(MDCSTAT00701) 당일 값
# (KIS 오픈API에는 업종지수 PER/PBR이 없어 KRX를 보조 소스로 사용. valuation.py 방식(getJsonData.cmd 직접 호출)을 따름)
# 결과: public/data/sectorval.json
#   {updated, date, map:{"업종명|KOSPI":{per,pbr,div,idx,raw}}, hist:{"업종명|KOSPI":[[YYYYMMDD,pbr,per],...]}, all:[...], debug:[...]}
# 원칙: KRX 실패 시 기존 파일(map/hist) 유지 + debug 기록. 값은 지어내지 않는다.
#
# ⚠ 2026-09 확인: KRX 정보데이터시스템은 이제 **로그인 세션을 요구**(비로그인 요청은 HTTP 400 본문 "LOGOUT").
#   로그인 폼(login.jsp)의 비밀번호 입력란은 nProtect Plugin-Free(nppfs, npkencrypt="on")로 클라이언트 암호화 →
#   KRX_ID/PW만으로 헤드리스(GitHub Actions·파이썬) 자동 로그인은 불가능(봇 차단 목적의 독점 암호화).
#   따라서 이 스크립트는 GitHub Actions에서는 사실상 기존 파일을 보존만 한다(정상). 실제 갱신 경로:
#     (1) 로그인된 Chrome 세션에서 MDCSTAT00701을 fetch해 sectorval.json을 만들어 커밋(2026-09-15 방식, claude/현황.md 참조)
#     (2) KRX_COOKIE 시크릿: 로그인된 브라우저의 data.krx.co.kr 쿠키 문자열을 넘기면 그 세션으로 수집 시도(세션 만료 시 실패→보존)
import os, sys, json, time, datetime, re, urllib.request, urllib.parse, urllib.error, http.cookiejar

OUT = 'public/data/sectorval.json'
HIST_SRC = 'public/data/leadershist.json'   # 랭크테이블 업종명·시장 목록(이름 매칭용)
HIST_CAP = 700                              # 업종별 PBR 히스토리 보관 일수
DEBUG = []


def dbg(msg):
    DEBUG.append(str(msg)[:300])
    print(msg, file=sys.stderr)


def tofloat(v):
    try:
        f = float(str(v).replace(',', '').strip())
        return f if f > 0 else None
    except Exception:
        return None


def load_prev():
    try:
        return json.load(open(OUT, encoding='utf-8'))
    except Exception:
        return {}


def norm_name(s):
    """KRX 지수명 → 랭크테이블 업종명. '코스피 음식료·담배' → '음식료·담배'"""
    s = (s or '').strip()
    for pre in ('코스피 ', '코스닥 ', 'KOSPI ', 'KOSDAQ ', '코스피', '코스닥'):
        if s.startswith(pre):
            s = s[len(pre):].strip()
            break
    return s


def loose(s):
    return re.sub(r'[\s·,/&()]', '', s or '').lower()


class KRX:
    """getJsonData.cmd 호출 — 헤더·파라미터 변형을 순서대로 시도, 첫 성공 응답 사용"""
    def __init__(self):
        self.cj = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.cj))
        self.ua = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36'
        self.warm = False
        # KRX_COOKIE 시크릿(로그인된 브라우저 쿠키 문자열)이 있으면 그 세션으로 요청
        self.cookie = (os.environ.get('KRX_COOKIE') or '').strip()
        if self.cookie:
            dbg('KRX_COOKIE 사용(로그인 세션 %d바이트)' % len(self.cookie))

    def warmup(self, scheme):
        try:
            req = urllib.request.Request(
                '%s://data.krx.co.kr/contents/MDC/MDI/mdiLoader/index.cmd?menuId=MDC0201020506' % scheme,
                headers={'User-Agent': self.ua})
            self.opener.open(req, timeout=20).read(2000)
            self.warm = True
        except Exception as e:
            dbg('KRX 워밍업(%s) 실패: %r' % (scheme, e))

    def call(self, params):
        last = ''
        for scheme in ('https', 'http'):
            if not self.warm and not self.cookie:
                self.warmup(scheme)
            url = '%s://data.krx.co.kr/comm/bldAttendant/getJsonData.cmd' % scheme
            for referer in ('%s://data.krx.co.kr/contents/MDC/MDI/mdiLoader/index.cmd?menuId=MDC0201020506' % scheme,
                            '%s://data.krx.co.kr/contents/MDC/MDI/mdiLoader' % scheme):
                hdr = {'User-Agent': self.ua, 'Referer': referer,
                       'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
                       'Accept': 'application/json, text/javascript, */*; q=0.01',
                       'X-Requested-With': 'XMLHttpRequest', 'Origin': '%s://data.krx.co.kr' % scheme}
                if self.cookie:
                    hdr['Cookie'] = self.cookie
                try:
                    req = urllib.request.Request(url, data=urllib.parse.urlencode(params).encode(), headers=hdr)
                    body = self.opener.open(req, timeout=30).read().decode('utf-8', 'ignore')
                    j = json.loads(body)
                    rows = None
                    for k in ('output', 'OutBlock_1', 'block1'):
                        if isinstance(j.get(k), list):
                            rows = j[k]; break
                    if rows is None:
                        for v in j.values():
                            if isinstance(v, list):
                                rows = v; break
                    if rows:
                        return rows, ''
                    last = '빈 응답 %s' % body[:120]
                except urllib.error.HTTPError as e:
                    detail = ''
                    try:
                        detail = e.read().decode('utf-8', 'ignore')[:40]
                    except Exception:
                        pass
                    if 'LOGOUT' in detail or e.code == 400:
                        last = 'HTTP %s "%s" → KRX 로그인 세션 필요(KRX_COOKIE 미설정/만료)' % (e.code, detail)
                    else:
                        last = '%s %s: %r' % (scheme, referer[-30:], e)
                except Exception as e:
                    last = '%s %s: %r' % (scheme, referer[-30:], e)
                time.sleep(0.8)
        return [], last


def fetch_day(krx, mkt_code, trd_dd):
    """전체지수 PER/PBR/배당수익률 (MDCSTAT00701) — 파라미터 변형 2종 시도.
    mkt_code: ('02','1')=KOSPI, ('03','2')=KOSDAQ"""
    mid, ind = mkt_code
    base = {'bld': 'dbms/MDC/STAT/standard/MDCSTAT00701', 'locale': 'ko_KR', 'searchType': '1',
            'trdDd': trd_dd, 'share': '2', 'money': '3', 'csvxls_isNo': 'false'}
    variants = [dict(base, idxIndMidclssCd=mid), dict(base, indTpCd=ind), dict(base, idxIndMidclssCd=mid, indTpCd=ind)]
    errs = []
    for p in variants:
        rows, err = krx.call(p)
        if rows:
            return rows, ''
        errs.append(err)
    return [], ' | '.join(e for e in errs if e)[:300]


def pick_keys(row):
    keys = list(row.keys())
    def find(preds, exclude=()):
        for k in keys:
            ku = k.upper()
            if any(p in ku for p in preds) and not any(x in ku for x in exclude):
                return k
        return None
    return {
        'name': find(['IDX_NM', 'IDX_IND_NM', 'ISU_NM', '_NM']),
        'idx': find(['CLSPRC_IDX', 'CLSPRC']),
        'per': find(['WT_PER', 'PER'], exclude=('FWD', 'PERIOD')),
        'fper': find(['FWD_PER']),
        'pbr': find(['NETASST', 'PBR']),
        'div': find(['DIV_YD', 'DIV']),
    }


def main():
    prev = load_prev()
    out_map = dict(prev.get('map') or {})
    hist = dict(prev.get('hist') or {})
    # 랭크테이블 업종명 목록(이름 매칭 대상)
    targets = {}
    try:
        hs = json.load(open(HIST_SRC, encoding='utf-8')).get('sectors', {})
        for code, v in hs.items():
            if v.get('name') and v.get('mkt'):
                targets[(loose(v['name']), v['mkt'])] = v['name']
    except Exception as e:
        dbg('leadershist.json 읽기 실패: %r' % e)

    krx = KRX()
    today = datetime.datetime.utcnow() + datetime.timedelta(hours=9)
    got = {}        # mkt -> (date, rows)
    all_rows = []
    for mkt, code in (('KOSPI', ('02', '1')), ('KOSDAQ', ('03', '2'))):
        d = today.date()
        rows, err = [], ''
        for back in range(6):   # 당일 값이 아직 없으면 직전 영업일로 후퇴(최대 6일)
            dd = d - datetime.timedelta(days=back)
            if dd.weekday() >= 5:
                continue
            rows, err = fetch_day(krx, code, dd.strftime('%Y%m%d'))
            if rows:
                got[mkt] = (dd.strftime('%Y%m%d'), rows)
                break
            time.sleep(0.5)
        if not rows:
            dbg('KRX %s 실패: %s' % (mkt, err or '응답 없음'))
    if not got:
        dbg('KRX 전 시장 실패 → 기존 파일 유지')
        prev['debug'] = (prev.get('debug') or [])[-10:] + DEBUG[-10:]
        prev['last_try'] = today.strftime('%Y-%m-%d %H:%M') + ' KST'
        prev.setdefault('map', {}); prev.setdefault('hist', {})
        os.makedirs('public/data', exist_ok=True)
        json.dump(prev, open(OUT, 'w', encoding='utf-8'), ensure_ascii=False)
        return

    keys = None
    matched = 0
    for mkt, (dd, rows) in got.items():
        if keys is None:
            keys = pick_keys(rows[0])
            dbg('KRX 응답 키: %s → 매핑 %s' % (','.join(list(rows[0].keys())[:20]), keys))
        if not keys.get('name') or not keys.get('pbr'):
            dbg('KRX 응답에 지수명/PBR 키 없음 — 매핑 중단')
            break
        for r in rows:
            raw = str(r.get(keys['name']) or '').strip()
            if not raw:
                continue
            e = {'raw': raw, 'mkt': mkt, 'date': dd,
                 'idx': tofloat(r.get(keys['idx'])) if keys.get('idx') else None,
                 'per': tofloat(r.get(keys['per'])) if keys.get('per') else None,
                 'fper': tofloat(r.get(keys['fper'])) if keys.get('fper') else None,
                 'pbr': tofloat(r.get(keys['pbr'])),
                 'div': tofloat(r.get(keys['div'])) if keys.get('div') else None}
            all_rows.append(e)
            nm = norm_name(raw)
            tgt = targets.get((loose(nm), mkt))
            if not tgt:
                # 시장 접두어 없는 이름이 그대로 매칭되는 경우(코스닥 지수명이 '코스닥 음식료·담배'가 아닌 경우 등)
                tgt = targets.get((loose(raw), mkt))
            if not tgt:
                continue
            key = '%s|%s' % (tgt, mkt)
            out_map[key] = {'per': e['per'], 'pbr': e['pbr'], 'div': e['div'], 'fper': e['fper'],
                            'idx': e['idx'], 'raw': raw, 'date': dd}
            matched += 1
            if e['pbr']:
                h = [x for x in (hist.get(key) or []) if x[0] != dd]
                h.append([dd, e['pbr'], e['per']])
                hist[key] = sorted(h)[-HIST_CAP:]
    dbg('KRX 지수 %d행, 랭크테이블 업종 매칭 %d개(대상 %d)' % (len(all_rows), matched, len(targets)))
    if matched == 0 and all_rows:
        dbg('매칭 0 — 지수명 샘플: ' + ', '.join(sorted({e['raw'] for e in all_rows})[:15]))

    # PBR 히스토리 백분위(현재 PBR이 자기 이력에서 어느 위치인지) — 이력이 20일 이상 쌓인 뒤 의미
    for key, e in out_map.items():
        h = hist.get(key) or []
        if e.get('pbr') and len(h) >= 20:
            vals = [x[1] for x in h if x[1]]
            e['pbr_pct'] = round(sum(1 for v in vals if v <= e['pbr']) / len(vals) * 100)
            e['pbr_n'] = len(vals)
            e['pbr_min'], e['pbr_max'] = round(min(vals), 2), round(max(vals), 2)

    out = {'updated': today.strftime('%Y-%m-%d %H:%M') + ' KST',
           'date': max(dd for dd, _ in got.values()),
           'map': out_map, 'hist': hist, 'all': all_rows[:200], 'debug': DEBUG[-30:],
           'note': 'KRX 정보데이터시스템 전체지수 PER/PBR/배당수익률(MDCSTAT00701) 당일값. map 키 = 업종명|시장. hist = [일자, PBR, PER] 일일 누적'}
    os.makedirs('public/data', exist_ok=True)
    json.dump(out, open(OUT, 'w', encoding='utf-8'), ensure_ascii=False)
    print('저장 완료: 매칭 %d' % matched, file=sys.stderr)


if __name__ == '__main__':
    try:
        main()
    except Exception as e:
        dbg('치명: %r' % e)
        prev = load_prev()
        prev['debug'] = (prev.get('debug') or [])[-10:] + DEBUG[-10:]
        prev.setdefault('map', {}); prev.setdefault('hist', {})
        try:
            os.makedirs('public/data', exist_ok=True)
            json.dump(prev, open(OUT, 'w', encoding='utf-8'), ensure_ascii=False)
        except Exception:
            pass
        sys.exit(0)
