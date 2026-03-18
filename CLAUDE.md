# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Playwright-based automation bot for managing ecommerce orders on `linhdanshopld.tpos.vn`. Two primary workflows:
- **collect_order**: Scrapes filtered orders, enriches with tags/address status/product matches, exports to CSV
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
2. Load & validate `config.yaml`
3. Launch Playwright Chromium with session persistence (`data/session.json`)
4. Authenticate: saved token → auto-login → manual login (300s wait)
5. Capture Bearer token to `data/auth_token.json`
6. Navigate to orders page, apply campaign filter
7. Execute feature (collect or confirm)
8. Save session state, cleanup

### Module Responsibilities

| Module | Role |
|--------|------|
| `app/order_page.py` | Page Object Model — all Playwright selectors, pagination, row extraction, modal interactions |
| `app/login.py` | Auth flow: token bootstrap → auto-login → manual login |
| `app/auth.py` | Bearer token extraction from browser storage (localStorage, sessionStorage, IndexedDB), JWT parsing |
| `app/config_loader.py` | YAML config loading with PyYAML fallback |
| `app/store.py` | State persistence (per-day JSON), CSV export, action audit logging |
| `app/rules.py` | Order classification (`classify_order`) and action decision (`decide_action`) logic |
| `app/constants.py` | Order tag constants: NEW, COC, CHECK, NO_ADDR, TODO_ADDR, TODO_NO_ADDR, ERR |
| `app/cli_helpers.py` | InquirerPy prompts for feature/date/CSV selection |
| `app/cli_menu.py` | ANSI terminal UI rendering (banner, select, summary) |
| `features/collect_order.py` | Two-pass: read all rows → enrich each row → export CSV |
| `features/confirm_order.py` | Load order codes from CSV → find each row via pagination → perform edit |
| `workflows/navigation.py` | `goto_orders()` — navigate to order URL |
| `runtime/process_logger.py` | Timestamped console logging, exception capture, debug browser keep-alive |

### Key Data Files (runtime, in `data/`)
- `session.json` — Playwright browser context storage state (cookies, storage)
- `auth_token.json` — Cached Bearer token with JWT expiry metadata
- `processed_{DATE}.json` — Per-day order processing history (MD5 hashes for dedup)
- `actions_{DATE}.csv` — Audit log of all bot actions
- `orders_{campaign}_{timestamp}.csv` — Collected order export (headers: No, Order_Code, Tag, Channel, Customer, Total_Amount, Total_Qty, Address_Status, Note, Match_Product, Decision)
- `error/` — Screenshots and exception logs on failure

### Configuration (`config.yaml`)
Key settings:
- `headless`: false = visible browser, true = headless
- `credentials`: username/password for auto-login
- `keywords.pickup`: Vietnamese phrases indicating in-store pickup (e.g., "ghé lấy")
- `keywords.match_product`: keywords for product matching in order notes
- `messages.ask_address`: Vietnamese message sent to customers missing address
- `auth.bootstrap_from_token`: reuse saved token to skip login
- `debug.keep_open`: keep browser open after run for inspection

### Pagination Pattern
`order_page.py` handles multi-page tables with two main methods:
- `read_filtered_orders()` — iterates all pages collecting rows
- `find_row_by_code_paginated(order_code)` — searches across pages for a specific code

### Session Persistence
Bad/expired session files are quarantined as `.bad.json`; a fresh context is created instead of crashing.

### Error Handling
Errors produce screenshots in `data/error/` and full tracebacks in `data/error/error_{timestamp}.log`.
