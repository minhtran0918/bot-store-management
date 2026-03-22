"""
TPOS token manager.
Reads config via cfg. Caches token to cfg.token.file.
Public interface: get_token() -> str
"""

import json
import requests
from datetime import datetime, timezone
from pathlib import Path
from email.utils import parsedate_to_datetime

from broadcast_order.config_loader import cfg


def get_token() -> str:
    """Return valid Bearer access_token. Auto-refresh when near expiry."""
    cached = _load_cached()
    if cached and not _is_expired(cached):
        return cached["access_token"]
    token_data = _fetch_new_token()
    _save_token(token_data)
    return token_data["access_token"]


def _load_cached() -> dict | None:
    """Load token from cfg.token.file. Return None if missing or unreadable."""
    path = Path(cfg.token.file)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _is_expired(token_data: dict) -> bool:
    """Return True if expires_at - now < cfg.token.refresh_buffer_seconds."""
    try:
        expires_at = datetime.fromisoformat(token_data["expires_at"].replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)
        remaining = (expires_at - now).total_seconds()
        return remaining < cfg.token.refresh_buffer_seconds
    except Exception:
        return True


def _fetch_new_token() -> dict:
    """
    POST to cfg.tpos.base_url + cfg.tpos.endpoints.token.
    Build body from cfg.tpos fields (client_id, grant_type, username, password, scope).
    Parse .expires RFC string -> ISO8601 expires_at.
    Save to cfg.token.file. Return normalized dict.
    """
    url = cfg.tpos.base_url + cfg.tpos.endpoints.token
    body = {
        "client_id": cfg.tpos.client_id,
        "grant_type": cfg.tpos.grant_type,
        "username": cfg.tpos.username,
        "password": cfg.tpos.password,
        "scope": cfg.tpos.scope,
    }
    resp = requests.post(url, data=body, timeout=30)
    resp.raise_for_status()
    raw = resp.json()

    # Parse RFC 2822 date from .expires field → ISO8601
    expires_dt = parsedate_to_datetime(raw[".expires"])
    expires_at = expires_dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    return {
        "access_token": raw["access_token"],
        "refresh_token": raw.get("refresh_token", ""),
        "expires_at": expires_at,
    }


def _save_token(token_data: dict) -> None:
    """Write normalized token_data to cfg.token.file."""
    path = Path(cfg.token.file)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(token_data, indent=2), encoding="utf-8")
