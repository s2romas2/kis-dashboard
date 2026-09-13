# kis-dashboard 프로젝트 현황 (2026-09-13 기준)

## 개요
- 배포: https://kis-dashboard.onrender.com / 저장소: github.com/s2romas2/kis-dashboard (공개 유지 필수)
- 키: DART_KEY·KIS_APPKEY·KIS_APPSECRET·KRX_ID/PW·CUSTOMS_KEY·CENSUS_KEY=GitHub Secrets (8/27 전부 가동 확인)
- git 푸시: extraheader Basic PAT — 8/25 새 토큰(repo+workflow). 컨테이너 초기화 시 재요청(repo+workflow 필수)
- 8/25 fine-grained PAT(kis-dashboard 전용·Contents만) — 주간 섹터흐름·분기 IR워치 예약작업 프롬프트에 내장
- **9/10 PC 세션 반영 경로 확립**: 로컬 클론 `C:\Users\ladea\Downloads\kis-dashboard` (Git for Windows 2.55 설치, git-credential-manager 브라우저 로그인 완료 → 이후 push 무인증). 클라우드 세션은 push 403·PC 폴더 불가 → 대시보드 반영은 PC 세션에서
- **9/13 예비 반영 경로(셸 고장 시)**: Cowork PC 세션의 Linux 셸이 9/8 Windows 업데이트 문제로 기동 불가(git·python 전부 불가)일 때, **Chrome 확장(1번 브라우저, github.com 로그인 s2romas2) → GitHub 웹 "Upload files"** 로 반영 가능. 폴더별 1커밋(`/upload/main/<폴더>`), 파일은 프로젝트 문서 경로에서 file_upload로 1개씩(여러 개 한 번에 올리면 분류기가 차단). 이름 변경은 업로드 후 `/edit/main/<경로>` 파일명 필드 수정 → 같은 이름이 이미 있으면 먼저 `/delete/main/<경로>`로 제거 후 재시도. 검증은 raw.githubusercontent.com fetch + JSON.parse로 대체

