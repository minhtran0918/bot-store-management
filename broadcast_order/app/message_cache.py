"""
Per-user message cache stored in cfg.data.messages_dir/{facebook_id}.json.
Keyed by message Id to avoid re-fetching and detect new messages.

Cache file schema:
{
  "facebook_id": "26333230062956263",
  "updated_at": "2026-03-22T10:00:00Z",
  "messages": {
    "69bfc40d0f45bfbb7dc4e41a": {
      "Id": "69bfc40d0f45bfbb7dc4e41a",
      "Type": "message",
      "Message": "...",
      "IsOwner": true,
      "CreatedTime": "2026-03-22T10:27:26.351Z",
      "ApplicationUser": { "Name": "..." }
    }
  }
}
"""

import json
from datetime import datetime, timezone
from pathlib import Path

from broadcast_order.config_loader import cfg


def _cache_path(facebook_id: str) -> Path:
    return Path(cfg.data.messages_dir) / f"{facebook_id}.json"


def load_cache(facebook_id: str) -> dict:
    """Load messages/{facebook_id}.json. Return empty structure if not found."""
    path = _cache_path(facebook_id)
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"facebook_id": facebook_id, "updated_at": None, "messages": {}}


def save_cache(facebook_id: str, cache: dict) -> None:
    """Write to messages/{facebook_id}.json."""
    path = _cache_path(facebook_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")


def merge_messages(facebook_id: str, raw_api_messages: list[dict]) -> tuple[dict, list[dict]]:
    """
    Merge new API messages into existing cache.
    Only store Type == "message" items.
    Key by message["Id"].

    Returns:
      - updated_cache: full cache dict after merge
      - new_messages:  list of message dicts that were NOT previously in cache
    """
    cache = load_cache(facebook_id)
    existing_ids = set(cache["messages"].keys())
    new_messages = []

    for msg in raw_api_messages:
        if msg.get("Type") != "message":
            continue
        msg_id = msg.get("Id")
        if not msg_id:
            continue
        if msg_id not in existing_ids:
            new_messages.append(msg)
        # Always update (message content may change)
        cache["messages"][msg_id] = {
            "Id": msg_id,
            "Type": msg.get("Type"),
            "Message": msg.get("Message", ""),
            "IsOwner": msg.get("IsOwner", False),
            "CreatedTime": msg.get("CreatedTime"),
            "ApplicationUser": msg.get("ApplicationUser"),
        }

    cache["facebook_id"] = facebook_id
    cache["updated_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    save_cache(facebook_id, cache)
    return cache, new_messages


def get_messages_list(facebook_id: str, limit: int | None = None) -> list[dict]:
    """
    Return messages as list sorted by CreatedTime descending.
    If limit provided, return only first N items.
    """
    cache = load_cache(facebook_id)
    messages = list(cache["messages"].values())

    def sort_key(m: dict):
        t = m.get("CreatedTime") or ""
        return t

    messages.sort(key=sort_key, reverse=True)
    if limit is not None:
        messages = messages[:limit]
    return messages
