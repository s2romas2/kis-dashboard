# -*- coding: utf-8 -*-
# ipo.py — 공모주 일정·수요예측·상장일 성적 수집 + 청약매력도(별표) 점수
# 원천: 38커뮤니케이션 공개 목록(공모청약일정·수요예측결과·수요예측일정·신규상장) — 하루 2회, 요청 간 1초 간격
# 결과: public/data/ipo.json   (외부 패키지·시크릿 없음)
import json, os, re, ssl, sys, time, datetime, urllib.request
from html.parser import HTMLParser

OUT = 'public/data/ipo.json'
BASE = 'https://www.38.co.kr/html/fund/index.htm?o=%s&page=%d'
DETAIL = 'https://www.38.co.kr/html/fund/?o=v&no=%s'
UA = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36',
      'Accept-Language': 'ko-KR,ko;q=0.9'}
KST = datetime.timezone(datetime.timedelta(hours=9))
TODAY = datetime.datetime.now(KST).date()
PAGES = {'k': int(os.environ.get('IPO_PAGES_K', '5')), 'r1': int(os.environ.get('IPO_PAGES_R1', '6')),
         'nw': int(os.environ.get('IPO_PAGES_NW', '6')), 'r': 1}
DEBUG = []
def log(m):
    print(m, flush=True); DEBUG.append(str(m)[:300])

# ───────── 별표 공식 (페이지가 이 표를 그대로 읽어 '기준'으로 보여줌 — 여기만 고치면 됨)
CFG = {
    'parts': [
        {'k': 'band', 'label': '확정 공모가의 밴드 위치', 'max': 30, 'easy': '기관들이 "이 가격이면 산다"고 한 수준 — 밴드 꼭대기(또는 그 위)면 수요가 넘쳤다는 뜻, 밴드 아래로 깎였으면 안 팔렸다는 뜻',
         'steps': [['상단 초과', 30], ['상단', 26], ['밴드 중간', 12], ['하단', 5], ['하단 미달', 0]]},
        {'k': 'inst', 'label': '기관 수요예측 경쟁률', 'max': 30, 'easy': '기관이 배정 물량의 몇 배를 달라고 했나 — 높을수록 상장일에 살 사람이 많음',
         'steps': [[1000, 30], [700, 24], [400, 16], [200, 9], [50, 4], [0, 0]]},
        {'k': 'lock', 'label': '의무보유확약 비율', 'max': 25, 'easy': '기관이 "상장 후 일정 기간 안 팔겠다"고 약속한 물량 비율 — 높을수록 상장일에 쏟아질 물량이 적음',
         'steps': [[30, 25], [15, 19], [5, 12], [1, 5], [0, 0]]},
        {'k': 'size', 'label': '공모 규모', 'max': 10, 'easy': '공모 금액이 작을수록 적은 돈으로도 주가가 움직임(수급이 가벼움)',
         'steps': [[0, 10], [300, 7], [500, 4], [1000, 2]]},   # 억원 이상 → 점수 (작을수록 높음)
        {'k': 'temp', 'label': '공모주 시장 온도', 'max': 5, 'easy': '직전에 상장한 공모주 10개의 상장일 시초가 평균 — 시장이 뜨거우면 다 같이 오르고 식으면 다 같이 눌림',
         'steps': [[50, 5], [20, 3], [0, 1], [-999, 0]]},
    ],
    'stars': [[78, 3], [58, 2], [38, 1], [0, 0]],          # 점수 이상 → 별 개수 (0 = ❌)
    'hard': '확정 공모가가 희망밴드 하단보다 낮으면 점수와 무관하게 ❌ (기관이 가격을 깎아야만 팔린 공모)',
    'note': '별표는 "상장일 수급 매력도"만 본다 — 기업가치·장기 주가와는 다른 문제. 스팩은 2,000원 원금 성격이라 별표 제외.',
}

def step_desc(pt, v):
    """v 이상인 첫 구간의 점수 (steps는 큰 값부터)"""
    for th, p in pt['steps']:
        if v >= th: return p, th
    return 0, None

