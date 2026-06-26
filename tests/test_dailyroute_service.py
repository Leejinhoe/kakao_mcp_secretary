from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from dailyroute_service import DailyRouteService


KST = timezone(timedelta(hours=9))


def build_service(tmp_path: Path) -> DailyRouteService:
    return DailyRouteService(tmp_path / "dailyroute-test.db")


def test_extract_schedule_from_text_parses_meeting(tmp_path: Path) -> None:
    service = build_service(tmp_path)

    result = service.extract_schedule_from_text(
        workspace_id="test",
        text="내일 오후 3시에 강남역에서 00기업 미팅 있어.",
        source_type="text",
        default_timezone="Asia/Seoul",
        reference_date="2026-06-26",
    )

    assert result["extracted_count"] == 1
    schedule = result["schedules"][0]
    assert schedule["title"] == "00기업 미팅"
    assert schedule["date_text"] == "내일"
    assert schedule["time_text"] == "오후 3시"
    assert schedule["location_text"] == "강남역"
    assert schedule["schedule_type"] == "meeting"
    assert schedule["start_at"] == "2026-06-27T15:00:00+09:00"


def test_extract_schedule_from_text_parses_deadline(tmp_path: Path) -> None:
    service = build_service(tmp_path)

    result = service.extract_schedule_from_text(
        workspace_id="test",
        text="오늘 밤 10시까지 데모 영상 초안 공유",
        source_type="text",
        default_timezone="Asia/Seoul",
        reference_date="2026-06-26",
    )

    schedule = result["schedules"][0]
    assert schedule["title"] == "데모 영상 초안 공유"
    assert schedule["schedule_type"] == "deadline"
    assert schedule["start_at"] == "2026-06-26T22:00:00+09:00"


def test_extract_schedule_from_text_warns_when_image_is_provided(tmp_path: Path) -> None:
    service = build_service(tmp_path)

    result = service.extract_schedule_from_text(
        workspace_id="test",
        text="",
        source_type="ocr_text",
        default_timezone="Asia/Seoul",
        reference_date="2026-06-26",
        image_base64="abc",
    )

    assert result["extracted_count"] == 0
    assert any("OCR 텍스트" in warning for warning in result["warnings"])


def test_save_schedule_blocks_duplicate_by_default(tmp_path: Path) -> None:
    service = build_service(tmp_path)

    first = service.save_schedule(
        workspace_id="test",
        title="00기업 미팅",
        start_at="2026-06-27T15:00:00+09:00",
        end_at="2026-06-27T16:00:00+09:00",
        date_text="내일",
        time_text="오후 3시",
        location_text="강남역",
        schedule_type="meeting",
        source_type="manual",
        reminder_minutes=60,
        save_to_talk_calendar=False,
        allow_conflict=False,
    )
    second = service.save_schedule(
        workspace_id="test",
        title="거래처 미팅",
        start_at="2026-06-27T15:00:00+09:00",
        end_at="2026-06-27T16:00:00+09:00",
        date_text="내일",
        time_text="오후 3시",
        location_text="역삼역",
        schedule_type="meeting",
        source_type="manual",
        reminder_minutes=60,
        save_to_talk_calendar=False,
        allow_conflict=False,
    )

    assert first["saved"] is True
    assert second["saved"] is False
    assert second["conflict_detected"] is True
    assert second["conflict_candidates"][0]["schedule_id"] == first["schedule_id"]
    assert "이미 내일 오후 3시에" in second["warning"]


def test_save_schedule_can_allow_conflict(tmp_path: Path) -> None:
    service = build_service(tmp_path)

    service.save_schedule(
        workspace_id="test",
        title="00기업 미팅",
        start_at="2026-06-27T15:00:00+09:00",
        end_at="2026-06-27T16:00:00+09:00",
        date_text="내일",
        time_text="오후 3시",
        location_text="강남역",
        schedule_type="meeting",
        source_type="manual",
        reminder_minutes=60,
        save_to_talk_calendar=False,
        allow_conflict=False,
    )
    result = service.save_schedule(
        workspace_id="test",
        title="거래처 미팅",
        start_at="2026-06-27T15:00:00+09:00",
        end_at="2026-06-27T16:00:00+09:00",
        date_text="내일",
        time_text="15:00",
        location_text="역삼역",
        schedule_type="meeting",
        source_type="manual",
        reminder_minutes=60,
        save_to_talk_calendar=True,
        allow_conflict=True,
    )

    assert result["saved"] is True
    assert result["conflict_detected"] is True
    assert result["talk_calendar_payload"]["title"] == "거래처 미팅"


