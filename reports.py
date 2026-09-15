#!/usr/bin/env python3
# 증권사 리포트 수집 — 한경컨센서스 + 네이버 리서치(신형 API) + 증권사 홈페이지 직접 수집(BROKERS) + 해외 리서치(번역)
# 최근 7일 발간분, PDF 페이지수·애널리스트 추출, 매일 갱신
# 해외: GS·MS·JPM·UBS(구글뉴스 site: 필터)·ING THINK·McKinsey 공개 리서치 — 제목·요약 한국어 번역
import json, re, time, datetime, urllib.request, urllib.parse, urllib.error, sys, io, os
import email.utils

OUT = 'public/data/reports.json'
UA = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
class _Dbg(list):   # DEBUG 줄을 즉시 stdout에도 찍어 Actions 로그에서 진행 위치를 볼 수 있게
    def append(self, s):
        print(s, flush=True); super().append(s)
DEBUG = _Dbg()
T0 = time.time()
PDF_BUDGET_SEC = 480   # 페이지수 측정(PDF 다운로드) 총 예산 — 넘으면 나머지는 다음 실행에서
TODAY = datetime.date.today()
CUTOFF = TODAY - datetime.timedelta(days=7)
MAX_PDF_DL = 100  # 실행당 페이지수 측정 최대 건수

def get(url, timeout=25, binary=False, encoding='euc-kr'):
    r = urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout).read()
    return r if binary else r.decode(encoding, 'ignore')

def parse_date(s):
    m = re.fullmatch(r'(\d{2})\.(\d{2})\.(\d{2})', s.strip())
    return '20%s-%s-%s' % (m.group(1), m.group(2), m.group(3)) if m else None

def rows_of(html):
    return re.findall(r'<tr>([\s\S]*?)</tr>', html)

CONS = 'https://consensus.hankyung.com'
def strip_html(s):
    return re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', s)).strip()

def scrape(kind):
    """kind: 'industry' | 'company' — 한경컨센서스(consensus.hankyung.com) 목록.
    2026-09-10 네이버 금융 리서치 페이지가 신형(Next.js)으로 바뀌어 기존 파싱이 0건 → 소스 교체.
    행: 작성일 | 제목(a href=/analysis/downpdf?report_idx=N) | 투자의견 | 작성자 | 제공출처 | 차트 | 첨부.
    기업(CO)은 차트 링크 business_code=6자리, 산업(IN)은 제목 [대괄호]에서 분류 추출."""
    out = []
    rt = 'IN' if kind == 'industry' else 'CO'
    for page in range(1, 12):
        url = ('%s/analysis/list?sdate=%s&edate=%s&now_page=%d&search_text=&pagenum=80&report_type=%s'
               % (CONS, CUTOFF.isoformat(), TODAY.isoformat(), page, rt))
        try:
            h = get(url, encoding='utf-8')
        except Exception as e:
            DEBUG.append('%s p%d: %r' % (kind, page, e))
            break
        got_old = False
        n = 0
        for r in re.findall(r'<tr[^>]*>([\s\S]*?)</tr>', h):
            m = re.search(r'href="/analysis/downpdf\?report_idx=(\d+)"[^>]*>([^<]+)</a>', r)
            dt = re.search(r'>\s*(\d{4}-\d{2}-\d{2})\s*<', r)
            if not (m and dt):
                continue
            d = dt.group(1)
            if d < CUTOFF.isoformat():
                got_old = True
                continue
            tds = [strip_html(x) for x in re.findall(r'<td[^>]*>([\s\S]*?)</td>', r)]
            # 열 순서: 작성일, 제목, (목표가), 투자의견, 작성자, 제공출처, 차트, 첨부
            broker = ''
            for t in tds:
                if re.search(r'(증권|투자증권|리서치|IR협의회|자산운용|경제연구|캐피탈|Securities)$', t) or t.endswith('증권'):
                    broker = t
            if not broker and len(tds) >= 6:
                broker = tds[5] if kind == 'company' else tds[4]
            rid = m.group(1)
            title = strip_html(m.group(2))
            item = {'t': title, 'b': broker, 'd': d, 'pdf': '%s/analysis/downpdf?report_idx=%s' % (CONS, rid), 'v': 0, 'src': '한경컨센서스'}
            if kind == 'industry':
                cat = re.match(r'\s*\[([^\]]{1,20})\]', title)
                c = cat.group(1).strip() if cat else ''
                # 대괄호가 업종명일 때만(짧고 공백 없는 한글/영문/슬래시) 채택 — "[AI 홍수 속 살아남기]" 같은 제목 장식은 기타
                item['cat'] = c if (c and len(c) <= 12 and re.fullmatch(r'[가-힣A-Za-z0-9/·&]+', c)) else '기타'
                ic = re.search(r'industry_code=(\d+)', r)
                if ic: item['icode'] = ic.group(1)
            else:
                st = re.search(r'business_code=([0-9A-Z]{6})', r) or re.search(r'stockcd=([0-9A-Z]{6})', r)
                nm = re.match(r'\s*(.+?)\s*\(\s*([0-9A-Z]{6})\s*\)', title)
                if st or nm:
                    item['code'] = (st.group(1) if st else nm.group(2))
                    item['name'] = nm.group(1).strip() if nm else ''
                else:
                    continue
            out.append(item)
            n += 1
        if got_old or n == 0:
            break
        time.sleep(0.5)
    # 중복 제거 (PDF 주소 + 제목·증권사·날짜 조합)
    seen, uniq = set(), []
    for x in out:
        k1 = x['pdf']
        k2 = (x['t'], x['b'], x['d'], x.get('code', ''))
        if k1 in seen or k2 in seen:
            continue
        seen.add(k1); seen.add(k2)
        uniq.append(x)
    DEBUG.append('%s %d건' % (kind, len(uniq)))
    return uniq

