from __future__ import annotations

from pathlib import Path
from typing import Callable

from app.order_page import OrderPage
from app.store import save_filtered_orders


LogActionFn = Callable[[str, str, str, str], None]
LogConsoleFn = Callable[[str], None]
TEST_MAX_COLLECT_RECORDS = 4  # Set to None for full run


def run_collect_order_flow(
    order_page: OrderPage,
    campaign_label: str,
    log_console: LogConsoleFn,
    log_action: LogActionFn,
    csv_output_path: Path | None = None,
    data_dir: Path | None = None,
) -> tuple[list[dict[str, str]], Path | None]:
    try:
        # Pass 1: Tag all orders as NEW (paginate through all pages)
        log_console(f"PASS 1: Tagging orders as NEW... (cap={TEST_MAX_COLLECT_RECORDS or 'unlimited'})")
        exported_orders = order_page.read_filtered_orders(max_records=TEST_MAX_COLLECT_RECORDS)
        log_console(f"PASS 1: done, total collected={len(exported_orders)}")

        if exported_orders:
            # Go back to page 1 before processing
            log_console("PASS 2: Go to page 1, start processing NEW orders...")
            order_page.go_to_first_page()

            processed, stock_issue_count, error_count = order_page.enrich_collected_rows(exported_orders, data_dir=data_dir)
            log_console(
                f"PASS 2: done | processed={processed} stock_issue={stock_issue_count} "
                f"error={error_count} total={len(exported_orders)}"
            )

        log_action("system", "export_orders_prepare", "ok", f"rows={len(exported_orders)}")
        exported_path = save_filtered_orders(
            exported_orders,
            campaign_label,
            output_path=csv_output_path,
        )
        log_console(f"CSV saved: {exported_path.resolve()} | total={len(exported_orders)}")
        return exported_orders, exported_path
    except Exception as exc:
        log_console(f"CSV collect failed: {exc}")
        log_action("system", "export_orders", "error", f"export failed: {exc}")
        raise


