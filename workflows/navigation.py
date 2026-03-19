from __future__ import annotations


def goto_orders(page, config: dict, log_console) -> None:
    order_url = str(config.get("auth", {}).get("order_url", "")).strip()
    if not order_url:
        base_url = str(config.get("base_url", "")).rstrip("/")
        order_url = f"{base_url}/#/order"

    log_console(f"[NAV] Open order page: {order_url}")
    page.goto(order_url)
    page.wait_for_load_state("domcontentloaded")
    # Wait for the order table to render (Angular components finish initializing).
    # "networkidle" is too slow on SPAs that continuously poll the API.
    table_load_ms = int(config.get("timeouts", {}).get("table_load", 5000))
    try:
        page.wait_for_selector("table tbody tr, tbody tr", state="visible", timeout=table_load_ms)
    except Exception:
        log_console(f"[NAV] Warning: order table rows not visible after {table_load_ms}ms, proceeding anyway")
    log_console(f"[NAV] Order page loaded: {page.url}")

