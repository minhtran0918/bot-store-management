from __future__ import annotations

from pathlib import Path
from typing import Callable

from app.bot_config import BotConfig
from app.order_page import OrderPage
from app.store import save_filtered_orders


LogActionFn = Callable[[str, str, str, str], None]
LogConsoleFn = Callable[[str], None]


def run_collect_order_flow(
    order_page: OrderPage,
    campaign_label: str,
    log_console: LogConsoleFn,
    log_action: LogActionFn,
    csv_output_path: Path | None = None,
    data_dir: Path | None = None,
    bot_config: BotConfig | None = None,
) -> tuple[list[dict[str, str]], Path | None]:
    try:
        max_records = bot_config.test_max_collect_records if bot_config else None
        # Collect qualifying orders (no tag / 1.2 / 2.2 + Nháp + Bình thường)
        log_console(f"Collecting qualifying orders... (cap={max_records or 'unlimited'})")
        exported_orders = order_page.read_filtered_orders(max_records=max_records)
        log_console(f"Collected {len(exported_orders)} qualifying orders")

        if exported_orders:
            # Go back to page 1 before enriching
            log_console("Go to page 1, start enriching orders...")
            order_page.go_to_first_page()

            processed, action_count, error_count = order_page.enrich_collected_rows(exported_orders, data_dir=data_dir, campaign_label=campaign_label)
            log_console(
                f"Enrich done | processed={processed} actioned={action_count} "
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

