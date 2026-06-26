from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from talkguard_service import TalkGuardService


def build_service(tmp_path: Path) -> TalkGuardService:
    return TalkGuardService(tmp_path / "talkguard-test.db")


def test_deadline_conflict_demo(tmp_path: Path) -> None:
    service = build_service(tmp_path)

    service.save_commitment(
        workspace_id="default",
        title="금요일까지 데모 영상 공유",
        commitment_type="deadline",
        deadline_text="금요일",
        time_text="",
        related_person="팀장",
        related_room="공모전 팀방",
        source_type="chat",
        importance="high",
        status="planned",
        memo="",
    )

    result = service.review_message_before_send(
        workspace_id="default",
        draft_message="다음 주에 데모 영상 정리해서 보내드리겠습니다.",
        room_name="공모전 팀방",
        recipient_type="team",
        extra_context="",
    )

    assert result["risk_level"] == "high"
    assert result["final_risk_score"] >= 70
    assert any("마감 약속 충돌" in issue for issue in result["detected_conflicts"])
    assert "금요일까지 데모 영상 초안을 먼저 공유드리고" in result["safer_message"]


def test_missing_commitment_demo(tmp_path: Path) -> None:
    service = build_service(tmp_path)

    service.save_room_context(
        workspace_id="default",
        room_name="공모전 팀방",
        room_type="team",
        context="팀장은 금요일까지 데모 영상을 원하고, 데모 영상 공유 여부를 중요하게 확인합니다.",
        communication_goal="데모 영상 공유 여부를 분명하게 말하기",
    )

    result = service.review_message_before_send(
        workspace_id="default",
        draft_message="오늘 기능 정리해서 공유드리겠습니다.",
        room_name="공모전 팀방",
        recipient_type="team",
        extra_context="",
    )

    assert result["risk_level"] == "medium"
    assert any("중요 항목 누락 가능성" in issue for issue in result["detected_conflicts"])
    assert any("데모 영상" in item for item in result["missing_items"])
    assert "데모 영상 관련 일정과 범위도 함께 분명히 말씀드리겠습니다." in result["safer_message"]


def test_schedule_conflict_demo(tmp_path: Path) -> None:
    service = build_service(tmp_path)

    service.save_commitment(
        workspace_id="default",
        title="내일 오후 3시 팀 회의",
        commitment_type="meeting",
        deadline_text="내일",
        time_text="오후 3시",
        related_person="",
        related_room="공모전 팀방",
        source_type="calendar",
        importance="high",
        status="planned",
        memo="",
    )

    result = service.review_message_before_send(
        workspace_id="default",
        draft_message="내일 오후 3시에 가능합니다.",
        room_name="공모전 팀방",
        recipient_type="client",
        extra_context="",
    )

    assert result["risk_level"] == "high"
    assert any("일정 충돌" in issue for issue in result["detected_conflicts"])
    assert "내일 오후 3시는 기존 일정이 있어 어렵고" in result["safer_message"]
    assert "오후 5시 이후" in result["safer_message"]


def test_low_risk_message_when_no_conflict_exists(tmp_path: Path) -> None:
    service = build_service(tmp_path)

    service.save_commitment(
        workspace_id="default",
        title="금요일까지 데모 영상 공유",
        commitment_type="deadline",
        deadline_text="금요일",
        time_text="",
        related_person="팀장",
        related_room="공모전 팀방",
        source_type="chat",
        importance="high",
        status="planned",
        memo="",
    )

    result = service.review_message_before_send(
        workspace_id="default",
        draft_message="금요일까지 데모 영상 초안을 먼저 공유드리겠습니다.",
        room_name="공모전 팀방",
        recipient_type="team",
        extra_context="",
    )

    assert result["risk_level"] == "low"
    assert result["final_risk_score"] == 10
    assert result["detected_conflicts"] == ["뚜렷한 충돌 신호는 발견되지 않았습니다."]


