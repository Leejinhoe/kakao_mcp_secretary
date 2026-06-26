# TalkGuard(톡가드)

TalkGuard(톡가드)는 중요한 메시지를 보내기 전에 약속, 일정, 대화 맥락을 다시 대조해 주는 한국어 중심 MCP 서버입니다. 핵심 목표는 "메시지를 보내기 전에 약속 충돌을 잡아내는 것"이며, 일반적인 캘린더 앱이 아니라 발송 직전의 커뮤니케이션 실수를 줄이는 Promise and Schedule Conflict Detection 도구입니다.

## 1. TalkGuard(톡가드) 소개

TalkGuard(톡가드)는 아래 기록을 SQLite에 저장합니다.

- 약속, 마감, 회의, 전달 일정
- 대화방/관계별 맥락과 커뮤니케이션 목표

그다음 `extract_commitments_from_text`, `extract_commitments_from_image`, `explain_conversation_context`, `review_message_before_send` 도구에서 카톡 텍스트/이미지, 이전 대화, 초안 메시지를 검사해 다음 위험을 알려줍니다.

- 카톡방 텍스트에서 약속/일정 후보 추출
- 카톡방 캡처 이미지 OCR 후 약속/일정 후보 추출
- ICS 캘린더 일정 가져오기
- 기존 약속보다 늦어지는 마감 표현
- 이미 잡힌 일정과 겹치는 가능 시간 제안
- 상대가 중요하게 보는 항목 누락
- 판교사투리나 복잡한 업무지시의 쉬운 설명
- 이전 대화의 업무지시를 답장이 제대로 반영하는지 확인
- 교수/고객/중요 관계에 맞지 않는 말투

날짜와 시간은 `다음 주`, `다음주`, `7월 1일`, `2026-07-01`, `오후 3시`처럼 자주 쓰는 한국어 표현을 규칙 기반으로 정규화해 비교합니다.

## 2. 핵심 컨셉: 약속/일정 충돌 감지기

TalkGuard(톡가드)의 핵심은 "보내기 전에 충돌을 먼저 본다"는 점입니다.

- 약속 저장: `save_commitment`
- 관계 맥락 저장: `save_room_context`
- 이전 대화 쉬운 설명: `explain_conversation_context`
- 텍스트 일정 추출: `extract_commitments_from_text`
- 이미지 OCR 일정 추출: `extract_commitments_from_image`
- 캘린더 일정 가져오기: `import_calendar_events`
- 발송 전 점검: `review_message_before_send`

특히 `review_message_before_send`는 내부적으로 PromiseGuard Engine을 사용해 아래 점수를 계산합니다.

- `deadline_conflict_score`
- `schedule_conflict_score`
- `missing_commitment_score`
- `instruction_alignment_score`
- `tone_risk_score`
- `final_risk_score`

최종 위험도 기준은 아래와 같습니다.

- `0-30`: `low`
- `31-69`: `medium`
- `70-100`: `high`

## 3. 왜 PlayMCP 공모전에 적합한지

- Streamable HTTP 기반 MCP 서버라서 PlayMCP AI Chat, MCP Inspector 같은 MCP 클라이언트가 바로 붙을 수 있습니다.
- 서버 안에서 LLM을 직접 돌리지 않고, 도구 서버 역할에 집중해서 MCP 아키텍처에 잘 맞습니다.
- SQLite 기반이라 가볍게 실행되면서도 실제 약속 기록을 누적할 수 있어 데모 가치가 높습니다.
- "메시지 보내기 전 충돌 감지"라는 명확한 사용 시나리오가 있어 Agentic Player 10 트랙에 잘 어울립니다.

## 4. MCP 서버와 LLM의 역할 차이

- TalkGuard(톡가드) MCP 서버:
  약속, 일정, 대화 맥락을 저장하고 규칙 기반으로 충돌을 계산합니다.
- LLM 클라이언트(예: PlayMCP AI Chat):
  사용자의 요청 흐름을 이해하고, 어떤 도구를 호출할지 판단하며, TalkGuard 결과를 바탕으로 대화를 이어갑니다.

즉, TalkGuard(톡가드)는 판단 재료를 제공하는 도구 서버이고, LLM 클라이언트는 그 도구를 사용하는 에이전트 역할입니다.