# ───────── 증권사 직접 수집 (2026-09-16) ─────────
# 하우스별 설정만 추가하면 되는 설정형 수집기. 실패는 그 하우스만 0건 + DEBUG, 나머지는 계속.
# 검증(9/16 Chrome, 비로그인 fetch): 삼성·키움·유안타·대신·하나·현대차 = 목록·PDF 공개 / KB = kbthink 요약 HTML만(PDF는 rc.kbsec.com 로그인)
# 유진(igii412.do 목록 0건·로그인 필요) / 미래에셋·신한·교보·DB·NH·한국투자 = 보류
BROKER_HDR = dict(UA, **{'Accept': 'text/html,application/json;q=0.9,*/*;q=0.8', 'Accept-Language': 'ko-KR,ko;q=0.9'})

def _get_text(url, data=None, timeout=20, enc=None):
    """GET/POST → (status, text). 문자셋은 헤더→meta→enc→utf-8 순."""
    req = urllib.request.Request(url, data=data.encode() if isinstance(data, str) else data, headers=BROKER_HDR)
    if data is not None:
        req.add_header('Content-Type', 'application/x-www-form-urlencoded')
    try:
        r = urllib.request.urlopen(req, timeout=timeout)
        b = r.read()
        ct = r.headers.get('Content-Type', '') or ''
        st = r.status
    except urllib.error.HTTPError as e:
        b = e.read()[:2000] if hasattr(e, 'read') else b''
        return e.code, b.decode('utf-8', 'ignore')
    m = re.search(r'charset=([\w-]+)', ct, re.I) or re.search(rb'charset=["\']?([\w-]+)', b[:3000], re.I)
    cs = (m.group(1) if isinstance(m.group(1), str) else m.group(1).decode()) if m else (enc or 'utf-8')
    try:
        return st, b.decode(cs, 'ignore')
    except Exception:
        return st, b.decode('utf-8', 'ignore')

def _unesc(s):
    return (s or '').replace('&amp;', '&').replace('&#39;', "'").replace('&quot;', '"').replace('&lt;', '<').replace('&gt;', '>').replace('&nbsp;', ' ')

def _date_norm(s):
    d = re.sub(r'[^0-9]', '', str(s or ''))[:8]
    if len(d) == 8:
        return '%s-%s-%s' % (d[:4], d[4:6], d[6:8])
    if len(d) == 6:
        return '20%s-%s-%s' % (d[:2], d[2:4], d[4:6])
    return None

_NAME2CODE = None
_CODE2NAME = None
def name_code_maps():
    """products.json(2,700여 종목)로 종목명↔코드 — 대신처럼 제목에 코드가 없는 하우스용."""
    global _NAME2CODE, _CODE2NAME
    if _NAME2CODE is None:
        _NAME2CODE, _CODE2NAME = {}, {}
        try:
            pm = json.load(open('public/data/products.json', encoding='utf-8')).get('map') or {}
            for c, v in pm.items():
                n = (v.get('n') if isinstance(v, dict) else None) or ''
                if n:
                    _CODE2NAME[c] = n
                    _NAME2CODE[re.sub(r'[\s㈜()]', '', n)] = c
        except Exception as e:
            DEBUG.append('products.json 종목명 맵 실패: %r' % e)
    return _NAME2CODE, _CODE2NAME

def _cat_of(title, catre=None):
    t = title.strip()
    if catre:
        m = re.search(catre, t)
        if m and m.group(1).strip():
            c = m.group(1).strip()
            if len(c) <= 14:
                return c
    m = re.match(r'\s*\[([^\]]{1,20})\]', t)
    if m:
        c = m.group(1).strip()
        if len(c) <= 12 and re.fullmatch(r'[가-힣A-Za-z0-9/·&\s]+', c):
            return c.replace(' ', '')
    return '기타'