def score(it, temp):
    """수요예측 결과가 있어야 계산. 반환 {score, stars, hard, parts:[{k,pt,max,val,rule}]}"""
    if it.get('spac'): return None
    fix, lo, hi, inst = it.get('fix'), it.get('band_lo'), it.get('band_hi'), it.get('inst')
    if not fix or inst is None: return None
    P = {p['k']: p for p in CFG['parts']}; parts = []; hard = False
    # 1) 밴드 위치
    if lo and hi:
        if fix > hi: pt, val, rule = 30, '확정 %s원 > 상단 %s원' % (f'{fix:,}', f'{hi:,}'), '상단 초과'
        elif fix == hi: pt, val, rule = 26, '확정 %s원 = 상단' % f'{fix:,}', '상단'
        elif fix > lo: pt, val, rule = 12, '확정 %s원 (밴드 %s~%s 중간)' % (f'{fix:,}', f'{lo:,}', f'{hi:,}'), '밴드 중간'
        elif fix == lo and hi > lo: pt, val, rule = 5, '확정 %s원 = 하단' % f'{fix:,}', '하단'
        elif fix == lo: pt, val, rule = 26, '확정 %s원 (단일가)' % f'{fix:,}', '상단'
        else: pt, val, rule, hard = 0, '확정 %s원 < 하단 %s원 (%.0f%% 할인)' % (f'{fix:,}', f'{lo:,}', (1 - fix / lo) * 100), '하단 미달', True
    else: pt, val, rule = 12, '희망밴드 정보 없음 → 중간 점수', '밴드 중간'
    parts.append({'k': 'band', 'pt': pt, 'max': 30, 'val': val, 'rule': rule})
    # 2) 기관 경쟁률
    pt, th = step_desc(P['inst'], inst)
    parts.append({'k': 'inst', 'pt': pt, 'max': 30, 'val': '%s:1' % f'{inst:,.0f}', 'rule': '%s:1 이상' % f'{th:,}'})
    # 3) 의무보유확약
    lock = it.get('lock') or 0.0
    pt, th = step_desc(P['lock'], lock)
    parts.append({'k': 'lock', 'pt': pt, 'max': 25, 'val': '%.2f%%%s' % (lock, ' (미기재 → 0%로 간주)' if it.get('lock') is None else ''), 'rule': '%s%% 이상' % th})
    # 4) 공모 규모 (작을수록 높음)
    amt = it.get('amt')
    if amt is None: pt, val, rule = 4, '공모금액 정보 없음 → 중간 점수', '—'
    else:
        pt = 10; rule = '300억 미만'
        for th, p in P['size']['steps']:
            if amt >= th: pt = p; rule = ('%s억 이상' % f'{th:,}') if th else '300억 미만'
        val = '%s억' % f'{amt:,.0f}'
    parts.append({'k': 'size', 'pt': pt, 'max': 10, 'val': val, 'rule': rule})
    # 5) 시장 온도
    if temp is None: pt, val, rule = 1, '직전 상장 표본 부족', '—'
    else:
        pt, th = step_desc(P['temp'], temp['avg'])
        val = '직전 %d개 시초가 평균 %+.1f%%' % (temp['n'], temp['avg']); rule = ('%+d%% 이상' % th) if th > -900 else '0% 미만'
    parts.append({'k': 'temp', 'pt': pt, 'max': 5, 'val': val, 'rule': rule})
    sc = sum(p['pt'] for p in parts)
    stars = 0
    for th, n in CFG['stars']:
        if sc >= th: stars = n; break
    if hard: stars = 0
    return {'score': sc, 'stars': stars, 'hard': hard, 'parts': parts}

# ───────── HTML 표 파서 (중첩 테이블 대응: 텍스트는 가장 안쪽 셀에만 붙임)
class TP(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True); self.tables = []; self.stack = []
    def handle_starttag(self, tag, attrs):
        if tag == 'table': self.stack.append({'rows': [], 'row': None, 'cell': None}); return
        if not self.stack: return
        t = self.stack[-1]
        if tag == 'tr': t['row'] = []; t['rows'].append(t['row']); t['cell'] = None
        elif tag in ('td', 'th'):
            if t['row'] is None: t['row'] = []; t['rows'].append(t['row'])
            t['cell'] = {'t': '', 'h': []}; t['row'].append(t['cell'])
        elif tag == 'a' and t['cell'] is not None:
            h = dict(attrs).get('href')
            if h: t['cell']['h'].append(h)
        elif tag == 'br' and t['cell'] is not None: t['cell']['t'] += ' '
    def handle_endtag(self, tag):
        if not self.stack: return
        t = self.stack[-1]
        if tag == 'table': self.tables.append(self.stack.pop())
        elif tag == 'tr': t['row'] = None; t['cell'] = None
        elif tag in ('td', 'th'): t['cell'] = None
    def handle_data(self, data):
        if self.stack and self.stack[-1]['cell'] is not None: self.stack[-1]['cell']['t'] += data

