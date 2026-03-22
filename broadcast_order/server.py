"""
Broadcast Order — Live Feed Server

Start via: select "broadcast_order" in the main menu (main.py)

Does 3 things:
  1. Periodically fetches API data (interval configured in broadcast_order/config/config.yaml)
  2. Serves static HTML files (display.html, control.html) over HTTP
  3. WebSocket server to push live data to browsers and receive tag actions from control panel
"""

from __future__ import annotations

import asyncio
import json
import threading
import urllib.error
import urllib.request
import webbrowser
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Callable

try:
    import websockets
except ImportError:
    raise ImportError("Missing dependency: websockets. Run: pip install websockets")

try:
    import yaml
except ImportError:
    raise ImportError("Missing dependency: PyYAML. Run: pip install pyyaml")

from broadcast_order.gsheets import make_gsheet_writer

# Directory containing this file (broadcast_order/)
_MODULE_DIR = Path(__file__).resolve().parent
_CONFIG_FILE = _MODULE_DIR / "config" / "config.yaml"


def _load_broadcast_config() -> dict:
    with open(_CONFIG_FILE, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


# ─── Static HTTP server ───────────────────────────────────────────────────────

_SERVE_DIR: Path | None = None
_WS_PORT: int = 8765


class _StaticHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass  # suppress access log

    def do_GET(self):
        name = self.path.lstrip("/") or "display.html"
        if not name.endswith(".html") or "/" in name:
            self.send_error(404)
            return
        path = _SERVE_DIR / name
        if not path.exists():
            self.send_error(404, f"Not found: {name}")
            return
        body = path.read_text(encoding="utf-8").replace("%%WS_PORT%%", str(_WS_PORT)).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)


def _start_http_server(port: int, serve_dir: Path, ws_port: int) -> None:
    global _SERVE_DIR, _WS_PORT
    _SERVE_DIR = serve_dir
    _WS_PORT = ws_port
    HTTPServer(("0.0.0.0", port), _StaticHandler).serve_forever()


# ─── Broadcast Server ─────────────────────────────────────────────────────────