## 5. 실행 방법

```bash
cd /Users/ijinhoe/talkguard-mcp
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python server.py
```

서버가 정상 실행되면 MCP 엔드포인트는 아래 주소입니다.

- `http://127.0.0.1:8000/mcp`

로컬 문법/테스트 확인 명령:

```bash
.venv/bin/python -m py_compile server.py talkguard_service.py tests/test_talkguard_service.py
.venv/bin/pytest -q
```

## 6. 클라우드 배포

TalkGuard(톡가드)는 클라우드 환경의 `PORT` 환경변수를 자동으로 사용하고, 외부 접속을 위해 기본 `HOST`를 `0.0.0.0`으로 설정합니다.

주요 엔드포인트:

- MCP Streamable HTTP: `/mcp`
- HTTP 헬스 체크: `/health`

Docker 실행 예시:

```bash
docker build -t talkguard-mcp .
docker run --rm -p 8000:8000 -e TALKGUARD_DB_PATH=/data/talkguard.db talkguard-mcp
```

Render 배포:

- `render.yaml`을 포함하고 있어 Render Blueprint로 배포할 수 있습니다.
- Health Check Path는 `/health`입니다.
- MCP 클라이언트 URL은 `https://<your-service>.onrender.com/mcp` 형식입니다.
- 장기 데이터 보존이 필요하면 Render 대시보드에서 persistent disk를 `/data`에 붙이고 `TALKGUARD_DB_PATH=/data/talkguard.db`를 유지하세요.

클라우드 환경변수:

- `HOST`: 기본값 `0.0.0.0`
- `PORT`: 기본값 `8000`, Render/Railway/Fly 등에서는 플랫폼이 자동 주입
- `TALKGUARD_DB_PATH`: 기본 로컬값은 `data/talkguard.db`, Docker 권장값은 `/data/talkguard.db`

## 7. MCP Inspector 테스트 방법

Inspector 실행:

```bash
npx -y @modelcontextprotocol/inspector
```

연결 정보:

- Transport: `Streamable HTTP`
- URL: `http://127.0.0.1:8000/mcp`

연결 후 아래 9개 도구가 보여야 합니다.

1. `health_check`
2. `save_commitment`
3. `save_room_context`
4. `explain_conversation_context`
5. `extract_commitments_from_text`
6. `extract_commitments_from_image`
7. `import_calendar_events`
8. `review_message_before_send`
9. `get_guard_summary`

Inspector의 `initialize` 응답에서 `serverInfo.version`이 `1.28.0`처럼 보이면 이는 MCP/FastMCP 라이브러리 버전입니다. TalkGuard(톡가드) 앱 버전은 `health_check` 결과의 `version` 필드에서 확인합니다.

## 8. Tool 목록

### `health_check`

서버 상태를 확인합니다.

### `save_commitment`

약속, 마감, 회의, 전달 일정을 저장합니다.

`deadline_text`와 `time_text`는 자유 문자열로 받을 수 있지만, TalkGuard(톡가드)가 해석하지 못한 날짜/시간 표현은 `warning`으로 알려줍니다. 예를 들어 `time_text`가 `메롱`이면 저장은 하되 일정 충돌 비교에는 쓰기 어렵다고 안내합니다.

### `save_room_context`

대화방/관계 맥락과 커뮤니케이션 목표를 저장합니다.

### `explain_conversation_context`

이전 대화가 판교사투리나 복잡한 업무지시로 되어 있을 때 쉬운 한국어 요약, 감지된 업무 용어, 핵심 요청, 답장에 반드시 넣을 항목, 예시 답장을 제공합니다.

### `extract_commitments_from_text`

카톡방/채팅 텍스트에서 날짜, 시간, 마감, 회의, 제출, 공유 같은 신호를 찾아 약속 후보를 추출합니다. `save_extracted`가 `true`이면 추출된 후보를 바로 저장해 이후 발송 전 점검의 충돌 감지에 사용합니다.

### `extract_commitments_from_image`

