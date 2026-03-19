from __future__ import annotations

from pathlib import Path


def _parse_scalar(value: str):
    value = value.strip()
    if not value:
        return ""
    if value.startswith('"') and value.endswith('"'):
        return value[1:-1]
    if value.startswith("'") and value.endswith("'"):
        return value[1:-1]
    if value.lower() == "true":
        return True
    if value.lower() == "false":
        return False
    return value


def _safe_load_yaml(text: str) -> dict:
    try:
        import yaml  # type: ignore

        loaded = yaml.safe_load(text) or {}
        return loaded if isinstance(loaded, dict) else {}
    except Exception:
        # Fallback parser for the project's simple YAML shape.
        root: dict = {}
        stack: list[tuple[int, dict | list]] = [(-1, root)]

        for raw_line in text.splitlines():
            if not raw_line.strip() or raw_line.lstrip().startswith("#"):
                continue

            indent = len(raw_line) - len(raw_line.lstrip(" "))
            line = raw_line.strip()

            while len(stack) > 1 and indent <= stack[-1][0]:
                stack.pop()

            parent = stack[-1][1]
            if line.startswith("- ") and isinstance(parent, list):
                parent.append(_parse_scalar(line[2:]))
                continue

            if ":" not in line or not isinstance(parent, dict):
                continue

            key, raw_value = line.split(":", 1)
            key = key.strip()
            raw_value = raw_value.strip()

            if raw_value:
                parent[key] = _parse_scalar(raw_value)
                continue

            # Decide whether next nested block is list or dict by peeking one line.
            container: dict | list = {}
            parent[key] = container
            stack.append((indent, container))

            # Convert empty nested map into list when first child uses "- ".
            # This keeps parser compact for current config structure.
            for next_raw in text.splitlines()[text.splitlines().index(raw_line) + 1:]:
                if not next_raw.strip() or next_raw.lstrip().startswith("#"):
                    continue
                next_indent = len(next_raw) - len(next_raw.lstrip(" "))
                next_line = next_raw.strip()
                if next_indent <= indent:
                    break
                if next_line.startswith("- "):
                    container = []
                    parent[key] = container
                    stack[-1] = (indent, container)
                break

        return root


def _to_bool(value, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return bool(value)


def load_config(path: Path | str = "config.yaml") -> dict:
    config_path = Path(path)
    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")

    raw = _safe_load_yaml(config_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("config.yaml must contain a top-level mapping")

    base_url = str(raw.get("base_url", "")).strip()
    if not base_url:
        raise ValueError("config.yaml requires non-empty 'base_url'")

    messages = raw.get("messages") if isinstance(raw.get("messages"), dict) else {}
    keywords = raw.get("keywords") if isinstance(raw.get("keywords"), dict) else {}
    credentials = raw.get("credentials") if isinstance(raw.get("credentials"), dict) else {}
    auth = raw.get("auth") if isinstance(raw.get("auth"), dict) else {}
    debug = raw.get("debug") if isinstance(raw.get("debug"), dict) else {}
    bot = raw.get("bot") if isinstance(raw.get("bot"), dict) else {}
    features = raw.get("features") if isinstance(raw.get("features"), dict) else {}
    timeouts = raw.get("timeouts") if isinstance(raw.get("timeouts"), dict) else {}

    pickup = keywords.get("pickup", [])
    if not isinstance(pickup, list):
        pickup = []

    try:
        keep_open_seconds = int(debug.get("keep_open_seconds", 120))
    except Exception:
        keep_open_seconds = 120
    keep_open_seconds = max(0, keep_open_seconds)

    # Collect all message template lists (passed through as-is for BotConfig)
    messages_out: dict = {
        "ask_address": str(messages.get("ask_address", "")).strip(),
    }
    for tpl_key in ("ask_address_templates", "comment_fallback_templates"):
        val = messages.get(tpl_key)
        if isinstance(val, list):
            messages_out[tpl_key] = [str(s) for s in val]
    for tpl_key in ("deposit_template",):
        val = messages.get(tpl_key)
        if isinstance(val, str):
            messages_out[tpl_key] = val

    config = {
        "site": str(raw.get("site", "")).strip(),
        "base_url": base_url,
        "headless": _to_bool(raw.get("headless"), False),
        "messages": messages_out,
        "bot": bot,
        "features": features,
        "timeouts": timeouts,
        "keywords": {
            "pickup": [str(item) for item in pickup],
        },
        "credentials": {
            "username": str(credentials.get("username", "")).strip(),
            "password": str(credentials.get("password", "")).strip(),
        },
        "auth": {
            "login_url": str(auth.get("login_url", "")).strip() or f"{base_url.rstrip('/')}/#/account/login",
            "dashboard_url": str(auth.get("dashboard_url", "")).strip() or f"{base_url.rstrip('/')}/#/dashboard",
            "order_url": str(auth.get("order_url", "")).strip() or f"{base_url.rstrip('/')}/#/order",
            "indexeddb_token_key": str(auth.get("indexeddb_token_key", "")).strip() or "TpageBearerToken",
            "token_file": str(auth.get("token_file", "")).strip() or "data/auth_token.json",
            "capture_enabled": _to_bool(auth.get("capture_enabled"), True),
            "bootstrap_from_token": _to_bool(auth.get("bootstrap_from_token"), True),
        },
        "debug": {
            "keep_open": _to_bool(debug.get("keep_open"), True),
            "keep_open_seconds": keep_open_seconds,
        },
    }

    return config

