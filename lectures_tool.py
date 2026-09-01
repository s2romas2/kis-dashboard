#!/usr/bin/env python3
# 🎓 강의 노트 — 팀더윤쎈 강의 녹음+요약 암호화 도구 (본인 전용)
# 사용: LEC_PASS=... python3 lectures_tool.py encaudio /tmp/lec/2강.webm 2   # 오디오 암호화 → public/data/lectures/gN.enc
#       LEC_PASS=... python3 lectures_tool.py build /tmp/lec/meta.json           # 메타+요약 → public/data/lectures.enc
#       LEC_PASS=... python3 lectures_tool.py decrypt                            # 메타 열람
# 포맷: base64( salt16 | iv12 | AES-GCM ), 키 = PBKDF2-SHA256(pass, salt, 200000, 32)
import os, sys, json, base64, time
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

META = 'public/data/lectures.enc'
ADIR = 'public/data/lectures'
ITER = 200000

def key_of(pw, salt): return PBKDF2HMAC(hashes.SHA256(), 32, salt, ITER).derive(pw.encode())
def enc_bytes(pw, data):
    salt, iv = os.urandom(16), os.urandom(12)
    ct = AESGCM(key_of(pw, salt)).encrypt(iv, data, None)
    return base64.b64encode(salt + iv + ct).decode()
def dec_bytes(pw, b64):
    raw = base64.b64decode(b64); salt, iv, ct = raw[:16], raw[16:28], raw[28:]
    return AESGCM(key_of(pw, salt)).decrypt(iv, ct, None)
def encrypt(pw, obj): return enc_bytes(pw, json.dumps(obj, ensure_ascii=False).encode())
def decrypt(pw, b64): return json.loads(dec_bytes(pw, b64).decode())

def main():
    pw = os.environ.get('LEC_PASS',''); 
    if not pw: print('LEC_PASS 필요'); sys.exit(1)
    cmd = sys.argv[1] if len(sys.argv)>1 else 'decrypt'
    if cmd == 'encaudio':
        src, g = sys.argv[2], sys.argv[3]
        os.makedirs(ADIR, exist_ok=True)
        b64 = enc_bytes(pw, open(src,'rb').read())
        out = '%s/g%s.enc' % (ADIR, g); open(out,'w').write(b64)
        print('오디오 암호화 %s → %s (%.1fMB)' % (src, out, len(b64)/1048576), file=sys.stderr)
    elif cmd == 'build':
        meta = json.load(open(sys.argv[2], encoding='utf-8'))
        data = {'updated': time.strftime('%Y-%m-%d %H:%M'), 'list': meta}
        os.makedirs('public/data', exist_ok=True)
        open(META,'w').write(encrypt(pw, data))
        print('메타 저장 %d강 → %s' % (len(meta), META), file=sys.stderr)
    else:
        print(json.dumps(decrypt(pw, open(META).read()), ensure_ascii=False)[:2000])

if __name__ == '__main__': main()
