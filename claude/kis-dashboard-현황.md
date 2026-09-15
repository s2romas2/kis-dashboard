# kis-dashboard 프로젝트 현황 (2026-09-15 기준)

> 이 파일이 원본. 프로젝트 지식(앱 업로드)·다운로드 폴더 사본은 더 이상 갱신하지 않음 — 작업 결과는 `claude/` 안의 파일을 직접 수정해 커밋한다.

## 개요
- 배포: https://kis-dashboard.onrender.com / 저장소: github.com/s2romas2/kis-dashboard (공개 유지 필수)
- 키: DART_KEY·KIS_APPKEY·KIS_APPSECRET·KRX_ID/PW·CUSTOMS_KEY·CENSUS_KEY=GitHub Secrets (8/27 전부 가동 확인)
- git 푸시(클라우드 세션 시절): extraheader Basic PAT — 8/25 새 토큰(repo+workflow). 컨테이너 초기화 시 재요청(repo+workflow 필수)
- 8/25 fine-grained PAT(kis-dashboard 전용·Contents만) — 주간 섹터흐름·분기 IR워치 예약작업 프롬프트에 내장
- **9/10 PC 세션 반영 경로 확립**: 로컬 클론 `C:\Users\ladea\Downloads\kis-dashboard` (Git for Windows 2.55 설치, git-credential-manager 브라우저 로그인 완료 → 이후 push 무인증). 클라우드 세션은 push 403·PC 폴더 불가 → 대시보드 반영은 PC 세션에서
- **9/11~ 셸 마운트 고장 시 우회**: `C:\Users\ladea\Downloads\kis-apply\stepN.bat`(PowerShell로 python·git 실행, stepN.log 기록)을 탐색기 더블클릭. 절차는 `claude/README-반영방법.md`. **무인 예약작업 중엔 computer-use 승인 불가** → 9/12 valalert.py는 Chrome(Claude in Chrome) GitHub 웹 업로드(github.com/…/upload/main, file_upload)로 직접 커밋(7a01026). 단 이 경우 로컬 클론이 dirty가 되어 다음 stepN.bat 은 `git checkout -- <파일>` 후 pull 필요(step6·step7에 반영). 미추적 파일(claude/ 신규 문서)은 웹 업로드하면 pull 충돌 → 로컬 bat 커밋으로만

## 🗂️ 업종 랭크테이블 업그레이드 (9/15 새벽 무인 예약작업 kis-ranktable-upgrade — 코드 준비 완료, 커밋은 `kis-apply\rank.bat`)
- 실행 환경: 셸 마운트 고장 + 무인 중 computer-use 승인 불가 + Claude in Chrome 미연결 + 내장 브라우저는 GitHub 미로그인(upload 페이지 "push access 필요") → **코드·yml·문서는 로컬 클론에 직접 작성, 커밋·푸시는 `C:\Users\ladea\Downloads\kis-apply\rank.bat` 더블클릭(rank.log 확인)**. rank.ps1은 py_compile 3종 통과 시에만 A→C→D→B(UI+문서) 4커밋 후 `pull --rebase --autostash` → push
- **[A] 딥 히스토리** `leaders.py` v3: `candles()`가 `[일자, 종가, 거래대금(억원), 거래량(주)]` 반환(acml_tr_pbmn·acml_vol). dv=2로 최초 1회 풀백필 — 일봉 2020-01-02~ 60달력일 창(~40거래일, 호출당 ~50봉 제한 안전), 주봉 2018-01-02~ 240일 창. 보관 상한 daily 1700·weekly 450, 호출 간 0.06초, 실패 시 1회 재시도(`candles_retry`). 백필 결과가 부족(일봉 최대 300개 미만)하면 dv를 올리지 않아 다음 실행에서 재시도. 월봉 hv=2 캐시(2001~)는 그대로 재사용(재수집 없음). 순위 계산용 최근 일봉도 병합 캐시에서 가져와 API 창 절단 영향 제거. leaders.yml timeout 30→55분(첫 백필 ~3,000콜 ≈ 10~15분 예상)
  - **거래대금 단위는 추정**: KOSPI(0001) 최근 일봉 acml_tr_pbmn 중앙값이 1e11↑이면 원, 1e8↑이면 천원, 그 미만이면 백만원으로 가정해 억원 환산 — `leaders.json.debug`·`money_note`에 기록. 첫 실행 후 `money.v5`가 코스피 전기·전자 기준 수조원대인지 확인 필요(틀리면 `guess_val_unit` 임계값 조정)
