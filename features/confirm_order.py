from __future__ import annotations

import csv
from pathlib import Path
from typing import Callable

from app.order_page import OrderPage


_RESET_TABLE_VIEW: Callable[[], None] | None = None


def set_confirm_reset_table_view(callback: Callable[[], None] | None) -> None:
    global _RESET_TABLE_VIEW
    _RESET_TABLE_VIEW = callback


def load_order_codes_from_csv(csv_path: Path) -> list[str]:
    if not csv_path.exists() or csv_path.stat().st_size == 0:
        raise ValueError(f"CSV file is missing or empty: {csv_path}")

    with csv_path.open("r", newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames or []
        order_code_header = "Order_Code" if "Order_Code" in fieldnames else "Order Code"
        if order_code_header not in fieldnames:
            raise ValueError(f"CSV missing required column 'Order_Code': {csv_path}")

        seen: set[str] = set()
        codes: list[str] = []
        for row in reader:
            order_code = str((row or {}).get(order_code_header, "")).strip()
            if not order_code or order_code in seen:
                continue
            seen.add(order_code)
            codes.append(order_code)

    return codes


def _safe_file_token(value: str) -> str:
    cleaned = []
    for ch in str(value or ""):
        if ch.isalnum() or ch in ("_", "-"):
            cleaned.append(ch)
    result = "".join(cleaned).strip("_-")
    return result[:60] or "unknown"


def run_confirm_order_from_csv(
    order_page: OrderPage,
    page,
    order_codes: list[str],
    error_dir: Path,
    error_log_file: Path,
    log_console: Callable[[str], None],
    log_action: Callable[[str, str, str, str], None],
    log_exception_trace: Callable[[str, Exception], None],
) -> None:
    has_reset_table_view = _RESET_TABLE_VIEW is not None
    reset_table_view = _RESET_TABLE_VIEW or (lambda: None)

    total = len(order_codes)
    log_console(f"[CONFIRM] Start confirm_order by CSV | total={total}")
    log_console(f"[CONFIRM] Error log file: {error_log_file}")

    for index, order_code in enumerate(order_codes, start=1):
        log_console(f"[CONFIRM] ({index}/{total}) Start edit action for order={order_code}")
        log_action(order_code, "confirm_order_edit", "info", "start")

        try:
            if has_reset_table_view:
                log_console(f"[CONFIRM] ({index}/{total}) Reset table view before lookup")
                reset_table_view()

            row, page_index = order_page.find_row_by_code_paginated(order_code)
            if row is None:
                raise ValueError("order code not found after pagination scan")

            log_console(f"[CONFIRM] ({index}/{total}) Located order at page={page_index}")

            # Placeholder for future edit flow implementation.
            log_console(f"[CONFIRM] ({index}/{total}) Edit action success for order={order_code}")
            log_action(order_code, "confirm_order_edit", "ok", "placeholder success")
        except Exception as exc:
            safe_code = _safe_file_token(order_code)
            screenshot_path: Path | None = None
            try:
                screenshot_path = error_dir / f"confirm_{index}_{safe_code}.png"
                page.screenshot(path=str(screenshot_path), full_page=True)
                log_console(f"[ERROR] Screenshot saved: {screenshot_path.resolve()}")
            except Exception:
                screenshot_path = None

            context = f"Confirm order failed | order={order_code}"
            if screenshot_path is not None:
                context = f"{context} | screenshot={screenshot_path}"
            log_exception_trace(context, exc)
            log_console(f"[CONFIRM] ({index}/{total}) Edit action failed for order={order_code}")
            log_action(order_code, "confirm_order_edit", "error", repr(exc))



