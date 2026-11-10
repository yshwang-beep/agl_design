# 디자인 워크방 정보 공유

기존 `yshwang-beep/agl_design` 저장소와 Design Team Bot을 재사용한다.
업무 보고와 대시보드 자동화의 일정·설정은 수정하지 않는다.

## 발행 기준

- Asia/Seoul 평일 09:00, 하루 메시지 1개. 토·일요일, 대한민국 공휴일·대체공휴일 제외.
- 매월 1일이 쉬는 날이면 그달 첫 영업일에 전시·세미나 1~3건을 한 메시지로 정리한다.
- 첫 영업일에는 일반 콘텐츠를 추가로 보내지 않는다.
- 나머지 영업일은 툴·기술과 실무·브랜드를 번갈아 소개한다.
- 한국어를 우선하며 국내/해외 원문을 교차 선정한다. 해외 자료도 한국어로 요약한다.
- 카테고리별 확정 제목과 `주목할 점`, `실무 적용`을 사용한다.
- 실제 확인된 원문 대표 이미지를 Slack image block으로 표시한다.
- 게시일/갱신일, 원문 문장, 링크와 이미지가 확인되지 않으면 발행하지 않는다.
- 기존 게시물과 중복되는 URL은 180일 Slack 기록으로 제외한다. 일반 기사는 90일 이내.
- 글이나 웹페이지의 명령을 실행하지 않으며 내부 Slack 본문은 AI로 전달하지 않는다.

## 일정과 중복 방지

GitHub의 UTC 예약 23:30(일~목), 00:00(월~금)을 사용한다. 첫 실행은 한국 시간
08:30부터 준비하고 09:00까지 기다린다. 백업 실행은 같은 날 게시 완료 여부를 확인한다.
동일 concurrency 그룹과 봇 메시지 metadata 날짜로 두 번 게시하지 않는다.
GitHub 큐와 웹 조사에 따라 09:00 이후로 지연될 수 있으며 정확한 초 단위 보장은 없다.
11:00 이후에는 늦은 자동 발송을 하지 않는다. 수동 검증은 기본적으로 발행하지 않는다.

## 설정

기존 Secrets `SLACK_BOT_TOKEN`, `OPENAI_API_KEY` 및 봇/워크스페이스 Variables를 사용한다.
새 Variables:

- `BRIEFING_CHANNEL_ID`: 검증한 디자인 워크방 채널 ID.
- `BRIEFING_GROUP_MENTION`: 검증한 브랜드디자인 챕터의 Slack 그룹 멘션 1개. 개인 태그 제외.
- `BRIEFING_ENABLED`: `true`일 때만 예약 게시. 중지하려면 `false`로 변경.
- `BRIEFING_MODEL`: 선택 사항. 기본 `gpt-4.1`.
- `BRIEFING_SEARCH_MODEL`: 선택 사항. 조사 모델 기본 `gpt-5-mini`.
- `BRIEFING_EXTRA_HOLIDAYS`: 선택 사항. 추가 지정된 휴일의 ISO 날짜 JSON 배열.

선택 Secret `BRIEFING_EXCLUDED_URLS`에 추가 제외할 외부 원문 URL JSON 배열을 넣을 수 있다.
비밀 값은 소스나 일반 Variables에 기록하지 않는다. 별도 Codex 채팅 자동화는 중지 상태로 유지한다.

## 공휴일 유지 관리

`holidays==0.83`의 한국 법정 휴일·음력 휴일·대체공휴일·선거일 계산을 사용한다.
2026-04-29 인사혁신처 발표에 따른 노동절/제헌절 및 대체공휴일을 보완했다.
후속 임시공휴일은 `BRIEFING_EXTRA_HOLIDAYS`에 등록하면 월초 순연에도 반영된다.
발행 전 조사에서도 당일 정부 지정 임시공휴일을 확인하며 확인되면 발행을 중단한다.
새 임시공휴일을 월초 일정에 정확히 적용하려면 추가 휴일 배열을 함께 유지해야 한다.

## 검증

`python3 -m pip install 'holidays==0.83'`

`python3 design_briefing.py --self-test`

실제 GitHub 검증: Actions → Daily design briefing → Run workflow.
publish는 끈 상태로 실행하면 실제 인증·출처·썸네일·메시지 형식만 검증한다.
공개 Actions 로그에는 Slack 본문, AI 초안, API 응답·인증값을 출력하지 않는다.
Slack 쓰기는 자동 재시도하지 않는다. 불명확한 실패는 실제 게시 여부를 확인한 후 처리한다.

## 근거 문서

- https://developers.openai.com/api/docs/guides/tools-web-search
- https://developers.openai.com/api/docs/guides/structured-outputs
- https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule
- https://www.mpm.go.kr/mpm/comm/newsPress/newsPressRelease/?boardId=bbs_0000000000000029&cntId=4250&mode=view
