from __future__ import annotations

import os
from typing import Literal

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import BaseModel, Field
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse

from dailyroute_service import (
    DEFAULT_WORKSPACE_ID,
    DailyRouteService,
    NotifyChannel,
    RoutineType,
    ScheduleType,
    TravelMode,
)


SERVICE_NAME = "DailyRoute Guard(생활동선 캘린더 가드)"
SERVICE_VERSION = "1.0.0"
DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 8000
ExtractScheduleSourceType = Literal["text", "ocr_text", "manual", "other"]
SaveScheduleSourceType = Literal["text", "ocr_text", "manual", "calendar", "other"]
RoutePreferenceTarget = Literal["route_profile", "errand", "routine"]
RoutePreferenceAction = Literal["save", "list"]


def _env_int(name: str, default: int) -> int:
    raw_value = os.getenv(name)
    if not raw_value:
        return default
    try:
        return int(raw_value)
    except ValueError:
        return default


service = DailyRouteService()

mcp = FastMCP(
    "DailyRoute Guard",
    host=os.getenv("HOST", DEFAULT_HOST),
    port=_env_int("PORT", DEFAULT_PORT),
    streamable_http_path="/mcp",
    stateless_http=True,
    json_response=True,
)


class HealthCheckResult(BaseModel):
    status: str
    service: str
    version: str
    message: str
    kakao_auth: dict = Field(default_factory=dict)
    kakao_login_url: str = ""
    oauth_callback_path: str = "/oauth/kakao/callback"


class ExtractScheduleResult(BaseModel):
    extracted_count: int
    schedules: list[dict] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    summary: str


class SaveScheduleResult(BaseModel):
    saved: bool
    schedule_id: str
    schedule: dict = Field(default_factory=dict)
    summary: str
    deduplicated: bool = False
    updated_existing: bool = False
    conflict_detected: bool = False
    conflict_candidates: list[dict] = Field(default_factory=list)
    warning: str | None = None
    talk_calendar_payload: dict = Field(default_factory=dict)
    calendar_result: dict = Field(default_factory=dict)
    calendar_sync_recommended: bool = False
    calendar_prompt: str = ""
    kakao_login_url: str = ""
    route_advice: dict = Field(default_factory=dict)
    errand_route_plan: dict = Field(default_factory=dict)
    auto_route_watch: dict = Field(default_factory=dict)
    next_recommended_action: str


class ListSchedulesResult(BaseModel):
    schedules: list[dict] = Field(default_factory=list)
    summary: str


class UpdateScheduleResult(BaseModel):
    updated: bool
    schedule: dict = Field(default_factory=dict)
    conflict_detected: bool = False
    conflict_candidates: list[dict] = Field(default_factory=list)
    route_advice: dict = Field(default_factory=dict)
    calendar_result: dict = Field(default_factory=dict)
    kakao_login_url: str = ""
    auto_route_watch: dict = Field(default_factory=dict)
    summary: str
    warning: str | None = None


class DeleteScheduleResult(BaseModel):
    deleted: bool
    schedule: dict = Field(default_factory=dict)
    calendar_result: dict = Field(default_factory=dict)
    kakao_login_url: str = ""
    summary: str
    warning: str | None = None


class ConflictCheckResult(BaseModel):
    conflict_detected: bool
    conflict_candidates: list[dict] = Field(default_factory=list)
    summary: str


class DayFeasibilityResult(BaseModel):
    date: str
    feasible: bool
    day_risk_level: Literal["low", "medium", "high"]
    warnings: list[str] = Field(default_factory=list)
    route_checks: list[dict] = Field(default_factory=list)
    impossible_segments: list[dict] = Field(default_factory=list)
    recommended_adjustments: list[str] = Field(default_factory=list)
    summary: str


class PlacesOnRouteResult(BaseModel):
    recommended_route: str
    selected_places: list[dict] = Field(default_factory=list)
    rejected_places: list[dict] = Field(default_factory=list)
    estimated_extra_time: int
    route_evaluation: dict = Field(default_factory=dict)
    warning: str | None = None
    summary: str


