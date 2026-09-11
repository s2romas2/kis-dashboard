# claude/ — 작업 문서 (프로젝트 지식 대체)

이 폴더는 Claude 세션이 읽는 작업 문서 모음이다. **프로젝트 지식(앱 업로드) 대신 여기가 원본** — 새 세션은 로컬 클론 `C:\Users\ladea\Downloads\kis-dashboard\claude\` 를 먼저 Read 한다.

## 규칙
- 저장소는 **공개**다. 암호·계정·API 키·PAT 값은 절대 쓰지 않는다(콜노트·강의노트 열람 암호는 프로젝트 지식의 원본 문서에만 둔다).
- 문서를 갱신하면 같은 커밋에 넣는다. 사용자에게 재업로드를 요청하지 않는다.
- 근거 원칙(소부장·광통신 등 리서치 공통): 증권사·한국IR협의회 리포트 원문 PDF + 전문매체(디일렉·전자신문·TrendForce·SEMI·Gartner·TechInsights·KSIA·KIPOST) + 공시(DART·KIND)만. 일반 뉴스·집계사이트·블로그 제외. 목표주가·투자의견 미기재. 비상장·원문 미확보는 순위 제외.

## 문서
- `kis-dashboard-현황.md` — 대시보드 전체 현황·노하우·미해결 (가장 먼저 읽을 것)
- `반도체-소부장-세부분야-대장주-2026-09.md` — 소부장 맵 세부분야 순위·차별성 (semidetail.json 원자료 설명 포함)
- `콜노트-갱신절차.md` / `강의노트-갱신절차.md` — 절차(암호 제거본). 암호는 프로젝트 지식 원본 참조
- `README-반영방법.md` — PC 세션 반영 방법(로컬 클론·bat 스크립트)

## 반영 방법(요약)
로컬 클론에서 직접 `git add/commit/push` (Git for Windows·credential manager 로그인 완료). 세션 셸이 고장(마운트 오류)이면 `C:\Users\ladea\Downloads\kis-apply\stepN.bat` 방식(PowerShell로 python·git 실행, 로그 파일 기록)으로 대체.