def _ctx():
    """인증서·호스트명 검증은 그대로 두고, 암호 스위트만 OpenSSL 표준 목록(DEFAULT)으로 넓힘.
    파이썬 기본 컨텍스트는 RSA 키교환·SHA1 MAC 스위트를 빼 두어서 구형 서버와 핸드셰이크가 실패하는 경우가 있음(curl·브라우저는 접속됨)"""
    c = ssl.create_default_context()
    try: c.set_ciphers('DEFAULT')
    except Exception as e: log('cipher 설정 실패 %r' % e)
    return c
_CTX = _ctx()
def fetch(o, page):
    url = BASE % (o, page)
    for attempt in range(3):
        try:
            b = urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30, context=_CTX).read()
            if len(b) > 2000: return b.decode('cp949', 'replace')
            log('응답 짧음 %s p%d: %d bytes' % (o, page, len(b)))
        except Exception as e:
            log('fetch 실패 %s p%d (%d): %r' % (o, page, attempt + 1, e))
        time.sleep(3 + attempt * 3)
    return ''

def norm(s): return re.sub(r'\s+', '', s or '')
def clean(s): return re.sub(r'\s+', ' ', s or '').strip()
def num(s):
    s = norm(s).replace(',', '').replace('%', '').replace('원', '')
    s = s.split(':')[0]
    try: return float(s) if s not in ('', '-', '.') else None
    except ValueError: return None
def inum(s):
    v = num(s); return int(v) if v is not None else None
def band(s):
    m = re.findall(r'[\d,]+', s or ''); v = [int(x.replace(',', '')) for x in m if x.replace(',', '').isdigit()]
    return (v[0], v[-1]) if v else (None, None)
def dates(s):
    """'2026.11.12~11.13' → ('2026-11-12','2026-11-13')"""
    m = re.match(r'\s*(\d{4})[./](\d{1,2})[./](\d{1,2})(?:\s*~\s*(?:(\d{4})[./])?(\d{1,2})[./](\d{1,2}))?', s or '')
    if not m: return None, None
    y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
    a = '%04d-%02d-%02d' % (y, mo, d)
    if not m.group(5): return a, a
    y2 = int(m.group(4)) if m.group(4) else (y + 1 if int(m.group(5)) < mo else y)
    return a, '%04d-%02d-%02d' % (y2, int(m.group(5)), int(m.group(6)))

def rows_of(html, o):
    """대상 표의 (헤더 인덱스 맵, 데이터 행들). 데이터 행 = 첫 칸 링크에 no= 가 있는 행"""
    p = TP()
    try: p.feed(html)
    except Exception as e: log('parse 오류 %s: %r' % (o, e))
    best = None
    for t in p.tables + p.stack:
        hdr = None; data = []
        for r in t['rows']:
            if not r: continue
            if hdr is None and any(norm(c['t']) in ('기업명', '종목명') for c in r): hdr = [norm(c['t']) for c in r]; continue
            if len(r) >= 5 and any('no=' in h for h in r[0]['h']): data.append(r)
        if data and (best is None or len(data) > len(best[1])): best = (hdr, data)
    if not best: return None, []
    return best

def col(hdr, keys, default):
    if hdr:
        for i, h in enumerate(hdr):
            if any(k in h for k in keys): return i
    return default
def cell(r, i): return r[i]['t'] if i is not None and i < len(r) else ''