class RoutePreferenceToolResult(BaseModel):
    target: str
    action: str
    saved: bool = False
    profile_id: str = ""
    profile: dict = Field(default_factory=dict)
    profiles: list[dict] = Field(default_factory=list)
    errand_id: str = ""
    errand: dict = Field(default_factory=dict)
    errands: list[dict] = Field(default_factory=list)
    routine_id: str = ""
    routine: dict = Field(default_factory=dict)
    routines: list[dict] = Field(default_factory=list)
    summary: str
    how_it_will_be_used: str = ""
    warning: str | None = None


class DailyRouteBriefingResult(BaseModel):
    briefing_title: str
    timeline: list[dict] = Field(default_factory=list)
    departure_deadlines: list[dict] = Field(default_factory=list)
    route_warnings: list[str] = Field(default_factory=list)
    errands_plan: dict = Field(default_factory=dict)
    preparation_checklist: list[str] = Field(default_factory=list)
    message_to_send: str
    sent_to_me: bool
    send_result: dict = Field(default_factory=dict)
    warning: str | None = None
    summary: str


class CreateRouteWatchResult(BaseModel):
    created: bool
    watch_id: str
    summary: str
    next_check_time: str
    warning: str | None = None


class RouteAlertsResult(BaseModel):
    alerts: list[dict] = Field(default_factory=list)
    summary: str


class KakaoCalendarConnectionResult(BaseModel):
    authenticated: bool
    workspace_id: str
    kakao_login_url: str
    pending_local_schedule_count: int = 0
    summary: str
    warning: str | None = None


class TalkCalendarSyncResult(BaseModel):
    synced: bool
    schedule_id: str = ""
    talk_calendar_event_id: str = ""
    calendar_result: dict = Field(default_factory=dict)
    kakao_login_url: str = ""
    summary: str
    warning: str | None = None


def _start_route_watch_scheduler() -> object | None:
    if os.getenv("ENABLE_ROUTE_WATCH_SCHEDULER", "true").lower() in {"0", "false", "no", "off"}:
        return None
    try:
        from apscheduler.schedulers.background import BackgroundScheduler
    except Exception:
        return None

    scheduler = BackgroundScheduler(timezone="Asia/Seoul")
    scheduler.add_job(
        lambda: service.run_due_route_watches(),
        "interval",
        minutes=1,
        id="dailyroute_watch",
        replace_existing=True,
    )
    scheduler.start()
    return scheduler


route_watch_scheduler = _start_route_watch_scheduler()


def _public_base_url_from_request(request: Request) -> str:
    configured = service.runtime_config_value("PUBLIC_BASE_URL", "", DEFAULT_WORKSPACE_ID).rstrip("/")
    if configured:
        return configured
    forwarded_proto = request.headers.get("x-forwarded-proto", request.url.scheme)
    forwarded_host = request.headers.get("x-forwarded-host", request.headers.get("host", "127.0.0.1:8000"))
    return f"{forwarded_proto}://{forwarded_host}".rstrip("/")


def _kakao_redirect_uri_from_request(request: Request) -> str:
    configured = service.runtime_config_value("KAKAO_REDIRECT_URI", "", DEFAULT_WORKSPACE_ID)
    return configured or f"{_public_base_url_from_request(request)}/oauth/kakao/callback"


def _default_kakao_login_url() -> str:
    base_url = service.runtime_config_value("PUBLIC_BASE_URL", "http://127.0.0.1:8000", DEFAULT_WORKSPACE_ID)
    base_url = base_url.rstrip("/")
    return f"{base_url}/oauth/kakao/login?workspace_id={DEFAULT_WORKSPACE_ID}"


@mcp.tool(
    name="health_check",
    description="Check whether DailyRoute Guard MCP server is running.",
    annotations=ToolAnnotations(
        title="서버 상태 확인",
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    ),
)
def health_check() -> HealthCheckResult:
    auth_status = service.kakao_auth_status(DEFAULT_WORKSPACE_ID)
    return HealthCheckResult(
        status="ok",
        service=SERVICE_NAME,
        version=SERVICE_VERSION,
        message="DailyRoute Guard 서버가 정상적으로 실행 중입니다.",
        kakao_auth=auth_status,
        kakao_login_url=auth_status.get("login_url") or _default_kakao_login_url(),
    )


