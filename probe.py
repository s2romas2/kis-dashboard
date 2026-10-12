#!/usr/bin/env python3
# 1회용 진단 — valfacts 수집기 개발용 샘플: DART 공급계약 원문·정기보고서 사업의 내용·지배구조 API·뉴스 RSS·네이버 컨센
# rerun-valfacts-1
import os, io, json, zipfile, re, time, urllib.request, urllib.parse, ssl, datetime

KEY = os.environ.get('DART_KEY', '')
UA = {'User-Agent': 'Mozilla/5.0'}
CTX = ssl.create_default_context(); CTX.check_hostname = False; CTX.verify_mode = ssl.CERT_NONE
BASE = 'https://opendart.fss.or.kr/api'
out = {'at': datetime.datetime.utcnow().isoformat(), 'api': {}, 'doc': {}, 'news': {}, 'naver': {}, 'err': []}

def get(url, timeout=60):
    return urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout, context=CTX).read()
def api(name, **kw):
    q = urllib.parse.urlencode(dict(crtfc_key=KEY, **kw))
    try:
        j = json.loads(get('%s/%s.json?%s' % (BASE, name, q)).decode('utf-8'))
    except Exception as e:
        out['err'].append('%s %r' % (name, e)); return {}
    time.sleep(0.25)
    return j
def doc(rcept):
    try:
        b = get('%s/document.xml?crtfc_key=%s&rcept_no=%s' % (BASE, KEY, rcept), 120)
        z = zipfile.ZipFile(io.BytesIO(b))
        names = z.namelist()
        raws = {n: z.read(n).decode('utf-8', 'ignore') for n in names}
        time.sleep(0.3)
        return names, raws
    except Exception as e:
        out['err'].append('doc %s %r' % (rcept, e)); return [], {}

CORPS = {'092870': '00611736', '101160': '00580065'}
TODAY = datetime.date.today().strftime('%Y%m%d')
for code, corp in CORPS.items():
    a = {}
    a['list_I'] = api('list', corp_code=corp, bgn_de='20241001', end_de=TODAY, pblntf_ty='I', page_count=100)
    a['list_A'] = api('list', corp_code=corp, bgn_de='20250101', end_de=TODAY, pblntf_ty='A', page_count=20)
    for nm in ('hyslrSttus', 'hyslrChgSttus', 'mrhlSttus', 'alotMatter', 'hmvAuditAllSttus', 'hmvAuditIndvdlBySttus', 'exctvSttus',
               'tesstkAcqsDspsSttus', 'stockTotqySttus', 'indvdlByPay', 'unrstExctvMendngSttus'):
        a[nm + '_2025_11011'] = api(nm, corp_code=corp, bsns_year='2025', reprt_code='11011')
    a['hyslrSttus_2026_11012'] = api('hyslrSttus', corp_code=corp, bsns_year='2026', reprt_code='11012')
    a['majorstock'] = api('majorstock', corp_code=corp)
    a['elestock'] = api('elestock', corp_code=corp)
    for nm in ('tsstkAqDecsn', 'tsstkDpDecsn', 'tsstkAqTrctrCnsDecsn', 'tsstkAqTrctrCcDecsn', 'cvbdIsDecsn', 'piicDecsn'):
        a[nm] = api(nm, corp_code=corp, bgn_de='20230101', end_de=TODAY)
    # 응답 길이 제한: list 20행까지
    for k, v in a.items():
        if isinstance(v.get('list'), list) and len(v['list']) > 25 and not k.startswith('list_'):
            v['list_n'] = len(v['list']); v['list'] = v['list'][:25]
    out['api'][code] = a

# 공급계약 원문(코스닥 2건 + 정정 1건), 유가증권 서식 1건(한미반도체 최근 공급계약)
for rc in ('20260710900182', '20260904900736', '20250929900126'):
    names, raws = doc(rc)
    out['doc'][rc] = {'names': names, 'raw': {n: r[:60000] for n, r in raws.items()}}
hm = api('list', corp_code='00161383', bgn_de='20250101', end_de=TODAY, pblntf_ty='I', page_count=100)
hits = [r for r in hm.get('list') or [] if '공급계약' in r.get('report_nm', '')][:2]
out['api']['042700_listhits'] = hits
for r in hits[:1]:
    names, raws = doc(r['rcept_no'])
    out['doc'][r['rcept_no']] = {'names': names, 'raw': {n: x[:60000] for n, x in raws.items()}}

# 정기보고서: 사업의 내용 구간만(엑시콘 반기, 월덱스 사업보고서)
for rc in ('20260814001521', '20260318001643'):
    names, raws = doc(rc)
    d = {'names': names, 'sizes': {n: len(r) for n, r in raws.items()}}
    for n, r in raws.items():
        titles = [(m.start(), re.sub(r'<[^>]+>', '', m.group(0))[:80]) for m in re.finditer(r'<TITLE[^>]*>.*?</TITLE>', r, re.S)]
        d.setdefault('titles', {})[n] = titles[:200]
        i = r.find('사업의 내용'); j = r.find('재무에 관한 사항', i + 10)
        if i >= 0:
            seg = r[i:(j if j > i else i + 400000)]
            d.setdefault('biz', {})[n] = seg[:250000]
            d.setdefault('biz_len', {})[n] = len(seg)
        k = r.find('제재')
        d.setdefault('head', {})[n] = r[:3000]
    out['doc'][rc] = d

# 뉴스 RSS
def rss(q):
    u = 'https://news.google.com/rss/search?q=%s&hl=ko&gl=KR&ceid=KR:ko' % urllib.parse.quote(q)
    try:
        x = get(u, 30).decode('utf-8', 'ignore')
        items = re.findall(r'<item>(.*?)</item>', x, re.S)
        res = []
        for it in items[:100]:
            t = re.search(r'<title>(.*?)</title>', it, re.S); l = re.search(r'<link>(.*?)</link>', it, re.S)
            d = re.search(r'<pubDate>(.*?)</pubDate>', it, re.S); s = re.search(r'<source[^>]*>(.*?)</source>', it, re.S)
            res.append([t.group(1) if t else '', l.group(1)[:120] if l else '', d.group(1) if d else '', s.group(1) if s else ''])
        return {'n': len(items), 'items': res}
    except Exception as e:
        return {'err': repr(e)}
KW = '승계 OR 증여 OR 상속 OR 주주환원 OR 배당 OR 자사주 OR 행동주의 OR 소액주주 OR 주주제안 OR 경영권 OR 횡령 OR 배임 OR 보수 OR 주총 OR 지배구조 OR 최대주주'
for nm in ('월덱스', '엑시콘', '테스'):
    out['news'][nm + '|kw'] = rss('"%s" (%s)' % (nm, KW))
    out['news'][nm + '|kw|after'] = rss('"%s" (%s) after:2025-10-01' % (nm, KW))
    time.sleep(1)
out['news']['월덱스|short'] = rss('월덱스 주주환원 OR 승계 OR 자사주 when:1y')

# 네이버 컨센
for code in ('092870', '101160'):
    for kind in ('annual', 'quarter'):
        try:
            out['naver'][code + '_' + kind] = json.loads(get('https://m.stock.naver.com/api/stock/%s/finance/%s' % (code, kind), 30).decode('utf-8'))
        except Exception as e:
            out['err'].append('naver %s %r' % (code, e))

os.makedirs('public/data', exist_ok=True)
s = json.dumps(out, ensure_ascii=False)
if KEY: s = s.replace(KEY, 'KEY')
open('public/data/probe.json', 'w', encoding='utf-8').write(s)
print('probe bytes', len(s), 'errors', len(out['err']))