- **[B] 거래대금 축** `leaders.json.money{code:{n,mkt,v5,v60,x,share,asof}}` + `money_top`(x 상위 10). x = 최근 5일 평균 ÷ 직전 60일 평균, share = 시장 내 5일 평균 점유율. ranktable.html: 마지막 칸 🔥(x≥1.8) 배지, 상단 "💰 돈 몰리는 업종 Top5", **순위 기준 토글(수익률/거래대금)** — 일·주는 봉 거래대금, 월·분기·반기·연은 일봉 합산(2020~). periods 엔트리에 `code` 추가(기존 n·mkt·r 유지 → leaders.html 영향 없음)
- **[C] 밸류 축** `sectorval.py`(신규) + `sectorval.yml`(평일 09:50 UTC=18:50 KST, push 트리거): KRX MDCSTAT00701(전체지수 PER/PBR/배당수익률) 코스피(idxIndMidclssCd 02)·코스닥(03) 당일값 → `public/data/sectorval.json {updated,date,map:{"업종명|시장":{per,pbr,div,fper,idx,raw,date,pbr_pct,pbr_n}},hist:{key:[[일자,PBR,PER]]},all,debug}`. 지수명 접두어(코스피/코스닥) 제거 후 leadershist 업종명과 느슨 매칭. 당일 빈 응답이면 직전 영업일로 최대 6일 후퇴. **KRX는 valuation.py에서 9/10 기준 HTTP 400(GitHub Actions IP)이라 성공 보장 없음** — 헤더(Referer 2종·https/http)·파라미터(idxIndMidclssCd/indTpCd) 변형을 순서대로 시도하고 실패 시 기존 파일 유지+debug. KRX_ID/PW 로그인은 폼을 오프라인에서 확인할 수 없어 미구현(쿠키 워밍업만). **KRX 실패 시 폴백**: sectorstocks.py가 견인 top15의 KIS 현재가 per/pbr를 시총가중(조화평균)한 `est{per,pbr,n}`를 넣어 패널에 "추정"으로 표시. PBR 이력 20일 이상 쌓이면 백분위(pbr_pct) 표시, 순위 상승 업종(🔺/🌱)이 PBR 하위 40%면 "🧲 밸류 대비 순위 상승" 배지
- **[D] 수급 축** `sectorstocks.py` v2: 견인 top15 종목마다 KIS 투자자매매동향(FHKST01010900, inquire-investor) 최근 5거래일 외국인·기관 **순매수수량×종가**를 억원으로 합산(단위 확실한 조합. API의 순매수대금 필드는 첫 응답에서 `필드/(수량×종가)` 비율만 DEBUG에 기록 → 원/백만원 판정 후 필요 시 전환) → `sectors[key].flow{f5,o5,n,last,note}`, 종목별 `f5,o5,per,pbr`. 응답 키는 CODE_KEYS 방식으로 방어적 매핑 + 첫 응답 키 DEBUG. 현재가(FHKST01010100) 호출 추가로 ~1,600콜, 0.06초 대기, sectorstocks.yml timeout 20→35분
- **[E] KRX 구성종목으로 sectormap 대체는 미착수**(응답 확인 불가). 기존 KIS 업종코드 매칭 유지
- 검증 필요(사용자·다음 세션): ① rank.log "push exit code: 0" ② 푸시 5~15분 뒤 leaders/sectorstocks/sectorval 워크플로 성공(leaders 첫 실행은 백필로 길다) ③ ranktable.html?v=… 렌더: 일별 보기에서 연도 2020 선택, 순위:거래대금 토글, 업종 클릭 시 💰/🧭/📐 지표 줄 ④ leaders.json.debug의 "거래대금 단위"·"백필 결과" 줄, sectorstocks.json.debug의 "투자자동향 응답 키"·"순매수대금 필드/(수량×종가) 비율", sectorval.json.debug의 KRX 성공 여부
- 한계: 거래대금·순매수 단위는 첫 실행 결과로 확정해야 함 / KRX 400이면 PER/PBR은 KIS 추정만 / leadershist.json이 ~4~5MB로 커짐(Render gzip 전제) / 견인 종목은 등락률순위 상위이므로 수급·밸류 합산은 "업종 전체"가 아닌 "견인 상위 15종목" 표본

