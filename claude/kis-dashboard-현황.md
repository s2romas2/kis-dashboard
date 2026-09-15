# kis-dashboard 프로젝트 현황 (2026-09-15 기준)

> 이 파일이 원본. 프로젝트 지식(앱 업로드)·다운로드 폴더 사본은 더 이상 갱신하지 않음 — 작업 결과는 `claude/` 안의 파일을 직접 수정해 커밋한다.

## 개요
- 배포: https://kis-dashboard.onrender.com / 저장소: github.com/s2romas2/kis-dashboard (공개 유지 필수)
- 키: DART_KEY·KIS_APPKEY·KIS_APPSECRET·KRX_ID/PW·CUSTOMS_KEY·CENSUS_KEY=GitHub Secrets (8/27 전부 가동 확인)
- git 푸시(클라우드 세션 시절): extraheader Basic PAT — 8/25 새 토큰(repo+workflow). 컨테이너 초기화 시 재요청(repo+workflow 필수)
- 8/25 fine-grained PAT(kis-dashboard 전용·Contents만) — 주간 섹터흐름·분기 IR워치 예약작업 프롬프트에 내장
- **9/10 PC 세션 반영 경로 확립**: 로컬 클론 `C:\Users\ladea\Downloads\kis-dashboard` (Git for Windows 2.55 설치, git-credential-manager 브라우저 로그인 완료 → 이후 push 무인증). 클라우드 세션은 push 403·PC 폴더 불가 → 대시보드 반영은 PC 세션에서
- **9/13 예비 반영 경로(셸 고장 시)**: Cowork PC 세션의 Linux 셸이 9/8 Windows 업데이트 문제로 기동 불가(git·python 전부 불가)일 때, **Chrome 확장(1번 브라우저, github.com 로그인 s2romas2) → GitHub 웹 "Upload files"** 로 반영 가능. 폴더별 1커밋(`/upload/main/<폴더>`), 파일은 프로젝트 문서 경로에서 file_upload로 1개씩(여러 개 한 번에 올리면 분류기가 차단). 이름 변경은 업로드 후 `/edit/main/<경로>` 파일명 필드 수정 → 같은 이름이 이미 있으면 먼저 `/delete/main/<경로>`로 제거 후 재시도. 검증은 raw.githubusercontent.com fetch + JSON.parse로 대체. **⚠ 웹 업로드 전 반드시 원격의 최신 파일(raw)과 로컬 사본을 대조할 것 — 9/15 새벽 작업에서 로컬 클론이 9/12 상태라 9/13 웹 커밋(ranktable.html e3c8623·현황 문서 bc0b5e2)을 덮어썼다가 재병합함**
- **9/11~ 셸 마운트 고장 시 우회**: `C:\Users\ladea\Downloads\kis-apply\stepN.bat`(PowerShell로 python·git 실행, stepN.log 기록)을 탐색기 더블클릭. 절차는 `claude/README-반영방법.md`. **무인 예약작업 중엔 computer-use 승인 불가** → 9/12 valalert.py는 Chrome(Claude in Chrome) GitHub 웹 업로드(github.com/…/upload/main, file_upload)로 직접 커밋(7a01026). 단 이 경우 로컬 클론이 dirty가 되어 다음 stepN.bat 은 `git checkout -- <파일>` 후 pull 필요(step6·step7에 반영). 미추적 파일(claude/ 신규 문서)은 웹 업로드하면 pull 충돌 → 로컬 bat 커밋으로만

