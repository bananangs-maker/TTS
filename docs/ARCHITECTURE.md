# RESEARCH OS — 구현 구조와 판단 근거

## 최종 구조

공개 RSS/Atom/FRED CSV → GitHub Actions 표준 Python 수집기 → Turso libSQL DB ← Render FastAPI 웹앱.

- 웹서버는 수집을 실행하지 않는다. 새로고침은 조회만 한다.
- 수집기는 DB에 직접 쓰므로 Render의 절전·재시작과 독립적이다.
- 프런트엔드는 외부 CDN이나 JS 프레임워크가 필요 없는 HTML/CSS/JS. SQL·키·비밀번호 해시는 서버에만 있다.
- Turso HTTP 프로토콜은 표준 `requests`로 구현. 로컬 SQLite는 개발/테스트만 사용한다.
- Render에서 Turso URL이 없으면 애플리케이션 시작을 거부한다. 임시 파일 DB에 성공한 것처럼 저장하지 않는다.
- 스키마는 `research_os/schema.sql`, 정보원은 `research_os/catalog.py`, 가중치는 `config/rules.json`.

## 무료 플랜 검토 (공식 자료, 2026-11-11)

|항목|Turso Free|Neon Free|
|---|---|---|
|저장|5GB|프로젝트당 1GB, 계정 합산 20GB|
|주요 사용량|월 5억 rows read / 1천만 rows written|프로젝트당 월 100 CU-hours|
|전송/동기화|월 sync 3GB 표기 (이 구현은 remote HTTP)|프로젝트당 public network 5GB|
|DB/프로젝트 수|100 DB|100 projects|
|휴면/복구|PITR 1일 표기|5분 유휴 compute scale-to-zero, restore 6시간|

근거:
1. Turso 요금: https://turso.tech/pricing
2. Neon 공식 무료 한도: https://github.com/neondatabase/website/blob/main/content/faqs/free-plan-limits-and-quotas.md
3. Render 무료 제약: https://render.com/docs/free

Neon은 PostgreSQL 전문검색/복잡한 분석에 장점이 있지만, 이번 규모에서는 SQLite와 동일한 SQL,
단순한 원격 HTTP, compute 시간 없이 rows 기준 한도를 관리할 수 있는 Turso를 우선 선택했다.
현재 DB 실접속은 계정/토큰이 없어 미검증이다. 수치는 조회 당시 기준이며 향후 변경될 수 있다.

## Python SDK 지원 검토

공식 Python quickstart는 엔진에 따라 구분한다.
- `pyturso`: 로컬/임베디드, `turso.sync`로 동기화.
- `turso_serverless`: 원격 Turso 엔진용, 표준 라이브러리 HTTP.
- `libsql`: 원격 libSQL 및 embedded replica.

문서: https://docs.turso.tech/sdk/python/quickstart
공식 SQL-over-HTTP: https://docs.turso.tech/sdk/http/quickstart

Render의 파일 비영속성을 고려해 로컬 복제/동기화 경로는 사용하지 않는다.
현재 구현/배포 지침은 **Turso의 libSQL 엔진 데이터베이스**와 `/v2/pipeline`을 대상으로 한다.
`DB.execute`는 공식 typed bound parameter와 execute/close 응답 구조를 구현한다.
엔진을 혼용하지 않는다. 새로운 Turso 엔진으로 전환 시 FTS5·SQL 지원과 HTTP 호환성을 별도 검증해야 한다.

## Render 비용·운영

공식 문서상 free web service는 15분 무트래픽 후 절전, 기동 약 1분, workspace 월 750 free instance hours.
로컬 파일은 재배포·재시작·절전 후 소실될 수 있다. Free Postgres도 30일 만료이므로 장기 저장소로 선택하지 않았다.
외부 DB 호출량·egress/build 사용량 제한이 있으며 무료한도를 무조건 무제한 운영으로 해석하지 않는다.
웹앱은 하루 수차례 사람 조회, 수집은 Actions에서 실행하여 Render 발신 트래픽을 줄인다.

## 수집 동작

