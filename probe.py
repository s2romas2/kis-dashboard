#!/usr/bin/env python3
# 1회용 진단 — 특정 회사(TARGET)의 D002 공시를 상세 분석해 왜 스크리너에 안 잡히는지 확인
import os, io, json, zipfile, re, importlib.util

spec = importlib.util.spec_from_file_location('ins', 'insider.py')
ins = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ins)

TARGET = os.environ.get('TARGET', '아가방')
reps = ins.list_reports()
out = []
for (rcept, corp, cname, dt, scode) in reps:
    if TARGET not in cname:
        continue
    info = {'rcept': rcept, 'name': cname, 'date': dt}
    try:
        b = ins.fetch('%s/document.xml?crtfc_key=%s&rcept_no=%s' % (ins.BASE, ins.DART_KEY, rcept))
        z = zipfile.ZipFile(io.BytesIO(b))
        raw = z.read(z.namelist()[0]).decode('utf-8', 'ignore')
        nm = re.search(r'ACODE="IFR_NM"[^>]*>\s*([^<]+)', raw)
        pos = re.search(r'ACODE="STF_PSM"[^>]*>\s*([^<]+)', raw)
        info['reporter'] = ins.clean(nm.group(1)) if nm else '?'
        info['position'] = ins.clean(pos.group(1)) if pos else '?'
        i = raw.find('세부변동내역')
        seg = raw[i:i + 6000] if i >= 0 else raw[:6000]
        info['seg'] = re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', seg))[:1200]
        info['parsed'] = ins.parse_doc(rcept)
    except Exception as e:
        info['err'] = repr(e)
    out.append(info)

os.makedirs('public/data', exist_ok=True)
with open('public/data/probe.json', 'w', encoding='utf-8') as f:
    json.dump({'target': TARGET, 'd002_reports_total': len(reps), 'matched': len(out), 'list': out},
              f, ensure_ascii=False)
print('probe: %s 관련 D002 %d건 / 전체 %d건' % (TARGET, len(out), len(reps)))
