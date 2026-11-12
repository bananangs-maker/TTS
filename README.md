# TTS — Think Tank System

공개 경제·산업 뉴스, 한국은행 보고서, 공식 경제지표를 수집·검색하는 개인 리서치 시스템입니다. Render + Turso/libSQL + 독립 Python 수집기 + GitHub Actions를 사용합니다. LLM API·Supabase·회사 내부자료를 사용하지 않습니다.

## 지금 확인된 운영 상태

2026-11-12 운영 점검: 최신 GitHub/Render 커밋 `8c4397030b7369460eb3235e663f48df359b3e48`, 배포 성공, 앱 2.0.1과 정적 파일 일치. 뉴스545·보고서259건은 저장돼 있지만 경제지표14개는 FRED 요청 시간 초과로 관측0건입니다. 예약 수집은 실제 실행됐으나 워크플로가 구형으로 남아 분석 단계와 FRED 키 전달이 없습니다.

**이번 유지보수 소스는 수정·로컬 검증 완료, 운영 반영 전입니다.** GitHub 쓰기/Render 관리 연결이 없어 업로드·배포·새 예약 실행·원격 재시작은 수행하지 못했습니다. 로컬 자료를 운영 자료로 보고하지 않습니다.

- [OPERATIONS_REPORT.md](OPERATIONS_REPORT.md): 사용자 요청 형식의 8개 영역 진단표, 기관별 상태, 실제 확인/미확인 구분
- [OPERATIONS_FIX.md](OPERATIONS_FIX.md): 기존 저장소·DB를 유지하는 반영 절차와 워크플로 전체
- [docs/operations-audit.json](docs/operations-audit.json): 운영·로컬 검증 수치
- `COLLECT_WORKFLOW.yml`: 숨김 파일 업로드 누락을 막기 위한 워크플로 복사본. 실제 실행 경로는 **.github/workflows/collect.yml**입니다.

## 유지보수 변경

- 읽기 중심의 흰색·회색·네이비 화면. 주요 뉴스→보고서→지표 순서, 보조 도구는 접어서 보존.
- 기본 뉴스 목록은 명시적 연구 주제로 제한하며 ‘연구 주제만’을 해제하면 원래 자료를 모두 검색할 수 있습니다. 기존 기사를 삭제하지 않습니다.
- 공개 열람과 선택 관리자 인증 분리. 개인 메모·북마크·설정·수정은 서버 인증과 CSRF 유지.
- 데이터/분석 부재를 0으로 채우지 않고 결측·대기로 구분. 초기 Quant 조회의 반복 쿼리·불필요한 통계 로딩 축소.
- 경제지표는 최초 수신·수정 빈티지 보존, 미래 관측 제외, DB 저장 후 재조회. 수집 실패는 다른 소스를 계속 처리한 뒤 실패 종료 코드로 노출.
- 독립 수집 후 분석·보고서 생성. 저장소 지문을 웹/Actions에서 대조할 수 있으나 운영 배포·실행 전에는 동일 DB 확인 완료로 간주하지 않습니다.

## 로컬 실행

Python3.12 권장. 공개 열람에는 관리자 비밀번호 설정이 필요 없습니다.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m research_os.collector --mode feeds
python -m research_os.collector --mode indicators
python -m research_os.research.pipeline
uvicorn research_os.app:app --host 127.0.0.1 --port 8000
```

로컬 개발은 SQLite를 사용합니다. Render에서는 기존 `TURSO_DATABASE_URL`, `TURSO_AUTH_TOKEN`을 유지하며 로컬 임시 저장소로 대체하지 않습니다. `.env.example`은 설정 이름의 예시이며 자동 로드하지 않습니다. 개인 저장 기능은 `python -m scripts.hash_password`로 생성한 `ADMIN_PASSWORD_HASH`와 선택 `ADMIN_USERNAME`으로 활성화합니다. 비밀번호·토큰을 코드에 넣지 않습니다.

## 검증

```bash
python -m pytest -q
node --test tests/client.test.cjs
python -m research_os.operations
```

Python42개 + JavaScript18개 통과. 브라우저에서 공개 메뉴11개, 한국어 검색·출처·기간·영문·페이지 이동·북마크 보호·390px 반응형 메뉴와 경제 차트를 확인했습니다. 실제 모바일 기기는 미검증입니다.

실제 RSS 로컬 재수집에서 뉴스33건 신규/17건 중복, BOK100건 중복을 확인했고 공식 환율517개를 저장·재조회했습니다. 로컬 전체는 뉴스669·보고서259·관측4252개로 운영 DB와 다릅니다. ZIP에는 DB·백업·비밀정보·가짜 seed가 없습니다.

## 운영·보존

```bash
python -m research_os.backup export backups/full.json
python -m research_os.operations --require-remote
```

백업에는 개인 메모가 포함되므로 비공개로 보관합니다. 복원 도구는 빈 대상 DB만 허용합니다. 이번 수정에 DB 초기화나 복원은 필요하지 않습니다. 한국 기준금리·한국 CPI 등 미연결 계열 및 대부분 기관 보고서 수집기는 공식 인증/구현 전입니다. 상태 화면에서 정상 수집과 구분합니다. 모든 지표에 관측일·수집일·원천·단위를 표시하며 서로 다른 단위를 같은 차트에 합치지 않습니다.

과거 구현·설치 기록은 `docs/README_HISTORY.md`, 분석 방법은 `docs/RESEARCH_2_0.md`입니다. 새로운 모델·투자 전략은 추가하지 않았습니다.
