# Order Monitor Dashboard — Project Plan

> All source for this module lives under `broadcast_order/`.
> Use this file with Claude Code to generate the full project.
> All code comments must be in English.

---

## Overview

Web dashboard to monitor customer messages per order bill.
- **Backend:** Python 3.11+ — WebSocket server + HTTP server + cronjob
- **Frontend:** Vanilla HTML/JS — `display.html` (TV/screen, read-only) + `control.html` (staff panel)
- **Persistence:** Local `monitors.json` + Google Sheets sync
- **Config:** Single `config.yml` — no hardcoded strings, URLs, or magic values anywhere in code
- **Logging:** All API requests/responses logged to `data/api.log`

---

## File Structure

```
broadcast_order/
├── config.yml                   # all config: credentials, URLs, staff, intervals, constants
│
├── config_loader.py             # load and validate config.yml, expose typed config object
│
├── app/
│   ├── auth.py                  # TPOS token manager: fetch, cache, auto-refresh
│   ├── api_client.py            # all TPOS API calls + request/response logging
│   ├── monitor_store.py         # monitors.json CRUD (thread-safe)
│   ├── sheets_client.py         # Google Sheets read/write
│   └── message_cache.py         # per-user message cache: store by message Id, detect new
│
├── dashboard/
│   ├── server.py                # WebSocket + HTTP server entry point
│   ├── display.html             # TV / any screen — read-only, 3 latest messages per user
│   └── control.html             # staff panel — full messages via collapse, tag/assign/note
│
└── data/
    ├── token.json               # auto-managed by auth.py
    ├── monitors.json            # persisted monitor records
    ├── messages/
    │   └── {facebook_id}.json   # per-user message cache
    └── api.log                  # all API request/response logs
```

---

## config.yml

```yaml
# TPOS API credentials
tpos:
  base_url: "https://linhdanshopld.tpos.vn"
  client_id: "tmtWebApp"
  grant_type: "password"
  username: "test"
  password: "Test@12345"
  scope: "profile"

  # Endpoints — no hardcoded paths in code
  endpoints:
    token:        "/token"
    user_info:    "/rest/v1.0/user/info"
    order_bills:  "/odata/FastSaleOrder/ODataService.GetView"
    messages:     "/api-ms/chatomni/v1/messages/all"

  # Message API fixed params
  message_type:       4            # type=4 for Facebook channel
  message_channel_id: "101008152679066"   # shop's Facebook page ID (fixed)

  # Order bill query
  order_top:          100
  order_date_range_days: 30
  order_filter_type:  "invoice"
  order_orderby:      "DateInvoice desc"

# Staff list
staff:
  - "An"
  - "Van"
  - "Linh"

# Fetch settings
fetch:
  message_interval_seconds: 600   # 10 minutes between full fetch cycles
  delay_between_users_seconds: 1  # delay between each user's message API call

# Token cache
token:
  file: "data/token.json"
  refresh_buffer_seconds: 300     # refresh 5 minutes before expiry

# Persistence
data:
  monitors_file:   "data/monitors.json"
  messages_dir:    "data/messages"
  log_file:        "data/api.log"

# Google Sheets
google_sheets:
  credentials_file: "data/google_credentials.json"
  spreadsheet_id:   "YOUR_SPREADSHEET_ID"
  monitors_sheet:   "Monitors"    # sheet name for monitor records
  messages_sheet:   "Messages"    # sheet name for new messages log

# Dashboard server
server:
  http_port: 8080
  ws_port:   8765
  display_path:  "/display"
  control_path:  "/control"
```

---

## config_loader.py

```python
"""
Load and expose config.yml as a typed object.
All other modules import cfg from here — never read config.yml directly.

Usage:
    from broadcast_order.config_loader import cfg

    cfg.tpos.base_url
    cfg.tpos.endpoints.token
    cfg.tpos.message_channel_id
    cfg.staff
    cfg.fetch.message_interval_seconds
    cfg.data.monitors_file
    cfg.google_sheets.spreadsheet_id
    cfg.server.http_port
"""

import yaml
from pathlib import Path
from types import SimpleNamespace

def _dict_to_ns(d: dict) -> SimpleNamespace:
    """Recursively convert dict to SimpleNamespace for dot-access."""

def load_config(path: str = "broadcast_order/config.yml") -> SimpleNamespace:
    """Load YAML, validate required fields, return namespace."""

# Module-level singleton — import this everywhere
cfg = load_config()
```

