#!/usr/bin/env python3
# 종목 딥다이브 수집: 분기·반기·사업보고서 원문(사업의 내용)에서
#  - 품목별 매출(누적→분기 차감), 품목별 판가(누적평균→분기 환산), 물량 지수(매출/판가)
#  - 생산능력·생산실적·가동률, 수주잔고
# 원문 접근: DART 뷰어(키 불필요) — rcpNo는 opendart list.json(키)으로 조회
# 결과: public/data/qdeep/{code}.json + index.json
import os, io, sys, json, time, zipfile, urllib.request, re, datetime
import xml.etree.ElementTree as ET

KEY = os.environ.get('DART_KEY', '')
BASE = 'https://opendart.fss.or.kr/api'
OUTDIR = 'public/data/qdeep'
MAXRUN = int(os.environ.get('MAXRUN', '10'))
REFRESH_DAYS = 25  # 분기마다 새 보고서 반영
PV = 1
START_YEAR = 2021
UA = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126 Safari/537.36'}
DEBUG = []

def fetch(url, timeout=40, referer=None):
    hd = dict(UA)
    if referer:
        hd['Referer'] = referer
    for i in range(3):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=hd), timeout=timeout) as r:
                return r.read()
        except Exception:
            time.sleep(1.5 * (i + 1))
    return b''

def jget(url):
    try:
        return json.loads(fetch(url).decode('utf-8'))
    except Exception:
        return {}

def tonum(s):
    s = str(s).replace(',', '').replace('△', '-').replace('(', '-').replace(')', '').strip()
    try:
        return float(s)
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

def filings(corp):
    """정기보고서 [(rcpNo, 'YYQn', cum_q)] — cum_q: 그 보고서 누적이 커버하는 분기 수(1,2,3,4)"""
    bgn = '%d0101' % START_YEAR
    out = []
    for page in (1, 2):
        d = jget('%s/list.json?crtfc_key=%s&corp_code=%s&pblntf_ty=A&bgn_de=%s&page_count=100&page_no=%d&last_reprt_at=Y'
                 % (BASE, KEY, corp, bgn, page))
        for it in (d.get('list') or []):
            nm = it.get('report_nm') or ''
            m = re.search(r'\((\d{4})\.(\d{2})\)', nm)
            if not m:
                continue
            y, mm = int(m.group(1)), int(m.group(2))
            if y < START_YEAR:
                continue
            if '사업보고서' in nm:
                q = 4
            elif '반기보고서' in nm:
                q = 2
            elif '분기보고서' in nm:
                q = 1 if mm == 3 else 3
            else:
                continue
            out.append((it['rcept_no'], '%02dQ%d' % (y % 100, q), q, y))
        if not (d.get('list') or []):
            break
        time.sleep(0.1)
    # 같은 (연,분기) 중 최신 rcpNo만
    best = {}
    for rcp, label, q, y in out:
        k = (y, q)
        if k not in best or rcp > best[k][0]:
            best[k] = (rcp, label, q, y)
    return [best[k] for k in sorted(best)]

def doc_tree(rcp):
    h = fetch('https://dart.fss.or.kr/dsaf001/main.do?rcpNo=%s' % rcp, 40).decode('utf-8', 'ignore')
    blocks = re.findall(r"node\d+\['text'\]\s*=\s*\"([^\"]*)\"[\s\S]{0,600}?node\d+\['dcmNo'\]\s*=\s*\"(\d+)\"[\s\S]{0,200}?node\d+\['eleId'\]\s*=\s*\"(\d+)\"[\s\S]{0,200}?node\d+\['offset'\]\s*=\s*\"(\d+)\"[\s\S]{0,200}?node\d+\['length'\]\s*=\s*\"(\d+)\"", h)
    return blocks

def viewer(rcp, dcm, ele, off, ln):
    u = ('https://dart.fss.or.kr/report/viewer.do?rcpNo=%s&dcmNo=%s&eleId=%s&offset=%s&length=%s&dtd=dart3.xsd'
         % (rcp, dcm, ele, off, ln))
    return fetch(u, 40, referer='https://dart.fss.or.kr/dsaf001/main.do?rcpNo=%s' % rcp).decode('utf-8', 'ignore')