# 필드 정규식은 행(row) 안에서 search. 값 대체: {pdf}{seq}{cd}{gb} 등 named group.
BROKERS = [
    {'name': '삼성증권', 'kind': 'both', 'enc': 'utf-8',
     'list': 'https://www.samsungpop.com/sscommon/jsp/search/research/research.jsp?GUBUN=all&startCount={p}&TOTALVIEWCOUNT=100',
     'pages': [0, 100, 200],
     'row': r"openPDFResizePreview\('(?P<pdf>/common\.do\?cmd=down[^']+\.pdf)','(?P<title>[^']*)','[^']*','(?P<date>\d{4}\.\d{2}\.\d{2})'",
     'pdf': 'https://www.samsungpop.com{pdf}',
     'kindon': 'pdf', 'kindre': {'company': r'fileName=2010/', 'industry': r'fileName=2020/', 'skip': r'fileName='},   # 폴더코드 2010=기업, 2020=산업, 나머지(전략·시황·경제)는 제외
     'title_strip': r'^\([^)]{1,30}\)\s*',           # "(애널리스트)" 접두 제거
     'catre': r'^([가-힣A-Za-z0-9/·& ]{1,14}?)\s*[\(\-:]'},
    {'name': '키움증권', 'kind': 'company', 'json': 'researchList', 'method': 'POST',
     'list': 'https://bbn.kiwoom.com/research/SResearchCRListAjax', 'body': 'pageNo={p}&stdate={cutoff8}&eddate={today8}&f_keyField=&f_key=',
     'pages': [1, 2, 3], 'f': {'title': 'titl', 'date': 'makeDt', 'seq': 'sqno', 'code': 'relItemList', 'cat': 'tpobNm', 'an': 'workId'},
     'pdf': 'https://bbn.kiwoom.com/rfCR{seq}'},
    {'name': '키움증권', 'kind': 'industry', 'json': 'researchList', 'method': 'POST',
     'list': 'https://bbn.kiwoom.com/research/SResearchCIListAjax', 'body': 'pageNo={p}&stdate={cutoff8}&eddate={today8}&f_keyField=&f_key=',
     'pages': [1, 2, 3], 'f': {'title': 'titl', 'date': 'makeDt', 'seq': 'sqno', 'cat': 'tpobNm', 'an': 'workId'},
     'pdf': 'https://bbn.kiwoom.com/rfCI{seq}'},
    {'name': '키움증권', 'kind': 'company', 'json': 'researchList', 'method': 'POST', 'tag': '스팟노트',
     'list': 'https://bbn.kiwoom.com/research/SResearchSNListAjax', 'body': 'pageNo={p}&stdate={cutoff8}&eddate={today8}&f_keyField=&f_key=',
     'pages': [1, 2], 'f': {'title': 'titl', 'date': 'makeDt', 'seq': 'sqno', 'code': 'relItemList', 'cat': 'tpobNm', 'an': 'workId'},
     'pdf': 'https://bbn.kiwoom.com/rfSN{seq}'},
    {'name': '유안타증권', 'kind': 'company',
     'list': 'https://www.myasset.com/myasset/research/rs_list/rs_list.cmd?cd006=&cd007=RE01&cd008=&page={p}&pgCnt=30', 'pages': [1, 2],
     'row': r'<tr class="js-moveRS">[\s\S]*?</tr>',
     'f': {'date': r'<td>\s*(\d{4}/\d{2}/\d{2})\s*</td>', 'code': r'data-jongcode="\((\w{6})\)"', 'name': r'js-jongname[^>]*>([^<]+)<',
           'title': r'cmd-type="view"[^>]*>\s*([^<]+?)\s*<', 'pdf': r"cmd-type='download' data-seq='([^']+)'"},
     'pdf': 'https://file.myasset.com/sitemanager/upload/{pdf}'},
    {'name': '유안타증권', 'kind': 'industry',
     'list': 'https://www.myasset.com/myasset/research/rs_list/rs_list.cmd?cd006=&cd007=RE02&cd008=&page={p}&pgCnt=30', 'pages': [1, 2],
     'row': r'<tr class="js-moveRS">[\s\S]*?</tr>',
     'f': {'date': r'<td>\s*(\d{4}/\d{2}/\d{2})\s*</td>', 'title': r'cmd-type="view"[^>]*>\s*([^<]+?)\s*<', 'pdf': r"cmd-type='download' data-seq='([^']+)'"},
     'pdf': 'https://file.myasset.com/sitemanager/upload/{pdf}', 'catre': r'^([가-힣A-Za-z0-9/·& ]{1,12}?)\s*[\-–:(\[]'},
    {'name': '대신증권', 'kind': 'both',
     'list': 'https://money2.daishin.com/E5/ResearchCenter/Work/Research_BasicList.aspx?pr_code=4&page={p}', 'pages': [1, 2, 3],
     'row': r'<tr>\s*<td\s+class="first">[\s\S]*?</tr>',
     'f': {'date': r'(\d{4}-\d{2}-\d{2})', 'title': r'lkbtnRead_\d+"[^>]*>([^<]+)<', 'pdf': r'filedownload\.aspx\?gubun=0&(?:amp;)?rowid=(\d+)'},
     'pdf': 'https://money2.daishin.com/e5/Pagelet/Board/Research/filedownload.aspx?gubun=0&rowid={pdf}',
     'title_strip': r'^\[대신증권[^\]]*\]\s*(\[[^\]]{1,25}\]\s*)?',
     'kindon': 'title', 'kindre': {'industry': r'\[(Industry|산업|월보|Issue\s*&\s*News|Sector)', 'company': r'\[(Company|Issue Comment|\dQ\d\d Preview|Earnings)'},
     'namere': r'\]\s*([가-힣A-Za-z0-9&]+)\s*:', 'catre': r'^([가-힣A-Za-z0-9/·&]{1,12})\s*[:,\-]'},
    {'name': '하나증권', 'kind': 'company',
     'list': 'https://www.hanaw.com/main/research/research/list.cmd?pid=3&cid=2&curPage={p}', 'pages': [1, 2, 3, 4],
     'row': r'class="more_btn title"[^>]*id="\d+_\d+">(?P<title>[^<]*)</a>(?:(?!more_btn title)[\s\S]){0,800}?class="txtbasic">(?P<date>\d{4}\.\d{2}\.\d{2})(?:(?!more_btn title)[\s\S]){0,8000}?href="(?P<pdf>/main/research/research/download\.cmd\?bbsSeq=\d+[^"]*)"',
     'pdf': 'https://www.hanaw.com{pdf}'},
    {'name': '하나증권', 'kind': 'industry',
     'list': 'https://www.hanaw.com/main/research/research/list.cmd?pid=3&cid=1&curPage={p}', 'pages': [1, 2, 3],
     'row': r'class="more_btn title"[^>]*id="\d+_\d+">(?P<title>[^<]*)</a>(?:(?!more_btn title)[\s\S]){0,800}?class="txtbasic">(?P<date>\d{4}\.\d{2}\.\d{2})(?:(?!more_btn title)[\s\S]){0,8000}?href="(?P<pdf>/main/research/research/download\.cmd\?bbsSeq=\d+[^"]*)"',
     'pdf': 'https://www.hanaw.com{pdf}', 'catre': r'^\[?([가-힣A-Za-z0-9/·&]{1,12})[\]\s]*[:\-–(]'},
    {'name': '현대차증권', 'kind': 'both', 'json': 'data_list', 'method': 'POST',
     'list': 'https://www.hmsec.com/research/research_list_ajax.do?Menu_category=2', 'body': 'curPage={p}', 'pages': [1, 2, 3, 4],
     'f': {'title': 'SUBJECT', 'date': 'REG_DATE', 'pdf': 'UPLOAD_FILE1', 'menu': 'MENU_CODE', 'an': 'NAME'},
     'pdf': 'https://www.hmsec.com/documents/research/{pdf}', 'kindfield': ('menu', {'201': 'company', '202': 'industry'}),
     'catre': r'^([가-힣A-Za-z0-9/·&]{1,12})\s*-'},
    {'name': 'KB증권', 'kind': 'both', 'html': True,   # PDF는 rc.kbsec.com 로그인 전용 → kbthink 요약 페이지 링크만
     'list': 'https://kbthink.com/investment/company-industry.html?pageNo={p}&sort=recent', 'pages': [1, 2, 3],
     'row': r'<a href="(?P<pdf>/securities-view\.html\?docId=(?P<date>\d{8})\d*K)"[^>]*class="list-comp type-stock">(?:(?!list-comp type-stock)[\s\S]){0,1500}?title="(?P<title>[^"]*)"',
     'pdf': 'https://kbthink.com{pdf}', 'title_strip': r'\s*주가전망\s*$', 'catre': r'^([가-힣A-Za-z0-9/·&]{1,12})\s*$'},
]

