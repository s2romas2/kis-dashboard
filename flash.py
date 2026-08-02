#!/usr/bin/env python3
# 잠정실적 속보 — DART '영업(잠정)실적' 공정공시를 수집·파싱
# 정기보고서(분기·반기·사업보고서)보다 몇 주 빠른 실적 발표를 즉시 반영
# 결과: public/data/flash.json
import os, io, sys, json, time, zipfile, urllib.request, re, html, datetime

DART_KEY = os.environ.get('DART_KEY', '')
DAYS = int(os.environ.get('DAYS', '14'))
MAXR = int(os.environ.get('MAXR', '0'))
BASE = 'https://opendart.fss.or.kr/api'
OUT = 'public/data/flash.json'

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
    s2 = re.sub(r'[^\d\-.]', '', str(s or ''))
    if s2 in ('', '-', '.'):
        return None
    try:
        return float(s2)
    except Exception:
        return None

def list_flash():
    end = datetime.date.today()
    bgn = end - datetime.timedelta(days=DAYS)
    out, page = [], 1
    while True:
        d = jget('%s/list.json?crtfc_key=%s&bgn_de=%s&end_de=%s&pblntf_ty=I&page_no=%d&page_count=100&sort=date&sort_mth=desc'
                 % (BASE, DART_KEY, bgn.strftime('%Y%m%d'), end.strftime('%Y%m%d'), page))
        lst = d.get('list') or []
        for x in lst:
            nm = x.get('report_nm', '')
            if ('잠정' in nm and '실적' in nm) or '영업(잠정)실적' in nm:
                out.append(x)
        tp = int(d.get('total_page', 1) or 1)
        if page >= tp:
            break
        page += 1
    return out

def parse_flash(rcept):
    """공정공시 잠정실적 표에서 매출액/영업이익/당기순이익의 당기·전년동기·증감율 추출"""
    b = fetch('%s/document.xml?crtfc_key=%s&rcept_no=%s' % (BASE, DART_KEY, rcept))
    try:
        z = zipfile.ZipFile(io.BytesIO(b))
        raw = z.read(z.namelist()[0]).decode('utf-8', 'ignore')
    except Exception:
        return None
    unit = 1  # 백만원 단위가 표준. 억원/천원도 감지
    um = re.search(r'단위\s*[:：]?\s*(백만\s*원|억\s*원|천\s*원|원)', raw)
    if um:
        u = re.sub(r'\s', '', um.group(1))
        unit = {'백만원': 1_000_000, '억원': 100_000_000, '천원': 1_000, '원': 1}.get(u, 1_000_000)
    else:
        unit = 1_000_000
    rows = re.findall(r'<TR[^>]*>(.*?)</TR>', raw, re.S)
    res = {}
    for row in rows:
        cells = [clean(c) for _, c in re.findall(r'<T[EDHU]([^>]*)>(.*?)</T[EDHU]>', row, re.S)]
        cells = [c for c in cells if c != '']
        if len(cells) < 2:
            continue
        head = cells[0].replace(' ', '')
        key = None
        if re.match(r'^-?매출액', head) or head.startswith('매출액') or head.startswith('영업수익'):
            key = 'rev'
        elif head.startswith('영업이익'):
            key = 'op'
        elif re.match(r'^(당기순이익|분기순이익|반기순이익|연결당기순이익)', head):
            key = 'ni'
        if not key or key in res:
            continue
        # 셀 배치: [항목, (당해실적 라벨?), 당기, 전기, 전기대비%, 전년동기, 전년동기대비%] 등 변형 다양
        nums = []
        for c in cells[1:]:
            v = num(c)
            nums.append(v)
        vals = [v for v in nums if v is not None]
        if not vals:
            continue
        cur = vals[0]
        yoy = None
        # 증감율 셀: '%' 포함 셀 우선, 없으면 마지막 값이 비율(절대값<1000)로 보이면 채택
        pct = [num(c) for c in cells[1:] if '%' in c or '△' in c]
        pct = [p for p in pct if p is not None]
        if pct:
            yoy = pct[-1]
        elif len(vals) >= 3 and abs(vals[-1]) < 1000 and abs(vals[0]) >= 1000:
            yoy = vals[-1]
        res[key] = {'cur': cur, 'yoy': yoy}
    if 'rev' not in res and 'op' not in res:
        return None
    def eok(v):
        return None if v is None else round(v * unit / 100_000_000)
    out = {}
    for k in ('rev', 'op', 'ni'):
        if k in res:
            out[k] = eok(res[k]['cur'])
            out[k + 'YoY'] = res[k]['yoy']
    return out

def main():
    if not DART_KEY:
        print('DART_KEY 필요'); sys.exit(1)
    reps = list_flash()
    if MAXR:
        reps = reps[:MAXR]
    print('잠정실적 공시 %d건' % len(reps), file=sys.stderr)
    items, seen = [], set()
    for x in reps:
        rcept = x['rcept_no']
        key = (x.get('stock_code') or x['corp_name'], x.get('rcept_dt'))
        if rcept in seen:
            continue
        seen.add(rcept)
        try:
            p = parse_flash(rcept)
        except Exception:
            p = None
        item = {
            'code': x.get('stock_code', ''), 'name': x['corp_name'], 'date': x.get('rcept_dt', ''),
            'title': x.get('report_nm', '').strip(),
            'link': 'https://dart.fss.or.kr/dsaf001/main.do?rcpNo=' + rcept,
        }
        if p:
            item.update(p)
        items.append(item)
        time.sleep(0.05)
    items.sort(key=lambda m: m['date'], reverse=True)
    out = {'updated': time.strftime('%Y-%m-%d %H:%M'), 'days': DAYS, 'count': len(items), 'list': items}
    os.makedirs('public/data', exist_ok=True)
    with open(OUT, 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False)
    parsed = sum(1 for i in items if 'rev' in i or 'op' in i)
    print('저장: %d건 (숫자 파싱 성공 %d건)' % (len(items), parsed), file=sys.stderr)
    # 파싱 전멸 시: 실제 문서 구조 덤프(파서 개선용)
    if items and parsed == 0:
        try:
            with open('public/data/flash_debug.txt', 'w', encoding='utf-8') as df:
                for x in reps[:2]:
                    b = fetch('%s/document.xml?crtfc_key=%s&rcept_no=%s' % (BASE, DART_KEY, x['rcept_no']))
                    try:
                        z = zipfile.ZipFile(io.BytesIO(b))
                        raw = z.read(z.namelist()[0]).decode('utf-8', 'ignore')
                    except Exception as e:
                        df.write('=== %s %s: unzip 실패 %s\n' % (x['corp_name'], x['rcept_no'], e))
                        continue
                    df.write('===== %s %s (%d bytes) =====\n' % (x['corp_name'], x['rcept_no'], len(raw)))
                    i = raw.find('매출액')
                    df.write(raw[max(0, i - 3000): i + 9000] if i >= 0 else raw[:12000])
                    df.write('\n\n')
        except Exception as e:
            print('디버그 덤프 실패:', e, file=sys.stderr)
    for m in items[:15]:
        print('%s %-12s 매출%s(%s%%) 영업%s(%s%%) %s' % (
            m['code'], m['name'][:10], m.get('rev'), m.get('revYoY'), m.get('op'), m.get('opYoY'), m['date']))

if __name__ == '__main__':
    main()
