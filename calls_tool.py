#!/usr/bin/env python3
# 📞 콜 노트 — 팀더윤쎈 콜 아카이브 암호화 도구 (본인 전용)
# 사용: CALLS_PASS=... python3 calls_tool.py build  /tmp/calls.json   # 원본 rows(JSON 배열) → public/data/calls.enc
#       CALLS_PASS=... python3 calls_tool.py decrypt                   # 현재 enc → stdout(JSON)
#       CALLS_PASS=... python3 calls_tool.py merge /tmp/new_rows.json  # 기존 + 신규 rows 병합 후 재암호화
#       CALLS_PASS=... python3 calls_tool.py setw /tmp/w.json         # 편입 비중(슬라이드 배지) 기록 {rptNo:{w,w0,style}}
#       CALLS_PASS=... python3 calls_tool.py setsum /tmp/sum.json     # 콜 한 줄 요약 기록 {rptNo:"요약"}
# 포맷: base64( salt16 | iv12 | AES-GCM(ciphertext) ), 키 = PBKDF2-SHA256(pass, salt, 200000, 32)
import os, sys, json, base64, re, time
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

OUT = 'public/data/calls.enc'
ITER = 200000
CDN = 'https://file.3o3campus.co.kr/bs_3o3campus/report/'

def key_of(pw, salt):
    return PBKDF2HMAC(hashes.SHA256(), 32, salt, ITER).derive(pw.encode())

def encrypt(pw, obj):
    salt, iv = os.urandom(16), os.urandom(12)
    ct = AESGCM(key_of(pw, salt)).encrypt(iv, json.dumps(obj, ensure_ascii=False).encode(), None)
    return base64.b64encode(salt + iv + ct).decode()

def decrypt(pw, b64):
    raw = base64.b64decode(b64)
    salt, iv, ct = raw[:16], raw[16:28], raw[28:]
    return json.loads(AESGCM(key_of(pw, salt)).decrypt(iv, ct, None).decode())

def classify(title, kw):
    t = title
    if '잠정실적' in t: return '잠정실적'
    if 'Weekly Letter' in t or '보강' in t: return '레터'
    if '신규 편입' in t or '신규편입' in kw or '신규 편입콜' in t: return '신규편입'
    if '편출' in t or '편출' in kw: return '편출'
    if '상향' in t and '비중' in t or '상향편입' in kw: return '비중상향'
    if '하향' in t and ('비중' in t or '편입' in t) or '하향편입' in kw: return '비중하향'
    if '업데이트콜' in t: return '업데이트'
    if '왓칭콜' in t or '왓칭' in kw: return '왓칭'
    if '매크로콜' in t or kw.startswith('매크로'): return '매크로'
    if '마켓콜' in t or kw.startswith('마켓콜'): return '마켓'
    return '기타'

ALIAS = {'삼정전자': '삼성전자'}

def stock_of(kind, kw, title):
    # 키워드에서 종목명 추출: "신규편입 BGF리테일", "상향편입 삼양식품", "롯데쇼핑 편출", "왓칭콜 코스맥스", "코스맥스 2Q26"
    k = re.sub(r'(신규편입|상향편입|하향편입|왓칭콜|편출|업데이트콜|마켓콜|매크로|2Q26|1Q26|3Q26|잠정실적)', ' ', kw).strip()
    k = k.split()[0] if k else ''
    if k in ('콜',): k = ''
    k = ALIAS.get(k, k)
    if kind == '잠정실적':
        m = re.match(r'(.+?) 잠정실적', title)
        return m.group(1).strip() if m else k
    return k

def norm_rows(rows):
    """[no, title, yymmdd, cate, kw, imgs('|'), gisu] → dict"""
    out = []
    for r in rows:
        no, title, d, cate, kw, imgs, g = r
        kind = classify(title, kw or '')
        m = re.search(r'Call No\.(\d+)', title)
        out.append({'no': no, 'callNo': int(m.group(1)) if m else None, 't': title, 'd': '20' + d[:2] + '-' + d[2:4] + '-' + d[4:6],
                    'kind': kind, 'kw': kw or '', 'stock': stock_of(kind, kw or '', title), 'g': g or '',
                    'imgs': [CDN + ('info/' if p.startswith('info') else p[:8] + '/') + p for p in (imgs.split('|') if imgs else [])]})
    out.sort(key=lambda x: (x['d'], int(x['no'])), reverse=True)
    return out

def main():
    pw = os.environ.get('CALLS_PASS', '')
    if not pw:
        print('CALLS_PASS 필요'); sys.exit(1)
    cmd = sys.argv[1] if len(sys.argv) > 1 else 'decrypt'
    if cmd == 'build':
        rows = json.load(open(sys.argv[2], encoding='utf-8'))
        data = {'updated': time.strftime('%Y-%m-%d %H:%M'), 'list': norm_rows(rows)}
    elif cmd == 'merge':
        cur = decrypt(pw, open(OUT).read())
        have = {x['no'] for x in cur['list']}
        new = [x for x in norm_rows(json.load(open(sys.argv[2], encoding='utf-8'))) if x['no'] not in have]
        data = {'updated': time.strftime('%Y-%m-%d %H:%M'), 'list': sorted(cur['list'] + new, key=lambda x: (x['d'], int(x['no'])), reverse=True)}
        print('신규 %d건 병합 → 총 %d건' % (len(new), len(data['list'])), file=sys.stderr)
    elif cmd == 'setw':
        # 슬라이드 배지에서 읽은 편입 비중을 항목에 기록: {rptNo: {"w":목표비중%, "w0":이전비중%(선택), "style":"가치성장|모멘텀"(선택)}}
        cur = decrypt(pw, open(OUT).read())
        wmap = json.load(open(sys.argv[2], encoding='utf-8'))
        n = 0
        for x in cur['list']:
            if x['no'] in wmap:
                x.update({k: v for k, v in wmap[x['no']].items() if k in ('w', 'w0', 'style')}); n += 1
        data = cur; print('비중 기록 %d건' % n, file=sys.stderr)
    elif cmd == 'setsum':
        # 슬라이드를 읽고 쓴 한 줄 요약 기록: {rptNo: "요약"}
        cur = decrypt(pw, open(OUT).read())
        smap = json.load(open(sys.argv[2], encoding='utf-8'))
        n = 0
        for x in cur['list']:
            if x['no'] in smap: x['sum'] = smap[x['no']].strip(); n += 1
        data = cur; print('요약 기록 %d건' % n, file=sys.stderr)
    else:
        print(json.dumps(decrypt(pw, open(OUT).read()), ensure_ascii=False)[:3000]); return
    os.makedirs('public/data', exist_ok=True)
    open(OUT, 'w').write(encrypt(pw, data))
    print('저장 %d건 → %s' % (len(data['list']), OUT), file=sys.stderr)

if __name__ == '__main__':
    main()
