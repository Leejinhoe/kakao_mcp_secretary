# DailyRoute Guard

DailyRoute Guard(생활동선 캘린더 가드)는 텍스트나 OCR 텍스트에서 일정을 추출하고, 캘린더형 로컬 DB에 저장한 뒤, 일정 중복과 이동 불가능한 동선을 미리 알려주는 MCP 서버입니다.

## 1. 서비스 소개

하루 일정은 시간만 맞는다고 끝나지 않습니다. 장소 이동 시간, 중간 심부름, 평소 루틴, 출발 마감 시간이 함께 맞아야 실제로 지킬 수 있습니다. DailyRoute Guard는 이 부분을 도와주는 생활동선 보조 서버입니다.

## 2. 피벗한 이유

초기 아이디어였던 메신저 대화방 자동 읽기와 답장 추천은 공식 API 제약이 커서 공모전 MVP로 안정적으로 구현하기 어렵습니다. 그래서 비공식 로그인, 브라우저 스크래핑, 개인 대화방 접근을 모두 제외하고, 공식 API와 로컬 DB만으로 가능한 일정/동선 문제에 집중했습니다.

## 3. 핵심 기능

- 텍스트 또는 OCR 텍스트에서 일정 후보 추출
- 일정 저장 및 중복/겹침 감지
- 저장 직후 이전 일정과의 이동 가능성 자동 검사
- 하루 일정 사이 이동 가능성 검사
- 약국, 카페, 프린트샵 같은 생활 경유지 추천
- 출퇴근/반복 루틴 저장
- 하루 동선 브리핑 생성
- 일정 전 경로 감시와 지각 위험 로그 생성
- 외부 API 키가 없어도 mock/fallback 모드로 데모 가능

## 4. MCP Tool 목록

1. `health_check`: 서버 상태 확인
2. `extract_schedule_from_text`: 텍스트/OCR 텍스트에서 일정 추출
3. `save_schedule`: 일정 저장, 중복 경고, 자동 이동 가능성 확인
4. `list_schedules`: 워크스페이스별 일정 조회
5. `update_schedule`: 일정 수정 및 이동 가능성 재확인
6. `delete_schedule`: 일정 삭제
7. `check_conflict`: 저장 전 일정 충돌 확인
8. `check_day_feasibility`: 하루 일정의 이동 가능성 확인
9. `find_places_on_route`: 동선 중 심부름 경유지 추천
10. `manage_route_preferences`: 동선 프로필, 심부름, 생활 루틴 저장/조회
11. `connect_kakao_calendar`: 카카오 캘린더 연결 상태와 로그인 URL 확인
12. `sync_to_talk_calendar`: 저장된 일정을 톡캘린더에 동기화
13. `build_daily_route_briefing`: 일일 동선 브리핑 생성
14. `create_route_watch`: 일정 전 경로 감시 등록
15. `get_route_alerts`: 최근 경로 경고 조회

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
- 카카오 OAuth를 쓸 경우 배포 도메인을 `PUBLIC_BASE_URL`에 넣고, 카카오 Developers의 Redirect URI에 `https://배포도메인/oauth/kakao/callback`을 등록하세요.
- 기존에 제한 단어가 들어간 서버 카드로 등록했다면 삭제 후 새 이름으로 다시 등록하는 편이 안전합니다.

### GHCR 이미지로 배포하기

PlayMCP가 GitHub 저장소 빌드가 아니라 Registry 이미지를 받는 경우, 로컬에서 secrets 파일을 포함한 Docker 이미지를 빌드해 GHCR에 push합니다.

1. 로컬 프로젝트 루트에 `secrets.local.json`을 만듭니다. 이 파일은 `.gitignore`에 포함되어 GitHub에 올라가지 않습니다.

