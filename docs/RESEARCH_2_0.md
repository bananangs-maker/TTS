# TTS 2.0 — 구현·운영 범위

## 구조

기존 FastAPI + Turso/libSQL + 정적 JavaScript UI를 유지합니다. 독립 Python 수집 후 `python -m research_os.research.pipeline`이 특성값, 일별 집계, 신호, 보고서 스냅샷을 생성합니다. GitHub Actions가 이를 실행하며 Render 절전과 무관하게 외부 Turso에 저장하도록 구성했습니다. 생성형 AI·LLM API·회사 내부자료를 사용하지 않습니다.

## 추가 화면과 기능

- Industry trends: 산업·키워드·기간별 빈도, 일/주/월 집계, 비교 커버리지, 실제 근거 기사.
- Sentiment index: 확장·위축 표현을 규칙으로 분류한 지수. 투자심리 또는 미래 수익률로 해석하지 않습니다.
- Event database: 정책·투자·증설 등 제목의 명시적 사건 후보, 원문 출처, 사용자별 검증·연결.
- Quant research: 뉴스·경제 시계열 정렬, 0/1/3/6개월 상관, Holm 보정, OLS/HAC·잔차·단위근 진단, expanding/rolling 기준 모델 비교.
- Report center: 일/주/월 정형 보고서, JSON, 브라우저 인쇄를 통한 PDF 저장. 서버 PDF 엔진은 없습니다.
- Research archive: 개인 프로젝트·가설·메모·실험·차트 스냅샷. 화면 검색은 최근 200개 기록 내에서 동작합니다. 전체 내보내기는 페이지 제한 없이 본인 기록과 JANUS 관측값·기사 스크랩을 포함합니다.
- JANUS lab: 공개 출처가 명시된 사용자 CSV 등록과 비용 반영 고정 롱/현금 전략. H1~H4 자동 복합 모델은 후속 작업입니다.

## 데이터·계산 규칙

`config/research.json`에서 한·영 동의어, 사건 패턴, 분류·신호 기준을 관리합니다. 알고리즘과 설정 해시로 버전을 구분합니다. 특성값 처리 완료 표식으로 증분 실행하며 같은 자료를 중복 집계하지 않습니다.

분석 입력은 RSS 제목입니다. ASCII 단어 경계와 보수적 부정·인용·불확실 표현 규칙을 적용합니다. positive/negative/mixed/uncertain/neutral로 분류하고 S=100×(P−N)/(P+N)을 계산합니다. 혼합·불확실·중립은 분모에서 제외합니다. 분모가 없으면 null, 분류 표본이 20 미만이면 작은 표본 상태를 명시합니다. 규칙 분류 정확도에 대한 외부 정답 검증은 수행하지 않았습니다.

발행일과 실제 수집일을 분리합니다. KST 기준 이용가능일은 두 시각 중 늦은 값입니다. 발행일이 없거나 미래이거나 48시간 넘게 늦게 처음 수집된 백필 자료는 빈도 지표에서 제외하되 원문 자료는 보존합니다. 기사 수집 장애일을 0건으로 바꾸지 않습니다.

급증 비교는 고정 정보원과 수집 성공일 커버리지를 사용합니다. 7일 대 28일 비교, 변화율·Z·최소 표본 기준을 사용하고 충분한 연속 관측이 없으면 판단을 유보합니다. 정보원 증가나 장애를 실제 산업 변화로 단정하지 않습니다. 경제지표 임계치는 비율과 금리 %p를 구분합니다.

경제 관측값은 observation_vintages에 실제 수신·개정 시각을 보존합니다. 월별 연구에는 완료된 월의 실제 이용가능 자료를 사용합니다. 과거에 알려지지 않았던 뉴스·통계 빈티지를 생성하지 않습니다. 훈련에서만 스케일을 추정하고 순서를 섞지 않으며, 예측 시점에 알려지지 않은 정답은 훈련에서 제외합니다. 최소 훈련 36개월과 표본외 12개월이 필요합니다. 초기 수집 자료로 실제 예측 성능을 주장할 수 없습니다.

JANUS CSV의 헤더는 date,value,available_at입니다. 시각은 사용자가 선언한 미검증 값입니다. Google Trends 원자료를 매수 신호로 자동 변환하지 않습니다. 명시적 신호가 양수이면 롱, 나머지는 현금, 신호 확인 후 다음 종가 진입, 종료 청산 비용 포함, 연 252일·무위험금리 0 가정입니다. 관측일과 크게 동떨어진 이용가능일의 과거 가격을 거부합니다.

## 스키마와 보안

기존 items, records, runs, observations를 유지하고 article_features, article_keywords, feature_completion, research_daily, research_dictionary, industry_events, event_sources, event_reviews, event_links, duplicate_origins, observation_vintages, detected_signals, analysis_runs, research_projects, research_hypotheses, research_experiments, research_notes, generated_reports, janus_datasets, janus_observations를 추가합니다.

개인 읽기는 인증, 쓰기는 인증+CSRF가 필요합니다. user_id 조건으로 개인 데이터를 분리하고 게스트가 owner 자료를 받지 않게 합니다. SQL은 바인딩을 사용하며 HTML은 이스케이프합니다. DB/서비스 토큰은 브라우저 코드에 포함하지 않습니다. 백업에는 비밀 세션 대신 개인 연구 데이터가 포함되므로 비공개로 보관합니다. 복원은 빈 DB로 제한합니다.

## 검증과 제한

35 Python 테스트와 13 JavaScript 테스트가 통과했습니다. 주요 검증은 중복·증분 처리, 동의어 경계·부정·혼합, 백필·결측, 개인 인증·CSRF·소유자 분리, 빈티지·수정, 시간 순서·훈련 정답 누출 방지, JANUS 지연·비용, 보고서 멱등성과 XSS, 추가 마이그레이션·백업 복구, 200건을 넘는 개인 내보내기입니다.

로컬의 실제 공개 자료 895건에 파이프라인을 실행해 분석 버전과 보고서 4개를 저장했습니다. 로컬 DB는 배포 DB와 별개이며 ZIP에 포함하지 않습니다. 검증 결과는 `docs/validation.json`의 v2_0에 있습니다.

이번 버전의 실제 Render 배포, 원격 Turso 마이그레이션, GitHub 예약 실행, 실제 FRED API 키 경로, 모바일 실제 기기, 장기 운영 부하는 미검증입니다. 신규 화면 전체의 실제 브라우저 E2E 완료를 주장하지 않습니다. 공적 예측력 결과, Granger 인과·공적분·변화점, H1~H4 완성 전략, 자동 시장·Trends 수집은 미구현입니다. 기존 기관별 미연결 수집기는 계속 미연결 상태입니다.

보고서는 현재 시점의 저장 관측값을 사용하므로 공식 통계 개정이 있을 수 있습니다. 공개 보고서에 개인 가설·메모를 자동 삽입하지 않습니다. 데이터 내보내기 기본 범위는 선택 산업의 최근 730일이며, 차트의 일별 필터와 독립적입니다.