---

## API Reference (confirmed from real responses)

### Auth — POST `{tpos.base_url}{tpos.endpoints.token}`

**Request body** (form-encoded, values from config):
```
client_id={tpos.client_id}
&grant_type={tpos.grant_type}
&username={tpos.username}
&password={tpos.password}
&scope={tpos.scope}
```

**Real response:**
```json
{
  "access_token": "eyJhbGci...",
  "token_type": "bearer",
  "expires_in": 1295999,
  "refresh_token": "7af943d4...",
  "userName": "test",
  "userId": "11b9564f-35b9-4bdd-aad6-38b51d83a9eb",
  ".issued": "Sun, 22 Mar 2026 14:34:29 GMT",
  ".expires": "Mon, 06 Apr 2026 14:34:29 GMT"
}
```

**token.json** (saved locally, path from `cfg.token.file`):
```json
{
  "access_token": "string",
  "expires_at": "2026-04-06T14:34:29Z",
  "refresh_token": "string"
}
```

Parse `.expires` RFC string → ISO8601 → save as `expires_at`.
Refresh when `expires_at - now < cfg.token.refresh_buffer_seconds`.

---

### User Info — GET `{tpos.endpoints.user_info}`

**Real response:**
```json
{
  "Id": "11b9564f-35b9-4bdd-aad6-38b51d83a9eb",
  "Name": "Test",
  "UserName": "test",
  "Email": "test@gmail.com",
  "PhoneNumber": "0915428242",
  "Avatar": "https://statics.tpos.vn/Content/images/avatar.png",
  "Company": { "Id": 1, "Name": "Linh Đan Shop" }
}
```

Used for: `{Company.Name}` as dashboard title.

---

### Order Bills — GET `{tpos.endpoints.order_bills}`

**Query params** (values from config):
```
$top={tpos.order_top}
$skip=0
$filter=(Type eq '{tpos.order_filter_type}'
  and (DateInvoice ge {date_from} and DateInvoice le {date_to})
  and IsMergeCancel ne true)
$orderby={tpos.order_orderby}
$count=true
```

**Real response fields (confirmed):**
```json
{
  "@odata.count": 3145,
  "value": [
    {
      "Id": 123608,
      "Reference": "260303620",
      "PartnerDisplayName": "[KH66378] Linh Xinh",
      "FacebookId": "26333230062956263",
      "Phone": "0902766505",
      "DateInvoice": "2026-03-22T17:27:18.617+07:00",
      "State": "draft",
      "AmountTotal": 288000.00,
      "CashOnDelivery": 323000.00,
      "Tags": null,
      "UserName": "An",
      "ShowState": "Nháp",
      "ExtraProperties": "{ ... }"
    }
  ]
}
```

**Key field notes:**
- `FacebookId` → `user_id` for message API. **Skip order if null.**
- `Reference` → display as order code
- `PartnerDisplayName` → strip `[KHxxxxx]` prefix for display
- `Tags` → null currently, reserved for future use

---

### Messages — GET `{tpos.endpoints.messages}`

**Query params** (values from config):
```
type={tpos.message_type}
channelId={tpos.message_channel_id}    ← fixed, from config
userId={order.FacebookId}              ← per-user
```

**Real response (confirmed):**
```json
{
  "Data": [
    {
      "Id": "69bfc40d0f45bfbb7dc4e41a",
      "Type": "message",
      "MessageType": 0,
      "Status": 1,
      "Message": "Dạ shop đi đơn ạ",
      "MessageFormatted": "Dạ shop đi đơn ạ",
      "IsOwner": true,
      "Owner": { "Id": "101008152679066" },
      "User": { "Id": "26333230062956263" },
      "Channel": { "Id": "101008152679066", "Type": 4 },
      "ApplicationUser": {
        "Id": "be4a16ab-8d70-440b-bf97-f268c9f9418a",
        "Name": "0915500082",
        "UserName": "0915500082"
      },
      "CreatedTime": "2026-03-22T10:27:26.351Z",
      "UpdatedTime": null
    }
  ],
  "Cursor": null,
  "After": "string",
  "Before": "string"
}
```

