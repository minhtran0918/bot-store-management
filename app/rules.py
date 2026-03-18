from __future__ import annotations

from datetime import datetime, timedelta

from .store import text_hash


PICKUP_KEYWORDS = [
    "ghé lấy",
    "tự lấy",
    "lấy tại shop",
    "không cần gửi hàng",
    "mai ghé lấy"
]

RESEND_COOLDOWN_HOURS = 24


def _parse_iso_datetime(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return None


def classify_order(note: str, address: str, pickup_keywords: list[str] | None = None) -> str:
    note_l = (note or "").lower()
    address_l = (address or "").strip()
    keywords = pickup_keywords or PICKUP_KEYWORDS

    for kw in keywords:
        if kw in note_l:
            return "pickup"

    if not address_l:
        return "need_address"

    return "has_address"


def should_skip(existing: dict | None, note: str, address: str) -> bool:
    if not existing:
        return False

    if existing.get("note_hash") == text_hash(note) and existing.get("address_hash") == text_hash(address):
        if existing.get("state") in {"asked_address", "done", "pickup"}:
            return True

    return False


def should_resend_ask(
    existing: dict | None,
    now: datetime | None = None,
    cooldown_hours: int = RESEND_COOLDOWN_HOURS,
) -> bool:
    if not existing or existing.get("state") != "asked_address":
        return False

    last_action_at = _parse_iso_datetime(existing.get("last_action_at"))
    if not last_action_at:
        return True

    now_dt = now or datetime.now()
    return now_dt - last_action_at >= timedelta(hours=cooldown_hours)


def decide_action(
    note: str,
    address: str,
    existing: dict | None,
    pickup_keywords: list[str] | None = None,
) -> str:
    """Return a concrete action for the current order state."""
    decision = classify_order(note, address, pickup_keywords=pickup_keywords)

    if decision == "pickup":
        return "pickup"

    if decision == "has_address":
        return "mark_done"

    if should_resend_ask(existing):
        return "send_ask_address"

    if existing and existing.get("state") == "asked_address":
        return "skip_already_asked"

    return "send_ask_address"
