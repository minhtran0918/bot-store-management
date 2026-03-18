from __future__ import annotations
from datetime import datetime
from pathlib import Path
from playwright.sync_api import sync_playwright

from app.auth import capture_and_save_auth_token
from app.login import ensure_login, new_context
from app.order_page import OrderPage
from app.store import log_action
from app.config_loader import load_config
from app.cli_helpers import (
    FEATURE_COLLECT_ORDER,
    FEATURE_CONFIRM_ORDER,
    prompt_campaign_label,
    prompt_csv_output_path,
    prompt_existing_csv_required,
    prompt_feature_run,
)
from app.cli_menu import show_banner, show_summary
from features.confirm_order import (
    load_order_codes_from_csv,
    run_confirm_order_from_csv,
    set_confirm_reset_table_view,
)
from features.collect_order import run_collect_order_flow
from workflows.navigation import goto_orders
from runtime.process_logger import (
    build_exception_logger,
    flush_stdio,
    keep_browser_open_for_debug,
    log_console,
    safe_close,
)


BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
ERROR_DIR = DATA_DIR / "error"
APP_START_STAMP = datetime.now().strftime("%Y%m%d_%H%M%S")
ERROR_LOG_FILE = ERROR_DIR / f"error_{APP_START_STAMP}.log"
SESSION_FILE = DATA_DIR / "session.json"



def main():
    DATA_DIR.mkdir(exist_ok=True)
    ERROR_DIR.mkdir(parents=True, exist_ok=True)

    show_banner()

    feature_run = prompt_feature_run()

    try:
        campaign_label = prompt_campaign_label()
    except ValueError as exc:
        print(f"Input error: {exc}")
        return

    csv_output_path: Path | None = None
    confirm_input_csv_path: Path | None = None
    confirm_order_codes: list[str] = []

    if feature_run == FEATURE_COLLECT_ORDER:
        csv_output_path = prompt_csv_output_path(DATA_DIR)
    elif feature_run == FEATURE_CONFIRM_ORDER:
        confirm_input_csv_path = prompt_existing_csv_required(DATA_DIR)
        if confirm_input_csv_path is None:
            return
        csv_output_path = confirm_input_csv_path
        try:
            confirm_order_codes = load_order_codes_from_csv(confirm_input_csv_path)
        except Exception as exc:
            print(f"CSV input error: {exc}")
            return
        if not confirm_order_codes:
            print(f"CSV input has no valid order codes: {confirm_input_csv_path}")
            return

    csv_mode = "reuse_existing" if csv_output_path else "create_new"

    try:
        config = load_config(BASE_DIR / "config.yaml")
    except Exception as exc:
        print(f"Config error: {exc}")
        return

    log_exception_trace = build_exception_logger(ERROR_DIR, ERROR_LOG_FILE, log_console)

    selected_csv_text = str(csv_output_path.resolve()) if csv_output_path else "(auto new file)"
    confirm_count_text = str(len(confirm_order_codes)) if feature_run == FEATURE_CONFIRM_ORDER else "n/a"

    summary_items = [
        ("Feature", feature_run),
        ("Campaign", campaign_label),
        ("CSV", selected_csv_text),
    ]
    if feature_run == FEATURE_CONFIRM_ORDER:
        summary_items.append(("Orders", confirm_count_text))
    show_summary(summary_items)

    log_console("=" * 80)
    log_console(
        f"[CLI] Selected options | feature={feature_run} | campaign='{campaign_label}' "
        f"| csv_mode={csv_mode} | csv_path={selected_csv_text} | confirm_orders={confirm_count_text}"
    )
    log_console("[START] Begin automation process")

    with sync_playwright() as p:
        browser = None
        context = None
        page = None
        interrupted = False
        try:
            browser = p.chromium.launch(headless=bool(config.get("headless", False)), slow_mo=200)
            context = new_context(browser, SESSION_FILE)
            page = context.new_page()
            order_page = OrderPage(page)

            if not ensure_login(context, page, config, base_dir=BASE_DIR, session_file=SESSION_FILE, log_console=log_console):
                log_action("auth", "login", "error", "timeout waiting manual login")
                keep_browser_open_for_debug(page, config, "Login timed out", log_console, log_exception_trace)
                return

            capture_and_save_auth_token(page, config, base_dir=BASE_DIR, log_action=log_action)
            target_order_url = str(config.get("auth", {}).get("order_url", "")).strip() or f"{str(config.get('base_url', '')).rstrip('/')}/#/order"
            if not page.url.startswith(target_order_url):
                goto_orders(page, config, log_console)

            log_action("system", "feature", "ok", feature_run)

            if feature_run in (FEATURE_COLLECT_ORDER, FEATURE_CONFIRM_ORDER):
                try:
                    before_rows = order_page.all_rows().count()
                    log_console(f"[FILTER] Rows before applying campaign filter: {before_rows}")
                    order_page.apply_campaign_filter(campaign_label)
                    log_action("system", "campaign_filter", "ok", campaign_label)
                    after_rows = order_page.filtered_order_rows().count()
                    log_console(f"[FILTER] Rows right after filter apply: {after_rows}")
                except Exception as exc:
                    log_action("system", "campaign_filter", "warning", f"failed to apply '{campaign_label}': {exc}")

            if feature_run == FEATURE_COLLECT_ORDER:
                run_collect_order_flow(
                    order_page=order_page,
                    campaign_label=campaign_label,
                    log_console=log_console,
                    log_action=log_action,
                    csv_output_path=csv_output_path,
                    data_dir=DATA_DIR,
                )

            if feature_run == FEATURE_CONFIRM_ORDER:
                log_console(f"[CONFIRM] Input CSV selected: {confirm_input_csv_path}")
                set_confirm_reset_table_view(lambda: order_page.apply_campaign_filter(campaign_label))
                run_confirm_order_from_csv(
                    order_page=order_page,
                    page=page,
                    order_codes=confirm_order_codes,
                    error_dir=ERROR_DIR,
                    error_log_file=ERROR_LOG_FILE,
                    log_console=log_console,
                    log_action=log_action,
                    log_exception_trace=log_exception_trace,
                )

            if interrupted:
                log_console("[INTERRUPT] Run stopped early by user.")
            else:
                keep_browser_open_for_debug(page, config, "Run completed successfully", log_console, log_exception_trace)

        except KeyboardInterrupt:
            interrupted = True
            log_console("[INTERRUPT] Stop requested by user (Ctrl+C). Shutting down cleanly...")
        except Exception as exc:
            log_exception_trace("main_run_failed", exc)
            keep_browser_open_for_debug(page, config, "Run failed", log_console, log_exception_trace)
        finally:
            try:
                set_confirm_reset_table_view(None)
                try:
                    if context is not None:
                        context.storage_state(path=str(SESSION_FILE))
                except Exception as exc:
                    log_console(f"[SHUTDOWN] Skip saving session state: {exc}")

                safe_close(context, "browser context", log_console)
                safe_close(browser, "browser", log_console)
            except KeyboardInterrupt:
                log_console("[INTERRUPT] Forced stop during cleanup (Ctrl+C x2). Exiting.")
            finally:
                log_console("[SHUTDOWN] Process ended.")
                flush_stdio()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log_console("[INTERRUPT] Process killed by user.")
        flush_stdio()