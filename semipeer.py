#!/usr/bin/env python3
# 반도체 peer 상대밸류 — "peer보다 싼데 이익 체력은 같거나 더 좋은 기업" 찾기
#   peer 정의 : public/data/semipeer_def.json (쌍별 5기준 점수·근거 인용, tools/semipeer/merge_def.py가 생성)
#               A·B등급 쌍만 저밸류 판정에 쓰고 C등급은 참고용으로만 계산한다.
#   재무(확인값): OpenDART — 최근 4분기 합산(TTM) 매출·영업이익·순이익·자본
#               ① 다중회사 주요계정(fnlttMultiAcnt)   → 매출·영업이익·당기순이익·자본총계
#               ② 단일회사 전체재무제표(fnlttSinglAcntAll, 연결만) → 지배주주 순이익·지배주주 자본(비지배지분 제거)
#               TTM = 올해 누적 + 전년 연간 − 전년 동기 누적 (EPS 절대값은 기업 간 비교 불가 → 쓰지 않음)
#   시세        : stockvals.json(KIS 일일 수집) 시총·현재가.  우선주 상장사는 우선주 시총을 더해 보정
#   선행(증권사 추정): peg.json(소부장 맵) / 그 밖은 네이버 컨센서스(FnGuide)
#   국면·분기 추이: hege.json (투자의 定石 헤게모니 4국면, 최근 8분기 매출·영업이익)
#   공정 구분   : semipeer_def.json의 stage(전공정·후공정·전후·공통 인프라·칩 제조·설계·모듈유통)
#   표시 방식   : 합산 점수 없이 "사실 꼬리표"만 — 대표는 peer 대비 저PER/비슷/고PER, 그 밖에 PBR·PSR·ROE·영업이익률·성장률·ROA·부채비율을
#                 각각 peer(A·B등급) 중앙값과 비교해 낮음/비슷/높음으로 표시한다. 판단은 사용자가 한다.
#   기준(basis) 우선순위: TTM = DART 최근 4분기(확인값) > TTMN = 네이버(FnGuide) 최근 4분기 주당순이익·주당순자산(DART 수집 전 임시·교차확인용)
#                        > FY0 = KIS 전년 확정 실적. 쌍 비교는 두 기업이 함께 가진 가장 좋은 기준으로 맞춘다.
#   DART 고유번호 파일(corpCode.xml)이 점검 중일 때를 대비해 tools/semipeer/dartcorp.json(종목코드→고유번호)을 시드로 쓴다.
#   책정값(val)  : 평가법마다 실제로 계산한 값 — 이 회사 배수·peer 중앙값·환산 주가·범위·DCF(11/20 추가). 재료(순차입금·감가상각비·영업현금흐름·설비투자)는
#                 ②에서 이미 받는 전체재무제표 응답에서 함께 뽑는다(finx 캐시). 별도 재무제표만 있는 종목은 fs_div=OFS로 같은 보고서를 받는다.
# 필요 시크릿: DART_API_KEY(권장)   결과: public/data/semipeer.json
import os, sys, json, time, re, io, zipfile, datetime, urllib.request, ssl, statistics, math
import xml.etree.ElementTree as ET

KEY = os.environ.get('DART_API_KEY', '')
DD = os.environ.get('DATA_DIR', 'public/data')
OUT = os.environ.get('OUT', os.path.join(DD, 'semipeer.json'))
OFFLINE = os.environ.get('OFFLINE', '') == '1'          # 네트워크 호출 없이 기존 파일만으로 계산(로컬 검증용)
REFRESH = os.environ.get('REFRESH', '') == '1'          # 재무 캐시 강제 갱신
FIN_TTL_DAYS = int(os.environ.get('FIN_TTL_DAYS', '6'))
CHUNK = int(os.environ.get('CHUNK', '50'))
UA = {'User-Agent': 'Mozilla/5.0'}
CTX = ssl.create_default_context(); CTX.check_hostname = False; CTX.verify_mode = ssl.CERT_NONE
KST = datetime.timezone(datetime.timedelta(hours=9)); NOW = datetime.datetime.now(KST); TODAY = NOW.date()
EOK = 1e8
FIN_VER = 3      # 재무 캐시 형식 버전(2: 자산총계·부채총계 추가, 3: 밸류 재료 finx 추가) — 바뀌면 다음 실행에서 DART를 다시 받는다
SEED_CORP = os.environ.get('SEED_CORP', 'tools/semipeer/dartcorp.json')
DEBUG = []
# 우선주가 따로 상장된 기업: 보통주 시총만 쓰면 PER·PBR이 낮게 나오므로 우선주 시총을 더한다
PREF = {'005930': ['005935'], '009150': ['009155'], '006400': ['006405'], '007810': ['007815'], '353200': ['35320K']}

def log(s): DEBUG.append(str(s)[:300]); print(s, file=sys.stderr, flush=True)
def fetch(url, timeout=60, tries=3):
    err = None
    for i in range(tries):
        try:
            return urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout, context=CTX).read()
        except Exception as e:
            err = e; time.sleep(2 * (i + 1))
    log('fetch 실패 %s %r' % (re.sub(r'crtfc_key=[^&]+', 'crtfc_key=***', url)[:110], err)); return b''
def jget(url, **kw):
    try: return json.loads(fetch(url, **kw).decode('utf-8'))
    except Exception: return {}
def tonum(s):
    try:
        s = str(s).replace(',', '').strip()
        if s in ('', '-', 'None'): return None
        return float(s)
    except Exception: return None
def load(name, default=None):
    try: return json.load(open(os.path.join(DD, name), encoding='utf-8'))
    except Exception as e:
        log('%s 로드 실패 %r' % (name, e)); return default
def rnd(v, n=2): return None if v is None else round(v, n)
def div(a, b): return None if (a is None or b is None or b == 0) else a / b

# ───────── 성장률(적자·흑전 처리: 흑자전환 = +500% 캡, 적자전환·확대 = −200% — hege.py와 같은 규칙)
def growth(cur, prev):
    if cur is None or prev is None: return None
    if prev == 0: return 500.0 if cur > 0 else (-200.0 if cur < 0 else None)
    if prev > 0 and cur < 0: return -200.0
    if prev < 0 and cur < 0: return -200.0 if cur < prev else min(500.0, (cur - prev) / abs(prev) * 100)
    if prev < 0 and cur >= 0: return 500.0
    return max(-200.0, min(500.0, (cur - prev) / abs(prev) * 100))

# ───────── DART
REPRT = {1: '11013', 2: '11012', 3: '11014', 4: '11011'}
def latest_quarter(today=None):
    """공시 마감 기준으로 나와 있을 최신 분기 (연, 분기)"""
    t = today or TODAY; y, md = t.year, (t.month, t.day)
    if md >= (11, 14): return (y, 3)
    if md >= (8, 14): return (y, 2)
    if md >= (5, 15): return (y, 1)
    if md >= (3, 31): return (y - 1, 4)
    return (y - 1, 3)
def reports_for(y, q):
    """TTM·전년 TTM 계산에 필요한 보고서: 올해 누적, 전년 동기, 전전년 동기, 전년 연간, 전전년 연간"""
    if q == 4: return [(y, 4), (y - 1, 4)]
    return [(y, q), (y - 1, q), (y - 2, q), (y - 1, 4), (y - 2, 4)]

def dart_corpcodes():
    b = fetch('https://opendart.fss.or.kr/api/corpCode.xml?crtfc_key=' + KEY, timeout=90)
    if not b: return {}
    try:
        z = zipfile.ZipFile(io.BytesIO(b)); xml = z.read(z.namelist()[0])
    except Exception as e:
        log('corpCode zip 실패 %r %s' % (e, b[:120])); return {}
    m = {}
    for el in ET.fromstring(xml).iter('list'):
        sc = (el.findtext('stock_code') or '').strip()
        if re.fullmatch(r'[0-9A-Z]{6}', sc): m[sc] = el.findtext('corp_code')
    log('DART 고유번호 %d개' % len(m)); return m

REV_PRI = {'매출액': 0, '수익(매출액)': 1, '매출': 2, '영업수익': 3, '순영업수익': 4, '매출및지분법손익': 5}
def acct_key(nm, sj):
    """주요계정 이름 → (키, 우선순위). 낮을수록 우선."""
    nm = (nm or '').replace(' ', '')
    if sj == 'BS':
        return {'자본총계': ('eq', 0), '자산총계': ('as', 0), '부채총계': ('li', 0)}.get(nm, (None, 9))
    if nm in REV_PRI: return ('rev', REV_PRI[nm])
    if nm.startswith('매출액') or nm.startswith('수익(매출'): return ('rev', 6)
    if nm in ('영업이익', '영업이익(손실)'): return ('op', 0)
    if nm.startswith('영업이익(') and '률' not in nm: return ('op', 1)
    if nm in ('당기순이익', '당기순이익(손실)'): return ('ni', 0)
    if nm in ('분기순이익', '분기순이익(손실)', '반기순이익', '반기순이익(손실)'): return ('ni', 1)
    if re.fullmatch(r'(연결)?(당기|분기|반기)순(이익|손익)(\(손실\))?', nm): return ('ni', 2)
    return (None, 9)

def parse_multi(rows, year, q, store):
    """fnlttMultiAcnt 응답 rows → store[corp][(year,q)][fs][key] = {'cum': 누적(손익)/기말(자본), 'pri'}"""
    for r in rows or []:
        sj = r.get('sj_div') or ''; fs = r.get('fs_div') or 'OFS'; corp = r.get('corp_code')
        key, pri = acct_key(r.get('account_nm'), sj)
        if key is None or not corp: continue
        amt = tonum(r.get('thstrm_amount')); add = tonum(r.get('thstrm_add_amount'))
        if key in ('eq', 'as', 'li'): cum = amt
        elif q == 4: cum = amt
        else: cum = add if add is not None else amt          # 분기·반기보고서 손익: 누적(add) 우선 (1분기는 3개월 = 누적)
        if cum is None: continue
        d = store.setdefault(corp, {}).setdefault((year, q), {'CFS': {}, 'OFS': {}}).setdefault(fs, {})
        if key in d and d[key]['pri'] <= pri: continue
        d[key] = {'cum': cum, 'pri': pri}

def dart_multi(corps, year, q, store):
    url = ('https://opendart.fss.or.kr/api/fnlttMultiAcnt.json?crtfc_key=%s&corp_code=%s&bsns_year=%d&reprt_code=%s'
           % (KEY, ','.join(corps), year, REPRT[q]))
    j = jget(url); st = j.get('status')
    if st == '020': log('DART 사용 한도 초과'); return 'quota'
    if st not in ('000', '013'): log('DART multi %d/%dQ status=%s %s' % (year, q, st, j.get('message'))); return 'err'
    parse_multi(j.get('list'), year, q, store); return 'ok'

def ttm_from(store_corp, y, q):
    """연결 우선(없으면 별도)으로 TTM·전년 TTM·자본을 계산. 반환 dict(단위 억) 또는 None"""
    for fs in ('CFS', 'OFS'):
        def g(yy, qq, k):
            v = (((store_corp.get((yy, qq)) or {}).get(fs) or {}).get(k) or {}).get('cum')
            return v
        out = {'fs': fs}
        ok = 0
        for k in ('rev', 'op', 'ni'):
            if q == 4:
                cur, prev = g(y, 4, k), g(y - 1, 4, k)
            else:
                a, b, c = g(y, q, k), g(y - 1, 4, k), g(y - 1, q, k)
                cur = None if None in (a, b, c) else a + b - c
                a2, b2, c2 = c, g(y - 2, 4, k), g(y - 2, q, k)
                prev = None if None in (a2, b2, c2) else a2 + b2 - c2
            out[k] = None if cur is None else cur / EOK
            out[k + '_prev'] = None if prev is None else prev / EOK
            if cur is not None: ok += 1
        eq = g(y, q, 'eq'); eq0 = g(y - 1, q, 'eq')
        out['eq'] = None if eq is None else eq / EOK
        out['eq_prev'] = None if eq0 is None else eq0 / EOK
        for k in ('as', 'li'):                                   # 자산총계·부채총계(기말) — ROA·부채비율용
            v = g(y, q, k); out[k] = None if v is None else v / EOK
        if ok >= 2 and out['rev'] is not None and out['rev'] > 0:
            return out
    return None

# 전체재무제표에서 지배주주 몫만 뽑는다(account_id는 ifrs-full_… / ifrs-full:… 두 표기 모두 허용)
def _aid(a): return (a or '').replace(':', '_').strip()
NIP_IDS = {'ifrs-full_ProfitLossAttributableToOwnersOfParent'}
EQP_IDS = {'ifrs-full_EquityAttributableToOwnersOfParent'}
NIP_PAT = re.compile(r'지배(기업|회사|주주)')
EQP_PAT = re.compile(r'^지배(기업|회사|주주).*(지분|자본)')
def parse_full(rows, q):
    """fnlttSinglAcntAll rows → {'ni_p': 누적 지배주주 순이익, 'eq_p': 지배주주 자본} (원)"""
    out = {}
    for r in rows or []:
        sj = r.get('sj_div') or ''; aid = _aid(r.get('account_id')); nm = (r.get('account_nm') or '').replace(' ', '')
        if sj in ('IS', 'CIS'):
            if 'ni_p' in out or 'ComprehensiveIncome' in aid: continue
            add = tonum(r.get('thstrm_add_amount')); amt = tonum(r.get('thstrm_amount'))
            v = amt if q == 4 else (add if add is not None else amt)
            if v is None: continue
            if aid in NIP_IDS: out['ni_p'] = v
            elif ('비지배' not in nm and '포괄' not in nm and '주당' not in nm and NIP_PAT.search(nm)
                  and any(k in nm for k in ('순이익', '순손익', '귀속', '소유주', '지분'))):
                out['ni_p'] = v
        elif sj == 'BS':
            if 'eq_p' in out: continue
            v = tonum(r.get('thstrm_amount'))
            if v is None: continue
            if aid in EQP_IDS or ('비지배' not in nm and EQP_PAT.search(nm)): out['eq_p'] = v
    return out