## 📞 콜 노트 (9/12 반영 — 커밋 __HASH6__)
- 2026-09-12 무인 예약작업(kis-callnote-update): 셸 마운트 고장 + 무인 실행 중엔 computer-use 승인 불가 → 데이터·스크립트(`kis-apply\new6.json·w6.json·sum6.json·prep6.py·verify6.py·step6.bat`)만 준비. **사용자가 step6.bat 더블클릭 → step6.log의 "push exit code: 0"·verify 출력(주식 85/현금 15) 확인** 필요
- 9/9~9/11 신규 23건(Call No.67~89, rptNo 2074~2110) 병합·요약·비중·스타일·kind 교정 → calls.enc 갱신. 9/12(토)는 신규 없음
- 포트 액션: 9/10 SK하이닉스 15→17.5% 상향(No.79) / 9/11 삼성SDS 5→0% 편출(No.83) + SK하이닉스 17.5→20% 상향(No.84) → 주식 85%·현금 15% 유지. 7기 현재 11종목(삼전 27.5·하이닉스 20·LG이노텍·LS·팬오션·삼성SDI·SKT·이수페타시스 각 5·두산에너빌리티·LG생건·BGF 각 2.5)
- 발견: 같은 Call No.가 새 rptNo로 재등록되는 경우 있음(9/8 No.65·66 → 2072·2073). merge 전 (callNo,기수) 중복 제외 로직 필요 — `kis-apply\prep6.py`, 절차 문서에 반영
- 문서 이전: 프로젝트 지식 문서 5종(현황·소부장 대장주·콜노트 절차·강의노트 절차·README 반영방법)을 `claude/`로 옮김(암호·플레이어 키는 "(프로젝트 지식 원본 참조)"로 치환). 이후 갱신은 `claude/`에서 직접

## 🔦 광통신 맵 (9/10 반영 — 커밋 8278e7d)
- 2026-09-10 광통신 맵 4탭 확장(마인드맵·관점합류도·용어구조) + optics.py 해외시세 워크플로 + 강의 15강 + 블로그 pokara61 — 커밋 8278e7d, PC 세션에서 반영
- optics.html 탭 4개: 📄 밸류체인 리포트 / 🕸 마인드맵(노드 181+, 대장주 뷰·8개 분야 뷰) / 🧭 관점 합류도(국내 7+해외 16=23건, S급5·A급3·B급3·논쟁6·사각지대5, 목표주가·투자의견 전량 제외) / 📚 용어·구조(용어 34 + SVG 도해 3종)
- 시세: 국내 25노드 → stockvals.json(sc:'코드') / 해외 49노드 → optics.py KIS 해외현재가상세 HHDFS76200200 24종목(미14·일4·중6, q:'티커'), optics.yml 평일 KST 07:30. optics_quotes.json 씨드=미국 14종목(9/8 종가), 일·중은 첫 실행 때 채움. 대만 KIS 미지원, 비상장 제외
- 강의 lectures.enc 15강 버전(g13 9/4~9/7 Call 리뷰 28:34 포함, 256KB 1줄) / 블로그 blogkeys.json pokara61(포카라의 실전투자, sec 종합) 추가 → 총 12명, 푸시 직후 blogs.yml 자동 수집 12건 확인