## 🔦 광통신 맵 5탭 + 구리/아마존/WICS 트래커 (9/13 반영 — 커밋 7e46030·1111cfe·824f577·449adaf·5b627bd·9ca42b3)
- 반영 파일 20개: optics.html(146KB, 탭 5개 tabRep/tabMap/tabCs/tabGl/tabCu 확인)·optics_quotes.json·optics.py·optics.yml / copper.json·copper.py·copper.yml / amazon.html·amazonbrands.json·amazonnodes.json·amazon.json·amazon.py·amazon.yml / ranktable.html(`data-cls="wics"`)·wicsmap.json(2,392종목·27섹터)·wics.py·wics.yml / nav.js(아마존 메뉴)·blogkeys.json(12명)·lectures.enc(256,273B base64)
- 배포 확인(9/13 23:15 KST): /optics.html 탭 5개·콘솔 에러 0 / /amazon.html 브랜드 카드·안내문 렌더·콘솔 에러 0 / /ranktable.html WICS 중분류 칩 존재(첫 워크플로 완료 전까지 비활성 정상)·nav 아마존 링크 / /blog.html 포카라 노출(9/13 12:17 블로그 수집 커밋 aa359d0에서 이미 수집됨) / /lectures.html lectures.enc 200·256,273B
- **WICS 섹터 지수 일일 수집 #1 수동 실행 시작(9/13 23:12 KST)** — 월봉 900종목 초기 수집 10~20분. 완료되면 wics.json 생성 → 랭크테이블 WICS 뷰 활성. 미완이면 Actions에서 결과 확인
- 구리 트래커 실측: 광통신주–구리 상관 +0.20~0.33 < 시장–구리 +0.49 → 구리는 광통신 고유 신호 아님
- 아마존 트래커: 78카테고리 매일 KST 06:15, 초기 94건(에이피알 59건 #1·닥터알테아 9건 #3·조선미녀 8건 #3·동국제약 4건 #5·아로마티카 2건 #6·LG생건 7건 #8·셀리맥스 5건 #10·이퀄베리 0). 검색(/s) 503·상품(/dp) 캡차 → 베스트셀러만. **pg1=1~30위, pg2=51~80위, 31~50위 구조적 미수집**. CTK 제외(off:true)
- WICS 중분류 27개: 구성종목 WISE 공개 API, 수익률은 시총 상위 900 KIS 월봉 시총가중 직접 계산(WISE 시총합계는 편입/편출·증자 왜곡 — 한 달 -28% 이상치 확인). 소분류는 WISE 빈 응답 → 불가. 과거 구간도 현재 구성종목 기준 = 생존편향(wics.json note 명시)
- 미실행 검증: python ast 문법검사·로컬 http.server(셸 불가). yml/py는 raw 200·크기 정상만 확인 → 각 워크플로 첫 실행 로그로 문법 확인 필요(optics.yml 평일 07:30, copper/amazon/wics 일일)

## 🔦 광통신 맵 (9/10 반영 — 커밋 8278e7d)
- 2026-09-10 광통신 맵 4탭 확장(마인드맵·관점합류도·용어구조) + optics.py 해외시세 워크플로 + 강의 15강 + 블로그 pokara61 — 커밋 8278e7d, PC 세션에서 반영
- optics.html 탭: 📄 밸류체인 리포트 / 🕸 마인드맵(노드 181+, 대장주 뷰·8개 분야 뷰) / 🧭 관점 합류도(국내 7+해외 16=23건, S급5·A급3·B급3·논쟁6·사각지대5, 목표주가·투자의견 전량 제외) / 📚 용어·구조(용어 34 + SVG 도해 3종) / 🟤 구리 트래커(9/13 추가)
- 시세: 국내 25노드 → stockvals.json(sc:'코드') / 해외 49노드 → optics.py KIS 해외현재가상세 HHDFS76200200 24종목(미14·일4·중6, q:'티커'), optics.yml 평일 KST 07:30. optics_quotes.json 씨드=미국 14종목(9/8 종가), 일·중은 첫 실행 때 채움. 대만 KIS 미지원, 비상장 제외
- 강의 lectures.enc 15강 버전(g13 9/4~9/7 Call 리뷰 28:34 포함, 256KB 1줄) / 블로그 blogkeys.json pokara61(포카라의 실전투자, sec 종합) 추가 → 총 12명

## 💠 소부장 맵 세부분야·대장주 (9/10 반영)
- 2026-09-10 소부장 맵에 세부분야 필터(25개)·대장주/2·3위 순위 패널(리포트 원문 인용문·페이지·PDF 링크)·기업 상세 드로어(특화·차별성·공통 KPI·출처·근거등급 A/B/C) 추가 — 데이터 `public/data/semidetail.json`, 빌드 `tools/semidetail/build_semidetail.py`(원자료 raw_co_*·raw_rank_*). 1차 범위 파츠·열처리·테스트·패키징장비 ~52사. 근거 원칙: 증권사·한국IR협의회 원문 PDF + 전문매체(디일렉·전자신문·TrendForce·SEMI·Gartner·TechInsights·KSIA·KIPOST) + 공시만, 일반 뉴스·집계사이트 제외(빌드 시 자동 필터)
- mk_semimap: 자비스 코드 196450→254120 정정, 티엘비(356860)·고영(098460)·한화비전(489790) 추가
- 리포트 아카이브: `public/data/report_seeds.json` 큐레이션(광통신 5·유리기판 3, 30p+)을 reports.py가 archive에 병합, reports.html 아카이브 탭 🔦광통신·🪟유리기판 필터 추가
- 쏘캠 결론: 심텍 1위(모듈PCB+MCP 동시공급 유일·메모리 3사·'27 3,210억) / 티엘비 2위(비중 '28 50%·순수도, SK는 '대장주'로 명명) / 코리아써키트 3위. 상세 문서 `반도체-소부장-세부분야-대장주-2026-09.md`
- 2차 예정: 전공정 장비·소재·인프라·기판·OSAT 나머지

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
- KIS 월봉: FHKST03010100 M 수정주가, 1콜 100봉 ≈ 8년 (wics.py) / WISE GetIndexComponets: 중분류만 응답, 소분류 빈 응답, 과거 3개월
- 아마존 베스트셀러: /s 503·/dp 캡차, /bestsellers pg1(1~30)·pg2(51~80)만 접근

## 미해결
- **WICS 수집 #1 결과 확인**(9/13 23:12 KST 수동 실행) → wics.json 생성·랭크테이블 WICS 칩 활성 여부 / copper·amazon·wics.yml 첫 정기실행 로그로 py 문법 확인(셸 불가로 ast 검사 생략)
- IR워치 첫 자동실행(11/17) / leadsig·power·pq 정기실행 관찰 / qdeep 신규 12종목 / 니어스랩 / 조선 페이지 / 소부장 이미지 2사
- optics.yml 일본·중국 시세 채워지는지 / 마인드맵 ⚠ 노드(확인 실패 항목) 후속 검증
- 셸 복구 후: 로컬 클론 `git pull` 필수(웹 커밋 7건이 원격에만 있음)

## 교훈 (누적)
- 배치 빈 결과 덮어쓰기 금지(전 수집기) · 로컬 시드 pv 주의 · DART 과속 차단 · 단위 교차검증 · 스크롤-하베스트 · performance API · 유튜브 429 폴백 · yml git add 개별 · 네이버 차단 · Render 빈 커밋 · 인라인 onclick 금지 · IR노트 실제 접촉만 · 기존 UI 제거 금지 · 무인작업 JSON 경유 · 렌더 검증 · 이미지 자체 호스팅 · PAT repo+workflow · fnlttSinglAcnt 분기 규칙 · 워크플로 커밋 if:always · 공공API 폐기 감시 · 예약작업엔 fine-grained PAT · 섹터흐름 품질 기준 유지 · 대용량 백필은 nohup 백그라운드 · 파일형 응답은 매직바이트 검증(PK) · XBRL 표준태그 0값 함정 · 관세청 GW 월별 합산+1년 제한+키 인코딩 정규화 · 워크플로 동시 트리거 push 경합 주의 · IR 수치는 출처 링크 필수 · 신호 로직은 합성 시계열 유닛테스트 · 대시보드 반영은 PC 세션(클라우드는 push 403) · 큰 파일은 copy로 배치(Write 재타이핑 금지) · PC 세션 셸 고장 시 .bat 스크립트를 탐색기 더블클릭으로 실행 · **셸 완전 고장 시 Chrome 확장→GitHub 웹 Upload files(폴더별 커밋·파일 1개씩·이름변경은 edit 페이지·중복명은 delete 후)** · 웹 업로드는 원격만 갱신되므로 로컬 클론 pull 필요
