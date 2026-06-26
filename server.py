from __future__ import annotations

import os
from typing import Literal

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import BaseModel, Field
from starlette.requests import Request
from starlette.responses import JSONResponse

from talkguard_service import (
    DEFAULT_WORKSPACE_ID,
    CommitmentImportance,
    CommitmentStatus,
    CommitmentType,
    RecipientType,
    RoomType,
    SourceType,
    TalkGuardService,
)


SERVICE_NAME = "TalkGuard(톡가드)"
SERVICE_VERSION = "0.6.0"
DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 8000


def _env_int(name: str, default: int) -> int:
    raw_value = os.getenv(name)
    if not raw_value:
        return default
    try:
        return int(raw_value)
    except ValueError:
        return default


service = TalkGuardService()

mcp = FastMCP(
    "TalkGuard",
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


class SaveCommitmentResult(BaseModel):
    saved: bool
    commitment_id: str
    summary: str
    warning: str | None = None


class SaveRoomContextResult(BaseModel):
    saved: bool
    room_name: str
    summary: str


class ExplainConversationContextResult(BaseModel):
    room_name: str
    plain_summary: str
    detected_jargon: list[dict]
    key_requests: list[str]
    reply_should_include: list[str]
    reply_checklist: list[str]
    suggested_reply: str
    risk_note: str


class ExtractCommitmentsResult(BaseModel):
    source_type: str
    extracted_count: int
    saved_count: int
    commitments: list[dict]
    saved_commitment_ids: list[str]
    extracted_text: str
    ocr_engine: str
    warnings: list[str]
    summary: str


class ReviewContextUsed(BaseModel):
    commitment_count: int
    room_context_found: bool
    previous_conversation_found: bool


class ReviewResult(BaseModel):
    risk_level: Literal["low", "medium", "high"]
    final_risk_score: int
    detected_conflicts: list[str]
    evidence: list[str]
    missing_items: list[str]
    safer_message: str
    checklist_before_send: list[str]
    context_used: ReviewContextUsed
    disclaimer: str


class GuardSummaryResult(BaseModel):
    commitments: list[dict]
    room_contexts: list[dict]
    summary: str
    next_risks_to_watch: list[str]


@mcp.tool(
    name="health_check",
    description="Check whether the TalkGuard(톡가드) MCP server is running.",
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
        message="TalkGuard(톡가드) 서버가 정상적으로 실행 중입니다.",
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
    name="save_commitment",
    description="Save a commitment in TalkGuard(톡가드).",
    annotations=ToolAnnotations(
        title="약속 저장",
        readOnlyHint=False,
        destructiveHint=False,
        idempotentHint=False,
        openWorldHint=False,
    ),
)
def save_commitment(
    workspace_id: str = Field(
        default=DEFAULT_WORKSPACE_ID,
        description="워크스페이스 ID입니다. 기본값은 default입니다.",
    ),
    title: str = Field(description="약속 또는 일정 제목입니다."),
    commitment_type: CommitmentType = Field(description="약속 유형입니다."),
    deadline_text: str = Field(default="", description="날짜 또는 마감 표현입니다."),
    time_text: str = Field(default="", description="시간 표현입니다."),
    related_person: str = Field(default="", description="관련 인물입니다."),
    related_room: str = Field(default="", description="관련 대화방 이름입니다."),
    source_type: SourceType = Field(description="약속이 나온 출처 유형입니다."),
    importance: CommitmentImportance = Field(description="약속 중요도입니다."),
    status: CommitmentStatus = Field(description="약속 현재 상태입니다."),
    memo: str = Field(default="", description="보조 메모입니다."),
) -> SaveCommitmentResult:
    return SaveCommitmentResult(
        **service.save_commitment(
            workspace_id=workspace_id,
            title=title,
            commitment_type=commitment_type,
            deadline_text=deadline_text,
            time_text=time_text,
            related_person=related_person,
            related_room=related_room,
            source_type=source_type,
            importance=importance,
            status=status,
            memo=memo,
        )
    )


@mcp.tool(
    name="save_room_context",
    description="Save room context in TalkGuard(톡가드).",
    annotations=ToolAnnotations(
        title="대화 맥락 저장",
        readOnlyHint=False,
        destructiveHint=False,
        idempotentHint=False,
        openWorldHint=False,
    ),
)
def save_room_context(
    workspace_id: str = Field(
        default=DEFAULT_WORKSPACE_ID,
        description="워크스페이스 ID입니다. 기본값은 default입니다.",
    ),
    room_name: str = Field(description="대화방 또는 관계 이름입니다."),
    room_type: RoomType = Field(description="대화방 또는 관계 유형입니다."),
    context: str = Field(description="중요한 대화 맥락입니다."),
    communication_goal: str = Field(default="", description="이 대화의 커뮤니케이션 목표입니다."),
) -> SaveRoomContextResult:
    return SaveRoomContextResult(
        **service.save_room_context(
            workspace_id=workspace_id,
            room_name=room_name,
            room_type=room_type,
            context=context,
            communication_goal=communication_goal,
        )
    )


@mcp.tool(
    name="explain_conversation_context",
    description="Explain difficult previous conversation in plain Korean with TalkGuard(톡가드).",
    annotations=ToolAnnotations(
        title="이전 대화 쉬운 설명",
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    ),
)
def explain_conversation_context(
    conversation_text: str = Field(description="쉬운 설명으로 바꿀 이전 대화 내용입니다."),
    room_name: str = Field(default="", description="관련 대화방 또는 관계 이름입니다."),
    recipient_type: RecipientType | None = Field(
        default=None,
        description="상대 유형입니다. 예시 답장의 말투를 고르는 데 사용합니다.",
    ),
) -> ExplainConversationContextResult:
    return ExplainConversationContextResult(
        **service.explain_conversation_context(
            conversation_text=conversation_text,
            room_name=room_name,
            recipient_type=recipient_type,
        )
    )


@mcp.tool(
    name="extract_commitments_from_text",
    description="Extract schedules and commitments from Korean chat text with TalkGuard(톡가드).",
    annotations=ToolAnnotations(
        title="텍스트 일정 추출",
        readOnlyHint=False,
        destructiveHint=False,
        idempotentHint=False,
        openWorldHint=False,
    ),
)
def extract_commitments_from_text(
    workspace_id: str = Field(
        default=DEFAULT_WORKSPACE_ID,
        description="워크스페이스 ID입니다. 기본값은 default입니다.",
    ),
    source_text: str = Field(description="일정이나 약속을 추출할 카톡방/채팅 텍스트입니다."),
    related_room: str = Field(default="", description="추출된 일정과 연결할 대화방 이름입니다."),
    source_type: SourceType = Field(default="chat", description="텍스트 출처 유형입니다."),
    save_extracted: bool = Field(
        default=False,
        description="true이면 추출된 일정 후보를 바로 약속 DB에 저장합니다.",
    ),
) -> ExtractCommitmentsResult:
    return ExtractCommitmentsResult(
        **service.extract_commitments_from_text(
            workspace_id=workspace_id,
            source_text=source_text,
            related_room=related_room,
            source_type=source_type,
            save_extracted=save_extracted,
        )
    )


@mcp.tool(
    name="extract_commitments_from_image",
    description="Run OCR on a Korean chat image and extract schedules with TalkGuard(톡가드).",
    annotations=ToolAnnotations(
        title="이미지 OCR 일정 추출",
        readOnlyHint=False,
        destructiveHint=False,
        idempotentHint=False,
        openWorldHint=False,
    ),
)
def extract_commitments_from_image(
    workspace_id: str = Field(
        default=DEFAULT_WORKSPACE_ID,
        description="워크스페이스 ID입니다. 기본값은 default입니다.",
    ),
    image_path: str = Field(default="", description="OCR할 이미지 파일 경로입니다."),
    image_base64: str = Field(default="", description="OCR할 이미지 base64 또는 data URL입니다."),
    related_room: str = Field(default="", description="추출된 일정과 연결할 대화방 이름입니다."),
    save_extracted: bool = Field(
        default=False,
        description="true이면 추출된 일정 후보를 바로 약속 DB에 저장합니다.",
    ),
    ocr_language: str = Field(
        default="ko-KR,en-US",
        description="OCR 언어 코드입니다. 기본값은 ko-KR,en-US입니다.",
    ),
    ocr_text: str = Field(
        default="",
        description="이미 클라이언트가 OCR한 텍스트가 있으면 이 값을 사용해 일정만 추출합니다.",
    ),
) -> ExtractCommitmentsResult:
    return ExtractCommitmentsResult(
        **service.extract_commitments_from_image(
            workspace_id=workspace_id,
            image_path=image_path,
            image_base64=image_base64,
            related_room=related_room,
            save_extracted=save_extracted,
            ocr_language=ocr_language,
            ocr_text=ocr_text,
        )
    )


@mcp.tool(
    name="import_calendar_events",
    description="Import ICS calendar events into TalkGuard(톡가드) commitments.",
    annotations=ToolAnnotations(
        title="캘린더 일정 가져오기",
        readOnlyHint=False,
        destructiveHint=False,
        idempotentHint=False,
        openWorldHint=False,
    ),
)
def import_calendar_events(
    workspace_id: str = Field(
        default=DEFAULT_WORKSPACE_ID,
        description="워크스페이스 ID입니다. 기본값은 default입니다.",
    ),
    calendar_text: str = Field(default="", description="가져올 ICS 캘린더 텍스트입니다."),
    calendar_file_path: str = Field(default="", description="가져올 .ics 파일 경로입니다."),
    related_room: str = Field(default="", description="가져온 일정과 연결할 대화방 이름입니다."),
    save_imported: bool = Field(
        default=True,
        description="true이면 가져온 캘린더 일정을 바로 약속 DB에 저장합니다.",
    ),
) -> ExtractCommitmentsResult:
    return ExtractCommitmentsResult(
        **service.import_calendar_events(
            workspace_id=workspace_id,
            calendar_text=calendar_text,
            calendar_file_path=calendar_file_path,
            related_room=related_room,
            save_imported=save_imported,
        )
    )


@mcp.tool(
    name="review_message_before_send",
    description="Review a draft with the PromiseGuard Engine in TalkGuard(톡가드).",
    annotations=ToolAnnotations(
        title="발송 전 점검",
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    ),
)
def review_message_before_send(
    workspace_id: str = Field(
        default=DEFAULT_WORKSPACE_ID,
        description="워크스페이스 ID입니다. 기본값은 default입니다.",
    ),
    draft_message: str = Field(description="발송 전 점검할 메시지 초안입니다."),
    room_name: str = Field(default="", description="관련 대화방 이름입니다."),
    recipient_type: RecipientType | None = Field(
        default=None,
        description="수신자 유형입니다. room_name이 없을 때 톤 점검에 사용됩니다.",
    ),
    extra_context: str = Field(default="", description="추가 반영할 보조 맥락입니다."),
    previous_conversation: str = Field(
        default="",
        description="답장이 이전 대화의 업무지시를 제대로 반영하는지 확인할 때 넣는 이전 대화 원문입니다.",
    ),
) -> ReviewResult:
    return ReviewResult(
        **service.review_message_before_send(
            workspace_id=workspace_id,
            draft_message=draft_message,
            room_name=room_name,
            recipient_type=recipient_type,
            extra_context=extra_context,
            previous_conversation=previous_conversation,
        )
    )


@mcp.tool(
    name="get_guard_summary",
    description="Get a workspace summary from TalkGuard(톡가드).",
    annotations=ToolAnnotations(
        title="가드 요약 조회",
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    ),
)
def get_guard_summary(
    workspace_id: str = Field(
        default=DEFAULT_WORKSPACE_ID,
        description="조회할 워크스페이스 ID입니다. 기본값은 default입니다.",
    ),
) -> GuardSummaryResult:
    return GuardSummaryResult(**service.get_guard_summary(workspace_id))


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