def scrape_broker(cfg, probe=False):
    """설정 1건 수집. probe=True면 상태·바이트·행 수만 DEBUG에 남기고 항목은 만들지 않음."""
    name = cfg['name']; out = []; tag = cfg.get('tag') or cfg['kind']
    n2c, c2n = name_code_maps()
    for p in cfg['pages']:
        url = cfg['list'].format(p=p)
        body = cfg.get('body').format(p=p, cutoff8=CUTOFF.strftime('%Y%m%d'), today8=TODAY.strftime('%Y%m%d')) if cfg.get('body') else None
        try:
            st, h = _get_text(url, data=body, enc=cfg.get('enc'))
        except Exception as e:
            DEBUG.append('%s/%s p%s: %r' % (name, tag, p, e)); break
        if st != 200 or not h:
            DEBUG.append('%s/%s p%s: HTTP %s %s' % (name, tag, p, st, re.sub(r'\s+', ' ', h[:200]))); break
        rows = []
        if cfg.get('json'):
            try:
                j = json.loads(h.strip())
                lst = j
                for k in cfg['json'].split('.'):
                    lst = lst.get(k) if isinstance(lst, dict) else None
                rows = lst or []
            except Exception as e:
                DEBUG.append('%s/%s p%s: JSON 아님 %s' % (name, tag, p, re.sub(r'\s+', ' ', h[:200]))); break
        else:
            rows = list(re.finditer(cfg['row'], h))
        if probe:
            npdf = len(re.findall(r'\.pdf', h, re.I)); nd = len(re.findall(r'20\d\d[.\-/]\d\d[.\-/]\d\d', h))
            DEBUG.append('탐사 %s/%s p%s: HTTP %s %d바이트 행%d pdf%d 날짜%d' % (name, tag, p, st, len(h), len(rows), npdf, nd))
            break
        got_old = False; n = 0
        for r in rows:
            g = {}
            if cfg.get('json'):
                for k, fk in cfg['f'].items():
                    v = r.get(fk)
                    g[k] = '' if v is None else str(v)
            else:
                g = {k: (v or '') for k, v in r.groupdict().items()} if r.groupdict() else {}
                for k, rx in (cfg.get('f') or {}).items():
                    m = re.search(rx, r.group(0))
                    g[k] = m.group(1) if m else ''
            for k in list(g): g[k] = _unesc(g[k]).strip()
            d = _date_norm(g.get('date'))
            title = strip_html(g.get('title') or '')
            if cfg.get('title_strip'):
                title = re.sub(cfg['title_strip'], '', title).strip()
            if not (d and title):
                continue
            if d < CUTOFF.isoformat():
                got_old = True; continue
            if d > TODAY.isoformat():
                d = TODAY.isoformat()
            try:
                pdf = cfg['pdf'].format(**g)
            except KeyError:
                pdf = ''
            if not pdf or ('{pdf}' in cfg['pdf'] and not g.get('pdf')) or ('{seq}' in cfg['pdf'] and not g.get('seq')):
                continue
            # kind 판정
            kind = cfg['kind']
            if cfg.get('kindre'):   # kindon: 'pdf'(폴더코드 등) | 'title'(원제목 태그) 에 정규식 적용, 못 정하면 both
                kind = 'both'; target = pdf if cfg.get('kindon') == 'pdf' else (g.get('title') or title)
                for kk, rx in cfg['kindre'].items():
                    if re.search(rx, target):
                        kind = kk; break
            if cfg.get('kindfield'):
                fk, mp = cfg['kindfield']; kind = mp.get(g.get(fk, ''))
            code = re.sub(r'[^0-9A-Z]', '', (g.get('code') or '').split('|')[0].split(',')[0])[:6]
            if not re.fullmatch(r'[0-9A-Z]{6}', code or ''):
                m = re.search(r'\(?\b(\d{6})\b', title)
                code = m.group(1) if m else ''
            nm = g.get('name') or ''
            if not nm:
                mm = re.match(r'\s*(.+?)\s*\(\s*[0-9A-Z]{6}', title)
                if mm: nm = mm.group(1).strip()
                elif cfg.get('namere'):
                    mm = re.search(cfg['namere'], g.get('title') or title)
                    if mm: nm = mm.group(1).strip()
            if not code and nm and n2c.get(re.sub(r'[\s㈜()]', '', nm)):
                code = n2c[re.sub(r'[\s㈜()]', '', nm)]
            if code and not nm:
                nm = c2n.get(code, '')
            if kind is None or kind == 'both':
                kind = 'company' if (code or (nm and cfg.get('namere'))) else 'industry'
            if kind not in ('company', 'industry'):
                continue
            item = {'t': title, 'b': name, 'd': d, 'pdf': pdf, 'v': 0, 'src': name}
            if cfg.get('html'): item['html'] = True
            if g.get('an'):
                an = [a for a in re.split(r'[,/·]', g['an']) if a.strip()][:4]
                if an: item['an'] = [a.strip() for a in an]
            item['kind'] = kind
            if kind == 'company':
                if not (code or nm):
                    continue   # 코드·종목명 모두 없으면 제외
                item['code'] = code; item['name'] = nm or code   # 코드 미확인(products.json에 없는 종목)이면 code=''
                if nm and code not in title and nm not in title:
                    item['t'] = '%s(%s) %s' % (nm, code, title)
            else:
                c = (g.get('cat') or '').strip()
                item['cat'] = c if (c and len(c) <= 12) else _cat_of(title, cfg.get('catre'))
            out.append(item); n += 1
        if got_old or n == 0:
            break
        time.sleep(0.4)
    DEBUG.append('%s/%s %d건' % (name, tag, len(out)))
    return out