## 💠 소부장 맵 세부분야·대장주 (9/10~9/11 반영)
- 2026-09-10 소부장 맵에 세부분야 필터(25개)·대장주/2·3위 순위 패널(리포트 원문 인용문·페이지·PDF 링크)·기업 상세 드로어(특화·차별성·공통 KPI·출처·근거등급 A/B/C) 추가 — 데이터 `public/data/semidetail.json`, 빌드 `tools/semidetail/build_semidetail.py`(원자료 raw_co_*·raw_rank_*). 1차 범위 파츠·열처리·테스트·패키징장비 ~52사. 근거 원칙: 증권사·한국IR협의회 원문 PDF + 전문매체(디일렉·전자신문·TrendForce·SEMI·Gartner·TechInsights·KSIA·KIPOST) + 공시만, 일반 뉴스·집계사이트 제외(빌드 시 자동 필터)
- mk_semimap: 자비스 코드 196450→254120 정정, 티엘비(356860)·고영(098460)·한화비전(489790) 추가
- 리포트 아카이브: `public/data/report_seeds.json` 큐레이션(광통신 5·유리기판 3, 30p+)을 reports.py가 archive에 병합, reports.html 아카이브 탭 🔦광통신·🪟유리기판 필터 추가
- 쏘캠 결론: 심텍 1위(모듈PCB+MCP 동시공급 유일·메모리 3사·'27 3,210억) / 티엘비 2위(비중 '28 50%·순수도, SK는 '대장주'로 명명) / 코리아써키트 3위. 상세 문서 `반도체-소부장-세부분야-대장주-2026-09.md`
- 2차 반영(9/10, 커밋 7decfbf2): 전공정 장비·계측/포토·소재·인프라·기판·OSAT 22개 세부분야 추가 → 칩 47개·기업 137사·dropped_refs 14, 원자료 `tools/semidetail/raw2_*.json`, 순위 전용 기업 근거 승계, 코드 정정(씨앤지하이테크·하이록코리아·라온로보틱스·엘비루셈 합병)
- 2차 마무리(9/11, 커밋 cab097f5 — step4.bat): 칩 id 중복 probe/stf 분리, 목표주가 금액 문장 제거 강화, semi.html 범례 문구, 예스티 HPA 원가 근거 재조사(챔버 내재화 디일렉 인용·원가 우위 원문 미확보 명시). 빌드 결과 companies 137·fields 47·dropped_refs 14. 순위표는 `반도체-소부장-세부분야-대장주-2026-09.md` §7
- 9/11 텔레그램 밸류 알림 추가(커밋 f0ea8183 — step5.bat): valalert.py + valalert.yml(평일 09:00 KST) — 에이피알·동국제약·아로마티카·펌텍코리아 트레일링/12M Fwd PER·P/OP

