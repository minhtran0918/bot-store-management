"""
All TPOS API calls.
Each function auto-calls auth.get_token() for Bearer header.
All requests/responses logged to cfg.data.log_file via _log().
No hardcoded URLs or values — all from cfg.
"""

import json
import re
import requests
from datetime import datetime, timezone
from pathlib import Path

from broadcast_order.config_loader import cfg
from broadcast_order.app.auth import get_token


def _log(method: str, url: str, params: dict, response_status: int, response_body: str) -> None:
    """Append one JSON line to cfg.data.log_file."""
    log_path = Path(cfg.data.log_file)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "method": method,
        "url": url,
        "params": params,
        "status": response_status,
        "body_preview": response_body[:500],
    }
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def _headers() -> dict:
    return {"Authorization": f"Bearer {get_token()}"}


def get_user_info() -> dict:
    """GET {base_url}{endpoints.user_info}. Log request/response."""
    url = cfg.tpos.base_url + cfg.tpos.endpoints.user_info
    resp = requests.get(url, headers=_headers(), timeout=30)
    _log("GET", url, {}, resp.status_code, resp.text)
    resp.raise_for_status()
    return resp.json()


def get_order_bills(date_from: str, date_to: str, skip: int = 0, search: str = "") -> dict:
    """
    GET {base_url}{endpoints.order_bills} with OData params from cfg.
    If search provided, append contains() filter for PartnerDisplayName, Phone, Reference.
    Returns: { "@odata.count": int, "value": [order, ...] }
    """
    url = cfg.tpos.base_url + cfg.tpos.endpoints.order_bills

    base_filter = (
        f"(Type eq '{cfg.tpos.order_filter_type}'"
        f" and (DateInvoice ge {date_from} and DateInvoice le {date_to})"
        f" and IsMergeCancel ne true)"
    )
    if search:
        s = search.replace("'", "''")
        search_filter = (
            f"(contains(PartnerDisplayName,'{s}')"
            f" or contains(Phone,'{s}')"
            f" or contains(Reference,'{s}'))"
        )
        full_filter = f"{base_filter} and {search_filter}"
    else:
        full_filter = base_filter

    params = {
        "$top": cfg.tpos.order_top,
        "$skip": skip,
        "$filter": full_filter,
        "$orderby": cfg.tpos.order_orderby,
        "$count": "true",
    }
    resp = requests.get(url, headers=_headers(), params=params, timeout=30)
    _log("GET", url, params, resp.status_code, resp.text)
    resp.raise_for_status()
    return resp.json()


def get_messages(user_id: str) -> dict:
    """
    GET {base_url}{endpoints.messages}
    Params: type={cfg.tpos.message_type}, channelId={cfg.tpos.message_channel_id}, userId={user_id}
    channel_id is always from config — never passed as argument.
    Returns raw response dict.
    """
    url = cfg.tpos.base_url + cfg.tpos.endpoints.messages
    params = {
        "type": cfg.tpos.message_type,
        "channelId": cfg.tpos.message_channel_id,
        "userId": user_id,
    }
    resp = requests.get(url, headers=_headers(), params=params, timeout=30)
    _log("GET", url, params, resp.status_code, resp.text)
    resp.raise_for_status()
    return resp.json()


def clean_partner_name(name: str) -> str:
    """Strip [KHxxxxx] prefix: re.sub(r'^\\[KH\\d+\\]\\s*', '', name)."""
    return re.sub(r"^\[KH\d+\]\s*", "", name or "")


def compute_message_stats(messages: list[dict]) -> dict:
    """
    Input: list of message dicts already filtered to Type == "message".
    Returns:
    {
      "last_customer_msg_time": str | None,
      "last_shop_msg_time":     str | None,
      "last_message_preview":   str,
      "unread_duration_mins":   float,
      "needs_reply":            bool,
      "messages_fetched_at":    str
    }
    """
    now = datetime.now(timezone.utc)
    fetched_at = now.strftime("%Y-%m-%dT%H:%M:%SZ")

    customer_msgs = [m for m in messages if not m.get("IsOwner")]
    shop_msgs = [m for m in messages if m.get("IsOwner")]

    def parse_time(m: dict) -> datetime | None:
        raw = m.get("CreatedTime")
        if not raw:
            return None
        try:
            return datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except Exception:
            return None

    last_customer_time = None
    last_customer_msg_time = None
    if customer_msgs:
        times = [(parse_time(m), m) for m in customer_msgs]
        times = [(t, m) for t, m in times if t]
        if times:
            times.sort(key=lambda x: x[0], reverse=True)
            last_customer_time, _ = times[0]
            last_customer_msg_time = last_customer_time.strftime("%Y-%m-%dT%H:%M:%SZ")

    last_shop_time = None
    last_shop_msg_time = None
    if shop_msgs:
        times = [(parse_time(m), m) for m in shop_msgs]
        times = [(t, m) for t, m in times if t]
        if times:
            times.sort(key=lambda x: x[0], reverse=True)
            last_shop_time, _ = times[0]
            last_shop_msg_time = last_shop_time.strftime("%Y-%m-%dT%H:%M:%SZ")

    needs_reply = False
    if last_customer_time:
        if last_shop_time is None or last_customer_time > last_shop_time:
            needs_reply = True

    unread_duration_mins = 0.0
    if needs_reply and last_customer_time:
        unread_duration_mins = (now - last_customer_time).total_seconds() / 60

    # Latest message preview (newest first regardless of owner)
    all_with_times = [(parse_time(m), m) for m in messages if parse_time(m)]
    last_message_preview = ""
    if all_with_times:
        all_with_times.sort(key=lambda x: x[0], reverse=True)
        latest_msg = all_with_times[0][1].get("Message") or ""
        last_message_preview = latest_msg[:80]

    return {
        "last_customer_msg_time": last_customer_msg_time,
        "last_shop_msg_time": last_shop_msg_time,
        "last_message_preview": last_message_preview,
        "unread_duration_mins": round(unread_duration_mins, 1),
        "needs_reply": needs_reply,
        "messages_fetched_at": fetched_at,
    }