def tables(h):
    out = []
    for t in re.findall(r'<TABLE[\s\S]*?</TABLE>', h, re.I):
        rows = []
        for tr in re.findall(r'<TR[\s\S]*?</TR>', t, re.I):
            cells = [re.sub(r'&nbsp;?', ' ', re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', c))).strip()
                     for c in re.findall(r'<T[DH][^>]*>([\s\S]*?)</T[DH]>', tr, re.I)]
            rows.append(cells)
        out.append(rows)
    return out

def unit_mult(h, pos):
    """표 앞 3000자에서 (단위: …) 탐지"""
    seg = h[max(0, pos - 3000):pos]
    if '백만원' in seg[-600:]:
        return 1e6
    if '천원' in seg[-600:]:
        return 1e3
    return 1.0

def parse_sales(h):
    """품목별 매출 누적: {품목: 원} — '매출유형/내수/수출/계' 형태 표"""
    out = {}
    for m in re.finditer(r'<TABLE[\s\S]*?</TABLE>', h, re.I):
        t = tables(m.group(0))[0]
        flat = ' '.join(' '.join(r) for r in t[:2])
        if not (('매출유형' in flat or '매출액' in flat) and any('품' in c for c in (t[0] if t else []))):
            continue
        mult = unit_mult(h, m.start())
        cur_item = None
        for r in t[1:]:
            if not r:
                continue
            first = r[0].replace(' ', '')
            joined = [c.replace(' ', '') for c in r]
            if first.startswith(('합계', '총계', '총합계')):
                cur_item = None  # 전사 합계 구간 — 품목으로 오귀속 방지
                continue
            if len(r) >= 3 and not re.fullmatch(r'[\d,.\-△() ]*', r[0]) and first not in ('내수', '수출', '계'):
                cur_item = r[0].strip()
            # '계' 행: 품목 합계 누적값(첫 숫자)
            if '계' in joined[:3] and cur_item:
                nums = [tonum(c) for c in r if tonum(c) is not None]
                if nums:
                    key = cur_item[:20]
                    if '합' not in key:
                        out[key] = nums[0] * mult
        if out:
            break
    return out

def parse_price(h):
    """품목별 판가(누적평균): {품목: (값, 단위문자)}"""
    out = {}
    for m in re.finditer(r'<TABLE[\s\S]*?</TABLE>', h, re.I):
        pos = m.start()
        seg = h[max(0, pos - 800):pos]
        um = re.search(r'단\s*위\s*[:：]\s*([^)＜<]{1,14})', seg)
        t = tables(m.group(0))[0]
        if not t or len(t) < 2:
            continue
        head = ' '.join(t[0])
        if not ('품' in head and ('기' in head or '분기' in head)):
            continue
        # 가격 표 추정: 행이 [품목, 숫자...]이고 근처에 '가격' 또는 단위가 원/…
        near = h[max(0, pos - 2500):pos]
        if '가격변동' not in near and '판매가격' not in near and '가격' not in near:
            continue
        for r in t[1:]:
            if len(r) >= 2 and tonum(r[0]) is None:
                v = tonum(r[1])
                if v is not None and v > 0:
                    out[r[0].strip()[:20]] = (v, (um.group(1).strip() if um else ''))
        if out:
            break
    return out

def parse_prod(h):
    """생산능력·생산실적·가동률(누적): {품목: {'cap':, 'act':, 'util':%}} — 헤더 열 위치 기반"""
    res = {}
    for m in re.finditer(r'<TABLE[\s\S]*?</TABLE>', h, re.I):
        t = tables(m.group(0))[0]
        if not t or len(t) < 2:
            continue
        head = [c.replace(' ', '') for c in t[0]]
        flat = ' '.join(head)
        if '가동률' not in flat and not ('생산능력' in flat and '생산실적' in flat):
            continue
        def hidx(word):
            return next((i for i, c in enumerate(head) if word in c), None)
        iu, ic, ia = hidx('가동률'), hidx('생산능력'), hidx('생산실적')
        ncol = len(head)
        for r in t[1:]:
            if not r or re.fullmatch(r'[\d,.\-△()% ]*', r[0] or ''):
                continue
            name = r[0].strip()[:20]
            if name.replace(' ', '') in ('계', '합계', '총계'):
                name = '전체'
            # rowspan으로 앞열이 병합된 행은 끝에서 정렬
            off = ncol - len(r)
            def cell(i):
                if i is None:
                    return None
                j = i - off
                return r[j] if 0 <= j < len(r) else None
            util = None
            cu = cell(iu)
            if cu:
                try:
                    util = float(re.sub(r'[%, ]', '', cu))
                except Exception:
                    util = None
            cap = tonum(cell(ic)) if ic is not None else None
            act = tonum(cell(ia)) if ia is not None else None
            if any(x is not None for x in (cap, act, util)):
                res[name] = {'cap': cap, 'act': act, 'util': util}
        if res:
            break
    return res

def parse_backlog(h):
    """수주잔고 합계(원): 수주상황 표의 '합계' 행 마지막 금액"""
    for m in re.finditer(r'<TABLE[\s\S]*?</TABLE>', h, re.I):
        t = tables(m.group(0))[0]
        if not t:
            continue
        flat = ' '.join(' '.join(r) for r in t[:2])
        if '수주잔고' not in flat and '수주총액' not in flat:
            continue
        mult = unit_mult(h, m.start())
        best = None
        for r in t[1:]:
            joined = [c.replace(' ', '') for c in r]
            nums = [tonum(c) for c in r if tonum(c) is not None]
            if nums and any(j in ('합계', '계', '총계') for j in joined[:2]):
                best = nums[-1] * mult
        if best is None:  # 합계행 없으면 모든 행 마지막 값 합
            s = 0
            for r in t[1:]:
                nums = [tonum(c) for c in r if tonum(c) is not None]
                if nums:
                    s += nums[-1]
            best = s * mult if s else None
        if best:
            return best
    return None

def contracts(corp):
    """수주 공시(단일판매·공급계약체결) 최근 3년: [{d,t,amt,ratio,party,until}]"""
    out = []
    bgn = (datetime.date.today() - datetime.timedelta(days=1095)).strftime('%Y%m%d')
    d = jget('%s/list.json?crtfc_key=%s&corp_code=%s&pblntf_ty=I&bgn_de=%s&page_count=100&last_reprt_at=Y'
             % (BASE, KEY, corp, bgn))
    for it in (d.get('list') or []):
        nm = it.get('report_nm') or ''
        if '공급계약' not in nm and '수주' not in nm:
            continue
        rcp = it['rcept_no']
        ent = {'d': '%s-%s-%s' % (it['rcept_dt'][:4], it['rcept_dt'][4:6], it['rcept_dt'][6:8]),
               't': re.sub(r'\s+', ' ', nm).strip(), 'rcp': rcp}
        try:
            # 거래소 공시는 원문 zip(document.xml API)으로 — 표 태그 구조 동일
            b = fetch('%s/document.xml?crtfc_key=%s&rcept_no=%s' % (BASE, KEY, rcp), 60)
            h = ''
            try:
                z = zipfile.ZipFile(io.BytesIO(b))
                for n in z.namelist():
                    raw = z.read(n)
                    for enc in ('utf-8', 'cp949'):
                        try:
                            h += raw.decode(enc)
                            break
                        except Exception:
                            continue
            except Exception:
                pass
            if h:
                rows = []
                for t in tables(h):
                    rows += t
                def find(*words):
                    for r in rows:
                        for i, c in enumerate(r):
                            cc = c.replace(' ', '')
                            if any(w in cc for w in words) and i + 1 < len(r):
                                for c2 in r[i + 1:]:
                                    if c2.strip():
                                        return c2.strip()
                    return None
                amt = tonum(find('계약금액', '공급계약금액'))
                if amt and amt > 1e6:
                    ent['amt'] = round(amt / 1e8, 1)  # 억원
                rt = find('매출액대비', '최근매출액대비')
                if rt:
                    m2 = re.search(r'[\d.]+', rt.replace(',', ''))
                    if m2:
                        ent['ratio'] = float(m2.group(0))
                ent['party'] = (find('계약상대방', '계약상대') or '')[:30]
                ent['until'] = (find('종료일') or '')[:10]
        except Exception:
            pass
        out.append(ent)
        time.sleep(0.3)
        if len(out) >= 30:
            break
    return out

def collect(code, name, corp):
    fl = filings(corp)
    if len(fl) < 4:
        return None
    cum = {}  # label -> {'sales':{item:원},'price':{item:(v,u)},'prod':[...],'backlog':원}
    for rcp, label, q, y in fl:
        tree = doc_tree(rcp)
        if not tree:
            continue
        sec = {}
        biz = None
        for txt, dcm, ele, off, ln in tree:
            tt = txt.replace(' ', '')
            if tt.endswith('사업의내용'):
                biz = (dcm, ele, off, ln)
            if '주요제품' in tt or ('제품및서비스' in tt):
                sec['prd'] = (dcm, ele, off, ln)
            elif '생산설비' in tt or '원재료및생산' in tt:
                sec['fac'] = (dcm, ele, off, ln)
            elif '매출및수주' in tt or ('수주상황' in tt) or (tt.startswith('4.매출') if tt else False):
                sec['sal'] = (dcm, ele, off, ln)
        if biz and ('sal' not in sec or 'prd' not in sec or 'fac' not in sec):
            # 구서식: 사업의 내용이 단일 섹션 — 전체를 각 파서에 사용
            for k in ('sal', 'prd', 'fac'):
                sec.setdefault(k, biz)
        slot = {}
        if 'sal' in sec:
            h = viewer(rcp, *sec['sal'])
            slot['sales'] = parse_sales(h)
            slot['backlog'] = parse_backlog(h)
        if 'prd' in sec:
            h = viewer(rcp, *sec['prd'])
            slot['price'] = parse_price(h)
            if not slot.get('sales'):
                slot['sales'] = parse_sales(h)
        if 'fac' in sec:
            h = viewer(rcp, *sec['fac'])
            slot['prod'] = parse_prod(h)
        cum[label] = slot
        time.sleep(0.4)
    if not cum:
        return None
    # 분기 차감: label 정렬(연도·분기), 연내 이전 누적과 차감
    labels = sorted(cum.keys())
    def prev_label(lb):
        y, q = int(lb[:2]), int(lb[-1])
        return '%02dQ%d' % (y, q - 1) if q > 1 else None
    items = sorted({it for lb in labels for it in (cum[lb].get('sales') or {})})
    pitems = sorted({it for lb in labels for it in (cum[lb].get('prod') or {})})
    quarters = []
    sales_q = {i: [] for i in items}
    price_q = {i: [] for i in items}
    vol_q = {i: [] for i in items}
    util_q = {i: [] for i in pitems}
    backlog = []
    for lb in labels:
        quarters.append('%s.%sQ' % (lb[:2], lb[-1]))
        pl = prev_label(lb)
        for it in items:
            c1 = (cum[lb].get('sales') or {}).get(it)
            c0 = (cum.get(pl, {}).get('sales') or {}).get(it) if pl else 0
            sq = (c1 - c0) if (c1 is not None and c0 is not None) else None
            sales_q[it].append(round(sq / 1e8, 1) if sq is not None else None)
            # 물량·판가: 누적물량 = 누적매출/누적평균판가, 분기 차감 [산출]
            p1 = ((cum[lb].get('price') or {}).get(it) or (None,))[0]
            p0 = ((cum.get(pl, {}).get('price') or {}).get(it) or (None,))[0] if pl else None
            v1 = (c1 / p1) if (c1 and p1) else None
            v0 = (c0 / p0) if (c0 and p0) else (0 if pl is None else None)
            vq = (v1 - v0) if (v1 is not None and v0 is not None) else None
            vol_q[it].append(round(vq / 1e6, 1) if vq is not None else None)  # 판가단위 kg 가정 → 천톤
            pq = (sq / vq) if (sq and vq and vq > 0) else (p1 if (lb.endswith('1') and p1) else None)
            price_q[it].append(round(pq, 1) if pq is not None else None)
        bl = cum[lb].get('backlog')
        backlog.append(round(bl / 1e8, 1) if bl else None)
        # 가동률: 누적 생산실적/능력 차감 → 분기 가동률
        for it in pitems:
            g1 = (cum[lb].get('prod') or {}).get(it) or {}
            g0 = (cum.get(pl, {}).get('prod') or {}).get(it) if pl else {'cap': 0, 'act': 0}
            u = None
            if g0 is not None and g1.get('cap') is not None and g1.get('act') is not None \
               and (g0.get('cap') is not None and g0.get('act') is not None):
                dc = g1['cap'] - (g0.get('cap') or 0)
                da = g1['act'] - (g0.get('act') or 0)
                if dc and dc > 0:
                    u = round(da / dc * 100, 1)
            if u is None and lb.endswith('1'):
                u = g1.get('util')
            util_q[it].append(u)
    # 판가 단위 표기
    punit = ''
    for lb in reversed(labels):
        for it, pv_ in (cum[lb].get('price') or {}).items():
            if pv_[1]:
                punit = pv_[1]
                break
        if punit:
            break
    return {'code': code, 'name': name, 'quarters': quarters, 'items': items,
            'sales': sales_q, 'price': price_q, 'vol': vol_q, 'backlog': backlog, 'util': util_q,
            'contracts': contracts(corp), 'punit': punit, 'pv': PV, 'gen': datetime.date.today().isoformat()}

def main():
    if not KEY:
        print('DART_KEY 필요'); sys.exit(1)
    targets = {}
    try:
        extra = json.load(open('qdeep_targets.json', encoding='utf-8'))
        for x in extra:
            targets[x['code']] = x['name']
    except Exception:
        pass
    try:
        sn = json.load(open('public/stocknotes.json', encoding='utf-8'))
        for g in sn['industries']:
            for s in g['stocks']:
                if re.fullmatch(r'\d{6}', s['code']):
                    targets.setdefault(s['code'], s['name'])
    except Exception as e:
        DEBUG.append('stocknotes 실패: %r' % e)
    os.makedirs(OUTDIR, exist_ok=True)
    cutoff = (datetime.date.today() - datetime.timedelta(days=REFRESH_DAYS)).isoformat()
    try:
        cmap = corp_map()
    except Exception as e:
        DEBUG.append('corp_map 실패: %r' % e)
        cmap = {}
    index, ran = {}, 0
    for code, name in targets.items():
        fp = '%s/%s.json' % (OUTDIR, code)
        try:
            old = json.load(open(fp, encoding='utf-8'))
            if old.get('pv') == PV and (old.get('gen') or '') >= cutoff:
                index[code] = name
                continue
        except Exception:
            pass
        if ran >= MAXRUN:
            if os.path.exists(fp):
                index[code] = name
            continue
        corp = cmap.get(code)
        if not corp:
            continue
        ran += 1
        try:
            r = collect(code, name, corp)
        except Exception as e:
            DEBUG.append('%s 예외: %r' % (code, str(e)[:60]))
            r = None
        if r and r.get('items'):
            json.dump(r, open(fp, 'w', encoding='utf-8'), ensure_ascii=False)
            index[code] = name
            print('%s %s OK 품목%d 분기%d' % (code, name, len(r['items']), len(r['quarters'])), file=sys.stderr)
        else:
            DEBUG.append('%s 품목 없음' % code)
    DEBUG.append('이번 실행 %d (한도 %d, 대상 %d)' % (ran, MAXRUN, len(targets)))
    json.dump({'updated': time.strftime('%Y-%m-%d %H:%M'), 'debug': DEBUG, 'codes': index},
              open('%s/index.json' % OUTDIR, 'w', encoding='utf-8'), ensure_ascii=False)
    print('완료:', DEBUG)

if __name__ == '__main__':
    try:
        main()
    except Exception:
        import traceback
        os.makedirs('public/data', exist_ok=True)
        json.dump({'error': traceback.format_exc(), 'ts': time.strftime('%Y-%m-%d %H:%M')},
                  open('public/data/qdeep_error.json', 'w', encoding='utf-8'), ensure_ascii=False)
        raise
