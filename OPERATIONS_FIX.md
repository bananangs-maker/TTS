# 기존 TTS 운영 반영 절차

현재 운영 커밋: `8c4397030b7369460eb3235e663f48df359b3e48`. 이번 수정은 그 코드와 파일을 대조한 유지보수입니다. 기존 GitHub 저장소·Render 서비스·Turso DB를 유지합니다.

## 1. 보호와 적용

기존 환경변수로 `python -m research_os.backup export backups/before-operations.json`을 실행해 개인 자료 포함 백업을 비공개 보관합니다. 현재 작업에서는 원격 관리자 권한이 없어 운영 백업은 수행하지 못했습니다. 로컬 DB는 수정 전에 백업했습니다.

ZIP의 전체 소스를 기존 저장소에 반영합니다. DB·backups·.env·토큰은 업로드하지 않습니다. 스키마는 기존 테이블을 추가 생성하는 방식이며 이번 수정은 기존 기사나 개인 기록을 삭제하지 않습니다. 새 DB를 만들거나 기존 DB를 초기화할 필요가 없습니다.

**중요: `.github/workflows/collect.yml`도 반드시 교체합니다.** 운영 저장소에서는 이 파일만 구형으로 남아 있었습니다. Finder에서 숨김 파일을 놓칠 경우 루트의 `COLLECT_WORKFLOW.yml` 내용을 GitHub의 기존 `.github/workflows/collect.yml`에 직접 붙여넣습니다. 루트 파일만 올리면 GitHub Actions가 실행하지 않습니다. `.github/workflows/test.yml`도 포함합니다.

## 2. 기존 비밀정보 유지

- 기존 `TURSO_DATABASE_URL`, `TURSO_AUTH_TOKEN`은 Render와 GitHub Actions에서 그대로 사용합니다.
- 관리자 계정·해시는 보호 기능용으로 유지합니다. 공개 열람은 이 설정 없이도 시작됩니다.
- `FRED_API_KEY`가 이미 있다면 새 워크플로가 이를 수집기에 전달합니다. 키의 실제 존재/값은 확인 권한이 없어 검사하지 않았습니다.
- 키가 없으면 기존 공식 CSV 경로를 사용합니다. 이 경로는 이번 로컬 검사에서 실제 동작했지만 Actions 실행 환경에서는 시간 초과했습니다. 계속 실패하면 공식 등록 FRED 키를 Actions Secret에 추가하고 API 경로를 실제 검증해야 합니다. API 키를 임의 생성하지 않습니다.

## 3. 배포와 수집 검증

수정 커밋을 push해 Render 자동 배포를 기다립니다. 현재 계정 연결이 없어 이번 push·배포는 수행하지 못했습니다.

1. `/healthz`에 `version=2026.11.12-operations-fix`, `storage=turso`, 실제 `commit`이 출력되는지 확인합니다.
2. GitHub Actions → Collect public research → Run workflow → `all`.
3. ‘Collect independently of Render’의 소스별 상태와 저장 건수를 확인합니다. 일부 실패도 작업 종료 코드는 실패지만 다른 소스 처리는 완료합니다. 실패한 지표를 수집 성공으로 보고하지 않습니다.
4. ‘Verify preserved records and storage identity’의 `storage_id`와 `/healthz`의 `storage_id`를 대조합니다. 이 값은 DB URL 해시의 일부로, 토큰·호스트명을 출력하지 않습니다. 토큰이 달라도 같은 URL이면 지문이 같습니다.
5. ‘Build research features, signals and period reports’ 실행과 앱 시스템 상태의 분석 이력을 대조합니다. 이 단계는 수집 부분 실패에도 실행됩니다.
6. 지표 API와 시스템 상태에서 저장 관측 수·관측일·단위·오류를 확인합니다. API가 200이라는 이유만으로 값이 있다고 판단하지 않습니다.
7. 비로그인 공개 메뉴, 검색/필터, 개인 저장 차단, 모바일을 운영에서 다시 검증합니다. 강제 재시작 전후 뉴스·보고서·북마크·메모를 대조합니다.

표본이 없는 분석은 ‘자료 부족/대기’로 표시합니다. 과거에 수집하지 않았던 데이터를 0이나 가상 기사로 채우지 않습니다.

## 실제 실행 워크플로 전체

```yaml
name: Collect public research
on:
  schedule:
    - cron: '17 1,7,13,19 * * *' # UTC → 10:17,16:17,22:17,04:17 KST
  workflow_dispatch:
    inputs:
      mode:
        description: Sources to update
        type: choice
        options: [all, feeds, indicators]
        default: all
permissions:
  contents: read
concurrency:
  group: research-os-collector
  cancel-in-progress: false
jobs:
  collect:
    runs-on: ubuntu-latest
    timeout-minutes: 20
    env:
      TURSO_DATABASE_URL: ${{ secrets.TURSO_DATABASE_URL }}
      TURSO_AUTH_TOKEN: ${{ secrets.TURSO_AUTH_TOKEN }}
      FRED_API_KEY: ${{ secrets.FRED_API_KEY }}
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'
          cache: pip
      - run: pip install -r requirements.txt
      - name: Check persistent storage configuration
        run: python -c "import os; assert os.environ.get('TURSO_DATABASE_URL') and os.environ.get('TURSO_AUTH_TOKEN'), 'Turso secrets must be configured'"
      - name: Collect independently of Render
        env:
          COLLECT_MODE: ${{ inputs.mode || 'all' }}
        run: python -m research_os.collector --mode "$COLLECT_MODE"
      - name: Verify preserved records and storage identity
        if: always()
        run: python -m research_os.operations --require-remote
      - name: Build research features, signals and period reports
        if: always() && env.TURSO_DATABASE_URL != '' && env.TURSO_AUTH_TOKEN != ''
        run: python -m research_os.research.pipeline
```

## 권한으로 남은 작업

필요한 연결은 GitHub의 TTS 저장소 쓰기·Actions 실행/로그와 Render의 배포·환경설정 확인·로그·재시작입니다. 웹앱의 개인 로그인 권한과 별개입니다. 연결 후 위의 운영 검증을 마쳐야 장애 해결 완료로 판정할 수 있습니다.
