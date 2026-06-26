from __future__ import annotations

import json
import os
import re
import sqlite3
from datetime import UTC, date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4


DEFAULT_WORKSPACE_ID = "default"
DB_PATH_ENV = "DAILYROUTE_DB_PATH"
KST = timezone(timedelta(hours=9))

ScheduleType = Literal["meeting", "deadline", "appointment", "personal", "routine", "errand", "other"]
ScheduleSourceType = Literal["text", "ocr_text", "manual", "calendar", "other"]
RoutineType = Literal["commute", "exercise", "hospital", "study", "work", "weekly", "custom"]
TravelMode = Literal["car", "transit_estimate", "walking_estimate"]
NotifyChannel = Literal["kakao_me", "log_only"]


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


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


def build_talk_calendar_event_payload(schedule: dict[str, Any]) -> dict[str, Any]:
    return {
        "title": schedule.get("title", ""),
        "time": {
            "start_at": schedule.get("start_at", ""),
            "end_at": schedule.get("end_at", ""),
            "timezone": "Asia/Seoul",
        },
        "location": schedule.get("location_text", ""),
        "reminders": [{"minutes": schedule.get("reminder_minutes", 60)}],
    }


def create_talk_calendar_event_if_configured(payload: dict[str, Any]) -> dict[str, Any]:
    if _mock_mode() or not os.getenv("KAKAO_ACCESS_TOKEN"):
        return {
            "created": False,
            "payload": payload,
            "message": "톡캘린더 연동 토큰이 없어 로컬 DB에만 저장했습니다.",
        }
    return {
        "created": False,
        "payload": payload,
        "message": "실제 톡캘린더 생성 호출은 어댑터 자리만 준비되어 있습니다.",
    }


def list_talk_calendar_events_if_configured(start_at: str = "", end_at: str = "") -> dict[str, Any]:
    if _mock_mode() or not os.getenv("KAKAO_ACCESS_TOKEN"):
        return {
            "events": [],
            "message": "톡캘린더 조회 토큰이 없어 로컬 DB 일정만 사용합니다.",
            "requested_range": {"start_at": start_at, "end_at": end_at},
        }
    return {
        "events": [],
        "message": "실제 톡캘린더 조회 호출은 어댑터 자리만 준비되어 있습니다.",
        "requested_range": {"start_at": start_at, "end_at": end_at},
    }


def send_message_to_me_if_configured(message_text: str) -> dict[str, Any]:
    if _mock_mode() or not os.getenv("KAKAO_ACCESS_TOKEN"):
        return {
            "sent": False,
            "message_payload": {"text": message_text},
            "warning": "나에게 보내기 토큰이 없어 메시지 본문만 반환했습니다.",
        }
    return {
        "sent": False,
        "message_payload": {"text": message_text},
        "warning": "실제 메시지 전송 호출은 어댑터 자리만 준비되어 있습니다.",
    }


def _area_token(place: str) -> str:
    for area in ("강남", "역삼", "판교", "안양", "홍대", "신촌", "잠실", "분당", "수원", "서울"):
        if area in (place or ""):
            return area
    return _normalize_spaces(place)[:2]


def estimate_route_duration(origin: str, destination: str, waypoints: list[str] | None = None) -> dict[str, Any]:
    waypoints = waypoints or []
    if _mock_mode() or not os.getenv("KAKAO_MOBILITY_API_KEY"):
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
        return {
            "duration_minutes": total or 40,
            "mode": "모의 이동시간",
            "provider": "fallback",
        }
    return {
        "duration_minutes": 40,
        "mode": "API 어댑터 미구현",
        "provider": "kakao_mobility_placeholder",
    }


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
    if _mock_mode() or not os.getenv("KAKAO_REST_API_KEY"):
        return [
            {
                "name": f"{search_area} {keyword} 후보",
                "keyword": keyword,
                "address": f"{search_area} 인근",
                "mock": True,
            }
        ]
    return [
        {
            "name": f"{search_area} {keyword} 검색 후보",
            "keyword": keyword,
            "address": f"{search_area} 인근",
            "mock": False,
        }
    ]


def resolve_address_or_place_to_coordinates(place_text: str) -> dict[str, Any]:
    if _mock_mode() or not os.getenv("KAKAO_REST_API_KEY"):
        token = _area_token(place_text)
        return {
            "place_text": place_text,
            "lat": 37.5,
            "lng": 127.0,
            "area_token": token,
            "mock": True,
            "warning": "장소 API 키가 없어 모의 좌표를 반환했습니다.",
        }
    return {
        "place_text": place_text,
        "lat": 37.5,
        "lng": 127.0,
        "area_token": _area_token(place_text),
        "mock": False,
        "warning": "실제 장소 좌표 조회 호출은 어댑터 자리만 준비되어 있습니다.",
    }


def search_places_by_category_or_keyword(
    origin: str,
    destination: str,
    errand: str,
    preferred_area: str = "",
) -> list[dict[str, Any]]:
    category, label = _errand_category(errand)
    area = preferred_area or _area_token(destination) or _area_token(origin)
    if _mock_mode() or not os.getenv("KAKAO_REST_API_KEY"):
        return [
            {
                "name": f"{area} 추천 {label}",
                "category": category,
                "address": f"{area} 인근",
                "estimated_detour_minutes": 8 if category != "other" else 12,
                "mock": True,
            }
        ]
    return [
        {
            "name": f"{area} {label} 후보",
            "category": category,
            "address": f"{area} 인근",
            "estimated_detour_minutes": 10,
            "mock": False,
        }
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

                CREATE INDEX IF NOT EXISTS idx_schedules_workspace_start
                ON schedules (workspace_id, start_at);

                CREATE INDEX IF NOT EXISTS idx_route_watch_workspace
                ON route_watch_jobs (workspace_id, next_check_time);
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
        calendar_result = create_talk_calendar_event_if_configured(talk_payload) if save_to_talk_calendar else {}
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
            route = estimate_route_duration(prev_location, next_location)
            required = route["duration_minutes"] + buffer_minutes
            risk = required > available_gap
            check = {
                "from_schedule": previous["title"],
                "to_schedule": schedule["title"],
                "origin": prev_location,
                "destination": next_location,
                "available_gap_minutes": available_gap,
                "estimated_travel_minutes": route["duration_minutes"],
                "buffer_minutes": buffer_minutes,
                "provider_mode": route["mode"],
                "risk": risk,
            }
            route_checks.append(check)
            if risk:
                message = (
                    f"{prev_location}에서 {next_location}까지 예상 이동 시간이 {route['duration_minutes']}분인데 "
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
        warning = "카카오 Local API 키가 없어 모의 장소 추천을 반환했습니다." if _mock_mode() or not os.getenv("KAKAO_REST_API_KEY") else None
        return {
            "recommended_route": recommended_route,
            "selected_places": selected_places,
            "rejected_places": rejected_places,
            "estimated_extra_time": estimated_extra_time,
            "warning": warning,
            "summary": f"{origin}에서 {destination}까지 {len(selected_places)}개 경유지를 추천합니다.",
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
                route = estimate_route_duration(start_location or "출발지", schedule["location_text"])
                departure_deadlines.append(
                    {
                        "schedule_title": schedule["title"],
                        "leave_by": (start - timedelta(minutes=route["duration_minutes"] + 15)).isoformat(timespec="minutes"),
                        "estimated_travel_minutes": route["duration_minutes"],
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
        send_result = send_message_to_me_if_configured(message) if send_to_me else {"sent": False}
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
            notify_result = (
                send_message_to_me_if_configured(message)
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