**Rules:**
- Only process `Type == "message"` (ignore `"comment"`)
- `IsOwner: true` = shop sent; `IsOwner: false` = customer sent
- Messages are identified by `Id` field for cache deduplication

---

## app/auth.py

```python
"""
TPOS token manager.
Reads config via cfg. Caches token to cfg.token.file.
Public interface: get_token() -> str
"""

def get_token() -> str:
    """Return valid Bearer access_token. Auto-refresh when near expiry."""

def _load_cached() -> dict | None:
    """Load token from cfg.token.file. Return None if missing or unreadable."""

def _is_expired(token_data: dict) -> bool:
    """Return True if expires_at - now < cfg.token.refresh_buffer_seconds."""

def _fetch_new_token() -> dict:
    """
    POST to cfg.tpos.base_url + cfg.tpos.endpoints.token.
    Build body from cfg.tpos fields (client_id, grant_type, username, password, scope).
    Parse .expires RFC string → ISO8601 expires_at.
    Log request/response via api_logger.
    Save to cfg.token.file. Return normalized dict.
    """

def _save_token(token_data: dict):
    """Write normalized token_data to cfg.token.file."""
```

---

## app/api_client.py

```python
"""
All TPOS API calls.
Each method auto-calls auth.get_token() for Bearer header.
All requests/responses logged to cfg.data.log_file via _log().
No hardcoded URLs or values — all from cfg.
"""

def _log(method: str, url: str, params: dict, response_status: int, response_body: str):
    """
    Append one JSON line to cfg.data.log_file:
    { "ts": "...", "method": "GET", "url": "...", "params": {}, "status": 200, "body_preview": "...500 chars..." }
    """

def _headers() -> dict:
    """Return {"Authorization": "Bearer {get_token()}"}"""

def get_user_info() -> dict:
    """GET {base_url}{endpoints.user_info}. Log request/response."""

def get_order_bills(date_from: str, date_to: str, skip: int = 0, search: str = "") -> dict:
    """
    GET {base_url}{endpoints.order_bills} with OData params from cfg.
    If search provided, append contains() filter for PartnerDisplayName, Phone, Reference.
    Log request/response.
    Returns: { "@odata.count": int, "value": [order, ...] }
    """

def get_messages(user_id: str) -> dict:
    """
    GET {base_url}{endpoints.messages}
    Params: type={cfg.tpos.message_type}, channelId={cfg.tpos.message_channel_id}, userId={user_id}
    channel_id is always from config — never passed as argument.
    Log request/response.
    Returns raw response dict.
    """

def clean_partner_name(name: str) -> str:
    """Strip [KHxxxxx] prefix: re.sub(r'^\\[KH\\d+\\]\\s*', '', name)."""

def compute_message_stats(messages: list[dict]) -> dict:
    """
    Input: list of message dicts already filtered to Type == "message".
    Returns:
    {
      "last_customer_msg_time": str | None,
      "last_shop_msg_time":     str | None,
      "last_message_preview":   str,          # first 80 chars of latest message
      "unread_duration_mins":   float,        # 0 if shop replied after customer
      "needs_reply":            bool,
      "messages_fetched_at":    str           # UTC ISO8601
    }
    Logic:
      - customer_msgs = [m for m in messages if not m["IsOwner"]]
      - shop_msgs     = [m for m in messages if m["IsOwner"]]
      - needs_reply   = last customer CreatedTime > last shop CreatedTime (or no shop msg)
      - unread_mins   = (now - last_customer_msg.CreatedTime).seconds / 60 if needs_reply else 0
    """
```

---

## app/message_cache.py

