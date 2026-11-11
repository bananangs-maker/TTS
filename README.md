# RESEARCH OS

외부 공개자료를 자동 수집하고 규칙·통계로 변화를 관측하는 개인 경제·산업 리서치 웹앱.
**Render + Turso(libSQL) + GitHub Actions + Python. Supabase / LLM / 생성형 AI API 미사용.**

## 현재 구현과 실제 검증

- 한국경제·전자신문 5개 RSS를 포함한 국내외 소스 12개, 한국은행 보고서 3종.
- RSS/Atom, HTML 정리, 발행일/수집일 분리, URL/제목/보수적 유사도 중복 탐지, 오류·재시도·304.
- FTS5 검색, 한국어/영어, 주제·출처·발행기간·안읽음·프로젝트 필터.
- 재현 가능한 수집 시점 0~100 점수, 다중 주제, 근거/규칙 버전.
- 35일 고정 정보원·수집 커버리지로 통제한 키워드 신호, 경제지표 변화·변동성·임계치.
- 여섯 화면, 수집 상태 화면, 개인 로그인·CSRF·메모·태그·북마크·JSON 내보내기.
- 표준 Python 독립 수집기, Render Blueprint, GitHub Actions workflow.
- 로컬 SQLite 실제 수집/테스트 완료. **GitHub 계정·Render 연결·Turso 토큰이 없으므로 외부 배포/원격 DB/예약 첫 실행은 미검증**.
- 최종 실제 수집 건수와 검사 결과는 `docs/validation.json`, 기관별 점검은 `docs/source-audit.json`.
- 데이터파일은 소스 배포에 포함하지 않는다. 실행 후 실제 수집기로 DB를 채운다. 가상 seed나 데모 기사 없음.

## 빠른 로컬 실행

Python 3.12 권장. 다음 명령은 저장소 루트에서 실행한다.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m scripts.hash_password
```

출력된 해시를 `ADMIN_PASSWORD_HASH` 환경변수에 설정한다. 평문 비밀번호는 getpass로만 입력한다.
비밀번호는 빈 값만 허용하지 않으며 길이 제한은 없다. 기본 아이디는 `researcher`, 변경하려면 `ADMIN_USERNAME` 설정.

```bash
export ADMIN_PASSWORD_HASH='출력된 pbkdf2 해시'
python -m research_os.collector --mode all
uvicorn research_os.app:app --host 127.0.0.1 --port 8000
```

브라우저: http://127.0.0.1:8000 . `.env.example`은 설정 이름의 예시이며 자동 로드하지 않는다.
`.env`를 사용할 경우 호스팅/쉘의 환경변수 설정 방식을 통해 주입한다. 비밀값을 커밋하지 않는다.

## Turso 생성과 연결

1. Turso 계정에서 **libSQL 엔진 DB**를 생성한다. 이 구현은 해당 엔진의 FTS5와 공식 `/v2/pipeline`을 대상으로 한다.
2. 공식 CLI로 URL과 DB 전용 토큰을 확인/발급한다.

```bash
turso db create research-os
turso db show research-os --url
turso db tokens create research-os
```

3. 서버 환경변수 `TURSO_DATABASE_URL`과 `TURSO_AUTH_TOKEN`을 설정한다. URL은 `libsql://...turso.io` 또는 공식 HTTPS 주소.
4. Python collector를 실행하면 스키마·카탈로그를 생성하고 실제 자료를 수집한다. 원격 토큰은 서버 및 Actions Secrets에만 있다.

실계정 생성·인증·원격 실접속은 아직 사용자 연결이 필요하다. 존재하지 않는 DB를 생성했다고 보고하지 않는다.
공식 Python SDK/HTTP 및 무료 대안 비교는 `docs/ARCHITECTURE.md`를 참고.

## GitHub + Render 배포

1. 전체 코드를 **새 GitHub 저장소**에 push한다. `data/`, `.env`, `.venv`, backups는 제외되어 있다.
2. GitHub repository → Settings → Secrets and variables → Actions에 다음을 등록한다.
   - `TURSO_DATABASE_URL`
   - `TURSO_AUTH_TOKEN`