def scrape_brokers(probe=False):
    ind, cmp_ = [], []
    for cfg in BROKERS:
        try:
            items = scrape_broker(cfg, probe=probe)
        except Exception as e:
            DEBUG.append('%s/%s 예외 %r' % (cfg['name'], cfg.get('tag') or cfg['kind'], e)); continue
        for x in items:
            (cmp_ if x.pop('kind', None) == 'company' else ind).append(x)
    return ind, cmp_

def _naver_pick(x, *names):
    for k, v in x.items():
        if any(re.search(n, k, re.I) for n in names) and v not in (None, ''):
            return v
    return None

def _naver_pdf_in(obj):
    """dict/list 어디에든 있는 .pdf URL(또는 stock.pstatic.net 링크) 1개."""
    stack = [obj]
    while stack:
        x = stack.pop()
        if isinstance(x, str):
            if re.search(r'\.pdf(\?|$)', x, re.I) or 'stock-research' in x:
                return x
        elif isinstance(x, dict):
            stack.extend(x.values())
        elif isinstance(x, list):
            stack.extend(x)
    return None

def scrape_naver(kind):
    """네이버 신형 리서치 — m.stock.naver.com/api/research/{industry|company}?page=N&pageSize=50 (9/15 Actions에서 JSON 확인:
    researchCategory·category·researchId·title·brokerName·writeDate…; 목록에는 PDF 링크가 없어 상세 API 후보에서 찾는다).
    실패하면 [] + DEBUG(진단). 상세 호출은 kind당 최대 NAVER_DETAIL_MAX건."""
    cat = 'industry' if kind == 'industry' else 'company'
    out = []; lst = []
    for page in (1, 2, 3):
        u = 'https://m.stock.naver.com/api/research/%s?page=%d&pageSize=50' % (cat, page)
        try:
            raw = urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=20).read().decode('utf-8', 'ignore')
            j = json.loads(raw)
        except Exception as e:
            DEBUG.append('naver %s p%d → %s' % (cat, page, repr(e)[:80])); break
        arr = j if isinstance(j, list) else None
        if arr is None and isinstance(j, dict):
            for v in j.values():
                if isinstance(v, list) and v and isinstance(v[0], dict):
                    arr = v; break
        if not arr:
            DEBUG.append('naver %s p%d → 목록 없음: %s' % (cat, page, re.sub(r'\s+', ' ', raw[:160]))); break
        if page == 1:
            DEBUG.append('naver %s 목록 키: %s' % (cat, list(arr[0].keys())[:16]))
        old = False
        for x in arr:
            d = _naver_pick(x, 'writeDate', 'date', 'regDate', 'createdAt')
            ds = re.sub(r'[^0-9]', '', str(d or ''))[:8]
            if len(ds) != 8:
                continue
            ds = '%s-%s-%s' % (ds[:4], ds[4:6], ds[6:8])
            if ds < CUTOFF.isoformat():
                old = True; continue
            x['_d'] = ds; lst.append(x)
        if old:
            break
        time.sleep(0.3)
    detail_n = 0; detail_ok = 0
    for x in lst:
        title = _naver_pick(x, '^title$', 'subject', 'title')
        rid = _naver_pick(x, 'researchId', '^id$', 'seq')
        if not (title and rid):
            continue
        pdf = _naver_pdf_in({k: v for k, v in x.items() if k != '_d'})
        if not pdf and detail_n < NAVER_DETAIL_MAX:
            detail_n += 1
            for du in ('https://m.stock.naver.com/api/research/%s/%s' % (cat, rid),
                       'https://m.stock.naver.com/api/research/detail?researchId=%s' % rid):
                try:
                    dr = urllib.request.urlopen(urllib.request.Request(du, headers=UA), timeout=15).read().decode('utf-8', 'ignore')
                    dj = json.loads(dr)
                except Exception as e:
                    if detail_n == 1: DEBUG.append('naver 상세 %s → %s' % (du.split('naver.com')[1][:50], repr(e)[:60]))
                    continue
                if detail_n == 1:
                    DEBUG.append('naver 상세 키: %s' % (list(dj.keys())[:20] if isinstance(dj, dict) else type(dj).__name__))
                pdf = _naver_pdf_in(dj)
                if pdf:
                    detail_ok += 1; break
            time.sleep(0.15)
        if not pdf:
            continue
        broker = _naver_pick(x, 'brokerName', 'broker', 'company', 'secur', 'org', 'source') or ''
        item = {'t': str(title).strip(), 'b': str(broker).strip(), 'd': x['_d'], 'pdf': str(pdf), 'v': int(_naver_pick(x, 'readCount', 'read', 'view', 'hit') or 0), 'src': '네이버'}
        if kind == 'industry':
            c = _naver_pick(x, '^category$', 'industry', 'upjong', 'sector')
            item['cat'] = str(c).strip() if c and str(c) != '기타' else _cat_of(item['t'])
        else:
            code = _naver_pick(x, 'itemCode', 'stockCode', '^code$')
            if not code:
                continue
            item['code'] = str(code); item['name'] = str(_naver_pick(x, 'itemName', 'stockName', '^name$') or '')
        out.append(item)
    DEBUG.append('naver %s 목록 %d건(7일) → 상세 %d건 시도·PDF %d건 → %d건' % (cat, len(lst), detail_n, detail_ok, len(out)))
    return out

NAVER_DETAIL_MAX = 150