@mcp.custom_route("/health", methods=["GET"], include_in_schema=False)
async def http_health_check(request: Request) -> JSONResponse:
    return JSONResponse(
        {
            "status": "ok",
            "service": SERVICE_NAME,
            "version": SERVICE_VERSION,
            "mcp_endpoint": "/mcp",
        }
    )


@mcp.custom_route("/oauth/kakao/login", methods=["GET"], include_in_schema=False)
async def kakao_oauth_login(request: Request) -> JSONResponse | RedirectResponse:
    workspace_id = request.query_params.get("workspace_id", DEFAULT_WORKSPACE_ID)
    redirect_uri = _kakao_redirect_uri_from_request(request)
    login_result = service.build_kakao_oauth_login_url(workspace_id=workspace_id, redirect_uri=redirect_uri)
    if not login_result.get("configured"):
        return JSONResponse(login_result, status_code=400)
    if request.query_params.get("format") == "json":
        return JSONResponse(
            {
                "login_url": login_result["login_url"],
                "workspace_id": login_result["workspace_id"],
                "redirect_uri": login_result["redirect_uri"],
                "scope": login_result["scope"],
                "message": "이 URL을 브라우저에서 열어 카카오 로그인/동의를 진행하세요.",
            }
        )
    return RedirectResponse(login_result["login_url"], status_code=302)


@mcp.custom_route("/oauth/kakao/callback", methods=["GET"], include_in_schema=False)
async def kakao_oauth_callback(request: Request) -> HTMLResponse | JSONResponse:
    error = request.query_params.get("error", "")
    if error:
        description = request.query_params.get("error_description", "")
        return HTMLResponse(
            f"<h1>카카오 로그인이 취소되었거나 실패했습니다.</h1><p>{error}: {description}</p>",
            status_code=400,
        )
    result = service.complete_kakao_oauth(
        code=request.query_params.get("code", ""),
        state=request.query_params.get("state", ""),
        redirect_uri=_kakao_redirect_uri_from_request(request),
    )
    if request.query_params.get("format") == "json":
        return JSONResponse(result, status_code=200 if result.get("success") else 400)
    if result.get("success"):
        backfill = result.get("calendar_backfill", {})
        return HTMLResponse(
            f"""
            <h1>DailyRoute Guard 카카오 연동 완료</h1>
            <p>토큰이 저장되었습니다. 사용자 워크스페이스: {result.get("workspace_id", "")}</p>
            <p>기존 로컬 일정 {backfill.get("attempted", 0)}건 중 {backfill.get("synced", 0)}건을 톡캘린더와 자동 동기화했습니다.</p>
            <p>이제 GPT/PlayMCP에서 일정 저장 또는 브리핑 전송을 다시 실행하세요.</p>
            <p>이 창은 닫아도 됩니다.</p>
            """
        )
    return HTMLResponse(
        f"<h1>DailyRoute Guard 카카오 연동 실패</h1><pre>{result}</pre>",
        status_code=400,
    )