```json
{
  "ENABLE_REAL_KAKAO_APIS": "true",
  "KAKAO_REST_API_KEY": "카카오_REST_API_키",
  "KAKAO_MOBILITY_API_KEY": "카카오_REST_API_키",
  "KAKAO_OAUTH_SCOPES": "talk_message,talk_calendar",
  "KAKAO_CALENDAR_ID": "primary"
}
```

2. Docker 이미지를 빌드합니다.

```bash
docker build --platform linux/amd64 -t mcp-secretary:v1.0.7 .
```

3. GHCR용 태그를 붙입니다.

```bash
docker tag mcp-secretary:v1.0.7 ghcr.io/leejinhoe/mcp-secretary:v1.0.7
```

4. GHCR에 로그인합니다. GitHub PAT에는 `write:packages`, `read:packages` 권한이 필요합니다.

```bash
echo "GitHub_PAT" | docker login ghcr.io -u Leejinhoe --password-stdin
```

5. 이미지를 push합니다.

```bash
docker push ghcr.io/leejinhoe/mcp-secretary:v1.0.7
```

6. PlayMCP 이미지 등록 화면에는 다음처럼 입력합니다.

```text
Registry 호스트: ghcr.io
Registry 사용자: Leejinhoe
Registry 비밀번호: GitHub PAT
image_name: leejinhoe/mcp-secretary
image_tag: v1.0.7
```

Docker 이미지는 `secrets.local.json`을 포함하므로 GHCR 패키지는 private으로 유지하세요.

## 8. 카카오 API 설정

키가 없어도 서버는 동작하며 mock/fallback 결과를 한국어로 표시합니다.

공개 MCP tool에는 API 키 조회/저장 도구를 노출하지 않습니다. PlayMCP에 환경변수 입력 기능이 없다면 `secrets.local.json`을 로컬에서만 만들고, private GHCR 이미지에 포함해 배포하세요.

로컬 실행이나 env 입력이 가능한 플랫폼에서는 아래 환경변수로도 설정할 수 있습니다.

```bash
ENABLE_REAL_KAKAO_APIS=true
KAKAO_REST_API_KEY=
KAKAO_MOBILITY_API_KEY=
KAKAO_ACCESS_TOKEN=
KAKAO_CLIENT_SECRET=
KAKAO_REDIRECT_URI=http://127.0.0.1:8000/oauth/kakao/callback
KAKAO_OAUTH_SCOPES=talk_message,talk_calendar
KAKAO_CALENDAR_ID=primary
PUBLIC_BASE_URL=http://127.0.0.1:8000
DAILYROUTE_DB_PATH=data/dailyroute_guard.db
```

- 키 없이 동작: 일정 추출, 일정 저장, 중복 경고, SQLite 저장, 모의 이동시간, 모의 경유지 추천, 경로 감시 로그
- `KAKAO_REST_API_KEY`가 있으면 카카오 OAuth 로그인 URL을 만들 수 있고, 카카오 Local 장소 검색을 실제 API로 시도합니다.
- `KAKAO_MOBILITY_API_KEY`는 비워도 `KAKAO_REST_API_KEY`를 자동차 길찾기 API 키로 사용합니다. 분리 관리하고 싶으면 같은 REST API 키를 `KAKAO_MOBILITY_API_KEY`에도 넣으면 됩니다.
- `KAKAO_REDIRECT_URI`는 카카오 Developers에 등록한 Redirect URI와 정확히 같아야 합니다.
- `KAKAO_CLIENT_SECRET`이 켜져 있는 앱이면 token 발급 때 필요합니다.
- `KAKAO_OAUTH_SCOPES`는 나에게 보내기와 톡캘린더 생성을 위해 `talk_message,talk_calendar`를 권장합니다. 카카오 OAuth `scope`는 쉼표로 구분되며, 카카오 Developers의 동의항목에서 scope ID가 다르게 표시되면 콘솔 값을 기준으로 바꾸세요.
- OAuth 로그인 후 저장된 access token으로 `save_schedule(save_to_talk_calendar=true)`는 톡캘린더 생성 API를, `build_daily_route_briefing(send_to_me=true)`와 route watch 알림은 나에게 보내기 API를 시도합니다.
- `check_day_feasibility`에서 `travel_mode="car"`이면 카카오모빌리티 자동차 길찾기 API로 차량 이동시간을 시도합니다.
- `travel_mode="transit_estimate"` 또는 `walking_estimate`이면 카카오 Local 좌표 조회 후 거리 기반 대중교통/도보 예상시간을 계산합니다. 공개 자동차 길찾기 API와 달리 실시간 대중교통 경로 검색은 아니므로 결과에 provider가 표시됩니다.
- 키가 없거나 API 권한 오류가 나면 fallback 모의 이동시간으로 안전하게 내려갑니다.
- MVP에서는 이미지 OCR을 서버 안에서 직접 수행하지 않습니다. 이미지에서 OCR된 텍스트를 `extract_schedule_from_text`의 `text`에 넣어 테스트하세요.

