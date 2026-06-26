from __future__ import annotations

import os
from typing import Literal

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import BaseModel, Field
from starlette.requests import Request
from starlette.responses import JSONResponse

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


class ExtractScheduleResult(BaseModel):
    extracted_count: int
    schedules: list[dict] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    summary: str


class SaveScheduleResult(BaseModel):
    saved: bool
    schedule_id: str
    summary: str
    conflict_detected: bool = False
    conflict_candidates: list[dict] = Field(default_factory=list)
    warning: str | None = None
    talk_calendar_payload: dict = Field(default_factory=dict)
    next_recommended_action: str


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
    warning: str | None = None
    summary: str


class SaveRoutineResult(BaseModel):
    saved: bool
    routine_id: str
    summary: str
    how_it_will_be_used: str


class DailyRouteBriefingResult(BaseModel):
    briefing_title: str
    timeline: list[dict] = Field(default_factory=list)
    departure_deadlines: list[dict] = Field(default_factory=list)
    route_warnings: list[str] = Field(default_factory=list)
    errands_plan: dict = Field(default_factory=dict)
    preparation_checklist: list[str] = Field(default_factory=list)
    message_to_send: str
    sent_to_me: bool
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
    return HealthCheckResult(
        status="ok",
        service=SERVICE_NAME,
        version=SERVICE_VERSION,
        message="DailyRoute Guard 서버가 정상적으로 실행 중입니다.",
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
        )
    )


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
    travel_mode: TravelMode = Field(default="car", description="이동 방식입니다."),
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
    name="save_routine",
    description="Save daily-life route routines and preferences.",
    annotations=ToolAnnotations(
        title="생활 루틴 저장",
        readOnlyHint=False,
        destructiveHint=False,
        idempotentHint=False,
        openWorldHint=False,
    ),
)
def save_routine(
    workspace_id: str = Field(default=DEFAULT_WORKSPACE_ID, description="워크스페이스 ID입니다. 기본값은 default입니다."),
    routine_name: str = Field(description="루틴 이름입니다."),
    routine_type: RoutineType = Field(default="custom", description="루틴 유형입니다."),
    rule_text: str = Field(description="루틴 규칙 설명입니다."),
    active_days: list[str] = Field(default_factory=list, description="활성 요일입니다. 예: mon, wed, fri"),
    origin: str = Field(default="", description="기본 출발지입니다."),
    destination: str = Field(default="", description="기본 도착지입니다."),
    preferred_buffer_minutes: int | None = Field(default=None, description="선호 여유 시간입니다."),
    avoid_conditions: list[str] = Field(default_factory=list, description="피하고 싶은 조건입니다."),
) -> SaveRoutineResult:
    return SaveRoutineResult(
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
        )
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