카톡방 캡처 이미지에서 OCR로 텍스트를 읽고, 그 텍스트에서 약속 후보를 추출합니다. 입력은 `image_path`, `image_base64`, 또는 이미 OCR된 `ocr_text`를 지원합니다. 로컬에 `tesseract`가 있으면 먼저 사용하고, 없으면 macOS Vision OCR을 시도합니다. 둘 다 사용할 수 없는 환경에서는 `warnings`에 실패 이유를 반환합니다.

### `import_calendar_events`

`.ics` 캘린더 텍스트나 파일을 가져와 `VEVENT` 일정을 약속 DB에 저장합니다. Google Calendar, Apple Calendar, Outlook 등에서 내보낸 ICS 파일을 사용할 수 있으며, OAuth나 외부 API 없이 데모할 수 있습니다.

### `review_message_before_send`

저장된 약속, 이전 대화, 초안 메시지를 대조해 충돌, 누락, 업무지시 반영 여부, 톤 위험을 점검합니다.

### `get_guard_summary`

워크스페이스에 저장된 약속과 대화 맥락, 그리고 다음 위험 포인트를 요약합니다.

## 9. 데모 시나리오 6개

### 시나리오 1. 마감 충돌 감지

1. `save_commitment` 호출

```json
{
  "workspace_id": "default",
  "title": "금요일까지 데모 영상 공유",
  "commitment_type": "deadline",
  "deadline_text": "금요일",
  "related_person": "팀장",
  "related_room": "공모전 팀방",
  "source_type": "chat",
  "importance": "high",
  "status": "planned"
}
```

2. `review_message_before_send` 호출

```json
{
  "workspace_id": "default",
  "draft_message": "다음 주에 데모 영상 정리해서 보내드리겠습니다.",
  "room_name": "공모전 팀방",
  "recipient_type": "team"
}
```

예상 결과:

- `risk_level`: `high`
- 설명: 기존 약속은 금요일까지 데모 영상을 공유하는 것이지만, 현재 메시지는 다음 주로 미루는 표현입니다.
- `safer_message` 예시:
  `금요일까지 데모 영상 초안을 먼저 공유드리고, 추가 정리는 이후에 보완하겠습니다.`

### 시나리오 2. 중요 항목 누락 감지

1. `save_room_context` 호출

```json
{
  "workspace_id": "default",
  "room_name": "공모전 팀방",
  "room_type": "team",
  "context": "팀장은 금요일까지 데모 영상을 원하고, 데모 영상 공유 여부를 중요하게 확인합니다.",
  "communication_goal": "데모 영상 공유 여부를 분명하게 말하기"
}
```

2. `review_message_before_send` 호출

```json
{
  "workspace_id": "default",
  "draft_message": "오늘 기능 정리해서 공유드리겠습니다.",
  "room_name": "공모전 팀방",
  "recipient_type": "team"
}
```

예상 결과:

- `risk_level`: `medium`
- 설명: 방 맥락에서 중요한 항목인 `데모 영상`이 초안에 직접 드러나지 않습니다.
- `safer_message` 예시:
  `데모 영상 관련 일정과 범위도 함께 분명히 말씀드리겠습니다.`

### 시나리오 3. 일정 충돌 감지

1. `save_commitment` 호출

```json
{
  "workspace_id": "default",
  "title": "내일 오후 3시 팀 회의",
  "commitment_type": "meeting",
  "deadline_text": "내일",
  "time_text": "오후 3시",
  "related_room": "공모전 팀방",
  "source_type": "calendar",
  "importance": "high",
  "status": "planned"
}
```

2. `review_message_before_send` 호출

```json
{
  "workspace_id": "default",
  "draft_message": "내일 오후 3시에 가능합니다.",
  "room_name": "공모전 팀방",
  "recipient_type": "client"
}
```

예상 결과:

- `risk_level`: `high`
- 설명: 내일 오후 3시에 이미 저장된 일정이 있는데, 현재 메시지는 같은 시간에 가능하다고 말하고 있습니다.
- `safer_message` 예시:
  `내일 오후 3시는 기존 일정이 있어 어렵고, 오후 5시 이후 가능할 것 같습니다.`

### 시나리오 4. 어려운 업무지시 쉬운 설명과 답장 체크

1. `explain_conversation_context` 호출

```json
{
  "conversation_text": "QA 리스크랑 데모 일정 얼라인해서 EOD까지 공유해 주세요.",
  "room_name": "공모전 팀방",
  "recipient_type": "team"
}
```