- publisher가 안내한 고정 URL만 허용. 임의 URL 입력 기능 없음.
- robots 확인 실패/금지면 미수집. RFC9309 longest Allow/Disallow, Crawl-delay 반영.
- redirect는 자동 추적하지 않고 검토가 필요한 오류로 기록.
- timeout 10초 연결/25초 읽기, 응답 3MB, RSS/Atom 페이지당 최대 250항목, pagination 최대 3페이지.
- 429/502/503/504는 제한 재시도, 최대 3회. 403 우회 없음.
- ETag/Last-Modified와 304 활용, 소스별 최소 주기 준수.
- 소스별 오류 catch → 다음 소스 진행. 모든 실행이 실패하면 CLI exit 1.
- DB 25분 임대 lock + Actions concurrency로 중복 실행 방지.
- 뉴스는 제목/링크/발행일 등 메타데이터만, 보고서는 공식 제공 요약 280자까지. 전문/PDF 파일 미저장.

## 중복과 검색

URL 정규화: fragment/tracking query 제거, 의미 있는 query 보존.
정규화 제목 exact match, 최근 자료 10,000건의 앞 8글자 bucket에서 SequenceMatcher >=0.94 탐지.
숫자가 다른 제목, 48시간을 넘는 서로 다른 시점의 유사 기사, 과도한 길이 차이는 합치지 않는다.
유사도는 보수적 wire 중복 탐지이며 의미적 동일성 판정이 아니다.

FTS5 unicode61 + prefix 검색을 사용하고 한국어 부분 문자열·개인 메모는 LIKE를 보완한다.
영어/한국어 형태소 분석기나 의미 검색은 구현하지 않았다. 임의 검색 문자열은 SQL bound parameter다.
기사 다중 주제는 JSON 태그로 저장하며 필터는 primary category와 주제 태그 모두 적용한다.

## 중요도 점수

모든 점수는 **수집 시점의 규칙 기반 정렬 보조값**이며 진실성·투자수익·예측 확률이 아니다.

|요소|최대 점수|정규화 규칙|
|---|---:|---|
|관련성|30|매칭 주제 수 / 2, 최대 1|
|키워드|15|매칭 단어 수 / 4, 최대 1|
|정책·투자 이벤트|20|event_words 일치 여부|
|정보원|10|공식 연구자료 1, 뉴스 0.6|
|최신성|15|exp(-발행 경과일/3), 날짜 미제공 0|
|신규성|10|중복 제거 후 처음 저장한 URL 1|

상세 기여값과 rule_version을 각 기사에 저장해 재현할 수 있다. 신규성은 새로운 산업 이슈라는 뜻이 아니다.
시간이 지나도 기존 점수를 매 조회마다 재계산하지 않는다. 자동 재점수·버전별 비교는 후속 과제.

## 신호와 지표

기사 신호는 완료된 UTC 7일과 직전 28일을 비교한다.
첫 성공 수집이 35일 이전이고 두 기간에서 각각 70% 이상 날짜에 성공/304가 있는 고정 뉴스 소스만 사용한다.
초기 RSS 과거 기사 적재나 새 정보원 추가를 급증으로 해석하지 않는다.
비교 이력이 없으면 현재 저장분 최근 7일 건수만 설명적으로 표시하며 판정은 `insufficient_history`.

기준 주간평균 = 이전 28일 건수 / 4.
Z = (최근7일 - 기준주간평균)/(과거 28일의 일별 표준편차 × sqrt(7)).
기본 급증 조건: 최근7일 >=5, 증가율 >=100%, Z>=2. 기준 0이면 별도 신규 키워드 후보.
이 통계는 iid count 분산 근사를 사용하며 계절성/매체 편집 정책/기사삭제까지 보정한 인과 추론은 아니다.

지표는 실제 관측일을 유지하고 결측 `.`를 버린다. 변경된 값은 upsert한다.
전일은 daily 지표의 직전 유효 관측, 전주는 7일 전 이하, 전월은 달력상 1개월 전 이하 가장 가까운 관측.
월간/분기 자료에 가짜 일별 변화는 계산하지 않는다.
최근 30관측 평균/고저 및 차분의 모집단 표준편차를 제공한다.
금리와 GDP 성장률 차이는 %p. FX/유가 임계값은 변화율, 국채 임계값은 %p.

정형 전망 비교용 `forecast_releases` 테이블은 준비했으나 검증된 전망 자동 입력기는 미구현이다.
PDF 숫자 추출이나 전망 생성은 수행하지 않는다.
