from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path

from app.cli_menu import select, text_input, show_summary

FEATURE_CONFIRM_ORDER = "confirm_order"
TOTAL_STEPS = 4


def prompt_feature_run() -> str:
    choices = [
        {"name": "confirm_order        — xác nhận đơn hàng (check sản phẩm/địa chỉ, gửi tin nhắn ảnh & bill cho khách)", "value": FEATURE_CONFIRM_ORDER},
    ]
    return select("Select Feature", choices, step=1, total=TOTAL_STEPS, default=FEATURE_CONFIRM_ORDER)


def resolve_campaign_date(raw_input: str, fallback_year: int, now_date: date | None = None) -> str:
    raw = (raw_input or "").strip()
    today = now_date or datetime.now().date()

    if not raw or raw.lower() == "yesterday":
        d = today - timedelta(days=1)
        return f"{d.day}/{d.month}/{d.year}"

    if raw.lower() == "today":
        return f"{today.day}/{today.month}/{today.year}"

    if raw.count("/") >= 2:
        return raw

    if raw.count("/") == 1:
        day_str, month_str = raw.split("/", 1)
        day = int(day_str)
        month = int(month_str)
        d = date(fallback_year, month, day)
        return f"{d.day}/{d.month}/{d.year}"

    if "-" in raw:
        parsed = datetime.fromisoformat(raw).date()
        return f"{parsed.day}/{parsed.month}/{parsed.year}"

    raise ValueError(
        "Invalid --campaign-date. Use today, yesterday, d/m, d/m/yyyy, yyyy-mm-dd, or 'LIVE d/m/yyyy'."
    )


def build_campaign_label(campaign_date: str, campaign_year: int) -> str:
    raw = (campaign_date or "").strip()
    if not raw:
        raw = "yesterday"

    if raw.lower().startswith("live "):
        return f"LIVE {raw[5:].strip()}"

    resolved = resolve_campaign_date(raw, campaign_year)
    return f"LIVE {resolved}"


def prompt_campaign_label() -> str:
    current_year = datetime.now().year
    yesterday_label = build_campaign_label("yesterday", current_year)
    today_label = build_campaign_label("today", current_year)

    choices = [
        {"name": f"yesterday     — {yesterday_label}", "value": "yesterday"},
        {"name": f"today         — {today_label}", "value": "today"},
        {"name": "custom date   — d/m, d/m/yyyy, yyyy-mm-dd", "value": "custom_date"},
        {"name": "full label    — e.g. LIVE 14/3/2026", "value": "custom_label"},
    ]
    selected = select("Select Campaign Date", choices, step=2, total=TOTAL_STEPS, default="yesterday")

    if selected == "today":
        return today_label
    if selected == "custom_date":
        custom = text_input("Enter date (d/m or d/m/yyyy):", step=2, total=TOTAL_STEPS)
        return build_campaign_label(custom, current_year)
    if selected == "custom_label":
        custom = text_input("Enter full campaign label:", step=2, total=TOTAL_STEPS)
        return build_campaign_label(custom, current_year)
    return yesterday_label


def prompt_tag_1_2_only() -> bool:
    choices = [
        {"name": "Không            — xử lý theo tất cả tag", "value": "no"},
        {"name": "Có               — chỉ xử lý TAG 1 và TAG 2", "value": "yes"},
    ]
    return select("Chỉ chạy TAG 1 & TAG 2", choices, step=3, total=TOTAL_STEPS, default="no") == "yes"


MAX_A_CODES = 9  # A1..A9


def prompt_price_code_mapping() -> dict[str, int | None]:
    """Step 4/4: prompt user to input price values for A-codes.

    First asks how many A-codes are active today (default 0 = none).
    Then prompts price for each A1..An.
    """
    raw_count = text_input("Number of A-codes today (0-9, enter=0)", step=4, total=TOTAL_STEPS)
    try:
        num_codes = max(0, min(MAX_A_CODES, int(raw_count)))
    except (TypeError, ValueError):
        num_codes = 0

    mapping: dict[str, int | None] = {}
    for i in range(1, num_codes + 1):
        key = f"A{i}"
        raw = text_input(f"{key} price", step=4, total=TOTAL_STEPS)
        if raw:
            try:
                mapping[key] = int(raw)
            except ValueError:
                mapping[key] = None
        else:
            mapping[key] = None
    return mapping