def merge_reports(a, b):
    """소스 병합 — 앞 목록(a)을 우선. 중복 판정:
    ① 같은 PDF 주소 ② 같은 증권사+종목코드이고 날짜 차이 ≤1일(소스마다 게시일이 하루 어긋남) ③ 같은 날짜+증권사에서 정규화 제목이
    서로 접두(≥8자, 대신처럼 목록 제목이 '...'로 잘리는 경우)."""
    def bkey(x):
        return re.sub(r'(투자)?증권|㈜|\s', '', x.get('b', ''))
    def tkey(x):
        t = x.get('t', '')
        t = re.sub(r'^\s*\([^)]{0,20}\)\s*', '', t)                                        # (애널리스트)
        while True:   # 짧은 태그·리포트 유형 태그만 제거 ([반도체], [Industry Report], [대신증권 김아영] …)
            m = re.match(r'\s*\[([^\]]{0,30})\]\s*', t)
            if m and (len(m.group(1)) <= 8 or re.search(r'Report|Preview|Comment|Issue|News|Review|Note|증권|월보', m.group(1), re.I)):
                t = t[m.end():]
            else:
                break
        t = re.sub(r'^\S+\s*\(\s*[0-9A-Z]{6}[^)]*\)\s*', '', t)                       # 종목명(코드) 접두
        t = re.sub(r'^[^:()\[\]]{1,24}\((Overweight|Neutral|Underweight|OW|UW|BUY|HOLD|SELL|매수|중립|비중확대|비중축소)[^)]*\)\s*:?\s*', '', t, flags=re.I)  # 업종(Overweight):
        t = re.sub(r'^([^:]{1,20}:\s*){1,2}', '', t)                                            # "유틸리티 Weekly: " 같은 접두 (네이버는 이를 뗀 제목을 씀)
        return re.sub(r'[^0-9a-zA-Z가-힣]', '', t).lower()[:24]
    SERIES = re.compile(r'daily|데일리|weekly|위클리|monthly|월간|월보|주간', re.I)
    def near(d):
        try:
            dd = datetime.date.fromisoformat(d)
        except Exception:
            return [d]
        return [(dd + datetime.timedelta(days=k)).isoformat() for k in (-1, 0, 1)]
    seen_pdf, seen_code, titles, out = set(), set(), {}, []
    for x in list(a) + list(b):
        bk, tk, d = bkey(x), tkey(x), x.get('d')
        dup = x.get('pdf') in seen_pdf
        if not dup and x.get('code'):
            dup = any((bk, x['code'], dd) in seen_code for dd in near(d))
        if not dup and tk and len(tk) >= 8:
            series = bool(SERIES.search(x.get('t', '')))   # 시리즈물(Daily·Weekly)은 같은 날 접두 일치 또는 ±1일 완전 일치(15자↑)만
            for dd in near(d):
                for t2 in titles.get((dd, bk), []):
                    if len(t2) < 8:
                        continue
                    if (not series or dd == d) and (tk.startswith(t2) or t2.startswith(tk)):
                        dup = True; break
                    if series and len(tk) >= 15 and tk == t2:
                        dup = True; break
                if dup: break
        if dup:
            continue
        seen_pdf.add(x.get('pdf'))
        if x.get('code'):
            seen_code.add((bk, x['code'], d))
        titles.setdefault((d, bk), []).append(tk)
        out.append(x)
    return out

AN_PAT = re.compile(r'([가-힣]{2,4})\s*(?:선임연구원|수석연구원|책임연구원|연구위원|연구원|애널리스트|Analyst)')
AN_PAT2 = re.compile(r'(?:Analyst|애널리스트)\s*[|:.\s]\s*([가-힣]{2,4})')

def extract_analysts(reader):
    names = []
    try:
        for pg in reader.pages[:2]:
            tx = pg.extract_text() or ''
            for m in AN_PAT.findall(tx) + AN_PAT2.findall(tx):
                if m not in names and m not in ('투자', '자료', '리서치', '증권사', '의료기기', '반도체', '제약',
                                                '바이오', '화장품', '인터넷', '플랫폼', '담당', '수석', '책임', '선임'):
                    names.append(m)
    except Exception:
        pass
    return names[:4]

def count_pages(items, cache, ancache):
    try:
        from pypdf import PdfReader
    except Exception as e:
        DEBUG.append('pypdf 없음: %r' % e)
        return
    dl = 0
    for x in items:
        u = x['pdf']
        if x.get('html'):
            continue
        if u in cache and u in ancache:
            x['pg'] = cache[u]
            if ancache[u]:
                x['an'] = ancache[u]
            continue
        if dl >= MAX_PDF_DL or (time.time() - T0) > PDF_BUDGET_SEC:
            if u in cache:
                x['pg'] = cache[u]
            continue
        try:
            b = get(u, timeout=25, binary=True)
            rd = PdfReader(io.BytesIO(b))
            x['pg'] = cache[u] = len(rd.pages)
            an = extract_analysts(rd)
            ancache[u] = an
            if an:
                x['an'] = an
        except Exception as e:
            if len(DEBUG) < 15:
                DEBUG.append('PDF %s: %r' % (u[-30:], e))
            cache.setdefault(u, None)
            ancache.setdefault(u, [])
        dl += 1
        time.sleep(0.3)
    DEBUG.append('PDF 측정 %d건 (캐시 %d)' % (dl, len(cache)))

def translate_ko(text):
    """구글 번역 비공식 엔드포인트 (무키). 실패 시 원문 유지."""
    try:
        u = ('https://translate.googleapis.com/translate_a/single?client=gtx&sl=en&tl=ko&dt=t&q='
             + urllib.parse.quote(text[:400]))
        raw = urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=20).read().decode('utf-8')
        r = json.loads(raw)
        return ''.join(s[0] for s in r[0]).strip()
    except Exception:
        return text

