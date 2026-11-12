# TTS 2.0 업데이트 안내

이 ZIP은 Render용 전체 소스 업데이트입니다. 기존 GitHub 저장소 https://github.com/bananangs-maker/TTS 를 사용합니다. 새 저장소나 새 Turso DB를 만들 필요가 없습니다.

## 적용 순서

1. 기존 Turso 설정을 사용하는 환경에서 먼저 백업합니다. `python -m research_os.backup export backups/before-v2.json`. 백업에는 개인 메모가 있으므로 공개 저장소에 올리지 않습니다. 새 코드의 백업 명령은 업그레이드 전 스키마도 처리합니다.
2. ZIP을 풀고 기존 저장소의 전체 코드를 교체해 커밋합니다. `.env`, DB, 토큰은 업로드하지 않습니다. 정적 파일만 교체하면 새 API와 스키마가 적용되지 않습니다.
3. **숨김 폴더 `.github`도 반드시 교체합니다.** macOS에서는 Command+Shift+. 로 표시합니다. 특히 `.github/workflows/collect.yml`에 아래 분석 단계가 있어야 합니다. GitHub 웹에서도 해당 파일을 직접 수정할 수 있습니다.
4. GitHub Actions Secrets의 `TURSO_DATABASE_URL`, `TURSO_AUTH_TOKEN`과 Render의 같은 환경변수를 유지합니다. 개인 로그인 설정도 기존 값을 유지합니다.
5. Render에서 최신 커밋을 배포합니다. 시작 시 CREATE TABLE IF NOT EXISTS 기반의 추가 마이그레이션이 실행됩니다. 기존 기사·북마크·메모 테이블을 초기화하지 않습니다.
6. `/healthz`에서 `version: 2026.11.11-tts-v2.0`, `storage: turso`를 확인합니다.
7. Actions → **Collect public research** → Run workflow → mode `all`. 수집 단계와 **Build research features, signals and period reports** 단계가 모두 실행되는지 확인합니다. 분석 단계는 수집에 부분 실패가 있어도 실행됩니다.
8. 앱에서 Industry trends, Sentiment index, Event database, Quant research, Report center, Research archive, JANUS lab을 확인합니다. 단순 새로고침은 수집 명령이 아닙니다.

## 경제지표 연결

`FRED_API_KEY`가 없으면 기존 공개 CSV 경로를 사용합니다. 기존 실행 환경에서 FRED CSV 요청이 시간 초과했다면, 공식 FRED 계정에서 발급받은 키를 Actions Repository Secret의 Name=`FRED_API_KEY`, Secret=발급값으로 추가할 수 있습니다. 키를 채팅이나 코드에 적지 않습니다.

공식 API 경로는 모의 응답 계약 테스트를 통과했으나 실제 발급 키를 사용한 원격 성공은 아직 검증하지 못했습니다. 키 추가 자체가 접속 성공을 보장하지 않습니다. 소스·지표별 오류와 마지막 성공 시각을 확인해야 합니다.

## 수집 워크플로 전체

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
      - name: Build research features, signals and period reports
        if: always()
        run: python -m research_os.research.pipeline
```

## 검증 범위와 남은 작업

- Python 35개 + JavaScript 13개 테스트 통과. 로컬 실제 기사·보고서 895건에 분석 파이프라인을 실행했습니다. 가상 기사나 DB는 ZIP에 넣지 않았습니다.
- 장기 뉴스 이력이 부족하므로 통계·예측 화면이 `insufficient_data`를 반환할 수 있습니다. 데이터가 없는 기간은 0으로 만들지 않습니다.
- JANUS는 시점이 선언된 CSV 등록 및 고정 롱/현금 전략 실험 기반입니다. H1~H4 복합 전략, 자동 가격·Google Trends 수집, 예측력 검증을 완료했다는 뜻은 아닙니다.
- 이번 2.0의 GitHub 업로드, Render 재배포, 원격 Turso 마이그레이션과 예약 실행은 아직 수행하지 않았습니다. 해당 계정의 쓰기/배포 연결이 현재 없습니다.
- 현재 ChatGPT Site의 정기 수집과 이 Render 앱은 별개입니다. Site 수집 성공을 Render 2.0 적용 증거로 사용하지 않습니다.

세부 방법론과 제한은 `docs/RESEARCH_2_0.md`에 있습니다.
