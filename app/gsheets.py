"""Google Sheets writer — dùng cho broadcast_order để sync tagged items.

Yêu cầu:
  pip install gspread google-auth

Credentials:
  Service Account JSON tại đường dẫn cấu hình trong config.yaml
  (broadcast_order.gsheets.credentials_file)

Cách dùng:
  writer = GSheetWriter(creds_file, spreadsheet_id, sheet_name, log_fn)
  writer.sync(messages_dict, tags_dict)
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable

try:
    import gspread
    from google.oauth2.service_account import Credentials as _SACredentials

    _GSPREAD_OK = True
except ImportError:
    _GSPREAD_OK = False

_SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

_HEADERS = [
    "ID",
    "Loại",
    "Người gửi",
    "Nội dung",
    "Mã đơn hàng",
    "Trạng thái tag",
    "Ghi chú",
    "Thời gian tag",
]


class GSheetWriter:
    """Ghi / cập nhật tagged items vào một worksheet Google Sheets.

    Mỗi lần ``sync()`` được gọi:
      - Xóa toàn bộ nội dung cũ từ hàng 2 trở xuống.
      - Ghi lại tất cả mục đang được tag theo thứ tự tagged_at.
      - Hàng 1 luôn là header (không bị xóa).
    """

    def __init__(
        self,
        credentials_file: Path,
        spreadsheet_id: str,
        sheet_name: str,
        log_fn: Callable[[str], None],
    ) -> None:
        if not _GSPREAD_OK:
            raise ImportError(
                "Thiếu thư viện gspread / google-auth. "
                "Chạy: pip install gspread google-auth"
            )
        self._creds_file = Path(credentials_file)
        self._spreadsheet_id = spreadsheet_id.strip()
        self._sheet_name = sheet_name
        self._log = log_fn
        self._ws: "gspread.Worksheet | None" = None
        self._connect()

    # ── Connection ────────────────────────────────────────────────────────────

    def _connect(self) -> None:
        creds = _SACredentials.from_service_account_file(
            str(self._creds_file), scopes=_SCOPES
        )
        client = gspread.authorize(creds)
        spreadsheet = client.open_by_key(self._spreadsheet_id)
        try:
            ws = spreadsheet.worksheet(self._sheet_name)
        except gspread.WorksheetNotFound:
            ws = spreadsheet.add_worksheet(
                title=self._sheet_name, rows=2000, cols=len(_HEADERS)
            )
            self._log(f"[GSHEETS] Created new worksheet: {self._sheet_name!r}")
        self._ws = ws
        self._log(f"[GSHEETS] Connected OK → {self._sheet_name!r}")

    # ── Sync ─────────────────────────────────────────────────────────────────

    def sync(self, messages: dict | None, tags: dict[str, dict]) -> None:
        """Ghi toàn bộ tagged items lên worksheet.

        Args:
            messages: Dữ liệu API mới nhất (có key ``Data`` là list items).
            tags:     Dict ``{item_id: {status, note, tagged_at}}``.
        """
        if self._ws is None:
            return

        # Build lookup: id → item dict
        items_by_id: dict[str, dict] = {}
        if messages and isinstance(messages.get("Data"), list):
            for item in messages["Data"]:
                item_id = item.get("Id")
                if item_id:
                    items_by_id[item_id] = item

        # Build rows — sorted by tagged_at ascending
        data_rows: list[list] = []
        for item_id, tag_info in sorted(
            tags.items(), key=lambda kv: kv[1].get("tagged_at", "")
        ):
            item = items_by_id.get(item_id, {})
            row = _build_row(item_id, item, tag_info)
            data_rows.append(row)

        # Write to sheet: header always on row 1, then data
        self._ws.update([_HEADERS], "A1")
        if data_rows:
            self._ws.update(data_rows, "A2")
            # Clear stale rows below new data
            last_row = 1 + len(data_rows)
            self._ws.batch_clear([f"A{last_row + 1}:H3000"])
        else:
            self._ws.batch_clear(["A2:H3000"])

        self._log(f"[GSHEETS] Synced {len(data_rows)} tagged item(s) → Sheets")


# ── Helpers ───────────────────────────────────────────────────────────────────


def _build_row(item_id: str, item: dict, tag_info: dict) -> list:
    """Tạo một hàng dữ liệu cho worksheet từ item + tag."""
    item_type = item.get("Type", "")

    if item.get("IsOwner"):
        sender = (item.get("ApplicationUser") or {}).get("Name", "Shop")
    else:
        sender = (
            (item.get("From") or {}).get("Name", "")
            or (item.get("ApplicationUser") or {}).get("Name", "")
        )

    message = (item.get("Message") or "").replace("\n", " ").strip()

    order_data = (item.get("Order") or {}).get("Data") or []
    orders = ", ".join(o.get("Code", "") for o in order_data if o.get("Code"))

    return [
        item_id,
        item_type,
        sender,
        message,
        orders,
        tag_info.get("status", ""),
        tag_info.get("note", ""),
        tag_info.get("tagged_at", ""),
    ]


# ── Factory ───────────────────────────────────────────────────────────────────


def make_gsheet_writer(
    gsheets_cfg: dict,
    base_dir: Path,
    log_fn: Callable[[str], None],
) -> "GSheetWriter | None":
    """Tạo GSheetWriter từ config dict, trả về None nếu disabled hoặc lỗi.

    Config dict (broadcast_order.gsheets):
      enabled:          true/false
      credentials_file: "app/gsheets_credentials.json"
      spreadsheet_id:   "<Google Sheets ID>"
      sheet_name:       "Broadcast"
    """
    if not gsheets_cfg.get("enabled"):
        return None

    spreadsheet_id = str(gsheets_cfg.get("spreadsheet_id") or "").strip()
    if not spreadsheet_id:
        log_fn("[GSHEETS] Skipped — spreadsheet_id not configured")
        return None

    creds_path = base_dir / str(
        gsheets_cfg.get("credentials_file", "app/gsheets_credentials.json")
    )
    if not creds_path.exists():
        log_fn(f"[GSHEETS] Credentials file not found: {creds_path}")
        return None

    sheet_name = str(gsheets_cfg.get("sheet_name") or "Broadcast")

    try:
        return GSheetWriter(creds_path, spreadsheet_id, sheet_name, log_fn)
    except Exception as exc:
        log_fn(f"[GSHEETS] Init error: {exc}")
        return None