```python
"""
Per-user message cache stored in cfg.data.messages_dir/{facebook_id}.json.
Keyed by message Id to avoid N+1 re-fetching and detect new messages.

Cache file schema:
{
  "facebook_id": "26333230062956263",
  "updated_at": "2026-03-22T10:00:00Z",
  "messages": {
    "69bfc40d0f45bfbb7dc4e41a": {
      "Id": "69bfc40d0f45bfbb7dc4e41a",
      "Type": "message",
      "Message": "Dạ shop đi đơn ạ",
      "IsOwner": true,
      "CreatedTime": "2026-03-22T10:27:26.351Z",
      "ApplicationUser": { "Name": "0915500082" }
    }
  }
}
"""

def load_cache(facebook_id: str) -> dict:
    """Load messages/{facebook_id}.json. Return empty structure if not found."""

def save_cache(facebook_id: str, cache: dict):
    """Write to messages/{facebook_id}.json."""

def merge_messages(facebook_id: str, raw_api_messages: list[dict]) -> tuple[dict, list[dict]]:
    """
    Merge new API messages into existing cache.
    Only store Type == "message" items.
    Key by message["Id"].

    Returns:
      - updated_cache: full cache dict after merge
      - new_messages:  list of message dicts that were NOT previously in cache

    This prevents N+1: only truly new messages are flagged for broadcast + Sheets sync.
    """

def get_messages_list(facebook_id: str, limit: int | None = None) -> list[dict]:
    """
    Return messages as list sorted by CreatedTime descending.
    If limit provided, return only first N items (e.g. limit=3 for display.html).
    """
```

---

## app/monitor_store.py

```python
"""
CRUD for data/monitors.json.
Thread-safe via threading.Lock.
"""

def load_monitors() -> dict
def save_monitors(data: dict)

def add_monitor(order: dict) -> dict | None:
    """
    Build record from order bill API response dict.
    Return None if order["FacebookId"] is None or empty.
    Do not overwrite if facebook_id already exists.

    Record schema:
    {
      "facebook_id":    str,
      "channel_id":     str,   # from cfg.tpos.message_channel_id
      "reference":      str,   # order["Reference"]
      "partner_name":   str,   # clean_partner_name(order["PartnerDisplayName"])
      "phone":          str,
      "date_invoice":   str,
      "amount_total":   float,
      "order_state":    str,
      "added_at":       str,   # UTC ISO8601 now

      # Monitor metadata (staff-managed)
      "status":         "pending",
      "assigned_to":    null,
      "priority":       "normal",
      "note":           "",

      # Computed from message cache (updated by cronjob)
      "last_customer_msg_time": null,
      "last_shop_msg_time":     null,
      "last_message_preview":   null,
      "unread_duration_mins":   null,
      "needs_reply":            false,
      "messages_fetched_at":    null
    }
    """

def remove_monitor(facebook_id: str) -> bool
def update_monitor(facebook_id: str, patch: dict) -> dict | None
def get_monitor(facebook_id: str) -> dict | None
def get_all_monitors() -> dict    # returns shallow copy
```

---

## app/sheets_client.py

```python
"""
Google Sheets sync.
Credentials file: cfg.google_sheets.credentials_file
Spreadsheet ID:   cfg.google_sheets.spreadsheet_id

Two sheets:
  1. cfg.google_sheets.monitors_sheet  — full monitor records (upsert by facebook_id)
  2. cfg.google_sheets.messages_sheet  — append-only log of new messages

Requires: pip install google-auth google-auth-httplib2 google-api-python-client
"""

def get_service():
    """Build and return Google Sheets API service using service account credentials."""

def upsert_monitor(record: dict):
    """
    Write/update one monitor record to monitors_sheet.
    Find row by facebook_id in column A, update in-place. Append if not found.
    Columns: facebook_id, reference, partner_name, phone, date_invoice,
             status, assigned_to, priority, note, needs_reply,
             unread_duration_mins, last_customer_msg_time, last_message_preview
    """

def append_new_messages(facebook_id: str, new_messages: list[dict]):
    """
    Append new message rows to messages_sheet.
    Columns: facebook_id, message_id, is_owner, sender_name,
             message_text, created_time, logged_at
    Only called when new_messages is non-empty.
    """

def sync_all_monitors(monitors: dict):
    """Batch upsert all monitor records. Called on startup and after refresh."""
```

---

## dashboard/server.py