def collect():
    items = {}
    def get(r):
        m = None
        for h in r[0]['h']:
            m = re.search(r'no=(\d+)', h)
            if m: break
        if not m: return None
        no = m.group(1); nm = clean(r[0]['t'])
        it = items.setdefault(no, {'no': no})
        if nm: it['name'] = nm
        return it
    # 공모청약일정
    for pg in range(1, PAGES['k'] + 1):
        hdr, data = rows_of(fetch('k', pg), 'k')
        if pg == 1: log('k 헤더=%s 행=%d' % (hdr, len(data)))
        if not data: break
        ci = {k: col(hdr, ks, d) for k, ks, d in [('sub', ['공모주일정', '청약일'], 1), ('fix', ['확정공모가'], 2), ('band', ['희망공모가'], 3), ('comp', ['청약경쟁률'], 4), ('lead', ['주간사', '주관사'], 5)]}
        for r in data:
            it = get(r)
            if not it: continue
            a, b = dates(cell(r, ci['sub']))
            if a: it['sub_s'], it['sub_e'] = a, b
            v = inum(cell(r, ci['fix']))
            if v: it['fix'] = v
            lo, hi = band(cell(r, ci['band']))
            if lo: it['band_lo'], it['band_hi'] = lo, hi
            v = num(cell(r, ci['comp']))
            if v is not None: it['sub_comp'] = v
            v = clean(cell(r, ci['lead']))
            if v: it['lead'] = v
        time.sleep(1)
    # 수요예측 결과
    for pg in range(1, PAGES['r1'] + 1):
        hdr, data = rows_of(fetch('r1', pg), 'r1')
        if pg == 1: log('r1 헤더=%s 행=%d' % (hdr, len(data)))
        if not data: break
        ci = {k: col(hdr, ks, d) for k, ks, d in [('fc', ['예측일'], 1), ('band', ['희망'], 2), ('fix', ['공모가(원)'], 3), ('amt', ['공모금액'], 4), ('inst', ['기관', '경쟁률'], 5), ('lock', ['의무보유', '확약'], 6), ('lead', ['주간사', '주관사'], 7)]}
        if hdr and ci['fix'] == ci['band']: ci['fix'] = 3
        for r in data:
            it = get(r)
            if not it: continue
            a, b = dates(cell(r, ci['fc']))
            if a: it['fc_s'], it['fc_e'] = a, b
            lo, hi = band(cell(r, ci['band']))
            if lo and not it.get('band_lo'): it['band_lo'], it['band_hi'] = lo, hi
            v = inum(cell(r, ci['fix']))
            if v: it['fix'] = v
            v = num(cell(r, ci['amt']))
            if v is not None: it['amt'] = round(v / 100, 1)          # 백만원 → 억원
            v = num(cell(r, ci['inst']))
            if v is not None:
                it['inst'] = v
                lk = num(cell(r, ci['lock'])); it['lock'] = lk     # '-' → None(미기재)
            v = clean(cell(r, ci['lead']))
            if v and not it.get('lead'): it['lead'] = v
        time.sleep(1)
    # 수요예측 일정(예정)
    hdr, data = rows_of(fetch('r', 1), 'r')
    log('r 헤더=%s 행=%d' % (hdr, len(data)))
    ci = {k: col(hdr, ks, d) for k, ks, d in [('fc', ['수요예측일', '예측일'], 1), ('band', ['희망'], 2), ('amt', ['공모금액'], 3), ('lead', ['주간사', '주관사'], 4)]}
    for r in data:
        it = get(r)
        if not it: continue
        a, b = dates(cell(r, ci['fc']))
        if a and not it.get('fc_s'): it['fc_s'], it['fc_e'] = a, b
        lo, hi = band(cell(r, ci['band']))
        if lo and not it.get('band_lo'): it['band_lo'], it['band_hi'] = lo, hi
        v = num(cell(r, ci['amt']))
        if v is not None and it.get('amt') is None: it['amt_plan'] = round(v / 100, 1)
        v = clean(cell(r, ci['lead']))
        if v and not it.get('lead'): it['lead'] = v
    time.sleep(1)
    # 신규상장
    for pg in range(1, PAGES['nw'] + 1):
        hdr, data = rows_of(fetch('nw', pg), 'nw')
        if pg == 1: log('nw 헤더=%s 행=%d' % (hdr, len(data)))
        if not data: break
        ci = {k: col(hdr, ks, d) for k, ks, d in [('ld', ['신규상장일', '상장일'], 1), ('cur', ['현재가'], 2), ('fix', ['공모가(원)'], 4), ('open', ['시초가'], 6), ('close', ['첫날종가', '종가'], 8)]}
        for r in data:
            it = get(r)
            if not it: continue
            a, _ = dates(cell(r, ci['ld']))
            if a: it['list'] = a
            for k, key in [('cur', 'cur'), ('open', 'open'), ('close', 'close1')]:
                v = inum(cell(r, ci[k]))
                if v: it[key] = v
            v = inum(cell(r, ci['fix']))
            if v and not it.get('fix'): it['fix'] = v
            for c in r:
                for h in c['h']:
                    m = re.search(r'code=([0-9A-Z]{6})', h)
                    if m: it['code'] = m.group(1)
        time.sleep(1)
    return items

