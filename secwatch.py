# -*- coding: utf-8 -*-
"""
미국 공시(SEC EDGAR) 수집기 — 키 불필요, GitHub Actions에서 그대로 동작.

SEC는 자동 접근 도구에 '이름 + 연락 이메일' 형식의 User-Agent를 요구한다.
형식이 틀리면 Akamai가 403 "Undeclared Automated Tool"로 끊는다.
연락처는 공개 저장소에 적지 않고 SEC_UA 시크릿으로 받는다.

출력
  public/data/sec/<티커>.json   종목별 제출 이력
  public/data/sec/index.json    목록·갱신시각·분류체계 연결
  public/data/sec/fts.json      키워드 전문검색 결과
"""
import os, json, time, re, gzip, urllib.request, urllib.error, urllib.parse, pathlib, datetime

UA   = os.environ.get('SEC_UA', '').strip()
OUT  = pathlib.Path('public/data/sec')
TAX  = pathlib.Path('public/data/sec_tax.json')
MAX  = int(os.environ.get('MAXRUN', '120'))        # 분 단위 예산
GAP  = 0.15                                        # SEC 권장 초당 10회 이하
KEEP = 80                                          # 종목당 보관 제출 건수
VER  = 1

# 투자 판단에 쓰는 보고서만 남긴다(내부자 Form 4 등 잡음 제외)
FORMS = {'10-K','10-Q','8-K','20-F','6-K','40-F','S-1','S-3','424B5','424B2',
         'DEF 14A','SC 13D','SC 13G','11-K','10-K/A','10-Q/A','8-K/A'}

class Blocked(Exception): pass

def get(url, tries=3):
    for i in range(tries):
        try:
            r = urllib.request.Request(url, headers={
                'User-Agent': UA, 'Accept-Encoding': 'gzip, deflate'})
            with urllib.request.urlopen(r, timeout=40) as f:
                b = f.read()
                if f.headers.get('Content-Encoding') == 'gzip': b = gzip.decompress(b)
                return b.decode('utf-8', 'ignore')
        except urllib.error.HTTPError as e:
            if e.code == 403: raise Blocked('SEC 403 — User-Agent 형식 확인 필요')
            if e.code == 404: return ''
            time.sleep(1.5 * (i + 1))
        except Exception:
            time.sleep(1.5 * (i + 1))
    return ''

def tickers_from_tax(tax):
    """분류체계에서 미국 상장 티커와 그 위치(섹터/그룹/세부단계)를 뽑는다"""
    out = {}
    for sec, v in tax['sectors'].items():
        for g in v['groups']:
            for st in g['stages']:
                for c in st['co']:
                    if c.get('notus'): continue
                    out.setdefault(c['t'], []).append(f"{sec}/{g['id']}/{st['id']}")
    return out

def filings(cik):
    j = get(f'https://data.sec.gov/submissions/CIK{cik}.json')
    if not j: return None, []
    d = json.loads(j)
    R = d.get('filings', {}).get('recent', {})
    n = len(R.get('form', []))
    rows = []
    for i in range(n):
        f = R['form'][i]
        if f not in FORMS: continue
        acc = R['accessionNumber'][i]
        rows.append({
            'f': f,
            'd': R['filingDate'][i],
            'rd': R.get('reportDate', [''] * n)[i],
            'acc': acc,
            'u': f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{acc.replace('-','')}/{R['primaryDocument'][i]}",
            'items': (R.get('items', [''] * n)[i] or '')[:60],
        })
        if len(rows) >= KEEP: break
    meta = {'name': d.get('name'), 'sic': d.get('sicDescription'),
            'ex': (d.get('exchanges') or [''])[0], 'fy': d.get('fiscalYearEnd')}
    return meta, rows

def fulltext(q, forms='10-K,10-Q,20-F', days=400):
    """EDGAR 전문검색 — 키워드를 본문에 쓴 기업을 역추적"""
    end = datetime.date.today()
    beg = end - datetime.timedelta(days=days)
    u = ('https://efts.sec.gov/LATEST/search-index?q=' + urllib.parse.quote(f'"{q}"') +
         f'&forms={urllib.parse.quote(forms)}&dateRange=custom'
         f'&startdt={beg}&enddt={end}')
    j = get(u)
    if not j: return {'q': q, 'n': 0, 'hits': []}
    d = json.loads(j)
    hits = []
    for h in d.get('hits', {}).get('hits', [])[:30]:
        s = h.get('_source', {})
        nm = (s.get('display_names') or [''])[0]
        m = re.search(r'\(([A-Z\.\-]{1,6})\)\s*\(CIK (\d{10})\)', nm)
        hits.append({'n': re.sub(r'\s*\(.*', '', nm).strip(),
                     't': m.group(1) if m else '',
                     'cik': m.group(2) if m else '',
                     'd': s.get('file_date', ''), 'f': s.get('file_type', '')})
    return {'q': q, 'n': d.get('hits', {}).get('total', {}).get('value', 0), 'hits': hits}

def main():
    if not UA or '@' not in UA:
        print('SEC_UA 시크릿이 없거나 형식이 틀립니다 — "이름 이메일@도메인" 형태여야 합니다'); return
    t0 = time.time()
    tax = json.loads(TAX.read_text(encoding='utf-8'))
    tmap = tickers_from_tax(tax)
    cm = tax['cik']
    OUT.mkdir(parents=True, exist_ok=True)
    idx_p = OUT / 'index.json'
    idx = json.loads(idx_p.read_text(encoding='utf-8')) if idx_p.exists() else {'co': {}}
    if idx.get('ver') != VER: idx = {'co': {}}          # 형식 올리면 전량 재수집

    todo = sorted(tmap, key=lambda t: idx['co'].get(t, {}).get('at', ''))
    done = fail = 0
    for t in todo:
        if (time.time() - t0) / 60 > MAX: print('시간 예산 소진'); break
        cik = cm.get(t, {}).get('cik')
        if not cik: continue
        try:
            meta, rows = filings(cik)
        except Blocked as e:
            print('중단:', e); break
        time.sleep(GAP)
        if not rows: fail += 1; continue
        (OUT / f'{t}.json').write_text(json.dumps(
            {'t': t, 'cik': cik, 'meta': meta, 'nodes': tmap[t], 'rows': rows,
             'at': time.strftime('%Y-%m-%d %H:%M')}, ensure_ascii=False), encoding='utf-8')
        idx['co'][t] = {'n': meta['name'], 'cik': cik, 'nodes': tmap[t],
                        'last': rows[0]['d'], 'lastf': rows[0]['f'], 'n_f': len(rows),
                        'at': time.strftime('%Y-%m-%d %H:%M')}
        done += 1

    # 전문검색 — 분류체계가 들고 있는 키워드
    fts = {}
    for q in tax.get('fts', [])[:25]:
        if (time.time() - t0) / 60 > MAX: break
        try: fts[q] = fulltext(q)
        except Blocked: break
        time.sleep(GAP)
    if fts: (OUT / 'fts.json').write_text(json.dumps(
        {'at': time.strftime('%Y-%m-%d %H:%M'), 'q': fts}, ensure_ascii=False), encoding='utf-8')

    idx['ver'] = VER
    idx['updated'] = time.strftime('%Y-%m-%d %H:%M')
    idx['n'] = len(idx['co'])
    idx_p.write_text(json.dumps(idx, ensure_ascii=False), encoding='utf-8')
    print(f'수집 {done}건 · 실패 {fail}건 · 전문검색 {len(fts)}건 · 누적 {len(idx["co"])}종목 '
          f'· {int(time.time()-t0)}초')

if __name__ == '__main__':
    main()
