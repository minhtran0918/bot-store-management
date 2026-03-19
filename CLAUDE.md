# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Playwright-based automation bot for managing ecommerce orders on `linhdanshopld.tpos.vn`. Two primary workflows:

- **collect_order**: Scrapes filtered orders, enriches with tags/address status/product matches, sends messages, exports to CSV
- **confirm_order**: Takes a CSV of order codes and performs batch confirmation/edit actions

## Setup

```bash
pip install -r requirements.txt
python -m playwright install chromium
```

## Running

```bash
python main.py
```

Interactive CLI prompts for feature selection, campaign date, and CSV file path.

## Tests

```bash
python -m unittest discover -s tests -v
# Single test file:
python -m unittest tests.test_rules -v
```

## Architecture

### Entry Point Flow (`main.py`)

1. CLI prompts (feature, campaign date, CSV path)
2. Load & validate `config.yaml` → `BotConfig` validates all required timeouts at startup
3. Launch Playwright Chromium with session persistence (`data/session.json`)
4. Maximize browser window via `window.resizeTo(screen.availWidth, screen.availHeight)` (Playwright locks viewport size, so JS maximize is needed)
5. Authenticate: saved token → auto-login → manual login (300s wait)
6. Capture Bearer token to `data/auth_token.json`
7. Navigate to orders page, apply campaign filter
8. Execute feature (collect or confirm)
9. Save session state, cleanup

### Module Responsibilities

| Module | Role |
| ------ | ---- |
| `app/order_page.py` | Page Object Model — all Playwright selectors, pagination, row extraction, modal interactions, message sending |
| `app/login.py` | Auth flow: token bootstrap → auto-login → manual login |
| `app/auth.py` | Bearer token extraction from browser storage (localStorage, sessionStorage, IndexedDB), JWT parsing |
| `app/config_loader.py` | YAML config loading with PyYAML fallback |
| `app/store.py` | State persistence (per-day JSON), CSV export, action audit logging |
| `app/rules.py` | Order classification (`classify_order`) and action decision (`decide_action`) logic |
| `app/constants.py` | 6-case tag system (TAG_1 through TAG_2_2), RECHECK_TAGS, STATUS_TO_TAG mapping |
| `app/cli_helpers.py` | InquirerPy prompts for feature/date/CSV selection |
| `app/bot_config.py` | Typed config accessor — validates required timeouts at startup, exposes feature flags and message templates |
| `app/cli_menu.py` | ANSI terminal UI rendering (banner, select, summary) |
| `features/collect_order.py` | Two-pass: read all rows → enrich each row → export CSV. Respects `bot.test_max_collect_records` cap |
| `features/confirm_order.py` | Load order codes from CSV → find each row via pagination → perform edit |
| `features/ask_address.py` | Single-order processing: open modal, classify, send ask-address message if needed |
| `workflows/navigation.py` | `goto_orders()` — navigate to order URL |
| `runtime/process_logger.py` | Timestamped console logging, exception capture, debug browser keep-alive |

### 6-Case Tag System (core business logic)

Orders are classified by address presence + product match count into 6 cases. Tags are set on the web UI and drive which messages get sent. Defined in `app/constants.py`, applied in `order_page.py`'s `enrich_collected_rows()`.

**Filter condition**: orders with no tag OR tag 1.2/2.2 (recheck) + status "Nháp" + customer "Bình thường".

| Tag | Status Constant | Condition | Actions |
| --- | --------------- | --------- | ------- |
| `1` | `HAVE_ADDR_LOW_SP` | Address + 1-3 products matched | IMAGE_PRODUCT |
| `1.1` | `HAVE_ADDR_HIGH_SP` | Address + 4+ products matched | IMAGE_PRODUCT, MESS 2, MESS 3 |
| `1.2` | `HAVE_ADDR_NO_SP` | Address + 0 matched | Tag only (manual review) |
| `2` | `NO_ADDR_LOW_SP` | No address + 1-3 products matched | IMAGE_PRODUCT, MESS 1, MESS 3 |
| `2.1` | `NO_ADDR_HIGH_SP` | No address + 4+ products matched | IMAGE_PRODUCT, MESS 1, MESS 2, MESS 3 |
| `2.2` | `NO_ADDR_NO_SP` | No address + 0 matched | Tag only (manual review) |

**Recheck tags** (1.2, 2.2): `RECHECK_TAGS` set — on next run these orders are re-picked and re-evaluated. If products now match, tag changes to the appropriate case.

### Message Types

- **MESS 1** — Ask for address (`_NO_ADDR_TEMPLATES`, random selection) → cases 2, 2.1
- **MESS 2** — Ask for deposit (`_DEPOSIT_TEMPLATE`, fixed) → cases 1.1, 2.1
- **MESS 3** — Reply comment (`_COMMENT_FALLBACK_TEMPLATES`, random, ALWAYS reply) → cases 1.1, 2, 2.1

Sending priority: images first, then text. CSV "Comment" column tracks MESS 3 result: `ok` / `send_fail`.

### Test Cap

`bot.test_max_collect_records` in `config.yaml` limits rows during development (set to `null` for full run). The cap counts ALL rows encountered (qualifying + skipped), not just qualifying ones. Skipped rows are logged with the reason.

### Key Data Files (runtime, in `data/`)

- `session.json` — Playwright browser context storage state (cookies, storage)
- `auth_token.json` — Cached Bearer token with JWT expiry metadata
- `processed_{DATE}.json` — Per-day order processing history (MD5 hashes for dedup)
- `actions_{DATE}.csv` — Audit log of all bot actions
- `orders_{campaign}_{timestamp}.csv` — Collected order export (headers: No, Order_Code, Tag, Channel, Customer, Total_Amount, Total_Qty, Address_Status, Note, Match_Product, Decision, Comment)
- `error/` — Screenshots and exception logs on failure

### Configuration (`config.yaml`)

`config.yaml` is the single source of truth for all timing and behavior settings. `BotConfig` validates at startup — missing required keys cause an immediate error (no silent defaults).

Key sections:

- `bot`: runtime limits (`test_max_collect_records`, `max_images_per_send`)
- `features`: feature flags (`enable_comment_reply`)
- `timeouts`: all Playwright wait durations in milliseconds — every key is required, no defaults in code
- `messages`: Vietnamese message templates with `{name}` placeholder for customer name
- `keywords.pickup`: phrases indicating in-store pickup (e.g., "ghé lấy")
- `keywords.match_product`: keywords for product matching in order notes
- `credentials`: username/password for auto-login
- `auth.bootstrap_from_token`: reuse saved token to skip login
- `debug.keep_open`: keep browser open after run for inspection

### Vietnamese Text Handling

The UI renders Vietnamese with diacritics (e.g., "Giá" not "Gia"). When writing regex patterns against `inner_text()` output, always account for diacritical marks: use character classes like `Gi[aá]` or Unicode-aware patterns.

### Pagination Pattern

`order_page.py` handles multi-page tables with two main methods:

- `read_filtered_orders()` — iterates all pages collecting rows
- `find_row_by_code_paginated(order_code)` — searches across pages for a specific code

### Session Persistence

Bad/expired session files are quarantined as `.bad.json`; a fresh context is created instead of crashing.

### Error Handling

Errors produce screenshots in `data/error/` and full tracebacks in `data/error/error_{timestamp}.log`.