def dart_full(corp, year, q):
    j = jget('https://opendart.fss.or.kr/api/fnlttSinglAcntAll.json?crtfc_key=%s&corp_code=%s&bsns_year=%d&reprt_code=%s&fs_div=CFS'
             % (KEY, corp, year, REPRT[q]))
    st = j.get('status')
    if st == '020': return 'quota'
    if st != '000': return None
    return parse_full(j.get('list'), q)

# ───────── 밸류 재료(순차입금·EBITDA·FCF) — 전체 재무제표(fnlttSinglAcntAll) 확장 파서
#   이미 받는 응답(올해 누적·전년 연간·전년 동기 3개 보고서)에서 뽑으므로 연결 종목은 추가 호출이 없다.
#   별도 재무제표만 내는 종목은 fs_div=OFS로 같은 3개 보고서를 새로 받는다(종목당 3콜, 사업보고서 분기는 1콜).
#   못 뽑은 항목은 None + 이유 코드(why). 0으로 덮어쓰지 않는다. '계정이 아예 없음 = 0'으로 본 항목은 src에 none0으로 남긴다.
XV = 1           # 확장 항목 파서 버전 — 바뀌면 다음 실행에서 다시 받는다
def tonum2(s):
    """금액 문자열 → float. '-'·빈칸 → None, '(1,234)'·'△1,234' → 음수"""
    if s is None: return None
    s = str(s).replace(',', '').replace(' ', '').replace('　', '').strip()
    if s in ('', '-', '－', '–', '—', 'None', 'null', 'N/A'): return None
    neg = False
    if s.startswith('(') and s.endswith(')'): neg = True; s = s[1:-1]
    if s[:1] in ('△', '▲', '▵', '−'): neg = True; s = s[1:]
    try: v = float(s)
    except Exception: return None
    return -v if neg else v
def _nmz(nm):
    """계정 이름 정리: 공백·머리 번호(Ⅰ. / 1. / (1))·꼬리 주석 표시 제거"""
    nm = re.sub(r'\s+', '', nm or '')
    nm = re.sub(r'^(?:[ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩ]+|[IVX]+|\d+)[\.\)]', '', nm)
    nm = re.sub(r'^\([0-9가-힣]\)', '', nm)
    nm = re.sub(r'\((?:주석?|註)[^)]*\)$', '', nm)
    return nm
SEC_ID = {'ifrs-full_CurrentAssets': 'ca', 'ifrs-full_NoncurrentAssets': 'nca', 'ifrs-full_Assets': 'A', 'ifrs-full_CurrentLiabilities': 'cl',
          'ifrs-full_NoncurrentLiabilities': 'ncl', 'ifrs-full_Liabilities': 'L', 'ifrs-full_Equity': 'E', 'ifrs-full_EquityAndLiabilities': 'E'}
SEC_NM = {'유동자산': 'ca', '비유동자산': 'nca', '자산총계': 'A', '유동부채': 'cl', '비유동부채': 'ncl', '부채총계': 'L', '자본총계': 'E',
          '부채와자본총계': 'E', '자본과부채총계': 'E', '부채및자본총계': 'E', '자본및부채총계': 'E'}
CASH_ID = {'ifrs-full_CashAndCashEquivalents'}
CASH_PAT = re.compile(r'^(현금및현금성자산|현금및현금등가물|현금및예치금)$')
STFI_ID = {'dart_ShortTermDepositsNotClassifiedAsCashEquivalents', 'ifrs-full_ShorttermDepositsNotClassifiedAsCashEquivalents'}
STFI_PAT = re.compile(r'^(단기금융상품|단기예금|정기예금|단기금융기관예치금|유동금융기관예치금|금융기관예치금|단기예치금|유동성?예치금)$')
OFA_ID = {'ifrs-full_OtherCurrentFinancialAssets', 'ifrs-full_CurrentFinancialAssets', 'ifrs-full_CurrentFinancialAssetsAtFairValueThroughProfitOrLoss',
          'ifrs-full_CurrentFinancialAssetsAtAmortisedCost', 'dart_ShortTermInvestmentAssets'}
OFA_PAT = re.compile(r'^(기타유동금융자산|유동금융자산|기타단기금융자산|단기금융자산|단기투자자산|단기투자증권|단기매매증권|단기매매금융자산'
                     r'|(유동성?|단기)(당기손익|상각후원가|기타포괄손익)-?(공정가치)?(측정)?(인식)?금융자산|당기손익-?공정가치(측정)?금융자산|상각후원가(측정)?금융자산)$')
DEBT_ID = {'ifrs-full_ShorttermBorrowings': 'st', 'dart_ShortTermBorrowings': 'st', 'ifrs-full_CurrentBorrowings': 'st',
           'ifrs-full_CurrentBorrowingsAndCurrentPortionOfNoncurrentBorrowings': 'st',
           'ifrs-full_CurrentPortionOfLongtermBorrowings': 'cl', 'dart_CurrentPortionOfLongTermBorrowings': 'cl', 'dart_CurrentPortionOfLongTermDebt': 'cl',
           'ifrs-full_LongtermBorrowings': 'lt', 'dart_LongTermBorrowingsGross': 'lt', 'dart_LongTermBorrowings': 'lt',
           'ifrs-full_NoncurrentPortionOfNoncurrentBorrowings': 'lt', 'ifrs-full_NoncurrentBorrowings': 'lt',
           'dart_BondsIssued': 'bond', 'ifrs-full_BondsIssued': 'bond', 'dart_CurrentPortionOfBonds': 'bond', 'dart_ConvertibleBonds': 'bond',
           'dart_CurrentPortionOfConvertibleBonds': 'bond', 'dart_BondsWithWarrants': 'bond', 'dart_ExchangeableBonds': 'bond',
           'ifrs-full_CurrentBondsIssuedAndCurrentPortionOfNoncurrentBondsIssued': 'bond', 'ifrs-full_NoncurrentPortionOfNoncurrentBondsIssued': 'bond',
           'ifrs-full_CurrentLeaseLiabilities': 'lease', 'ifrs-full_NoncurrentLeaseLiabilities': 'lease', 'ifrs-full_LeaseLiabilities': 'lease'}
DEBT_PAT = re.compile(r'차입금|차입부채|유동성장기부채|사채|리스부채|우선주부채|전환권조정|신주인수권조정')
DEBT_NOT = re.compile(r'이자|파생|보증|충당|관련|평가|상환이익|상환손실')       # 미지급 사채이자·전환사채 파생상품부채 등은 빚의 원금이 아니다
NCI_ID = {'ifrs-full_NoncontrollingInterests'}
NCI_PAT = re.compile(r'^비지배(주주)?지분$')
CFO_ID = {'ifrs-full_CashFlowsFromUsedInOperatingActivities'}
CFO_PAT = re.compile(r'^영업활동(으로인한|으로부터의|에서의|에의한|으로인한순|순)?(순)?현금(흐름|유입|유출)')
CAPEX_ID = {'ifrs-full_PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities'}
CAPEX_PAT = re.compile(r'^유형자산의?(취득|증가)$')
CAPEX_PART = re.compile(r'^(건설중인자산|토지|건물|구축물|기계장치|차량운반구|공구와기구|공기구비품|공기구|비품|집기비품|시설장치|금형|기타유형자산|기타의유형자산|임차자산개량권?)의?(취득|증가)$')
CAPEXI_ID = {'ifrs-full_PurchaseOfIntangibleAssetsClassifiedAsInvestingActivities'}
CAPEXI_PAT = re.compile(r'^(무형자산|개발비|소프트웨어|산업재산권|기타무형자산|기타의무형자산)의?(취득|증가)$')
DEP_ID = {'ifrs-full_AdjustmentsForDepreciationExpense', 'ifrs-full_AdjustmentsForDepreciationAndAmortisationExpense', 'ifrs-full_DepreciationExpense',
          'ifrs-full_DepreciationAndAmortisationExpense', 'ifrs-full_DepreciationRightofuseAssets', 'dart_DepreciationExpense',
          'ifrs-full_DepreciationPropertyPlantAndEquipment', 'ifrs-full_DepreciationInvestmentProperty'}
AMO_ID = {'ifrs-full_AdjustmentsForAmortisationExpense', 'ifrs-full_AmortisationExpense', 'dart_AmortisationExpense', 'ifrs-full_AmortisationIntangibleAssetsOtherThanGoodwill'}
DEP_PAT = re.compile(r'감가상각')
AMO_PAT = re.compile(r'(무형자산|사용권자산|개발비|리스자산|투자부동산)상각')
DA_NOT = re.compile(r'대손|차금|할인|사채|채권|이연|현재가치|누계|손상|환입|처분')   # 대손상각비·사채할인발행차금상각 등은 감가상각이 아니다

def _flow(r, q, cf):
    """손익·현금흐름 행 → (당기 누적, 전년 동기 누적). 분기·반기 손익은 누적(add) 우선, 현금흐름표는 원래 누적만 싣는다."""
    amt = tonum2(r.get('thstrm_amount')); add = tonum2(r.get('thstrm_add_amount'))
    cur = amt if q == 4 else (add if add is not None else amt)
    if q == 4: prv = tonum2(r.get('frmtrm_amount'))
    elif cf:
        prv = next((v for v in (tonum2(r.get('frmtrm_q_amount')), tonum2(r.get('frmtrm_add_amount')), tonum2(r.get('frmtrm_amount'))) if v is not None), None)
    else:
        prv = tonum2(r.get('frmtrm_add_amount'))
        if prv is None and q == 1: prv = tonum2(r.get('frmtrm_q_amount'))
    return cur, prv
def _ord(rows):
    """sj_div 안에서 ord(표시 순서)가 모두 숫자면 그 순서로, 아니면 응답 순서 그대로"""
    try: return sorted(rows, key=lambda r: int(r['ord']))
    except Exception: return rows
def _drop_parent(items):
    """합계 계정과 그 내역이 함께 실린 경우(예: 차입금 = 단기차입금 + 유동성장기부채) 합계 쪽을 뺀다 — 두 번 세지 않기"""
    out = []; n = len(items)
    for i, it in enumerate(items):
        dup = False
        for j in range(2, 5):
            seg = items[i + 1:i + 1 + j]
            if len(seg) == j and abs(sum(s[1] for s in seg) - it[1]) <= max(1.0, abs(it[1]) * 1e-9) and it[1] != 0: dup = True; break
        if not dup: out.append(it)
    return out