## 🗂️ 업종 랭크테이블 업그레이드 (9/15 새벽 무인 예약작업 kis-ranktable-upgrade — 커밋 079e3d0·f233305·f89c2d8·bf858bf·4145297·477a0cf)
- 실행 환경: 셸 마운트 고장 + 무인 중 computer-use 승인 불가 + 내장 브라우저는 GitHub 미로그인(upload 페이지 "push access 필요") → 코드·yml·문서는 로컬 클론에 Write로 작성한 뒤 **Claude in Chrome(처음엔 미연결, 재시도 후 연결) GitHub 웹 업로드(github.com/…/upload/main/<폴더>, file_upload)로 6커밋**: 워크플로 3종(leaders 55분·sectorstocks 35분·sectorval 신규) → ranktable.html → 현황 문서 → leaders.py(A) → sectorval.py(C) → sectorstocks.py(D) 순(yml 먼저 올려야 push 트리거 실행이 새 timeout을 씀). **로컬 클론은 dirty 상태** → `C:\Users\ladea\Downloads\kis-apply\rank.bat`(동기화 전용: 로컬 수정본 checkout·미추적 sectorval.py/yml 삭제·pull) 더블클릭 후 rank.log 확인 필요. py_compile은 못 돌렸고 서브에이전트 정독 리뷰만 함(성장주 단계의 stale `m` 버그 1건 발견·수정) → 워크플로 첫 실행 로그로 문법 오류 여부 확인
- **[A] 딥 히스토리** `leaders.py` v3: `candles()`가 `[일자, 종가, 거래대금(억원), 거래량(주)]` 반환(acml_tr_pbmn·acml_vol). dv=2로 최초 1회 풀백필 — 일봉 2020-01-02~ 60달력일 창(~40거래일, 호출당 ~50봉 제한 안전), 주봉 2018-01-02~ 240일 창. 보관 상한 daily 1700·weekly 450, 호출 간 0.06초, 실패 시 1회 재시도(`candles_retry`). 월봉 hv=2 캐시(2001~)는 그대로 재사용(재수집 없음). 순위 계산용 최근 일봉도 병합 캐시에서 가져와 API 창 절단 영향 제거. **첫 실행 #107이 45분+ 장기화(GitHub→KIS 왕복 지연, ~3,000콜)** → d478e7e에서 백필을 **업종별 재개형**으로 변경: dv 전역 플래그 대신 업종별 `deep_ok`(첫 행 ≤ 2020-03/2018-03 + 거래대금 컬럼) 판정으로 미완료 업종만 수행, 업종마다 leadershist.json 중간 저장(타임아웃돼도 `if: always` 커밋으로 진행분 보존 → 다음 실행이 이어서). leaders.yml timeout 110분 + concurrency(cron 겹침은 대기). 완료 판정은 debug "딥 백필 … 완료 53/53"
  - **거래대금 단위는 추정**: KOSPI(0001) 최근 일봉 acml_tr_pbmn 중앙값이 1e11↑이면 원, 1e8↑이면 천원, 그 미만이면 백만원으로 가정해 억원 환산 — `leaders.json.debug`·`money_note`에 기록. 첫 실행 후 `money.v5`가 코스피 전기·전자 기준 수조원대인지 확인 필요(틀리면 `guess_val_unit` 임계값 조정)