def test_deadline_conflict_handles_no_space_relative_date(tmp_path: Path) -> None:
    service = build_service(tmp_path)

    service.save_commitment(
        workspace_id="default",
        title="금요일까지 데모 영상 공유",
        commitment_type="deadline",
        deadline_text="금요일",
        time_text="",
        related_person="팀장",
        related_room="공모전 팀방",
        source_type="chat",
        importance="high",
        status="planned",
        memo="",
    )

    result = service.review_message_before_send(
        workspace_id="default",
        draft_message="다음주에 데모 영상 정리해서 보내드리겠습니다.",
        room_name="공모전 팀방",
        recipient_type="team",
        extra_context="",
    )

    assert result["risk_level"] == "high"
    assert any("마감 약속 충돌" in issue for issue in result["detected_conflicts"])
    assert not any("다음주에로" in issue for issue in result["detected_conflicts"])
    assert any("다음주로" in issue for issue in result["detected_conflicts"])


def test_save_commitment_warns_when_time_is_not_parseable(tmp_path: Path) -> None:
    service = build_service(tmp_path)

    result = service.save_commitment(
        workspace_id="default",
        title="금요일까지 데모 영상 공유",
        commitment_type="deadline",
        deadline_text="금요일",
        time_text="메롱",
        related_person="팀장",
        related_room="공모전 팀방",
        source_type="chat",
        importance="high",
        status="planned",
        memo="",
    )

    assert result["saved"] is True
    assert result["warning"] is not None
    assert "시간 표현을 해석하지 못했습니다" in result["warning"]


def test_save_commitment_warns_when_deadline_is_not_parseable(tmp_path: Path) -> None:
    service = build_service(tmp_path)

    result = service.save_commitment(
        workspace_id="default",
        title="데모 영상 공유",
        commitment_type="deadline",
        deadline_text="메롱",
        time_text="",
        related_person="팀장",
        related_room="공모전 팀방",
        source_type="chat",
        importance="high",
        status="planned",
        memo="",
    )

    assert result["saved"] is True
    assert result["warning"] is not None
    assert "날짜 표현을 해석하지 못했습니다" in result["warning"]


def test_explain_conversation_context_plainifies_pangyo_jargon(tmp_path: Path) -> None:
    service = build_service(tmp_path)

    result = service.explain_conversation_context(
        conversation_text="QA 리스크랑 데모 일정 얼라인해서 EOD까지 공유해 주세요.",
        room_name="공모전 팀방",
        recipient_type="team",
    )

    assert "쉽게 말하면" in result["plain_summary"]
    assert any(jargon["term"] == "리스크" for jargon in result["detected_jargon"])
    assert any(jargon["term"] == "얼라인" for jargon in result["detected_jargon"])
    assert any(jargon["term"] == "EOD" for jargon in result["detected_jargon"])
    assert "리스크" in result["reply_should_include"]
    assert "데모" in result["reply_should_include"]
    assert "오늘 업무 끝 전까지" in result["reply_should_include"]
    assert "오늘 업무 끝 전까지까지" not in result["plain_summary"]


def test_review_message_checks_previous_conversation_alignment(tmp_path: Path) -> None:
    service = build_service(tmp_path)

    result = service.review_message_before_send(
        workspace_id="default",
        draft_message="확인했습니다.",
        room_name="공모전 팀방",
        recipient_type="team",
        extra_context="",
        previous_conversation="QA 리스크랑 데모 일정 얼라인해서 EOD까지 공유해 주세요.",
    )

    assert result["risk_level"] == "medium"
    assert any("이전 대화 답변 누락 가능성" in issue for issue in result["detected_conflicts"])
    assert "리스크" in result["missing_items"]
    assert "데모" in result["missing_items"]
    assert result["context_used"]["previous_conversation_found"] is True


def test_extract_commitments_from_text_can_save_and_feed_review(tmp_path: Path) -> None:
    service = build_service(tmp_path)

    extraction = service.extract_commitments_from_text(
        workspace_id="default",
        source_text="금요일까지 데모 영상 공유\n내일 오후 3시 팀 회의",
        related_room="공모전 팀방",
        source_type="chat",
        save_extracted=True,
    )

    assert extraction["extracted_count"] == 2
    assert extraction["saved_count"] == 2
    assert any(item["commitment_type"] == "deadline" for item in extraction["commitments"])
    assert any(item["commitment_type"] == "meeting" for item in extraction["commitments"])

    review = service.review_message_before_send(
        workspace_id="default",
        draft_message="다음 주에 데모 영상 정리해서 보내드리겠습니다.",
        room_name="공모전 팀방",
        recipient_type="team",
        extra_context="",
    )

    assert review["risk_level"] == "high"
    assert any("마감 약속 충돌" in issue for issue in review["detected_conflicts"])


