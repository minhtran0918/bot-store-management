# Bot Store Management

Simple Playwright automation for order handling with conditional actions.

## What it does

- Opens the orders page.
- Iterates through rows in the order table (all pages via pagination for collect flow).
- Opens each order modal and reads note + address.
- Applies rules:
  - `pickup`: skip asking address.
  - `send_ask_address`: send message + confirmation image.
  - `skip_already_asked`: avoid duplicate sends in cooldown window.
  - `mark_done`: mark as done if address exists.
- Stores state and writes CSV logs in `data/`.
- Exports filtered orders with progress fields: `Tag`, `Address_Status`, `Note`, `Match_Product`, `Decision`.
- Uses shared order constants in `app/constants.py`: `NEW`, `DEPOSIT`, `READY`, `NO_ADDRESS`, `STOCK_ISSUE`, `ERROR`.

## Project files

- `main.py`: orchestration entrypoint and Playwright run loop.
- `app/order_page.py`: page-object selectors and UI actions.
- `app/login.py`: token/bootstrap login + auto/manual login flow.
- `app/auth.py`: bearer token parsing/capture/save helpers.
- `app/config_loader.py`: loads and normalizes runtime config from YAML.
- `app/store.py`: JSON state + CSV action log/export.
- `app/constants.py`: shared status/tag constants.
- `app/cli_helpers.py`: interactive CLI option prompts.
- `features/confirm_order.py`: confirm flow from collected CSV (`Order Code` list).
- `features/ask_address.py`: ask-address decision/action feature logic (extracted for modularity).
- `features/collect_order.py`: collect flow (strict export mode).
- `app/rules.py`: conditional decision logic.
- `tests/test_rules.py`: unit tests for action decisions.

## Setup

```powershell
python -m pip install -r requirements.txt
python -m playwright install chromium
```

## Run

```powershell
python main.py
```

Campaign filter selection is interactive when starting `main.py`:

- First, choose run feature:
  - `collect_order` (default): filter and collect rows to CSV across pagination, auto-add `NEW` tag for empty-tag rows, then run per-order check (`check_tag_new -> address_ok/no_address -> match_product/no_match_product`) before saving CSV.
  - `confirm_order`: requires selecting an existing collected CSV, then runs login -> dashboard -> order -> filter -> iterate CSV order codes with per-order pagination lookup before edit-action placeholders.
- Press `1` for `yesterday` (default)
- Press `2` for `today`
- Press `3` to input a custom date (`d/m`, `d/m/yyyy`, or `yyyy-mm-dd`)
- Press `4` to input a full label (example: `LIVE 14/3/2026`)

When running `collect_order`, you can choose to create a new CSV or reuse an existing `orders_*.csv` file. The flow is strict: if collect/export fails, the run fails (no empty fallback CSV).

When running `confirm_order`, selecting an existing CSV is mandatory. The bot logs start/success/fail for each order code listed in that CSV.

If an error happens during a run, screenshots are saved to `data/error/` and detailed stack traces are appended to a per-run file like `data/error/error_YYYYMMDD_HHMMSS.log`.

## Config

Edit `config.yaml` to control:

- `base_url`, `headless`
- `messages.ask_address`
- `keywords.pickup`
- `keywords.match_product` (list of note keywords to mark `Match Product=true`)
- `credentials.username` and `credentials.password` for optional auto-login
- `auth.login_url`, `auth.dashboard_url`, `auth.order_url` for route flow
- `auth.capture_enabled`, `auth.bootstrap_from_token`, `auth.indexeddb_token_key`, `auth.token_file` for Bearer token capture/reuse
- `debug.keep_open` and `debug.keep_open_seconds` to keep browser open for debugging

If credentials are empty or login selectors do not match, the bot falls back to manual sign-in and waits in the open browser. Session is saved to `data/session.json`.

When `auth.capture_enabled` is true, the bot captures a Bearer token from browser storage (including IndexedDB key `TpageBearerToken`) and saves it to `data/auth_token.json` (or your configured `auth.token_file`) with safe metadata (`expires_in`, issue/expiry strings, refresh-token presence flag). If the saved token is expired, the token file is automatically cleared and the bot falls back to full login.

## Test

```powershell
python -m unittest discover -s tests -v
```