## 📨 텔레그램 밸류 알림 (9/11 신설, 9/12 검증·수정 — valalert.py + .github/workflows/valalert.yml)
- 소스: `valalert.py` / 워크플로 `valalert.yml` — cron `0 0 * * 1-5` UTC(=평일 09:00 KST) + workflow_dispatch + `valalert.py` push 트리거. 결과 `public/data/valalert.json`(메시지·debug·종목별 원본 응답) 자동 커밋
- 시크릿: KIS_APPKEY·KIS_APPSECRET·DART_KEY(기존) + **TELEGRAM_BOT_TOKEN·TELEGRAM_CHAT_ID(사용자 등록 필요, 값은 코드·문서에 절대 기재 금지)**. 미등록이면 debug에 "TELEGRAM_BOT_TOKEN/CHAT_ID 없음 → 발송 생략"·`sent:false`. 휴장일은 발송 생략(FORCE=1 env로 강제 가능)
- 대상 4종목: 에이피알 278470 / 동국제약 086450 / 아로마티카 0015N0(신형 영문혼합 코드, KIS·DART 모두 정상 조회 확인) / 펌텍코리아 251970. DART corp_code 상수(01190568·00114808·01381805·00761059) — 누락 시 corpCode.xml 폴백
- 계산: 트레일링 = DART fnlttSinglAcntAll 직전 4분기(25Q3~26Q2, Q4=사업보고서−3Q누적) 영업이익·순이익(지배주주 우선) 합산 → PER=시총÷순이익, P/OP=시총÷영업이익. 12M Fwd = KIS 종목추정실적(HHKST668300C0) FY1·FY2 잔여일 가중
- **9/11 첫 실행(run 34557923801, push 트리거) 결과**: success, 6분16초(스크립트 단계), 결과 커밋 OK. 4종목 시세·트레일링 4분기 모두 확보. 발송은 시크릿 미등록으로 생략
- **9/12 검증에서 찾은 문제 → 수정(커밋 7a01026 — 셸·computer-use 모두 불가라 GitHub 웹 업로드로 valalert.py 커밋, 로컬 클론 동기화는 `kis-apply\step7.bat`)**:
  - 추정실적 구조 확정: output4.dt=[2023.12,2024.12,2025.12,2026.12E,2027.12E]=data1~5, output2=라벨 없는 6행(매출액·증감율·영업이익·증감율·순이익·증감율, 증감율은 0.1%p 단위). 근거: 순이익 행 2025=2897억 ≈ KIS eps 7704×3,744만주. 런타임에 증감율 행으로 순서 검증, 불일치면 '조회 실패'
  - **추정실적 API는 한국투자증권 리서치 단일 추정(output1.name1=애널리스트)이지 컨센서스가 아님**. 미커버 종목(동국제약·아로마티카·펌텍코리아)은 전부 빈 값 → 메시지에 "KIS 리서치 미커버" 표기. 문구 '컨센서스'→'KIS리서치'로 정정
  - 펌텍코리아 순이익 버그: 보고서마다 계정 매칭이 달라(Q3 ni만·Q1/Q2 nip만·사업보고서 없음) 누락 분기를 0으로 합산 → 순이익 132억·PER 50.5로 잘못 산출(KIS PER 19.3). 계정 매칭 강화(번호 접두 제거·표준 ID·'지배기업소유주지분' 인정·순이익 정규식) + 분기별 nip→ni 대체, 한 분기라도 없으면 합산 안 함
  - 에이피알 계산 PER 32.2 vs KIS 48.2: 오류 아님 — KIS per는 직전 결산(2025) EPS 기준, 트레일링은 26Q1·Q2 급성장 반영. 이후 ±30% 괴리는 debug에 기록(`per_gap_vs_kis`)
  - 실행시간: corpCode.xml 다운로드 제거 + 3Q 보고서 재호출 캐시 → **재실행(run 34652968226, 9/12 07:12 KST) 2분18초(종목 처리 110초), 6분38초→단축 확인**
- **9/12 재실행 결과**: 4종목 모두 시세·트레일링 4분기 확보. 펌텍 지배주주 순이익 4분기 모두 매칭(112.4·13.6·126.6·181.9=434억, PER 15.1, KIS 19.0 대비 −21%). 에이피알 PER 32.2(KIS 48.3, −33% 괴리는 고성장 기인) / 동국 11.8 / 아로마티카 22.8(지배주주 계정 없음→전체 순이익). 포워드는 에이피알만(26E 30%+27E 70% → PER 21.8·P/OP 16.4). 토요일이라 휴장일 판정→발송 생략(정상)
- 한계·미해결: ①포워드가 KIS 커버 종목(현재 에이피알만)에 한정 — 컨센서스 소스(FnGuide 등) 미연결 ②에이피알 추정 EPS는 액면분할 전 기준(10배)이라 미사용 ③펌텍 26Q1 순이익≈영업이익 등 분기값 타당성은 재실행 후 DART 원문과 대조 필요 ④cron 09:00 KST는 GitHub 지연으로 5~15분 늦을 수 있음(메시지에 실제 시각 표기)

