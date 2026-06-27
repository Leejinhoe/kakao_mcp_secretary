from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import dailyroute_service
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
    assert result["talk_calendar_payload"]["event"]["title"] == "거래처 미팅"


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


def test_check_day_feasibility_uses_selected_travel_mode(tmp_path: Path) -> None:
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

    assert result["route_checks"][0]["travel_mode"] == "walking_estimate"
    assert result["route_checks"][0]["provider_mode"] == "모의 도보 이동시간"


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