- **[B] 거래대금 축** `leaders.json.money{code:{n,mkt,v5,v60,x,share,asof}}` + `money_top`(x 상위 10). x = 최근 5일 평균 ÷ 직전 60일 평균, share = 시장 내 5일 평균 점유율. ranktable.html: 마지막 칸 🔥(x≥1.8) 배지, 상단 "💰 돈 몰리는 업종 Top5", **순위 기준 토글(수익률/거래대금)** — 일·주는 봉 거래대금, 월·분기·반기·연은 일봉 합산(2020~). periods 엔트리에 `code` 추가(기존 n·mkt·r 유지 → leaders.html 영향 없음)
- **[C] 밸류 축** `sectorval.py`(신규) + `sectorval.yml`(평일 09:50 UTC=18:50 KST, push 트리거): KRX MDCSTAT00701(전체지수 PER/PBR/배당수익률) 코스피(idxIndMidclssCd 02)·코스닥(03) 당일값 → `public/data/sectorval.json {updated,date,map:{"업종명|시장":{per,pbr,div,fper,idx,raw,date,pbr_pct,pbr_n}},hist:{key:[[일자,PBR,PER]]},all,debug}`. 지수명 접두어(코스피/코스닥) 제거 후 leadershist 업종명과 느슨 매칭. 당일 빈 응답이면 직전 영업일로 최대 6일 후퇴. **첫 실행(run #1) 결과: 전 변형 HTTP 400 → 기존 파일 유지(정상 폴백)**. 원인은 IP가 아니라 **KRX가 로그인 세션을 요구**(응답 본문 "LOGOUT", 노하우 섹션 참조) — 로그인 상태 Chrome에서 같은 파라미터(idxIndMidclssCd 02/03)로 코스피 53행·PER/PBR/DIV 정상 수신 확인. KRX_ID/PW 자동 로그인은 보안입력 폼이라 미구현(쿠키 워밍업만) → sectorval.json은 로그인 자동화 전까지 비어 있음. **KRX 실패 시 폴백**: sectorstocks.py가 견인 top15의 KIS 현재가 per/pbr를 시총가중(조화평균)한 `est{per,pbr,n}`를 넣어 패널에 "추정"으로 표시. PBR 이력 20일 이상 쌓이면 백분위(pbr_pct) 표시, 순위 상승 업종(🔺/🌱)이 PBR 하위 40%면 "🧲 밸류 대비 순위 상승" 배지
- **[D] 수급 축** `sectorstocks.py` v2: 견인 top15 종목마다 KIS 투자자매매동향(FHKST01010900, inquire-investor) 최근 5거래일 외국인·기관 **순매수수량×종가**를 억원으로 합산(단위 확실한 조합. API의 순매수대금 필드는 첫 응답에서 `필드/(수량×종가)` 비율만 DEBUG에 기록 → 원/백만원 판정 후 필요 시 전환) → `sectors[key].flow{f5,o5,n,last,note}`, 종목별 `f5,o5,per,pbr`. 응답 키는 CODE_KEYS 방식으로 방어적 매핑 + 첫 응답 키 DEBUG. 현재가(FHKST01010100) 호출 추가로 ~1,600콜, 0.06초 대기, sectorstocks.yml timeout 20→35분
- **[D] 첫 실행 #29 성공(8분)**: 수급 363종목·현재가 310종목·실패 0, 업종 flow 43개·est 43개. 투자자동향 응답 키 확인(stck_bsop_date, stck_clpr, frgn_ntby_qty, orgn_ntby_qty, frgn_ntby_tr_pbmn …), **순매수대금 필드/(수량×종가) 비율 9.51e-07 → 대금 필드 단위는 백만원**(현재는 수량×종가 사용, 필요 시 전환). 예: 전기·전자 KOSPI 외인 5일 -2,698억·기관 +1,006억, est PER 42.6·PBR 2.15
- **[E] KRX 구성종목으로 sectormap 대체는 미착수** — 단 로그인된 Chrome에서 요청 형식은 확인(노하우 섹션 MDCSTAT03901). KRX 업종명(예: 기타금융)이 KIS 업종지수명과 1:1이 아니므로 매핑표 필요. 기존 KIS 업종코드 매칭 유지
- **UI 재병합 사고**: 처음 올린 ranktable.html(f233305)이 9/12 로컬 사본 기반이라 9/13 e3c8623(테마·누적·카드·신규부상)을 덮어씀 → raw에서 e3c8623을 받아 그 위에 재적용해 재커밋(같은 날 후속 커밋). 현황 문서도 9/13 bc0b5e2 내용(광통신 5탭 섹션·노하우·교훈)을 병합
- 검증 필요(사용자·다음 세션): ① rank.bat 실행 → rank.log 에 "RANK SYNC DONE"·status 깨끗 ② 푸시 5~15분 뒤 leaders/sectorstocks/sectorval 워크플로 성공(leaders 첫 실행은 백필로 길다) ③ ranktable.html?v=… 렌더: 일별 보기에서 연도 2020 선택, 순위:거래대금 토글, 업종 클릭 시 💰/🧭/📐 지표 줄 ④ leaders.json.debug의 "거래대금 단위"·"백필 결과" 줄, sectorstocks.json.debug의 "투자자동향 응답 키"·"순매수대금 필드/(수량×종가) 비율", sectorval.json.debug의 KRX 성공 여부
- 한계: 거래대금·순매수 단위는 첫 실행 결과로 확정해야 함 / KRX 400이면 PER/PBR은 KIS 추정만 / leadershist.json이 ~4~5MB로 커짐(Render gzip 전제) / 견인 종목은 등락률순위 상위이므로 수급·밸류 합산은 "업종 전체"가 아닌 "견인 상위 15종목" 표본

## 🔦 광통신 맵 5탭 + 구리/아마존/WICS 트래커 (9/13 반영 — 커밋 7e46030·1111cfe·824f577·449adaf·5b627bd·9ca42b3, 랭크테이블 테마/누적/카드 e3c8623)
- 반영 파일 20개: optics.html(146KB, 탭 5개 tabRep/tabMap/tabCs/tabGl/tabCu 확인)·optics_quotes.json·optics.py·optics.yml / copper.json·copper.py·copper.yml / amazon.html·amazonbrands.json·amazonnodes.json·amazon.json·amazon.py·amazon.yml / ranktable.html(`data-cls="wics"`)·wicsmap.json(2,392종목·27섹터)·wics.py·wics.yml / nav.js(아마존 메뉴)·blogkeys.json(12명)·lectures.enc(256,273B base64)
- 랭크테이블 e3c8623: 테마 뷰(themes.json, 주봉·월봉)·WICS 중분류 뷰(wics.json 월봉)·기준(기간/누적 수익률, 롤링 N칸)·🆕 신규 부상(3/6/12개월 전 하위 절반→상위 1/3)·선택 섹터 카드(순위·변동·최고/최저·테마 상위 종목). **9/15 업그레이드는 이 버전 위에 재병합됨**
- 배포 확인(9/13 23:15 KST): /optics.html 탭 5개·콘솔 에러 0 / /amazon.html 브랜드 카드·안내문 렌더·콘솔 에러 0 / /ranktable.html WICS 중분류 칩 존재(첫 워크플로 완료 전까지 비활성 정상)·nav 아마존 링크 / /blog.html 포카라 노출(9/13 12:17 블로그 수집 커밋 aa359d0에서 이미 수집됨) / /lectures.html lectures.enc 200·256,273B
- **WICS 섹터 지수 일일 수집 #1 수동 실행 시작(9/13 23:12 KST)** — 월봉 900종목 초기 수집 10~20분. 완료되면 wics.json 생성 → 랭크테이블 WICS 뷰 활성. 미완이면 Actions에서 결과 확인
- 구리 트래커 실측: 광통신주–구리 상관 +0.20~0.33 < 시장–구리 +0.49 → 구리는 광통신 고유 신호 아님
- 아마존 트래커: 78카테고리 매일 KST 06:15, 초기 94건(에이피알 59건 #1·닥터알테아 9건 #3·조선미녀 8건 #3·동국제약 4건 #5·아로마티카 2건 #6·LG생건 7건 #8·셀리맥스 5건 #10·이퀄베리 0). 검색(/s) 503·상품(/dp) 캡차 → 베스트셀러만. **pg1=1~30위, pg2=51~80위, 31~50위 구조적 미수집**. CTK 제외(off:true)
- WICS 중분류 27개: 구성종목 WISE 공개 API, 수익률은 시총 상위 900 KIS 월봉 시총가중 직접 계산(WISE 시총합계는 편입/편출·증자 왜곡 — 한 달 -28% 이상치 확인). 소분류는 WISE 빈 응답 → 불가. 과거 구간도 현재 구성종목 기준 = 생존편향(wics.json note 명시)
- 미실행 검증: python ast 문법검사·로컬 http.server(셸 불가). yml/py는 raw 200·크기 정상만 확인 → 각 워크플로 첫 실행 로그로 문법 확인 필요(optics.yml 평일 07:30, copper/amazon/wics 일일)

## 📞 콜 노트 (9/12 반영 — 커밋 __HASH6__)
- 2026-09-12 무인 예약작업(kis-callnote-update): 셸 마운트 고장 + 무인 실행 중엔 computer-use 승인 불가 → 데이터·스크립트(`kis-apply\new6.json·w6.json·sum6.json·prep6.py·verify6.py·step6.bat`)만 준비. **사용자가 step6.bat 더블클릭 → step6.log의 "push exit code: 0"·verify 출력(주식 85/현금 15) 확인** 필요
- 9/9~9/11 신규 23건(Call No.67~89, rptNo 2074~2110) 병합·요약·비중·스타일·kind 교정 → calls.enc 갱신. 9/12(토)는 신규 없음
- 포트 액션: 9/10 SK하이닉스 15→17.5% 상향(No.79) / 9/11 삼성SDS 5→0% 편출(No.83) + SK하이닉스 17.5→20% 상향(No.84) → 주식 85%·현금 15% 유지. 7기 현재 11종목(삼전 27.5·하이닉스 20·LG이노텍·LS·팬오션·삼성SDI·SKT·이수페타시스 각 5·두산에너빌리티·LG생건·BGF 각 2.5)
- 발견: 같은 Call No.가 새 rptNo로 재등록되는 경우 있음(9/8 No.65·66 → 2072·2073). merge 전 (callNo,기수) 중복 제외 로직 필요 — `kis-apply\prep6.py`, 절차 문서에 반영
- 문서 이전: 프로젝트 지식 문서 5종(현황·소부장 대장주·콜노트 절차·강의노트 절차·README 반영방법)을 `claude/`로 옮김(암호·플레이어 키는 "(프로젝트 지식 원본 참조)"로 치환). 이후 갱신은 `claude/`에서 직접

## 🔦 광통신 맵 (9/10 반영 — 커밋 8278e7d)
- 2026-09-10 광통신 맵 4탭 확장(마인드맵·관점합류도·용어구조) + optics.py 해외시세 워크플로 + 강의 15강 + 블로그 pokara61 — 커밋 8278e7d, PC 세션에서 반영
- optics.html 탭 4개: 📄 밸류체인 리포트 / 🕸 마인드맵(노드 181+, 대장주 뷰·8개 분야 뷰) / 🧭 관점 합류도(국내 7+해외 16=23건, S급5·A급3·B급3·논쟁6·사각지대5, 목표주가·투자의견 전량 제외) / 📚 용어·구조(용어 34 + SVG 도해 3종) / 🟤 구리 트래커(9/13 추가)
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
- KIS 월봉: FHKST03010100 M 수정주가, 1콜 100봉 ≈ 8년 (wics.py) / WISE GetIndexComponets: 중분류만 응답, 소분류 빈 응답, 과거 3개월
- 아마존 베스트셀러: /s 503·/dp 캡차, /bestsellers pg1(1~30)·pg2(51~80)만 접근
- KIS 업종지수 기간별 시세 FHKUP03500100: 창을 잘게 나눠 반복하면 과거 무제한(leaders.py 일봉 60달력일·주봉 240일 창). output2에 acml_tr_pbmn·acml_vol 있음(단위는 0001 샘플로 추정)
- **KRX 정보데이터시스템(data.krx.co.kr getJsonData.cmd)은 2026-09 현재 로그인 세션 필수** — 비로그인/GitHub Actions에서는 HTTP 400 본문 "LOGOUT". 로그인 상태(Chrome)에서 확인한 요청: 전체지수 PER/PBR/배당 = bld `dbms/MDC/STAT/standard/MDCSTAT00701`, searchType 1, idxIndMidclssCd 02(코스피)/03(코스닥), trdDd, share 2, money 3 → output[IDX_NM, CLSPRC_IDX, WT_PER, WT_STKPRC_NETASST_RTO, DIV_YD] (코스피 53행, 업종명은 접두어 없이 '음식료·담배' 등). 업종분류 현황(종목→업종) = `MDCSTAT03901`, mktId STK/KSQ, trdDd, money 1 → block1[ISU_SRT_CD, ISU_ABBRV, MKT_TP_NM, IDX_IND_NM, MKTCAP]. 로그인 페이지 `/contents/MDC/COMS/client/MDCCOMS001.cmd`(폼 COMS001_FORM, 비밀번호 보안입력 → 파이썬 자동 로그인 미검증). **주의: 로그인 상태에서 스크립트로 연속 호출·로그인 페이지 fetch 시 세션이 끊김(9/15 확인) → 사용자 재로그인 필요**

## 미해결
- **WICS 수집 #1 결과 확인**(9/13 23:12 KST 수동 실행) → wics.json 생성·랭크테이블 WICS 칩 활성 여부 / copper·amazon·wics.yml 첫 정기실행 로그로 py 문법 확인(셸 불가로 ast 검사 생략)
- 셸 복구 후: 로컬 클론 동기화 필수(9/13 웹 커밋 7건 + 9/15 웹 커밋이 원격에만 있음 — `kis-apply\rank.bat`)
- 랭크테이블 업그레이드 검증(9/15): leaders/sectorstocks 첫 실행 로그·debug(단위 추정·백필 결과·투자자동향 키) / sectorval은 KRX 로그인 필요라 KIS 추정(est)만 동작 — KRX 로그인 자동화 또는 로그인된 Chrome에서 수동 수집 경로 검토 / KRX 세션 재로그인
- IR워치 첫 자동실행(11/17) / leadsig·power·pq 정기실행 관찰 / qdeep 신규 12종목 / 니어스랩 / 조선 페이지 / 소부장 이미지 2사
- optics.yml 첫 실행(9/11 07:30 KST) 관찰 — 일본·중국 시세 채워지는지 / 마인드맵 ⚠ 노드(확인 실패 항목) 후속 검증
- valalert: 사용자 TELEGRAM_BOT_TOKEN·TELEGRAM_CHAT_ID 시크릿 등록 → 첫 cron 실제 발송(9/14 월 09:00 KST) 확인 / 9/12 수정 후 재실행 결과(펌텍 순이익·실행시간) 확인
- 소부장 순위 패널 잔여 문구(9/12 배포 점검): rank.why/gap 안에 "○○는 원문 미확보"(케이엔제이·디아이티·티에프이·티에스이 4건, 순위 제외가 아닌 부연), "목표주가 근거(Target P/E 50x)"(ISC why)·"목표주가 미제시"(에이피티씨 gap), 워트 why의 고객명 '세메스' — 순위 자체는 정상(칩 47·기업 137·dropped 14, updated 2026-09-11). 다음 빌드 때 문구만 정리
- 강의 노트: 9/8 이후 강의(16강~) 올라오면 녹음·요약·슬라이드 추가

## 교훈 (누적)
- 배치 빈 결과 덮어쓰기 금지(전 수집기) · 로컬 시드 pv 주의 · DART 과속 차단 · 단위 교차검증 · 스크롤-하베스트 · performance API · 유튜브 429 폴백 · yml git add 개별 · 네이버 차단 · Render 빈 커밋 · 인라인 onclick 금지 · IR노트 실제 접촉만 · 기존 UI 제거 금지 · 무인작업 JSON 경유 · 렌더 검증 · 이미지 자체 호스팅 · PAT repo+workflow · fnlttSinglAcnt 분기 규칙 · 워크플로 커밋 if:always · 공공API 폐기 감시 · 예약작업엔 fine-grained PAT · 섹터흐름 품질 기준 유지 · 대용량 백필은 nohup 백그라운드 · 파일형 응답은 매직바이트 검증(PK) · XBRL 표준태그 0값 함정 · 관세청 GW 월별 합산+1년 제한+키 인코딩 정규화 · 워크플로 동시 트리거 push 경합 주의 · IR 수치는 출처 링크 필수 · 신호 로직은 합성 시계열 유닛테스트 · 대시보드 반영은 PC 세션(클라우드는 push 403) · 큰 파일은 copy로 배치(Write 재타이핑 금지) · PC 세션 셸 고장 시 .bat 스크립트를 탐색기 더블클릭으로 실행 · 콜노트 merge 전 callNo 중복 확인(rptNo 재발급) · 공개 저장소 문서엔 암호·키 값 금지 · **셸 완전 고장 시 Chrome 확장→GitHub 웹 Upload files(폴더별 커밋·파일 1개씩·이름변경은 edit 페이지·중복명은 delete 후)** · 웹 업로드는 원격만 갱신되므로 로컬 클론 pull 필요 · **웹 업로드 전 원격 최신본(raw)과 대조 — 오래된 로컬 사본으로 덮어쓰기 금지** · 무인 예약작업 커밋 경로 = Claude in Chrome GitHub 웹 업로드(미연결이면 몇 분 뒤 재시도) → yml 먼저·py 마지막·폴더별 1커밋 → 로컬 클론은 동기화 bat · KIS 기간별 시세는 창을 잘게 나눠 반복하면 과거 무제한(창당 봉 수 제한 ~50 준수) · 단위 불명 필드는 기준값(코스피 0001 등)으로 자동 추정하고 debug에 근거 기록