def parse_ext(rows, q):
    """fnlttSinglAcntAll rows → 밸류 재료(원).
       반환 {'has_bs', 'has_cf', 'bs': {cash, stfi, ofa, st, cl, lt, bond, lease, nci}, 'fl': {cfo, capex, capex_i, dep, amo: (당기 누적, 전년 동기 누적)}, 'src': {키: id|nm|parts|is|none0}}"""
    rows = rows or []
    bsr = _ord([r for r in rows if (r.get('sj_div') or '') == 'BS'])
    cfr = [r for r in rows if (r.get('sj_div') or '') == 'CF']
    isr = [r for r in rows if (r.get('sj_div') or '') in ('IS', 'CIS')]
    out = {'has_bs': bool(bsr), 'has_cf': bool(cfr), 'bs': {}, 'fl': {}, 'src': {}}
    bs, src = out['bs'], out['src']
    # ── 재무상태표: 구획(유동자산 → 비유동자산 → 자산총계 → 유동부채 → 비유동부채 → 부채총계 → 자본)을 따라가며 읽는다
    def sec_of(r):
        nm = _nmz(r.get('account_nm')); nm = re.sub(r'^(유동자산|비유동자산|유동부채|비유동부채)(합계|총계|계)$', r'\1', nm); nm = re.sub(r'^(자산|부채|자본)(합계)$', r'\1총계', nm)
        return SEC_ID.get(_aid(r.get('account_id'))) or SEC_NM.get(nm)
    has_sec = any(sec_of(r) == 'A' for r in bsr)
    sec = None; debts = []; stfi = []; ofa = []; dby = set()
    for r in bsr:
        aid = _aid(r.get('account_id')); nm = _nmz(r.get('account_nm')); s = sec_of(r)
        if s:
            sec = {'ca': 'ca', 'nca': 'nca', 'A': 'l?', 'cl': 'cl', 'ncl': 'ncl', 'L': 'eq', 'E': 'eq'}[s]; continue
        v = tonum2(r.get('thstrm_amount'))
        if v is None: continue
        asset = (sec in (None, 'ca', 'nca')) if has_sec else True
        liab = (sec in ('l?', 'cl', 'ncl')) if has_sec else True
        if aid in NCI_ID or NCI_PAT.match(nm):
            if 'nci' not in bs: bs['nci'] = v; src['nci'] = 'id' if aid in NCI_ID else 'nm'
            continue
        if asset:
            if aid in CASH_ID or CASH_PAT.match(nm):
                if 'cash' not in bs: bs['cash'] = v; src['cash'] = 'id' if aid in CASH_ID else 'nm'
                continue
            if sec != 'nca' and (aid in STFI_ID or STFI_PAT.match(nm)): stfi.append((nm, v)); src['stfi'] = 'id' if aid in STFI_ID else src.get('stfi', 'nm'); continue
            if (sec == 'ca' or (sec is None and re.match(r'^(유동|단기|기타유동|기타단기)', nm))) and (aid in OFA_ID or OFA_PAT.match(nm)): ofa.append((nm, v)); continue
        if liab and '자산' not in nm and '채권' not in nm:
            k = DEBT_ID.get(aid); by = 'id' if k else None
            if k is None and DEBT_PAT.search(nm) and not DEBT_NOT.search(nm):
                by = 'nm'
                if '리스부채' in nm: k = 'lease'
                elif re.search(r'우선주부채|전환권조정|신주인수권조정', nm) or ('사채' in nm and '차입' not in nm): k = 'bond'
                elif '유동성' in nm: k = 'cl'
                elif '단기' in nm: k = 'st'
                elif '장기' in nm: k = 'lt'
                else: k = 'st' if sec == 'cl' else 'lt'
            if k: dby.add(by)
            if k: debts.append((k, v, nm))
    if bsr:
        if stfi: bs['stfi'] = sum(v for _, v in stfi)
        else: bs['stfi'] = 0.0; src['stfi'] = 'none0'
        if ofa: bs['ofa'] = sum(v for _, v in ofa)
        debts = _drop_parent(debts)
        for k in ('st', 'cl', 'lt', 'bond', 'lease'): bs[k] = sum(v for kk, v, _ in debts if kk == k)
        bs['n_debt'] = len(debts)
        src['debt'] = 'none0' if not debts else 'id' if dby == {'id'} else 'nm' if dby == {'nm'} else 'id+nm'
        if 'nci' not in bs: bs['nci'] = 0.0; src['nci'] = 'none0'
    # ── 현금흐름표
    fl = out['fl']
    def add(k, r, cf=True):
        c, p = _flow(r, q, cf)
        if c is None and p is None: return False
        a = fl.get(k) or (None, None)
        fl[k] = ((a[0] or 0.0) + c if c is not None else a[0], (a[1] or 0.0) + p if p is not None else a[1]); return True
    parts = []
    for r in cfr:
        aid = _aid(r.get('account_id')); nm = _nmz(r.get('account_nm'))
        if aid in CFO_ID or (CFO_PAT.match(nm) and '조정' not in nm and '창출' not in nm):
            if 'cfo' not in fl and add('cfo', r): src['cfo'] = 'id' if aid in CFO_ID else 'nm'
        elif aid in CAPEX_ID or CAPEX_PAT.match(nm):
            if add('capex', r): src['capex'] = 'id' if aid in CAPEX_ID else 'nm'
        elif CAPEX_PART.match(nm): parts.append(r)
        elif aid in CAPEXI_ID or CAPEXI_PAT.match(nm):
            if add('capex_i', r): src['capex_i'] = 'id' if aid in CAPEXI_ID else 'nm'
        elif (aid in DEP_ID or DEP_PAT.search(nm)) and not DA_NOT.search(nm):
            if add('dep', r): src['dep'] = 'id' if aid in DEP_ID else src.get('dep', 'nm')
        elif (aid in AMO_ID or AMO_PAT.search(nm)) and not DA_NOT.search(nm):
            if add('amo', r): src['amo'] = 'id' if aid in AMO_ID else src.get('amo', 'nm')
    if parts:                                             # 자산 종류별 취득(건설중인자산·기계장치 등)이 따로 적힌 회사
        main = fl.pop('capex', None)
        for r in parts: add('capex', r)
        pt = fl.pop('capex', None)
        if main is None:
            if pt is not None: fl['capex'] = pt; src['capex'] = 'parts'
        elif pt is None or (pt[0] is not None and main[0] is not None and abs(abs(pt[0]) - abs(main[0])) <= max(1.0, abs(main[0]) * 1e-9)):
            fl['capex'] = main                              # '유형자산의 취득'이 종류별 줄의 합계 — 합계만 쓴다(두 번 세지 않기)
        else:                                               # 합계가 아니라 나란히 적힌 별개 줄 — 더한다
            sm = lambda a, b: None if (a is None and b is None) else abs(a or 0.0) + abs(b or 0.0)
            fl['capex'] = (sm(main[0], pt[0]), sm(main[1], pt[1])); src['capex'] = 'nm+parts'
    by_nature = any(re.search(r'재고자산의?변동|원재료.*사용|종업원급여', _nmz(r.get('account_nm'))) for r in isr)
    if 'dep' not in fl and by_nature:                     # 현금흐름표 본문에 없으면 손익계산서가 '성격별 분류'일 때만 거기서(기능별의 판관비 내역은 일부라 쓰지 않는다)
        for r in isr:
            aid = _aid(r.get('account_id')); nm = _nmz(r.get('account_nm'))
            if (aid in DEP_ID or DEP_PAT.search(nm)) and not DA_NOT.search(nm):
                if add('dep', r, False): src['dep'] = 'is'
            elif (aid in AMO_ID or AMO_PAT.search(nm)) and not DA_NOT.search(nm):
                if add('amo', r, False): src['amo'] = 'is'
    for k in ('capex', 'capex_i', 'dep', 'amo'):          # 나가는 돈·비용은 부호를 떼고 크기로 둔다(회사마다 음수·양수 표기가 다르다)
        if k in fl: fl[k] = tuple(None if v is None else abs(v) for v in fl[k])
    if cfr and 'cfo' in fl:
        if 'capex' in fl and 'capex_i' not in fl: fl['capex_i'] = (0.0, 0.0); src['capex_i'] = 'none0'
    if 'dep' in fl and 'amo' not in fl: fl['amo'] = (0.0, 0.0); src['amo'] = 'none0'
    return out

XWHY = {'next': '다음 수집부터 표시(전체 재무제표 확장 항목 수집 전)', 'nodata': 'DART에 이 분기 전체 재무제표가 없음', 'err': 'DART 수집 실패 — 다음 실행에서 다시 시도',
        'no_bs': '재무상태표 행이 없음', 'no_cf': '현금흐름표 행이 없음', 'no_acct': '재무제표 본문에서 계정을 찾지 못함',
        'da_notes': '감가상각비가 현금흐름표·손익계산서 본문에 없음(주석에만 기재 — 사업보고서 주석 "비용의 성격별 분류"에서 확인)', 'no_prev': '전년 보고서에서 같은 항목을 찾지 못해 최근 4분기 합을 만들지 못함',
        'chk': '검산 실패(다른 계정과 크기가 맞지 않음) — 값을 버림', 'stale': '이전 분기 값(이번 분기 수집 실패)'}
def ext_build(raw, y, q, fs, asof, prevx, f):
    """raw {(연, 분기): (상태, rows)} → 확장 재무 캐시 한 종목분(억원). f = 주요계정 TTM(검산용)"""
    st0 = (raw.get((y, q)) or ('err', None))[0]
    if st0 != 'ok':
        if st0 == 'nodata': return {'v': XV, 'asof': asof, 'fs': fs, 'none': 'nodata'}
        if prevx and prevx.get('cash') is not None: return dict(prevx, fail=1)          # 이번 수집 실패 → 기존 값 유지(다음 실행에서 재시도)
        return {'v': XV, 'asof': asof, 'fs': fs, 'none': 'err', 'fail': 1}
    P = {k: (parse_ext(v[1], k[1]) if v[0] == 'ok' else None) for k, v in raw.items()}
    p0 = P[(y, q)]; x = {'v': XV, 'asof': asof, 'fs': fs}; why = {}; src = dict(p0['src'])
    E = lambda v: None if v is None else round(v / EOK, 2)
    b = p0['bs']
    if not p0['has_bs']:
        for k in ('cash', 'debt', 'nci'): why[k] = 'no_bs'
    else:
        if b.get('cash') is None: why['cash'] = 'no_acct'
        else: x['cash'] = E(b['cash']); x['stfi'] = E(b.get('stfi'))
        if b.get('ofa'): x['ofa'] = E(b['ofa'])
        for k in ('st', 'cl', 'lt', 'bond', 'lease'): x[k] = E(b.get(k) or 0.0)
        x['debt'] = round(sum(x[k] for k in ('st', 'cl', 'lt', 'bond', 'lease')), 2)
        x['nci'] = E(b.get('nci')) if fs == 'CFS' else 0.0
        if fs != 'CFS': src['nci'] = 'ofs'
        # 검산: 차입금 합계 ≤ 부채총계, 현금 ≤ 자산총계, 비지배지분 ≤ 자본총계
        if f.get('li') is not None and x['debt'] > f['li'] * 1.02 + 1:
            for k in ('st', 'cl', 'lt', 'bond', 'lease', 'debt'): x.pop(k, None)
            why['debt'] = 'chk'
        if x.get('cash') is not None and f.get('as') is not None and x['cash'] + (x.get('stfi') or 0) > f['as'] * 1.02 + 1:
            x.pop('cash', None); x.pop('stfi', None); why['cash'] = 'chk'
        if x.get('nci') and f.get('eq') is not None and (x['nci'] > f['eq'] * 1.02 + 1): x.pop('nci', None); why['nci'] = 'chk'
    # 손익·현금흐름: 최근 4분기 합 = 올해 누적 + 전년 연간 − 전년 동기 누적
    reps = [(y, 4)] if q == 4 else [(y, q), (y - 1, 4), (y - 1, q)]
    bad = [k for k in reps[1:] if (raw.get(k) or ('err',))[0] == 'err']
    for k in ('cfo', 'capex', 'capex_i', 'dep', 'amo'):
        a = p0['fl'].get(k)
        if a is None or a[0] is None:
            why[k] = ('no_cf' if not p0['has_cf'] else 'da_notes' if k in ('dep', 'amo') else 'no_acct'); continue
        if q == 4: x[k] = E(a[0]); continue
        pa, pc = P.get((y - 1, 4)), P.get((y - 1, q))
        zero = (src.get(k) == 'none0')
        bv = ((pa['fl'].get(k) or (None,))[0] if pa else None)
        cv = ((pc['fl'].get(k) or (None,))[0] if pc else None)
        if cv is None and a[1] is not None and not zero: cv = a[1]; src[k + '_c'] = 'prvcol'       # 전년 동기 보고서에 없으면 올해 보고서의 전년 동기 열
        if zero or (k in ('capex_i', 'amo') and pa and pc):                                         # 무형자산 취득·상각은 줄이 없으면 그 기간 0
            bv = 0.0 if bv is None else bv; cv = 0.0 if cv is None else cv
        if bv is None or cv is None:
            if bad: why[k] = 'err'
            else: why[k] = 'no_prev'
            continue
        x[k] = E(a[0] + bv - cv)
        if k in ('capex', 'capex_i', 'dep', 'amo') and x[k] < 0: x.pop(k); why[k] = 'chk'
    if x.get('dep') is not None and f.get('rev') and x['dep'] + (x.get('amo') or 0) > f['rev']: x.pop('dep'); x.pop('amo', None); why['dep'] = 'chk'
    if bad:
        x['fail'] = 1
        if prevx and prevx.get('asof') == asof:                                                     # 같은 분기의 기존 값이 있으면 못 만든 항목만 기존 값으로
            for k in ('cfo', 'capex', 'capex_i', 'dep', 'amo'):
                if k not in x and prevx.get(k) is not None: x[k] = prevx[k]; why.pop(k, None)
    if why: x['why'] = why
    x['src'] = {k: v for k, v in src.items() if v not in ('id',)}                                   # 표준 계정 ID로 잡은 것은 적지 않는다(나머지만 추적)
    return x
def dart_full_rows(corp, year, q, fs='CFS'):
    """전체 재무제표 원본 행. 반환 (상태, rows) — ok / nodata(자료 없음 013) / quota(한도 020) / err(그 밖의 실패)"""
    j = jget('https://opendart.fss.or.kr/api/fnlttSinglAcntAll.json?crtfc_key=%s&corp_code=%s&bsns_year=%d&reprt_code=%s&fs_div=%s'
             % (KEY, corp, year, REPRT[q], fs))
    st = j.get('status')
    if st == '020': return 'quota', None
    if st == '000': return 'ok', j.get('list') or []
    if st == '013': return 'nodata', None
    return 'err', None