## 📡 주도주 신호 (8/27 신설 — leadsig.html + leadsig.py, 매일 21:35 UTC)
- 사용자 정의 규칙 구현: 주봉 MA 4·13·26·52주 — 🟢 정배열 시작 8주 내=신규 진입 / 🔵 유지(4-13 교차는 노이즈로 카운트만) / 🟡 13-26 데드크로스=힘 꺾임 경고 / 🔴 4-26 데드크로스=완전 이탈. 경고·이탈은 최근 12주 내 발생+현재 상태 유지분만, 과거 정배열 이력 없는 종목의 DC는 제외
- 이익성장률: screener.json opqSeries 조인 — QoQ 성장률이 직전 분기보다 크면 "가속🔥", 작으면 "둔화⚠"(주도주 힘 상실 위험)
- 대상: stockvals 시총 상위 1000(컷 ~1,600억). 주봉: KIS 기간별시세 FHKST03010100, FID_PERIOD_DIV_CODE=W, FID_ORG_ADJ_PRC=0(수정주가), **1콜 최대 100봉 → 2구간(699일+1440~700일) 병합 ≈ 200주**
- 첫 스캔: 신호 584건(신규 21·유지 111·경고 198·이탈 254, 실패 0). 검증: 삼전 정배열 55주(노이즈 6주)·하이닉스 66주 유지, 한화에어로 6/29 13-26 경고, HD현대일렉·효성중 4-26 이탈(단 이익은 가속 — 기술 이탈 vs 펀더 괜찮음 대비 노출)
- UI: 상태 KPI 필터+검색, 카드 클릭 → 주봉+4MA 차트(lazy) + 분기 OP·QoQ 표, 밴드/딥다이브 링크. 판정 로직은 합성 시계열 유닛테스트 6종으로 검증(신규/유지/노이즈/이탈/오래된 이탈 제외/무신호)
- 빈 결과 가드: 수집이 기존의 1/3 미만이면 유지

## ⚡ 전력 수요 파이프라인 (8/26 배포, 8/27 확장 완료 — power.html + power.py)
- 5층: ①CSP 캐펙스 ②대형부하 계통 신청 ③**EIA-860M 계획 발전소(매월 공식 원장)** ④유틸리티 파이프라인 ⑤장비 백로그
- EIA-860M 13개월: 가스터빈 36.1→69.7GW(1년 2배)·원전 5.0GW·총 291.1GW. PPI 5종(변압기 +81%/배전반 +78%/전선 +69%, 2021.1 대비)
- **8/27 한화 리포트 재현 — 전부 라이브 (15개 차트 + IR 표)**:
  - 🏗️ CAPEX(EDGAR XBRL 무키): 유틸리티 AEP·Duke·Southern·Dominion + 빅테크 MS·알파벳·아마존·메타, 분기 26개. 빅테크 26Q2 합산 $165B(1년 전 $88B). **태그: AEP=PaymentsForConstructionInProcess, Dominion=PaymentsForProceedsFromProductiveAssets, Duke·Southern·빅테크=PaymentsToAcquirePropertyPlantAndEquipment(아마존 ProductiveAssets). Exelon·NextEra·FirstEnergy 표준태그 없음→제외. 0값/스테일이면 companyfacts에서 construction 키워드 스캔. YTD 누적→같은 start끼리 차감(span 60~130일만 인정), 450일↑ 스테일 배제**
  - 🇺🇸 미국 수입·한국 비중(그림41~43): Census intltrade, 78개월. 초고압변압기 한국비중 10.1%(2020)→18.7%(26.6) / 배전반 3.1→12.9% / GIS 0.6→4.1%. CENSUS_KEY 가동 확인
  - 💱 수출단가 $/kg(그림31~33): 79개월, 전체+북미+유럽 분해. 초고압변압기 $21.6/kg(북미 23.4 > 유럽 17.8)
  - 🇺🇸 미국향 수출 합산: 최근 12개월 $4.33B(+8% YoY), 3품목 누적 막대
  - 📋 **IR 워치(irwatch.json)**: 계약 GW·CAPEX 계획·가이던스를 IR 발표에서 분기 수집, **모든 수치에 출처 링크 필수**(18건). AEP 계약 69GW·$780억 / Dominion 53.8GW·$650억 / Southern 17GW·$810억 / Duke $1,030억 / FirstEnergy 6.4GW / Exelon 11GW·$413억 / 알파벳 $195~205B·아마존 $220B·메타 $130~145B·MS FY27 증가