class BroadcastServer:
    """Manages WebSocket clients, periodic API fetching, and order tag persistence."""

    def __init__(self, base_dir: Path, log_fn: Callable[[str], None]):
        bc = _load_broadcast_config()
        self._http_port: int = int(bc["http_port"])
        self._ws_port: int = int(bc["ws_port"])
        self._fetch_interval: int = int(bc.get("fetch_interval", 60))
        self._api_url: str = str(bc.get("api_url") or "").strip()
        self._api_headers: dict = dict(bc.get("api_headers") or {})

        self._tags_dir: Path = base_dir / "data" / "broadcast"
        self._token_file: Path = base_dir / "data" / "auth_token.json"

        self._log = log_fn
        self._messages: dict | None = None
        self._clients: set = set()
        self._tags: dict[str, dict] = self._load_tags()

        gsheets_cfg: dict = bc.get("gsheets") or {}
        self._gsheets = make_gsheet_writer(gsheets_cfg, base_dir, log_fn)

    # ── Tag persistence ──────────────────────────────────────────────────────

    @property
    def _tags_file(self) -> Path:
        return self._tags_dir / "tags.json"

    def _load_tags(self) -> dict:
        path = self._tags_file
        if path.exists():
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                return {}
        return {}

    def _save_tags(self) -> None:
        path = self._tags_file
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(self._tags, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    # ── Auth token ───────────────────────────────────────────────────────────

    def _load_bearer_token(self) -> str | None:
        if not self._token_file.exists():
            return None
        try:
            data = json.loads(self._token_file.read_text(encoding="utf-8"))
            return data.get("access_token") or None
        except Exception:
            return None

    # ── Sample data (shown when api_url is not configured) ───────────────────

    @staticmethod
    def _sample_data() -> dict:
        from datetime import timezone
        now = datetime.now(timezone.utc)

        def ts(offset_minutes: int = 0) -> str:
            from datetime import timedelta
            return (now - timedelta(minutes=offset_minutes)).strftime("%Y-%m-%dT%H:%M:%S.000Z")

        return {
            "is_sample": True,
            "Data": [
                {
                    "Id": "sample-001",
                    "Type": "comment",
                    "IsOwner": False,
                    "Message": "1 bộ size M",
                    "CreatedTime": ts(55),
                    "Order": {"Count": 1, "Data": [{"Code": "ORD20240001"}]},
                    "Attachments": [],
                    "Object": {
                        "Description": "Set áo váy hè 2024",
                        "LiveCampaign": {"Name": "LIVE 21/3/2026"},
                    },
                },
                {
                    "Id": "sample-002",
                    "Type": "message",
                    "IsOwner": True,
                    "ApplicationUser": {"Name": "Linh Đan"},
                    "Message": "Dạ chị Hoa ! Số lượng đơn chốt đủ bộ\nChị \"GỬI ĐỊA CHỈ\" shop đi đơn ạ !",
                    "CreatedTime": ts(50),
                    "Order": {"Count": 1, "Data": [{"Code": "ORD20240001"}]},
                    "Attachments": [],
                },
                {
                    "Id": "sample-003",
                    "Type": "message",
                    "IsOwner": False,
                    "Message": "Shop ơi cho mình hỏi còn hàng không ạ?",
                    "CreatedTime": ts(30),
                    "Order": {"Count": 0, "Data": []},
                    "Attachments": [],
                },
                {
                    "Id": "sample-004",
                    "Type": "comment",
                    "IsOwner": False,
                    "Message": "2 bộ **********",
                    "CreatedTime": ts(20),
                    "Order": {"Count": 1, "Data": [{"Code": "ORD20240002"}]},
                    "Attachments": [],
                    "Object": {
                        "Description": "Đầm maxi boho",
                        "LiveCampaign": {"Name": "LIVE 21/3/2026"},
                    },
                },
                {
                    "Id": "sample-005",
                    "Type": "message",
                    "IsOwner": False,
                    "Message": "Chị địa chỉ: 123 Nguyễn Văn A, Quận 1, HCM",
                    "CreatedTime": ts(10),
                    "Order": {"Count": 2, "Data": [{"Code": "ORD20240001"}, {"Code": "ORD20240003"}]},
                    "Attachments": [],
                    "Error": False,
                },
                {
                    "Id": "sample-006",
                    "Type": "message",
                    "IsOwner": True,
                    "ApplicationUser": {"Name": "Linh Đan"},
                    "Message": "Dạ chị Lan !\n1/ Đơn 4 bộ cọc 100, 8 bộ cọc 200,..\nNGUYEN THI NGOC NHUNG\nACB\n19337611",
                    "CreatedTime": ts(5),
                    "Order": {"Count": 1, "Data": [{"Code": "ORD20240003"}]},
                    "Attachments": [],
                },
            ],
        }

    # ── API fetch ────────────────────────────────────────────────────────────

    def _fetch_api(self) -> dict | None:
        if not self._api_url:
            self._log("[BROADCAST] api_url not configured — showing sample data")
            return self._sample_data()
        headers = dict(self._api_headers)
        token = self._load_bearer_token()
        if token and "Authorization" not in headers:
            headers["Authorization"] = f"Bearer {token}"
        try:
            req = urllib.request.Request(self._api_url, headers=headers)
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                count = len(data.get("Data") or [])
                self._log(f"[BROADCAST] Fetch OK — {count} item(s)")
                return data
        except urllib.error.URLError as exc:
            self._log(f"[BROADCAST] Fetch error: {exc}")
        except Exception as exc:
            self._log(f"[BROADCAST] Unexpected error: {exc}")
        return None

    # ── Google Sheets sync ───────────────────────────────────────────────────

    def _gsheets_sync(self) -> None:
        """Sync tagged items to Google Sheets (runs in executor to avoid blocking)."""
        if self._gsheets is None:
            return
        try:
            self._gsheets.sync(self._messages, self._tags)
        except Exception as exc:
            self._log(f"[GSHEETS] Sync error: {exc}")

    # ── Broadcast ────────────────────────────────────────────────────────────

    def _make_payload(self) -> str:
        return json.dumps(
            {"event": "update", "data": {"messages": self._messages, "tags": self._tags}},
            ensure_ascii=False,
        )

    async def _broadcast(self, payload: str) -> None:
        dead: set = set()
        for ws in list(self._clients):
            try:
                await ws.send(payload)
            except Exception:
                dead.add(ws)
        self._clients -= dead

    # ── WebSocket handler ────────────────────────────────────────────────────

    async def _handle_client(self, ws) -> None:
        self._clients.add(ws)
        addr = ws.remote_address
        self._log(f"[BROADCAST] Client connected: {addr}  (total: {len(self._clients)})")
        try:
            # send current state immediately on connect
            await ws.send(self._make_payload())

            async for raw in ws:
                try:
                    msg = json.loads(raw)
                except Exception:
                    continue

                action = msg.get("action")
                item_id = msg.get("id")
                if not item_id:
                    continue

                if action == "tag":
                    status = str(msg.get("status") or "ok")
                    note = str(msg.get("note") or "")
                    self._tags[item_id] = {
                        "status": status,
                        "note": note,
                        "tagged_at": datetime.now().isoformat(),
                    }
                    self._save_tags()
                    self._log(f"[BROADCAST] Tag [{status}] <- {item_id}")
                    await self._broadcast(self._make_payload())
                    loop = asyncio.get_event_loop()
                    loop.run_in_executor(None, self._gsheets_sync)

                elif action == "untag":
                    removed = self._tags.pop(item_id, None)
                    if removed is not None:
                        self._save_tags()
                        self._log(f"[BROADCAST] Untag <- {item_id}")
                        await self._broadcast(self._make_payload())
                        loop = asyncio.get_event_loop()
                        loop.run_in_executor(None, self._gsheets_sync)

        except Exception:
            pass
        finally:
            self._clients.discard(ws)
            self._log(f"[BROADCAST] Client disconnected: {addr}  (remaining: {len(self._clients)})")

    # ── Fetch loop ───────────────────────────────────────────────────────────

    async def _fetch_loop(self) -> None:
        while True:
            loop = asyncio.get_event_loop()
            data = await loop.run_in_executor(None, self._fetch_api)
            if data is not None:
                self._messages = {**data, "fetched_at": datetime.now().isoformat()}
                await self._broadcast(self._make_payload())
            await asyncio.sleep(self._fetch_interval)

    # ── Entry point ──────────────────────────────────────────────────────────

    async def run(self) -> None:
        serve_dir = _MODULE_DIR

        # HTTP server runs on a separate thread (doesn't block the event loop)
        threading.Thread(
            target=_start_http_server,
            args=(self._http_port, serve_dir, self._ws_port),
            daemon=True,
        ).start()

        self._log(f"[BROADCAST] Display  -> http://localhost:{self._http_port}/display.html")
        self._log(f"[BROADCAST] Control  -> http://localhost:{self._http_port}/control.html")

        # Open both tabs in the default browser after a short delay
        # (give HTTP server thread time to bind the port)
        def _open_browser() -> None:
            import time
            time.sleep(0.8)
            webbrowser.open(f"http://localhost:{self._http_port}/display.html")
            webbrowser.open(f"http://localhost:{self._http_port}/control.html")

        threading.Thread(target=_open_browser, daemon=True).start()

        # Initial fetch before entering the loop
        loop = asyncio.get_event_loop()
        data = await loop.run_in_executor(None, self._fetch_api)
        if data is not None:
            self._messages = {**data, "fetched_at": datetime.now().isoformat()}

        asyncio.create_task(self._fetch_loop())

        async with websockets.serve(self._handle_client, "0.0.0.0", self._ws_port):
            self._log(f"[BROADCAST] WebSocket -> ws://localhost:{self._ws_port}")
            self._log("[BROADCAST] Press Ctrl+C to stop the server")
            await asyncio.Future()  # run forever


# ─── Public entry point ───────────────────────────────────────────────────────

def run_broadcast_server(base_dir: Path, log_fn: Callable[[str], None]) -> None:
    """Start the broadcast server. Blocking — runs until Ctrl+C."""
    server = BroadcastServer(base_dir, log_fn)
    try:
        asyncio.run(server.run())
    except KeyboardInterrupt:
        log_fn("[BROADCAST] Server stopped.")
