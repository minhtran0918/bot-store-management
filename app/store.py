from __future__ import annotations
import csv
import json
from datetime import datetime
from pathlib import Path
from hashlib import md5

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)

TODAY = datetime.now().strftime("%Y-%m-%d")
STATE_FILE = DATA_DIR / f"processed_{TODAY}.json"
LOG_FILE = DATA_DIR / f"actions_{TODAY}.csv"


def _safe_file_part(value: str) -> str:
    raw = (value or "").strip().replace(" ", "_")
    allowed = []
    for ch in raw:
        if ch.isalnum() or ch in ("_", "-"):
            allowed.append(ch)
    result = "".join(allowed)
    return result[:60] or "campaign"


def _read_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _write_json(path: Path, data: dict) -> None:
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )


def load_state() -> dict:
    return _read_json(STATE_FILE)


def save_state(state: dict) -> None:
    _write_json(STATE_FILE, state)


def text_hash(text: str) -> str:
    norm = (text or "").strip()
    if not norm:
        return "empty"
    return md5(norm.encode("utf-8")).hexdigest()


def get_order_state(order_code: str) -> dict | None:
    state = load_state()
    return state.get(order_code)


def upsert_order_state(order_code: str, payload: dict) -> None:
    state = load_state()
    state[order_code] = payload
    save_state(state)


def log_action(order_code: str, action: str, result: str, detail: str = "") -> None:
    new_file = not LOG_FILE.exists()
    with LOG_FILE.open("a", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        if new_file:
            writer.writerow(["time", "order_code", "action", "result", "detail"])
        writer.writerow([datetime.now().isoformat(), order_code, action, result, detail])


def save_filtered_orders(
    rows: list[dict[str, str]],
    campaign_label: str,
    output_dir: Path | None = None,
    output_path: Path | None = None,
) -> Path:
    target_dir = output_dir or DATA_DIR
    target_dir.mkdir(parents=True, exist_ok=True)

    if output_path is None:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        campaign_part = _safe_file_part(campaign_label.replace("LIVE", "", 1).strip())
        path = target_dir / f"orders_{campaign_part}_{stamp}.csv"
    else:
        path = output_path
        path.parent.mkdir(parents=True, exist_ok=True)

    headers = [
        "No",
        "Order_Code",
        "Tag",
        "Channel",
        "Customer",
        "Total_Amount",
        "Total_Qty",
        "Address_Status",
        "Note",
        "Match_Product",
        "Decision",
    ]

    temp_path = path.with_suffix(f"{path.suffix}.tmp")

    with temp_path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=headers)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: str(row.get(k, "")).strip() for k in headers})

    temp_path.replace(path)

    # Re-open once after write to ensure file is immediately readable on disk.
    path.read_text(encoding="utf-8-sig")

    return path