@mcp.tool(
    name="extract_schedule_from_text",
    description="Extract schedule candidates from plain text or OCR text.",
    annotations=ToolAnnotations(
        title="텍스트 일정 추출",
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    ),
)
def extract_schedule_from_text(
    workspace_id: str = Field(default=DEFAULT_WORKSPACE_ID, description="워크스페이스 ID입니다. 기본값은 default입니다."),
    text: str = Field(description="일정을 추출할 일반 텍스트 또는 OCR 텍스트입니다."),
    source_type: ExtractScheduleSourceType = Field(default="text", description="텍스트 출처입니다. text, ocr_text, manual, other 중 하나입니다."),
    default_timezone: str = Field(default="Asia/Seoul", description="기본 시간대입니다."),
    reference_date: str = Field(default="", description="내일, 이번 주 금요일 같은 표현을 해석할 기준 날짜입니다. YYYY-MM-DD 형식입니다."),
    image_base64: str = Field(default="", description="MVP에서는 사용하지 않습니다. 이미지 OCR 결과 텍스트를 text에 넣어 주세요."),
    image_url: str = Field(default="", description="MVP에서는 사용하지 않습니다. 이미지 OCR 결과 텍스트를 text에 넣어 주세요."),
) -> ExtractScheduleResult:
    return ExtractScheduleResult(
        **service.extract_schedule_from_text(
            workspace_id=workspace_id,
            text=text,
            source_type=source_type,
            default_timezone=default_timezone,
            reference_date=reference_date,
            image_base64=image_base64,
            image_url=image_url,
        )
    )


@mcp.tool(
    name="save_schedule",
    description="Save a schedule to local DB and optionally prepare Talk Calendar creation payload.",
    annotations=ToolAnnotations(
        title="일정 저장",
        readOnlyHint=False,
        destructiveHint=False,
        idempotentHint=False,
        openWorldHint=False,
    ),
)
def save_schedule(
    workspace_id: str = Field(default=DEFAULT_WORKSPACE_ID, description="워크스페이스 ID입니다. 기본값은 default입니다."),
    title: str = Field(description="저장할 일정 제목입니다."),
    start_at: str = Field(default="", description="ISO 형식 시작 시각입니다. 예: 2026-06-27T15:00:00+09:00"),
    end_at: str = Field(default="", description="ISO 형식 종료 시각입니다. 비우면 유형별 기본 길이를 추정합니다."),
    date_text: str = Field(default="", description="내일, 7월 1일 같은 날짜 표현입니다."),
    time_text: str = Field(default="", description="오후 3시, 15:00 같은 시간 표현입니다."),
    location_text: str = Field(default="", description="일정 장소입니다."),
    schedule_type: ScheduleType = Field(default="other", description="일정 유형입니다."),
    source_type: SaveScheduleSourceType = Field(default="manual", description="일정 출처입니다."),
    reminder_minutes: int = Field(default=60, description="일정 전 알림 분 단위입니다."),
    save_to_talk_calendar: bool = Field(default=False, description="true이면 톡캘린더 생성 payload를 함께 만듭니다."),
    allow_conflict: bool = Field(default=False, description="true이면 겹치는 일정이 있어도 저장합니다."),
    raw_text: str = Field(default="", description="원본 입력 텍스트입니다."),
    notes: str = Field(default="", description="일정 메모입니다."),
) -> SaveScheduleResult:
    return SaveScheduleResult(
        **service.save_schedule(
            workspace_id=workspace_id,
            title=title,
            start_at=start_at,
            end_at=end_at,
            date_text=date_text,
            time_text=time_text,
            location_text=location_text,
            schedule_type=schedule_type,
            source_type=source_type,
            reminder_minutes=reminder_minutes,
            save_to_talk_calendar=save_to_talk_calendar,
            allow_conflict=allow_conflict,
            raw_text=raw_text,
            notes=notes,
        )
    )


@mcp.tool(
    name="list_schedules",
    description="List schedules saved in the current workspace without exposing other workspaces.",
    annotations=ToolAnnotations(
        title="일정 목록 조회",
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    ),
)
def list_schedules(
    workspace_id: str = Field(default=DEFAULT_WORKSPACE_ID, description="워크스페이스 ID입니다. 사용자별로 다른 값을 쓰면 일정이 섞이지 않습니다."),
    date: str = Field(default="", description="조회할 날짜입니다. YYYY-MM-DD 형식입니다. 비우면 최근 일정을 조회합니다."),
    limit: int = Field(default=50, description="조회할 최대 일정 수입니다."),
) -> ListSchedulesResult:
    return ListSchedulesResult(**service.list_schedules(workspace_id=workspace_id, date_text=date, limit=limit))


