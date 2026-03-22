"""
Entry point for the dashboard.
Starts: HTTP server (thread) + WebSocket server (asyncio) + cronjob (asyncio task).
All config from cfg.

Run:
    python -m broadcast_order.dashboard.server
"""

import asyncio
import json
import logging
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import websockets

from broadcast_order.config import cfg
from broadcast_order.app.api_client import get_user_info, get_order_bills, get_messages, compute_message_stats
from broadcast_order.app.message_cache import merge_messages, get_messages_list
from broadcast_order.app.monitor_store import (
    add_monitor, remove_monitor, update_monitor, get_all_monitors
)
from broadcast_order.app.sheets_client import upsert_monitor, append_new_messages, sync_all_monitors

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

_DASHBOARD_DIR = Path(__file__).parent

# Module-level state
last_user_info: dict = {}
ws_clients: set = set()


# ---------------------------------------------------------------------------
# HTTP server
# ---------------------------------------------------------------------------

class _StaticHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass  # Suppress default access logs

    def do_GET(self):
        path = self.path.split("?")[0].rstrip("/")
        if path in ("", "/display"):
            self._serve_file("display.html")
        elif path == "/control":
            self._serve_file("control.html")
        else:
            self.send_response(404)
            self.end_headers()

    def _serve_file(self, filename: str):
        file_path = _DASHBOARD_DIR / filename
        if not file_path.exists():
            self.send_response(404)
            self.end_headers()
            return
        content = file_path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)


def _start_http_server():
    port = cfg.server.http_port
    server = HTTPServer(("0.0.0.0", port), _StaticHandler)
    logger.info("HTTP server: http://localhost:%d/display", port)
    server.serve_forever()


# ---------------------------------------------------------------------------
# WebSocket helpers
# ---------------------------------------------------------------------------

def build_payload() -> dict:
    """Build full state payload for broadcast."""
    monitors = get_all_monitors()
    messages = {
        fid: get_messages_list(fid)
        for fid in monitors
    }
    return {
        "monitors": monitors,
        "staff": cfg.staff,
        "user_info": last_user_info,
        "messages": messages,
    }


async def _broadcast(event: str, data: dict):
    if not ws_clients:
        return
    payload = json.dumps({"event": event, "data": data}, ensure_ascii=False)
    await asyncio.gather(
        *[client.send(payload) for client in ws_clients],
        return_exceptions=True,
    )


# ---------------------------------------------------------------------------
# Cronjob
# ---------------------------------------------------------------------------

async def cronjob_loop():
    """Every cfg.fetch.message_interval_seconds: refresh messages for all monitors."""
    while True:
        await asyncio.sleep(cfg.fetch.message_interval_seconds)
        logger.info("Cronjob: refreshing messages for %d monitors", len(get_all_monitors()))
        await _run_refresh()


async def _run_refresh():
    monitors = get_all_monitors()
    for facebook_id in list(monitors.keys()):
        try:
            raw = await asyncio.get_event_loop().run_in_executor(
                None, get_messages, facebook_id
            )
            raw_list = raw.get("Data") or []
            _, new_messages = merge_messages(facebook_id, raw_list)

            if new_messages:
                append_new_messages(facebook_id, new_messages)

            msg_list = [m for m in raw_list if m.get("Type") == "message"]
            stats = compute_message_stats(msg_list)
            update_monitor(facebook_id, stats)

            record = get_all_monitors().get(facebook_id)
            if record:
                upsert_monitor(record)

            await asyncio.sleep(cfg.fetch.delay_between_users_seconds)
        except Exception as e:
            logger.error("Cronjob error for %s: %s", facebook_id, e)

    await _broadcast("update", build_payload())


# ---------------------------------------------------------------------------
# WebSocket handler
# ---------------------------------------------------------------------------

