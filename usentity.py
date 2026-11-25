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

# ── 미국 법인 판별 ───────────────────────────────────────────
# 법인명만으로 거르면 'USANA' 같은 오탐이 난다. 단어 경계를 둔다.
US = re.compile(
    r'(?<![A-Za-z])(U\.?S\.?A?|US|USA|AMERICA[N]?|AMERICAS|NORTH\s*AMERICA)(?![A-Za-z])'
    r'|미국|아메리카|미주'
    r'|(?<![A-Za-z])(NEW\s*YORK|NEW\s*JERSEY|CALIFORNIA|LOS\s*ANGELES|SEATTLE|OHIO|TEXAS|DELAWARE)(?![A-Za-z])',
    re.I)
# 미국 법인에서 흔한 법인격 — 이름에 지명이 없어도 함께 보는 보조 신호
USFORM = re.compile(r'(?<![A-Za-z])(INC|LLC|CORP|CORPORATION|CO\.?,?\s*LTD\.?\s*USA)(?![A-Za-z])', re.I)
# 생산법인 신호 — 미국에서 만들면 관세를 아예 안 맞는다
MAKE = re.compile(r'제조|생산|공장|LAB|LABORATOR|MANUFACTUR|PLANT|COSMAX|KOLMAR|ENGLEWOOD', re.I)
SELL = re.compile(r'판매|유통|도소매|마케팅|무역|DISTRIBUT|TRADING|SALES|RETAIL|COMMERCE', re.I)

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

def classify(nm, purpose):
    t = '%s %s' % (nm or '', purpose or '')
    if MAKE.search(t):
        return '생산'
    if SELL.search(t):
        return '판매'
    return '미상'

def one(code, name, corp):
    rec = {'n': name, 'corp': corp, 'us': [], 'year': None, 'tag': {}}
    rows, used = [], None
    for y in range(TODAY.year - 1, TODAY.year - 1 - YEARS, -1):
        rows = invest(corp, y)
        if rows:
            used = y; break
        time.sleep(0.25)
    rec['year'] = used
    if not rows:
        rec['why'] = '타법인 출자현황을 찾지 못했다 — 기재 대상이 아니거나 보고서 미제출'
        return rec
    for it in rows:
        nm = (it.get('inv_prm') or '').strip()          # 법인명
        pp = (it.get('invstmnt_purps') or '').strip()   # 출자목적
        if not nm:
            continue
        hit_name = bool(US.search(nm))
        hit_form = bool(USFORM.search(nm))
        if not hit_name:
            continue
        rec['us'].append({
            'nm': nm, 'purps': pp,
            'own': tonum(it.get('trmend_blce_qota_rt')),   # 기말 지분율 %
            'amt': tonum(it.get('trmend_blce_acntbk_amt')),# 기말 장부가
            'kind': classify(nm, pp),
            'form': hit_form,
        })
    # 사실 요약 — 여기까지가 '확인'
    mk = [x for x in rec['us'] if x['kind'] == '생산']
    sl = [x for x in rec['us'] if x['kind'] == '판매']
    rec['tag'] = {
        'n_us': len(rec['us']),
        'has_make': bool(mk),
        'has_sell': bool(sl),
        'max_own': max([x['own'] for x in rec['us'] if x['own'] is not None], default=None),
    }
    # 판단 — 확인된 사실에서 끌어낸 추론이다. 통관서류를 본 것이 아니다.
    if mk:
        rec['ior'] = {'lv': 'make', 'm':
            '미국에 생산법인이 있다(%s). 미국에서 만든 물량은 한국산이 아니라 관세를 아예 맞지 않는다. '
            '다만 한국에서 보내는 물량은 별개다.' % mk[0]['nm'][:40], 'tag': '확인'}
    elif sl and (rec['tag']['max_own'] or 0) >= 50:
        rec['ior'] = {'lv': 'self', 'm':
            '미국에 과반지분 판매법인이 있다(%s). 본사→자회사로 넘기는 구조라면 자회사가 IOR 이 되어 '
            '관세가 연결 손익에 직접 잡히고, 환급 청구권도 그 자회사에 생긴다. '
            '다만 실제 통관서류상 IOR 은 공개되지 않아 확정할 수 없다.' % sl[0]['nm'][:40], 'tag': '판단'}
    elif rec['us']:
        rec['ior'] = {'lv': 'part', 'm':
            '미국 법인이 있으나 지분율이 낮거나 역할이 불분명하다. IOR 구조를 공시만으로는 가를 수 없다.',
            'tag': '판단'}
    else:
        rec['ior'] = {'lv': 'none', 'm':
            '출자현황에 미국 법인이 없다. 미국 바이어·유통사가 IOR 일 가능성이 높고, 그렇다면 '
            '관세는 바이어가 내고 환급 청구권도 바이어에게 있다 — 한국 수출사는 가격 압박으로 간접 노출된다.',
            'tag': '판단'}
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
            n = out[c]['tag'].get('n_us', 0)
            log('%s %-14s 미국법인 %d · %s' % (c, (v.get('n') or c)[:14], n, out[c]['ior']['lv']))
        except Exception as e:
            out[c] = old.get(c) or {'n': v.get('n'), 'err': repr(e)[:120]}
            log('%s 실패 %r' % (c, e))
        time.sleep(0.3)
    from collections import Counter
    lv = Counter((x.get('ior') or {}).get('lv') for x in out.values())
    res = {'updated': NOW.strftime('%Y-%m-%d %H:%M KST'), 'n': len(out), 'co': out,
           'miss': miss, 'stat': dict(lv),
           'note': ('DART 「타법인 출자현황」에서 미국 소재 법인만 추린 것이다. '
                    '미국 법인의 존재·지분율·출자목적은 공시로 확인한 사실이고, '
                    'IOR(통관서류상 수입자) 추정은 거기서 끌어낸 판단이다 — CBP 서류는 공개되지 않아 확정할 수 없다. '
                    '생산법인이 있으면 그 물량은 한국산이 아니므로 관세 자체를 맞지 않는다.'),
           'debug': DEBUG[-60:]}
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(res, open(OUT, 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'))
    log('완료 %d곳 → %s · %s' % (len(out), OUT, dict(lv)))
    return 0

if __name__ == '__main__':
    sys.exit(main())