3. Render → New → Blueprint → 해당 저장소 선택. `render.yaml`을 사용한다. plan은 free로 명시되어 있다.
4. Render 환경변수를 설정한다.
   - `TURSO_DATABASE_URL`, `TURSO_AUTH_TOKEN` (같은 DB)
   - `ADMIN_USERNAME` (기본 researcher)
   - `ADMIN_PASSWORD_HASH` (위 도구로 생성)
   - `APP_BASE_URL` (발급된 https://...onrender.com origin, 마지막 / 제외)
5. 배포 로그의 기동 성공과 `/healthz`의 `storage: turso`를 확인한다.
6. GitHub Actions의 Collect public research → Run workflow → all로 첫 수집을 실행한다.
7. Actions 로그의 실제 성공과 앱 정보원·지표 갱신일을 대조한다.

스케줄은 UTC 01:17·07:17·13:17·19:17 = **한국시간 10:17·16:17·22:17·04:17**.
GitHub schedule은 기본 브랜치에 workflow가 있어야 실행되고 지연될 수 있다.
공개 저장소에서 장기 활동이 없으면 예약 작업이 비활성화될 수 있으므로 확인할 것.
공식 문서: https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule
GitHub의 민간 저장소 Actions 사용량은 계정 요금/분 한도를 확인할 것. 주기적 인위적 ping으로 Render 절전을 우회하지 않는다.

## 사용

- Overview: 한국어 중요도순 기사, 오늘 수집 수, 최신 연구자료, 분야별 기사량, 실제 지표, 북마크.
- Newsroom: 기본 한국어, 영어 전환 가능. 최신/수집 시점 중요도 정렬, 다중 주제 필터.
- Research library: 제목 클릭 → PDF enclosure가 있으면 링크, 메모/태그/프로젝트, 연관 시리즈 추정.
- Economic monitor: 관측일·수집일·단위·원천, 실제 시계열, 최근 값 표, 통계.
- Signal monitor: 이력 부족/기준 이내/급증 조건, 공식 계산 근거, 설정 임계치, 정책·투자 태그 기사.
- Personal archive: 북마크한 자료/메모/프로젝트 검색, JSON 백업.
- 상단 수집 상태: 소스별 enabled/최소 주기, 실제 성공률·오류·미연결 기관.

점수는 뉴스 진실성이나 예측 정확도가 아니다. 초기 신호 이력 부족은 정상 상태이며 가짜 비교기준을 만들지 않는다.

## 운영 명령

```bash
python -m research_os.collector --mode feeds
python -m research_os.collector --mode indicators
python -m research_os.collector --mode feeds --sources kr-hk-economy --force
python -m research_os.audit
python -m research_os.backup export backups/full.json
python -m research_os.backup restore backups/full.json
python -m pytest -q
node --check research_os/static/app.js
```

`--force`는 수동 점검용이며 routine 작업은 source 주기를 따른다.
백업에는 개인 메모가 포함되므로 비공개 보관. sessions·로그인 시도·서버 비밀정보는 백업하지 않는다.
복구는 **빈 대상 DB에만** 허용하여 기존 연구자료를 덮어쓰지 않는다.
서버 재시작 후 같은 Turso 환경변수를 유지하면 외부 DB 자료가 보존되는 구조이며 실제 Render 재시작 검증은 배포 후 수행해야 한다.

## 알려진 제약과 후속 작업

- 실 Render 배포, Turso 인증/FTS 실접속, GitHub schedule 첫 실행, 실제 모바일 브라우저 검증은 미완료.
- 한국 기준금리·한국 월간 CPI·세계교역량·한국 GDP 등 일부 계열은 공식 인증·코드 검증 전이다.
- 한국 수출입은 IMF IFS 지연 계열이다. 관세청 당월 속보치와 동일하지 않다.
- KDI Open API는 인증키 필요. KITA/KIET/IEA/IMF/SEMI/SIA 보고서 자동 등록기는 미구현. 공식 페이지 연결 상태를 수집 성공과 구분한다.
- EIA 공식 RSS는 robots 제한으로 미수집. 유가는 FRED의 EIA 실제 관측 계열을 사용한다.
- PDF는 enclosure로 공식 제공된 링크만 저장. 상세 페이지 PDF 탐색/전망 숫자 자동 추출 없음.
- 형식상 존재하지만 중단된 계열을 최신값으로 오인하지 않도록 관측일 표시. 공급기관 지연/수정은 가능하다.
- 3천건/일 네트워크·원격 DB 부하 및 장기 저장은 실제 운영에서 추가 검증해야 한다.
- full 백업은 CLI 수동 실행. 별도 외부 비공개 스토리지 예약 백업은 미연결.
- 수집 이력은 계속 축적되므로 월별 DB 크기와 읽기·쓰기량을 확인하고 보존정책을 추가할 것.
- 역할은 단일 개인 owner. 다중 사용자·공유·공개배포 기능 없음.

제약은 실제 코드/검증 범위를 기준으로 작성했다. 계정 연결 후 생성형 AI 없이 독립 운영할 수 있도록 구성했다.


## v1.1 — 로그인 후 화면·상호작용 오류 보완

- 서버 HTML/빈 응답을 무조건 JSON으로 읽지 않고 API 경로·HTTP 상태를 표시한다.
- 탭 이동은 API 완료 전 즉시 그리며, 한 요청 실패가 다른 화면을 막지 않는다.
- 화면별 필요한 요청만 실행하고 메타데이터는 짧게 재사용한다. 새로고침은 캐시를 비운다.
- 소스 상태는 집계 SQL, 시계열은 일괄 조회로 변경하여 정보원·지표별 반복 원격 요청을 줄였다.
- 서버 예외는 확인 코드가 있는 JSON 503으로 반환하며 상세 원인은 Render Logs에 기록한다.
- 네트워크 지연/HTML 응답/빈 응답/부분 실패/탭 경합/잘못된 날짜의 클라이언트 회귀 테스트를 추가했다.
- 실제 배포 서버의 원래 오류 원인은 URL·로그 확인 전이며 이 수정만으로 원격 해결을 확인했다고 보지 않는다.
- 적용: 저장소 파일을 교체하여 push → Render 재배포. DB와 환경변수는 기존 값을 사용한다.
- 화면 왼쪽 하단 v1.1 또는 /healthz의 version=2026.11.11-ui-fix1로 수정본 적용 여부를 확인한다.

추가 클라이언트 테스트: `node --test tests/client.test.cjs`.
