"""
Load and expose config.yml as a typed object.
All other modules import cfg from here - never read config.yml directly.

Usage:
    from broadcast_order.config import cfg

    cfg.tpos.base_url
    cfg.tpos.endpoints.token
    cfg.tpos.message_channel_id
    cfg.staff
    cfg.fetch.message_interval_seconds
    cfg.data.monitors_file
    cfg.google_sheets.spreadsheet_id
    cfg.server.http_port
"""

from pathlib import Path
from types import SimpleNamespace

import yaml

_REQUIRED_KEYS = [
    "tpos",
    "staff",
    "fetch",
    "token",
    "data",
    "google_sheets",
    "server",
]

_DEFAULT_CONFIG_PATH = Path(__file__).with_name("config.yml")


def _dict_to_ns(d: dict) -> SimpleNamespace:
    """Recursively convert dict to SimpleNamespace for dot-access."""
    ns = SimpleNamespace()
    for key, value in d.items():
        if isinstance(value, dict):
            setattr(ns, key, _dict_to_ns(value))
        else:
            setattr(ns, key, value)
    return ns


def load_config(path: str | Path | None = None) -> SimpleNamespace:
    """Load YAML, validate required fields, return namespace."""
    config_path = Path(path) if path is not None else _DEFAULT_CONFIG_PATH
    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path.resolve()}")

    with config_path.open(encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    if not isinstance(raw, dict):
        raise ValueError(f"Config file is not a valid YAML mapping: {config_path}")

    missing = [k for k in _REQUIRED_KEYS if k not in raw]
    if missing:
        raise KeyError(f"Config missing required keys: {missing}")

    return _dict_to_ns(raw)


# Module-level singleton - import this everywhere
cfg = load_config()
