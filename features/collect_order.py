from __future__ import annotations

from pathlib import Path
from typing import Callable

from app.bot_config import BotConfig
from app.order_page import OrderPage
from app.store import make_csv_path, OrderCsvWriter


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
    price_code_mapping: dict[str, int | None] | None = None,
    tag_1_2_only: bool = False,
) -> tuple[int, Path | None]:
    try:
        max_records = bot_config.test_max_collect_records if bot_config else None
        csv_path = make_csv_path(campaign_label, output_path=csv_output_path)

        log_console(f"Single-pass collect+enrich (cap={max_records or 'unlimited'})")
        log_console(f"CSV: {csv_path.resolve()}")

        with OrderCsvWriter(csv_path) as csv_writer:
            processed, action_count, error_count = order_page.collect_and_enrich_single_pass(
                csv_writer=csv_writer,
                max_records=max_records,
                data_dir=data_dir,
                campaign_label=campaign_label,
                price_code_mapping=price_code_mapping,
                tag_1_2_only=tag_1_2_only,
            )

        total = csv_writer.count
        log_console(
            f"Done | processed={processed} actioned={action_count} "
            f"error={error_count} csv_rows={total}"
        )
        log_action("system", "export_orders", "ok", f"rows={total}")
        return total, csv_path
    except Exception as exc:
        log_console(f"CSV collect failed: {exc}")
        log_action("system", "export_orders", "error", f"export failed: {exc}")
        raise