예상 결과:

- `plain_summary`: 상대 요청을 쉬운 말로 설명
- `detected_jargon`: `리스크`, `얼라인`, `EOD` 같은 표현과 뜻
- `reply_should_include`: 답장에 넣어야 할 핵심 항목

2. `review_message_before_send` 호출

```json
{
  "workspace_id": "default",
  "draft_message": "확인했습니다.",
  "room_name": "공모전 팀방",
  "recipient_type": "team",
  "previous_conversation": "QA 리스크랑 데모 일정 얼라인해서 EOD까지 공유해 주세요."
}
```

예상 결과:

- `risk_level`: `medium`
- 설명: 이전 대화의 핵심인 리스크, 데모 일정, EOD 기준이 답장에 빠져 있습니다.
- `safer_message` 예시:
  `이전 대화 기준으로 빠진 항목(리스크, 일정, 데모)을 확인했고, 진행 가능 여부와 다음 액션도 함께 말씀드리겠습니다.`

### 시나리오 5. 카톡 텍스트/이미지에서 일정 추출

1. `extract_commitments_from_text` 호출

```json
{
  "workspace_id": "default",
  "source_text": "금요일까지 데모 영상 공유\n내일 오후 3시 팀 회의",
  "related_room": "공모전 팀방",
  "source_type": "chat",
  "save_extracted": true
}
```

예상 결과:

- `extracted_count`: `2`
- 첫 번째 후보: 금요일까지 데모 영상 공유
- 두 번째 후보: 내일 오후 3시 팀 회의
- `save_extracted`가 `true`이면 저장된 약속이 이후 `review_message_before_send`에서 충돌 감지에 사용됩니다.

2. `extract_commitments_from_image` 호출

```json
{
  "workspace_id": "default",
  "image_path": "/path/to/chat-screenshot.png",
  "related_room": "공모전 팀방",
  "save_extracted": true
}
```

이미 MCP 클라이언트나 다른 도구가 OCR 텍스트를 제공하는 경우에는 아래처럼 `ocr_text`만 넣어도 같은 일정 추출 로직을 사용할 수 있습니다.

```json
{
  "workspace_id": "default",
  "ocr_text": "7월 1일 오후 3시 고객 미팅",
  "related_room": "고객방",
  "save_extracted": true
}
```

### 시나리오 6. ICS 캘린더 일정 가져오기

`import_calendar_events` 호출:

```json
{
  "workspace_id": "default",
  "calendar_text": "BEGIN:VCALENDAR\nVERSION:2.0\nBEGIN:VEVENT\nUID:event-1\nSUMMARY:고객 미팅\nDTSTART;TZID=Asia/Seoul:20260701T150000\nDTEND;TZID=Asia/Seoul:20260701T160000\nLOCATION:판교\nDESCRIPTION:고객사와 데모 범위 논의\nEND:VEVENT\nEND:VCALENDAR",
  "related_room": "고객방",
  "save_imported": true
}
```

예상 결과:

- `extracted_count`: `1`
- `saved_count`: `1`
- 가져온 일정은 `source_type: calendar`로 저장됩니다.
- 이후 `7월 1일 오후 3시에 가능합니다.` 같은 답장은 기존 일정과 충돌하는지 점검됩니다.

## 10. 향후 확장 계획

- 이메일에서 약속 추출
- 메신저 나와의 채팅방 알림
- 팀/교수/거래처별 말투 정책 강화
- 판교사투리/업무 용어 사전 확장
- OCR 엔진별 정확도 개선과 Docker 환경 OCR 패키징
- 반복 일정 RRULE 확장과 실시간 Google/Apple Calendar OAuth 연동

## 부가 파일

- [server.py](/Users/ijinhoe/talkguard-mcp/server.py)
- [talkguard_service.py](/Users/ijinhoe/talkguard-mcp/talkguard_service.py)
- [tests/test_talkguard_service.py](/Users/ijinhoe/talkguard-mcp/tests/test_talkguard_service.py)
- [Dockerfile](/Users/ijinhoe/talkguard-mcp/Dockerfile)
- [requirements.txt](/Users/ijinhoe/talkguard-mcp/requirements.txt)
