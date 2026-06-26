from __future__ import annotations

import os
import re
import sqlite3
import base64
import shutil
import subprocess
import tempfile
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4


DEFAULT_WORKSPACE_ID = "default"
DB_PATH_ENV = "TALKGUARD_DB_PATH"
ACTIVE_COMMITMENT_STATUSES = {"planned", "changed", "unknown"}
OCR_HELPER_PATH = Path(__file__).resolve().parent / "tools" / "macos_vision_ocr.swift"
KST = timezone(timedelta(hours=9))
VAGUE_DEADLINE_TERMS = {
    "나중에",
    "조만간",
    "다음에",
    "언젠가",
    "가능한 빨리",
    "빠르게",
    "이번 주 중",
    "다음 주 중",
}
STOPWORDS = {
    "그리고",
    "하지만",
    "입니다",
    "합니다",
    "대한",
    "관련",
    "전체",
    "기능",
    "현재",
    "추가",
    "공유",
    "확인",
    "중요",
    "저장",
    "작업",
    "일정",
    "약속",
    "상황",
    "완료",
    "테스트",
    "진행",
    "공모전",
    "까지",
    "회의",
    "가능",
    "보내드리겠습니다",
    "정리",
    "팀장",
}
TOPIC_NOISE_TOKENS = STOPWORDS | {
    "답장",
    "회신",
    "전달",
    "공유드리겠습니다",
    "드리겠습니다",
    "요청",
    "원함",
    "원하고",
    "원합니다",
    "초안",
    "검토",
    "기존",
}
CONTEXT_NOISE_TOKENS = TOPIC_NOISE_TOKENS | {
    "팀장",
    "교수",
    "교수님",
    "고객",
    "거래처",
    "전체",
    "여부",
    "중요하게",
    "원하",
    "확인",
    "분명히",
    "말하기",
    "명확히",
    "알리기",
    "말씀",
}
PANGYO_JARGON_TERMS = (
    ("얼라인", "방향과 기준을 맞추기"),
    ("align", "방향과 기준을 맞추기"),
    ("alignment", "방향과 기준을 맞추기"),
    ("싱크", "서로 같은 이해로 맞추기"),
    ("sync", "서로 같은 이해로 맞추기"),
    ("팔로업", "후속 확인과 진행"),
    ("follow-up", "후속 확인과 진행"),
    ("follow up", "후속 확인과 진행"),
    ("액션아이템", "해야 할 일"),
    ("action item", "해야 할 일"),
    ("아젠다", "논의할 주제"),
    ("agenda", "논의할 주제"),
    ("ASAP", "가능한 빨리"),
    ("EOD", "오늘 업무 끝 전까지"),
    ("ETA", "예상 완료 시점"),
    ("블로커", "막히는 문제"),
    ("blocker", "막히는 문제"),
    ("리소스", "필요한 사람, 시간, 예산"),
    ("resource", "필요한 사람, 시간, 예산"),
    ("이슈", "문제나 확인할 점"),
    ("issue", "문제나 확인할 점"),
    ("리스크", "위험 요소"),
    ("risk", "위험 요소"),
    ("마일스톤", "중요한 중간 목표"),
    ("milestone", "중요한 중간 목표"),
    ("스콥", "작업 범위"),
    ("scope", "작업 범위"),
    ("킥오프", "시작 회의"),
    ("kickoff", "시작 회의"),
)
PANGYO_PHRASE_REPLACEMENTS = (
    ("얼라인해서", "방향과 기준을 맞춰서"),
    ("얼라인해", "방향과 기준을 맞춰"),
    ("싱크해서", "서로 같은 이해로 맞춰서"),
    ("싱크해", "서로 같은 이해로 맞춰"),
    ("팔로업해서", "후속 확인을 진행해서"),
    ("팔로업해", "후속 확인을 진행해"),
    ("EOD까지", "오늘 업무 끝 전까지"),
    ("ASAP으로", "가능한 빨리"),
    ("ASAP하게", "가능한 빨리"),
)
REQUEST_KEYWORDS = (
    "해주세요",
    "해 주세요",
    "부탁",
    "요청",
    "정리",
    "공유",
    "확인",
    "검토",
    "회신",
    "답변",
    "보내",
    "알려",
    "업데이트",
    "맞춰",
    "얼라인",
    "싱크",
    "팔로업",
    "액션아이템",
    "ASAP",
    "EOD",
    "ETA",
)
COMPLEX_INSTRUCTION_KEYWORDS = (
    "해주세요",
    "해 주세요",
    "부탁",
    "요청",
    "회신",
    "답변",
    "알려",
    "업데이트",
    "얼라인",
    "싱크",
    "팔로업",
    "액션아이템",
    "ASAP",
    "EOD",
    "ETA",
    "블로커",
    "blocker",
    "스콥",
    "scope",
)
REPLY_POINT_HINTS = (
    ("리스크", "리스크"),
    ("risk", "리스크"),
    ("이슈", "이슈"),
    ("issue", "이슈"),
    ("블로커", "블로커"),
    ("blocker", "블로커"),
    ("일정", "일정"),
    ("마감", "마감"),
    ("데드라인", "마감"),
    ("deadline", "마감"),
    ("ETA", "예상 완료 시점"),
    ("예상 완료", "예상 완료 시점"),
    ("범위", "작업 범위"),
    ("스콥", "작업 범위"),
    ("scope", "작업 범위"),
    ("담당", "담당자"),
    ("오너", "담당자"),
    ("owner", "담당자"),
    ("우선순위", "우선순위"),
    ("priority", "우선순위"),
    ("자료", "자료"),
    ("문서", "문서"),
    ("데모", "데모"),
    ("공유", "공유 방식"),
    ("회신", "회신"),
    ("답변", "답변"),
    ("확인", "확인 결과"),
    ("ASAP", "가능한 빠른 처리 일정"),
    ("EOD", "오늘 업무 끝 전까지"),
)

CommitmentType = Literal[
    "deadline",
    "meeting",
    "delivery",
    "reply",
    "task",
    "promise",
    "other",
]
SourceType = Literal["manual", "chat", "email", "ocr", "calendar", "other"]
CommitmentImportance = Literal["low", "medium", "high"]
CommitmentStatus = Literal["planned", "done", "changed", "cancelled", "unknown"]
RoomType = Literal[
    "team",
    "professor",
    "client",
    "friend",
    "family",
    "school",
    "important",
    "other",
]
RecipientType = Literal[
    "team",
    "professor",
    "client",
    "friend",
    "family",
    "school",
    "important",
    "other",
]


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _resolve_db_path(default_path: str | Path) -> Path:
    override = os.getenv(DB_PATH_ENV)
    return Path(override) if override else Path(default_path)