@mcp.tool(
    name="update_schedule",
    description="Update one schedule in the current workspace and re-check route feasibility.",
    annotations=ToolAnnotations(
        title="일정 수정",
        readOnlyHint=False,
        destructiveHint=False,
        idempotentHint=False,
        openWorldHint=False,
    ),
)
def update_schedule(
    workspace_id: str = Field(default=DEFAULT_WORKSPACE_ID, description="워크스페이스 ID입니다. 이 값이 같은 일정만 수정합니다."),
    schedule_id: str = Field(description="수정할 일정 ID입니다."),
    title: str = Field(default="", description="새 일정 제목입니다. 비우면 유지합니다."),
    start_at: str = Field(default="", description="새 시작 시각입니다. ISO 형식입니다."),
    end_at: str = Field(default="", description="새 종료 시각입니다. ISO 형식입니다."),
    date_text: str = Field(default="", description="새 날짜 표현입니다."),
    time_text: str = Field(default="", description="새 시간 표현입니다."),
    location_text: str = Field(default="", description="새 장소입니다."),
    notes: str = Field(default="", description="새 메모입니다."),
    allow_conflict: bool = Field(default=False, description="true이면 겹치는 일정이 있어도 수정합니다."),
) -> UpdateScheduleResult:
    return UpdateScheduleResult(
        **service.update_schedule(
            workspace_id=workspace_id,
            schedule_id=schedule_id,
            title=title,
            start_at=start_at,
            end_at=end_at,
            date_text=date_text,
            time_text=time_text,
            location_text=location_text,
            notes=notes,
            allow_conflict=allow_conflict,
        )
    )


@mcp.tool(
    name="delete_schedule",
    description="Delete one schedule from the current workspace.",
    annotations=ToolAnnotations(
        title="일정 삭제",
        readOnlyHint=False,
        destructiveHint=True,
        idempotentHint=False,
        openWorldHint=False,
    ),
)
def delete_schedule(
    workspace_id: str = Field(default=DEFAULT_WORKSPACE_ID, description="워크스페이스 ID입니다. 이 값이 같은 일정만 삭제합니다."),
    schedule_id: str = Field(description="삭제할 일정 ID입니다."),
) -> DeleteScheduleResult:
    return DeleteScheduleResult(**service.delete_schedule(workspace_id=workspace_id, schedule_id=schedule_id))


@mcp.tool(
    name="check_conflict",
    description="Check whether a proposed schedule conflicts with existing schedules in the same workspace.",
    annotations=ToolAnnotations(
        title="일정 충돌 확인",
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    ),
)
def check_conflict(
    workspace_id: str = Field(default=DEFAULT_WORKSPACE_ID, description="워크스페이스 ID입니다. 이 값이 같은 일정만 비교합니다."),
    title: str = Field(description="확인할 일정 제목입니다."),
    start_at: str = Field(default="", description="확인할 시작 시각입니다. ISO 형식입니다."),
    end_at: str = Field(default="", description="확인할 종료 시각입니다. 비우면 기본 길이를 추정합니다."),
    date_text: str = Field(default="", description="내일, 7월 1일 같은 날짜 표현입니다."),
    time_text: str = Field(default="", description="오후 3시, 15:00 같은 시간 표현입니다."),
    location_text: str = Field(default="", description="일정 장소입니다."),
) -> ConflictCheckResult:
    return ConflictCheckResult(
        **service.check_schedule_conflict(
            workspace_id=workspace_id,
            title=title,
            start_at=start_at,
            end_at=end_at,
            date_text=date_text,
            time_text=time_text,
            location_text=location_text,
        )
    )


@mcp.tool(
    name="connect_kakao_calendar",
    description="Return Kakao calendar connection status and a login URL when authorization is needed.",
    annotations=ToolAnnotations(
        title="카카오 캘린더 연결",
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=True,
    ),
)
def connect_kakao_calendar(
    workspace_id: str = Field(default=DEFAULT_WORKSPACE_ID, description="워크스페이스 ID입니다. 사용자별 토큰을 분리합니다."),
) -> KakaoCalendarConnectionResult:
    return KakaoCalendarConnectionResult(**service.connect_kakao_calendar(workspace_id=workspace_id))


