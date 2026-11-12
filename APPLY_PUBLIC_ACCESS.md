# 공개 열람 수정 — TTS 2.0.1

## 현재 상태

소스 수정과 로컬 테스트·브라우저 검증은 완료했습니다. GitHub/Render 관리 연결이 없어 이번 수정의 원격 업로드와 Render 재배포는 아직 하지 않았습니다. 서비스 접근용 ChatGPT Site 토큰을 GitHub나 Render 배포에 사용하지 않았습니다.

## 기존 2.0에 적용

기존 GitHub 저장소 https://github.com/bananangs-maker/TTS 에서 아래 3개 파일을 이 ZIP의 같은 파일로 교체합니다.

- research_os/app.py
- research_os/static/app.js
- research_os/static/index.html

동일한 기존 2.0 소스를 Git으로 관리한다면, `PUBLIC_ACCESS_FIX.patch`만 저장소 루트에 복사한 뒤 `git apply --check PUBLIC_ACCESS_FIX.patch`, `git apply PUBLIC_ACCESS_FIX.patch`로 적용할 수도 있습니다. 충돌이 나면 강제로 덮어쓰지 않고 해당 파일의 현재 변경과 대조합니다.

변경을 커밋·push하고 Render에서 해당 커밋을 배포합니다. 자동 배포가 연결돼 있다면 완료를 기다립니다. Turso·API 키·관리자 아이디/비밀번호 설정은 유지합니다. DB를 초기화하거나 새 DB를 만들 필요가 없습니다.

배포 후 `/healthz`의 version이 **2026.11.12-public-access-v2.0.1**인지 확인합니다. 이전 버전이면 이 수정의 배포가 완료된 것이 아닙니다.

## 확인할 동작

1. 쿠키 없는 브라우저에서 홈페이지를 열면 로그인 입력 없이 공개 화면이 표시됩니다.
2. Overview, Newsroom, Research library, Economic monitor, Signal monitor, Industry trends, Sentiment index, Event database, Quant research, Report center, 수집 상태를 이동합니다.
3. 공개 기사·보고서 검색, 필터, 상세, 원문 링크를 사용할 수 있습니다. 경제지표 자체가 미수집이면 수집 오류·결측이 표시되며 로그인 문제와 구분해야 합니다.
4. 선택 로그인에는 ‘공개 뉴스룸으로 돌아가기’가 있습니다. 로그인 취소와 세션 만료가 공개 메뉴를 막지 않습니다.
5. 개인 보관함·연구 메모·실험 저장·JANUS 개인 데이터와 관리자 설정은 인증 전에는 열람/수정할 수 없습니다. 서버는 관련 접근을 401, CSRF 없는 인증 요청을 403으로 거부합니다. 정보원 상태의 수정 입력란은 비로그인 화면에서 숨깁니다.

## 검증 기록

36 Python 테스트 + 18 JavaScript 테스트 통과. 인증 만료·없는 쿠키의 공개 API, 개인정보 누출 방지, 관리자 수정 거부, 401 이후 공개 화면 유지, 선택 로그인 취소, 세션 조회 대기 중 공개 자료 로딩을 포함합니다.

실제 저장 공개자료가 있는 로컬 수정본에서 공개 메뉴 11개를 비로그인 브라우저로 이동했고 로그인 폼 0개·메뉴 오류 0개를 확인했습니다. 개인 메뉴 3개에서는 내용 대신 보호 안내만 나왔습니다. 이는 로컬 검증이며 Render 재배포 완료의 증거가 아닙니다.

현재 Render의 2.0 배포본에서는 비로그인 공개 API와 뉴스·보고서 열람을 확인했으나 Economic monitor는 FRED 시간 초과로 미수집, Quant research는 API 시간 초과가 발생했습니다. 이 패치는 해당 데이터 수집/쿼리 성능 문제까지 해결했다고 주장하지 않습니다.
