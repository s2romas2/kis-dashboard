#!/usr/bin/env python3
# 네이버 데이터랩 웹 요청 형식 진단 (공식 API 종료 대응)
# trendSearch 페이지와 JS 번들에서 qcHash 요청 파라미터 구성을 추출해 커밋
import json, re, time, urllib.request, urllib.parse

OUT = 'public/data/datalab_probe.json'
UA = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36'}
R = {'steps': []}

def fetch(url, headers=None, data=None):
    req = urllib.request.Request(url, data=data, headers=dict(UA, **(headers or {})))
    return urllib.request.urlopen(req, timeout=30).read().decode('utf-8', 'ignore')

try:
    h = fetch('https://datalab.naver.com/keyword/trendSearch.naver')
    R['steps'].append('페이지 %d바이트' % len(h))
    scripts = re.findall(r'<script[^>]+src="([^"]+)"', h)
    R['scripts'] = scripts
    # 히든 인풋 전부
    R['hidden'] = re.findall(r'<input type="hidden"[^>]*id="([^"]+)"[^>]*value="([^"]*)"', h)
    # 인라인 스크립트에서 qcHash 주변
    R['inline_qc'] = [m[:400] for m in re.findall(r'[^\n]{0,200}qcHash[^\n]{0,200}', h)]
    # JS 번들에서 qcHash/queryGroups 주변 추출
    R['js_qc'] = []
    for s in scripts[:8]:
        u = s if s.startswith('http') else ('https://datalab.naver.com' + s)
        try:
            js = fetch(u)
            for pat in ('qcHash', 'queryGroups', 'trendSearch'):
                for m in re.findall(r'.{0,250}' + pat + r'.{0,250}', js)[:4]:
                    R['js_qc'].append({'src': u.split('/')[-1][:40], 'pat': pat, 'ctx': m})
            # ajax POST 데이터 구성부 (qcHash.naver 뒤 900자)
            for m in re.findall(r'qcHash\.naver[\s\S]{0,900}', js)[:2]:
                R['js_qc'].append({'src': u.split('/')[-1][:40], 'pat': 'ajax_data', 'ctx': m})
            # keywordForm 직렬화 함수
            for m in re.findall(r'getKeywordGroup[\s\S]{0,500}|serializeArray[\s\S]{0,300}', js)[:3]:
                R['js_qc'].append({'src': u.split('/')[-1][:40], 'pat': 'form', 'ctx': m})
        except Exception as e:
            R['js_qc'].append({'src': u[:60], 'err': repr(e)})
        time.sleep(0.5)
except Exception as e:
    R['steps'].append('실패: %r' % e)

# qcType 후보값 일괄 테스트 (구분자 __OUML__/__SZLIG__ 확인됨)
R['try'] = []
qg = '반도체__SZLIG__반도체,HBM__OUML__AI__SZLIG__인공지능,챗GPT'
for qc in ('N', 'C', 'P', 'S', 'T', 'K', '0', '1', '2', ''):
    for tu in ('date', 'week'):
        try:
            body = urllib.parse.urlencode({'qcType': qc, 'queryGroups': qg,
                'startDate': '2024-01-01', 'endDate': '2026-08-01', 'timeUnit': tu,
                'gender': '', 'age': '', 'device': ''}).encode()
            r = fetch('https://datalab.naver.com/qcHash.naver',
                      headers={'Referer': 'https://datalab.naver.com/keyword/trendSearch.naver',
                               'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
                               'X-Requested-With': 'XMLHttpRequest',
                               'Origin': 'https://datalab.naver.com'}, data=body)
            R['try'].append({'qc': qc, 'tu': tu, 'r': r[:160]})
            if '"success":true' in r:
                # 성공 시 결과 페이지에서 데이터 위치 확인
                hk = json.loads(r).get('hashKey', '')
                r2 = fetch('https://datalab.naver.com/keyword/trendResult.naver?hashKey=' + hk,
                           headers={'Referer': 'https://datalab.naver.com/keyword/trendSearch.naver'})
                idx = max(r2.find('chartData'), r2.find('"data"'), r2.find('graph'))
                R['try'].append({'result_page': len(r2), 'peek': r2[max(0, idx - 50):idx + 500] if idx > 0 else r2[:500]})
                break
        except Exception as e:
            R['try'].append({'qc': qc, 'tu': tu, 'err': repr(e)[:120]})
        time.sleep(1.2)
    else:
        continue
    break

R['updated'] = time.strftime('%Y-%m-%d %H:%M')
with open(OUT, 'w', encoding='utf-8') as f:
    json.dump(R, f, ensure_ascii=False)
print('완료', R['steps'])