### 기능별 사용 API

- 일정과 일정 사이 이동시간 검사: 카카오 Local API로 장소 좌표를 찾고, `travel_mode="car"`일 때 카카오모빌리티 `GET /v1/directions` 자동차 길찾기로 예상 소요시간과 거리를 가져옵니다. 결과를 일정 사이 여유시간과 비교해 지각 위험을 판단합니다.
- 회사 → 약국 → 카페 → 집 경유지 추천: 카카오 Local API로 약국/카페 후보를 찾고, 후보 조합을 카카오모빌리티 `POST /v1/waypoints/directions` 다중 경유지 길찾기로 비교해 가장 덜 돌아가는 경로를 추천합니다.
- 약속 1시간 전 교통상황 확인: route watch가 due 상태가 되면 현재 출발지에서 약속 장소까지 `GET /v1/directions`를 다시 호출해 현재 이동시간을 확인합니다. 남은 시간보다 이동시간+버퍼가 크면 경고 로그를 만듭니다.
- 출발 데드라인 계산: 일일 브리핑은 일정 시작 약 1시간 전 출발을 기준으로 카카오모빌리티 `GET /v1/future/directions` 미래 운행 정보 길찾기를 먼저 시도합니다. 실패하면 fallback 이동시간으로 출발 마감 시간을 계산합니다.

### 카카오 로그인 흐름

1. GPT/PlayMCP에서 `health_check`를 호출하면 `kakao_login_url`이 함께 반환됩니다.
2. 사용자가 브라우저에서 `kakao_login_url`을 열면 `/oauth/kakao/login`이 카카오 로그인 페이지로 redirect합니다.
3. 사용자가 로그인/동의하면 카카오가 `/oauth/kakao/callback`으로 authorization code를 보냅니다.
4. 서버가 code를 access token/refresh token으로 교환하고 SQLite에 저장합니다.
5. 이후 같은 `workspace_id`에서 톡캘린더 생성과 나에게 보내기를 실제 API로 시도합니다.

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

기대 결과: API 키가 있으면 차량 이동시간을 실제 길찾기로 시도하고, 키가 없으면 안양에서 강남까지 모의 차량 이동시간 48분이 필요해 지각 위험이 높다고 경고합니다.

### 시나리오 4: 퇴근길 심부름 경유지 추천

입력: 회사에서 집 가는 길에 약국과 카페를 들러야 하는 상황

흐름: `find_places_on_route`

기대 결과: `회사 → 약국 → 카페 → 집` 형태의 추천 경로와 mock 장소 후보가 반환됩니다.

### 시나리오 5: 경로 감시

15:00 강남 미팅을 저장하고 60분 전 경로 감시를 등록합니다.

흐름: `create_route_watch` → `get_route_alerts`

기대 결과: 남은 시간과 차량 이동시간을 비교해 지각 위험이 있으면 `route_check_logs`에 경고가 저장됩니다. API 키가 없으면 모의 차량 이동시간을 사용합니다.