def collect_fin(codes, prev_fin, prev_corp=None, prev_finx=None):
    """DART에서 재무를 모아 (fin, meta, corpmap, finx) 반환. 실패한 종목은 이전 캐시 유지."""
    prev_finx = prev_finx or {}
    y, q = latest_quarter()
    corpmap = {}
    try: corpmap.update(json.load(open(SEED_CORP, encoding='utf-8')))
    except Exception as e: log('고유번호 시드 없음 %r' % e)
    corpmap.update(prev_corp or {})
    fresh = dart_corpcodes()
    if fresh: corpmap.update({c: fresh[c] for c in codes if c in fresh})
    else: log('corpCode.xml 실패(점검 등) — 시드·캐시 고유번호 %d개로 진행' % len(corpmap))
    if not corpmap: log('DART 고유번호 없음 — 재무 캐시 유지'); return prev_fin, None, {}, prev_finx
    todo = [c for c in codes if c in corpmap]
    log('DART 대상 %d/%d종목, 기준 분기 %d년 %dQ' % (len(todo), len(codes), y, q))
    store = {}; calls = 0; quota = False; T0 = time.time()
    for i in range(0, len(todo), CHUNK):
        batch = [corpmap[c] for c in todo[i:i + CHUNK]]
        for (yy, qq) in reports_for(y, q):
            r = dart_multi(batch, yy, qq, store); calls += 1
            if r == 'quota': quota = True; break
            time.sleep(0.2)
        if quota: break
    fin = dict(prev_fin); n_ok = 0; n_p = 0
    asof = '%dQ%02d' % (q, y % 100)
    for c in todo:
        t = ttm_from(store.get(corpmap[c], {}), y, q)
        if not t: continue
        t['asof'] = asof; t['src'] = 'DART'
        pf = prev_fin.get(c) or {}                              # ② 결과는 같은 분기면 다시 받지 않는다(종목당 3콜 절약)
        if pf.get('asof') == asof and pf.get('fs') == t['fs'] and (pf.get('b') or 'ni_p' in pf):
            for k in ('ni_p', 'eq_p'):
                if k in pf: t[k] = pf[k]
            t['b'] = 1
        fin[c] = t; n_ok += 1
    log('① 주요계정 TTM 산출 %d종목 (호출 %d, %ds)' % (n_ok, calls, time.time() - T0))
    # ② 전체 재무제표 — 지배주주 몫(연결 종목) + 밸류 재료(순차입금·감가상각비·현금흐름, 연결·별도 모두). 같은 응답에서 함께 뽑는다
    finx = dict(prev_finx); n_x = 0; n_xf = 0
    if not quota:
        reps = [(y, 4)] if q == 4 else [(y, q), (y - 1, 4), (y - 1, q)]
        for c in todo:
            t = fin.get(c)
            if not t or t.get('asof') != asof: continue
            fs = t.get('fs') or 'CFS'; px_ = finx.get(c) or {}
            need_b = (fs == 'CFS' and not t.get('b'))                       # 지배주주 몫: 같은 분기에 이미 받았으면 다시 받지 않는다
            need_x = not (px_.get('v') == XV and px_.get('asof') == asof and px_.get('fs') == fs and not px_.get('fail'))
            if not need_b and not need_x:
                if 'ni_p' in t: n_p += 1
                n_x += 1; continue
            corp = corpmap[c]; raw = {}
            for (yy, qq) in reps:
                st, rows = dart_full_rows(corp, yy, qq, fs); calls += 1; time.sleep(0.2)
                if st == 'quota': quota = True; break
                raw[(yy, qq)] = (st, rows)
            if quota: log('DART 한도 초과 — 전체 재무제표 수집 중단'); break
            if need_x:
                try: finx[c] = ext_build(raw, y, q, fs, asof, px_, t)
                except Exception as e: log('확장 항목 파싱 실패 %s %r' % (c, e)); finx[c] = dict(px_, fail=1) if px_ else {'v': XV, 'asof': asof, 'fs': fs, 'none': 'err', 'fail': 1}
                if finx[c].get('fail'): n_xf += 1
                else: n_x += 1
            if not need_b:
                if 'ni_p' in t: n_p += 1
                continue
            t['b'] = 1
            if not all(v[0] == 'ok' for v in raw.values()): continue
            got = {k: parse_full(v[1], k[1]) for k, v in raw.items()}
            if q == 4: nip = got[(y, 4)].get('ni_p')
            else:
                a, b, d = got[(y, q)].get('ni_p'), got[(y - 1, 4)].get('ni_p'), got[(y - 1, q)].get('ni_p')
                nip = None if None in (a, b, d) else a + b - d
            eqp = got[(y, q)].get('eq_p')
            # 지배주주 몫이 전체보다 터무니없이 다르면(계정 오인) 버린다
            if nip is not None and t.get('ni') not in (None, 0):
                ratio = (nip / EOK) / t['ni']
                if 0.2 <= ratio <= 1.25: t['ni_p'] = nip / EOK
            if eqp is not None and t.get('eq') not in (None, 0):
                ratio = (eqp / EOK) / t['eq']
                if 0.2 <= ratio <= 1.02: t['eq_p'] = eqp / EOK
            if 'ni_p' in t: n_p += 1
        log('② 지배주주 순이익 산출 %d종목 · 밸류 재료 %d종목(실패 %d) (누적 호출 %d, %ds)' % (n_p, n_x, n_xf, calls, time.time() - T0))
    if n_ok < max(10, len(todo) // 3):
        log('DART 산출 종목이 너무 적음(%d) — 이전 재무 캐시 유지' % n_ok); return prev_fin, None, corpmap, prev_finx
    return (fin, {'asof': asof, 'calls': calls, 'ok': n_ok, 'ctrl': n_p, 'quota': quota, 'date': TODAY.isoformat(), 'ver': FIN_VER, 'x': n_x, 'xfail': n_xf},
            {c: corpmap[c] for c in codes if c in corpmap}, finx)

# ───────── 네이버(증권사 추정·우선주 시총) — 선행 지표는 "증권사 추정" 태그로만 표시
def naver_consensus(code):
    j = jget('https://m.stock.naver.com/api/stock/%s/finance/annual' % code, timeout=20, tries=2)
    fi = (j or {}).get('financeInfo') or {}
    tl = fi.get('trTitleList') or []; rows = fi.get('rowList') or []
    if not tl or not rows: return {}
    def row(title):
        for r in rows:
            if (r.get('title') or '').replace(' ', '') == title: return r.get('columns') or {}
        return {}
    op, ni, nic = row('영업이익'), row('당기순이익'), row('지배주주순이익')
    fy = {}
    for t in tl:
        k = t.get('key') or ''; m = re.match(r'(20\d\d)', k)
        if not m: continue
        v = lambda col: tonum((col.get(k) or {}).get('value'))
        n = v(nic); n = n if n is not None else v(ni)
        fy[m.group(1)] = {'op': v(op), 'ni': n, 'est': (t.get('isConsensus') == 'Y')}
    return fy
def cap_str(s):
    """'2조 4,560억' → 24560.0(억)"""
    if not s: return None
    s = str(s).replace(',', '').replace(' ', ''); m = re.fullmatch(r'(?:(\d+)조)?(?:(\d+)억)?', s)
    if not m or not (m.group(1) or m.group(2)): return None
    return float(m.group(1) or 0) * 10000 + float(m.group(2) or 0)
def _nnum(v):
    return tonum(re.sub(r'[배원%]', '', str(v or '')).replace('N/A', ''))
def naver_basic(code):
    """네이버 종목 요약: 최근 4분기 주당순이익 기준 PER·EPS, 최근 분기 BPS 기준 PBR (FnGuide)"""
    j = jget('https://m.stock.naver.com/api/stock/%s/integration' % code, timeout=20, tries=2)
    o = {}
    for t in j.get('totalInfos') or []:
        c = t.get('code')
        if c in ('per', 'pbr', 'eps', 'bps'): o[c] = _nnum(t.get('value'))
    return o if any(v is not None for v in o.values()) else {}
def naver_cap(code):
    j = jget('https://m.stock.naver.com/api/stock/%s/integration' % code, timeout=20, tries=2)
    for t in j.get('totalInfos') or []:
        if t.get('key') in ('시총', '시가총액') or t.get('code') == 'marketValue': return cap_str(t.get('value'))
    return None
def fwd_from_fy(fy, cap):
    """컨센 fy dict → 12M 선행 PER·2년 순이익 CAGR. 단위 억."""
    if not fy or not cap: return {}
    y0, y1, y2 = str(TODAY.year - 1), str(TODAY.year), str(TODAY.year + 1)
    a0, a1, a2 = fy.get(y0) or {}, fy.get(y1) or {}, fy.get(y2) or {}
    if not a1.get('est') or a1.get('ni') is None: return {}
    ni0, ni1, ni2 = a0.get('ni'), a1.get('ni'), a2.get('ni') if a2.get('est') else None
    rem = (datetime.date(TODAY.year, 12, 31) - TODAY).days / 365.0
    nif = ni1 * rem + ni2 * (1 - rem) if ni2 is not None else ni1
    o = {'src': '네이버 컨센서스(FnGuide)', 'ni0': ni0, 'ni1': ni1, 'ni2': ni2}
    o['per_f12'] = rnd(cap / nif) if nif and nif > 0 else None
    o['g1'] = rnd((ni1 / ni0 - 1) * 100, 1) if (ni0 and ni0 > 0 and ni1 and ni1 > 0) else None
    o['cagr2'] = rnd(((ni2 / ni0) ** 0.5 - 1) * 100, 1) if (ni0 and ni0 > 0 and ni2 and ni2 > 0) else None
    return o

# ───────── peer 대비 꼬리표(사실 표시) — 합산 점수는 만들지 않는다
CHEAP = 0.9    # 멀티플(PER·PBR·PSR): peer의 90% 이하면 "낮음", 110% 이상이면 "높음"
DEAR = 1.1
TOL = {'roe': 1.0, 'opm': 1.0, 'roa': 1.0, 'g': 5.0, 'debt': 20.0}   # peer와의 차이(%p)가 이 안이면 "비슷" — 부채비율은 15% vs 11% 같은 작은 차이를 '고부채'로 부르지 않도록 20%p
G_CAP = 300    # 성장률 비교 상한(%) — 흑자전환·기저효과로 부풀려진 성장률끼리는 우열을 가리지 않는다
PER_MAX = 150  # PER이 이보다 크면 이익이 너무 작은 상태 — PER 비교에서 뺀다
def tag_ratio(ratios):
    """내 값 ÷ peer 값의 중앙값으로 낮음/비슷/높음"""
    if not ratios: return None
    m = statistics.median(ratios)
    return 'low' if m <= CHEAP else 'high' if m >= DEAR else 'mid'
def tag_diff(diffs, tol):
    """내 값 − peer 값(%p)의 중앙값으로 높음/비슷/낮음"""
    if not diffs: return None
    m = statistics.median(diffs)
    return 'high' if m >= tol else 'low' if m <= -tol else 'mid'
def cmp_pair(mine, theirs):
    """한 쌍에서 지표별 (비율 또는 차이, 상대 값). mine/theirs는 같은 기준으로 맞춘 dict"""
    o = {}
    for k in ('per', 'pbr', 'psr'):
        a, b = mine.get(k), theirs.get(k)
        if a is None or b is None or a <= 0 or b <= 0: continue
        if k == 'per' and (a > PER_MAX or b > PER_MAX): continue
        o[k] = (a / b, b)
    for k in ('roe', 'opm', 'roa', 'debt'):
        a, b = mine.get(k), theirs.get(k)
        if a is None or b is None: continue
        o[k] = (a - b, b)
    gk = 'g_ni' if (mine.get('g_ni') is not None and theirs.get('g_ni') is not None) else 'g_op'
    a, b = mine.get(gk), theirs.get(gk)
    if a is not None and b is not None: o['g'] = (min(a, G_CAP) - min(b, G_CAP), b)
    return o

# ───────── PBR–ROE 판정 (11/17 추가)
# 사용자 관점: 저PBR이어도 ROE가 함께 낮으면 의미 없음 / ROE가 높은데 저PBR이면 저평가 후보 / '적정 ROE + 저PBR'은 칸으로 자르지 않고
# 비교 집단의 ROE–PBR 관계선에서 얼마나 떨어져 있는지(괴리율)로 본다. PBR ÷ ROE = PER이라 최근 4분기 ROE만 쓰면 저PER 꼬리표와 같아지므로
# ROE는 최근 3개 연도 + 최근 4분기의 평균(평균 ROE)을 기본으로 쓴다. 비교는 A·B등급 peer 우선, 없으면 같은 분야(top) 관계선, 표본이 적으면 반도체 전체 관계선.
PR = {'hi': 15.0, 'lo': 8.0, 'gap': 20.0, 'min_n': 10, 'roe_tol': 2.0, 'coe': 10.0}
def _theil(pts):
    """강건 직선 맞춤(기울기 = 두 점씩 이은 기울기들의 중앙값). pts [(x, y)] → (a, b, n) : y = a + b·x"""
    n = len(pts)
    if n < 5: return None
    sl = [(pts[j][1] - pts[i][1]) / (pts[j][0] - pts[i][0]) for i in range(n) for j in range(i + 1, n) if abs(pts[j][0] - pts[i][0]) > 0.5]
    if len(sl) < 5: return None
    b = statistics.median(sl); a = statistics.median([y - b * x for x, y in pts])
    return (round(a, 3), round(b, 4), n)
def _roe_hist(code):
    """valfacts 수집본(네이버 연간)의 확정 연도 ROE — 최근 3개 [[연도, ROE]]"""
    try:
        an = (json.load(open('public/data/vf/%s.json' % code, encoding='utf-8')).get('annual') or {})
        roe = (an.get('rows') or {}).get('ROE') or {}
        ys = [c[0] for c in an.get('cols') or [] if not c[1] and roe.get(c[0]) is not None]
        return [[y[:4], roe[y]] for y in sorted(ys)[-3:]]
    except Exception:
        return []
def pbr_roe(co, defpairs):
    # 1) 종목별 평균 ROE
    for c, r in co.items():
        if 'cap' not in r: continue
        h = _roe_hist(c); t = r.get('roe')
        vals = [v for _, v in h] + ([t] if t is not None else [])
        pr = {'hist': h, 'roe_t': t}
        if vals:
            pr['roe_n'] = rnd(sum(vals) / len(vals), 1); pr['roe_min'] = rnd(min(vals), 1)
        r['pr'] = pr
    ok = lambda r, k: r.get('pr') and r['pr'].get(k) is not None and 0 < r['pr'][k] <= 80 and r.get('pbr') and 0 < r['pbr'] <= 30
    # 2) 관계선: 평균 ROE 기준(n)과 최근 4분기 ROE 기준(t), 전체와 분야별
    lines = {'all': {}, 'top': {}}
    for k, key in (('n', 'roe_n'), ('t', 'roe_t')):
        L = _theil([(r['pr'][key], r['pbr']) for r in co.values() if ok(r, key)])
        if L: lines['all'][k] = L
    tops = sorted({r.get('top') for r in co.values() if r.get('top')})
    for tp in tops:
        d = {}
        for k, key in (('n', 'roe_n'), ('t', 'roe_t')):
            pts = [(r['pr'][key], r['pbr']) for r in co.values() if r.get('top') == tp and ok(r, key)]
            if len(pts) >= PR['min_n']:
                L = _theil(pts)
                if L and L[1] > 0: d[k] = L          # 기울기가 음수면(ROE가 높을수록 PBR이 낮게 나오는 표본) 쓰지 않음
        if d: lines['top'][tp] = d
        pb = [r['pbr'] for r in co.values() if r.get('top') == tp and r.get('pbr') and r['pbr'] > 0]
        if len(pb) >= 3: lines['top'].setdefault(tp, {})['pbr_med'] = rnd(statistics.median(pb))
    pball = [r['pbr'] for r in co.values() if r.get('pbr') and r['pbr'] > 0]
    lines['all']['pbr_med'] = rnd(statistics.median(pball)) if pball else None
    def fair(r, k, key):
        v = r['pr'].get(key)
        if v is None or v <= 0 or not r.get('pbr'): return None, None, None
        L = (lines['top'].get(r.get('top')) or {}).get(k); grp = r.get('top')
        if not L: L = lines['all'].get(k); grp = 'all'
        if not L: return None, None, None
        f = max(L[0] + L[1] * v, 0.3)                     # 관계선이 주는 PBR(하한 0.3배)
        return rnd(f), rnd((r['pbr'] / f - 1) * 100, 0), grp
    # 3) peer(A·B) 비교: 현재 PBR 비율 × 평균 ROE 차이
    pv = {}
    for p in defpairs:
        if p['grade'] not in ('A', 'B'): continue
        for me, ot in ((p['a'], p['b']), (p['b'], p['a'])):
            x, y = co.get(me) or {}, co.get(ot) or {}
            if not (x.get('pbr') and y.get('pbr') and x.get('pr') and y.get('pr')): continue
            if x['pr'].get('roe_n') is None or y['pr'].get('roe_n') is None or x['pbr'] <= 0 or y['pbr'] <= 0: continue
            pv.setdefault(me, []).append((x['pbr'] / y['pbr'], x['pr']['roe_n'] - y['pr']['roe_n'], ot))
    # 4) 판정
    for c, r in co.items():
        pr = r.get('pr')
        if not pr: continue
        rn = pr.get('roe_n'); pbr = r.get('pbr')
        pr['lvl'] = None if rn is None else 'loss' if rn <= 0 else 'high' if rn >= PR['hi'] else 'mid' if rn >= PR['lo'] else 'low'
        pr['fair_n'], pr['gap_n'], pr['grp'] = fair(r, 'n', 'roe_n')
        pr['fair_t'], pr['gap_t'], _ = fair(r, 't', 'roe_t')
        med = (lines['top'].get(r.get('top')) or {}).get('pbr_med') or lines['all'].get('pbr_med')
        g = pr['gap_n']; lc = None; tneg = pr.get('roe_t') is not None and pr['roe_t'] <= 0
        if pr['lvl'] == 'loss' or rn is None or not pbr or tneg: lc = 'loss'      # 평균 ROE가 0 이하이거나 최근 4분기 적자 — 판단하지 않음
        elif g is not None:
            if g <= -PR['gap']: lc = 'trap' if pr['lvl'] == 'low' else 'cheap'     # 저ROE면 선보다 싸도 '싼 이유 있음'(자산주 여부는 fl의 asset)
            elif g >= PR['gap']: lc = 'rich' if pr['lvl'] == 'high' else 'over'
            else: lc = 'trap' if (pr['lvl'] == 'low' and med and pbr < med * 0.8) else 'fair'
        pr['line'] = lc
        if c in pv:
            pm_ = statistics.median([v[0] for v in pv[c]]); dm = statistics.median([v[1] for v in pv[c]])
            pt = 'low' if pm_ <= CHEAP else 'high' if pm_ >= DEAR else 'mid'
            rt = 'high' if dm >= PR['roe_tol'] else 'low' if dm <= -PR['roe_tol'] else 'mid'
            pc = {('low', 'high'): 'cheap', ('low', 'mid'): 'cheap', ('low', 'low'): 'trap', ('mid', 'high'): 'cheap', ('mid', 'mid'): 'fair',
                  ('mid', 'low'): 'over', ('high', 'high'): 'rich', ('high', 'mid'): 'over', ('high', 'low'): 'over'}[(pt, rt)]
            if pr['lvl'] == 'loss' or tneg: pc = 'loss'
            elif pc == 'cheap' and pr['lvl'] == 'low': pc = 'trap'           # peer보다 싸고 ROE가 높아도 평균 ROE 자체가 8% 미만이면 저평가 후보로 올리지 않음
            pr['peer'] = {'cls': pc, 'pbr': rnd((pm_ - 1) * 100, 0), 'roe': rnd(dm, 1), 'n': len(pv[c]), 'with': [v[2] for v in pv[c]]}
        pr['cls'] = (pr.get('peer') or {}).get('cls') or lc
        pr['src'] = 'peer' if pr.get('peer') else 'line'
        pr['split'] = bool(pr.get('peer') and lc and lc != 'loss' and pr['peer']['cls'] != lc)
        # ROE의 질·방향
        fl = []; t = pr.get('roe_t'); h = pr.get('hist') or []
        if rn and t is not None and rn > 0 and t - rn >= 8 and t >= rn * 1.5: fl.append('peak34' if r.get('ph') in (3, 4) else 'peakroe')
        if h and t is not None and t <= h[-1][1] - 3: fl.append('down')
        if r.get('debt') is not None and r['debt'] >= 150 and rn and rn >= PR['hi']: fl.append('lev')
        if 'nonop' in (r.get('warn') or []) or (r.get('ni') and r.get('op') and r['op'] > 0 and r['ni'] / r['op'] > 1.3): fl.append('nonop')
        if rn and rn >= PR['coe'] and pbr and pbr < 1: fl.append('abs')
        if pr['lvl'] == 'low' and g is not None and g <= -PR['gap'] and (r.get('debt') is not None and r['debt'] < 50): fl.append('asset')   # 저ROE인데 선보다도 20%↑ 싸고 부채 적음 — 자산주 가능(현금·주주환원 확인)
        if len(h) < 3: fl.append('short')
        pr['fl'] = fl
    cnt = {}
    for r in co.values():
        k = (r.get('pr') or {}).get('cls')
        if k: cnt[k] = cnt.get(k, 0) + 1
    return {'th': PR, 'lines': lines, 'count': cnt,
            'rule': '평균 ROE = 최근 3개 연도 ROE(네이버·FnGuide 연간, 지배주주 기준)와 최근 4분기 ROE(DART)의 평균. 관계선 = 같은 분야 기업들의 (평균 ROE, 현재 PBR)을 강건 직선(Theil–Sen)으로 맞춘 것, 분야 표본이 10개 미만이거나 기울기가 음수면 반도체 전체 선. 괴리율 = 현재 PBR ÷ 관계선이 주는 PBR − 1. A·B등급 peer가 있으면 peer와의 비교(PBR 비율 × 평균 ROE 차이)를 대표 판정으로 쓰고 관계선 판정을 함께 표시'}

# ───────── 평가법별 책정값(val) — "이 회사에 맞는 평가법"에 방법 이름만 적지 않고 실제로 계산한 값을 싣는다
#   방법마다: 이 회사의 배수 · 비교 대상(peer) 중앙값 · 그 배수를 받는다면의 환산 주가 · 현재가 대비 %
#   환산 주가는 목표주가가 아니다 — "peer와 같은 배수를 받는다면 어디인가"를 보는 위치 확인용.
#   peer 범위: ① A·B등급 peer(표본 1곳 이상) → ② 같은 묶음(2곳 이상) → ③ 같은 단계(3곳 이상) 순으로 넓히고, 어느 범위·몇 곳인지 남긴다.
#   배수가 0 이하이거나 상한(lim)을 넘는 peer는 중앙값에서 빼고 그 수를 남긴다(pe).
#   곱한 결과가 현재가의 0.1배 미만·10배 초과면(far) 비교 대상과 사업 구조가 너무 다른 것이라 환산 주가로 쓰지 않고 이유만 남긴다.
VALCFG = {'coe': PR['coe'], 'gt': 2.0, 'gcap': 30.0, 'yrs': 10, 'band_yrs': 5, 'peg_gmax': 100.0, 'wide': 2.0, 'nci_need': 20.0, 'far': 10.0,
          'lim': {'per': PER_MAX, 'fper': PER_MAX, 'norm_per': PER_MAX, 'por': 150, 'ev_ebit': 150, 'ev_ebitda': 100, 'ev_sales': 50, 'p_fcf': 150, 'pbr': 30, 'psr': 50, 'peg': 5},
          'min_n': {'ab': 1, 'grp': 2, 'stage': 3}}
# 단계별 주력·보조 방법 — 화면(semipeer.html)의 VALM 문구와 같은 순서. band = 자기 과거 밴드(Historical Band)
VALM = {'chip':   (['norm_per', 'ev_ebitda'], ['band_pbr', 'dcf']),
        'design': (['dcf', 'ev_sales'], ['fper', 'peg']),
        'dist':   (['fper', 'ev_ebit'], ['p_fcf']),
        'pre':    (['fper', 'ev_ebit'], ['dcf', 'band_per', 'band_pbr']),
        'post':   (['fper', 'ev_ebitda'], ['ev_ebit', 'band_per', 'band_pbr']),
        'both':   (['fper', 'ev_ebit'], ['ev_ebitda', 'dcf']),
        'infra':  (['ev_ebitda', 'p_fcf'], ['fper']),
        'etc':    (['fper', 'ev_ebit'], ['pbr'])}
PEERK = ['per', 'fper', 'norm_per', 'por', 'ev_ebit', 'ev_ebitda', 'ev_sales', 'p_fcf', 'pbr', 'psr', 'peg']
EVBASE = {'ev_ebit': 'op', 'ev_ebitda': 'ebitda', 'ev_sales': 'rev'}
VWHY = {'loss': '최근 4분기 순손실 — PER이 성립하지 않음', 'nodata': '순이익 자료 없음', 'nocov': '증권사 추정 없음(미커버)',
        'norm_loss': '몇 해 평균 순이익이 적자 — 정상화 PER이 성립하지 않음', 'norm_short': '연간 실적이 3개 연도 미만 — 평균을 내지 않음',
        'oploss': '최근 4분기 영업적자 — 영업이익 기준 배수가 성립하지 않음', 'ebitda_neg': 'EBITDA가 0 이하', 'rev0': '매출 자료 없음',
        'fcf_neg': '잉여현금흐름(FCF)이 0 이하 — 번 현금보다 설비투자가 큼', 'g_neg': '추정 이익 성장률이 0 이하 — PEG가 성립하지 않음',
        'g_base': '추정 성장률 100% 초과(기저효과) — PEG 환산을 하지 않음', 'thin': '이익이 너무 작아 배수가 상한을 넘음 — 환산하지 않음',
        'no_peer': '비교할 표본이 없음(peer·같은 묶음·같은 단계 모두 값 없음)',
        'far': '곱해 보면 현재가의 0.1배 미만이거나 10배 초과 — 같은 잣대로 보기 어려워 환산 주가로 쓰지 않음', 'neg_eq': 'peer 배수를 곱한 사업가치보다 순차입금이 큼',
        'no_file': '밴드 자료 없음(일별 PER·PBR 시계열이 수집되지 않은 종목)', 'short': '밴드 자료가 1년 미만', 'no_cur': '현재 값이 없음(적자 등) — 밴드 위치를 잡지 못함',
        'no_g': '증권사 추정 성장률이 없음(미커버) — 성장률 가정을 만들지 않음', 'no_cf': '현금흐름 자료 없음', 'no_nd': '순차입금을 구하지 못함',
        'no_da': '감가상각비를 구하지 못함', 'gt': '연 80%를 넘는 성장이 필요 — 계산 범위 밖', 'lt': '이익이 해마다 30% 넘게 줄어도 되는 수준 — 계산 범위 밖'}
VWHY.update(XWHY)
def _r2(v):
    """소수 둘째 자리 반올림(5는 올림) — 화면(JS)의 계산과 끝자리까지 같게 하려고 파이썬 기본 반올림(짝수 쪽) 대신 쓴다"""
    return math.floor(v * 100 + 0.5 + 1e-9) / 100
def _vf(code):
    try: return json.load(open(os.path.join(DD, 'vf', '%s.json' % code), encoding='utf-8'))
    except Exception: return {}
def _annual_ni(vf):
    """vf 수집본(네이버·FnGuide 연간)의 확정 연도 순이익(지배주주 우선, 없으면 당기순이익) — 최근 3개 [[연도, 억]]"""
    an = vf.get('annual') or {}; rows = an.get('rows') or {}
    a, b = rows.get('지배주주순이익') or {}, rows.get('당기순이익') or {}
    out = []
    for col in an.get('cols') or []:
        if col[1]: continue
        v = a.get(col[0]); v = v if v is not None else b.get(col[0])
        if v is not None: out.append([col[0][:4], v])
    return sorted(out)[-3:]
SEG_SKIP = re.compile(r'합\s*계|소\s*계|총\s*계|^계$|전\s*사|연결\s*조정|내부\s*거래|기\s*타|공통|조정|단순\s*합|^[-–—]+$')
def _segs(vf):
    """사업보고서 '주요 제품 등의 현황' 표의 첫 열이 사업부문이면 부문 이름 목록(합계·전사·조정 제외)"""
    try:
        rows = ((vf.get('biz') or {}).get('prod') or {}).get('r') or []
        cell = lambda v: (v[0], int(v[2]) if len(v) > 2 else 1) if isinstance(v, list) else (v, 1)
        h, hs = cell(rows[0][0])
        if '부문' not in re.sub(r'\s+', '', str(h)): return []
        out = []; skip = hs - 1
        for r in rows[1:]:
            if skip > 0: skip -= 1; continue
            if not r: continue
            t, span = cell(r[0]); skip = span - 1
            t = re.sub(r'^\d+[\.\)]\s*', '', re.sub(r'\s+', ' ', str(t)).strip())
            if t and not SEG_SKIP.search(t) and t not in out and len(t) <= 30: out.append(t)
        return out
    except Exception:
        return []
def _band(code, px):
    """자기 과거 밴드 — compare/<코드>.json(일별 PER·PBR)에서 최근 5년 최저·중앙·최고와 현재 위치.
       현재 값도 같은 시계열의 마지막 값을 쓴다(주식 수·반영 시점 기준이 달라 이 파일의 다른 PER과 섞지 않는다)."""
    try: j = json.load(open(os.path.join(DD, 'compare', '%s.json' % code), encoding='utf-8'))
    except Exception: return {'per': {'why': 'no_file'}, 'pbr': {'why': 'no_file'}}
    d0 = (TODAY - datetime.timedelta(days=365 * VALCFG['band_yrs'])).isoformat(); recent = (TODAY - datetime.timedelta(days=14)).isoformat()
    out = {}
    for k in ('per', 'pbr'):
        lim = VALCFG['lim'][k]
        s = [(d, v) for d, v in (j.get(k) or []) if d >= d0 and v is not None and 0 < v <= lim]
        if len(s) < 240: out[k] = {'why': 'short' if (j.get(k) or []) else 'no_file'}; continue
        if s[-1][0] < recent: out[k] = {'why': 'no_cur'}; continue
        vs = sorted(v for _, v in s); cur = s[-1][1]; md = statistics.median(vs)
        o = {'cur': rnd(cur), 'lo': rnd(vs[0]), 'md': rnd(md), 'hi': rnd(vs[-1]), 'pct': rnd(sum(1 for v in vs if v <= cur) / len(vs) * 100, 0),
             'n': len(vs), 'from': s[0][0], 'to': s[-1][0]}
        if px: o['ip'] = round(px * md / cur); o['ip_lo'] = round(px * vs[0] / cur); o['ip_hi'] = round(px * vs[-1] / cur)
        out[k] = o
    return out
def _dcf_path(g1, gt, n=10):
    """성장률 길: 앞 5년 g1, 뒤 5년은 g1에서 영구성장률 gt까지 고르게 낮춘다"""
    h = n // 2
    return [g1] * h + [g1 + (gt - g1) * (i + 1) / (n - h) for i in range(n - h)]
def _dcf_pv(cf0, gs, r, gt):
    """앞으로 len(gs)년 현금흐름의 현재가치 + 그 뒤(영구성장 gt)의 현재가치. r·g는 소수(0.10)"""
    pv = 0.0; cf = cf0
    for t, g in enumerate(gs, 1):
        cf *= (1 + g); pv += cf / (1 + r) ** t
    return pv + cf * (1 + gt) / (r - gt) / (1 + r) ** len(gs)
def _dcf_solve(cf0, target, r, gt, n=10, lo=-0.30, hi=0.80):
    """현재가치가 target이 되는 10년 연 성장률(이분법). 범위 밖이면 ('gt'|'lt', None)"""
    f = lambda g: _dcf_pv(cf0, [g] * n, r, gt) - target
    if f(hi) < 0: return 'gt', None
    if f(lo) > 0: return 'lt', None
    for _ in range(60):
        m = (lo + hi) / 2
        if f(m) > 0: hi = m
        else: lo = m
    return None, (lo + hi) / 2
def build_val(co, fin, finx, DEF, fwdc, peg):
    C = VALCFG; LIM = C['lim']; r_ = C['coe'] / 100.0; gt = C['gt'] / 100.0; vfs = {}
    # 1) 재료와 자기 배수
    for c, r in co.items():
        if 'cap' not in r or not r.get('px'): continue
        cap, px = r['cap'], r['px']; f = fin.get(c) or {}; x = finx.get(c) or {}
        rev, op, ni, eq = r.get('rev'), r.get('op'), r.get('ni'), r.get('eq')
        mat = {'cap': cap, 'px': px, 'sh': round(cap * EOK / px), 'rev': rev, 'op': op, 'ni': ni, 'eq': eq}
        if r.get('pref'): mat['pref'] = r['pref']
        w = {}                                          # 재료를 못 구한 이유
        xw = x.get('why') or {}; xnone = x.get('none') or (None if x else 'next')
        if x and x.get('asof') and r.get('asof') and x['asof'] != r['asof']: mat['stale'] = x['asof']
        # 순차입금 = 차입금·사채·리스부채 − 현금·단기금융상품
        if x.get('cash') is not None and x.get('debt') is not None:
            for k in ('cash', 'stfi', 'st', 'cl', 'lt', 'bond', 'lease', 'debt', 'ofa'):
                if x.get(k) is not None: mat[k] = rnd(x[k], 1)
            mat['nd'] = rnd(x['debt'] - x['cash'] - (x.get('stfi') or 0), 1)
        else: w['nd'] = xnone or xw.get('cash') or xw.get('debt') or 'no_acct'
        # 비지배지분: 재무상태표 값 우선, 없으면 자본총계 − 지배주주 자본(이미 가진 값으로 계산)
        if x.get('nci') is not None: mat['nci'] = rnd(x['nci'], 1)
        elif f.get('fs') == 'OFS': mat['nci'] = 0.0
        elif f.get('eq') is not None and f.get('eq_p') is not None: mat['nci'] = rnd(max(0.0, f['eq'] - f['eq_p']), 1); mat['nci_src'] = 'calc'
        else: w['nci'] = xnone or xw.get('nci') or 'no_acct'
        if mat.get('nd') is not None and mat.get('nci') is not None: mat['ev'] = rnd(cap + mat['nd'] + mat['nci'], 1)
        else: w['ev'] = w.get('nd') or w.get('nci')
        # EBITDA = 영업이익 + 감가상각비 + 무형자산상각비
        if x.get('dep') is not None:
            mat['dep'] = rnd(x['dep'], 1); mat['amo'] = rnd(x.get('amo') or 0, 1)
            if op is not None: mat['ebitda'] = rnd(op + mat['dep'] + mat['amo'], 1)
        else: w['ebitda'] = xnone or xw.get('dep') or 'no_da'
        # FCF = 영업활동현금흐름 − 유형자산 취득 − 무형자산 취득
        if x.get('cfo') is not None and x.get('capex') is not None:
            mat['cfo'] = rnd(x['cfo'], 1); mat['capex'] = rnd(x['capex'], 1); mat['capex_i'] = rnd(x.get('capex_i') or 0, 1)
            mat['fcf'] = rnd(mat['cfo'] - mat['capex'] - mat['capex_i'], 1)
        else: w['fcf'] = xnone or xw.get('cfo') or xw.get('capex') or 'no_cf'
        # 정상화 이익 = 최근 3개 사업연도 + 최근 4분기 순이익의 단순 평균(적자 연도 포함 — 사이클의 일부이므로 빼지 않는다)
        vf = _vf(c); hist = _annual_ni(vf)
        ys = [v for _, v in hist] + ([ni] if (ni is not None and r.get('basis') == 'TTM') else [])
        mat['ni_hist'] = hist
        if len(hist) >= 2 and len(ys) >= 3: mat['ni_norm'] = rnd(sum(ys) / len(ys), 1)
        else: w['ni_norm'] = 'norm_short'
        fw = r.get('fwd') or {}
        g = fw.get('cagr2') if fw.get('cagr2') is not None else fw.get('g1')
        if fw.get('per_f12'):
            mat['ni_f'] = rnd(cap / fw['per_f12'], 1)
            pg = peg.get(c) or {}
            if pg.get('status') == 'ok': mat['f_b'] = '12m' if pg.get('ni2') is not None else 'fy1'
            else:
                a2 = ((fwdc.get(c) or {}).get('fy') or {}).get(str(TODAY.year + 1)) or {}
                mat['f_b'] = '12m' if (a2.get('est') and a2.get('ni') is not None) else 'fy1'
        if g is not None: mat['g'] = g; mat['g_src'] = 'cagr2' if fw.get('cagr2') is not None else 'g1'
        if r.get('ctrl') is not None: mat['ctrl'] = r['ctrl']
        if w: mat['why'] = w
        # 자기 배수
        m = {}
        def put(k, v, why=None, **kw):
            o = dict(kw)
            if v is not None:
                o['v'] = rnd(v)
                if v > LIM.get(k, 1e18): o['thin'] = 1
            elif why: o['why'] = why
            m[k] = o
        put('per', r.get('per'), 'loss' if (ni is not None and ni <= 0) else 'nodata')
        put('fper', fw.get('per_f12'), 'nocov')
        nn = mat.get('ni_norm')
        put('norm_per', cap / nn if (nn and nn > 0) else None, w.get('ni_norm') or 'norm_loss')
        put('por', r.get('por'), 'oploss' if (op is not None and op <= 0) else 'nodata')
        ev = mat.get('ev')
        put('ev_ebit', ev / op if (ev is not None and op and op > 0) else None, w.get('ev') if ev is None else 'oploss')
        eb = mat.get('ebitda')
        put('ev_ebitda', ev / eb if (ev is not None and eb and eb > 0) else None, w.get('ev') if ev is None else (w.get('ebitda') if eb is None else 'ebitda_neg'))
        put('ev_sales', ev / rev if (ev is not None and rev and rev > 0) else None, w.get('ev') if ev is None else 'rev0')
        fc = mat.get('fcf')
        put('p_fcf', cap / fc if (fc and fc > 0) else None, w.get('fcf') if fc is None else 'fcf_neg')
        put('pbr', r.get('pbr'), 'nodata'); put('psr', r.get('psr'), 'rev0')
        pv = fw.get('peg')
        if not fw.get('per_f12'): put('peg', None, 'nocov')
        elif g is None or g <= 0 or not pv or pv <= 0: put('peg', None, 'g_neg')
        elif g > C['peg_gmax']: m['peg'] = {'x': pv, 'why': 'g_base'}
        else: put('peg', pv)
        r['val'] = {'mat': mat, 'm': m}; vfs[c] = vf
    # 2) peer 범위별 표본
    ab = {}; grp = {}; stg = {}
    for p in DEF['pairs']:
        if p['grade'] in ('A', 'B'):
            for a, b in ((p['a'], p['b']), (p['b'], p['a'])):
                if b not in ab.setdefault(a, []): ab[a].append(b)
    gm = {g['id']: g['members'] for g in DEF['groups']}
    for c, r in co.items():
        s = []
        for gid in r.get('gids') or []:
            for o in gm.get(gid) or []:
                if o != c and o not in s: s.append(o)
        grp[c] = s
        stg.setdefault(r.get('stage') or 'etc', []).append(c)
    def sample(c, k, scope):
        ps = ab.get(c, []) if scope == 'ab' else grp.get(c, []) if scope == 'grp' else [o for o in stg.get(co[c].get('stage') or 'etc', []) if o != c]
        good = []; ex = 0
        for o in ps:
            mo = ((co.get(o) or {}).get('val') or {}).get('m', {}).get(k) or {}
            v = mo.get('v')
            if v is None:
                if 'x' in mo: ex += 1
                continue
            if v <= 0 or v > LIM[k]: ex += 1; continue
            good.append(v)
        return good, ex
    cnt = {'n': 0, 'nd': 0, 'ebitda': 0, 'fcf': 0, 'band': 0, 'dcf': 0, 'rdcf': 0, 'range': 0, 'sotp': 0}
    for c, r in co.items():
        V = r.get('val')
        if not V: continue
        mat, m = V['mat'], V['m']; cap, px = mat['cap'], mat['px']; cnt['n'] += 1
        for kk in ('nd', 'ebitda', 'fcf'):
            if mat.get(kk) is not None: cnt[kk] += 1
        # 3) peer 중앙값과 환산 주가
        for k in PEERK:
            o = m[k]
            for scope in ('ab', 'grp', 'stage'):
                good, ex = sample(c, k, scope)
                if len(good) >= C['min_n'][scope]:
                    o['pm'] = _r2(statistics.median(good)); o['pn'] = len(good); o['ps'] = scope
                    if ex: o['pe'] = ex
                    break
            else: o['pwhy'] = 'no_peer'
            if o.get('pm') is None or 'why' in o: continue
            if o.get('thin'): o['why'] = 'thin'; continue
            if k in EVBASE:
                base = mat.get(EVBASE[k])
                if o.get('v') is None or not base or base <= 0: continue
                ip = (o['pm'] * base - mat['nd'] - mat['nci']) * px / cap
            else:
                if o.get('v') is None or o['v'] <= 0: continue
                ip = px * o['pm'] / o['v']
            if ip <= 0: o['why'] = 'neg_eq'; continue
            if ip < px / C['far'] or ip > px * C['far']: o['why'] = 'far'; o['far'] = rnd(ip / px, 2); continue      # 10배 넘게 벌어지면 같은 잣대가 아니다 — 환산하지 않는다
            o['ip'] = round(ip); o['up'] = rnd((ip / px - 1) * 100, 1)
        # 4) 자기 과거 밴드
        bd = _band(c, px)
        for k in ('per', 'pbr'):
            b = bd[k]; o = {}
            if 'why' in b: o['why'] = b['why']
            elif b['ip'] < px / C['far'] or b['ip'] > px * C['far']:
                o = {'v': b['cur'], 'pm': b['md'], 'lo': b['lo'], 'hi': b['hi'], 'pct': b['pct'], 'pn': b['n'], 'from': b['from'], 'ps': 'self', 'why': 'far', 'far': rnd(b['ip'] / px, 2)}
            else:
                o = {'v': b['cur'], 'pm': b['md'], 'lo': b['lo'], 'hi': b['hi'], 'pct': b['pct'], 'pn': b['n'], 'from': b['from'], 'ps': 'self',
                     'ip': b['ip'], 'ip_lo': b['ip_lo'], 'ip_hi': b['ip_hi'], 'up': rnd((b['ip'] / px - 1) * 100, 1)}
            m['band_' + k] = o
        if any('ip' in m['band_' + k] for k in ('per', 'pbr')): cnt['band'] += 1
        # 5) DCF — ① 역산: 지금 시총이 맞으려면 10년간 연 몇 % 성장이 필요한가  ② 순방향: 증권사 추정 성장률(상한 30%)로 5년, 이후 5년 감속
        share = min(1.0, max(0.2, (mat.get('ctrl') if mat.get('ctrl') is not None else 100.0) / 100.0))
        D = {'r': C['coe'], 'gt': C['gt'], 'yrs': C['yrs'], 'share': rnd(share, 2)}
        fcf, ni = mat.get('fcf'), mat.get('ni')
        if fcf is not None and fcf > 0: basis, cf0 = 'fcf', fcf * share
        elif ni is not None and ni > 0: basis, cf0 = 'ni', ni
        else: basis, cf0 = None, None
        if cf0:
            flag, gv = _dcf_solve(cf0, cap, r_, gt, C['yrs'])
            D['rev'] = {'basis': basis, 'cf0': rnd(cf0, 1)}
            if basis == 'ni': D['rev']['note'] = ((mat.get('why') or {}).get('fcf')) or 'fcf_neg'
            if gv is None: D['rev']['flag'] = flag
            else: D['rev']['g'] = rnd(gv * 100, 1); cnt['rdcf'] += 1
        else: D['rev'] = {'why': 'loss' if (ni is not None and ni <= 0) else 'nodata'}
        g = mat.get('g')
        if fcf is None: D['fwd'] = {'why': (mat.get('why') or {}).get('fcf') or 'no_cf'}
        elif fcf <= 0: D['fwd'] = {'why': 'fcf_neg'}
        elif g is None: D['fwd'] = {'why': 'no_g'}
        else:
            g1 = min(C['gcap'], max(0.0, g)); gs = _dcf_path(g1 / 100.0, gt, C['yrs']); cf0 = fcf * share
            val = lambda rr: _dcf_pv(cf0, gs, rr, gt)
            pv = val(r_); ip = pv * px / cap
            D['fwd'] = {'cf0': rnd(cf0, 1), 'g_raw': g, 'g_src': mat.get('g_src'), 'g': rnd(g1, 1), 'path': [rnd(v * 100, 1) for v in gs], 'pv': rnd(pv, 0),
                        'v': round(ip), 'up': rnd((ip / px - 1) * 100, 1), 'v_lo': round(val(r_ + 0.01) * px / cap), 'v_hi': round(val(r_ - 0.01) * px / cap)}
            cnt['dcf'] += 1
        V['dcf'] = D
        if 'v' not in D['fwd']: m['dcf'] = {'why': D['fwd']['why']}
        elif D['fwd']['v'] < px / C['far'] or D['fwd']['v'] > px * C['far']: m['dcf'] = {'why': 'far', 'far': rnd(D['fwd']['v'] / px, 2)}
        else: m['dcf'] = {'ip': D['fwd']['v'], 'up': D['fwd']['up'], 'ip_lo': D['fwd']['v_lo'], 'ip_hi': D['fwd']['v_hi']}
        # 6) 범위 — 주력 방법의 환산 주가 최저~최고·중앙, 보조까지 넣은 범위, 현재가의 위치
        main, aux = VALM.get(r.get('stage') or 'etc', VALM['etc'])
        def rng(keys):
            vs = [(m[k]['ip'], k) for k in keys if (m.get(k) or {}).get('ip')]
            if not vs: return {'n': 0}
            ips = sorted(v for v, _ in vs); lo, hi = ips[0], ips[-1]
            o = {'n': len(ips), 'lo': lo, 'hi': hi, 'mid': round(statistics.median(ips)), 'ks': [k for _, k in vs]}
            if len(ips) >= 2:
                o['wide'] = bool(hi / lo > C['wide'])
                if hi > lo: o['pos'] = rnd((px - lo) / (hi - lo) * 100, 0)
                o['zone'] = 'below' if px < lo else 'above' if px > hi else ('low' if o.get('pos', 50) < 33.4 else 'high' if o.get('pos', 50) > 66.6 else 'mid')
            else: o['zone'] = 'above' if px > lo * 1.05 else 'below' if px < lo * 0.95 else 'at'
            return o
        V['range'] = {'main': rng(main), 'all': rng(main + aux)}
        if V['range']['main']['n']: cnt['range'] += 1
        # 7) 통째 배수로 보면 왜곡되는 회사인가(SOTP 필요 신호) — 자동 SOTP 계산은 하지 않는다(사업부별 이익이 공시에 없는 경우가 많다)
        why = []; need = False
        nci, eqt = mat.get('nci'), (fin.get(c) or {}).get('eq')
        if nci is not None and eqt and eqt > 0 and nci / eqt * 100 >= 5:
            pct = nci / eqt * 100; strong = pct >= C['nci_need']; need = need or strong
            why.append({'k': 'nci', 's': int(strong), 't': '비지배지분이 자본총계의 %d%%(%s억) — 연결 영업이익·자산에 남의 몫이 섞여 있습니다' % (round(pct), format(round(nci), ','))})
        elif nci is None and mat.get('ctrl') is not None and mat['ctrl'] < 80:
            need = True; why.append({'k': 'nci', 's': 1, 't': '연결 순이익의 %d%%가 비지배주주 몫 — 연결 영업이익에 남의 몫이 섞여 있습니다' % round(100 - mat['ctrl'])})
        nm = r.get('n') or ''
        if '홀딩스' in nm or nm.endswith('지주') or '지주회사' in ((DEF['co'].get(c) or {}).get('main') or ''):
            need = True; why.append({'k': 'hold', 's': 1, 't': '지주사 성격 — 자회사 지분 가치와 자체 사업을 따로 봐야 합니다'})
        if r.get('pure') == 'low': need = True; why.append({'k': 'pure', 's': 1, 't': '반도체가 전사 매출의 일부 — 반도체 peer 배수를 회사 전체에 곱하면 다른 사업까지 같은 값으로 치게 됩니다'})
        elif r.get('pure') == 'mid': why.append({'k': 'pure', 's': 0, 't': '반도체 외 사업을 함께 합니다(겸업) — 사업별로 맞는 배수가 다를 수 있습니다'})
        sg = _segs(vfs.get(c) or {})
        if len(sg) >= 2:
            strong = len(sg) >= 3 and r.get('pure') != 'high'; need = need or strong
            why.append({'k': 'seg', 's': int(strong), 't': '사업보고서 제품 표에 사업부문이 %d개 — %s' % (len(sg), ' · '.join(sg[:5]))})
        op_ = mat.get('op')
        if ni and op_ and op_ > 0 and ni / op_ > 1.3: why.append({'k': 'eqm', 's': 0, 't': '순이익이 영업이익보다 30% 넘게 큼 — 지분법 자회사·영업외 이익이 영업이익 기준 배수에는 잡히지 않습니다'})
        V['sotp'] = {'need': need, 'why': why}
        if need: cnt['sotp'] += 1
    return {'ver': 1, 'cfg': C, 'methods': {k: {'main': v[0], 'aux': v[1]} for k, v in VALM.items()}, 'why': VWHY, 'count': cnt,
            'rule': {'peer': 'peer 중앙값은 ① A·B등급 peer(표본 1곳 이상) → ② 같은 묶음(2곳 이상) → ③ 같은 단계(3곳 이상) 순으로 넓혀 처음 표본이 채워지는 범위를 쓴다. 배수가 0 이하이거나 상한을 넘는 peer는 빼고 그 수를 남긴다.',
                     'ip': '환산 주가 = 현재가 × (peer 중앙 배수 ÷ 이 회사 배수). EV 계열은 (peer 중앙 배수 × 영업이익·EBITDA·매출 − 순차입금 − 비지배지분) ÷ 주식수. 주식수 = 시가총액 ÷ 현재가(우선주 시총 포함 종목은 우선주도 같은 비율로 움직인다고 본다).',
                     'ev': '순차입금 = 단기차입금 + 유동성장기부채 + 장기차입금 + 사채(전환사채 포함) + 리스부채 − 현금및현금성자산 − 단기금융상품. EV = 시가총액(우선주 포함) + 순차입금 + 비지배지분. 기타 유동 금융자산은 성격을 알 수 없어 현금에 넣지 않는다(ofa에 따로 표시).',
                     'norm': '정상화 이익 = 최근 3개 사업연도 순이익(지배주주)과 최근 4분기 순이익의 단순 평균. 적자 연도도 넣는다.',
                     'band': '자기 과거 밴드 = 최근 5년 일별 PER·PBR의 최저·중앙·최고. 환산 주가 = 현재가 × (과거 중앙 ÷ 현재), 현재 값도 같은 시계열의 마지막 값.',
                     'dcf': '할인율 = 자기자본비용 관행값 10%(가정), 영구성장률 = 장기 명목 성장률 2%(가정). 현금흐름 = FCF × 지배주주 순이익 비율. 역산은 10년 같은 성장률, 순방향은 증권사 추정 성장률(0~30%로 자름)로 5년 뒤 5년에 걸쳐 2%까지 낮춘다. 쌓아 둔 순현금은 더하지 않는다.',
                     'range': '범위 = 단계별 주력 방법의 환산 주가 최저~최고(중앙값 함께). 최고 ÷ 최저가 2배를 넘으면 "방법마다 크게 갈림". 환산 주가가 현재가의 0.1배 미만·10배 초과인 방법은 범위에 넣지 않는다.'}}

def main():
    DEF = load('semipeer_def.json')
    if not DEF: log('semipeer_def.json 없음'); sys.exit(1)
    sv = (load('stockvals.json', {}) or {}).get('map') or {}
    pegj = load('peg.json', {}) or {}
    peg = {r['c']: r for r in pegj.get('rows') or []}
    hegj = load('hege.json', {}) or {}
    hege = {r['c']: r for r in hegj.get('rows') or []}
    prev = load('semipeer.json', {}) or {}
    codes = sorted(DEF['co'].keys())

    # 1) 재무 캐시
    fin = prev.get('fin') or {}; fin_meta = prev.get('fin_meta') or {}; corpcache = prev.get('corpmap') or {}
    finx = prev.get('finx') or {}                            # 밸류 재료 캐시(순차입금·감가상각비·현금흐름)
    need = REFRESH or not fin_meta.get('date') or fin_meta.get('ver') != FIN_VER or bool(fin_meta.get('xfail')) or bool(fin_meta.get('quota'))
    if not need:
        try: need = (TODAY - datetime.date.fromisoformat(fin_meta['date'])).days >= FIN_TTL_DAYS
        except Exception: need = True
        if fin_meta.get('asof') != '%dQ%02d' % (latest_quarter()[1], latest_quarter()[0] % 100): need = True
    if need and KEY and not OFFLINE:
        fin, meta, cm, finx = collect_fin(codes, fin, corpcache, finx)
        if meta: fin_meta = meta
        if cm: corpcache = cm
    elif need: log('DART 키 없음/오프라인 — 재무는 기존 캐시(%s) 또는 KIS·hege 대체값 사용' % (fin_meta.get('date') or '없음'))

    # 2) 선행(증권사 추정)·우선주 시총
    fwd = prev.get('fwd') or {}; prefcap = prev.get('prefcap') or {}; nv = prev.get('nv') or {}
    if not isinstance(nv, dict): nv = {}
    if not OFFLINE:
        n = 0
        for c in codes:
            o = naver_basic(c); time.sleep(0.1)
            if o: o['date'] = TODAY.isoformat(); nv[c] = o; n += 1
        log('네이버 요약(PER·PBR) 수집 %d종목' % n)
        n = 0
        for c in codes:
            if c in peg and peg[c].get('status') == 'ok': continue
            fy = naver_consensus(c); time.sleep(0.12)
            if fy: fwd[c] = {'fy': fy, 'date': TODAY.isoformat()}; n += 1
        log('네이버 컨센 수집 %d종목' % n)
        for c, ps in PREF.items():
            if c not in DEF['co']: continue
            tot = 0.0; ok = True
            for p in ps:
                v = naver_cap(p); time.sleep(0.12)
                if v is None: ok = False; break
                tot += v
            if ok: prefcap[c] = {'cap': tot, 'date': TODAY.isoformat()}
        log('우선주 시총 %s' % {k: v['cap'] for k, v in prefcap.items()})

    # 3) 종목별 지표
    GMAP = {g['id']: g for g in DEF['groups']}
    co = {}
    for c in codes:
        d = DEF['co'][c]; v = sv.get(c); f = fin.get(c) or {}; h = hege.get(c) or {}; pg = peg.get(c) or {}
        g0 = GMAP.get((d.get('gids') or [None])[0]) or {}
        r = {'n': d['n'], 'pure': d.get('pure'), 'gids': d.get('gids') or [], 'top': g0.get('top'), 'seg': g0.get('seg'), 'map': bool(d.get('map')), 'stage': d.get('stage') or 'etc', 'procs': d.get('procs') or [], 'flags': []}
        if not v or not v[2]:
            r['flags'].append('시세 없음'); co[c] = r; continue
        kpbr, kper, cap0, px = v[0], v[1], v[2], v[3]
        kroe = v[4] if len(v) > 4 else None
        cap = cap0
        if c in PREF:
            if c in prefcap: cap = cap0 + prefcap[c]['cap']; r['pref'] = rnd(prefcap[c]['cap'], 0)
            else: r['flags'].append('우선주 시총 미반영 — PER·PBR이 실제보다 낮게 보일 수 있음')
        r.update({'px': px, 'cap': rnd(cap, 0), 'kper': kper, 'kpbr': kpbr})
        # 매출·영업이익 TTM: DART 캐시 우선, 없으면 hege(같은 DART 주요계정, 주 1회)
        rev = f.get('rev'); op = f.get('op'); rev0 = f.get('rev_prev'); op0 = f.get('op_prev'); asof = f.get('asof')
        if rev is None and h.get('rev'):
            rv, ov = h['rev'], h['op']
            if len(rv) >= 4 and all(x is not None for x in rv[-4:] + ov[-4:]):
                rev, op = sum(rv[-4:]), sum(ov[-4:]); asof = h.get('q')
                if len(rv) >= 8 and all(x is not None for x in rv[-8:-4] + ov[-8:-4]): rev0, op0 = sum(rv[-8:-4]), sum(ov[-8:-4])
        ni_tot = f.get('ni'); ni = f.get('ni_p', ni_tot); eq = f.get('eq_p', f.get('eq'))
        r['asof'] = asof; r['fs'] = f.get('fs') or h.get('fs')
        r['rev'] = rnd(rev, 0); r['op'] = rnd(op, 0)
        r['rev0'] = rnd(rev0, 0); r['op0'] = rnd(op0, 0)                 # 1년 전 같은 기간(직전 4분기 합산)
        # 분기 추이(최근 8분기 매출·영업이익, hege.json = DART 주요계정)
        if h.get('rev') and h.get('ql'):
            k = min(8, len(h['ql']), len(h['rev']), len(h['op']))
            r['ql'] = h['ql'][-k:]; r['rq'] = h['rev'][-k:]; r['oq'] = h['op'][-k:]
        r['psr'] = rnd(div(cap, rev)) if rev and rev > 0 else None
        r['por'] = rnd(div(cap, op)) if op and op > 0 else None
        r['opm'] = rnd(div(op, rev) * 100, 1) if (rev and rev > 0 and op is not None) else None
        r['g_op'] = rnd(growth(op, op0), 1); r['g_rev'] = rnd(growth(rev, rev0), 1)
        bv = {}
        if ni is not None and eq:
            r['ni'] = rnd(ni, 0); r['eq'] = rnd(eq, 0)
            r['ni_t'] = rnd(ni_tot, 0); r['ni0'] = rnd(f.get('ni_prev'), 0)   # 연결 순이익 전체(비지배 포함)와 1년 전 값
            bv['TTM'] = [rnd(cap / ni) if ni > 0 else None, rnd(cap / eq) if eq > 0 else None,
                         rnd(ni / eq * 100, 1) if eq > 0 else None]      # ROE = 최근 4분기 순이익 ÷ 기말 자본
            r['npm'] = rnd(ni / rev * 100, 1) if rev and rev > 0 else None
            r['g_ni'] = rnd(growth(ni_tot, f.get('ni_prev')), 1)
            if f.get('as') and ni_tot is not None: r['roa'] = rnd(ni_tot / f['as'] * 100, 1)        # 연결 순이익 전체 ÷ 자산총계
            if f.get('li') is not None and f.get('eq'): r['debt'] = rnd(f['li'] / f['eq'] * 100, 0)   # 부채총계 ÷ 자본총계
            if 'ni_p' in f and ni_tot: r['ctrl'] = rnd(ni / ni_tot * 100, 0)
            elif f.get('fs') == 'CFS': r['flags'].append('지배주주 몫 미확인 — 연결 순이익 전체(비지배지분 포함) 기준')
            if ni <= 0: r['flags'].append('최근 4분기 순손실 — PER 계산 불가')
        n_ = nv.get(c) or {}
        if n_.get('pbr') or n_.get('per'):
            nroe = rnd(n_['eps'] / n_['bps'] * 100, 1) if (n_.get('eps') is not None and n_.get('bps')) else None
            bv['TTMN'] = [n_['per'] if (n_.get('per') or 0) > 0 else None, n_['pbr'] if (n_.get('pbr') or 0) > 0 else None, nroe]
        bv['FY0'] = [kper if (kper and kper > 0) else None, kpbr if (kpbr and kpbr > 0) else None, kroe]
        r['basis'] = 'TTM' if 'TTM' in bv else 'TTMN' if 'TTMN' in bv else 'FY0'
        r['bv'] = bv
        r['per'], r['pbr'], r['roe'] = bv[r['basis']]
        if r['basis'] == 'TTMN':
            r['flags'].append('DART 최근 4분기 수집 전 — PER·PBR·ROE는 네이버(FnGuide)의 최근 4분기 주당순이익·주당순자산 기준')
            if r['per'] is None: r['flags'].append('PER 없음 — 최근 4분기 순손실')
        elif r['basis'] == 'FY0':
            r['flags'].append('최근 4분기 순이익 미수집 — PER·PBR·ROE는 전년 확정 실적(KIS) 기준')
            if r['per'] is None: r['flags'].append('PER 없음 — 전년 순손실이거나 KIS가 값을 주지 않음')
        elif bv.get('TTMN') and bv['TTMN'][0] and r['per']:
            dv = r['per'] / bv['TTMN'][0] - 1
            if abs(dv) > 0.2: r['flags'].append('PER 교차확인: DART 기준 %.1f배 vs 네이버(FnGuide) %.1f배 — 20%%↑ 차이(일회성 손익·주식 수 변동·지배주주 몫 확인 필요)' % (r['per'], bv['TTMN'][0]))
        # 선행(증권사 추정)
        if pg.get('status') == 'ok':
            r['fwd'] = {'per_f12': pg.get('per_f12'), 'cagr2': pg.get('cagr2'), 'g1': pg.get('g1'), 'peg': pg.get('peg2'), 'src': pg.get('src')}
        elif c in fwd:
            o = fwd_from_fy(fwd[c].get('fy'), cap)
            if o.get('per_f12'):
                gg = o.get('cagr2') if o.get('cagr2') is not None else o.get('g1')
                o['peg'] = rnd(o['per_f12'] / gg) if gg and gg > 0 else None
                r['fwd'] = {k: o.get(k) for k in ('per_f12', 'cagr2', 'g1', 'peg', 'src')}
        # 국면
        if h:
            r['ph'] = h.get('ph'); r['hq'] = h.get('q'); r['streak'] = h.get('streak')
            r['new1'] = bool(h.get('new1')); r['entry2'] = bool(h.get('entry2')); r['slow'] = bool(h.get('slow'))
            r['rg'] = h.get('rg'); r['og'] = h.get('og'); r['hist'] = h.get('hist')
        # 신뢰도 경고
        if r.get('ni') is not None and op and op > 0 and r['ni'] > 0:
            k = r['ni'] / op
            if k > 1.3: r['flags'].append('순이익이 영업이익의 %.1f배 — 영업외 이익(일회성 가능) 영향이 커 PER이 낮게 보일 수 있음. P/OP 함께 확인' % k)
            elif k < 0.5: r['flags'].append('순이익이 영업이익의 절반 미만 — 영업외 비용 영향. P/OP 함께 확인')
        if r.get('per') and r['per'] > PER_MAX: r['flags'].append('PER %d배↑ — 이익이 매우 작은 상태라 PER 비교에서 제외' % PER_MAX)
        if r.get('g_ni') is not None and r['g_ni'] >= G_CAP: r['flags'].append('순이익 증가율이 기저효과로 과장(300%↑ 또는 흑자전환) — 비교할 때 300%로 봄')
        elif r.get('g_ni') is None and r.get('g_op') is not None and r['g_op'] >= G_CAP: r['flags'].append('영업이익 증가율이 기저효과로 과장(300%↑ 또는 흑자전환) — 비교할 때 300%로 봄')
        if d.get('pure') == 'low': r['flags'].append('반도체가 전사 매출의 일부 — 전사 멀티플이 반도체 사업 가치를 그대로 반영하지 않음')
        if r.get('ctrl') is not None and r['ctrl'] < 85: r['flags'].append('비지배지분 몫 %d%% 제외(지배주주 순이익 기준)' % (100 - r['ctrl']))
        co[c] = r

    # 4) 쌍 비교 — A·B등급 peer에 대해서만 지표별 비율·차이를 모은다(C등급은 화면에서 숫자만 나란히 보여 준다)
    pairs = []; agg = {c: {'nA': 0, 'nB': 0, 'nC': 0, 'v': {}, 'pm': {}} for c in codes}
    for p in DEF['pairs']:
        a, b, g = p['a'], p['b'], p['grade']
        x, y = co.get(a) or {}, co.get(b) or {}
        bx, by = x.get('bv') or {}, y.get('bv') or {}
        bs = next((k for k in ('TTM', 'TTMN', 'FY0') if k in bx and k in by), None)
        def at(r, k):
            if not k or 'bv' not in r: return r
            v = r['bv'][k]; return dict(r, per=v[0], pbr=v[1], roe=v[2], g_ni=(r.get('g_ni') if k == 'TTM' else None))
        fx, fy_ = at(x, bs), at(y, bs)
        capr = None
        if x.get('cap') and y.get('cap'): capr = max(x['cap'], y['cap']) / min(x['cap'], y['cap'])
        pairs.append({'a': a, 'b': b, 'g': g, 'sum': p['sum'], 'gid': p['gid'], 'bs': bs, 'capr': rnd(capr, 1)})
        for me, mine, theirs in ((a, fx, fy_), (b, fy_, fx)):
            A = agg[me]; A['n' + g] += 1
            if g not in ('A', 'B') or 'cap' not in mine or 'cap' not in theirs: continue
            for k, (v, pv) in cmp_pair(mine, theirs).items():
                A['v'].setdefault(k, []).append(v); A['pm'].setdefault(k, []).append(pv)

    # 5) 종목별 꼬리표 — PER 꼬리표가 대표 표시(sig), 나머지는 독립 꼬리표
    for c in codes:
        r = co[c]; A = agg[c]
        r['nA'], r['nB'], r['nC'] = A['nA'], A['nB'], A['nC']
        if 'cap' not in r: r['sig'] = 'nodata'; continue
        if A['nA'] + A['nB'] == 0: r['sig'] = 'nopeer'; continue
        # 근거 강도: A등급 peer가 있고 peer가 둘 이상이면 3, A가 하나 있거나 B가 둘 이상이면 2, B 하나뿐이면 1
        r['conf'] = 3 if (A['nA'] >= 1 and A['nA'] + A['nB'] >= 2) else 2 if (A['nA'] >= 1 or A['nB'] >= 2) else 1
        tags = {}
        for k in ('per', 'pbr', 'psr'):
            t = tag_ratio(A['v'].get(k))
            if t: tags[k] = t
        for k in ('roe', 'opm', 'roa', 'g', 'debt'):
            t = tag_diff(A['v'].get(k), TOL[k])
            if t: tags[k] = t
        r['tags'] = tags
        r['pm'] = {k: rnd(statistics.median(v), 1 if k in ('roe', 'opm', 'roa', 'g', 'debt') else 2) for k, v in A['pm'].items() if v}
        if A['v'].get('per'): r['disc'] = rnd((statistics.median(A['v']['per']) - 1) * 100, 0)   # 쌍마다 같은 기준으로 맞춘 PER 비율의 중앙값
        loss = (r.get('op') is not None and r['op'] <= 0) or (r.get('basis') == 'TTM' and r.get('ni') is not None and r['ni'] <= 0) or r.get('per') is None
        thin = bool(r.get('per') and r['per'] > PER_MAX)
        if loss or thin: r['sig'] = 'loss'                  # 적자·이익 미미 — PER 꼬리표를 붙이지 않는다
        elif 'per' not in tags: r['sig'] = 'noper'          # peer 쪽이 적자·이익 미미라 PER을 비교할 수 없음
        else: r['sig'] = {'low': 'lowper', 'mid': 'midper', 'high': 'highper'}[tags['per']]
        # 저PER을 그대로 믿기 전에 볼 것(짧은 경고 코드 — 화면에서 문구로 풀어 쓴다)
        w = []
        gq = r.get('g_ni') if r.get('g_ni') is not None else r.get('g_op')
        if gq is not None and gq >= G_CAP: w.append('peak')                                   # 이익 급증(흑전·300%↑) — 호황 정점일 수 있음
        if r.get('ni') and r.get('op') and r['op'] > 0 and r['ni'] / r['op'] > 1.3: w.append('nonop')   # 영업외 이익 영향
        if r.get('ph') in (3, 4): w.append('ph34')                                              # 3·4국면
        if r['conf'] == 1: w.append('one')                                                      # 비교 상대가 B등급 하나뿐
        if r.get('pure') == 'low': w.append('pure')                                             # 반도체 비중 작음
        if any('교차확인' in f for f in r['flags']): w.append('xchk')                             # DART vs 네이버 PER 20%↑ 차이
        r['warn'] = w

    # 5-2) PBR–ROE 판정
    try: prmeta = pbr_roe(co, DEF['pairs'])
    except Exception as e: prmeta = None; log('PBR–ROE 판정 실패 %r' % e)

    # 5-3) 평가법별 책정값(이 회사 배수·peer 중앙값·환산 주가·범위·DCF)
    try: valmeta = build_val(co, fin, finx, DEF, fwd, peg); log('책정값 %s' % valmeta['count'])
    except Exception as e:
        valmeta = None; log('책정값 계산 실패 %r' % e)
        for r in co.values(): r.pop('val', None)

    # 6) 그룹 중앙값(참고 — 등급과 무관하게 같은 묶음 전체)
    groups = []
    for g in DEF['groups']:
        ms = [m for m in g['members'] if m in co and 'cap' in co[m]]
        def med(k):
            vs = [co[m][k] for m in ms if co[m].get(k) is not None and co[m][k] > 0]
            return rnd(statistics.median(vs)) if len(vs) >= 2 else None
        groups.append({'id': g['id'], 'name': g['name'], 'seg': g['seg'], 'top': g.get('top'), 'n': len(ms), 'per': med('per'), 'pbr': med('pbr'), 'psr': med('psr')})

    cnt = {}
    for r in co.values(): cnt[r.get('sig')] = cnt.get(r.get('sig'), 0) + 1
    nb = sum(1 for r in co.values() if r.get('basis') == 'TTM'); nbn = sum(1 for r in co.values() if r.get('basis') == 'TTMN')
    out = {'updated': NOW.strftime('%Y-%m-%d %H:%M'), 'price_updated': (load('stockvals.json', {}) or {}).get('updated'),
           'hege_q': hegj.get('asof_quarter'), 'fin_meta': fin_meta, 'n': len(co), 'n_ttm': nb, 'n_ttmn': nbn, 'count': cnt,
           'th': {'cheap': CHEAP, 'dear': DEAR, 'tol': TOL, 'gcap': G_CAP, 'permax': PER_MAX},
           'rule': {'tag': 'A·B등급 peer와 쌍마다 비교해 (내 값 ÷ peer 값)의 중앙값이 0.9 이하면 낮음, 1.1 이상이면 높음(PER·PBR·PSR). ROE·영업이익률·ROA는 1%p, 성장률은 5%p, 부채비율은 20%p 넘게 차이 나면 높음/낮음',
                    'per': '대표 표시는 PER 꼬리표 하나(저PER·비슷·고PER). 최근 4분기 영업적자·순손실이거나 PER 150배 초과면 붙이지 않음. 성장률은 300% 상한으로 비교',
                    'basis': 'TTM = DART 최근 4분기 합산(확인값). TTMN = 네이버(FnGuide) 최근 4분기 주당순이익·주당순자산(DART 수집 전 임시). FY0 = KIS 전년 확정 실적'},
           'pr': prmeta, 'val_meta': valmeta, 'co': co, 'pairs': pairs, 'groups': groups, 'fin': fin, 'finx': finx, 'fwd': fwd, 'prefcap': prefcap, 'nv': nv, 'corpmap': corpcache, 'debug': DEBUG[-40:]}
    # 빈 결과 가드: 시세가 붙은 종목이 기존의 1/3 미만이면 덮어쓰지 않는다
    n_new = sum(1 for r in co.values() if 'cap' in r); n_old = sum(1 for r in (prev.get('co') or {}).values() if 'cap' in r)
    if n_old and n_new < n_old / 3:
        log('시세 붙은 종목 %d < 기존 %d의 1/3 — 저장 생략' % (n_new, n_old)); return
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(out, open(OUT, 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'))
    log('저장 %s 종목 %d (DART TTM %d · 네이버 TTM %d) 판정 %s' % (OUT, len(co), nb, nbn, cnt))

if __name__ == '__main__': main()
