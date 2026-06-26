from __future__ import annotations

import json
import os
import re
import sqlite3
import urllib.error
import urllib.parse
import urllib.request
from itertools import product
from math import asin, cos, radians, sin, sqrt
from datetime import UTC, date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4


DEFAULT_WORKSPACE_ID = "default"
DB_PATH_ENV = "DAILYROUTE_DB_PATH"
KST = timezone(timedelta(hours=9))
KAKAO_OAUTH_AUTHORIZE_URL = "https://kauth.kakao.com/oauth/authorize"
KAKAO_OAUTH_TOKEN_URL = "https://kauth.kakao.com/oauth/token"
KAKAO_CALENDAR_CREATE_EVENT_URL = "https://kapi.kakao.com/v2/api/calendar/create/event"
KAKAO_TALK_MEMO_SEND_URL = "https://kapi.kakao.com/v2/api/talk/memo/default/send"
KAKAO_LOCAL_KEYWORD_URL = "https://dapi.kakao.com/v2/local/search/keyword.json"
KAKAO_LOCAL_ADDRESS_URL = "https://dapi.kakao.com/v2/local/search/address.json"
KAKAO_MOBILITY_DIRECTIONS_URL = "https://apis-navi.kakaomobility.com/v1/directions"
KAKAO_MOBILITY_WAYPOINTS_DIRECTIONS_URL = "https://apis-navi.kakaomobility.com/v1/waypoints/directions"
KAKAO_MOBILITY_FUTURE_DIRECTIONS_URL = "https://apis-navi.kakaomobility.com/v1/future/directions"

ScheduleType = Literal["meeting", "deadline", "appointment", "personal", "routine", "errand", "other"]
ScheduleSourceType = Literal["text", "ocr_text", "manual", "calendar", "other"]
RoutineType = Literal["commute", "exercise", "hospital", "study", "work", "weekly", "custom"]
TravelMode = Literal["car", "transit_estimate", "walking_estimate"]
NotifyChannel = Literal["kakao_me", "log_only"]


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _now_utc() -> datetime:
    return datetime.now(UTC)


def _normalize_spaces(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _compact_text(text: str) -> str:
    return re.sub(r"\s+", "", text or "")


def _resolve_db_path(default_path: str | Path) -> Path:
    override = os.getenv(DB_PATH_ENV)
    return Path(override) if override else Path(default_path)


def _parse_reference_date(reference_date: str) -> date:
    if reference_date:
        try:
            return datetime.strptime(reference_date, "%Y-%m-%d").date()
        except ValueError:
            pass
    return datetime.now(KST).date()


def _weekday_index(text: str) -> int | None:
    return {
        "월": 0,
        "월요일": 0,
        "화": 1,
        "화요일": 1,
        "수": 2,
        "수요일": 2,
        "목": 3,
        "목요일": 3,
        "금": 4,
        "금요일": 4,
        "토": 5,
        "토요일": 5,
        "일": 6,
        "일요일": 6,
    }.get(text)


def _extract_date_info(text: str, reference_date: str = "") -> tuple[str, str]:
    normalized = _normalize_spaces(text)
    compact = _compact_text(normalized)
    base_date = _parse_reference_date(reference_date)

    iso_match = re.search(r"(\d{4})[-./](\d{1,2})[-./](\d{1,2})", normalized)
    if iso_match:
        year, month, day = map(int, iso_match.groups())
        parsed = date(year, month, day)
        return iso_match.group(0), parsed.isoformat()

    month_day_match = re.search(r"(\d{1,2})월\s*(\d{1,2})일", normalized)
    if month_day_match:
        month, day = map(int, month_day_match.groups())
        parsed = date(base_date.year, month, day)
        if parsed < base_date - timedelta(days=180):
            parsed = date(base_date.year + 1, month, day)
        return month_day_match.group(0), parsed.isoformat()

    relative_map = {
        "오늘": 0,
        "내일": 1,
        "모레": 2,
    }
    for label, offset in relative_map.items():
        if label in compact:
            return label, (base_date + timedelta(days=offset)).isoformat()

    week_match = re.search(r"(이번\s*주|다음\s*주)?\s*(월요일|화요일|수요일|목요일|금요일|토요일|일요일)", normalized)
    if week_match:
        week_label = _compact_text(week_match.group(1) or "")
        weekday_label = week_match.group(2)
        target_weekday = _weekday_index(weekday_label)
        if target_weekday is not None:
            start_of_week = base_date - timedelta(days=base_date.weekday())
            if week_label == "다음주":
                start_of_week += timedelta(days=7)
            target_date = start_of_week + timedelta(days=target_weekday)
            if not week_label and target_date < base_date:
                target_date += timedelta(days=7)
            return week_match.group(0).strip(), target_date.isoformat()

    short_week_match = re.search(r"(?<![가-힣0-9])(월|화|수|목|금|토|일)(?:\s*요일)?(?![가-힣0-9])", normalized)
    if short_week_match:
        weekday_label = short_week_match.group(0).replace("요일", "").strip()
        target_weekday = _weekday_index(weekday_label)
        if target_weekday is not None:
            target_date = base_date + timedelta(days=(target_weekday - base_date.weekday()) % 7)
            return short_week_match.group(0), target_date.isoformat()

    return "", ""


def _extract_time_info(text: str) -> tuple[str, str]:
    normalized = _normalize_spaces(text)
    colon_match = re.search(r"(?<!\d)(\d{1,2}):(\d{2})(?!\d)", normalized)
    if colon_match:
        hour, minute = map(int, colon_match.groups())
        return colon_match.group(0), f"{hour:02d}:{minute:02d}"

    korean_match = re.search(r"(새벽|오전|오후|저녁|밤)?\s*(\d{1,2})시(?:\s*(\d{1,2})분)?", normalized)
    if korean_match:
        meridiem, hour_text, minute_text = korean_match.groups()
        hour = int(hour_text)
        minute = int(minute_text or "0")
        if meridiem in {"오후", "저녁", "밤"} and hour < 12:
            hour += 12
        if meridiem == "새벽" and hour == 12:
            hour = 0
        if meridiem == "오전" and hour == 12:
            hour = 0
        return korean_match.group(0).strip(), f"{hour:02d}:{minute:02d}"

    return "", ""


def _build_datetime(date_iso: str, time_hm: str) -> str:
    if not date_iso or not time_hm:
        return ""
    return f"{date_iso}T{time_hm}:00+09:00"


def _parse_iso_datetime(value: str) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _to_utc_z(value: str) -> str:
    parsed = _parse_iso_datetime(value)
    if not parsed:
        return ""
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=KST)
    return parsed.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _infer_end_at(start_at: str, schedule_type: ScheduleType) -> str:
    start = _parse_iso_datetime(start_at)
    if not start:
        return ""
    duration_minutes = 30 if schedule_type in {"deadline", "errand"} else 60
    return (start + timedelta(minutes=duration_minutes)).isoformat(timespec="seconds")


def _infer_schedule_type(text: str) -> ScheduleType:
    if any(term in text for term in ("까지", "마감", "제출", "공유", "완료")):
        return "deadline"
    if any(term in text for term in ("회의", "미팅", "면담", "콜")):
        return "meeting"
    if any(term in text for term in ("병원", "치과", "예약", "진료")):
        return "appointment"
    if any(term in text for term in ("약국", "카페", "프린트", "세탁", "다이소")):
        return "errand"
    return "other"


def _extract_location(text: str) -> str:
    location_matches = re.findall(r"([A-Za-z0-9가-힣._-]{2,30})(?:에서|으로|로)\s", text)
    if location_matches:
        return _normalize_spaces(location_matches[-1])
    place_match = re.search(r"(강남역|역삼역|강남|안양|판교|회사|집|학교|병원|카페|약국)", text)
    return place_match.group(1) if place_match else ""


def _extract_title(text: str, date_text: str, time_text: str, location_text: str) -> str:
    title = _normalize_spaces(text)
    for value in (date_text, time_text):
        if value:
            title = title.replace(value, " ")
    if location_text:
        title = re.sub(re.escape(location_text) + r"\s*(에서|으로|로)?", " ", title)
    title = re.sub(r"(있어|있습니다|해야 해|해야 합니다|예정|까지|에|에서|으로|로)", " ", title)
    title = re.sub(r"[.。!?！？]+", " ", title)
    title = _normalize_spaces(title)
    return title or "제목 미정 일정"


def _extract_schedule_candidate(text: str, source_type: ScheduleSourceType, reference_date: str) -> dict[str, Any]:
    normalized = _normalize_spaces(text)
    date_text, date_iso = _extract_date_info(normalized, reference_date)
    time_text, time_hm = _extract_time_info(normalized)
    schedule_type = _infer_schedule_type(normalized)
    location_text = _extract_location(normalized)
    title = _extract_title(normalized, date_text, time_text, location_text)
    start_at = _build_datetime(date_iso, time_hm)
    end_at = _infer_end_at(start_at, schedule_type)

    missing_fields: list[str] = []
    if not date_text:
        missing_fields.append("date")
    if not time_text:
        missing_fields.append("time")
    if not location_text and schedule_type in {"meeting", "appointment", "errand"}:
        missing_fields.append("location")

    confidence = 100 - len(missing_fields) * 20
    if title == "제목 미정 일정":
        confidence -= 15
    confidence = max(35, min(95, confidence))

    return {
        "title": title,
        "date_text": date_text,
        "time_text": time_text,
        "start_at": start_at,
        "end_at": end_at,
        "location_text": location_text,
        "schedule_type": schedule_type,
        "source_type": source_type,
        "confidence_score": confidence,
        "missing_fields": missing_fields,
        "raw_text": normalized,
    }


