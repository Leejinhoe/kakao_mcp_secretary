from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import dailyroute_service
from dailyroute_service import DailyRouteService


KST = timezone(timedelta(hours=9))


@pytest.fixture(autouse=True)
def isolate_runtime_config(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("DAILYROUTE_SECRETS_PATH", str(tmp_path / "missing-secrets.local.json"))
    for key in (
        "DAILYROUTE_DB_PATH",
        "ENABLE_REAL_KAKAO_APIS",
        "KAKAO_REST_API_KEY",
        "KAKAO_MOBILITY_API_KEY",
        "KAKAO_CLIENT_SECRET",
        "KAKAO_ACCESS_TOKEN",
        "KAKAO_REDIRECT_URI",
        "KAKAO_OAUTH_SCOPES",
        "KAKAO_CALENDAR_ID",
        "PUBLIC_BASE_URL",
    ):
        monkeypatch.delenv(key, raising=False)


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


def test_extract_schedule_detects_errand_and_destination(tmp_path: Path) -> None:
    service = build_service(tmp_path)

    result = service.extract_schedule_from_text(
        workspace_id="test",
        text="오늘 약국들렀다 3시에 오산시청 보배반점에서 점심약속 있어",
        source_type="text",
        default_timezone="Asia/Seoul",
        reference_date="2026-06-28",
    )

    schedule = result["schedules"][0]
    assert schedule["title"] == "점심약속"
    assert schedule["date_text"] == "오늘"
    assert schedule["time_text"] == "3시"
    assert schedule["start_at"] == "2026-06-28T15:00:00+09:00"
    assert schedule["location_text"] == "오산시청 보배반점"
    assert schedule["schedule_type"] == "personal"
    assert schedule["detected_errands"] == ["약국 들르기"]


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
    assert result["talk_calendar_payload"]["event"]["title"] == "거래처 미팅"


def test_save_schedule_deduplicates_same_time_title_and_place(tmp_path: Path) -> None:
    service = build_service(tmp_path)

    first = service.save_schedule(
        workspace_id="test",
        title="보배반점 점심약속",
        start_at="2026-06-28T15:00:00+09:00",
        end_at="2026-06-28T16:00:00+09:00",
        date_text="오늘",
        time_text="3시",
        location_text="오산시청 보배반점",
        schedule_type="personal",
        source_type="manual",
        reminder_minutes=60,
        save_to_talk_calendar=False,
        allow_conflict=False,
        notes="처음 저장",
    )
    second = service.save_schedule(
        workspace_id="test",
        title="보배반점 점심약속",
        start_at="2026-06-28T15:00:00+09:00",
        end_at="2026-06-28T16:00:00+09:00",
        date_text="오늘",
        time_text="3시",
        location_text="오산시청 보배반점",
        schedule_type="personal",
        source_type="manual",
        reminder_minutes=60,
        save_to_talk_calendar=False,
        allow_conflict=False,
        notes="메모 추가",
    )
    listed = service.list_schedules("test", date_text="2026-06-28")

    assert first["saved"] is True
    assert second["saved"] is True
    assert second["schedule_id"] == first["schedule_id"]
    assert second["deduplicated"] is True
    assert len(listed["schedules"]) == 1
    assert "메모 추가" in listed["schedules"][0]["notes"]


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
    assert any("안양에서 강남까지 모의 차량 이동시간 기준 예상 이동 시간이 48분" in warning for warning in result["warnings"])


def test_save_schedule_returns_route_advice_from_previous_schedule(tmp_path: Path) -> None:
    service = build_service(tmp_path)
    service.save_schedule(
        workspace_id="test",
        title="화성 집결",
        start_at="2026-06-27T08:20:00+09:00",
        end_at="2026-06-27T09:00:00+09:00",
        date_text="2026-06-27",
        time_text="오전 8시 20분",
        location_text="화성",
        schedule_type="meeting",
        source_type="manual",
        reminder_minutes=60,
        save_to_talk_calendar=False,
        allow_conflict=False,
    )

    result = service.save_schedule(
        workspace_id="test",
        title="출판사 미팅",
        start_at="2026-06-27T14:00:00+09:00",
        end_at="2026-06-27T15:00:00+09:00",
        date_text="2026-06-27",
        time_text="오후 2시",
        location_text="출판사",
        schedule_type="meeting",
        source_type="manual",
        reminder_minutes=60,
        save_to_talk_calendar=False,
        allow_conflict=False,
    )

    assert result["route_advice"]["checked"] is True
    assert result["route_advice"]["origin"] == "화성"
    assert result["route_advice"]["destination"] == "출판사"
    assert result["route_advice"]["recommended_departure_time"]


def test_save_schedule_recommends_errand_place_near_route(tmp_path: Path) -> None:
    service = build_service(tmp_path)
    service.save_route_profile(
        workspace_id="test",
        profile_name="집 출발",
        origin="오산시티자이 1단지",
        destination="오산시청",
        preferences={"home_location": "오산시티자이 1단지", "buffer_minutes": 15},
    )

    result = service.save_schedule(
        workspace_id="test",
        title="점심약속",
        start_at="2026-06-28T15:00:00+09:00",
        end_at="2026-06-28T16:00:00+09:00",
        date_text="오늘",
        time_text="3시",
        location_text="오산시청 보배반점",
        schedule_type="personal",
        source_type="text",
        reminder_minutes=60,
        save_to_talk_calendar=False,
        allow_conflict=False,
        raw_text="오늘 약국들렀다 3시에 오산시청 보배반점에서 점심약속 있어",
    )

    assert result["route_advice"]["origin"] == "오산시티자이 1단지"
    assert result["errand_route_plan"]["planned"] is True
    assert result["errand_route_plan"]["detected_errands"] == ["약국 들르기"]
    assert "약국" in result["errand_route_plan"]["places_plan"]["recommended_route"]


def test_schedule_crud_is_workspace_scoped(tmp_path: Path) -> None:
    service = build_service(tmp_path)
    saved_a = service.save_schedule(
        workspace_id="user-a",
        title="A 일정",
        start_at="2026-06-27T10:00:00+09:00",
        end_at="2026-06-27T11:00:00+09:00",
        date_text="2026-06-27",
        time_text="오전 10시",
        location_text="강남",
        schedule_type="meeting",
        source_type="manual",
        reminder_minutes=60,
        save_to_talk_calendar=False,
        allow_conflict=False,
    )
    service.save_schedule(
        workspace_id="user-b",
        title="B 일정",
        start_at="2026-06-27T10:00:00+09:00",
        end_at="2026-06-27T11:00:00+09:00",
        date_text="2026-06-27",
        time_text="오전 10시",
        location_text="강남",
        schedule_type="meeting",
        source_type="manual",
        reminder_minutes=60,
        save_to_talk_calendar=False,
        allow_conflict=False,
    )

    listed_a = service.list_schedules("user-a", date_text="2026-06-27")
    listed_b = service.list_schedules("user-b", date_text="2026-06-27")
    delete_wrong_workspace = service.delete_schedule("user-b", saved_a["schedule_id"])

    assert [item["title"] for item in listed_a["schedules"]] == ["A 일정"]
    assert [item["title"] for item in listed_b["schedules"]] == ["B 일정"]
    assert delete_wrong_workspace["deleted"] is False


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


def test_route_profile_can_be_saved_and_listed(tmp_path: Path) -> None:
    service = build_service(tmp_path)

    saved = service.save_route_profile(
        workspace_id="test",
        profile_name="평일 출근길",
        origin="집",
        destination="회사",
        preferences={"buffer_minutes": 20, "avoid": ["도보 많은 경로"]},
    )
    listed = service.list_route_profiles(workspace_id="test", limit=10)

    assert saved["saved"] is True
    assert listed["profiles"][0]["id"] == saved["profile_id"]
    assert listed["profiles"][0]["preferences"]["buffer_minutes"] == 20


def test_errand_can_be_saved_and_listed(tmp_path: Path) -> None:
    service = build_service(tmp_path)

    saved = service.save_errand(
        workspace_id="test",
        errand_text="약국 들르기",
        category="",
        preferred_area="강남",
    )
    listed = service.list_errands(workspace_id="test", limit=10)

    assert saved["saved"] is True
    assert saved["errand"]["category"] == "pharmacy"
    assert listed["errands"][0]["id"] == saved["errand_id"]


def test_api_config_can_be_saved_and_read_by_helpers(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("DAILYROUTE_DB_PATH", str(tmp_path / "dailyroute-config.db"))
    monkeypatch.delenv("ENABLE_REAL_KAKAO_APIS", raising=False)
    monkeypatch.delenv("KAKAO_REST_API_KEY", raising=False)
    service = DailyRouteService()

    saved = service.save_api_config(
        workspace_id="default",
        api_config={
            "ENABLE_REAL_KAKAO_APIS": "true",
            "KAKAO_REST_API_KEY": "rest_key_for_test",
            "PUBLIC_BASE_URL": "https://example.test",
        },
    )
    listed = service.list_api_config("default")

    assert saved["saved"] is True
    assert saved["api_config"]["KAKAO_REST_API_KEY"] == "rest...test"
    assert listed["api_config"]["KAKAO_REST_API_KEY"]["value"] == "rest...test"
    assert dailyroute_service._mock_mode() is False
    assert dailyroute_service._rest_api_key() == "rest_key_for_test"
    assert dailyroute_service._public_base_url() == "https://example.test"


def test_local_secrets_file_can_feed_api_config(tmp_path: Path, monkeypatch) -> None:
    secrets_path = tmp_path / "secrets.local.json"
    secrets_path.write_text(
        '{"ENABLE_REAL_KAKAO_APIS":"true","KAKAO_REST_API_KEY":"rest_from_file","KAKAO_CALENDAR_ID":"primary"}',
        encoding="utf-8",
    )
    monkeypatch.setenv("DAILYROUTE_SECRETS_PATH", str(secrets_path))
    monkeypatch.delenv("ENABLE_REAL_KAKAO_APIS", raising=False)
    monkeypatch.delenv("KAKAO_REST_API_KEY", raising=False)

    assert dailyroute_service._mock_mode() is False
    assert dailyroute_service._rest_api_key() == "rest_from_file"
    assert dailyroute_service._config_value("KAKAO_CALENDAR_ID") == "primary"


def test_local_secrets_override_stale_db_api_config(tmp_path: Path, monkeypatch) -> None:
    secrets_path = tmp_path / "secrets.local.json"
    secrets_path.write_text(
        '{"PUBLIC_BASE_URL":"https://fresh.example","KAKAO_REDIRECT_URI":"https://fresh.example/oauth/kakao/callback"}',
        encoding="utf-8",
    )
    monkeypatch.setenv("DAILYROUTE_DB_PATH", str(tmp_path / "stale-config.db"))
    monkeypatch.setenv("DAILYROUTE_SECRETS_PATH", str(secrets_path))
    service = DailyRouteService()
    service.save_api_config(
        workspace_id="default",
        api_config={
            "PUBLIC_BASE_URL": "https://stale.example",
            "KAKAO_REDIRECT_URI": "https://stale.example/oauth/kakao/callback",
        },
    )

    assert dailyroute_service._config_value("PUBLIC_BASE_URL") == "https://fresh.example"
    assert dailyroute_service._config_value("KAKAO_REDIRECT_URI") == "https://fresh.example/oauth/kakao/callback"


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


def test_kakao_oauth_login_url_uses_env_key_and_stores_state(tmp_path: Path, monkeypatch) -> None:
    service = build_service(tmp_path)
    monkeypatch.setenv("KAKAO_REST_API_KEY", "rest_key_for_test")
    monkeypatch.setenv("KAKAO_OAUTH_SCOPES", "talk_message")

    result = service.build_kakao_oauth_login_url(
        workspace_id="test",
        redirect_uri="http://127.0.0.1:8000/oauth/kakao/callback",
    )

    assert result["configured"] is True
    assert "kauth.kakao.com/oauth/authorize" in result["login_url"]
    assert "client_id=rest_key_for_test" in result["login_url"]
    assert "scope=talk_message" in result["login_url"]
    assert service._fetch_one("SELECT * FROM oauth_states WHERE state = ?", (result["state"],)) is not None


def test_kakao_token_storage_can_feed_api_callers(tmp_path: Path) -> None:
    service = build_service(tmp_path)

    stored = service._save_kakao_token(
        "test",
        {
            "access_token": "access_for_test",
            "refresh_token": "refresh_for_test",
            "expires_in": 3600,
            "refresh_token_expires_in": 7200,
            "scope": "talk_message",
        },
    )
    token = service.get_kakao_access_token("test")

    assert stored["stored"] is True
    assert token["available"] is True
    assert token["access_token"] == "access_for_test"
    assert service.kakao_auth_status("test")["authenticated"] is True


def test_kakao_oauth_migrates_default_workspace_and_backfills_calendar(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = build_service(tmp_path)
    monkeypatch.setenv("KAKAO_REST_API_KEY", "rest_key_for_test")

    saved = service.save_schedule(
        workspace_id="default",
        title="기존 로컬 일정",
        start_at="2026-06-29T10:00:00+09:00",
        end_at="2026-06-29T11:00:00+09:00",
        date_text="2026-06-29",
        time_text="오전 10시",
        location_text="강남",
        schedule_type="meeting",
        source_type="manual",
        reminder_minutes=60,
        save_to_talk_calendar=False,
        allow_conflict=False,
    )
    login = service.build_kakao_oauth_login_url("default", "https://service.example/oauth/kakao/callback")

    def fake_form_post_json(url: str, data: dict, headers: dict | None = None) -> dict:
        return {
            "ok": True,
            "json": {
                "access_token": "access_for_test",
                "refresh_token": "refresh_for_test",
                "expires_in": 3600,
                "refresh_token_expires_in": 7200,
                "scope": "talk_message,talk_calendar",
            },
        }

    def fake_calendar_create(payload: dict, access_token: str = "", auth_url: str = "") -> dict:
        return {
            "created": True,
            "event_id": "event_from_backfill",
            "payload": payload,
            "auth_required": False,
            "auth_url": "",
            "message": "톡캘린더에 일정을 생성했습니다.",
        }

    monkeypatch.setattr(dailyroute_service, "_form_post_json", fake_form_post_json)
    monkeypatch.setattr(dailyroute_service, "fetch_kakao_user_id", lambda access_token: {"ok": True, "kakao_user_id": "12345"})
    monkeypatch.setattr(dailyroute_service, "create_talk_calendar_event_if_configured", fake_calendar_create)

    result = service.complete_kakao_oauth(
        code="auth_code",
        state=login["state"],
        redirect_uri="https://service.example/oauth/kakao/callback",
    )
    migrated = service._fetch_one("SELECT * FROM schedules WHERE workspace_id = ? AND id = ?", ("kakao_12345", saved["schedule_id"]))
    default_rows = service._fetch_all("SELECT * FROM schedules WHERE workspace_id = ?", ("default",))

    assert result["success"] is True
    assert result["workspace_id"] == "kakao_12345"
    assert result["migration_result"]["migrated_schedules"] == 1
    assert result["calendar_backfill"]["synced"] == 1
    assert migrated is not None
    assert migrated["talk_calendar_event_id"] == "event_from_backfill"
    assert default_rows == []


def test_check_day_feasibility_rejects_non_car_travel_mode(tmp_path: Path) -> None:
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
        travel_mode="walking_estimate",
        buffer_minutes=15,
    )

    assert result["feasible"] is False
    assert result["day_risk_level"] == "high"
    assert result["route_checks"] == []
    assert "자동차 이동시간만 지원" in result["warnings"][0]


def test_estimate_route_duration_rejects_non_car_mode() -> None:
    result = dailyroute_service.estimate_route_duration("회사", "집", travel_mode="walking_estimate")

    assert result["unsupported"] is True
    assert result["duration_minutes"] == 0
    assert "자동차 이동시간만 지원" in result["warning"]


def test_car_route_uses_rest_key_when_mobility_key_is_empty(monkeypatch) -> None:
    calls: list[dict] = []
    monkeypatch.setenv("ENABLE_REAL_KAKAO_APIS", "true")
    monkeypatch.setenv("KAKAO_REST_API_KEY", "rest_key_for_route")
    monkeypatch.delenv("KAKAO_MOBILITY_API_KEY", raising=False)

    def fake_coordinates(place_text: str) -> dict:
        return {
            "place_text": place_text,
            "lat": 37.5 if place_text == "회사" else 37.51,
            "lng": 127.0 if place_text == "회사" else 127.02,
            "mock": False,
        }

    def fake_get_json(url: str, params: dict, headers: dict | None = None) -> dict:
        calls.append({"url": url, "params": params, "headers": headers or {}})
        return {
            "ok": True,
            "status": 200,
            "json": {
                "routes": [
                    {
                        "result_code": 0,
                        "summary": {"duration": 600, "distance": 5000, "fare": {}},
                    }
                ]
            },
        }

    monkeypatch.setattr(dailyroute_service, "resolve_address_or_place_to_coordinates", fake_coordinates)
    monkeypatch.setattr(dailyroute_service, "_get_json", fake_get_json)

    result = dailyroute_service.estimate_route_duration("회사", "집", travel_mode="car")

    assert result["duration_minutes"] == 10
    assert result["distance_meters"] == 5000
    assert result["provider"] == "kakao_mobility_directions"
    assert calls[0]["headers"]["Authorization"] == "KakaoAK rest_key_for_route"


def test_waypoints_route_uses_multi_waypoint_api(monkeypatch) -> None:
    calls: list[dict] = []
    monkeypatch.setenv("ENABLE_REAL_KAKAO_APIS", "true")
    monkeypatch.setenv("KAKAO_REST_API_KEY", "rest_key_for_route")

    def fake_coordinates(place_text: str) -> dict:
        index = {"회사": 0, "약국": 1, "카페": 2, "집": 3}.get(place_text, 4)
        return {
            "place_text": place_text,
            "lat": 37.5 + index * 0.01,
            "lng": 127.0 + index * 0.01,
            "mock": False,
        }

    def fake_post_json(url: str, payload: dict, headers: dict | None = None) -> dict:
        calls.append({"url": url, "payload": payload, "headers": headers or {}})
        return {
            "ok": True,
            "status": 200,
            "json": {
                "routes": [
                    {
                        "result_code": 0,
                        "summary": {"duration": 900, "distance": 7000, "fare": {}},
                    }
                ]
            },
        }

    monkeypatch.setattr(dailyroute_service, "resolve_address_or_place_to_coordinates", fake_coordinates)
    monkeypatch.setattr(dailyroute_service, "_post_json", fake_post_json)

    result = dailyroute_service.estimate_route_duration("회사", "집", waypoints=["약국", "카페"], travel_mode="car")

    assert result["duration_minutes"] == 15
    assert result["provider"] == "kakao_mobility_waypoints_directions"
    assert calls[0]["url"].endswith("/v1/waypoints/directions")
    assert [item["name"] for item in calls[0]["payload"]["waypoints"]] == ["약국", "카페"]


def test_future_route_uses_future_directions_api(monkeypatch) -> None:
    calls: list[dict] = []
    monkeypatch.setenv("ENABLE_REAL_KAKAO_APIS", "true")
    monkeypatch.setenv("KAKAO_REST_API_KEY", "rest_key_for_route")

    def fake_coordinates(place_text: str) -> dict:
        return {
            "place_text": place_text,
            "lat": 37.5,
            "lng": 127.0,
            "mock": False,
        }

    def fake_get_json(url: str, params: dict, headers: dict | None = None) -> dict:
        calls.append({"url": url, "params": params, "headers": headers or {}})
        return {
            "ok": True,
            "status": 200,
            "json": {
                "routes": [
                    {
                        "result_code": 0,
                        "summary": {"duration": 1200, "distance": 9000, "fare": {}},
                    }
                ]
            },
        }

    monkeypatch.setattr(dailyroute_service, "resolve_address_or_place_to_coordinates", fake_coordinates)
    monkeypatch.setattr(dailyroute_service, "_get_json", fake_get_json)

    result = dailyroute_service.estimate_future_route_duration(
        "회사",
        "강남역",
        "2026-06-27T14:00:00+09:00",
    )

    assert result["duration_minutes"] == 20
    assert result["provider"] == "kakao_mobility_future_directions"
    assert calls[0]["url"].endswith("/v1/future/directions")
    assert calls[0]["params"]["departure_time"] == "202606271400"
