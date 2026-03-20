from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path

from app.cli_menu import select, text_input, show_summary

FEATURE_CONFIRM_ORDER = "confirm_order"
FEATURE_ADD_PRODUCT = "add_product_to_order"

TOTAL_STEPS = 3


def prompt_feature_run() -> str:
    choices = [
        {"name": "confirm_order        — xác nhận đơn hàng (check sản phẩm/địa chỉ, gửi tin nhắn ảnh & bill cho khách)", "value": FEATURE_CONFIRM_ORDER},
        {"name": "add_product_to_order — thêm sản phẩm vào đơn hàng (thêm sản phẩm & chỉnh giá từ file csv)", "value": FEATURE_ADD_PRODUCT},
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


def _list_existing_order_csv_files(data_dir: Path) -> list[Path]:
    if not data_dir.exists():
        return []

    files = [p for p in data_dir.glob("orders_*.csv") if p.is_file()]
    files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return files


PRICE_CODE_KEYS = [f"A{i}" for i in range(1, 10)]  # A1..A9


def prompt_price_code_mapping() -> dict[str, int | None]:
    """Step 3/3: prompt user to input price values for A1-A9 codes.

    Enter = null (skip). These map product alias codes in notes to actual prices.
    """
    mapping: dict[str, int | None] = {}
    for key in PRICE_CODE_KEYS:
        raw = text_input(f"{key} price (enter=skip)", step=3, total=TOTAL_STEPS)
        if raw:
            try:
                mapping[key] = int(raw)
            except ValueError:
                mapping[key] = None
        else:
            mapping[key] = None
    return mapping


def prompt_existing_csv_required(data_dir: Path) -> Path | None:
    csv_files = _list_existing_order_csv_files(data_dir)
    if not csv_files:
        print("No existing orders CSV found. Please run collect_order first.")
        return None

    choices = []
    for path in csv_files:
        modified_at = datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
        choices.append({"name": f"{path.name}  ({modified_at})", "value": str(path)})

    selected = select("Select Input CSV", choices, step=3, total=TOTAL_STEPS)
    return Path(selected)