GLOBAL_FEEDS = [
    ('Goldman Sachs', 'https://news.google.com/rss/search?q=' + urllib.parse.quote('site:goldmansachs.com/insights when:7d') + '&hl=en-US&gl=US&ceid=US:en'),
    ('Morgan Stanley', 'https://news.google.com/rss/search?q=' + urllib.parse.quote('site:morganstanley.com/insights when:7d') + '&hl=en-US&gl=US&ceid=US:en'),
    ('J.P. Morgan', 'https://news.google.com/rss/search?q=' + urllib.parse.quote('site:jpmorgan.com/insights when:7d') + '&hl=en-US&gl=US&ceid=US:en'),
    ('UBS', 'https://news.google.com/rss/search?q=' + urllib.parse.quote('site:ubs.com when:7d research OR outlook OR CIO') + '&hl=en-US&gl=US&ceid=US:en'),
    ('ING THINK', 'https://think.ing.com/rss'),
    ('McKinsey', 'https://www.mckinsey.com/insights/rss'),
]

def strip_tags(s):
    return re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', '', s or '')).strip()

def gn_resolve(link):
    """구글뉴스 리다이렉트 → 실제 기사 URL (batchexecute 해독)"""
    try:
        art_id = link.split('/articles/')[1].split('?')[0]
        h = urllib.request.urlopen(urllib.request.Request(link, headers=UA), timeout=20).read().decode('utf-8', 'ignore')
        sg = re.search(r'data-n-a-sg="([^"]+)"', h)
        ts = re.search(r'data-n-a-ts="([^"]+)"', h)
        if not (sg and ts):
            return None
        inner = json.dumps(["garturlreq", [["X", "X", ["X", "X"], None, None, 1, 1, "US:en", None, 1,
                            None, None, None, None, None, 0, 1], "X", "X", 1, [1, 1, 1], 1, 1, None, 0, 0, None, 0],
                            art_id, int(ts.group(1)), sg.group(1)])
        freq = json.dumps([[["Fbv4je", inner, None, "generic"]]])
        body = urllib.parse.urlencode({'f.req': freq}).encode()
        req = urllib.request.Request('https://news.google.com/_/DotsSplashUi/data/batchexecute',
                                     data=body, headers=dict(UA, **{'Content-Type': 'application/x-www-form-urlencoded;charset=UTF-8'}))
        r = urllib.request.urlopen(req, timeout=20).read().decode('utf-8', 'ignore')
        seg = r.split('garturlres')[-1] if 'garturlres' in r else r
        m = re.search(r'"(https?://[^"\\]+)', seg)
        return m.group(1) if m else None
    except Exception:
        return None

def fetch_body_ko(url):
    """기사 본문 추출 → 한국어 번역 (문단 그룹 단위). 실패 시 None"""
    try:
        h = urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=25).read().decode('utf-8', 'ignore')
    except Exception:
        return None
    ps = [re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', '', p)).strip()
          for p in re.findall(r'<p[^>]*>([\s\S]*?)</p>', h)]
    ps = [p for p in ps if len(p) > 80 and '.' in p and 'cookie' not in p.lower() and 'browser' not in p.lower()]
    if not ps:
        return None
    ps = ps[:22]
    # ~1600자 단위 청크로 묶어 번역
    chunks, cur = [], ''
    for p in ps:
        if len(cur) + len(p) > 1600 and cur:
            chunks.append(cur)
            cur = p
        else:
            cur = (cur + ' ' + p).strip()
    if cur:
        chunks.append(cur)
    out = []
    for c in chunks[:6]:
        try:
            u = ('https://translate.googleapis.com/translate_a/single?client=gtx&sl=en&tl=ko&dt=t&q='
                 + urllib.parse.quote(c))
            raw = urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=25).read().decode('utf-8')
            out.append(''.join(s[0] for s in json.loads(raw)[0]).strip())
        except Exception:
            break
        time.sleep(0.3)
    return '\n\n'.join(out) if out else None

def scrape_global(prev_items):
    prev_tr = {x.get('link'): x for x in (prev_items or [])}
    out = []
    for src, feed in GLOBAL_FEEDS:
        try:
            x = urllib.request.urlopen(urllib.request.Request(feed, headers=UA), timeout=25).read().decode('utf-8', 'ignore')
        except Exception as e:
            DEBUG.append('해외 %s: %r' % (src, e))
            continue
        n = 0
        for it in re.findall(r'<item>([\s\S]*?)</item>', x):
            tt = re.search(r'<title>(?:<!\[CDATA\[)?([\s\S]*?)(?:\]\]>)?</title>', it)
            lk = re.search(r'<link>(?:<!\[CDATA\[)?([\s\S]*?)(?:\]\]>)?</link>', it)
            pd = re.search(r'<pubDate>([^<]+)</pubDate>', it)
            ds = re.search(r'<description>(?:<!\[CDATA\[)?([\s\S]*?)(?:\]\]>)?</description>', it)
            if not (tt and lk):
                continue
            title = strip_tags(tt.group(1))
            title = re.sub(r'\s*-\s*(Goldman Sachs|Morgan Stanley|J\.?P\.? ?Morgan(?: Chase)?(?: & Co\.?)?|UBS)\s*$', '', title, flags=re.I)
            d = None
            if pd:
                try:
                    d = email.utils.parsedate_to_datetime(pd.group(1)).date().isoformat()
                except Exception:
                    pass
            if d and d < CUTOFF.isoformat():
                continue
            link = lk.group(1).strip()
            prev_x = prev_tr.get(link)
            if prev_x and prev_x.get('t_en') == title and prev_x.get('body'):  # 본문 번역까지 완료 → 재사용
                out.append(prev_x)
                n += 1
                continue
            summ = strip_tags(ds.group(1))[:220] if ds else ''
            item = prev_x if (prev_x and prev_x.get('t_en') == title) else {
                'src': src, 'd': d or TODAY.isoformat(), 'link': link,
                't_en': title, 't': translate_ko(title)}
            if summ and src in ('ING THINK', 'McKinsey') and not item.get('s'):
                item['s'] = translate_ko(summ)
            out.append(item)
            n += 1
            time.sleep(0.25)
            if n >= 20:
                break
        DEBUG.append('해외 %s %d건' % (src, n))
    # 본문 통번역 (실행당 최대 25건 — 나머지는 다음 실행에서)
    done_body = 0
    for x in out:
        if x.get('body') or done_body >= 25 or (time.time() - T0) > PDF_BUDGET_SEC + 300:
            continue
        real = x.get('url')
        if not real:
            real = x['link'] if 'news.google.com' not in x['link'] else gn_resolve(x['link'])
            if real:
                x['url'] = real
        if real:
            b = fetch_body_ko(real)
            if b and len(b) > 300:
                x['body'] = b[:7000]
        done_body += 1
        time.sleep(0.5)
    DEBUG.append('해외 본문 번역 %d건 시도, 보유 %d건' % (done_body, sum(1 for x in out if x.get('body'))))
    out.sort(key=lambda x: x['d'], reverse=True)
    return out[:90]

