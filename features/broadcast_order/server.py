"""
Broadcast Order — Live Feed Server

Khởi động bằng: chọn "broadcast_order" trong menu chính (main.py)

Làm 3 việc:
  1. Fetch API định kỳ (chu kỳ cấu hình trong config.yaml → broadcast_order.fetch_interval)
  2. Serve file HTML tĩnh (display.html, control.html) qua HTTP
  3. WebSocket server để push data xuống browser theo thời gian thực và nhận tag từ control panel
"""

from __future__ import annotations

import asyncio
import json
import threading
import urllib.error
import urllib.request
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Callable

try:
    import websockets
except ImportError:
    raise ImportError("Thiếu thư viện websockets. Chạy: pip install websockets")


# ─── HTTP server tĩnh ────────────────────────────────────────────────────────

_SERVE_DIR: Path | None = None


class _StaticHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass  # tắt access log

    def do_GET(self):
        name = self.path.lstrip("/") or "display.html"
        if not name.endswith(".html") or "/" in name:
            self.send_error(404)
            return
        path = _SERVE_DIR / name
        if not path.exists():
            self.send_error(404, f"Không tìm thấy: {name}")
            return
        body = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)


def _start_http_server(port: int, serve_dir: Path) -> None:
    global _SERVE_DIR
    _SERVE_DIR = serve_dir
    HTTPServer(("0.0.0.0", port), _StaticHandler).serve_forever()


# ─── Broadcast Server ─────────────────────────────────────────────────────────

class BroadcastServer:
    """Quản lý WebSocket clients, fetch API định kỳ và lưu tag đơn hàng."""

    def __init__(self, config: dict, base_dir: Path, log_fn: Callable[[str], None]):
        bc: dict = config.get("broadcast_order") or {}
        self._http_port: int = int(bc.get("http_port", 8080))
        self._ws_port: int = int(bc.get("ws_port", 8765))
        self._fetch_interval: int = int(bc.get("fetch_interval", 60))
        self._api_url: str = str(bc.get("api_url") or "").strip()
        self._api_headers: dict = dict(bc.get("api_headers") or {})

        tags_rel = bc.get("tags_file") or "data/broadcast_tags.json"
        self._tags_file: Path = Path(tags_rel) if Path(tags_rel).is_absolute() else base_dir / tags_rel
        self._token_file: Path = base_dir / str(
            (config.get("auth") or {}).get("token_file", "data/auth_token.json")
        )

        self._log = log_fn
        self._messages: dict | None = None
        self._tags: dict[str, dict] = self._load_tags()
        self._clients: set = set()

    # ── Tag persistence ──────────────────────────────────────────────────────

    def _load_tags(self) -> dict:
        if self._tags_file.exists():
            try:
                return json.loads(self._tags_file.read_text(encoding="utf-8"))
            except Exception:
                return {}
        return {}

    def _save_tags(self) -> None:
        self._tags_file.parent.mkdir(parents=True, exist_ok=True)
        self._tags_file.write_text(
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

    # ── API fetch ────────────────────────────────────────────────────────────

    def _fetch_api(self) -> dict | None:
        if not self._api_url:
            return None
        headers = dict(self._api_headers)
        token = self._load_bearer_token()
        if token and "Authorization" not in headers:
            headers["Authorization"] = f"Bearer {token}"
        try:
            req = urllib.request.Request(self._api_url, headers=headers)
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                count = len(data.get("Data") or [])
                self._log(f"[BROADCAST] Fetch OK — {count} mục")
                return data
        except urllib.error.URLError as exc:
            self._log(f"[BROADCAST] Fetch lỗi: {exc}")
        except Exception as exc:
            self._log(f"[BROADCAST] Lỗi không xác định: {exc}")
        return None

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
        self._log(f"[BROADCAST] Kết nối mới: {addr}  (tổng: {len(self._clients)})")
        try:
            # gửi state hiện tại ngay khi client vừa kết nối
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
                    self._log(f"[BROADCAST] Tag [{status}] ← {item_id}")
                    await self._broadcast(self._make_payload())

                elif action == "untag":
                    removed = self._tags.pop(item_id, None)
                    if removed is not None:
                        self._save_tags()
                        self._log(f"[BROADCAST] Untag ← {item_id}")
                        await self._broadcast(self._make_payload())

        except Exception:
            pass
        finally:
            self._clients.discard(ws)
            self._log(f"[BROADCAST] Ngắt kết nối: {addr}  (còn: {len(self._clients)})")

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
        serve_dir = Path(__file__).resolve().parent

        # HTTP server chạy trên thread riêng (không block event loop)
        threading.Thread(
            target=_start_http_server,
            args=(self._http_port, serve_dir),
            daemon=True,
        ).start()

        self._log(f"[BROADCAST] Display  → http://localhost:{self._http_port}/display.html")
        self._log(f"[BROADCAST] Control  → http://localhost:{self._http_port}/control.html")

        # fetch lần đầu ngay lập tức trước khi vào loop
        loop = asyncio.get_event_loop()
        data = await loop.run_in_executor(None, self._fetch_api)
        if data is not None:
            self._messages = {**data, "fetched_at": datetime.now().isoformat()}
        elif not self._api_url:
            self._log("[BROADCAST] api_url chưa cấu hình — chỉ phục vụ tag từ control panel")

        asyncio.create_task(self._fetch_loop())

        async with websockets.serve(self._handle_client, "0.0.0.0", self._ws_port):
            self._log(f"[BROADCAST] WebSocket → ws://localhost:{self._ws_port}")
            self._log("[BROADCAST] Nhấn Ctrl+C để dừng server")
            await asyncio.Future()  # giữ server chạy mãi


# ─── Public entry point ───────────────────────────────────────────────────────

def run_broadcast_server(config: dict, base_dir: Path, log_fn: Callable[[str], None]) -> None:
    """Khởi động broadcast server. Blocking — chạy đến khi Ctrl+C."""
    server = BroadcastServer(config, base_dir, log_fn)
    try:
        asyncio.run(server.run())
    except KeyboardInterrupt:
        log_fn("[BROADCAST] Server đã dừng.")