- 분기 자동갱신: **trig_01B43Kwm7H2vdD877hAiL1zr** (2·5·8·11월 16일 22:00 UTC, 다음 11/17). fine-grained PAT git clone 방식, 빈 결과 덮어쓰기·항목 감소 금지
- **관세청 GW API 노하우(8/27)**: ①월×국가×HS6 행 분해 → 월별 합산 필수 ②조회 1년 제한 → 연 분할 ③품목별 API가 statCd 국가 분해 제공(국가별 API 불필요) ④키는 인코딩형 — '%' 없으면 quote() 정규화(3개 수집기)
- 수집 노하우: EIA PK 매직바이트·BACKFILL=1·nohup. power.yml 매일 21:20 UTC. **동시 푸시 트리거 시 push 경합 유실 가능 — 결과 안 보이면 재트리거**

## 🌊 섹터 흐름·병목 맵 (8/26 심화) — 뉴스 매일+리포트 매칭+주간 AI 재작성 trig_01VnhbYFozwkEVgFVvvxFoxT(월 07시 KST)
- **8/30 주간 갱신 첫 실행 성공** (5섹터 병렬 리서치 → mk_sectorflow.py 수정 → 커밋 ebc6ca7 → 배포 200 확인). 주요 반영: 캐나다 잠수함 TKMS 확정(한화 탈락 7/7, 조선·방산 정정), 한화에어로 미 MTC 화포 단독 수주(8/19), 엔비디아 DC 매출 $89B(+117%)·메모리 병목 심화(26 서버 D램 ~+270% 전망), 세포라×올리브영 미 전매장(8/20), 조선 빅3 잔고 200조 돌파·트럼프 2척 행정명령(8/13), 미 155mm 월 3.6만발로 하향 정정
- **9/6 주간 갱신 2차 실행 성공** (커밋 0dd2a55 → 배포 200 확인). 주요 반영: ①메모리 급등→둔화 국면(8월 D램 고정가 +4.2% MoM)·HBM 수출단가 첫 $70 돌파·삼성 HBM 점유율 33%로 추격 ②브로드컴 AI $16.7B(+221%)·FY28 $230B 로드맵 ③방산 유럽 2국 신규(스페인 K9 8/31·크로아티아 천무 €4.35억 9/4) ④조선 잔량 216M CGT·8월 한국 점유율 7%(선별수주)·한화오션 이틀새 2조 ⑤K뷰티 8월 +52.1% 최대 vs 원화 강세(1,345원) 주가 조정 괴리 ⑥라면 관세 15→12.5% 정정(7/24 강제노동 301조)·삼양 자싱 11.3억→8.4억개 정정 ⑦현대위아 방산→로템 연내 4,000억 이관 구체화·폴란드 오르카 종결(사브 A26) 처리

## 🔄 반도체 P→Q 추적 — 국내판 🚦국면판정+수출 P/Q 8/27 가동(79개월), 글로벌판 고정가·현물가·번역. trends.py 8품목 수출도 가동
## 💰 내부자 매수 — 매수일 필터+빈결과 가드 / 💠 소부장 맵 / 🛡️ 방산 맵 / 🚢 조선(페이지 승인 대기) / 🔬 딥다이브(PV=4) / 🎵 틱톡