@mcp.tool(
    name="sync_to_talk_calendar",
    description="Sync one saved schedule to Talk Calendar using the workspace's Kakao OAuth token.",
    annotations=ToolAnnotations(
        title="톡캘린더 동기화",
        readOnlyHint=False,
        destructiveHint=False,
        idempotentHint=False,
        openWorldHint=True,
    ),
)
def sync_to_talk_calendar(
    workspace_id: str = Field(default=DEFAULT_WORKSPACE_ID, description="워크스페이스 ID입니다. 사용자별 토큰을 분리합니다."),
    schedule_id: str = Field(description="톡캘린더에 동기화할 일정 ID입니다."),
) -> TalkCalendarSyncResult:
    return TalkCalendarSyncResult(**service.sync_schedule_to_talk_calendar(workspace_id=workspace_id, schedule_id=schedule_id))


@mcp.tool(
    name="check_day_feasibility",
    description="Check whether schedules on a given day are feasible considering travel time.",
    annotations=ToolAnnotations(
        title="하루 동선 가능성 확인",
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=True,
    ),
)
def check_day_feasibility(
    workspace_id: str = Field(default=DEFAULT_WORKSPACE_ID, description="워크스페이스 ID입니다. 기본값은 default입니다."),
    date: str = Field(description="확인할 날짜입니다. YYYY-MM-DD 형식입니다."),
    default_origin: str = Field(default="", description="장소가 비어 있을 때 사용할 기본 출발지입니다."),
    travel_mode: TravelMode = Field(default="car", description="이동 방식입니다. 현재는 car만 지원합니다."),
    buffer_minutes: int = Field(default=15, description="이동 시간 외에 추가로 둘 여유 시간입니다."),
) -> DayFeasibilityResult:
    return DayFeasibilityResult(
        **service.check_day_feasibility(
            workspace_id=workspace_id,
            target_date=date,
            default_origin=default_origin,
            travel_mode=travel_mode,
            buffer_minutes=buffer_minutes,
        )
    )


@mcp.tool(
    name="find_places_on_route",
    description="Find useful places on or near a route for errands such as pharmacy, cafe, or print shop.",
    annotations=ToolAnnotations(
        title="동선 중 경유지 추천",
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=True,
    ),
)
def find_places_on_route(
    workspace_id: str = Field(default=DEFAULT_WORKSPACE_ID, description="워크스페이스 ID입니다. 기본값은 default입니다."),
    origin: str = Field(description="출발지입니다."),
    destination: str = Field(description="도착지입니다."),
    errands: list[str] = Field(default_factory=list, description="처리할 심부름 목록입니다. 예: 약국 들르기, 카페 들르기"),
    max_detour_minutes: int = Field(default=15, description="허용할 최대 우회 시간입니다."),
    preferred_area: str = Field(default="", description="선호 지역입니다."),
) -> PlacesOnRouteResult:
    return PlacesOnRouteResult(
        **service.find_places_on_route(
            workspace_id=workspace_id,
            origin=origin,
            destination=destination,
            errands=errands,
            max_detour_minutes=max_detour_minutes,
            preferred_area=preferred_area,
        )
    )