def test_check_day_feasibility_warns_for_impossible_route(tmp_path: Path) -> None:
    service = build_service(tmp_path)
    service.save_schedule(
        workspace_id="test",
        title="안양 미팅",
        start_at="2026-06-27T14:00:00+09:00",
        end_at="2026-06-27T14:00:00+09:00",
        date_text="2026-06-27",
        time_text="오후 2시",
        location_text="안양",
        schedule_type="meeting",
        source_type="manual",
        reminder_minutes=60,
        save_to_talk_calendar=False,
        allow_conflict=False,
    )
    service.save_schedule(
        workspace_id="test",
        title="강남 미팅",
        start_at="2026-06-27T14:30:00+09:00",
        end_at="2026-06-27T15:30:00+09:00",
        date_text="2026-06-27",
        time_text="오후 2시 30분",
        location_text="강남",
        schedule_type="meeting",
        source_type="manual",
        reminder_minutes=60,
        save_to_talk_calendar=False,
        allow_conflict=False,
    )

    result = service.check_day_feasibility(
        workspace_id="test",
        target_date="2026-06-27",
        default_origin="집",
        travel_mode="car",
        buffer_minutes=15,
    )

    assert result["feasible"] is False
    assert result["day_risk_level"] == "high"
    assert any("안양에서 강남까지 예상 이동 시간이 48분" in warning for warning in result["warnings"])


def test_find_places_on_route_returns_mock_stops(tmp_path: Path) -> None:
    service = build_service(tmp_path)

    result = service.find_places_on_route(
        workspace_id="test",
        origin="회사",
        destination="집",
        errands=["약국 들르기", "카페 들르기"],
        max_detour_minutes=15,
        preferred_area="강남",
    )

    assert "회사" in result["recommended_route"]
    assert "집" in result["recommended_route"]
    assert len(result["selected_places"]) == 2
    assert result["warning"]


def test_save_routine_and_daily_briefing_include_routine(tmp_path: Path) -> None:
    service = build_service(tmp_path)
    service.save_routine(
        workspace_id="test",
        routine_name="퇴근길 심부름",
        routine_type="commute",
        rule_text="퇴근길에는 약국이나 세탁소를 우선 배치한다.",
        active_days=["mon", "tue", "wed", "thu", "fri"],
        origin="회사",
        destination="집",
        preferred_buffer_minutes=20,
        avoid_conditions=["비 오는 날 도보 많은 경로 피하기"],
    )

    briefing = service.build_daily_route_briefing(
        workspace_id="test",
        target_date="2026-06-27",
        start_location="회사",
        end_location="집",
        extra_errands=["약국 들르기"],
        send_to_me=False,
    )

    assert briefing["briefing_title"] == "2026-06-27 생활동선 브리핑"
    assert any("퇴근길 심부름" in item for item in briefing["preparation_checklist"])


def test_route_watch_creates_due_alert(tmp_path: Path) -> None:
    service = build_service(tmp_path)
    start = datetime.now(KST) + timedelta(minutes=10)
    end = start + timedelta(hours=1)
    saved = service.save_schedule(
        workspace_id="test",
        title="강남 미팅",
        start_at=start.isoformat(timespec="seconds"),
        end_at=end.isoformat(timespec="seconds"),
        date_text=start.date().isoformat(),
        time_text=start.strftime("%H:%M"),
        location_text="강남",
        schedule_type="meeting",
        source_type="manual",
        reminder_minutes=60,
        save_to_talk_calendar=False,
        allow_conflict=False,
    )
    watch = service.create_route_watch(
        workspace_id="test",
        schedule_id=saved["schedule_id"],
        origin="안양",
        check_minutes_before=60,
        buffer_minutes=15,
        notify_channel="log_only",
    )

    alerts = service.get_route_alerts(workspace_id="test", limit=10)

    assert watch["created"] is True
    assert alerts["alerts"]
    assert alerts["alerts"][0]["risk_level"] == "high"