def _split_schedule_text(text: str) -> list[str]:
    pieces = re.split(r"(?:\n+|[;；]|그리고|또)", text or "")
    return [_normalize_spaces(piece) for piece in pieces if _normalize_spaces(piece)]


def _overlaps(start_a: str, end_a: str, start_b: str, end_b: str) -> bool:
    a_start = _parse_iso_datetime(start_a)
    a_end = _parse_iso_datetime(end_a)
    b_start = _parse_iso_datetime(start_b)
    b_end = _parse_iso_datetime(end_b)
    if not all([a_start, a_end, b_start, b_end]):
        return False
    return a_start < b_end and b_start < a_end


def _same_date_time_text(existing: dict[str, Any], date_text: str, time_text: str, start_at: str) -> bool:
    if date_text and time_text and existing.get("date_text") == date_text and existing.get("time_text") == time_text:
        return True
    existing_start = _parse_iso_datetime(existing.get("start_at", ""))
    new_start = _parse_iso_datetime(start_at)
    return bool(existing_start and new_start and existing_start == new_start)


def _env_enabled(name: str) -> bool:
    return os.getenv(name, "").lower() in {"1", "true", "yes", "on"}


def _mock_mode() -> bool:
    return not _env_enabled("ENABLE_REAL_KAKAO_APIS")


def _rest_api_key() -> str:
    return os.getenv("KAKAO_REST_API_KEY", "")


def _mobility_api_key() -> str:
    return os.getenv("KAKAO_MOBILITY_API_KEY") or _rest_api_key()


def _local_api_key() -> str:
    return _rest_api_key() or os.getenv("KAKAO_MOBILITY_API_KEY", "")


def _public_base_url() -> str:
    return os.getenv("PUBLIC_BASE_URL", "http://127.0.0.1:8000").rstrip("/")


def _kakao_login_url_for_workspace(workspace_id: str) -> str:
    query = urllib.parse.urlencode({"workspace_id": workspace_id or DEFAULT_WORKSPACE_ID})
    return f"{_public_base_url()}/oauth/kakao/login?{query}"


