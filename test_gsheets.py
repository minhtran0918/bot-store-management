"""Quick standalone test for Google Sheets sync (no browser needed).

Run:
    python test_gsheets.py
"""

import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

from pathlib import Path
from app.gsheets import make_gsheet_writer

BASE_DIR = Path(__file__).parent

# ── Config giả lập từ config.yaml ────────────────────────────────────────────
gsheets_cfg = {
    "enabled": True,
    "credentials_file": "app/gsheets_credentials.json",
    "spreadsheet_id": "1pMEWw-661XgZB5mF7-8APf6BvQeqMnqBZ-_3g3bMOVI",
    "sheet_name": "Broadcast",
}

# ── Sample messages (giả lập dữ liệu API) ────────────────────────────────────
sample_messages = {
    "is_sample": True,
    "Data": [
        {
            "Id": "sample-001",
            "Type": "comment",
            "IsOwner": False,
            "Message": "1 bộ size M",
            "CreatedTime": "2026-03-22T10:00:00.000Z",
            "Order": {"Count": 1, "Data": [{"Code": "ORD20240001"}]},
            "From": {"Name": "Nguyễn Thị Hoa"},
        },
        {
            "Id": "sample-002",
            "Type": "message",
            "IsOwner": True,
            "ApplicationUser": {"Name": "Linh Đan"},
            "Message": "Dạ chị! Shop lên đơn cho chị rồi ạ.",
            "CreatedTime": "2026-03-22T10:05:00.000Z",
            "Order": {"Count": 1, "Data": [{"Code": "ORD20240001"}]},
        },
        {
            "Id": "sample-003",
            "Type": "comment",
            "IsOwner": False,
            "Message": "2 bộ **********",
            "CreatedTime": "2026-03-22T10:10:00.000Z",
            "Order": {"Count": 1, "Data": [{"Code": "ORD20240002"}]},
            "From": {"Name": "Trần Thị Lan"},
        },
    ],
}

# ── Sample tags ───────────────────────────────────────────────────────────────
sample_tags = {
    "sample-001": {
        "status": "ok",
        "note": "Đã xử lý xong",
        "tagged_at": "2026-03-22T10:15:00",
    },
    "sample-003": {
        "status": "pending",
        "note": "Chờ xác nhận địa chỉ",
        "tagged_at": "2026-03-22T10:20:00",
    },
}


def log(msg: str) -> None:
    print(msg)


if __name__ == "__main__":
    print("=== Test Google Sheets Sync ===\n")

    writer = make_gsheet_writer(gsheets_cfg, BASE_DIR, log)
    if writer is None:
        print("❌ Không tạo được GSheetWriter — kiểm tra config và credentials.")
    else:
        print(f"\nSync {len(sample_tags)} tagged items...\n")
        writer.sync(sample_messages, sample_tags)
        print("\n✅ Xong! Kiểm tra Google Sheets.")