```python
"""
Entry point for the dashboard.
Starts: HTTP server (thread) + WebSocket server (asyncio) + cronjob (asyncio task).
All config from cfg.
"""

# Module-level state
last_user_info: dict = {}
ws_clients: set = set()

async def main():
    # 1. Fetch user_info for dashboard title
    # 2. Sync all monitors to Google Sheets on startup
    # 3. Start HTTP server thread
    # 4. Schedule cronjob task
    # 5. Start WebSocket server

async def cronjob_loop():
    """
    Every cfg.fetch.message_interval_seconds:
      For each monitored facebook_id:
        1. Call get_messages(facebook_id)
        2. Merge into cache via message_cache.merge_messages()
        3. If new_messages: append to Google Sheets + log
        4. Compute stats via compute_message_stats()
        5. update_monitor() with stats patch
        6. upsert_monitor() to Google Sheets
        7. await asyncio.sleep(cfg.fetch.delay_between_users_seconds)
      Broadcast "update" event to all WS clients.
    """

async def ws_handler(websocket):
    """
    On connect: send current state immediately.
    Handle actions: search_orders, add_monitor, remove_monitor, update_monitor, refresh.
    On disconnect: remove from ws_clients.
    """

def build_payload() -> dict:
    """
    Build full state payload for broadcast:
    {
      "monitors": get_all_monitors(),
      "staff": cfg.staff,
      "user_info": last_user_info,
      # per monitor, include messages list (limit=3 for display, full for control — handled client-side)
      "messages": { facebook_id: get_messages_list(facebook_id) }
    }
    """

# HTTP routes:
#   GET /           → display.html
#   GET /display    → display.html
#   GET /control    → control.html
```

---

## WebSocket Protocol

**Server → Client events:**
```json
{ "event": "update", "data": {
    "monitors": { "26333230062956263": { ... } },
    "staff":    ["An", "Van", "Linh"],
    "user_info": { "Name": "Test", "Company": { "Name": "Linh Đan Shop" } },
    "messages": { "26333230062956263": [ ...all messages sorted desc... ] }
}}
{ "event": "orders", "data": { "count": 10, "items": [ ...order bills... ] } }
{ "event": "error",  "data": { "message": "..." } }
```

**Client → Server actions:**
```json
{ "action": "search_orders",  "query": "linh", "date_from": "2026-02-01", "date_to": "2026-03-22" }
{ "action": "add_monitor",    "facebook_id": "26333230062956263", "reference": "260303620",
                               "partner_name": "Linh Xinh", "phone": "...", "date_invoice": "...",
                               "amount_total": 288000, "order_state": "draft" }
{ "action": "remove_monitor", "facebook_id": "26333230062956263" }
{ "action": "update_monitor", "facebook_id": "26333230062956263",
  "patch": { "status": "done", "assigned_to": "An", "priority": "high", "note": "..." } }
{ "action": "refresh" }
```

---

## dashboard/display.html — TV / Any Screen

**Layout:** Full-width table, auto-refreshes via WebSocket.

**Table columns (tiếng Việt):**

| # | Cột | Field | Format |
|---|-----|-------|--------|
| 1 | Mã đơn | `reference` | plain |
| 2 | Khách hàng | `partner_name` | plain (already cleaned) |
| 3 | Ngày xuất | `date_invoice` | `HH:mm DD/MM/YY` |
| 4 | Ưu tiên | `priority` | badge 🔴/🟡/🟢 |
| 5 | Trạng thái | `status` | Chưa xử lý / Đang xử lý / Hoàn tất |
| 6 | Phụ trách | `assigned_to` | plain or `—` |
| 7 | Tin nhắn (3 mới nhất) | `messages[0..2]` | show up to 3, bubble style, `IsOwner` differentiated |
| 8 | Khách nhắn lúc | `last_customer_msg_time` | relative: "2 giờ trước" |
| 9 | Chưa rep | `unread_duration_mins` | "72 phút" — red >60, yellow >30 |
| 10 | Ghi chú | `note` | plain |

**Row highlight rules:**
- 🔴 Red bg: `needs_reply == true` AND `unread_duration_mins > 60`
- 🟡 Yellow bg: `needs_reply == true` AND `unread_duration_mins <= 60`
- ⬛ Dimmed: `status == "done"`
- Default sort: `needs_reply DESC`, `unread_duration_mins DESC`

**Message display (column 7):**
- Show max 3 latest messages (already limited by server payload)
- Each message: small bubble — grey for customer, blue for shop
- Show sender name + time
- No interaction — read-only

---

## dashboard/control.html — Staff Panel

**Layout:** Mobile-friendly card list + collapsible message thread.

### Header
- Shop name from `user_info.Company.Name`
- WebSocket connection badge
- "Làm mới ngay" button → `refresh` action
- Last updated timestamp

