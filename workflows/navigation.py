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
    try:
        page.wait_for_selector("table tbody tr, tbody tr", state="visible", timeout=8000)
    except Exception:
        pass
    log_console(f"[NAV] Order page loaded: {page.url}")