def _normalize_spaces(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _compact_text(text: str) -> str:
    return re.sub(r"\s+", "", text or "")


def _room_type_label(room_type: RoomType | RecipientType) -> str:
    return {
        "team": "팀",
        "professor": "교수",
        "client": "고객",
        "friend": "친구",
        "family": "가족",
        "school": "학교",
        "important": "중요 관계",
        "other": "기타",
    }[room_type]


def _commitment_type_label(commitment_type: CommitmentType) -> str:
    return {
        "deadline": "마감",
        "meeting": "회의",
        "delivery": "전달",
        "reply": "답장",
        "task": "작업",
        "promise": "약속",
        "other": "기타",
    }[commitment_type]


def _importance_label(importance: CommitmentImportance) -> str:
    return {"low": "낮음", "medium": "보통", "high": "높음"}[importance]


def _commitment_status_label(status: CommitmentStatus) -> str:
    return {
        "planned": "예정",
        "done": "완료",
        "changed": "변경됨",
        "cancelled": "취소됨",
        "unknown": "불확실",
    }[status]


def _source_type_label(source_type: SourceType) -> str:
    return {
        "manual": "수동 입력",
        "chat": "채팅",
        "email": "이메일",
        "ocr": "OCR",
        "calendar": "캘린더",
        "other": "기타",
    }[source_type]


def _is_schedule_token(token: str) -> bool:
    patterns = (
        r"^\d{4}-\d{2}-\d{2}$",
        r"^\d{1,2}월\d{1,2}일$",
        r"^(오늘|내일|모레|이번주|다음주|이번달|다음달)$",
        r"^(오늘|내일|모레|이번|다음)$",
        r"^(월|화|수|목|금|토|일)요일?$",
        r"^(월요일|화요일|수요일|목요일|금요일|토요일|일요일)(까지)?$",
        r"^(오전|오후|저녁|밤)$",
        r"^\d{1,2}시$",
        r"^\d{1,2}분$",
    )
    compact = token.replace(" ", "")
    return any(re.match(pattern, compact) for pattern in patterns)


def _extract_topic_tokens(text: str) -> list[str]:
    cleaned: list[str] = []
    for token in re.findall(r"[A-Za-z0-9가-힣]{2,}", text or ""):
        normalized = re.sub(r"(은|는|이|가|을|를|의|에|와|과|로|으로|도|만|께|한테|에서)$", "", token)
        if len(normalized) >= 2 and normalized not in TOPIC_NOISE_TOKENS and not _is_schedule_token(normalized):
            cleaned.append(normalized)
    return cleaned


def _extract_focus_phrase(text: str) -> str:
    tokens = _extract_topic_tokens(text)
    if len(tokens) >= 2:
        return " ".join(tokens[:2])
    if tokens:
        return tokens[0]
    return _normalize_spaces(text)


def _extract_context_focus_items(text: str, limit: int = 3) -> list[str]:
    tokens = [
        token
        for token in _extract_topic_tokens(text)
        if token not in CONTEXT_NOISE_TOKENS
        and not token.startswith(("확인", "원하"))
        and not token.endswith("합니다")
    ]
    if not tokens:
        return []

    phrases: list[str] = []
    for index in range(len(tokens) - 1):
        pair = f"{tokens[index]} {tokens[index + 1]}"
        if pair not in phrases:
            phrases.append(pair)
        if len(phrases) >= limit:
            return phrases

    if phrases:
        return phrases

    for token in tokens:
        if token not in phrases:
            phrases.append(token)
        if len(phrases) >= limit:
            break
    return phrases


def _draft_mentions_item(draft_message: str, item: str) -> bool:
    draft_tokens = set(_extract_topic_tokens(draft_message))
    item_tokens = _extract_topic_tokens(item)
    if not item_tokens:
        return False
    return any(token in draft_tokens or token in draft_message for token in item_tokens)


def _split_context_sentences(text: str) -> list[str]:
    normalized = re.sub(r"[ \t\r\f\v]+", " ", text or "").strip()
    if not normalized:
        return []
    raw_sentences = re.split(r"(?:\n+|(?<=[.!?。！？])\s+|[;；])", normalized)
    sentences: list[str] = []
    for sentence in raw_sentences:
        cleaned = re.sub(r"^[^:：]{1,12}[:：]\s*", "", sentence).strip()
        cleaned = cleaned.strip(" .!?。！？")
        if cleaned and cleaned not in sentences:
            sentences.append(cleaned)
    return sentences


def _detect_jargon_terms(text: str) -> list[dict[str, str]]:
    normalized = text or ""
    lowered = normalized.lower()
    detected: list[tuple[int, dict[str, str]]] = []
    seen: set[str] = set()
    for term, meaning in PANGYO_JARGON_TERMS:
        key = term.lower()
        if key in lowered and key not in seen:
            detected.append((lowered.index(key), {"term": term, "meaning": meaning}))
            seen.add(key)
    return [item for _, item in sorted(detected, key=lambda entry: entry[0])]


def _plainify_business_jargon(text: str) -> str:
    updated = text or ""
    for before, after in PANGYO_PHRASE_REPLACEMENTS:
        updated = re.sub(re.escape(before), after, updated, flags=re.IGNORECASE)
    for term, meaning in sorted(PANGYO_JARGON_TERMS, key=lambda item: len(item[0]), reverse=True):
        updated = re.sub(re.escape(term), meaning, updated, flags=re.IGNORECASE)
    return _normalize_spaces(updated)


def _extract_instruction_sentences(text: str, limit: int = 5) -> list[str]:
    sentences = _split_context_sentences(text)
    instruction_sentences: list[str] = []
    for sentence in sentences:
        compact_sentence = _compact_text(sentence)
        if any(keyword.lower() in sentence.lower() for keyword in REQUEST_KEYWORDS) or any(
            _compact_text(keyword) in compact_sentence for keyword in REQUEST_KEYWORDS
        ):
            plain_sentence = _plainify_business_jargon(sentence)
            if plain_sentence not in instruction_sentences:
                instruction_sentences.append(plain_sentence)
        if len(instruction_sentences) >= limit:
            return instruction_sentences
    return instruction_sentences


def _extract_reply_requirement_items(text: str, limit: int = 6) -> list[str]:
    normalized = _normalize_spaces(text)
    if not normalized:
        return []

    items: list[str] = []
    lowered = normalized.lower()
    compact = _compact_text(normalized)
    for hint, label in REPLY_POINT_HINTS:
        if hint.lower() in lowered or _compact_text(hint) in compact:
            if label not in items:
                items.append(label)
        if len(items) >= limit:
            return items

    for date_phrase in _extract_date_phrases(normalized):
        display_date = _display_date_phrase(date_phrase)
        if display_date and display_date not in items:
            items.append(display_date)
        if len(items) >= limit:
            return items

    if len(items) >= 3:
        return items[:limit]

    for focus_item in _extract_context_focus_items(normalized, limit=limit):
        if focus_item and focus_item not in items:
            items.append(focus_item)
        if len(items) >= limit:
            break
    return items


def _build_plain_context_summary(
    conversation_text: str,
    key_requests: list[str],
    reply_should_include: list[str],
) -> str:
    if key_requests:
        summary_items = "; ".join(key_requests[:3])
        return f"쉽게 말하면 상대의 요청은 '{summary_items}'입니다."
    if reply_should_include:
        return f"쉽게 말하면 답장에 {', '.join(reply_should_include[:4])}를 포함해야 합니다."
    plain_text = _plainify_business_jargon(conversation_text)
    if plain_text:
        return f"이전 대화의 핵심은 '{plain_text[:120]}'입니다."
    return "분석할 이전 대화 내용이 비어 있습니다."


def _build_reply_checklist(reply_should_include: list[str]) -> list[str]:
    if not reply_should_include:
        return ["상대가 요청한 내용, 일정, 다음 액션을 한 문장씩 확인하세요."]
    return [f"답장에 '{item}' 직접 언급하기" for item in reply_should_include[:6]]


def _build_suggested_context_reply(reply_should_include: list[str], recipient_type: RecipientType | None) -> str:
    if not reply_should_include:
        return "확인했습니다. 요청하신 내용과 다음 일정을 정리해서 다시 말씀드리겠습니다."

    joined_items = ", ".join(reply_should_include[:4])
    polite_suffix = "정리해 공유드리겠습니다."
    if recipient_type in {"friend", "family"}:
        polite_suffix = "정리해서 공유할게요."
    return f"확인했습니다. {joined_items} 기준으로 확인한 뒤, 진행 가능 여부와 다음 액션을 {polite_suffix}"


def _looks_like_complex_instruction(text: str) -> bool:
    lowered = (text or "").lower()
    compact = _compact_text(text)
    return bool(_detect_jargon_terms(text)) or any(
        keyword.lower() in lowered or _compact_text(keyword) in compact
        for keyword in COMPLEX_INSTRUCTION_KEYWORDS
    )


def _draft_covers_reply_item(draft_message: str, item: str) -> bool:
    if _draft_mentions_item(draft_message, item):
        return True

    synonyms = {
        "리스크": ("리스크", "위험", "위험 요소"),
        "이슈": ("이슈", "문제", "확인할 점"),
        "블로커": ("블로커", "막히는", "막힌", "문제"),
        "예상 완료 시점": ("ETA", "예상 완료", "완료 시점", "언제까지"),
        "오늘 업무 끝 전까지": ("EOD", "오늘", "업무 끝", "퇴근 전"),
        "가능한 빠른 처리 일정": ("ASAP", "가능한 빨리", "빠르게", "최대한 빨리"),
        "작업 범위": ("범위", "스콥", "scope"),
        "담당자": ("담당", "오너", "owner"),
        "공유 방식": ("공유", "전달", "보내"),
        "확인 결과": ("확인", "검토"),
    }
    return any(keyword in draft_message for keyword in synonyms.get(item, ()))


def _extract_time_phrases(text: str) -> list[str]:
    patterns = [
        r"(오전|오후|저녁|밤)\s*\d{1,2}시(?:\s*\d{1,2}분)?",
        r"\d{1,2}:\d{2}",
        r"(?<!\d)\d{1,2}시(?:\s*\d{1,2}분)?",
    ]
    matches: list[tuple[int, str]] = []
    for pattern in patterns:
        for match in re.finditer(pattern, text or ""):
            phrase = _normalize_spaces(match.group(0))
            if phrase:
                matches.append((match.start(), phrase))

    seen: set[str] = set()
    ordered_phrases: list[str] = []
    for _, phrase in sorted(matches, key=lambda item: item[0]):
        compact = _compact_text(phrase)
        if compact not in seen:
            ordered_phrases.append(phrase)
            seen.add(compact)
    return ordered_phrases


def _extract_time_phrase(text: str) -> str:
    phrases = _extract_time_phrases(text)
    return phrases[0] if phrases else ""


def _time_keys(text: str) -> set[str]:
    keys: set[str] = set()
    normalized = _compact_text(text)
    if not normalized:
        return keys

    colon_match = re.search(r"(?<!\d)(\d{1,2}):(\d{2})(?!\d)", normalized)
    if colon_match:
        hour, minute = map(int, colon_match.groups())
        keys.add(f"time:{hour:02d}:{minute:02d}")

    korean_match = re.search(r"(오전|오후|저녁|밤)?(\d{1,2})시(?:(\d{1,2})분)?", normalized)
    if korean_match:
        meridiem, hour_text, minute_text = korean_match.groups()
        hour = int(hour_text)
        minute = int(minute_text or "0")
        original_hour = hour
        if meridiem in {"오후", "저녁", "밤"} and hour < 12:
            hour += 12
        if meridiem == "오전" and hour == 12:
            hour = 0
        keys.add(f"time:{hour:02d}:{minute:02d}")
        if meridiem is None or meridiem in {"오후", "저녁", "밤"}:
            keys.add(f"time_ambiguous:{original_hour:02d}:{minute:02d}")
    return keys


def _time_keys_match(saved_time: str, draft_message: str) -> bool:
    saved_keys = _time_keys(saved_time)
    if not saved_keys:
        return False
    draft_keys: set[str] = set()
    for phrase in _extract_time_phrases(draft_message):
        draft_keys.update(_time_keys(phrase))
    return bool(saved_keys & draft_keys)


def _extract_date_phrases(text: str) -> list[str]:
    patterns = [
        r"\d{4}[-./]\d{1,2}[-./]\d{1,2}",
        r"\d{1,2}월\s*\d{1,2}일",
        r"(오늘|내일|모레)\s*(?:까지|에)?",
        r"(이번\s*주|다음\s*주|이번\s*달|다음\s*달)\s*(?:중|까지|에)?",
        r"(월요일|화요일|수요일|목요일|금요일|토요일|일요일)\s*(?:까지|에)?",
        r"(?<![가-힣0-9])(월|화|수|목|금|토|일)(?:\s*요일)?\s*(?:까지|에)?(?![가-힣0-9])",
    ]
    matches: list[tuple[int, str]] = []
    for pattern in patterns:
        for match in re.finditer(pattern, text or ""):
            phrase = _normalize_spaces(match.group(0))
            if phrase:
                matches.append((match.start(), phrase))

    seen: set[str] = set()
    ordered_phrases: list[str] = []
    for _, phrase in sorted(matches, key=lambda item: item[0]):
        compact = _compact_text(phrase)
        if compact not in seen:
            ordered_phrases.append(phrase)
            seen.add(compact)
    return ordered_phrases


def _extract_date_phrase(text: str) -> str:
    phrases = _extract_date_phrases(text)
    return phrases[0] if phrases else ""


def _display_date_phrase(text: str) -> str:
    phrase = _normalize_spaces(text)
    phrase = re.sub(r"\s*(까지|부터|에는|에|중)$", "", phrase)
    return phrase or _normalize_spaces(text)


def _date_keys(text: str) -> set[str]:
    keys: set[str] = set()
    normalized = _compact_text(text)
    normalized = re.sub(r"(까지|부터|에는|에|중)$", "", normalized)
    if not normalized:
        return keys

    iso_match = re.search(r"(\d{4})[-./](\d{1,2})[-./](\d{1,2})", normalized)
    if iso_match:
        year, month, day = map(int, iso_match.groups())
        keys.add(f"ymd:{year:04d}-{month:02d}-{day:02d}")
        keys.add(f"md:{month:02d}-{day:02d}")

    month_day_match = re.search(r"(\d{1,2})월(\d{1,2})일", normalized)
    if month_day_match:
        month, day = map(int, month_day_match.groups())
        keys.add(f"md:{month:02d}-{day:02d}")

    relative_aliases = {
        "오늘": "relative:today",
        "내일": "relative:tomorrow",
        "모레": "relative:after_tomorrow",
        "이번주": "relative:this_week",
        "다음주": "relative:next_week",
        "이번달": "relative:this_month",
        "다음달": "relative:next_month",
        "월": "weekday:mon",
        "월요일": "weekday:mon",
        "화": "weekday:tue",
        "화요일": "weekday:tue",
        "수": "weekday:wed",
        "수요일": "weekday:wed",
        "목": "weekday:thu",
        "목요일": "weekday:thu",
        "금": "weekday:fri",
        "금요일": "weekday:fri",
        "토": "weekday:sat",
        "토요일": "weekday:sat",
        "일": "weekday:sun",
        "일요일": "weekday:sun",
    }
    for alias, key in relative_aliases.items():
        if len(alias) == 1:
            matched = normalized == alias
        else:
            matched = normalized == alias or alias in normalized
        if matched:
            keys.add(key)
    return keys


def _date_keys_match(saved_date: str, draft_message: str) -> bool:
    saved_keys = _date_keys(saved_date)
    if not saved_keys:
        return False
    draft_keys: set[str] = set()
    for phrase in _extract_date_phrases(draft_message):
        draft_keys.update(_date_keys(phrase))
    return bool(saved_keys & draft_keys)


def _deadline_rank(text: str) -> int | None:
    normalized = _compact_text(text)
    normalized = re.sub(r"(까지|부터|에는|에|중)$", "", normalized)
    if not normalized:
        return None

    date_match = re.search(r"(\d{4})[-./](\d{1,2})[-./](\d{1,2})", normalized)
    if date_match:
        year, month, day = map(int, date_match.groups())
        return year * 10000 + month * 100 + day

    month_day_match = re.search(r"(\d{1,2})월(\d{1,2})일", normalized)
    if month_day_match:
        month, day = map(int, month_day_match.groups())
        return 5000 + month * 100 + day

    relative_map = {
        "오늘": 1,
        "내일": 2,
        "모레": 3,
        "이번주": 4,
        "월요일": 5,
        "월": 5,
        "화요일": 6,
        "화": 6,
        "수요일": 7,
        "수": 7,
        "목요일": 8,
        "목": 8,
        "금요일": 9,
        "금": 9,
        "토요일": 10,
        "토": 10,
        "일요일": 11,
        "일": 11,
        "이번달": 12,
        "다음주": 20,
        "다음달": 30,
    }
    for key, rank in relative_map.items():
        if key in normalized:
            return rank
    return None


def _is_later_deadline(saved_deadline: str, draft_message: str) -> tuple[bool, str]:
    saved_rank = _deadline_rank(saved_deadline)
    draft_date_phrase = _extract_date_phrase(draft_message)
    draft_rank = _deadline_rank(draft_date_phrase)
    display_draft_date_phrase = _display_date_phrase(draft_date_phrase)
    saved_month_day_match = re.search(r"(?:\d{4}[-./])?(\d{1,2})[-./](\d{1,2})", _compact_text(saved_deadline))
    draft_month_day_match = re.search(r"(\d{1,2})월(\d{1,2})일", _compact_text(draft_date_phrase))
    if saved_month_day_match and draft_month_day_match:
        saved_month, saved_day = map(int, saved_month_day_match.groups())
        draft_month, draft_day = map(int, draft_month_day_match.groups())
        return (draft_month, draft_day) > (saved_month, saved_day), display_draft_date_phrase
    if saved_rank is None or draft_rank is None:
        return False, display_draft_date_phrase
    return draft_rank > saved_rank, display_draft_date_phrase


def _contains_availability_claim(text: str) -> bool:
    keywords = ("가능", "괜찮", "비어", "됩니다", "시간 됩니다", "시간 가능", "됩니다", "잡을 수")
    return any(keyword in text for keyword in keywords)


def _commitment_matches_text(commitment: dict[str, Any], text: str) -> bool:
    if not text:
        return False
    title_tokens = _extract_topic_tokens(commitment.get("title", ""))
    text_tokens = set(_extract_topic_tokens(text))
    if title_tokens and any(token in text_tokens or token in text for token in title_tokens):
        return True
    related_person = commitment.get("related_person", "")
    return bool(related_person and related_person in text)


def _is_relevant_commitment(
    commitment: dict[str, Any],
    room_name: str,
    draft_message: str,
    extra_context: str,
) -> bool:
    if commitment["status"] not in ACTIVE_COMMITMENT_STATUSES:
        return False
    related_room = commitment.get("related_room", "")
    if room_name:
        return not related_room or related_room == room_name
    combined_text = f"{draft_message} {extra_context}"
    if not related_room:
        return _commitment_matches_text(commitment, combined_text) or _date_keys_match(
            commitment.get("deadline_text", ""), combined_text
        )
    if commitment.get("commitment_type") == "meeting":
        return _date_keys_match(commitment.get("deadline_text", ""), combined_text) and _time_keys_match(
            commitment.get("time_text", ""), combined_text
        )
    return _commitment_matches_text(commitment, combined_text)


def _replace_tone_risky_words(text: str) -> str:
    replacements = {
        "무조건": "가능한 범위에서",
        "완벽히": "세부 확인 후",
        "문제 없습니다": "현재 기준으로는 큰 문제는 없어 보입니다",
        "대충": "우선",
        "아마": "현재 예상으로는",
        "될 것 같아요": "가능할 것으로 보고 있습니다",
        "왜요": "어떤 부분이 필요한지 확인 부탁드립니다",
        "그건 좀": "그 부분은 조정이 필요합니다",
    }
    updated = text
    for before, after in replacements.items():
        updated = updated.replace(before, after)
    return _normalize_spaces(updated)


def _suggest_alternate_time(time_text: str) -> str:
    match = re.search(r"(오전|오후|저녁|밤)\s*(\d{1,2})시", time_text or "")
    if not match:
        return "다른 시간"

    meridiem, hour_text = match.groups()
    hour = int(hour_text)
    base_hour = hour
    if meridiem == "오후" and hour < 12:
        base_hour += 12
    if meridiem in {"저녁", "밤"} and hour < 12:
        base_hour += 12
    suggested = min(base_hour + 2, 22)
    if suggested >= 12:
        display_hour = 12 if suggested == 12 else suggested - 12 if suggested > 12 else suggested
        display_meridiem = "오후"
    else:
        display_hour = suggested
        display_meridiem = "오전"
    return f"{display_meridiem} {display_hour}시 이후"


def _warning_for_vague_deadline(deadline_text: str) -> str | None:
    normalized = _normalize_spaces(deadline_text)
    if not normalized:
        return None
    compact = _compact_text(normalized)
    vague_compact_terms = {_compact_text(term) for term in VAGUE_DEADLINE_TERMS}
    if (
        normalized in VAGUE_DEADLINE_TERMS
        or any(term in normalized for term in VAGUE_DEADLINE_TERMS)
        or compact in vague_compact_terms
        or any(term in compact for term in vague_compact_terms)
    ):
        return "마감 표현이 다소 모호합니다. 가능하면 더 구체적인 날짜나 시간을 함께 저장해 주세요."
    return None


def _warning_for_unrecognized_deadline(deadline_text: str) -> str | None:
    normalized = _normalize_spaces(deadline_text)
    if normalized and not _date_keys(normalized):
        return (
            "날짜 표현을 해석하지 못했습니다. 저장은 했지만 마감 충돌 비교에 쓰기 어려울 수 있으니 "
            "`금요일`, `다음 주`, `7월 1일`, `2026-07-01`처럼 구체적으로 입력해 주세요."
        )
    return None


def _warning_for_unrecognized_time(time_text: str) -> str | None:
    normalized = _normalize_spaces(time_text)
    if normalized and not _time_keys(normalized):
        return (
            "시간 표현을 해석하지 못했습니다. 저장은 했지만 일정 충돌 비교에 쓰기 어려울 수 있으니 "
            "`오후 3시`, `15:00`, `3시 30분`처럼 구체적으로 입력해 주세요."
        )
    return None


def _warning_for_missing_meeting_parts(
    commitment_type: CommitmentType,
    deadline_text: str,
    time_text: str,
) -> str | None:
    if commitment_type == "meeting" and (not _normalize_spaces(deadline_text) or not _normalize_spaces(time_text)):
        return "회의 일정은 날짜와 시간을 함께 저장해야 일정 충돌 감지가 정확합니다."
    return None


def _build_commitment_warning(
    commitment_type: CommitmentType,
    deadline_text: str,
    time_text: str,
) -> str | None:
    warnings = [
        _warning_for_vague_deadline(deadline_text),
        _warning_for_unrecognized_deadline(deadline_text),
        _warning_for_unrecognized_time(time_text),
        _warning_for_missing_meeting_parts(commitment_type, deadline_text, time_text),
    ]
    return " ".join(warning for warning in warnings if warning) or None


def _commitment_has_same_schedule(
    commitment: dict[str, Any],
    deadline_text: str,
    time_text: str,
) -> bool:
    if commitment.get("status") not in ACTIVE_COMMITMENT_STATUSES:
        return False
    if not commitment.get("deadline_text") or not commitment.get("time_text"):
        return False
    saved_date_keys = _date_keys(commitment.get("deadline_text", ""))
    new_date_keys = _date_keys(deadline_text)
    saved_time_keys = _time_keys(commitment.get("time_text", ""))
    new_time_keys = _time_keys(time_text)
    return bool(saved_date_keys & new_date_keys) and bool(saved_time_keys & new_time_keys)


def _build_same_schedule_conflict_candidates(
    commitments: list[dict[str, Any]],
    deadline_text: str,
    time_text: str,
) -> list[dict[str, Any]]:
    if not _normalize_spaces(deadline_text) or not _normalize_spaces(time_text):
        return []

    candidates: list[dict[str, Any]] = []
    for commitment in commitments:
        if not _commitment_has_same_schedule(commitment, deadline_text, time_text):
            continue
        candidates.append(
            {
                "commitment_id": commitment.get("id", ""),
                "title": commitment.get("title", ""),
                "commitment_type": commitment.get("commitment_type", ""),
                "deadline_text": commitment.get("deadline_text", ""),
                "time_text": commitment.get("time_text", ""),
                "related_person": commitment.get("related_person", ""),
                "related_room": commitment.get("related_room", ""),
                "source_type": commitment.get("source_type", ""),
                "importance": commitment.get("importance", ""),
                "status": commitment.get("status", ""),
            }
        )
    return candidates


def _warning_for_same_schedule_conflict(
    deadline_text: str,
    time_text: str,
    conflict_candidates: list[dict[str, Any]],
) -> str | None:
    if not conflict_candidates:
        return None
    first_candidate = conflict_candidates[0]
    return (
        f"이미 {deadline_text} {time_text}에 '{first_candidate['title']}' 일정이 저장되어 있습니다. "
        "같은 시간에 새 일정을 추가해도 되는지 확인하세요."
    )


def _join_warnings(*warnings: str | None) -> str | None:
    joined = " ".join(warning for warning in warnings if warning)
    return joined or None


def _split_schedule_candidate_sentences(text: str) -> list[str]:
    sentences: list[str] = []
    for sentence in _split_context_sentences(text):
        parts = re.split(r"\s*(?:그리고|또|및|,|，)\s*", sentence)
        for part in parts:
            cleaned = _normalize_spaces(part)
            if cleaned and cleaned not in sentences:
                sentences.append(cleaned)
    return sentences


def _has_commitment_signal(text: str) -> bool:
    signal_terms = (
        "회의",
        "미팅",
        "면담",
        "콜",
        "세미나",
        "발표",
        "일정",
        "약속",
        "마감",
        "제출",
        "공유",
        "전달",
        "보내",
        "회신",
        "답장",
        "완료",
        "정리",
        "업로드",
        "검토",
        "까지",
    )
    return any(term in text for term in signal_terms)


def _infer_commitment_type_from_text(text: str, date_text: str, time_text: str) -> CommitmentType:
    if any(term in text for term in ("회의", "미팅", "면담", "콜", "세미나", "약속", "일정")) and (
        date_text or time_text
    ):
        return "meeting"
    if any(term in text for term in ("마감", "제출", "까지", "완료", "업로드")):
        return "deadline"
    if any(term in text for term in ("공유", "전달", "보내")):
        return "delivery"
    if any(term in text for term in ("회신", "답장", "답변")):
        return "reply"
    if time_text:
        return "meeting"
    if date_text:
        return "promise"
    return "other"


def _infer_importance_from_text(text: str, date_text: str) -> CommitmentImportance:
    high_terms = ("중요", "반드시", "꼭", "필수", "마감", "제출", "ASAP", "EOD", "오늘", "내일")
    if date_text or any(term in text for term in high_terms):
        return "high"
    return "medium"


def _extract_related_person_from_text(text: str) -> str:
    known_people = ("교수님", "교수", "팀장", "고객", "거래처", "멘토", "PM", "디자이너", "개발자")
    for person in known_people:
        if person in text:
            return person
    person_match = re.search(r"([가-힣A-Za-z0-9]{2,8}(?:님|팀|파트|부서))", text)
    return person_match.group(1) if person_match else ""


def _build_extracted_title(text: str, date_text: str, time_text: str) -> str:
    title = _normalize_spaces(text)
    title = re.sub(r"^(일정|약속|공지|안내)\s*[:：-]\s*", "", title)
    if len(title) > 80:
        title = title[:77].rstrip() + "..."
    if title:
        return title
    pieces = [piece for piece in (date_text, time_text, "추출된 일정") if piece]
    return " ".join(pieces)


def _confidence_for_extracted_commitment(date_text: str, time_text: str, text: str) -> float:
    if date_text and time_text:
        return 0.9
    if date_text:
        return 0.78
    if time_text:
        return 0.65
    if _has_commitment_signal(text):
        return 0.48
    return 0.0


def _extract_commitment_candidates_from_text(
    source_text: str,
    related_room: str,
    source_type: SourceType,
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for sentence in _split_schedule_candidate_sentences(source_text):
        date_phrase = _extract_date_phrase(sentence)
        date_text = _display_date_phrase(date_phrase)
        time_text = _extract_time_phrase(sentence)
        if not (date_text or time_text or _has_commitment_signal(sentence)):
            continue

        commitment_type = _infer_commitment_type_from_text(sentence, date_text, time_text)
        confidence = _confidence_for_extracted_commitment(date_text, time_text, sentence)
        if confidence <= 0:
            continue

        title = _build_extracted_title(sentence, date_text, time_text)
        identity = (_compact_text(title), date_text, time_text)
        if identity in seen:
            continue
        seen.add(identity)

        candidates.append(
            {
                "title": title,
                "commitment_type": commitment_type,
                "deadline_text": date_text,
                "time_text": time_text,
                "related_person": _extract_related_person_from_text(sentence),
                "related_room": _normalize_spaces(related_room),
                "source_type": source_type,
                "importance": _infer_importance_from_text(sentence, date_text),
                "status": "planned",
                "memo": f"원문 근거: {sentence}",
                "confidence": confidence,
                "evidence": sentence,
            }
        )
    return candidates


def _decode_image_base64_to_temp_file(image_base64: str) -> Path:
    payload = image_base64.split(",", 1)[1] if "," in image_base64[:80] else image_base64
    image_bytes = base64.b64decode(payload, validate=True)
    temp_file = tempfile.NamedTemporaryFile(prefix="talkguard-ocr-", suffix=".png", delete=False)
    temp_file.write(image_bytes)
    temp_file.close()
    return Path(temp_file.name)


def _tesseract_language_from_ocr_language(ocr_language: str) -> str:
    lowered = (ocr_language or "").lower()
    languages: list[str] = []
    if "ko" in lowered or "kor" in lowered:
        languages.append("kor")
    if "en" in lowered or "eng" in lowered or not languages:
        languages.append("eng")
    return "+".join(languages)


def _run_tesseract_ocr(image_path: Path, ocr_language: str) -> tuple[str, str, str | None]:
    tesseract_path = shutil.which("tesseract")
    if not tesseract_path:
        return "", "", "tesseract 실행 파일을 찾지 못했습니다."
    language = _tesseract_language_from_ocr_language(ocr_language)
    try:
        completed = subprocess.run(
            [tesseract_path, str(image_path), "stdout", "-l", language],
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except subprocess.TimeoutExpired:
        return "", "Tesseract", "Tesseract OCR 시간이 초과되었습니다."
    except Exception as exc:
        return "", "Tesseract", f"Tesseract OCR 실행 중 오류가 발생했습니다: {exc}"

    ocr_text = "\n".join(
        _normalize_spaces(line) for line in completed.stdout.splitlines() if _normalize_spaces(line)
    )
    if completed.returncode != 0:
        error = _normalize_spaces(completed.stderr) or "알 수 없는 Tesseract OCR 오류입니다."
        return ocr_text, "Tesseract", f"Tesseract OCR에 실패했습니다: {error}"
    if not ocr_text:
        return "", "Tesseract", "Tesseract가 이미지에서 텍스트를 찾지 못했습니다."
    return ocr_text, "Tesseract", None


def _run_macos_vision_ocr(image_path: Path, ocr_language: str) -> tuple[str, str, str | None]:
    swift_path = Path("/usr/bin/swift")
    if not swift_path.exists():
        return "", "", "macOS Vision OCR을 실행할 Swift 런타임을 찾지 못했습니다."
    if not OCR_HELPER_PATH.exists():
        return "", "", "macOS Vision OCR helper 파일을 찾지 못했습니다."
    language = _normalize_spaces(ocr_language) or "ko-KR,en-US"
    swift_cache_dir = Path(tempfile.gettempdir()) / "talkguard-swift-cache"
    swift_cache_dir.mkdir(parents=True, exist_ok=True)
    for child in ("clang", "swift", "xdg"):
        (swift_cache_dir / child).mkdir(parents=True, exist_ok=True)
    swift_env = os.environ.copy()
    swift_env["CLANG_MODULE_CACHE_PATH"] = str(swift_cache_dir / "clang")
    swift_env["SWIFT_MODULE_CACHE_PATH"] = str(swift_cache_dir / "swift")
    swift_env["XDG_CACHE_HOME"] = str(swift_cache_dir / "xdg")
    try:
        completed = subprocess.run(
            [str(swift_path), "-suppress-warnings", str(OCR_HELPER_PATH), str(image_path), language],
            check=False,
            capture_output=True,
            text=True,
            env=swift_env,
            timeout=30,
        )
    except subprocess.TimeoutExpired:
        return "", "macOS Vision", "이미지 OCR 시간이 초과되었습니다. 더 선명하거나 작은 이미지로 다시 시도해 주세요."
    except Exception as exc:
        return "", "macOS Vision", f"이미지 OCR 실행 중 오류가 발생했습니다: {exc}"

    ocr_text = "\n".join(
        _normalize_spaces(line) for line in completed.stdout.splitlines() if _normalize_spaces(line)
    )
    if completed.returncode != 0:
        error = _normalize_spaces(completed.stderr) or "알 수 없는 OCR 오류입니다."
        return ocr_text, "macOS Vision", f"이미지 OCR에 실패했습니다: {error}"
    if not ocr_text:
        return "", "macOS Vision", "이미지에서 텍스트를 찾지 못했습니다. 해상도나 대비가 낮으면 OCR이 어려울 수 있습니다."
    return ocr_text, "macOS Vision", None


def _run_image_ocr(image_path: Path, ocr_language: str) -> tuple[str, str, list[str]]:
    warnings: list[str] = []
    tesseract_text, tesseract_engine, tesseract_warning = _run_tesseract_ocr(image_path, ocr_language)
    if tesseract_text:
        if tesseract_warning:
            warnings.append(tesseract_warning)
        return tesseract_text, tesseract_engine, warnings
    if tesseract_warning:
        warnings.append(tesseract_warning)

    vision_text, vision_engine, vision_warning = _run_macos_vision_ocr(image_path, ocr_language)
    if vision_text:
        if vision_warning:
            warnings.append(vision_warning)
        return vision_text, vision_engine, warnings
    if vision_warning:
        warnings.append(vision_warning)
    return "", vision_engine or tesseract_engine, warnings


def _unescape_ics_text(text: str) -> str:
    return (
        (text or "")
        .replace(r"\n", " ")
        .replace(r"\N", " ")
        .replace(r"\,", ",")
        .replace(r"\;", ";")
        .replace(r"\\", "\\")
    )


def _unfold_ics_lines(calendar_text: str) -> list[str]:
    unfolded: list[str] = []
    for raw_line in (calendar_text or "").splitlines():
        line = raw_line.rstrip("\r\n")
        if line.startswith((" ", "\t")) and unfolded:
            unfolded[-1] += line[1:]
        elif line:
            unfolded.append(line)
    return unfolded


def _parse_ics_property(line: str) -> tuple[str, dict[str, str], str] | None:
    if ":" not in line:
        return None
    left, value = line.split(":", 1)
    parts = left.split(";")
    name = parts[0].upper()
    params: dict[str, str] = {}
    for part in parts[1:]:
        if "=" in part:
            key, param_value = part.split("=", 1)
            params[key.upper()] = param_value.strip('"')
    return name, params, _unescape_ics_text(value)


def _extract_ics_events(calendar_text: str) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    current_event: dict[str, Any] | None = None
    for line in _unfold_ics_lines(calendar_text):
        upper_line = line.upper()
        if upper_line == "BEGIN:VEVENT":
            current_event = {}
            continue
        if upper_line == "END:VEVENT":
            if current_event is not None:
                events.append(current_event)
            current_event = None
            continue
        if current_event is None:
            continue

        parsed = _parse_ics_property(line)
        if not parsed:
            continue
        name, params, value = parsed
        if name in {"SUMMARY", "DESCRIPTION", "LOCATION", "UID", "STATUS"}:
            current_event[name.lower()] = value
        elif name in {"DTSTART", "DTEND"}:
            current_event[name.lower()] = {"value": value, "params": params}
    return events


def _format_date_text_from_datetime(value: datetime) -> str:
    return value.strftime("%Y-%m-%d")


def _format_time_text_from_datetime(value: datetime) -> str:
    hour = value.hour
    minute = value.minute
    meridiem = "오전" if hour < 12 else "오후"
    display_hour = hour if 1 <= hour <= 12 else hour - 12 if hour > 12 else 12
    if minute:
        return f"{meridiem} {display_hour}시 {minute}분"
    return f"{meridiem} {display_hour}시"


def _parse_ics_datetime_text(value: str, params: dict[str, str]) -> tuple[str, str, str | None]:
    normalized = _normalize_spaces(value)
    if not normalized:
        return "", "", "빈 캘린더 날짜 값입니다."

    try:
        if params.get("VALUE", "").upper() == "DATE" or re.fullmatch(r"\d{8}", normalized):
            parsed_date = datetime.strptime(normalized[:8], "%Y%m%d")
            return parsed_date.strftime("%Y-%m-%d"), "", None

        cleaned = normalized.rstrip("Z")
        parsed_datetime = datetime.strptime(cleaned[:15], "%Y%m%dT%H%M%S")
        if normalized.endswith("Z"):
            parsed_datetime = parsed_datetime.replace(tzinfo=UTC).astimezone(KST).replace(tzinfo=None)
        return _format_date_text_from_datetime(parsed_datetime), _format_time_text_from_datetime(parsed_datetime), None
    except ValueError:
        return "", "", f"캘린더 날짜 형식을 해석하지 못했습니다: {value}"


def _calendar_event_to_commitment(
    event: dict[str, Any],
    related_room: str,
) -> tuple[dict[str, Any] | None, str | None]:
    summary = _normalize_spaces(event.get("summary", "캘린더 일정"))
    description = _normalize_spaces(event.get("description", ""))
    location = _normalize_spaces(event.get("location", ""))
    status = _normalize_spaces(event.get("status", "")).upper()
    if status == "CANCELLED":
        return None, f"취소된 캘린더 일정은 건너뛰었습니다: {summary}"

    starts_at = event.get("dtstart")
    if not isinstance(starts_at, dict):
        return None, f"시작 시간이 없는 캘린더 일정은 건너뛰었습니다: {summary}"

    date_text, time_text, warning = _parse_ics_datetime_text(
        starts_at.get("value", ""),
        starts_at.get("params", {}),
    )
    if warning:
        return None, f"{summary}: {warning}"

    evidence_parts = [summary]
    if date_text:
        evidence_parts.append(date_text)
    if time_text:
        evidence_parts.append(time_text)
    if location:
        evidence_parts.append(f"장소: {location}")
    if description:
        evidence_parts.append(f"설명: {description}")
    evidence = " / ".join(evidence_parts)

    return (
        {
            "title": summary,
            "commitment_type": "meeting",
            "deadline_text": date_text,
            "time_text": time_text,
            "related_person": _extract_related_person_from_text(f"{summary} {description} {location}"),
            "related_room": _normalize_spaces(related_room),
            "source_type": "calendar",
            "importance": "high" if date_text else "medium",
            "status": "planned",
            "memo": f"캘린더 가져오기 근거: {evidence}",
            "confidence": 0.95 if date_text and time_text else 0.82,
            "evidence": evidence,
            "location": location,
        },
        None,
    )


class TalkGuardService:
    def __init__(self, db_path: str | Path = "data/talkguard.db") -> None:
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
                CREATE TABLE IF NOT EXISTS commitments (
                    id TEXT PRIMARY KEY,
                    workspace_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    commitment_type TEXT NOT NULL,
                    deadline_text TEXT NOT NULL DEFAULT '',
                    time_text TEXT NOT NULL DEFAULT '',
                    related_person TEXT NOT NULL DEFAULT '',
                    related_room TEXT NOT NULL DEFAULT '',
                    source_type TEXT NOT NULL,
                    importance TEXT NOT NULL,
                    status TEXT NOT NULL,
                    memo TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS room_contexts (
                    id TEXT PRIMARY KEY,
                    workspace_id TEXT NOT NULL,
                    room_name TEXT NOT NULL,
                    room_type TEXT NOT NULL,
                    context TEXT NOT NULL,
                    communication_goal TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_commitments_workspace
                ON commitments (workspace_id, created_at DESC);

                CREATE INDEX IF NOT EXISTS idx_room_contexts_workspace
                ON room_contexts (workspace_id, room_name, created_at DESC);
                """
            )
            self._ensure_column(connection, "room_contexts", "updated_at", "TEXT NOT NULL DEFAULT ''")
            connection.execute(
                "UPDATE room_contexts SET updated_at = created_at WHERE updated_at = '' OR updated_at IS NULL"
            )
            connection.commit()

    def _ensure_column(
        self,
        connection: sqlite3.Connection,
        table_name: str,
        column_name: str,
        column_definition: str,
    ) -> None:
        columns = {
            row["name"]
            for row in connection.execute(f"PRAGMA table_info({table_name})").fetchall()
        }
        if column_name not in columns:
            connection.execute(
                f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_definition}"
            )

    def _fetch_all(self, query: str, params: tuple[Any, ...]) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(query, params).fetchall()
        return [dict(row) for row in rows]

    def _fetch_one(self, query: str, params: tuple[Any, ...]) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(query, params).fetchone()
        return dict(row) if row else None

    def save_commitment(
        self,
        workspace_id: str,
        title: str,
        commitment_type: CommitmentType,
        deadline_text: str,
        time_text: str,
        related_person: str,
        related_room: str,
        source_type: SourceType,
        importance: CommitmentImportance,
        status: CommitmentStatus,
        memo: str,
    ) -> dict[str, Any]:
        normalized_workspace = workspace_id or DEFAULT_WORKSPACE_ID
        existing_commitments = self._fetch_all(
            """
            SELECT * FROM commitments
            WHERE workspace_id = ? AND status IN (?, ?, ?)
            ORDER BY created_at DESC
            """,
            (normalized_workspace, *sorted(ACTIVE_COMMITMENT_STATUSES)),
        )
        conflict_candidates = _build_same_schedule_conflict_candidates(
            commitments=existing_commitments,
            deadline_text=deadline_text,
            time_text=time_text,
        )

        commitment_id = f"commit_{uuid4().hex[:10]}"
        now = _now_iso()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO commitments (
                    id, workspace_id, title, commitment_type, deadline_text, time_text,
                    related_person, related_room, source_type, importance, status, memo,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    commitment_id,
                    normalized_workspace,
                    _normalize_spaces(title),
                    commitment_type,
                    _normalize_spaces(deadline_text),
                    _normalize_spaces(time_text),
                    _normalize_spaces(related_person),
                    _normalize_spaces(related_room),
                    source_type,
                    importance,
                    status,
                    _normalize_spaces(memo),
                    now,
                    now,
                ),
            )
            connection.commit()

        summary_parts = [
            f"'{title}' 약속을 저장했습니다.",
            f"유형: {_commitment_type_label(commitment_type)}",
            f"중요도: {_importance_label(importance)}",
            f"상태: {_commitment_status_label(status)}",
        ]
        if deadline_text:
            summary_parts.append(f"마감: {deadline_text}")
        if time_text:
            summary_parts.append(f"시간: {time_text}")
        warning = _join_warnings(
            _warning_for_same_schedule_conflict(deadline_text, time_text, conflict_candidates),
            _build_commitment_warning(commitment_type, deadline_text, time_text),
        )
        return {
            "saved": True,
            "commitment_id": commitment_id,
            "summary": " / ".join(summary_parts),
            "warning": warning,
            "conflict_detected": bool(conflict_candidates),
            "conflict_candidates": conflict_candidates,
        }

    def save_room_context(
        self,
        workspace_id: str,
        room_name: str,
        room_type: RoomType,
        context: str,
        communication_goal: str,
    ) -> dict[str, Any]:
        context_id = f"room_{uuid4().hex[:10]}"
        now = _now_iso()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO room_contexts (
                    id, workspace_id, room_name, room_type, context, communication_goal,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    context_id,
                    workspace_id or DEFAULT_WORKSPACE_ID,
                    _normalize_spaces(room_name),
                    room_type,
                    _normalize_spaces(context),
                    _normalize_spaces(communication_goal),
                    now,
                    now,
                ),
            )
            connection.commit()

        summary = (
            f"'{room_name}'의 {_room_type_label(room_type)} 맥락을 저장했습니다. "
            "발송 전 점검 시 이 관계의 우선순위와 말투 기준을 함께 확인합니다."
        )
        return {"saved": True, "room_name": room_name, "summary": summary}

    def explain_conversation_context(
        self,
        conversation_text: str,
        room_name: str,
        recipient_type: RecipientType | None,
    ) -> dict[str, Any]:
        normalized_text = _normalize_spaces(conversation_text)
        detected_jargon = _detect_jargon_terms(normalized_text)
        key_requests = _extract_instruction_sentences(normalized_text)
        reply_should_include = _extract_reply_requirement_items(normalized_text)
        plain_summary = _build_plain_context_summary(
            conversation_text=normalized_text,
            key_requests=key_requests,
            reply_should_include=reply_should_include,
        )
        checklist = _build_reply_checklist(reply_should_include)
        suggested_reply = _build_suggested_context_reply(reply_should_include, recipient_type)
        risk_note = (
            "답장에는 요청받은 항목과 다음 액션을 직접 써야 합니다. "
            "단순히 '확인했습니다'만 보내면 이전 대화의 핵심을 놓친 답장으로 보일 수 있습니다."
        )
        if not normalized_text:
            risk_note = "이전 대화 내용이 비어 있어 쉬운 설명과 답장 체크 기준을 만들 수 없습니다."

        return {
            "room_name": _normalize_spaces(room_name),
            "plain_summary": plain_summary,
            "detected_jargon": detected_jargon,
            "key_requests": key_requests,
            "reply_should_include": reply_should_include,
            "reply_checklist": checklist,
            "suggested_reply": suggested_reply,
            "risk_note": risk_note,
        }

    def _save_extracted_commitments(
        self,
        workspace_id: str,
        extracted_commitments: list[dict[str, Any]],
    ) -> tuple[list[str], list[str]]:
        saved_commitment_ids: list[str] = []
        warnings: list[str] = []
        for commitment in extracted_commitments:
            save_result = self.save_commitment(
                workspace_id=workspace_id,
                title=commitment["title"],
                commitment_type=commitment["commitment_type"],
                deadline_text=commitment["deadline_text"],
                time_text=commitment["time_text"],
                related_person=commitment["related_person"],
                related_room=commitment["related_room"],
                source_type=commitment["source_type"],
                importance=commitment["importance"],
                status=commitment["status"],
                memo=commitment["memo"],
            )
            saved_commitment_ids.append(save_result["commitment_id"])
            if save_result.get("warning"):
                warnings.append(f"{commitment['title']}: {save_result['warning']}")
        return saved_commitment_ids, warnings

    def extract_commitments_from_text(
        self,
        workspace_id: str,
        source_text: str,
        related_room: str,
        source_type: SourceType = "chat",
        save_extracted: bool = False,
    ) -> dict[str, Any]:
        normalized_workspace = workspace_id or DEFAULT_WORKSPACE_ID
        normalized_text = _normalize_spaces(source_text)
        warnings: list[str] = []
        extracted_commitments = _extract_commitment_candidates_from_text(
            source_text=source_text,
            related_room=related_room,
            source_type=source_type,
        )
        saved_commitment_ids: list[str] = []
        if save_extracted and extracted_commitments:
            saved_commitment_ids, save_warnings = self._save_extracted_commitments(
                workspace_id=normalized_workspace,
                extracted_commitments=extracted_commitments,
            )
            warnings.extend(save_warnings)
        if not normalized_text:
            warnings.append("추출할 텍스트가 비어 있습니다.")
        elif not extracted_commitments:
            warnings.append("날짜, 시간, 마감, 회의 같은 일정 신호를 찾지 못했습니다.")

        saved_count = len(saved_commitment_ids)
        summary = (
            f"텍스트에서 일정 후보 {len(extracted_commitments)}건을 추출했고, {saved_count}건을 저장했습니다."
            if save_extracted
            else f"텍스트에서 일정 후보 {len(extracted_commitments)}건을 추출했습니다."
        )
        return {
            "source_type": source_type,
            "extracted_count": len(extracted_commitments),
            "saved_count": saved_count,
            "commitments": extracted_commitments,
            "saved_commitment_ids": saved_commitment_ids,
            "extracted_text": normalized_text,
            "ocr_engine": "",
            "warnings": warnings,
            "summary": summary,
        }

    def extract_commitments_from_image(
        self,
        workspace_id: str,
        image_path: str = "",
        image_base64: str = "",
        related_room: str = "",
        save_extracted: bool = False,
        ocr_language: str = "ko-KR,en-US",
        ocr_text: str = "",
    ) -> dict[str, Any]:
        warnings: list[str] = []
        engine = ""
        temp_image_path: Path | None = None
        extracted_text = _normalize_spaces(ocr_text)
        image_path_obj: Path | None = None

        if not extracted_text:
            if image_base64:
                try:
                    temp_image_path = _decode_image_base64_to_temp_file(image_base64)
                    image_path_obj = temp_image_path
                except Exception as exc:
                    warnings.append(f"base64 이미지 해석에 실패했습니다: {exc}")
            elif image_path:
                image_path_obj = Path(image_path).expanduser()
                if not image_path_obj.exists():
                    warnings.append(f"이미지 파일을 찾지 못했습니다: {image_path}")
            else:
                warnings.append("이미지 OCR을 하려면 image_path 또는 image_base64가 필요합니다.")

            if image_path_obj and image_path_obj.exists():
                extracted_text, engine, ocr_warnings = _run_image_ocr(image_path_obj, ocr_language)
                warnings.extend(ocr_warnings)
        else:
            engine = "provided_text"

        try:
            result = self.extract_commitments_from_text(
                workspace_id=workspace_id,
                source_text=extracted_text,
                related_room=related_room,
                source_type="ocr",
                save_extracted=save_extracted,
            )
        finally:
            if temp_image_path and temp_image_path.exists():
                temp_image_path.unlink(missing_ok=True)

        result["ocr_engine"] = engine
        result["warnings"] = warnings + result["warnings"]
        if result["extracted_count"]:
            result["summary"] = (
                f"이미지 OCR 텍스트에서 일정 후보 {result['extracted_count']}건을 추출했고, "
                f"{result['saved_count']}건을 저장했습니다."
                if save_extracted
                else f"이미지 OCR 텍스트에서 일정 후보 {result['extracted_count']}건을 추출했습니다."
            )
        else:
            result["summary"] = "이미지에서 저장할 수 있는 일정 후보를 찾지 못했습니다."
        return result

    def import_calendar_events(
        self,
        workspace_id: str,
        calendar_text: str = "",
        calendar_file_path: str = "",
        related_room: str = "",
        save_imported: bool = True,
    ) -> dict[str, Any]:
        warnings: list[str] = []
        normalized_workspace = workspace_id or DEFAULT_WORKSPACE_ID
        source_text = calendar_text
        if not source_text and calendar_file_path:
            path = Path(calendar_file_path).expanduser()
            if path.exists():
                source_text = path.read_text(encoding="utf-8")
            else:
                warnings.append(f"캘린더 파일을 찾지 못했습니다: {calendar_file_path}")
        if not _normalize_spaces(source_text):
            warnings.append("가져올 캘린더 ICS 텍스트가 비어 있습니다.")

        imported_commitments: list[dict[str, Any]] = []
        for event in _extract_ics_events(source_text):
            commitment, warning = _calendar_event_to_commitment(event, related_room)
            if warning:
                warnings.append(warning)
            if commitment:
                imported_commitments.append(commitment)

        saved_commitment_ids: list[str] = []
        if save_imported and imported_commitments:
            saved_commitment_ids, save_warnings = self._save_extracted_commitments(
                workspace_id=normalized_workspace,
                extracted_commitments=imported_commitments,
            )
            warnings.extend(save_warnings)
        if source_text and not imported_commitments:
            warnings.append("VEVENT 캘린더 일정 후보를 찾지 못했습니다.")

        saved_count = len(saved_commitment_ids)
        summary = (
            f"캘린더에서 일정 {len(imported_commitments)}건을 가져왔고, {saved_count}건을 저장했습니다."
            if save_imported
            else f"캘린더에서 일정 {len(imported_commitments)}건을 가져왔습니다."
        )
        return {
            "source_type": "calendar",
            "extracted_count": len(imported_commitments),
            "saved_count": saved_count,
            "commitments": imported_commitments,
            "saved_commitment_ids": saved_commitment_ids,
            "extracted_text": _normalize_spaces(source_text),
            "ocr_engine": "",
            "warnings": warnings,
            "summary": summary,
        }

    def get_guard_summary(self, workspace_id: str) -> dict[str, Any]:
        commitments = self._fetch_all(
            "SELECT * FROM commitments WHERE workspace_id = ? ORDER BY created_at DESC",
            (workspace_id,),
        )
        room_contexts = self._fetch_all(
            "SELECT * FROM room_contexts WHERE workspace_id = ? ORDER BY created_at DESC",
            (workspace_id,),
        )

        next_risks_to_watch: list[str] = []
        for commitment in commitments:
            if commitment["status"] in ACTIVE_COMMITMENT_STATUSES and commitment["importance"] == "high":
                label = _extract_focus_phrase(commitment["title"]) or commitment["title"]
                due = commitment["deadline_text"] or commitment["time_text"] or "일정 확인 필요"
                next_risks_to_watch.append(f"{label}: {due} 약속을 놓치지 않도록 확인이 필요합니다.")
        if not next_risks_to_watch and (commitments or room_contexts):
            next_risks_to_watch.append("현재 저장된 기록 기준으로 즉시 눈에 띄는 충돌 경고는 크지 않습니다.")
        if not commitments and not room_contexts:
            next_risks_to_watch.append("아직 저장된 기록이 없어 먼저 약속과 대화 맥락을 저장하는 것이 좋습니다.")

        summary_parts = [
            f"현재 워크스페이스에는 약속 {len(commitments)}건, 대화 맥락 {len(room_contexts)}건이 저장되어 있습니다."
        ]
        high_commitments = [c for c in commitments if c["importance"] == "high" and c["status"] in ACTIVE_COMMITMENT_STATUSES]
        if high_commitments:
            summary_parts.append(
                f"우선 확인할 높은 중요도 약속은 {', '.join(_extract_focus_phrase(c['title']) or c['title'] for c in high_commitments[:3])}입니다."
            )
        if room_contexts:
            summary_parts.append("이제 발송 전 점검 시 대화방 맥락과 약속 충돌을 함께 비교할 수 있습니다.")

        return {
            "commitments": commitments,
            "room_contexts": room_contexts,
            "summary": " ".join(summary_parts),
            "next_risks_to_watch": next_risks_to_watch,
        }

    def _build_safer_message(
        self,
        draft_message: str,
        room_context: dict[str, Any] | None,
        deadline_conflict_commitment: dict[str, Any] | None,
        schedule_conflict_commitment: dict[str, Any] | None,
        missing_items: list[str],
        flags: dict[str, bool],
    ) -> str:
        sentences: list[str] = []

        if deadline_conflict_commitment:
            title_phrase = _extract_focus_phrase(deadline_conflict_commitment["title"]) or deadline_conflict_commitment["title"]
            deadline = deadline_conflict_commitment["deadline_text"] or "기존 일정"
            sentences.append(
                f"{deadline}까지 {title_phrase} 초안을 먼저 공유드리고, 추가 정리는 이후에 보완하겠습니다."
            )

        if schedule_conflict_commitment:
            date_phrase = schedule_conflict_commitment["deadline_text"] or "해당 시간"
            time_phrase = schedule_conflict_commitment["time_text"] or "기존 일정 시간"
            alternate = _suggest_alternate_time(schedule_conflict_commitment["time_text"])
            sentences.append(
                f"{date_phrase} {time_phrase}는 기존 일정이 있어 어렵고, {alternate} 가능할 것 같습니다."
            )

        if flags.get("missing_commitment") and missing_items:
            item = missing_items[0]
            if not any(item in sentence for sentence in sentences):
                sentences.append(f"{item} 관련 일정과 범위도 함께 분명히 말씀드리겠습니다.")

        if flags.get("missing_instruction") and missing_items:
            instruction_items = ", ".join(missing_items[:3])
            if not any(instruction_items in sentence for sentence in sentences):
                sentences.append(
                    f"이전 대화 기준으로 빠진 항목({instruction_items})을 확인했고, 진행 가능 여부와 다음 액션도 함께 말씀드리겠습니다."
                )

        if not sentences and room_context and room_context.get("communication_goal"):
            sentences.append(f"{room_context['communication_goal']}에 맞춰 현재 상태와 다음 일정을 함께 정리해 말씀드리겠습니다.")

        if not sentences:
            sentences.append(_replace_tone_risky_words(draft_message).rstrip(".") + ".")

        return " ".join(_normalize_spaces(sentence) for sentence in sentences if sentence)

    def _run_promiseguard_engine(
        self,
        draft_message: str,
        commitments: list[dict[str, Any]],
        room_context: dict[str, Any] | None,
        recipient_type: RecipientType | None,
        extra_context: str,
        previous_conversation: str,
        room_name: str,
    ) -> dict[str, Any]:
        relevant_commitments = [
            commitment
            for commitment in commitments
            if _is_relevant_commitment(commitment, room_name, draft_message, extra_context)
        ]
        recipient = recipient_type or (room_context["room_type"] if room_context else None)

        detected_conflicts: list[str] = []
        evidence: list[str] = []
        missing_items: list[str] = []
        checklist_before_send: list[str] = []
        flags = {
            "missing_commitment": False,
            "missing_instruction": False,
        }
        deadline_conflict_commitment: dict[str, Any] | None = None
        schedule_conflict_commitment: dict[str, Any] | None = None

        deadline_conflict_score = 0
        schedule_conflict_score = 0
        missing_commitment_score = 0
        instruction_alignment_score = 0
        tone_risk_score = 0

        for commitment in relevant_commitments:
            if not commitment["deadline_text"]:
                continue
            later, draft_date_phrase = _is_later_deadline(commitment["deadline_text"], draft_message)
            topic = _extract_focus_phrase(commitment["title"])
            if later and (not topic or _draft_mentions_item(draft_message, topic) or commitment["related_room"] == room_name):
                deadline_conflict_commitment = commitment
                deadline_conflict_score = max(
                    deadline_conflict_score,
                    70 if commitment["importance"] == "high" else 55,
                )
                detected_conflicts.append(
                    f"마감 약속 충돌: 기존 약속은 {commitment['deadline_text']}까지 {topic or commitment['title']} 관련 공유였는데, 현재 메시지는 {draft_date_phrase}로 미루는 표현입니다."
                )
                evidence.append(
                    f"저장된 약속: {commitment['title']} / 마감: {commitment['deadline_text']} / 중요도: {_importance_label(commitment['importance'])}"
                )
                checklist_before_send.append("기존에 약속한 마감보다 늦어지는 표현이 없는지 다시 확인하세요.")
                break

        for commitment in relevant_commitments:
            saved_date = commitment["deadline_text"]
            saved_time = commitment["time_text"]
            draft_date = _extract_date_phrase(draft_message)
            draft_time = _extract_time_phrase(draft_message)
            if (
                saved_date
                and saved_time
                and draft_date
                and draft_time
                and _date_keys_match(saved_date, draft_message)
                and _time_keys_match(saved_time, draft_message)
                and _contains_availability_claim(draft_message)
            ):
                schedule_conflict_commitment = commitment
                schedule_conflict_score = max(
                    schedule_conflict_score,
                    70 if commitment["importance"] == "high" else 55,
                )
                detected_conflicts.append(
                    f"일정 충돌: {saved_date} {saved_time}에는 이미 저장된 일정이 있는데, 현재 메시지는 같은 시간에 가능하다고 말하고 있습니다."
                )
                evidence.append(
                    f"저장된 일정: {commitment['title']} / 날짜: {saved_date} / 시간: {saved_time}"
                )
                checklist_before_send.append("가능하다고 답하기 전에 같은 시간의 기존 일정이 있는지 확인하세요.")
                break

        important_candidates: list[str] = []
        for commitment in relevant_commitments:
            if commitment["importance"] == "high" and commitment["commitment_type"] != "meeting":
                phrase = _extract_focus_phrase(commitment["title"])
                if phrase:
                    important_candidates.append(phrase)
        if room_context:
            important_candidates.extend(_extract_context_focus_items(room_context["context"]))
            important_candidates.extend(_extract_context_focus_items(room_context["communication_goal"]))
        unique_candidates: list[str] = []
        for item in important_candidates:
            if item and item not in unique_candidates:
                unique_candidates.append(item)
        checked_text = f"{draft_message} {extra_context}"
        missing_items = [item for item in unique_candidates if not _draft_mentions_item(checked_text, item)]
        if missing_items:
            flags["missing_commitment"] = True
            missing_commitment_score = min(40, 30 + 4 * len(missing_items))
            detected_conflicts.append(
                "중요 항목 누락 가능성: 저장된 약속이나 대화 맥락의 핵심 항목이 현재 메시지에 충분히 드러나지 않습니다."
            )
            evidence.append("누락 가능 항목: " + ", ".join(missing_items[:4]))
            checklist_before_send.append("상대가 중요하게 보는 약속이나 산출물을 메시지에 한 번은 직접 언급하세요.")

        instruction_sources: list[str] = []
        normalized_previous_conversation = _normalize_spaces(previous_conversation)
        if normalized_previous_conversation:
            instruction_sources.append(normalized_previous_conversation)
        elif room_context:
            room_instruction_text = f"{room_context['context']} {room_context['communication_goal']}"
            if _looks_like_complex_instruction(room_instruction_text):
                instruction_sources.append(room_instruction_text)

        reply_requirement_items: list[str] = []
        for source in instruction_sources:
            for item in _extract_reply_requirement_items(source):
                if item and item not in reply_requirement_items:
                    reply_requirement_items.append(item)

        missing_instruction_items = [
            item for item in reply_requirement_items if not _draft_covers_reply_item(draft_message, item)
        ]
        if missing_instruction_items:
            flags["missing_instruction"] = True
            instruction_alignment_score = min(55, 35 + 5 * len(missing_instruction_items))
            for item in missing_instruction_items:
                if item not in missing_items:
                    missing_items.append(item)
            detected_conflicts.append(
                "이전 대화 답변 누락 가능성: 복잡한 업무지시나 이전 대화의 핵심 포인트가 현재 답장에 충분히 반영되지 않았습니다."
            )
            evidence.append("답장에 빠진 이전 대화 포인트: " + ", ".join(missing_instruction_items[:5]))
            checklist_before_send.append("이전 대화의 요청 항목, 일정, 리스크, 다음 액션을 답장에 직접 포함하세요.")

        tone_risk_terms = (
            "했는데요",
            "아닌데요",
            "왜요",
            "그건 좀",
            "대충",
            "아마",
            "될 것 같아요",
            "무조건",
            "완벽히",
            "문제 없습니다",
        )
        matched_tone_terms = [term for term in tone_risk_terms if term in draft_message]
        if recipient in {"professor", "client", "important"} and matched_tone_terms:
            tone_risk_score = 15
            detected_conflicts.append(
                f"톤 위험: {_room_type_label(recipient)} 관계에는 가볍거나 방어적으로 들릴 수 있는 표현이 포함되어 있습니다."
            )
            evidence.append(
                f"감지된 표현: {', '.join(matched_tone_terms)} / 수신자 유형: {_room_type_label(recipient)}"
            )
            checklist_before_send.append("교수·고객·중요 관계에는 단정하고 공손한 문장으로 다듬어 주세요.")

        final_risk_score = min(
            100,
            deadline_conflict_score
            + schedule_conflict_score
            + missing_commitment_score
            + instruction_alignment_score
            + tone_risk_score,
        )

        if not detected_conflicts:
            detected_conflicts.append("뚜렷한 충돌 신호는 발견되지 않았습니다.")
            evidence.append("저장된 약속과 대화 맥락 기준에서 직접 충돌하는 표현은 크게 보이지 않았습니다.")
            checklist_before_send.append("보내기 전 날짜, 시간, 상대방 기대치만 마지막으로 한 번 더 확인하세요.")
            final_risk_score = 10

        risk_level: Literal["low", "medium", "high"]
        if final_risk_score >= 70:
            risk_level = "high"
        elif final_risk_score >= 31:
            risk_level = "medium"
        else:
            risk_level = "low"

        safer_message = self._build_safer_message(
            draft_message=draft_message,
            room_context=room_context,
            deadline_conflict_commitment=deadline_conflict_commitment,
            schedule_conflict_commitment=schedule_conflict_commitment,
            missing_items=missing_items,
            flags=flags,
        )

        return {
            "deadline_conflict_score": deadline_conflict_score,
            "schedule_conflict_score": schedule_conflict_score,
            "missing_commitment_score": missing_commitment_score,
            "instruction_alignment_score": instruction_alignment_score,
            "tone_risk_score": tone_risk_score,
            "final_risk_score": final_risk_score,
            "risk_level": risk_level,
            "detected_conflicts": detected_conflicts,
            "evidence": evidence,
            "missing_items": missing_items,
            "safer_message": safer_message,
            "checklist_before_send": checklist_before_send,
        }

    def review_message_before_send(
        self,
        workspace_id: str,
        draft_message: str,
        room_name: str,
        recipient_type: RecipientType | None,
        extra_context: str,
        previous_conversation: str = "",
    ) -> dict[str, Any]:
        normalized_workspace = workspace_id or DEFAULT_WORKSPACE_ID
        commitments = self._fetch_all(
            "SELECT * FROM commitments WHERE workspace_id = ? ORDER BY created_at DESC",
            (normalized_workspace,),
        )
        room_context = None
        if room_name:
            room_context = self._fetch_one(
                """
                SELECT * FROM room_contexts
                WHERE workspace_id = ? AND room_name = ?
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (normalized_workspace, room_name),
            )

        engine_result = self._run_promiseguard_engine(
            draft_message=draft_message,
            commitments=commitments,
            room_context=room_context,
            recipient_type=recipient_type,
            extra_context=extra_context,
            previous_conversation=previous_conversation,
            room_name=room_name,
        )

        return {
            "risk_level": engine_result["risk_level"],
            "final_risk_score": engine_result["final_risk_score"],
            "detected_conflicts": engine_result["detected_conflicts"],
            "evidence": engine_result["evidence"],
            "missing_items": engine_result["missing_items"],
            "safer_message": engine_result["safer_message"],
            "checklist_before_send": engine_result["checklist_before_send"],
            "context_used": {
                "commitment_count": len(commitments),
                "room_context_found": room_context is not None,
                "previous_conversation_found": bool(_normalize_spaces(previous_conversation)),
            },
            "disclaimer": "최종 전송 여부는 사용자가 직접 확인해야 합니다.",
        }