def _form_post_json(url: str, data: dict[str, Any], headers: dict[str, str] | None = None) -> dict[str, Any]:
    encoded = urllib.parse.urlencode(data).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=encoded,
        headers={
            "Content-Type": "application/x-www-form-urlencoded;charset=utf-8",
            **(headers or {}),
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            raw = response.read().decode("utf-8")
            return {"ok": True, "status": response.status, "json": json.loads(raw) if raw else {}}
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        try:
            parsed_body: Any = json.loads(body)
        except json.JSONDecodeError:
            parsed_body = body
        return {"ok": False, "status": exc.code, "error": parsed_body}
    except Exception as exc:
        return {"ok": False, "status": 0, "error": str(exc)}


def _get_json(url: str, params: dict[str, Any], headers: dict[str, str] | None = None) -> dict[str, Any]:
    query = urllib.parse.urlencode(params)
    request = urllib.request.Request(
        f"{url}?{query}" if query else url,
        headers=headers or {},
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            raw = response.read().decode("utf-8")
            return {"ok": True, "status": response.status, "json": json.loads(raw) if raw else {}}
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        try:
            parsed_body: Any = json.loads(body)
        except json.JSONDecodeError:
            parsed_body = body
        return {"ok": False, "status": exc.code, "error": parsed_body}
    except Exception as exc:
        return {"ok": False, "status": 0, "error": str(exc)}


def _post_json(url: str, payload: dict[str, Any], headers: dict[str, str] | None = None) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            **(headers or {}),
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            raw = response.read().decode("utf-8")
            return {"ok": True, "status": response.status, "json": json.loads(raw) if raw else {}}
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        try:
            parsed_body: Any = json.loads(body)
        except json.JSONDecodeError:
            parsed_body = body
        return {"ok": False, "status": exc.code, "error": parsed_body}
    except Exception as exc:
        return {"ok": False, "status": 0, "error": str(exc)}


def build_talk_calendar_event_payload(schedule: dict[str, Any]) -> dict[str, Any]:
    event: dict[str, Any] = {
        "title": schedule.get("title", "")[:50] or "제목 미정 일정",
        "time": {
            "start_at": _to_utc_z(schedule.get("start_at", "")),
            "end_at": _to_utc_z(schedule.get("end_at", "")),
            "time_zone": "Asia/Seoul",
            "all_day": False,
            "lunar": False,
        },
        "description": "DailyRoute Guard에서 생성한 일정입니다.",
        "reminders": [schedule.get("reminder_minutes", 60)],
    }
    if schedule.get("location_text"):
        event["location"] = {"name": schedule.get("location_text", "")}
    return {
        "calendar_id": os.getenv("KAKAO_CALENDAR_ID", "primary"),
        "event": event,
    }


def create_talk_calendar_event_if_configured(
    payload: dict[str, Any],
    access_token: str = "",
    auth_url: str = "",
) -> dict[str, Any]:
    if _mock_mode():
        return {
            "created": False,
            "payload": payload,
            "auth_required": False,
            "auth_url": auth_url,
            "message": "ENABLE_REAL_KAKAO_APIS가 true가 아니어서 로컬 DB에만 저장했습니다.",
        }
    token = access_token or os.getenv("KAKAO_ACCESS_TOKEN", "")
    if not token:
        return {
            "created": False,
            "payload": payload,
            "auth_required": True,
            "auth_url": auth_url,
            "message": "카카오 로그인이 필요합니다. auth_url에서 동의하면 다음부터 톡캘린더 생성을 시도합니다.",
        }
    result = _form_post_json(
        KAKAO_CALENDAR_CREATE_EVENT_URL,
        {
            "calendar_id": payload.get("calendar_id", "primary"),
            "event": json.dumps(payload.get("event", {}), ensure_ascii=False),
        },
        {"Authorization": f"Bearer {token}"},
    )
    if result["ok"]:
        return {
            "created": True,
            "event_id": result["json"].get("event_id", ""),
            "payload": payload,
            "auth_required": False,
            "auth_url": "",
            "message": "톡캘린더에 일정을 생성했습니다.",
        }
    return {
        "created": False,
        "payload": payload,
        "auth_required": result.get("status") in {401, 403},
        "auth_url": auth_url,
        "message": "톡캘린더 생성 API 호출에 실패했습니다.",
        "error": result.get("error"),
    }


def list_talk_calendar_events_if_configured(
    start_at: str = "",
    end_at: str = "",
    access_token: str = "",
) -> dict[str, Any]:
    token = access_token or os.getenv("KAKAO_ACCESS_TOKEN", "")
    if _mock_mode() or not token:
        return {
            "events": [],
            "message": "톡캘린더 조회 토큰이 없어 로컬 DB 일정만 사용합니다.",
            "requested_range": {"start_at": start_at, "end_at": end_at},
        }
    result = _get_json(
        "https://kapi.kakao.com/v2/api/calendar/events",
        {"calendar_id": os.getenv("KAKAO_CALENDAR_ID", "primary"), "from": start_at, "to": end_at},
        {"Authorization": f"Bearer {token}"},
    )
    if result["ok"]:
        return {
            "events": result["json"].get("events", []),
            "message": "톡캘린더 일정을 조회했습니다.",
            "requested_range": {"start_at": start_at, "end_at": end_at},
        }
    return {
        "events": [],
        "message": "톡캘린더 일정 조회 API 호출에 실패했습니다.",
        "requested_range": {"start_at": start_at, "end_at": end_at},
        "error": result.get("error"),
    }


def send_message_to_me_if_configured(message_text: str, access_token: str = "", auth_url: str = "") -> dict[str, Any]:
    template_object = {
        "object_type": "text",
        "text": message_text[:200],
        "link": {
            "web_url": _public_base_url(),
            "mobile_web_url": _public_base_url(),
        },
        "button_title": "DailyRoute 보기",
    }
    if _mock_mode():
        return {
            "sent": False,
            "message_payload": {"template_object": template_object},
            "auth_required": False,
            "auth_url": auth_url,
            "warning": "ENABLE_REAL_KAKAO_APIS가 true가 아니어서 메시지 본문만 반환했습니다.",
        }
    token = access_token or os.getenv("KAKAO_ACCESS_TOKEN", "")
    if not token:
        return {
            "sent": False,
            "message_payload": {"template_object": template_object},
            "auth_required": True,
            "auth_url": auth_url,
            "warning": "카카오 로그인이 필요합니다. auth_url에서 동의하면 나에게 보내기를 시도할 수 있습니다.",
        }
    result = _form_post_json(
        KAKAO_TALK_MEMO_SEND_URL,
        {"template_object": json.dumps(template_object, ensure_ascii=False)},
        {"Authorization": f"Bearer {token}"},
    )
    if result["ok"] and result["json"].get("result_code") == 0:
        return {
            "sent": True,
            "message_payload": {"template_object": template_object},
            "auth_required": False,
            "auth_url": "",
            "warning": None,
        }
    return {
        "sent": False,
        "message_payload": {"template_object": template_object},
        "auth_required": result.get("status") in {401, 403},
        "auth_url": auth_url,
        "warning": "나에게 보내기 API 호출에 실패했습니다.",
        "error": result.get("error"),
    }


def _area_token(place: str) -> str:
    for area in ("강남", "역삼", "판교", "안양", "홍대", "신촌", "잠실", "분당", "수원", "서울"):
        if area in (place or ""):
            return area
    return _normalize_spaces(place)[:2]


def _haversine_km(start: dict[str, Any], end: dict[str, Any]) -> float:
    lat1 = radians(float(start.get("lat") or 0))
    lng1 = radians(float(start.get("lng") or 0))
    lat2 = radians(float(end.get("lat") or 0))
    lng2 = radians(float(end.get("lng") or 0))
    delta_lat = lat2 - lat1
    delta_lng = lng2 - lng1
    a = sin(delta_lat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(delta_lng / 2) ** 2
    return 6371.0 * 2 * asin(sqrt(a))


def _fallback_route_duration(origin: str, destination: str, waypoints: list[str], travel_mode: TravelMode) -> dict[str, Any]:
    locations = [origin, *waypoints, destination]
    total = 0
    for start, end in zip(locations, locations[1:]):
        start_area = _area_token(start)
        end_area = _area_token(end)
        if not start or not end:
            total += 40
        elif start_area == end_area:
            total += 15
        elif {start_area, end_area} == {"안양", "강남"}:
            total += 48
        elif start_area in {"강남", "역삼", "판교"} and end_area in {"강남", "역삼", "판교"}:
            total += 30
        else:
            total += 50
    multiplier = {"car": 1.0, "transit_estimate": 1.25, "walking_estimate": 2.8}.get(travel_mode, 1.0)
    return {
        "duration_minutes": max(1, int((total or 40) * multiplier)),
        "distance_meters": 0,
        "mode": {
            "car": "모의 차량 이동시간",
            "transit_estimate": "모의 대중교통 이동시간",
            "walking_estimate": "모의 도보 이동시간",
        }.get(travel_mode, "모의 이동시간"),
        "provider": "fallback",
        "travel_mode": travel_mode,
    }


def _coordinate_route_duration(origin: str, destination: str, waypoints: list[str], travel_mode: TravelMode) -> dict[str, Any]:
    coordinates = [resolve_address_or_place_to_coordinates(place) for place in [origin, *waypoints, destination]]
    if any(item.get("mock") for item in coordinates):
        return _fallback_route_duration(origin, destination, waypoints, travel_mode)
    total_km = sum(_haversine_km(start, end) for start, end in zip(coordinates, coordinates[1:]))
    if travel_mode == "walking_estimate":
        minutes = int((total_km / 4.5) * 60)
        mode = "카카오 Local 좌표 기반 도보 예상시간"
    else:
        minutes = int((total_km / 24) * 60) + 10
        mode = "카카오 Local 좌표 기반 대중교통 예상시간"
    return {
        "duration_minutes": max(1, minutes),
        "distance_meters": int(total_km * 1000),
        "mode": mode,
        "provider": "kakao_local_distance_estimate",
        "travel_mode": travel_mode,
        "note": "대중교통/도보는 공개 자동차 길찾기 API가 아니라 좌표 거리 기반 예상치입니다.",
    }


def _mobility_headers(api_key: str) -> dict[str, str]:
    return {"Authorization": f"KakaoAK {api_key}", "Content-Type": "application/json"}


def _coord_payload(coord: dict[str, Any], name: str) -> dict[str, Any]:
    return {
        "name": name,
        "x": float(coord["lng"]),
        "y": float(coord["lat"]),
    }


def _coord_query(coord: dict[str, Any], name: str) -> str:
    return f"{coord['lng']},{coord['lat']},name={name}"


def _mobility_route_result(
    route: dict[str, Any],
    provider: str,
    mode: str,
    travel_mode: TravelMode = "car",
) -> dict[str, Any] | None:
    summary = route.get("summary", {})
    if route.get("result_code", 0) != 0 or summary.get("duration") is None:
        return None
    return {
        "duration_minutes": max(1, int((int(summary.get("duration", 0)) + 59) // 60)),
        "distance_meters": int(summary.get("distance", 0) or 0),
        "mode": mode,
        "provider": provider,
        "travel_mode": travel_mode,
        "fare": summary.get("fare", {}),
    }


def _first_successful_mobility_result(
    result: dict[str, Any],
    provider: str,
    mode: str,
) -> dict[str, Any] | None:
    if not result.get("ok"):
        return None
    for route in result.get("json", {}).get("routes", []):
        parsed = _mobility_route_result(route, provider, mode)
        if parsed:
            return parsed
    return None


def _waypoints_route_duration(origin: str, destination: str, waypoints: list[str]) -> dict[str, Any]:
    api_key = _mobility_api_key()
    if _mock_mode() or not api_key:
        return _fallback_route_duration(origin, destination, waypoints, "car")
    coordinates = [resolve_address_or_place_to_coordinates(place) for place in [origin, *waypoints, destination]]
    if any(item.get("mock") for item in coordinates):
        return _fallback_route_duration(origin, destination, waypoints, "car")
    payload = {
        "origin": _coord_payload(coordinates[0], origin),
        "destination": _coord_payload(coordinates[-1], destination),
        "waypoints": [
            _coord_payload(coord, name)
            for coord, name in zip(coordinates[1:-1], waypoints)
        ],
        "priority": "RECOMMEND",
        "car_fuel": "GASOLINE",
        "car_hipass": False,
        "alternatives": False,
        "road_details": False,
        "summary": True,
    }
    result = _post_json(KAKAO_MOBILITY_WAYPOINTS_DIRECTIONS_URL, payload, _mobility_headers(api_key))
    parsed = _first_successful_mobility_result(
        result,
        "kakao_mobility_waypoints_directions",
        "카카오모빌리티 다중 경유지 자동차 길찾기",
    )
    if parsed:
        return parsed | {"waypoints": waypoints}
    return {
        **_fallback_route_duration(origin, destination, waypoints, "car"),
        "provider": "fallback_after_kakao_waypoints_error",
        "error": result.get("error"),
        "waypoints": waypoints,
    }


def _car_route_duration(origin: str, destination: str, waypoints: list[str]) -> dict[str, Any]:
    if waypoints:
        return _waypoints_route_duration(origin, destination, waypoints)
    api_key = _mobility_api_key()
    if _mock_mode() or not api_key:
        return _fallback_route_duration(origin, destination, waypoints, "car")
    coordinates = [resolve_address_or_place_to_coordinates(place) for place in [origin, *waypoints, destination]]
    if any(item.get("mock") for item in coordinates):
        return _fallback_route_duration(origin, destination, waypoints, "car")
    origin_coord = coordinates[0]
    destination_coord = coordinates[-1]
    waypoint_coords = coordinates[1:-1]
    params: dict[str, Any] = {
        "origin": _coord_query(origin_coord, origin),
        "destination": _coord_query(destination_coord, destination),
        "priority": "RECOMMEND",
        "summary": "true",
        "alternatives": "false",
        "road_details": "false",
    }
    if waypoint_coords:
        params["waypoints"] = "|".join(
            _coord_query(coord, place)
            for coord, place in zip(waypoint_coords, waypoints)
        )
    result = _get_json(
        KAKAO_MOBILITY_DIRECTIONS_URL,
        params,
        _mobility_headers(api_key),
    )
    parsed = _first_successful_mobility_result(
        result,
        "kakao_mobility_directions",
        "카카오모빌리티 자동차 길찾기",
    )
    if parsed:
        return parsed
    return {
        **_fallback_route_duration(origin, destination, waypoints, "car"),
        "provider": "fallback_after_kakao_mobility_error",
        "error": result.get("error"),
    }


def estimate_future_route_duration(
    origin: str,
    destination: str,
    departure_at: str,
    waypoints: list[str] | None = None,
) -> dict[str, Any]:
    waypoints = waypoints or []
    api_key = _mobility_api_key()
    if _mock_mode() or not api_key:
        return _fallback_route_duration(origin, destination, waypoints, "car") | {
            "provider": "fallback_future_route",
            "departure_time": departure_at,
        }
    coordinates = [resolve_address_or_place_to_coordinates(place) for place in [origin, *waypoints, destination]]
    if any(item.get("mock") for item in coordinates):
        return _fallback_route_duration(origin, destination, waypoints, "car") | {
            "provider": "fallback_future_route",
            "departure_time": departure_at,
        }
    departure = _parse_iso_datetime(departure_at)
    if not departure:
        departure = datetime.now(KST)
    if departure.tzinfo is None:
        departure = departure.replace(tzinfo=KST)
    departure_text = departure.astimezone(KST).strftime("%Y%m%d%H%M")
    params: dict[str, Any] = {
        "origin": _coord_query(coordinates[0], origin),
        "destination": _coord_query(coordinates[-1], destination),
        "departure_time": departure_text,
        "priority": "RECOMMEND",
        "summary": "true",
        "alternatives": "false",
        "road_details": "false",
    }
    if len(coordinates) > 2:
        params["waypoints"] = "|".join(
            _coord_query(coord, place)
            for coord, place in zip(coordinates[1:-1], waypoints)
        )
    result = _get_json(KAKAO_MOBILITY_FUTURE_DIRECTIONS_URL, params, _mobility_headers(api_key))
    parsed = _first_successful_mobility_result(
        result,
        "kakao_mobility_future_directions",
        "카카오모빌리티 미래 운행 정보 자동차 길찾기",
    )
    if parsed:
        return parsed | {"departure_time": departure_text}
    return {
        **_fallback_route_duration(origin, destination, waypoints, "car"),
        "provider": "fallback_after_kakao_future_error",
        "departure_time": departure_text,
        "error": result.get("error"),
    }


def estimate_route_duration(
    origin: str,
    destination: str,
    waypoints: list[str] | None = None,
    travel_mode: TravelMode = "car",
) -> dict[str, Any]:
    waypoints = waypoints or []
    if travel_mode == "car":
        return _car_route_duration(origin, destination, waypoints)
    if _mock_mode() or not _local_api_key():
        return _fallback_route_duration(origin, destination, waypoints, travel_mode)
    return _coordinate_route_duration(origin, destination, waypoints, travel_mode)


def _errand_category(errand: str) -> tuple[str, str]:
    if any(term in errand for term in ("약", "감기약", "약국")):
        return "pharmacy", "약국"
    if any(term in errand for term in ("커피", "카페", "작업")):
        return "cafe", "카페"
    if any(term in errand for term in ("프린트", "복사", "출력")):
        return "print_shop", "프린트샵"
    if any(term in errand for term in ("다이소", "생활용품")):
        return "daily_goods", "생활용품점"
    if "세탁" in errand:
        return "laundry", "세탁소"
    return "other", "생활 편의 장소"


def search_place_keyword(keyword: str, area: str = "") -> list[dict[str, Any]]:
    search_area = area or "주변"
    local_key = _local_api_key()
    if _mock_mode() or not local_key:
        return [
            {
                "name": f"{search_area} {keyword} 후보",
                "keyword": keyword,
                "address": f"{search_area} 인근",
                "mock": True,
            }
        ]
    result = _get_json(
        KAKAO_LOCAL_KEYWORD_URL,
        {"query": f"{search_area} {keyword}", "size": 5},
        {"Authorization": f"KakaoAK {local_key}"},
    )
    if result["ok"]:
        places = []
        for document in result["json"].get("documents", []):
            places.append(
                {
                    "name": document.get("place_name", ""),
                    "keyword": keyword,
                    "address": document.get("road_address_name") or document.get("address_name", ""),
                    "place_url": document.get("place_url", ""),
                    "x": document.get("x", ""),
                    "y": document.get("y", ""),
                    "mock": False,
                }
            )
        if places:
            return places
    return [
        {
            "name": f"{search_area} {keyword} 검색 후보",
            "keyword": keyword,
            "address": f"{search_area} 인근",
            "mock": False,
            "warning": result.get("error") if "result" in locals() else None,
        }
    ]


def resolve_address_or_place_to_coordinates(place_text: str) -> dict[str, Any]:
    local_key = _local_api_key()
    if _mock_mode() or not local_key:
        token = _area_token(place_text)
        return {
            "place_text": place_text,
            "lat": 37.5,
            "lng": 127.0,
            "area_token": token,
            "mock": True,
            "warning": "장소 API 키가 없어 모의 좌표를 반환했습니다.",
        }
    result = _get_json(
        KAKAO_LOCAL_ADDRESS_URL,
        {"query": place_text, "size": 1},
        {"Authorization": f"KakaoAK {local_key}"},
    )
    if result["ok"] and result["json"].get("documents"):
        document = result["json"]["documents"][0]
        return {
            "place_text": place_text,
            "lat": float(document.get("y") or 0),
            "lng": float(document.get("x") or 0),
            "area_token": _area_token(document.get("address_name", place_text)),
            "mock": False,
            "warning": None,
        }
    keyword_result = _get_json(
        KAKAO_LOCAL_KEYWORD_URL,
        {"query": place_text, "size": 1},
        {"Authorization": f"KakaoAK {local_key}"},
    )
    if keyword_result["ok"] and keyword_result["json"].get("documents"):
        document = keyword_result["json"]["documents"][0]
        return {
            "place_text": place_text,
            "lat": float(document.get("y") or 0),
            "lng": float(document.get("x") or 0),
            "area_token": _area_token(document.get("address_name", place_text)),
            "mock": False,
            "warning": None,
            "place_name": document.get("place_name", ""),
            "address": document.get("road_address_name") or document.get("address_name", ""),
        }
    return {
        "place_text": place_text,
        "lat": 37.5,
        "lng": 127.0,
        "area_token": _area_token(place_text),
        "mock": False,
        "warning": "장소 좌표 조회 API 호출에 실패해 기본 좌표를 반환했습니다.",
    }


def search_places_by_category_or_keyword(
    origin: str,
    destination: str,
    errand: str,
    preferred_area: str = "",
) -> list[dict[str, Any]]:
    category, label = _errand_category(errand)
    area = preferred_area or _area_token(destination) or _area_token(origin)
    if _mock_mode() or not _local_api_key():
        return [
            {
                "name": f"{area} 추천 {label}",
                "category": category,
                "address": f"{area} 인근",
                "estimated_detour_minutes": 8 if category != "other" else 12,
                "mock": True,
            }
        ]
    candidates = search_place_keyword(label, area)
    return [
        {
            "name": candidate.get("name", ""),
            "category": category,
            "address": candidate.get("address", ""),
            "place_url": candidate.get("place_url", ""),
            "estimated_detour_minutes": 10,
            "mock": candidate.get("mock", False),
        }
        for candidate in candidates[:3]
    ]


class DailyRouteService:
    def __init__(self, db_path: str | Path = "data/dailyroute_guard.db") -> None:
        self.db_path = _resolve_db_path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.init_database()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        return connection

    def init_database(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS schedules (
                    id TEXT PRIMARY KEY,
                    workspace_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    start_at TEXT NOT NULL DEFAULT '',
                    end_at TEXT NOT NULL DEFAULT '',
                    date_text TEXT NOT NULL DEFAULT '',
                    time_text TEXT NOT NULL DEFAULT '',
                    location_text TEXT NOT NULL DEFAULT '',
                    schedule_type TEXT NOT NULL,
                    source_type TEXT NOT NULL,
                    reminder_minutes INTEGER NOT NULL DEFAULT 60,
                    raw_text TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS route_profiles (
                    id TEXT PRIMARY KEY,
                    workspace_id TEXT NOT NULL,
                    profile_name TEXT NOT NULL,
                    origin TEXT NOT NULL DEFAULT '',
                    destination TEXT NOT NULL DEFAULT '',
                    preferences_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS routines (
                    id TEXT PRIMARY KEY,
                    workspace_id TEXT NOT NULL,
                    routine_name TEXT NOT NULL,
                    routine_type TEXT NOT NULL,
                    rule_text TEXT NOT NULL,
                    active_days_json TEXT NOT NULL DEFAULT '[]',
                    origin TEXT NOT NULL DEFAULT '',
                    destination TEXT NOT NULL DEFAULT '',
                    preferred_buffer_minutes INTEGER,
                    avoid_conditions_json TEXT NOT NULL DEFAULT '[]',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS errands (
                    id TEXT PRIMARY KEY,
                    workspace_id TEXT NOT NULL,
                    errand_text TEXT NOT NULL,
                    category TEXT NOT NULL DEFAULT '',
                    preferred_area TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS route_watch_jobs (
                    id TEXT PRIMARY KEY,
                    workspace_id TEXT NOT NULL,
                    schedule_id TEXT NOT NULL,
                    origin TEXT NOT NULL,
                    check_minutes_before INTEGER NOT NULL DEFAULT 60,
                    buffer_minutes INTEGER NOT NULL DEFAULT 15,
                    notify_channel TEXT NOT NULL DEFAULT 'log_only',
                    status TEXT NOT NULL DEFAULT 'active',
                    next_check_time TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS route_check_logs (
                    id TEXT PRIMARY KEY,
                    workspace_id TEXT NOT NULL,
                    watch_id TEXT NOT NULL,
                    schedule_id TEXT NOT NULL,
                    risk_level TEXT NOT NULL,
                    message TEXT NOT NULL,
                    estimated_travel_minutes INTEGER NOT NULL,
                    remaining_minutes INTEGER NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS oauth_states (
                    state TEXT PRIMARY KEY,
                    workspace_id TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    redirect_uri TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS oauth_tokens (
                    workspace_id TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    access_token TEXT NOT NULL,
                    refresh_token TEXT NOT NULL DEFAULT '',
                    token_type TEXT NOT NULL DEFAULT 'bearer',
                    scope TEXT NOT NULL DEFAULT '',
                    expires_at TEXT NOT NULL DEFAULT '',
                    refresh_token_expires_at TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (workspace_id, provider)
                );

                CREATE INDEX IF NOT EXISTS idx_schedules_workspace_start
                ON schedules (workspace_id, start_at);

                CREATE INDEX IF NOT EXISTS idx_route_watch_workspace
                ON route_watch_jobs (workspace_id, next_check_time);

                CREATE INDEX IF NOT EXISTS idx_oauth_states_created
                ON oauth_states (provider, created_at);
                """
            )
            connection.commit()

    def _fetch_all(self, query: str, params: tuple[Any, ...]) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(query, params).fetchall()
        return [dict(row) for row in rows]

    def _fetch_one(self, query: str, params: tuple[Any, ...]) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(query, params).fetchone()
        return dict(row) if row else None

    def _save_kakao_token(self, workspace_id: str, token_response: dict[str, Any]) -> dict[str, Any]:
        normalized_workspace = workspace_id or DEFAULT_WORKSPACE_ID
        now = _now_utc()
        expires_in = int(token_response.get("expires_in") or 0)
        refresh_expires_in = int(token_response.get("refresh_token_expires_in") or 0)
        expires_at = (now + timedelta(seconds=expires_in)).isoformat(timespec="seconds") if expires_in else ""
        refresh_expires_at = (
            now + timedelta(seconds=refresh_expires_in)
        ).isoformat(timespec="seconds") if refresh_expires_in else ""
        previous = self._fetch_one(
            "SELECT * FROM oauth_tokens WHERE workspace_id = ? AND provider = 'kakao'",
            (normalized_workspace,),
        )
        refresh_token = token_response.get("refresh_token") or (previous or {}).get("refresh_token", "")
        refresh_token_expires_at = refresh_expires_at or (previous or {}).get("refresh_token_expires_at", "")
        created_at = (previous or {}).get("created_at", now.isoformat(timespec="seconds"))
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO oauth_tokens (
                    workspace_id, provider, access_token, refresh_token, token_type,
                    scope, expires_at, refresh_token_expires_at, created_at, updated_at
                ) VALUES (?, 'kakao', ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(workspace_id, provider) DO UPDATE SET
                    access_token = excluded.access_token,
                    refresh_token = excluded.refresh_token,
                    token_type = excluded.token_type,
                    scope = excluded.scope,
                    expires_at = excluded.expires_at,
                    refresh_token_expires_at = excluded.refresh_token_expires_at,
                    updated_at = excluded.updated_at
                """,
                (
                    normalized_workspace,
                    token_response.get("access_token", ""),
                    refresh_token,
                    token_response.get("token_type", "bearer"),
                    token_response.get("scope", ""),
                    expires_at,
                    refresh_token_expires_at,
                    created_at,
                    now.isoformat(timespec="seconds"),
                ),
            )
            connection.commit()
        return {
            "stored": True,
            "workspace_id": normalized_workspace,
            "expires_at": expires_at,
            "refresh_token_expires_at": refresh_token_expires_at,
            "scope": token_response.get("scope", ""),
        }

    def build_kakao_oauth_login_url(self, workspace_id: str, redirect_uri: str) -> dict[str, Any]:
        rest_key = os.getenv("KAKAO_REST_API_KEY", "")
        normalized_workspace = workspace_id or DEFAULT_WORKSPACE_ID
        if not rest_key:
            return {
                "configured": False,
                "login_url": "",
                "warning": "KAKAO_REST_API_KEY 환경변수가 없어 카카오 로그인 URL을 만들 수 없습니다.",
            }
        if not redirect_uri:
            return {
                "configured": False,
                "login_url": "",
                "warning": "KAKAO_REDIRECT_URI 또는 PUBLIC_BASE_URL 설정이 필요합니다.",
            }
        state = f"state_{uuid4().hex}"
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO oauth_states (state, workspace_id, provider, redirect_uri, created_at)
                VALUES (?, ?, 'kakao', ?, ?)
                """,
                (state, normalized_workspace, redirect_uri, _now_iso()),
            )
            connection.commit()
        params = {
            "response_type": "code",
            "client_id": rest_key,
            "redirect_uri": redirect_uri,
            "state": state,
        }
        scopes = _normalize_spaces(os.getenv("KAKAO_OAUTH_SCOPES", "talk_message"))
        if scopes:
            params["scope"] = scopes
        return {
            "configured": True,
            "login_url": f"{KAKAO_OAUTH_AUTHORIZE_URL}?{urllib.parse.urlencode(params)}",
            "state": state,
            "workspace_id": normalized_workspace,
            "redirect_uri": redirect_uri,
            "scope": scopes,
            "warning": None,
        }

    def complete_kakao_oauth(self, code: str, state: str, redirect_uri: str) -> dict[str, Any]:
        if not code:
            return {"success": False, "summary": "authorization code가 없습니다.", "warning": "카카오 로그인 callback 값을 확인하세요."}
        saved_state = self._fetch_one(
            "SELECT * FROM oauth_states WHERE state = ? AND provider = 'kakao'",
            (state,),
        )
        if not saved_state:
            return {"success": False, "summary": "OAuth state를 찾지 못했습니다.", "warning": "로그인 URL을 다시 발급해 주세요."}
        with self._connect() as connection:
            connection.execute("DELETE FROM oauth_states WHERE state = ?", (state,))
            connection.commit()

        rest_key = os.getenv("KAKAO_REST_API_KEY", "")
        if not rest_key:
            return {"success": False, "summary": "KAKAO_REST_API_KEY가 없습니다.", "warning": "환경변수를 먼저 설정하세요."}
        token_request = {
            "grant_type": "authorization_code",
            "client_id": rest_key,
            "redirect_uri": redirect_uri or saved_state["redirect_uri"],
            "code": code,
        }
        client_secret = os.getenv("KAKAO_CLIENT_SECRET", "")
        if client_secret:
            token_request["client_secret"] = client_secret
        token_result = _form_post_json(KAKAO_OAUTH_TOKEN_URL, token_request)
        if not token_result["ok"]:
            return {
                "success": False,
                "summary": "카카오 token 발급에 실패했습니다.",
                "warning": "Redirect URI, REST API key, Client Secret 설정을 확인하세요.",
                "error": token_result.get("error"),
            }
        stored = self._save_kakao_token(saved_state["workspace_id"], token_result["json"])
        return {
            "success": True,
            "summary": "카카오 access_token과 refresh_token을 저장했습니다.",
            "workspace_id": saved_state["workspace_id"],
            "scope": stored.get("scope", ""),
            "expires_at": stored.get("expires_at", ""),
            "refresh_token_expires_at": stored.get("refresh_token_expires_at", ""),
        }

    def kakao_auth_status(self, workspace_id: str) -> dict[str, Any]:
        normalized_workspace = workspace_id or DEFAULT_WORKSPACE_ID
        if os.getenv("KAKAO_ACCESS_TOKEN"):
            return {
                "authenticated": True,
                "source": "env",
                "workspace_id": normalized_workspace,
                "expires_at": "",
                "scope": "",
                "login_url": "",
            }
        token = self._fetch_one(
            "SELECT * FROM oauth_tokens WHERE workspace_id = ? AND provider = 'kakao'",
            (normalized_workspace,),
        )
        return {
            "authenticated": token is not None,
            "source": "db" if token else "none",
            "workspace_id": normalized_workspace,
            "expires_at": token.get("expires_at", "") if token else "",
            "scope": token.get("scope", "") if token else "",
            "login_url": "" if token else _kakao_login_url_for_workspace(normalized_workspace),
        }

    def get_kakao_access_token(self, workspace_id: str) -> dict[str, Any]:
        normalized_workspace = workspace_id or DEFAULT_WORKSPACE_ID
        env_token = os.getenv("KAKAO_ACCESS_TOKEN", "")
        if env_token:
            return {"available": True, "access_token": env_token, "source": "env", "warning": None}
        token = self._fetch_one(
            "SELECT * FROM oauth_tokens WHERE workspace_id = ? AND provider = 'kakao'",
            (normalized_workspace,),
        )
        if not token:
            return {
                "available": False,
                "access_token": "",
                "source": "none",
                "warning": "카카오 로그인이 필요합니다.",
                "auth_url": _kakao_login_url_for_workspace(normalized_workspace),
            }
        expires_at = _parse_iso_datetime(token.get("expires_at", ""))
        if expires_at and expires_at <= _now_utc() + timedelta(minutes=5) and token.get("refresh_token"):
            refreshed = self._refresh_kakao_token(normalized_workspace, token["refresh_token"])
            if refreshed.get("available"):
                return refreshed
        return {
            "available": True,
            "access_token": token.get("access_token", ""),
            "source": "db",
            "warning": None,
            "auth_url": "",
        }

    def _refresh_kakao_token(self, workspace_id: str, refresh_token: str) -> dict[str, Any]:
        rest_key = os.getenv("KAKAO_REST_API_KEY", "")
        if not rest_key:
            return {"available": False, "access_token": "", "source": "db", "warning": "KAKAO_REST_API_KEY가 없어 토큰 갱신을 못했습니다."}
        refresh_request = {
            "grant_type": "refresh_token",
            "client_id": rest_key,
            "refresh_token": refresh_token,
        }
        client_secret = os.getenv("KAKAO_CLIENT_SECRET", "")
        if client_secret:
            refresh_request["client_secret"] = client_secret
        refresh_result = _form_post_json(KAKAO_OAUTH_TOKEN_URL, refresh_request)
        if not refresh_result["ok"]:
            return {
                "available": False,
                "access_token": "",
                "source": "db",
                "warning": "카카오 access_token 갱신에 실패했습니다. 다시 로그인해 주세요.",
                "auth_url": _kakao_login_url_for_workspace(workspace_id),
                "error": refresh_result.get("error"),
            }
        stored = self._save_kakao_token(workspace_id, refresh_result["json"])
        return {
            "available": True,
            "access_token": refresh_result["json"].get("access_token", ""),
            "source": "db_refresh",
            "warning": None,
            "expires_at": stored.get("expires_at", ""),
            "auth_url": "",
        }

    def extract_schedule_from_text(
        self,
        workspace_id: str,
        text: str,
        source_type: ScheduleSourceType,
        default_timezone: str,
        reference_date: str,
        image_base64: str = "",
        image_url: str = "",
    ) -> dict[str, Any]:
        warnings: list[str] = []
        if image_base64 or image_url:
            warnings.append("MVP에서는 서버 내부 이미지 OCR을 수행하지 않습니다. 이미지에서 추출된 OCR 텍스트를 text에 넣어 주세요.")
        if not _normalize_spaces(text):
            return {
                "extracted_count": 0,
                "schedules": [],
                "warnings": warnings + ["추출할 텍스트가 비어 있습니다."],
                "summary": "일정 후보를 찾지 못했습니다.",
            }

        schedules = [
            _extract_schedule_candidate(piece, source_type, reference_date)
            for piece in _split_schedule_text(text)
        ]
        schedules = [schedule for schedule in schedules if schedule["date_text"] or schedule["time_text"] or schedule["title"]]
        return {
            "extracted_count": len(schedules),
            "schedules": schedules,
            "warnings": warnings,
            "summary": f"텍스트에서 일정 후보 {len(schedules)}건을 추출했습니다.",
        }

    def _find_schedule_conflicts(
        self,
        workspace_id: str,
        title: str,
        start_at: str,
        end_at: str,
        date_text: str,
        time_text: str,
        location_text: str,
    ) -> list[dict[str, Any]]:
        existing = self._fetch_all(
            "SELECT * FROM schedules WHERE workspace_id = ? ORDER BY start_at",
            (workspace_id,),
        )
        conflicts: list[dict[str, Any]] = []
        for schedule in existing:
            same_text_time = _same_date_time_text(schedule, date_text, time_text, start_at)
            overlap = _overlaps(schedule.get("start_at", ""), schedule.get("end_at", ""), start_at, end_at)
            same_signature = (
                _compact_text(schedule.get("title", "")) == _compact_text(title)
                and _compact_text(schedule.get("location_text", "")) == _compact_text(location_text)
                and same_text_time
            )
            if same_text_time or overlap or same_signature:
                conflicts.append(
                    {
                        "schedule_id": schedule["id"],
                        "title": schedule["title"],
                        "start_at": schedule["start_at"],
                        "end_at": schedule["end_at"],
                        "date_text": schedule["date_text"],
                        "time_text": schedule["time_text"],
                        "location_text": schedule["location_text"],
                        "reason": "같은 시간 또는 겹치는 일정입니다.",
                    }
                )
        return conflicts

    def save_schedule(
        self,
        workspace_id: str,
        title: str,
        start_at: str,
        end_at: str,
        date_text: str,
        time_text: str,
        location_text: str,
        schedule_type: ScheduleType,
        source_type: ScheduleSourceType,
        reminder_minutes: int,
        save_to_talk_calendar: bool,
        allow_conflict: bool,
        raw_text: str = "",
    ) -> dict[str, Any]:
        normalized_workspace = workspace_id or DEFAULT_WORKSPACE_ID
        resolved_start_at = start_at
        if not resolved_start_at:
            _, date_iso = _extract_date_info(date_text)
            _, time_hm = _extract_time_info(time_text)
            resolved_start_at = _build_datetime(date_iso, time_hm)
        resolved_end_at = end_at or _infer_end_at(resolved_start_at, schedule_type)

        conflict_candidates = self._find_schedule_conflicts(
            normalized_workspace,
            title,
            resolved_start_at,
            resolved_end_at,
            date_text,
            time_text,
            location_text,
        )
        conflict_detected = bool(conflict_candidates)
        if conflict_detected and not allow_conflict:
            first = conflict_candidates[0]
            when_text = " ".join(
                part
                for part in (
                    date_text or first.get("date_text", ""),
                    time_text or first.get("time_text", ""),
                )
                if part
            )
            when_text = when_text or "같은 시간대"
            warning = (
                f"이미 {when_text}에 '{first['title']}' 일정이 저장되어 있습니다. "
                "같은 시간에 새 일정을 추가해도 되는지 확인한 뒤 allow_conflict=true로 다시 저장하세요."
            )
            return {
                "saved": False,
                "schedule_id": "",
                "summary": "겹치는 일정이 있어 저장하지 않았습니다.",
                "conflict_detected": True,
                "conflict_candidates": conflict_candidates,
                "warning": warning,
                "talk_calendar_payload": {},
                "next_recommended_action": "기존 일정을 조정하거나 allow_conflict=true로 다시 저장하세요.",
            }

        schedule_id = f"sch_{uuid4().hex[:10]}"
        now = _now_iso()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO schedules (
                    id, workspace_id, title, start_at, end_at, date_text, time_text,
                    location_text, schedule_type, source_type, reminder_minutes, raw_text,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    schedule_id,
                    normalized_workspace,
                    _normalize_spaces(title),
                    resolved_start_at,
                    resolved_end_at,
                    _normalize_spaces(date_text),
                    _normalize_spaces(time_text),
                    _normalize_spaces(location_text),
                    schedule_type,
                    source_type,
                    reminder_minutes,
                    _normalize_spaces(raw_text),
                    now,
                    now,
                ),
            )
            connection.commit()

        saved_schedule = {
            "id": schedule_id,
            "title": title,
            "start_at": resolved_start_at,
            "end_at": resolved_end_at,
            "location_text": location_text,
            "reminder_minutes": reminder_minutes,
        }
        talk_payload = build_talk_calendar_event_payload(saved_schedule) if save_to_talk_calendar else {}
        token_result = self.get_kakao_access_token(normalized_workspace) if save_to_talk_calendar else {}
        calendar_result = (
            create_talk_calendar_event_if_configured(
                talk_payload,
                access_token=token_result.get("access_token", ""),
                auth_url=token_result.get("auth_url", _kakao_login_url_for_workspace(normalized_workspace)),
            )
            if save_to_talk_calendar
            else {}
        )
        warning = ""
        if conflict_detected:
            first = conflict_candidates[0]
            when_text = " ".join(
                part
                for part in (
                    date_text or first.get("date_text", ""),
                    time_text or first.get("time_text", ""),
                )
                if part
            )
            warning = (
                f"이미 {when_text or '같은 시간대'}에 '{first['title']}' 일정이 있지만 "
                "allow_conflict=true라서 새 일정도 저장했습니다."
            )
        if calendar_result.get("message"):
            warning = f"{warning} {calendar_result['message']}".strip()

        return {
            "saved": True,
            "schedule_id": schedule_id,
            "summary": f"'{title}' 일정을 저장했습니다.",
            "conflict_detected": conflict_detected,
            "conflict_candidates": conflict_candidates,
            "warning": warning or None,
            "talk_calendar_payload": talk_payload,
            "calendar_result": calendar_result,
            "kakao_login_url": calendar_result.get("auth_url", "") if calendar_result else "",
            "next_recommended_action": "일정 장소가 있다면 check_day_feasibility로 이동 가능성을 확인하세요.",
        }

    def _schedules_for_date(self, workspace_id: str, target_date: str) -> list[dict[str, Any]]:
        rows = self._fetch_all(
            "SELECT * FROM schedules WHERE workspace_id = ? ORDER BY start_at, time_text",
            (workspace_id or DEFAULT_WORKSPACE_ID,),
        )
        return [
            row
            for row in rows
            if (row.get("start_at", "").startswith(target_date) or row.get("date_text") == target_date)
        ]

    def check_day_feasibility(
        self,
        workspace_id: str,
        target_date: str,
        default_origin: str,
        travel_mode: TravelMode,
        buffer_minutes: int,
    ) -> dict[str, Any]:
        schedules = self._schedules_for_date(workspace_id, target_date)
        warnings: list[str] = []
        route_checks: list[dict[str, Any]] = []
        impossible_segments: list[dict[str, Any]] = []
        previous = None
        for schedule in schedules:
            if previous is None:
                previous = schedule
                if not schedule.get("location_text"):
                    warnings.append(f"'{schedule['title']}' 일정의 장소 정보가 부족합니다.")
                continue
            prev_location = previous.get("location_text") or default_origin
            next_location = schedule.get("location_text")
            if not prev_location or not next_location:
                warnings.append(f"'{previous['title']}' → '{schedule['title']}' 구간의 장소 정보가 부족합니다.")
                previous = schedule
                continue

            prev_end = _parse_iso_datetime(previous.get("end_at", ""))
            next_start = _parse_iso_datetime(schedule.get("start_at", ""))
            available_gap = int((next_start - prev_end).total_seconds() // 60) if prev_end and next_start else 0
            route = estimate_route_duration(prev_location, next_location, travel_mode=travel_mode)
            required = route["duration_minutes"] + buffer_minutes
            risk = required > available_gap
            check = {
                "from_schedule": previous["title"],
                "to_schedule": schedule["title"],
                "origin": prev_location,
                "destination": next_location,
                "available_gap_minutes": available_gap,
                "estimated_travel_minutes": route["duration_minutes"],
                "distance_meters": route.get("distance_meters", 0),
                "buffer_minutes": buffer_minutes,
                "provider_mode": route["mode"],
                "provider": route.get("provider", ""),
                "travel_mode": route.get("travel_mode", travel_mode),
                "risk": risk,
            }
            route_checks.append(check)
            if risk:
                message = (
                    f"{prev_location}에서 {next_location}까지 {route['mode']} 기준 예상 이동 시간이 {route['duration_minutes']}분인데 "
                    f"일정 사이 여유가 {available_gap}분뿐이라 지각 가능성이 높습니다."
                )
                warnings.append(message)
                impossible_segments.append(check | {"message": message})
            previous = schedule

        day_risk_level = "high" if impossible_segments else "medium" if warnings else "low"
        return {
            "date": target_date,
            "feasible": not impossible_segments,
            "day_risk_level": day_risk_level,
            "warnings": warnings,
            "route_checks": route_checks,
            "impossible_segments": impossible_segments,
            "recommended_adjustments": ["일정 간격을 늘리거나 출발 시간을 앞당기세요."] if impossible_segments else [],
            "summary": f"{target_date} 일정 {len(schedules)}건을 기준으로 이동 가능성을 확인했습니다.",
        }

    def find_places_on_route(
        self,
        workspace_id: str,
        origin: str,
        destination: str,
        errands: list[str],
        max_detour_minutes: int,
        preferred_area: str,
    ) -> dict[str, Any]:
        if _mock_mode() or not _local_api_key():
            selected_places: list[dict[str, Any]] = []
            rejected_places: list[dict[str, Any]] = []
            for errand in errands:
                candidates = search_places_by_category_or_keyword(origin, destination, errand, preferred_area)
                best = candidates[0] if candidates else None
                if best and best["estimated_detour_minutes"] <= max_detour_minutes:
                    selected_places.append(best | {"errand": errand})
                elif best:
                    rejected_places.append(best | {"errand": errand, "reason": "허용 우회 시간 초과"})

            stops = [place["name"] for place in selected_places]
            recommended_route = " → ".join([origin, *stops, destination])
            estimated_extra_time = sum(place["estimated_detour_minutes"] for place in selected_places)
            return {
                "recommended_route": recommended_route,
                "selected_places": selected_places,
                "rejected_places": rejected_places,
                "estimated_extra_time": estimated_extra_time,
                "route_evaluation": {"provider": "fallback", "reason": "API 키가 없어 모의 경유지 추천을 사용했습니다."},
                "warning": "카카오 Local API 키가 없어 모의 장소 추천을 반환했습니다.",
                "summary": f"{origin}에서 {destination}까지 {len(selected_places)}개 경유지를 추천합니다.",
            }

        direct_route = estimate_route_duration(origin, destination, travel_mode="car")
        candidate_groups: list[list[dict[str, Any]]] = []
        all_candidates: list[dict[str, Any]] = []
        for errand in errands:
            candidates = [
                candidate | {"errand": errand}
                for candidate in search_places_by_category_or_keyword(origin, destination, errand, preferred_area)[:3]
            ]
            if candidates:
                candidate_groups.append(candidates)
                all_candidates.extend(candidates)

        if not candidate_groups:
            return {
                "recommended_route": f"{origin} → {destination}",
                "selected_places": [],
                "rejected_places": [],
                "estimated_extra_time": 0,
                "route_evaluation": {"provider": "none", "reason": "조건에 맞는 경유지 후보를 찾지 못했습니다."},
                "warning": "경유지 후보를 찾지 못했습니다.",
                "summary": "추천할 경유지가 없습니다.",
            }

        best_plan: dict[str, Any] | None = None
        evaluated_count = 0
        for combo in product(*candidate_groups):
            evaluated_count += 1
            if evaluated_count > 12:
                break
            waypoint_names = [place["name"] for place in combo]
            route = estimate_route_duration(origin, destination, waypoints=waypoint_names, travel_mode="car")
            extra_minutes = max(0, route["duration_minutes"] - direct_route["duration_minutes"])
            plan = {
                "places": list(combo),
                "waypoint_names": waypoint_names,
                "route": route,
                "extra_minutes": extra_minutes,
            }
            if best_plan is None or extra_minutes < best_plan["extra_minutes"]:
                best_plan = plan

        selected_places = list(best_plan["places"]) if best_plan else []
        selected_names = {place["name"] for place in selected_places}
        rejected_places = [
            place | {"reason": "선택 경로보다 우회 시간이 큽니다."}
            for place in all_candidates
            if place["name"] not in selected_names
        ]
        estimated_extra_time = int(best_plan["extra_minutes"]) if best_plan else 0
        if estimated_extra_time > max_detour_minutes:
            warning = f"가장 나은 경유 조합도 {estimated_extra_time}분 정도 우회가 필요합니다."
        else:
            warning = None
        stops = [place["name"] for place in selected_places]
        recommended_route = " → ".join([origin, *stops, destination])
        return {
            "recommended_route": recommended_route,
            "selected_places": selected_places,
            "rejected_places": rejected_places,
            "estimated_extra_time": estimated_extra_time,
            "route_evaluation": {
                "direct_route": direct_route,
                "selected_route": best_plan["route"] if best_plan else {},
                "evaluated_combinations": min(evaluated_count, 12),
            },
            "warning": warning,
            "summary": f"{origin}에서 {destination}까지 {len(selected_places)}개 경유지를 포함한 최소 우회 경로를 추천합니다.",
        }

    def save_route_profile(
        self,
        workspace_id: str,
        profile_name: str,
        origin: str,
        destination: str,
        preferences: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        normalized_workspace = workspace_id or DEFAULT_WORKSPACE_ID
        route_profile_id = f"profile_{uuid4().hex[:10]}"
        now = _now_iso()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO route_profiles (
                    id, workspace_id, profile_name, origin, destination,
                    preferences_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    route_profile_id,
                    normalized_workspace,
                    _normalize_spaces(profile_name),
                    _normalize_spaces(origin),
                    _normalize_spaces(destination),
                    json.dumps(preferences or {}, ensure_ascii=False),
                    now,
                    now,
                ),
            )
            connection.commit()
        return {
            "saved": True,
            "profile_id": route_profile_id,
            "summary": f"'{profile_name}' 동선 프로필을 저장했습니다.",
            "profile": {
                "id": route_profile_id,
                "workspace_id": normalized_workspace,
                "profile_name": _normalize_spaces(profile_name),
                "origin": _normalize_spaces(origin),
                "destination": _normalize_spaces(destination),
                "preferences": preferences or {},
                "created_at": now,
                "updated_at": now,
            },
        }

    def list_route_profiles(self, workspace_id: str, limit: int) -> dict[str, Any]:
        normalized_workspace = workspace_id or DEFAULT_WORKSPACE_ID
        rows = self._fetch_all(
            """
            SELECT * FROM route_profiles
            WHERE workspace_id = ?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (normalized_workspace, limit),
        )
        profiles = []
        for row in rows:
            try:
                preferences = json.loads(row.get("preferences_json") or "{}")
            except json.JSONDecodeError:
                preferences = {}
            profiles.append(
                {
                    "id": row["id"],
                    "workspace_id": row["workspace_id"],
                    "profile_name": row["profile_name"],
                    "origin": row["origin"],
                    "destination": row["destination"],
                    "preferences": preferences,
                    "created_at": row["created_at"],
                    "updated_at": row["updated_at"],
                }
            )
        return {
            "profiles": profiles,
            "summary": f"동선 프로필 {len(profiles)}건을 조회했습니다.",
        }

    def save_errand(
        self,
        workspace_id: str,
        errand_text: str,
        category: str,
        preferred_area: str,
    ) -> dict[str, Any]:
        normalized_workspace = workspace_id or DEFAULT_WORKSPACE_ID
        errand_id = f"errand_{uuid4().hex[:10]}"
        inferred_category, label = _errand_category(errand_text)
        resolved_category = _normalize_spaces(category) or inferred_category
        now = _now_iso()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO errands (
                    id, workspace_id, errand_text, category, preferred_area, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    errand_id,
                    normalized_workspace,
                    _normalize_spaces(errand_text),
                    resolved_category,
                    _normalize_spaces(preferred_area),
                    now,
                ),
            )
            connection.commit()
        return {
            "saved": True,
            "errand_id": errand_id,
            "summary": f"'{errand_text}' 심부름을 저장했습니다.",
            "errand": {
                "id": errand_id,
                "workspace_id": normalized_workspace,
                "errand_text": _normalize_spaces(errand_text),
                "category": resolved_category,
                "category_label": label,
                "preferred_area": _normalize_spaces(preferred_area),
                "created_at": now,
            },
        }

    def list_errands(self, workspace_id: str, limit: int) -> dict[str, Any]:
        normalized_workspace = workspace_id or DEFAULT_WORKSPACE_ID
        errands = self._fetch_all(
            """
            SELECT * FROM errands
            WHERE workspace_id = ?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (normalized_workspace, limit),
        )
        return {
            "errands": errands,
            "summary": f"심부름 {len(errands)}건을 조회했습니다.",
        }

    def save_routine(
        self,
        workspace_id: str,
        routine_name: str,
        routine_type: RoutineType,
        rule_text: str,
        active_days: list[str],
        origin: str,
        destination: str,
        preferred_buffer_minutes: int | None,
        avoid_conditions: list[str],
    ) -> dict[str, Any]:
        routine_id = f"routine_{uuid4().hex[:10]}"
        now = _now_iso()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO routines (
                    id, workspace_id, routine_name, routine_type, rule_text,
                    active_days_json, origin, destination, preferred_buffer_minutes,
                    avoid_conditions_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    routine_id,
                    workspace_id or DEFAULT_WORKSPACE_ID,
                    _normalize_spaces(routine_name),
                    routine_type,
                    _normalize_spaces(rule_text),
                    json.dumps(active_days, ensure_ascii=False),
                    _normalize_spaces(origin),
                    _normalize_spaces(destination),
                    preferred_buffer_minutes,
                    json.dumps(avoid_conditions, ensure_ascii=False),
                    now,
                    now,
                ),
            )
            connection.commit()
        return {
            "saved": True,
            "routine_id": routine_id,
            "summary": f"'{routine_name}' 루틴을 저장했습니다.",
            "how_it_will_be_used": "일일 브리핑과 경유지 추천에서 선호 출발지, 목적지, 여유 시간을 반영합니다.",
        }

    def build_daily_route_briefing(
        self,
        workspace_id: str,
        target_date: str,
        start_location: str,
        end_location: str,
        extra_errands: list[str],
        send_to_me: bool,
    ) -> dict[str, Any]:
        schedules = self._schedules_for_date(workspace_id, target_date)
        routines = self._fetch_all(
            "SELECT * FROM routines WHERE workspace_id = ? ORDER BY created_at DESC",
            (workspace_id or DEFAULT_WORKSPACE_ID,),
        )
        preferred_buffer = next(
            (
                routine.get("preferred_buffer_minutes")
                for routine in routines
                if routine.get("preferred_buffer_minutes") is not None
            ),
            15,
        )
        feasibility = self.check_day_feasibility(workspace_id, target_date, start_location, "car", int(preferred_buffer or 15))
        errands_plan = self.find_places_on_route(
            workspace_id,
            start_location or "출발지",
            end_location or "도착지",
            extra_errands,
            15,
            "",
        ) if extra_errands else {
            "recommended_route": "",
            "selected_places": [],
            "rejected_places": [],
            "estimated_extra_time": 0,
            "warning": None,
            "summary": "추가 심부름이 없습니다.",
        }

        timeline = [
            {
                "time": schedule.get("start_at") or schedule.get("time_text"),
                "title": schedule["title"],
                "location": schedule["location_text"],
            }
            for schedule in schedules
        ]
        departure_deadlines = []
        for schedule in schedules:
            start = _parse_iso_datetime(schedule.get("start_at", ""))
            if start and schedule.get("location_text"):
                probe_departure = start - timedelta(minutes=60)
                route = estimate_future_route_duration(
                    start_location or "출발지",
                    schedule["location_text"],
                    probe_departure.isoformat(timespec="minutes"),
                )
                departure_deadlines.append(
                    {
                        "schedule_title": schedule["title"],
                        "leave_by": (start - timedelta(minutes=route["duration_minutes"] + 15)).isoformat(timespec="minutes"),
                        "estimated_travel_minutes": route["duration_minutes"],
                        "distance_meters": route.get("distance_meters", 0),
                        "provider": route.get("provider", ""),
                        "provider_mode": route.get("mode", ""),
                        "future_departure_probe": route.get("departure_time", ""),
                    }
                )

        message = "\n".join(
            [
                f"[{target_date} 생활동선 브리핑]",
                f"일정 {len(schedules)}건이 있습니다.",
                feasibility["summary"],
                errands_plan["summary"],
            ]
        )
        token_result = self.get_kakao_access_token(workspace_id) if send_to_me else {}
        send_result = (
            send_message_to_me_if_configured(
                message,
                access_token=token_result.get("access_token", ""),
                auth_url=token_result.get("auth_url", _kakao_login_url_for_workspace(workspace_id or DEFAULT_WORKSPACE_ID)),
            )
            if send_to_me
            else {"sent": False}
        )
        warning = send_result.get("warning")
        routine_notes = [
            f"{routine['routine_name']}: {routine['rule_text']}"
            for routine in routines[:3]
        ]
        return {
            "briefing_title": f"{target_date} 생활동선 브리핑",
            "timeline": timeline,
            "departure_deadlines": departure_deadlines,
            "route_warnings": feasibility["warnings"],
            "errands_plan": errands_plan,
            "preparation_checklist": [
                "장소와 이동 시간을 확인하세요.",
                "겹치는 일정이 있으면 미리 조정하세요.",
                *routine_notes,
            ],
            "message_to_send": message,
            "sent_to_me": bool(send_result.get("sent")),
            "send_result": send_result,
            "warning": warning,
            "summary": "일정, 이동 가능성, 심부름 계획을 합쳐 브리핑을 만들었습니다.",
        }

    def create_route_watch(
        self,
        workspace_id: str,
        schedule_id: str,
        origin: str,
        check_minutes_before: int,
        buffer_minutes: int,
        notify_channel: NotifyChannel,
    ) -> dict[str, Any]:
        normalized_workspace = workspace_id or DEFAULT_WORKSPACE_ID
        schedule = self._fetch_one(
            "SELECT * FROM schedules WHERE workspace_id = ? AND id = ?",
            (normalized_workspace, schedule_id),
        )
        if not schedule:
            return {
                "created": False,
                "watch_id": "",
                "summary": "대상 일정을 찾지 못했습니다.",
                "next_check_time": "",
                "warning": "schedule_id를 다시 확인하세요.",
            }
        start = _parse_iso_datetime(schedule.get("start_at", ""))
        if not start:
            return {
                "created": False,
                "watch_id": "",
                "summary": "시작 시간이 없는 일정에는 경로 감시를 만들 수 없습니다.",
                "next_check_time": "",
                "warning": "start_at이 있는 일정으로 다시 시도하세요.",
            }
        watch_id = f"watch_{uuid4().hex[:10]}"
        next_check_time = (start - timedelta(minutes=check_minutes_before)).isoformat(timespec="seconds")
        now = _now_iso()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO route_watch_jobs (
                    id, workspace_id, schedule_id, origin, check_minutes_before,
                    buffer_minutes, notify_channel, status, next_check_time, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 'active', ?, ?, ?)
                """,
                (
                    watch_id,
                    normalized_workspace,
                    schedule_id,
                    _normalize_spaces(origin),
                    check_minutes_before,
                    buffer_minutes,
                    notify_channel,
                    next_check_time,
                    now,
                    now,
                ),
            )
            connection.commit()
        warning = "카카오톡 알림 토큰이 없으면 경고는 로그로만 저장됩니다." if notify_channel == "kakao_me" else None
        return {
            "created": True,
            "watch_id": watch_id,
            "summary": f"'{schedule['title']}' 일정의 경로 감시를 등록했습니다.",
            "next_check_time": next_check_time,
            "warning": warning,
        }

    def run_due_route_watches(self, workspace_id: str = "") -> list[dict[str, Any]]:
        now = datetime.now(KST).isoformat(timespec="seconds")
        normalized_workspace = _normalize_spaces(workspace_id)
        if normalized_workspace:
            jobs = self._fetch_all(
                """
                SELECT w.*, s.title, s.start_at, s.location_text
                FROM route_watch_jobs w
                JOIN schedules s ON s.id = w.schedule_id AND s.workspace_id = w.workspace_id
                WHERE w.workspace_id = ? AND w.status = 'active' AND w.next_check_time <= ?
                ORDER BY w.next_check_time
                """,
                (normalized_workspace, now),
            )
        else:
            jobs = self._fetch_all(
                """
                SELECT w.*, s.title, s.start_at, s.location_text
                FROM route_watch_jobs w
                JOIN schedules s ON s.id = w.schedule_id AND s.workspace_id = w.workspace_id
                WHERE w.status = 'active' AND w.next_check_time <= ?
                ORDER BY w.next_check_time
                """,
                (now,),
            )
        logs: list[dict[str, Any]] = []
        for job in jobs:
            start = _parse_iso_datetime(job.get("start_at", ""))
            remaining = int((start - datetime.now(KST)).total_seconds() // 60) if start else 0
            route = estimate_route_duration(job["origin"], job["location_text"])
            risk = route["duration_minutes"] + job["buffer_minutes"] > remaining
            risk_level = "high" if risk else "low"
            message = (
                f"{job['origin']}에서 {job['location_text']}까지 {route['duration_minutes']}분 예상입니다. "
                f"남은 시간 {remaining}분 기준으로 {'지각 위험이 있습니다' if risk else '이동 가능해 보입니다'}."
            )
            token_result = self.get_kakao_access_token(job["workspace_id"]) if job.get("notify_channel") == "kakao_me" and risk else {}
            notify_result = (
                send_message_to_me_if_configured(
                    message,
                    access_token=token_result.get("access_token", ""),
                    auth_url=token_result.get("auth_url", _kakao_login_url_for_workspace(job["workspace_id"])),
                )
                if job.get("notify_channel") == "kakao_me" and risk
                else {"sent": False}
            )
            log_id = f"alert_{uuid4().hex[:10]}"
            created_at = _now_iso()
            with self._connect() as connection:
                connection.execute(
                    """
                    INSERT INTO route_check_logs (
                        id, workspace_id, watch_id, schedule_id, risk_level, message,
                        estimated_travel_minutes, remaining_minutes, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        log_id,
                        job["workspace_id"],
                        job["id"],
                        job["schedule_id"],
                        risk_level,
                        message,
                        route["duration_minutes"],
                        remaining,
                        created_at,
                    ),
                )
                connection.execute(
                    "UPDATE route_watch_jobs SET status = 'checked', updated_at = ? WHERE id = ?",
                    (created_at, job["id"]),
                )
                connection.commit()
            logs.append(
                {
                    "alert_id": log_id,
                    "watch_id": job["id"],
                    "schedule_id": job["schedule_id"],
                    "risk_level": risk_level,
                    "message": message,
                    "sent_to_me": bool(notify_result.get("sent")),
                    "notify_warning": notify_result.get("warning"),
                    "created_at": created_at,
                }
            )
        return logs

    def get_route_alerts(self, workspace_id: str, limit: int) -> dict[str, Any]:
        normalized_workspace = workspace_id or DEFAULT_WORKSPACE_ID
        self.run_due_route_watches(normalized_workspace)
        alerts = self._fetch_all(
            """
            SELECT * FROM route_check_logs
            WHERE workspace_id = ?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (normalized_workspace, limit),
        )
        return {
            "alerts": alerts,
            "summary": f"최근 경로 경고 {len(alerts)}건을 조회했습니다.",
        }