@mcp.tool(
    name="manage_route_preferences",
    description="Save or list route profiles, errands, and daily-life routines.",
    annotations=ToolAnnotations(
        title="동선 선호 저장/조회",
        readOnlyHint=False,
        destructiveHint=False,
        idempotentHint=False,
        openWorldHint=False,
    ),
)
def manage_route_preferences(
    target: RoutePreferenceTarget = Field(description="관리할 대상입니다. route_profile, errand, routine 중 하나입니다."),
    action: RoutePreferenceAction = Field(description="수행할 작업입니다. save 또는 list입니다."),
    workspace_id: str = Field(default=DEFAULT_WORKSPACE_ID, description="워크스페이스 ID입니다. 기본값은 default입니다."),
    profile_name: str = Field(default="", description="route_profile 저장 시 사용할 동선 프로필 이름입니다."),
    errand_text: str = Field(default="", description="errand 저장 시 사용할 심부름 내용입니다."),
    category: str = Field(default="", description="errand 카테고리입니다. 비우면 내용에서 자동 추정합니다."),
    preferred_area: str = Field(default="", description="errand 선호 지역입니다."),
    routine_name: str = Field(default="", description="routine 저장 시 사용할 루틴 이름입니다."),
    routine_type: RoutineType = Field(default="custom", description="루틴 유형입니다."),
    rule_text: str = Field(default="", description="routine 규칙 설명입니다."),
    active_days: list[str] = Field(default_factory=list, description="활성 요일입니다. 예: mon, wed, fri"),
    origin: str = Field(default="", description="기본 출발지입니다."),
    destination: str = Field(default="", description="기본 도착지입니다."),
    preferred_buffer_minutes: int | None = Field(default=None, description="선호 여유 시간입니다."),
    avoid_conditions: list[str] = Field(default_factory=list, description="피하고 싶은 조건입니다."),
    preferences: dict = Field(default_factory=dict, description="route_profile 선호 조건입니다."),
    limit: int = Field(default=20, description="list 작업에서 조회할 최대 개수입니다."),
) -> RoutePreferenceToolResult:
    workspace_id = workspace_id if isinstance(workspace_id, str) else DEFAULT_WORKSPACE_ID
    profile_name = profile_name if isinstance(profile_name, str) else ""
    errand_text = errand_text if isinstance(errand_text, str) else ""
    category = category if isinstance(category, str) else ""
    preferred_area = preferred_area if isinstance(preferred_area, str) else ""
    routine_name = routine_name if isinstance(routine_name, str) else ""
    routine_type = routine_type if isinstance(routine_type, str) else "custom"
    rule_text = rule_text if isinstance(rule_text, str) else ""
    origin = origin if isinstance(origin, str) else ""
    destination = destination if isinstance(destination, str) else ""
    active_days = active_days if isinstance(active_days, list) else []
    avoid_conditions = avoid_conditions if isinstance(avoid_conditions, list) else []
    preferences = preferences if isinstance(preferences, dict) else {}
    preferred_buffer_minutes = preferred_buffer_minutes if isinstance(preferred_buffer_minutes, int) else None
    limit = limit if isinstance(limit, int) else 20

    if target == "route_profile":
        if action == "save":
            if not profile_name:
                return RoutePreferenceToolResult(target=target, action=action, summary="동선 프로필 이름이 필요합니다.", warning="profile_name을 입력해 주세요.")
            route_preferences = dict(preferences)
            if preferred_buffer_minutes is not None:
                route_preferences["buffer_minutes"] = preferred_buffer_minutes
            if avoid_conditions:
                route_preferences["avoid_options"] = avoid_conditions
            if origin and not route_preferences.get("home_location"):
                route_preferences["home_location"] = origin
            return RoutePreferenceToolResult(
                target=target,
                action=action,
                **service.save_route_profile(
                    workspace_id=workspace_id,
                    profile_name=profile_name,
                    origin=origin,
                    destination=destination,
                    preferences=route_preferences,
                ),
            )
        return RoutePreferenceToolResult(
            target=target,
            action=action,
            **service.list_route_profiles(workspace_id=workspace_id, limit=limit),
        )
    if target == "errand":
        if action == "save":
            if not errand_text:
                return RoutePreferenceToolResult(target=target, action=action, summary="심부름 내용이 필요합니다.", warning="errand_text를 입력해 주세요.")
            return RoutePreferenceToolResult(
                target=target,
                action=action,
                **service.save_errand(
                    workspace_id=workspace_id,
                    errand_text=errand_text,
                    category=category,
                    preferred_area=preferred_area,
                ),
            )
        return RoutePreferenceToolResult(
            target=target,
            action=action,
            **service.list_errands(workspace_id=workspace_id, limit=limit),
        )
    if action == "save":
        if not routine_name or not rule_text:
            return RoutePreferenceToolResult(target=target, action=action, summary="루틴 이름과 규칙 설명이 필요합니다.", warning="routine_name과 rule_text를 입력해 주세요.")
        return RoutePreferenceToolResult(
            target=target,
            action=action,
            **service.save_routine(
                workspace_id=workspace_id,
                routine_name=routine_name,
                routine_type=routine_type,
                rule_text=rule_text,
                active_days=active_days,
                origin=origin,
                destination=destination,
                preferred_buffer_minutes=preferred_buffer_minutes,
                avoid_conditions=avoid_conditions,
            ),
        )
    return RoutePreferenceToolResult(
        target=target,
        action=action,
        **service.list_routines(workspace_id=workspace_id, limit=limit),
    )