### Add Order Section
- Date range picker (default: last `cfg.tpos.order_date_range_days` days)
- Search input: name / phone / reference
- "Tìm đơn" button → `search_orders` WS action
- Results table: Reference, Khách hàng, Ngày, SĐT, COD
  - "Theo dõi" button → `add_monitor` (disabled + "Đang theo dõi" if already added; disabled if FacebookId null)

### Monitor List
**Filter tabs:** Tất cả / Cần rep / Đang xử lý / Hoàn tất / per staff name

**Each monitor card:**
```
┌─────────────────────────────────────────┐
│ #260303620  Linh Xinh  17:27 22/03/26   │
│ 🔴 Cao  •  Đang xử lý  •  An           │
│ ⏱ Chưa rep: 72 phút                    │
├─────────────────────────────────────────┤
│ [3 latest message bubbles — same as TV] │
│ ▼ Xem tất cả tin nhắn (collapse)        │
│   [full message thread on expand]        │
├─────────────────────────────────────────┤
│ Phụ trách: [An ▼]                       │
│ Trạng thái: [Chưa xử lý][Đang xử lý][Hoàn tất] │
│ Ưu tiên:   [🔴 Cao][🟡 Thường][🟢 Thấp] │
│ Ghi chú:   [__________________] [Lưu]   │
│                        [Xoá khỏi ds]    │
└─────────────────────────────────────────┘
```

**Collapse "Xem tất cả tin nhắn":**
- Default: collapsed, shows 3 latest (same as display.html)
- On expand: shows full message thread from `messages[facebook_id]`
- Messages sorted newest-first
- Each bubble: sender name, time, content, `IsOwner` styling

---

## Google Sheets Structure

### Sheet: Monitors
| Column | Field |
|--------|-------|
| A | facebook_id |
| B | reference |
| C | partner_name |
| D | phone |
| E | date_invoice |
| F | status |
| G | assigned_to |
| H | priority |
| I | note |
| J | needs_reply |
| K | unread_duration_mins |
| L | last_customer_msg_time |
| M | last_message_preview |
| N | updated_at |

### Sheet: Messages (append-only log)
| Column | Field |
|--------|-------|
| A | facebook_id |
| B | message_id |
| C | is_owner |
| D | sender_name |
| E | message_text |
| F | created_time |
| G | logged_at |

---

## Implementation Order

```
Step 1: config.yml + config_loader.py
        → test: python -c "from broadcast_order.config_loader import cfg; print(cfg.tpos.base_url)"

Step 2: app/auth.py
        → test: python -c "from broadcast_order.app.auth import get_token; print(get_token()[:20])"

Step 3: app/api_client.py
        → test: python -c "from broadcast_order.app.api_client import get_user_info; print(get_user_info())"
        → check data/api.log after each call

Step 4: app/message_cache.py
        → unit test merge_messages with sample data

Step 5: app/monitor_store.py
        → unit test add/update/remove

Step 6: app/sheets_client.py
        → test upsert_monitor with one dummy record

Step 7: dashboard/server.py
        → python -m broadcast_order.dashboard.server

Step 8: dashboard/display.html

Step 9: dashboard/control.html
```

---

## Run

```bash
# Install dependencies
pip install websockets pyyaml google-auth google-auth-httplib2 google-api-python-client

# Start dashboard
python -m broadcast_order.dashboard.server

# TV / Display screen
http://localhost:8080/display

# Staff control panel
http://localhost:8080/control

# Watch API logs
tail -f broadcast_order/data/api.log
```

---

## Edge Cases & Rules

| Case | Handling |
|------|----------|
| `FacebookId` null in order | Skip — `add_monitor` returns None |
| No new messages in API response | `merge_messages` returns empty `new_messages` list — no Sheets write |
| Same message Id seen again | Cache dedup — not counted as new |
| Token expired mid-run | `get_token()` checks expiry before every call |
| `[KHxxxxx]` prefix in name | Strip with `re.sub(r'^\[KH\d+\]\s*', '', name)` |
| API rate limit / timeout | Catch per user in cronjob, log to api.log, continue |
| Monitor removed while cronjob running | Check key exists before update |
| Multiple browsers open | All receive same broadcast via WS |
| Google Sheets API failure | Log error, continue — local data is source of truth |
| `unread_duration_mins` < 1 | Display "< 1 phút" |
| No messages at all for user | Show "Chưa có tin nhắn" placeholder |