def main():
    old = {}
    try:
        for it in json.load(open(OUT, encoding='utf-8')).get('items', []): old[it['no']] = it
    except Exception: pass
    new = collect()
    log('수집 %d종목 (기존 %d)' % (len(new), len(old)))
    if len(new) < 10 and old:
        log('수집 실패로 판단 → 기존 데이터 유지');
        d = json.load(open(OUT, encoding='utf-8')); d['debug'] = DEBUG; d['stale'] = True
        json.dump(d, open(OUT, 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':')); return
    for no, it in new.items():
        o = old.get(no, {})
        for k in ('score', 'stars', 'hard', 'parts', 'temp'): o.pop(k, None)
        o.update({k: v for k, v in it.items() if v is not None}); old[no] = o
    items = list(old.values())
    for it in items:
        nm = it.get('name', '')
        it['spac'] = bool(re.search(r'스팩|기업인수목적', nm))
        it['mkt'] = '코스피' if '(유가)' in nm else '코스닥'
        it['url'] = DETAIL % it['no']
        if it.get('fix') and it.get('open'): it['r_open'] = round((it['open'] / it['fix'] - 1) * 100, 1)
        if it.get('fix') and it.get('close1'): it['r_close'] = round((it['close1'] / it['fix'] - 1) * 100, 1)
    # 시장 온도: 그 종목 청약 시작 전(없으면 오늘) 이미 상장한 일반기업 최근 10개의 시초가 수익률 평균
    listed = sorted([it for it in items if not it['spac'] and it.get('list') and it.get('r_open') is not None], key=lambda x: x['list'])
    def temp_at(day):
        prev = [x for x in listed if x['list'] < day][-10:]
        if len(prev) < 5: return None
        return {'n': len(prev), 'avg': round(sum(x['r_open'] for x in prev) / len(prev), 1)}
    for it in items:
        ref = it.get('sub_s') or TODAY.isoformat()
        t = temp_at(min(ref, TODAY.isoformat()))
        s = score(it, t)
        if s: it.update(s); it['temp'] = t
    # 검증(백테스트): 별 등급별 상장일 성적
    bt = []
    for st in (3, 2, 1, 0):
        g = [x for x in listed if x.get('stars') == st and x.get('score') is not None]
        if not g: bt.append({'stars': st, 'n': 0}); continue
        ro = sorted(x['r_open'] for x in g); rc = [x['r_close'] for x in g if x.get('r_close') is not None]
        bt.append({'stars': st, 'n': len(g), 'open_avg': round(sum(ro) / len(ro), 1), 'open_med': ro[len(ro) // 2], 'close_avg': round(sum(rc) / len(rc), 1) if rc else None,
                   'win': round(sum(1 for v in ro if v > 0) / len(ro) * 100), 'loss': round(sum(1 for v in ro if v < 0) / len(ro) * 100), 'worst': ro[0], 'best': ro[-1]})
    items.sort(key=lambda x: (x.get('sub_s') or x.get('fc_s') or x.get('list') or ''), reverse=True)
    items = items[:500]
    cur_t = temp_at(TODAY.isoformat())
    last10 = [{'no': x['no'], 'name': x['name'], 'list': x['list'], 'r_open': x['r_open'], 'r_close': x.get('r_close'), 'stars': x.get('stars')} for x in listed[-10:]]
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump({'updated': datetime.datetime.now(KST).strftime('%Y-%m-%d %H:%M'), 'source': '38커뮤니케이션 공개 목록(공모청약일정·수요예측결과·수요예측일정·신규상장)',
               'src_urls': {'청약일정': BASE % ('k', 1), '수요예측결과': BASE % ('r1', 1), '수요예측일정': BASE % ('r', 1), '신규상장': BASE % ('nw', 1)},
               'formula': CFG, 'temp': cur_t, 'last10': last10, 'backtest': bt, 'n_listed': len(listed), 'bt_from': listed[0]['list'] if listed else None,
               'items': items, 'debug': DEBUG}, open(OUT, 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'))
    log('저장 %s %d종목 · 상장 표본 %d · 별표 %d' % (OUT, len(items), len(listed), sum(1 for x in items if x.get('score') is not None)))
    for b in bt: log('BT %s' % b)

if __name__ == '__main__':
    main()
