#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
미국 현지법인 보유 현황 — 관세를 누가 내는지(IOR)를 가르는 사실

왜 필요한가
    2026-07-24 부터 한국산에 Section 301 12.5% 가 붙는다.
    그런데 이 관세를 '누가 내느냐'는 수출 조건과 통관서류상 수입자(IOR)가 정한다.
      · FOB·EXW  → 미국 바이어가 IOR. 한국 수출사는 관세를 직접 안 낸다(대신 가격 압박을 받는다)
      · DDP·자가수입 → 한국 기업(또는 그 미국 자회사)이 IOR. 관세가 연결 손익에 바로 꽂힌다
    환급 청구권도 **IOR 에게만** 있다. 그래서 같은 수출액이라도 구조에 따라 손익이 갈린다.

무엇을 확인할 수 있고 무엇은 못 하나 — 이 구분이 이 수집기의 전부다
    확인 가능 : 미국 소재 종속·관계기업이 있는가, 지분율, 출자목적, 생산법인인가 판매법인인가
                (DART 「타법인 출자현황」 — 사업보고서 기재사항, 공시 원본)
    확인 불가 : 실제 통관서류상 IOR 이 누구인지. 이건 CBP 서류라 공개되지 않는다.
    그래서 산출물은 **사실(확인)과 추론(판단)을 분리해서** 담는다. 섞으면 안 된다.