@mcp.tool(
    name="build_daily_route_briefing",
    description="Create a daily route briefing using saved schedules, routines, errands, and route feasibility.",
    annotations=ToolAnnotations(
        title="일일 동선 브리핑",
        readOnlyHint=False,
        destructiveHint=False,
        idempotentHint=False,
        openWorldHint=True,
    ),
)
def build_daily_route_briefing(
    workspace_id: str = Field(default=DEFAULT_WORKSPACE_ID, description="워크스페이스 ID입니다. 기본값은 default입니다."),
    date: str = Field(description="브리핑할 날짜입니다. YYYY-MM-DD 형식입니다."),
    start_location: str = Field(default="", description="하루 시작 위치입니다."),
    end_location: str = Field(default="", description="하루 종료 위치입니다."),
    extra_errands: list[str] = Field(default_factory=list, description="추가로 처리할 심부름 목록입니다."),
    send_to_me: bool = Field(default=False, description="true이면 나에게 보내기 연동을 시도합니다."),
) -> DailyRouteBriefingResult:
    return DailyRouteBriefingResult(
        **service.build_daily_route_briefing(
            workspace_id=workspace_id,
            target_date=date,
            start_location=start_location,
            end_location=end_location,
            extra_errands=extra_errands,
            send_to_me=send_to_me,
        )
    )


@mcp.tool(
    name="create_route_watch",
    description="Register a route watch job that checks travel time before an appointment.",
    annotations=ToolAnnotations(
        title="경로 감시 등록",
        readOnlyHint=False,
        destructiveHint=False,
        idempotentHint=False,
        openWorldHint=True,
    ),
)
def create_route_watch(
    workspace_id: str = Field(default=DEFAULT_WORKSPACE_ID, description="워크스페이스 ID입니다. 기본값은 default입니다."),
    schedule_id: str = Field(description="감시할 일정 ID입니다."),
    origin: str = Field(description="해당 일정으로 출발할 위치입니다."),
    check_minutes_before: int = Field(default=60, description="일정 시작 몇 분 전에 확인할지 설정합니다."),
    buffer_minutes: int = Field(default=15, description="이동 외에 둘 여유 시간입니다."),
    notify_channel: NotifyChannel = Field(default="log_only", description="알림 채널입니다. kakao_me 또는 log_only입니다."),
) -> CreateRouteWatchResult:
    return CreateRouteWatchResult(
        **service.create_route_watch(
            workspace_id=workspace_id,
            schedule_id=schedule_id,
            origin=origin,
            check_minutes_before=check_minutes_before,
            buffer_minutes=buffer_minutes,
            notify_channel=notify_channel,
        )
    )


@mcp.tool(
    name="get_route_alerts",
    description="Return recent route watch alerts and warnings.",
    annotations=ToolAnnotations(
        title="경로 경고 조회",
        readOnlyHint=False,
        destructiveHint=False,
        idempotentHint=False,
        openWorldHint=True,
    ),
)
def get_route_alerts(
    workspace_id: str = Field(default=DEFAULT_WORKSPACE_ID, description="워크스페이스 ID입니다. 기본값은 default입니다."),
    limit: int = Field(default=10, description="조회할 최대 경고 개수입니다."),
) -> RouteAlertsResult:
    return RouteAlertsResult(**service.get_route_alerts(workspace_id=workspace_id, limit=limit))


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