def main():
    try:
        prev = json.load(open(OUT, encoding='utf-8'))
    except Exception:
        prev = {}
    cache = {k: v for k, v in (prev.get('pagecache') or {}).items() if v}
    ancache = dict(prev.get('ancache') or {})
    ind = scrape('industry')
    cmp_ = scrape('company')
    try:   # 네이버 신형 리서치(모바일 API) 병합 — 실패해도 한경 결과는 유지
        ind = merge_reports(ind, scrape_naver('industry'))
        cmp_ = merge_reports(cmp_, scrape_naver('company'))
    except Exception as e:
        DEBUG.append('naver 병합 예외 %r' % e)
    try:   # 증권사 홈페이지 직접 수집 병합 (한경 → 네이버 → 각 하우스 순, 앞 소스 우선)
        b_ind, b_cmp = scrape_brokers(probe=bool(os.environ.get('BROKER_PROBE')))
        ind = merge_reports(ind, b_ind)
        cmp_ = merge_reports(cmp_, b_cmp)
    except Exception as e:
        DEBUG.append('증권사 직접수집 병합 예외 %r' % e)
    ind.sort(key=lambda x: x['d'], reverse=True); cmp_.sort(key=lambda x: x['d'], reverse=True)
    DEBUG.append('병합 후 industry %d · company %d' % (len(ind), len(cmp_)))
    from collections import Counter
    srcc = Counter(x.get('src', '') for x in ind + cmp_); brc = Counter(x.get('b', '') for x in ind + cmp_)
    DEBUG.append('소스별 건수: ' + ', '.join('%s %d' % kv for kv in srcc.most_common()))
    DEBUG.append('증권사별 건수: ' + ', '.join('%s %d' % kv for kv in brc.most_common()))
    DEBUG.append('수집 단계 %.0f초' % (time.time() - T0))
    try:   # 중간 저장 — 이후 PDF 측정·해외 번역이 타임아웃돼도 목록은 보존(워크플로 커밋은 if: always)
        for arr in (ind, cmp_):
            for x in arr:
                if x['pdf'] in cache: x['pg'] = cache[x['pdf']]
        mid = dict(prev); mid.update({'updated': time.strftime('%Y-%m-%d %H:%M'), 'debug': list(DEBUG) + ['(중간 저장)'], 'industry': ind, 'company': cmp_})
        os.makedirs('public/data', exist_ok=True)
        json.dump(mid, open(OUT, 'w', encoding='utf-8'), ensure_ascii=False)
    except Exception as e:
        DEBUG.append('중간 저장 실패 %r' % e)
    count_pages(ind, cache, ancache)
    count_pages(cmp_, cache, ancache)
    gl = scrape_global(prev.get('global'))
    for arr in (ind, cmp_):
        arr.sort(key=lambda x: (-(x.get('pg') or 0), x['d']), reverse=False)
        arr.sort(key=lambda x: (x.get('pg') or 0), reverse=True)
    live = set(x['pdf'] for x in ind + cmp_)
    # 📚 아카이브: 50페이지 이상 심층 리포트는 무기한 누적 (7일 창에서 빠져도 보존)
    archive = {x['pdf']: x for x in (prev.get('archive') or []) if x.get('pdf')}
    for kind, arr in (('industry', ind), ('company', cmp_)):
        for x in arr:
            if (x.get('pg') or 0) >= 50:
                y = dict(x); y['kind'] = kind
                old = archive.get(x['pdf']) or {}
                if not old or (y.get('v') or 0) >= (old.get('v') or 0):
                    archive[x['pdf']] = {**old, **y}
    # 📌 수동 시드(광통신·유리기판 등 심층 리포트) 병합 — public/data/report_seeds.json
    try:
        seeds = json.load(open('public/data/report_seeds.json', encoding='utf-8')).get('items') or []
        for s in seeds:
            if s.get('pdf'):
                old = archive.get(s['pdf']) or {}
                archive[s['pdf']] = {**old, **s, 'seed': True}
        DEBUG.append('시드 %d건' % len(seeds))
    except Exception as e:
        DEBUG.append('시드 병합 실패: %r' % e)
    arch_list = sorted(archive.values(), key=lambda x: (x.get('d') or '', x.get('pg') or 0), reverse=True)
    DEBUG.append('아카이브 %d건' % len(arch_list))
    DEBUG.append('총 %.0f초' % (time.time() - T0))
    out = {'updated': time.strftime('%Y-%m-%d %H:%M'), 'debug': DEBUG,
           'industry': ind, 'company': cmp_, 'global': gl, 'archive': arch_list,
           'pagecache': {k: v for k, v in cache.items() if v and k in live},
           'ancache': {k: v for k, v in ancache.items() if k in live}}
    os.makedirs('public/data', exist_ok=True)
    with open(OUT, 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False)
    print('완료:', DEBUG)

if __name__ == '__main__':
    main()