def test_extract_commitments_from_image_uses_provided_ocr_text(tmp_path: Path) -> None:
    service = build_service(tmp_path)

    result = service.extract_commitments_from_image(
        workspace_id="default",
        related_room="공모전 팀방",
        save_extracted=False,
        ocr_text="7월 1일 오후 3시 고객 미팅",
    )

    assert result["ocr_engine"] == "provided_text"
    assert result["extracted_count"] == 1
    assert result["commitments"][0]["deadline_text"] == "7월 1일"
    assert result["commitments"][0]["time_text"] == "오후 3시"
    assert result["commitments"][0]["source_type"] == "ocr"


def test_import_calendar_events_can_feed_schedule_conflict(tmp_path: Path) -> None:
    service = build_service(tmp_path)
    calendar_text = """BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VEVENT
UID:event-1
SUMMARY:고객 미팅
DTSTART;TZID=Asia/Seoul:20260701T150000
DTEND;TZID=Asia/Seoul:20260701T160000
LOCATION:판교
DESCRIPTION:고객사와 데모 범위 논의
END:VEVENT
END:VCALENDAR
"""

    imported = service.import_calendar_events(
        workspace_id="default",
        calendar_text=calendar_text,
        related_room="고객방",
        save_imported=True,
    )

    assert imported["extracted_count"] == 1
    assert imported["saved_count"] == 1
    assert imported["commitments"][0]["source_type"] == "calendar"
    assert imported["commitments"][0]["deadline_text"] == "2026-07-01"
    assert imported["commitments"][0]["time_text"] == "오후 3시"

    review = service.review_message_before_send(
        workspace_id="default",
        draft_message="7월 1일 오후 3시에 가능합니다.",
        room_name="고객방",
        recipient_type="client",
        extra_context="",
    )

    assert review["risk_level"] == "high"
    assert any("일정 충돌" in issue for issue in review["detected_conflicts"])


def test_schedule_conflict_matches_equivalent_date_formats(tmp_path: Path) -> None:
    service = build_service(tmp_path)

    service.save_commitment(
        workspace_id="default",
        title="고객 미팅",
        commitment_type="meeting",
        deadline_text="2026-07-01",
        time_text="오후 3시",
        related_person="고객사",
        related_room="고객방",
        source_type="calendar",
        importance="high",
        status="planned",
        memo="",
    )

    result = service.review_message_before_send(
        workspace_id="default",
        draft_message="7월 1일 오후 3시에 가능합니다.",
        room_name="고객방",
        recipient_type="client",
        extra_context="",
    )

    assert result["risk_level"] == "high"
    assert any("일정 충돌" in issue for issue in result["detected_conflicts"])


def test_extra_context_can_satisfy_missing_item(tmp_path: Path) -> None:
    service = build_service(tmp_path)

    service.save_room_context(
        workspace_id="default",
        room_name="공모전 팀방",
        room_type="team",
        context="팀장은 데모 영상을 중요하게 확인합니다.",
        communication_goal="데모 영상 공유 여부를 분명히 말하기",
    )

    result = service.review_message_before_send(
        workspace_id="default",
        draft_message="오늘 기능 정리해서 공유드리겠습니다.",
        room_name="공모전 팀방",
        recipient_type="team",
        extra_context="추가로 데모 영상 초안도 함께 공유할 예정입니다.",
    )

    assert result["risk_level"] == "low"
    assert result["missing_items"] == []


def test_roomless_review_ignores_unrelated_room_commitment(tmp_path: Path) -> None:
    service = build_service(tmp_path)

    service.save_commitment(
        workspace_id="default",
        title="금요일까지 데모 영상 공유",
        commitment_type="deadline",
        deadline_text="금요일",
        time_text="",
        related_person="팀장",
        related_room="공모전 팀방",
        source_type="chat",
        importance="high",
        status="planned",
        memo="",
    )

    result = service.review_message_before_send(
        workspace_id="default",
        draft_message="다음 주에 회의 자료를 정리해서 보내드리겠습니다.",
        room_name="",
        recipient_type="team",
        extra_context="",
    )

    assert result["risk_level"] == "low"
    assert result["context_used"]["commitment_count"] == 1