async def ws_handler(websocket):
    ws_clients.add(websocket)
    logger.info("WS client connected (%d total)", len(ws_clients))
    try:
        # Send current state on connect
        await websocket.send(json.dumps(
            {"event": "update", "data": build_payload()}, ensure_ascii=False
        ))

        async for raw_msg in websocket:
            try:
                msg = json.loads(raw_msg)
            except Exception:
                continue
            await _handle_action(websocket, msg)

    except websockets.exceptions.ConnectionClosed:
        pass
    finally:
        ws_clients.discard(websocket)
        logger.info("WS client disconnected (%d total)", len(ws_clients))


async def _handle_action(websocket, msg: dict):
    action = msg.get("action")

    if action == "search_orders":
        await _action_search_orders(websocket, msg)

    elif action == "add_monitor":
        order = {
            "FacebookId": msg.get("facebook_id"),
            "Reference": msg.get("reference", ""),
            "PartnerDisplayName": msg.get("partner_name", ""),
            "Phone": msg.get("phone", ""),
            "DateInvoice": msg.get("date_invoice", ""),
            "AmountTotal": msg.get("amount_total", 0),
            "State": msg.get("order_state", ""),
        }
        record = add_monitor(order)
        if record:
            upsert_monitor(record)
            await _broadcast("update", build_payload())
        else:
            await websocket.send(json.dumps(
                {"event": "error", "data": {"message": "Cannot add: FacebookId is null"}},
                ensure_ascii=False,
            ))

    elif action == "remove_monitor":
        facebook_id = msg.get("facebook_id")
        remove_monitor(facebook_id)
        await _broadcast("update", build_payload())

    elif action == "update_monitor":
        facebook_id = msg.get("facebook_id")
        patch = msg.get("patch", {})
        # Only allow staff-managed fields
        allowed = {"status", "assigned_to", "priority", "note"}
        safe_patch = {k: v for k, v in patch.items() if k in allowed}
        record = update_monitor(facebook_id, safe_patch)
        if record:
            upsert_monitor(record)
        await _broadcast("update", build_payload())

    elif action == "refresh":
        await _run_refresh()


async def _action_search_orders(websocket, msg: dict):
    query = msg.get("query", "")
    date_from = msg.get("date_from", "")
    date_to = msg.get("date_to", "")
    try:
        result = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: get_order_bills(date_from, date_to, search=query),
        )
        items = result.get("value") or []
        count = result.get("@odata.count", len(items))
        monitored_ids = set(get_all_monitors().keys())
        for item in items:
            item["_monitored"] = item.get("FacebookId") in monitored_ids
        await websocket.send(json.dumps(
            {"event": "orders", "data": {"count": count, "items": items}},
            ensure_ascii=False,
            default=str,
        ))
    except Exception as e:
        logger.error("search_orders error: %s", e)
        await websocket.send(json.dumps(
            {"event": "error", "data": {"message": str(e)}},
            ensure_ascii=False,
        ))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def main():
    global last_user_info

    # Fetch user info for dashboard title
    try:
        last_user_info = get_user_info()
        logger.info("Logged in as: %s", last_user_info.get("Name"))
    except Exception as e:
        logger.warning("Could not fetch user info: %s", e)

    # Sync all monitors to Google Sheets on startup
    try:
        monitors = get_all_monitors()
        if monitors:
            sync_all_monitors(monitors)
            logger.info("Synced %d monitors to Google Sheets", len(monitors))
    except Exception as e:
        logger.warning("Google Sheets sync failed: %s", e)

    # Start HTTP server in background thread
    http_thread = threading.Thread(target=_start_http_server, daemon=True)
    http_thread.start()

    # Schedule cronjob
    asyncio.create_task(cronjob_loop())

    # Start WebSocket server
    ws_port = cfg.server.ws_port
    logger.info("WebSocket server: ws://localhost:%d", ws_port)
    async with websockets.serve(ws_handler, "0.0.0.0", ws_port):
        logger.info(
            "Dashboard ready — display: http://localhost:%d/display  control: http://localhost:%d/control",
            cfg.server.http_port, cfg.server.http_port,
        )
        await asyncio.Future()  # Run forever


def run_server():
    """Entry point for launching from main.py CLI."""
    asyncio.run(main())


if __name__ == "__main__":
    run_server()