"""
import os, io, sys, json, time, zipfile, urllib.request, re, datetime
import xml.etree.ElementTree as ET

KEY    = os.environ.get('DART_KEY', '')
BASE   = 'https://opendart.fss.or.kr/api'
OUT    = os.environ.get('OUT', 'public/data/usentity.json')
DEF    = os.environ.get('DEF', 'public/data/cospeer_def.json')
YEARS  = int(os.environ.get('YEARS', '3'))      # 최근 몇 개 사업연도를 훑나
MAXRUN = int(os.environ.get('MAXRUN', '0'))     # 0 = 전부
KST    = datetime.timezone(datetime.timedelta(hours=9))
NOW    = datetime.datetime.now(KST)
TODAY  = NOW.date()
DEBUG  = []

def log(s):
    DEBUG.append(s); print(s, flush=True)

def fetch(url, timeout=60):
    for i in range(3):
        try:
            rq = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(rq, timeout=timeout) as r:
                return r.read()
        except Exception:
            time.sleep(1.2 * (i + 1))
    return b''

def jget(url):
    try:
        return json.loads(fetch(url).decode('utf-8'))
    except Exception:
        return {}

def corp_map():
    b = fetch('%s/corpCode.xml?crtfc_key=%s' % (BASE, KEY), 120)
    z = zipfile.ZipFile(io.BytesIO(b))
    root = ET.fromstring(z.read(z.namelist()[0]))
    m = {}
    for it in root.iter('list'):
        sc = (it.findtext('stock_code') or '').strip()
        if len(sc) == 6:
            m[sc] = (it.findtext('corp_code') or '').strip()
    return m

# ── 해외 법인 판별 ───────────────────────────────────────────
# 처음엔 법인명에 US/AMERICA 가 있는지로만 걸렀더니, 미국 공장을 가진
# 코스맥스·한국콜마·코스메카코리아가 전부 '미국 법인 0곳'으로 나왔다.
# 자회사 이름에 지명이 없기 때문이다(Englewood Lab, Nu-World …).
# 이름만으로는 소재국을 알 수 없다 — 그래서 **해외로 보이는 법인을 전부 내보내고**
# 그중 이름에 미국 토큰이 있는 것만 '미국 확인'으로 따로 표시한다. 추측으로 메우지 않는다.
USNAME = re.compile(
    r'(?<![A-Za-z])(U\.?S\.?A?|US|USA|AMERICA[N]?|AMERICAS|NORTH\s*AMERICA)(?![A-Za-z])'
    r'|미국|아메리카|미주'
    r'|(?<![A-Za-z])(NEW\s*YORK|NEW\s*JERSEY|CALIFORNIA|LOS\s*ANGELES|SEATTLE|OHIO|TEXAS|DELAWARE)(?![A-Za-z])',
    re.I)
# 다른 나라가 이름에 박혀 있으면 미국이 아니다 — 오탐을 줄인다
NOTUS = re.compile(
    r'(?<![A-Za-z])(CHINA|SHANGHAI|GUANGZHOU|BEIJING|JAPAN|TOKYO|VIETNAM|THAI|INDONESIA|'
    r'SINGAPORE|MALAYSIA|INDIA|EUROPE|FRANCE|PARIS|GERMANY|UK|LONDON|AUSTRALIA|CANADA|'
    r'TAIWAN|HONGKONG|HONG\s*KONG|RUSSIA|BRAZIL|MEXICO|TURKEY|DUBAI|UAE)(?![A-Za-z])'
    r'|중국|상해|상하이|광저우|북경|일본|베트남|태국|인도네시아|싱가포르|말레이시아|'
    r'유럽|프랑스|독일|영국|호주|캐나다|대만|홍콩|러시아|브라질|멕시코',
    re.I)
# 라틴문자가 섞여 있으면 해외 법인일 가능성이 있다 — 판단이 아니라 '후보'로만 쓴다
LATIN = re.compile(r'[A-Za-z]{3,}')

# 출자목적에 성격이 적혀 있을 때만 쓴다. 이름으로 생산/판매를 가르지 않는다 —
# 앞서 법인명에 COSMAX·KOLMAR 를 넣어 '생산'으로 찍었는데, 그건 답을 미리 박아 넣은 것이라 걷어냈다.
MAKE = re.compile(r'제조|생산|공장|MANUFACTUR|PRODUCTION|PLANT', re.I)
SELL = re.compile(r'판매|유통|도소매|마케팅|무역|DISTRIBUT|TRADING|SALES|RETAIL', re.I)

def tonum(s):
    try:
        return float(re.sub(r'[^\d.\-]', '', str(s)))
    except Exception:
        return None

def invest(corp, year, reprt='11011'):
    """타법인 출자현황 — 사업보고서 기재사항"""
    d = jget('%s/otrCprInvstmntSttus.json?crtfc_key=%s&corp_code=%s&bsns_year=%d&reprt_code=%s'
             % (BASE, KEY, corp, year, reprt))
    if d.get('status') != '013' and not (d.get('list') or []):
        log('  출자현황 status=%s %s' % (d.get('status'), (d.get('message') or '')[:40]))
    return d.get('list') or []

def classify(purpose):
    """출자목적 기재에만 근거한다. 법인명으로 추정하면 근거 없는 '확인'이 생긴다."""
    p = purpose or ''
    if MAKE.search(p):
        return '생산'
    if SELL.search(p):
        return '판매'
    return '미상'

def one(code, name, corp):
    rec = {'n': name, 'corp': corp, 'us': [], 'fg': [], 'year': None, 'rows': 0, 'tag': {}}
    rows, used = [], None
    for y in range(TODAY.year - 1, TODAY.year - 1 - YEARS, -1):
        rows = invest(corp, y)
        if rows:
            used = y; break
        time.sleep(0.25)
    rec['year'] = used
    rec['rows'] = len(rows)
    if not rows:
        rec['why'] = '타법인 출자현황이 비어 있다 — 기재 대상이 아니거나 보고서를 찾지 못했다'
        rec['ior'] = {'lv': 'unk', 'tag': '미확인',
                      'm': '출자현황을 받지 못해 미국 법인 보유 여부를 판단할 수 없다.'}
        return rec
    for it in rows:
        nm = re.sub(r'\s+', ' ', (it.get('inv_prm') or '')).strip()
        pp = (it.get('invstmnt_purps') or '').strip()
        if not nm:
            continue
        e = {'nm': nm, 'purps': pp,
             'own': tonum(it.get('trmend_blce_qota_rt')),
             'amt': tonum(it.get('trmend_blce_acntbk_amt')),
             'kind': classify(pp)}
        if USNAME.search(nm) and not NOTUS.search(nm):
            rec['us'].append(e)
        elif LATIN.search(nm) and not NOTUS.search(nm):
            # 라틴문자 이름인데 미국 토큰이 없다 — 소재국을 알 수 없다.
            # 코스맥스·한국콜마·코스메카의 미국 공장이 여기로 빠진다. 숨기지 않고 내보낸다.
            rec['fg'].append(e)
    rec['us'].sort(key=lambda x: -(x['own'] or 0))
    rec['fg'].sort(key=lambda x: -(x['own'] or 0))
    rec['fg'] = rec['fg'][:12]
    mx = max([x['own'] for x in rec['us'] if x['own'] is not None], default=None)
    rec['tag'] = {'n_us': len(rec['us']), 'n_fg': len(rec['fg']), 'max_own': mx,
                  'make': [x['nm'] for x in rec['us'] if x['kind'] == '생산'][:2]}
    # ── 판단 ─────────────────────────────────────────────
    # 공시로 확인되는 것은 '미국 법인이 있다/지분율이 얼마다'까지다.
    # 통관서류상 IOR 은 CBP 자료라 공개되지 않으므로 아래는 모두 추론이고, 그렇게 표시한다.
    note_fg = ('' if not rec['fg'] else
               ' 다만 소재국을 알 수 없는 해외 법인이 %d곳 더 있어(이름에 지명이 없다) '
               '미국 법인이 더 있을 수 있다.' % len(rec['fg']))
    if rec['tag']['make']:
        rec['ior'] = {'lv': 'make', 'tag': '판단', 'm':
            '출자목적에 제조·생산이 적힌 미국 법인이 있다(%s). 미국에서 만든 물량은 한국산이 아니라 '
            '관세를 맞지 않는다. 한국에서 보내는 물량은 별개다.' % rec['tag']['make'][0][:40] + note_fg}
    elif mx is not None and mx >= 50:
        rec['ior'] = {'lv': 'self', 'tag': '판단', 'm':
            '미국에 과반(%.0f%%) 자회사가 있다. 본사→자회사로 넘기는 구조라면 그 자회사가 IOR 이 되어 '
            '관세가 연결 손익에 직접 잡히고 환급 청구권도 자회사에 생긴다. '
            '실제 통관서류상 IOR 은 공개되지 않아 확정할 수 없다.' % mx + note_fg}
    elif rec['us']:
        rec['ior'] = {'lv': 'part', 'tag': '판단', 'm':
            '미국 법인이 있으나 지분이 과반에 못 미친다(최대 %s%%). 지분투자에 가까워 '
            'IOR 구조를 공시만으로는 가를 수 없다.' % (mx if mx is not None else '미상') + note_fg}
    elif rec['fg']:
        rec['ior'] = {'lv': 'fg', 'tag': '미확인', 'm':
            '이름에 미국이 드러난 법인은 없으나 소재국을 알 수 없는 해외 법인이 %d곳 있다. '
            '이 중 미국 법인이 있는지는 사업보고서의 종속기업 현황(소재지 열)을 봐야 한다.' % len(rec['fg'])}
    else:
        rec['ior'] = {'lv': 'none', 'tag': '판단', 'm':
            '출자현황에 해외 법인이 보이지 않는다. 미국 바이어·유통사가 IOR 일 가능성이 높고, '
            '그렇다면 관세는 바이어가 내고 환급 청구권도 바이어에게 있다 — '
            '한국 수출사는 가격 압박으로 간접 노출된다.'}
    return rec

def main():
    if not KEY:
        print('DART_KEY 필요', file=sys.stderr); return 1
    co = {}
    try:
        co = json.load(open(DEF, encoding='utf-8')).get('co') or {}
    except Exception as e:
        print('정의 파일 실패 %r' % e, file=sys.stderr); return 1
    cmap = corp_map()
    log('corp_map %d건 · 대상 %d곳' % (len(cmap), len(co)))
    old = {}
    try:
        old = (json.load(open(OUT, encoding='utf-8')).get('co') or {})
    except Exception:
        pass
    out, ran, miss = {}, 0, []
    for c, v in co.items():
        corp = cmap.get(c)
        if not corp:
            miss.append(c); continue
        if MAXRUN and ran >= MAXRUN and c in old:
            out[c] = old[c]; continue
        try:
            out[c] = one(c, v.get('n') or c, corp); ran += 1
            t = out[c]['tag']
            log('%s %-14s 출자 %d행 · 미국 %d · 해외미상 %d · %s' % (
                c, (v.get('n') or c)[:14], out[c].get('rows', 0),
                t.get('n_us', 0), t.get('n_fg', 0), out[c]['ior']['lv']))
        except Exception as e:
            out[c] = old.get(c) or {'n': v.get('n'), 'err': repr(e)[:120]}
            log('%s 실패 %r' % (c, e))
        time.sleep(0.3)
    from collections import Counter
    lv = Counter((x.get('ior') or {}).get('lv') for x in out.values())
    res = {'updated': NOW.strftime('%Y-%m-%d %H:%M KST'), 'n': len(out), 'co': out,
           'miss': miss, 'stat': dict(lv),
           'note': ('DART 「타법인 출자현황」이 원본이다. 법인명·지분율·출자목적은 공시로 확인한 사실이고, '
                    'IOR(통관서류상 수입자) 추정은 거기서 끌어낸 판단이다 — CBP 서류는 공개되지 않아 확정할 수 없다. '
                    '한계: 출자현황에는 소재국 열이 없어 이름으로만 미국 법인을 가린다. '
                    '이름에 지명이 없는 해외 법인(Englewood Lab, Nu-World 등)은 fg 로 따로 담았다 — '
                    '여기에 미국 공장이 섞여 있을 수 있으니 fg 가 있는 곳은 사업보고서 종속기업 현황을 봐야 한다.'),
           'debug': DEBUG[-60:]}
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(res, open(OUT, 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'))
    log('완료 %d곳 → %s · %s' % (len(out), OUT, dict(lv)))
    return 0

if __name__ == '__main__':
    sys.exit(main())
