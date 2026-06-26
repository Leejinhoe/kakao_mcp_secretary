# DailyRoute Guard

DailyRoute Guard(생활동선 캘린더 가드)는 텍스트나 OCR 텍스트에서 일정을 추출하고, 캘린더형 로컬 DB에 저장한 뒤, 일정 중복과 이동 불가능한 동선을 미리 알려주는 MCP 서버입니다.

## 1. 서비스 소개

하루 일정은 시간만 맞는다고 끝나지 않습니다. 장소 이동 시간, 중간 심부름, 평소 루틴, 출발 마감 시간이 함께 맞아야 실제로 지킬 수 있습니다. DailyRoute Guard는 이 부분을 도와주는 생활동선 보조 서버입니다.

## 2. 피벗한 이유

초기 아이디어였던 메신저 대화방 자동 읽기와 답장 추천은 공식 API 제약이 커서 공모전 MVP로 안정적으로 구현하기 어렵습니다. 그래서 비공식 로그인, 브라우저 스크래핑, 개인 대화방 접근을 모두 제외하고, 공식 API와 로컬 DB만으로 가능한 일정/동선 문제에 집중했습니다.

## 3. 핵심 기능

- 텍스트 또는 OCR 텍스트에서 일정 후보 추출
- 일정 저장 및 중복/겹침 감지
- 하루 일정 사이 이동 가능성 검사
- 약국, 카페, 프린트샵 같은 생활 경유지 추천
- 출퇴근/반복 루틴 저장
- 하루 동선 브리핑 생성
- 일정 전 경로 감시와 지각 위험 로그 생성
- 외부 API 키가 없어도 mock/fallback 모드로 데모 가능

## 4. MCP Tool 목록

1. `health_check`: 서버 상태 확인
2. `extract_schedule_from_text`: 텍스트/OCR 텍스트에서 일정 추출
3. `save_schedule`: 일정 저장 및 중복 경고
4. `check_day_feasibility`: 하루 일정의 이동 가능성 확인
5. `find_places_on_route`: 동선 중 심부름 경유지 추천
6. `save_routine`: 생활 루틴 저장
7. `build_daily_route_briefing`: 일일 동선 브리핑 생성
8. `create_route_watch`: 일정 전 경로 감시 등록
9. `get_route_alerts`: 최근 경로 경고 조회

## 5. 로컬 실행 방법

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m py_compile server.py dailyroute_service.py
python server.py
```

로컬 MCP endpoint:

```text
http://127.0.0.1:8000/mcp
```

HTTP health check:

```text
http://127.0.0.1:8000/health
```

SQLite DB는 기본적으로 `data/dailyroute_guard.db`에 생성됩니다.

## 6. MCP Inspector 테스트 방법

Inspector 설정:

- Transport: `Streamable HTTP`
- URL: `http://127.0.0.1:8000/mcp`
- Command: 비워둠
- Args: 비워둠

예시 입력:

```json
{
  "tool": "extract_schedule_from_text",
  "input": {
    "workspace_id": "demo",
    "text": "내일 오후 3시에 강남역에서 00기업 미팅 있어.",
    "source_type": "text",
    "reference_date": "2026-06-26"
  }
}
```

```json
{
  "tool": "save_schedule",
  "input": {
    "workspace_id": "demo",
    "title": "00기업 미팅",
    "start_at": "2026-06-27T15:00:00+09:00",
    "end_at": "2026-06-27T16:00:00+09:00",
    "date_text": "내일",
    "time_text": "오후 3시",
    "location_text": "강남역",
    "schedule_type": "meeting",
    "source_type": "manual"
  }
}
```

## 7. PlayMCP in KC 배포 주의사항

- 서버 이름에는 제한 단어를 넣지 말고 `dailyroute-guard` 또는 `dailyroute-mcp`처럼 등록하세요.
- Dockerfile 경로는 기본값 `Dockerfile`이면 됩니다.
- PAT는 HTTPS 비공개 저장소를 클론할 때만 필요합니다.
- 서버는 `HOST=0.0.0.0`, `PORT` 환경변수를 사용합니다.
- Streamable HTTP path는 `/mcp`입니다.
- 기존에 제한 단어가 들어간 서버 카드로 등록했다면 삭제 후 새 이름으로 다시 등록하는 편이 안전합니다.

## 8. 카카오 API 연동 환경변수

키가 없어도 서버는 동작하며 mock/fallback 결과를 한국어로 표시합니다.

```bash
ENABLE_REAL_KAKAO_APIS=false
KAKAO_REST_API_KEY=
KAKAO_MOBILITY_API_KEY=
KAKAO_ACCESS_TOKEN=
DAILYROUTE_DB_PATH=data/dailyroute_guard.db
```

- 키 없이 동작: 일정 추출, 일정 저장, 중복 경고, SQLite 저장, 모의 이동시간, 모의 경유지 추천, 경로 감시 로그
- 실제 API 키 필요: 실제 장소 검색, 실제 이동시간 조회, 톡캘린더 생성, 나에게 보내기 알림
- MVP에서는 이미지 OCR을 서버 안에서 직접 수행하지 않습니다. 이미지에서 OCR된 텍스트를 `extract_schedule_from_text`의 `text`에 넣어 테스트하세요.

## 9. 데모 시나리오 5개

### 시나리오 1: 텍스트에서 일정 저장

입력: `내일 오후 3시에 강남역에서 00기업 미팅 있어.`

흐름: `extract_schedule_from_text` → `save_schedule`

기대 결과: 제목 `00기업 미팅`, 날짜 `내일`, 시간 `오후 3시`, 장소 `강남역` 일정이 저장됩니다.

### 시나리오 2: 중복 일정 경고

먼저 `내일 오후 3시 강남역 00기업 미팅`을 저장한 뒤, `내일 오후 3시 역삼역 거래처 미팅`을 저장합니다.

기대 결과: `이미 내일 오후 3시에 '00기업 미팅' 일정이 저장되어 있습니다.` 형식의 경고가 반환되고, 기본값에서는 새 일정이 저장되지 않습니다.

### 시나리오 3: 이동 불가능한 일정 감지

일정 1: `2026-06-27T14:00:00+09:00` 안양 미팅

일정 2: `2026-06-27T14:30:00+09:00` 강남 미팅

흐름: `check_day_feasibility`

기대 결과: 안양에서 강남까지 모의 이동시간 48분이 필요해 지각 위험이 높다고 경고합니다.

### 시나리오 4: 퇴근길 심부름 경유지 추천

입력: 회사에서 집 가는 길에 약국과 카페를 들러야 하는 상황

흐름: `find_places_on_route`

기대 결과: `회사 → 약국 → 카페 → 집` 형태의 추천 경로와 mock 장소 후보가 반환됩니다.

### 시나리오 5: 경로 감시

15:00 강남 미팅을 저장하고 60분 전 경로 감시를 등록합니다.

흐름: `create_route_watch` → `get_route_alerts`

기대 결과: 남은 시간과 모의 이동시간을 비교해 지각 위험이 있으면 `route_check_logs`에 경고가 저장됩니다.
