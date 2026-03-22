from __future__ import annotations
from datetime import datetime
from pathlib import Path
from playwright.sync_api import sync_playwright

from app.auth import capture_and_save_auth_token
from app.bot_config import BotConfig
from app.login import ensure_login, new_context
from app.order_page import OrderPage
from app.store import log_action
from app.config_loader import load_config
from app.cli_helpers import (
    FEATURE_CONFIRM_ORDER,
    FEATURE_ADD_PRODUCT,
    FEATURE_BROADCAST_ORDER,
    prompt_campaign_label,
    prompt_price_code_mapping,
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
    suppress_playwright_shutdown_noise,
)


BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
ERROR_DIR = DATA_DIR / "error"
APP_START_STAMP = datetime.now().strftime("%Y%m%d_%H%M%S")
ERROR_LOG_FILE = ERROR_DIR / f"error_{APP_START_STAMP}.log"
SESSION_FILE = DATA_DIR / "session.json"



def main():
    suppress_playwright_shutdown_noise()
    DATA_DIR.mkdir(exist_ok=True)
    ERROR_DIR.mkdir(parents=True, exist_ok=True)

    show_banner()

    feature_run = prompt_feature_run()

    if feature_run == FEATURE_BROADCAST_ORDER:
        try:
            config = load_config(BASE_DIR / "config.yaml")
        except Exception as exc:
            log_console(f"Config error: {exc}")
            return
        from features.broadcast_order.server import run_broadcast_server
        run_broadcast_server(config, BASE_DIR, log_console)
        return

    try:
        campaign_label = prompt_campaign_label()
    except ValueError as exc:
        log_console(f"Input error: {exc}")
        return

    csv_output_path: Path | None = None
    confirm_input_csv_path: Path | None = None
    confirm_order_codes: list[str] = []
    price_code_mapping: dict[str, int | None] = {}

    if feature_run == FEATURE_CONFIRM_ORDER:
        price_code_mapping = prompt_price_code_mapping()
    elif feature_run == FEATURE_ADD_PRODUCT:
        confirm_input_csv_path = prompt_existing_csv_required(DATA_DIR)
        if confirm_input_csv_path is None:
            return
        csv_output_path = confirm_input_csv_path
        try:
            confirm_order_codes = load_order_codes_from_csv(confirm_input_csv_path)
        except Exception as exc:
            log_console(f"CSV input error: {exc}")
            return
        if not confirm_order_codes:
            log_console(f"CSV input has no valid order codes: {confirm_input_csv_path}")
            return

    try:
        config = load_config(BASE_DIR / "config.yaml")
    except Exception as exc:
        log_console(f"Config error: {exc}")
        return

    log_exception_trace = build_exception_logger(ERROR_DIR, ERROR_LOG_FILE, log_console)

    confirm_count_text = str(len(confirm_order_codes)) if feature_run == FEATURE_ADD_PRODUCT else "n/a"
    active_codes = {k: v for k, v in price_code_mapping.items() if v is not None}
    price_map_text = ", ".join(f"{k}={v}" for k, v in active_codes.items()) if active_codes else "(none)"

    summary_items = [
        ("Feature", feature_run),
        ("Campaign", campaign_label),
    ]
    if feature_run == FEATURE_CONFIRM_ORDER:
        summary_items.append(("Price Codes", price_map_text))
    if feature_run == FEATURE_ADD_PRODUCT:
        summary_items.append(("Orders", confirm_count_text))
    show_summary(summary_items)

    log_console("=" * 80)
    log_console(
        f"[CLI] Selected options | feature={feature_run} | campaign='{campaign_label}' "
        f"| price_codes={price_map_text} | confirm_orders={confirm_count_text}"
    )
    log_console("[START] Begin automation process")

    with sync_playwright() as p:
        browser = None
        context = None
        page = None
        interrupted = False
        try:
            browser = p.chromium.launch(
                headless=bool(config.get("headless", False)),
                slow_mo=200,
                args=["--force-device-scale-factor=1"],
            )
            context = new_context(browser, SESSION_FILE)
            page = context.new_page()

            # Detect Windows display scaling and adjust window to fill the screen.
            # At 150% scaling, screen.availWidth returns CSS pixels (e.g. 1280 instead of 1920).
            # We use these CSS values directly since Playwright operates in CSS pixels.
            screen_info = page.evaluate("""() => {
                const dpr = window.devicePixelRatio || 1;
                const w = screen.availWidth;
                const h = screen.availHeight;
                window.moveTo(0, 0);
                window.resizeTo(w, h);
                return { width: w, height: h, dpr: dpr };
            }""")
            log_console(f"[SCREEN] {screen_info['width']}x{screen_info['height']} (scale={screen_info['dpr']}x)")
            bot_config = BotConfig(config)
            order_page = OrderPage(page, bot_config)

            if not ensure_login(context, page, config, base_dir=BASE_DIR, session_file=SESSION_FILE, log_console=log_console):
                log_action("auth", "login", "error", "timeout waiting manual login")
                keep_browser_open_for_debug(page, config, "Login timed out", log_console, log_exception_trace)
                return

            capture_and_save_auth_token(page, config, base_dir=BASE_DIR, log_action=log_action)
            target_order_url = str(config.get("auth", {}).get("order_url", "")).strip() or f"{str(config.get('base_url', '')).rstrip('/')}/#/order"
            if not page.url.startswith(target_order_url):
                goto_orders(page, config, log_console)

            log_action("system", "feature", "ok", feature_run)

            if feature_run in (FEATURE_CONFIRM_ORDER, FEATURE_ADD_PRODUCT):
                try:
                    before_rows = order_page.all_rows().count()
                    log_console(f"[FILTER] Rows before applying campaign filter: {before_rows}")
                    order_page.apply_campaign_filter(campaign_label)
                    log_action("system", "campaign_filter", "ok", campaign_label)
                    after_rows = order_page.filtered_order_rows().count()
                    log_console(f"[FILTER] Rows right after filter apply: {after_rows}")
                except Exception as exc:
                    log_action("system", "campaign_filter", "warning", f"failed to apply '{campaign_label}': {exc}")

            if feature_run == FEATURE_CONFIRM_ORDER:
                run_collect_order_flow(
                    order_page=order_page,
                    campaign_label=campaign_label,
                    log_console=log_console,
                    log_action=log_action,
                    csv_output_path=csv_output_path,
                    data_dir=DATA_DIR,
                    bot_config=bot_config,
                    price_code_mapping=price_code_mapping,
                )

            if feature_run == FEATURE_ADD_PRODUCT:
                log_console(f"[ADD_PRODUCT] Input CSV selected: {confirm_input_csv_path}")
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