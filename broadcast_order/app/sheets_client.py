"""
Google Sheets sync.
Credentials file: cfg.google_sheets.credentials_file
Spreadsheet ID:   cfg.google_sheets.spreadsheet_id

Two sheets:
  1. cfg.google_sheets.monitors_sheet  — full monitor records (upsert by facebook_id)
  2. cfg.google_sheets.messages_sheet  — append-only log of new messages

Requires: pip install google-auth google-auth-httplib2 google-api-python-client

All Sheets failures are logged and swallowed — local JSON is source of truth.
"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from broadcast_order.config_loader import cfg

logger = logging.getLogger(__name__)

# Column order for Monitors sheet (A-N)
_MONITOR_COLS = [
    "facebook_id",
    "reference",
    "partner_name",
    "phone",
    "date_invoice",
    "status",
    "assigned_to",
    "priority",
    "note",
    "needs_reply",
    "unread_duration_mins",
    "last_customer_msg_time",
    "last_message_preview",
    "updated_at",
]

# Column order for Messages sheet (A-G)
_MESSAGE_COLS = [
    "facebook_id",
    "message_id",
    "is_owner",
    "sender_name",
    "message_text",
    "created_time",
    "logged_at",
]


def get_service():
    """Build and return Google Sheets API service using service account credentials."""
    from google.oauth2 import service_account
    from googleapiclient.discovery import build

    creds_path = Path(cfg.google_sheets.credentials_file)
    if not creds_path.exists():
        raise FileNotFoundError(f"Google credentials not found: {creds_path}")

    scopes = ["https://www.googleapis.com/auth/spreadsheets"]
    credentials = service_account.Credentials.from_service_account_file(
        str(creds_path), scopes=scopes
    )
    return build("sheets", "v4", credentials=credentials, cache_discovery=False)


def _get_all_values(service, sheet_name: str) -> list[list]:
    """Fetch all values from a sheet. Returns [] if sheet is empty."""
    try:
        result = (
            service.spreadsheets()
            .values()
            .get(
                spreadsheetId=cfg.google_sheets.spreadsheet_id,
                range=f"{sheet_name}!A:Z",
            )
            .execute()
        )
        return result.get("values", [])
    except Exception as e:
        logger.error("sheets _get_all_values error: %s", e)
        return []


def _ensure_header(service, sheet_name: str, header: list[str]) -> None:
    """Write header row if the sheet is empty."""
    values = _get_all_values(service, sheet_name)
    if not values:
        service.spreadsheets().values().update(
            spreadsheetId=cfg.google_sheets.spreadsheet_id,
            range=f"{sheet_name}!A1",
            valueInputOption="RAW",
            body={"values": [header]},
        ).execute()


def upsert_monitor(record: dict) -> None:
    """
    Write/update one monitor record to monitors_sheet.
    Find row by facebook_id in column A, update in-place. Append if not found.
    """
    try:
        service = get_service()
        sheet = cfg.google_sheets.monitors_sheet
        _ensure_header(service, sheet, _MONITOR_COLS)

        values = _get_all_values(service, sheet)
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        row = [str(record.get(col, "") or "") for col in _MONITOR_COLS[:-1]] + [now]

        # Find existing row by facebook_id (col A)
        target_row = None
        for i, r in enumerate(values):
            if r and r[0] == record.get("facebook_id"):
                target_row = i + 1  # 1-based
                break

        if target_row:
            service.spreadsheets().values().update(
                spreadsheetId=cfg.google_sheets.spreadsheet_id,
                range=f"{sheet}!A{target_row}",
                valueInputOption="RAW",
                body={"values": [row]},
            ).execute()
        else:
            service.spreadsheets().values().append(
                spreadsheetId=cfg.google_sheets.spreadsheet_id,
                range=f"{sheet}!A1",
                valueInputOption="RAW",
                insertDataOption="INSERT_ROWS",
                body={"values": [row]},
            ).execute()
    except Exception as e:
        logger.error("upsert_monitor failed: %s", e)


def append_new_messages(facebook_id: str, new_messages: list[dict]) -> None:
    """
    Append new message rows to messages_sheet.
    Only called when new_messages is non-empty.
    """
    if not new_messages:
        return
    try:
        service = get_service()
        sheet = cfg.google_sheets.messages_sheet
        _ensure_header(service, sheet, _MESSAGE_COLS)

        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        rows = []
        for msg in new_messages:
            app_user = msg.get("ApplicationUser") or {}
            rows.append([
                facebook_id,
                msg.get("Id", ""),
                str(msg.get("IsOwner", False)),
                app_user.get("Name", ""),
                msg.get("Message", ""),
                msg.get("CreatedTime", ""),
                now,
            ])

        service.spreadsheets().values().append(
            spreadsheetId=cfg.google_sheets.spreadsheet_id,
            range=f"{sheet}!A1",
            valueInputOption="RAW",
            insertDataOption="INSERT_ROWS",
            body={"values": rows},
        ).execute()
    except Exception as e:
        logger.error("append_new_messages failed: %s", e)


def sync_all_monitors(monitors: dict) -> None:
    """Batch upsert all monitor records. Called on startup and after refresh."""
    for record in monitors.values():
        upsert_monitor(record)