## DART·데이터 노하우
- 키리스 뷰어 / 과속 차단 / fnlttSinglAcnt 분기 차감(Q1~Q3 단일값, Q4=연간-누적) / 계약부채 불연속
- 샌드박스: api.github.com·네이버 차단, 번역 MyMemory (git clone/push는 가능 — 예약작업도 git 방식)
- EDGAR XBRL 무키: data.sec.gov/api/xbrl/companyconcept/CIK{10}/us-gaap/{tag}.json
- Census intltrade: I_COMMODITY={HS6}&time=from+2020-01 — 한국 CTY_CODE 5800, 전체 '-'
- KIS 주봉: FHKST03010100 W 수정주가, 100봉 제한 → 다구간 병합
- KIS 해외 현재가상세: HHDFS76200200 (optics.py) — 대만 미지원

## 미해결
- IR워치 첫 자동실행(11/17) / leadsig·power·pq 정기실행 관찰 / qdeep 신규 12종목 / 니어스랩 / 조선 페이지 / 소부장 이미지 2사
- optics.yml 첫 실행(9/11 07:30 KST) 관찰 — 일본·중국 시세 채워지는지 / 마인드맵 ⚠ 노드(확인 실패 항목) 후속 검증
- valalert: 사용자 TELEGRAM_BOT_TOKEN·TELEGRAM_CHAT_ID 시크릿 등록 → 첫 cron 실제 발송(9/14 월 09:00 KST) 확인 / 9/12 수정 후 재실행 결과(펌텍 순이익·실행시간) 확인
- 소부장 순위 패널 잔여 문구(9/12 배포 점검): rank.why/gap 안에 "○○는 원문 미확보"(케이엔제이·디아이티·티에프이·티에스이 4건, 순위 제외가 아닌 부연), "목표주가 근거(Target P/E 50x)"(ISC why)·"목표주가 미제시"(에이피티씨 gap), 워트 why의 고객명 '세메스' — 순위 자체는 정상(칩 47·기업 137·dropped 14, updated 2026-09-11). 다음 빌드 때 문구만 정리
- 강의 노트: 9/8 이후 강의(16강~) 올라오면 녹음·요약·슬라이드 추가

## 교훈 (누적)
- 배치 빈 결과 덮어쓰기 금지(전 수집기) · 로컬 시드 pv 주의 · DART 과속 차단 · 단위 교차검증 · 스크롤-하베스트 · performance API · 유튜브 429 폴백 · yml git add 개별 · 네이버 차단 · Render 빈 커밋 · 인라인 onclick 금지 · IR노트 실제 접촉만 · 기존 UI 제거 금지 · 무인작업 JSON 경유 · 렌더 검증 · 이미지 자체 호스팅 · PAT repo+workflow · fnlttSinglAcnt 분기 규칙 · 워크플로 커밋 if:always · 공공API 폐기 감시 · 예약작업엔 fine-grained PAT · 섹터흐름 품질 기준 유지 · 대용량 백필은 nohup 백그라운드 · 파일형 응답은 매직바이트 검증(PK) · XBRL 표준태그 0값 함정 · 관세청 GW 월별 합산+1년 제한+키 인코딩 정규화 · 워크플로 동시 트리거 push 경합 주의 · IR 수치는 출처 링크 필수 · 신호 로직은 합성 시계열 유닛테스트 · 대시보드 반영은 PC 세션(클라우드는 push 403) · 큰 파일은 copy로 배치(Write 재타이핑 금지) · PC 세션 셸 고장 시 .bat 스크립트를 탐색기 더블클릭으로 실행 · 콜노트 merge 전 callNo 중복 확인(rptNo 재발급) · 공개 저장소 문서엔 암호·키 값 금지
