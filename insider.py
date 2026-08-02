#!/usr/bin/env python3
# 내부자(임원) 매수 스크리너 — DART 임원·주요주주 소유상황보고서(D002) 원문 파싱
# 조건: 임원(경영진)이 1건에서 1억원 이상 순매수(취득단가 × 증감수량, 공시 원문 기준)
import os, io, sys, json, time, zipfile, urllib.request, re, html, datetime

DART_KEY = os.environ.get('DART_KEY', '')
DAYS = int(os.environ.get('DAYS', '30'))
MAXR = int(os.environ.get('MAXR', '0'))          # 테스트용 처리 건수 제한(0=전체)
MIN_AMT = int(os.environ.get('MIN_AMT', '100000000'))  # 1억
BUY_ONLY = os.environ.get('BUY_ONLY', '1') == '1'      # 1=장내매수만 집계
REASONS = {}                                            # 사유별 건수(디버그용)
BASE = 'https://opendart.fss.or.kr/api'

def fetch(url):
    for _ in range(3):
        try:
            with urllib.request.urlopen(url, timeout=25) as r:
                return r.read()
        except Exception:
            time.sleep(1)
    return b''

def jget(url):
    try:
        return json.loads(fetch(url).decode('utf-8'))
    except Exception:
        return {}

def clean(s):
    return html.unescape(re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', '', s))).strip()

def num(s):
    s = re.sub(r'[^\d\-]', '', s or '')
    if s in ('', '-'):
        return None
    try:
        return int(s)
    except Exception:
        return None

def list_reports():
    end = datetime.date.today()
    bgn = end - datetime.timedelta(days=DAYS)
    out, page = [], 1
    while True:
        d = jget('%s/list.json?crtfc_key=%s&bgn_de=%s&end_de=%s&pblntf_detail_ty=D002&page_no=%d&page_count=100&sort=date&sort_mth=desc'
                 % (BASE, DART_KEY, bgn.strftime('%Y%m%d'), end.strftime('%Y%m%d'), page))
        lst = d.get('list') or []
        out += [(x['rcept_no'], x['corp_code'], x['corp_name'], x['rcept_dt'], x.get('stock_code', '')) for x in lst]
        tp = int(d.get('total_page', 1) or 1)
        if page >= tp:
            break
        page += 1
    return out

def parse_doc(rcept):
    b = fetch('%s/document.xml?crtfc_key=%s&rcept_no=%s' % (BASE, DART_KEY, rcept))
    try:
        raw = zipfile.ZipFile(io.BytesIO(b)).read(zipfile.ZipFile(io.BytesIO(b)).namelist()[0]).decode('utf-8', 'ignore')
    except Exception:
        return None
    nm = re.search(r'ACODE="IFR_NM"[^>]*>\s*([^<]+)', raw)
    pos = re.search(r'ACODE="STF_PSM"[^>]*>\s*([^<]+)', raw)
    name = clean(nm.group(1)) if nm else ''
    position = clean(pos.group(1)) if pos else ''
    # 임원·주요주주 등 누구든 포함. 직위가 없으면 '주요주주'로 표기
    if not position or position in ('-', '해당없음'):
        position = '주요주주'
    # 세부변동내역: ACODE 기준 정확 매핑. 증감=MDF_STK_CNT, 취득단가=ACI_AMT2, 합계=MDF_STK_SUM
    seg = raw[raw.find('세부변동내역'): (raw.find('증권시장에서 주식등을') or len(raw))]
    rows = re.findall(r'<TR[^>]*>(.*?)</TR>', seg, re.S)
    def cellmap(row):
        d, cells = {}, []
        for attr, c in re.findall(r'<T[EDHU]([^>]*)>(.*?)</T[EDHU]>', row, re.S):
            txt = clean(c)
            cells.append(txt)
            m = re.search(r'ACODE="([^"]*)"', attr)
            if m:
                d[m.group(1)] = txt
        return d, cells
    def firstnum(t):
        # 주식 외 증권(CB 등)은 "행사총액 (주당단가)" 형태 → 괄호 안이 실제 단가
        if not t:
            return None
        mp = re.search(r'\(([^)]*\d[^)]*)\)', t)
        if mp:
            return num(mp.group(1))
        m = re.search(r'(\d[\d,]*)', t)
        return num(m.group(1)) if m else None
    def rowreason(cm):
        # 보고사유 셀: D002 원문은 "장내매수(+)", "주식배당(+)", "장내매도(-)" 형태
        for v in cm.values():
            if re.search(r'\([+\-]\)\s*$', v):
                return v
        for v in cm.values():
            if re.search(r'장내매수|장외매수|장내매도|신규선임|신규보고|주식배당|무상신주|유상신주|수증|증여|상속|전환|행사|취득|처분', v):
                return v
        return ''
    qty, amt, reasons = 0, 0, set()
    for row in rows:
        cm, cells = cellmap(row)
        if 'MDF_STK_SUM' in cm:
            continue
        reason, chg, price = None, None, None
        if 'MDF_STK_CNT' in cm:
            # 유형 A: ACODE 매핑 문서 (증감=MDF_STK_CNT, 취득단가=ACI_AMT2)
            reason = rowreason(cm)
            chg = num(cm.get('MDF_STK_CNT'))
            price = firstnum(cm.get('ACI_AMT2'))
        elif len(cells) >= 7 and re.search(r'\([+\-]\)', cells[0]):
            # 유형 B: AUNIT형 문서 — 위치 기반
            # [보고사유, 변동일, 증권종류, 변동전, 증감, 변동후, 취득/처분단가, ...]
            reason = cells[0]
            bf, af = num(cells[3]), num(cells[5])
            chg = (af - bf) if (bf is not None and af is not None) else num(cells[4])
            price = firstnum(cells[6])
        else:
            continue
        REASONS[reason or '(사유식별불가)'] = REASONS.get(reason or '(사유식별불가)', 0) + 1
        # 장내매수만 집계 (BUY_ONLY=0 이면 모든 증가분 집계)
        if BUY_ONLY and '장내매수' not in (reason or ''):
            continue
        if chg and chg > 0 and price and price > 0:
            qty += chg
            amt += chg * price
            if reason:
                reasons.add(re.sub(r'\([+\-]\)\s*$', '', reason).strip())
    if amt < MIN_AMT:
        return None
    avg_price = round(amt / qty) if qty else None
    return {'name': name, 'position': position, 'qty': qty, 'amount': amt, 'price': avg_price,
            'reason': ', '.join(sorted(reasons)) if reasons else ('장내매수' if BUY_ONLY else '취득')}

def main():
    if not DART_KEY:
        print('DART_KEY 필요'); sys.exit(1)
    reps = list_reports()
    if MAXR:
        reps = reps[:MAXR]
    print('D002 보고서 %d건 처리' % len(reps), file=sys.stderr)
    seen, matches = set(), []
    for (rcept, corp, cname, dt, scode) in reps:
        try:
            r = parse_doc(rcept)
        except Exception:
            r = None
        if not r:
            continue
        matches.append({
            'code': scode, 'name': cname, 'corp_code': corp,
            'insider': r['name'], 'position': r['position'],
            'qty': r['qty'], 'amount': r['amount'], 'amountEok': round(r['amount'] / 1e8, 1),
            'price': r['price'], 'date': dt, 'reason': r.get('reason', ''),
            'link': 'https://dart.fss.or.kr/dsaf001/main.do?rcpNo=' + rcept,
            'src': '공시원문 취득단가'
        })
        time.sleep(0.03)
    top_reasons = sorted(REASONS.items(), key=lambda x: -x[1])[:12]
    print('사유 분포(상위): ' + ', '.join('%s=%d' % t for t in top_reasons), file=sys.stderr)
    matches.sort(key=lambda m: m['amount'], reverse=True)
    out = {'updated': time.strftime('%Y-%m-%d %H:%M'), 'days': DAYS, 'count': len(matches),
           'buyOnly': BUY_ONLY, 'list': matches}
    os.makedirs('public/data', exist_ok=True)
    with open('public/data/insider.json', 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False)
    print('임원 1억↑ 매수 %d건' % len(matches), file=sys.stderr)
    for m in matches[:20]:
        print('%s %-10s %s(%s) %s주 @ %s원 = %s억  %s' % (
            m['code'], m['name'][:9], m['insider'], m['position'],
            format(m['qty'], ','), format(m['price'] or 0, ','), m['amountEok'], m['date']))

if __name__ == '__main__':
    main()
