"""
CRUD for data/monitors.json.
Thread-safe via threading.Lock.

Monitor record schema (keyed by facebook_id):
{
  "facebook_id":    str,
  "channel_id":     str,
  "reference":      str,
  "partner_name":   str,
  "phone":          str,
  "date_invoice":   str,
  "amount_total":   float,
  "order_state":    str,
  "added_at":       str,

  "status":         "pending" | "processing" | "done",
  "assigned_to":    str | null,
  "priority":       "normal" | "high" | "low",
  "note":           str,

  "last_customer_msg_time": str | null,
  "last_shop_msg_time":     str | null,
  "last_message_preview":   str | null,
  "unread_duration_mins":   float | null,
  "needs_reply":            bool,
  "messages_fetched_at":    str | null
}
"""

import json
import threading
from datetime import datetime, timezone
from pathlib import Path

from broadcast_order.config_loader import cfg
from broadcast_order.app.api_client import clean_partner_name

_lock = threading.Lock()


def _monitors_path() -> Path:
    return Path(cfg.data.monitors_file)


def load_monitors() -> dict:
    path = _monitors_path()
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def save_monitors(data: dict) -> None:
    path = _monitors_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def add_monitor(order: dict) -> dict | None:
    """
    Build record from order bill API response dict.
    Return None if order["FacebookId"] is None or empty.
    Do not overwrite if facebook_id already exists.
    """
    facebook_id = order.get("FacebookId")
    if not facebook_id:
        return None

    with _lock:
        data = load_monitors()
        if facebook_id in data:
            return data[facebook_id]

        record = {
            "facebook_id": facebook_id,
            "channel_id": cfg.tpos.message_channel_id,
            "reference": order.get("Reference", ""),
            "partner_name": clean_partner_name(order.get("PartnerDisplayName", "")),
            "phone": order.get("Phone", ""),
            "date_invoice": order.get("DateInvoice", ""),
            "amount_total": order.get("AmountTotal", 0.0),
            "order_state": order.get("State", ""),
            "added_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),

            "status": "pending",
            "assigned_to": None,
            "priority": "normal",
            "note": "",

            "last_customer_msg_time": None,
            "last_shop_msg_time": None,
            "last_message_preview": None,
            "unread_duration_mins": None,
            "needs_reply": False,
            "messages_fetched_at": None,
        }
        data[facebook_id] = record
        save_monitors(data)
        return record


def remove_monitor(facebook_id: str) -> bool:
    with _lock:
        data = load_monitors()
        if facebook_id not in data:
            return False
        del data[facebook_id]
        save_monitors(data)
        return True


def update_monitor(facebook_id: str, patch: dict) -> dict | None:
    with _lock:
        data = load_monitors()
        if facebook_id not in data:
            return None
        data[facebook_id].update(patch)
        save_monitors(data)
        return data[facebook_id]


def get_monitor(facebook_id: str) -> dict | None:
    data = load_monitors()
    return data.get(facebook_id)


def get_all_monitors() -> dict:
    return dict(load_monitors())
