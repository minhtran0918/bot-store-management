from __future__ import annotations

from datetime import datetime

from app.order_page import OrderPage
from app.rules import should_skip, decide_action
from app.store import get_order_state, log_action, text_hash, upsert_order_state


def _close_modal_safely(order_page: OrderPage) -> None:
    try:
        order_page.close_button().click(timeout=2000)
    except Exception:
        pass


def is_product_match(note: str, config: dict) -> bool:
    keywords = config.get("keywords", {}).get("match_product", [])
    if not isinstance(keywords, list) or not keywords:
        return False

    note_l = (note or "").lower()
    for kw in keywords:
        kw_l = str(kw or "").strip().lower()
        if kw_l and kw_l in note_l:
            return True
    return False


def process_one(order_page: OrderPage, row, config: dict) -> dict[str, str]:
    order_code = order_page.order_code_in_row(row)

    order_page.open_edit_modal_by_row(row)
    order_page.wait_modal(timeout=5000)

    note = order_page.read_note()
    address = order_page.read_address()
    address_status = "have address" if (address or "").strip() else "empty address"
    match_product = "true" if is_product_match(note, config) else "false"
    progress = {
        "order_code": order_code,
        "Address Status": address_status,
        "Note": note,
        "Match Product": match_product,
        "Decision": "",
    }

    existing = get_order_state(order_code)
    if should_skip(existing, note, address):
        progress["Decision"] = "skip_same_content"
        log_action(order_code, "skip", "ok", "same content already processed")
        _close_modal_safely(order_page)
        return progress

    pickup_keywords = config.get("keywords", {}).get("pickup", [])
    decision = decide_action(note, address, existing, pickup_keywords=pickup_keywords)

    if decision == "pickup":
        progress["Decision"] = decision
        upsert_order_state(
            order_code,
            {
                "state": "pickup",
                "note_hash": text_hash(note),
                "address_hash": text_hash(address),
                "last_action_at": datetime.now().isoformat(),
            },
        )
        log_action(order_code, "pickup", "ok", "skip asking address")
        _close_modal_safely(order_page)
        return progress

    if decision == "send_ask_address":
        progress["Decision"] = decision
        ask_address_msg = config.get("messages", {}).get("ask_address", "")
        order_page.message_box().fill(ask_address_msg)
        order_page.send_button().click()
        order_page.confirmation_image_button().click()
        upsert_order_state(
            order_code,
            {
                "state": "asked_address",
                "note_hash": text_hash(note),
                "address_hash": text_hash(address),
                "last_action_at": datetime.now().isoformat(),
            },
        )
        log_action(order_code, "send_ask_address", "ok", "sent text + image")
        _close_modal_safely(order_page)
        return progress

    if decision == "skip_already_asked":
        progress["Decision"] = decision
        log_action(order_code, "skip", "ok", "asked address recently; waiting")
        _close_modal_safely(order_page)
        return progress

    if decision == "mark_done":
        progress["Decision"] = decision
        upsert_order_state(
            order_code,
            {
                "state": "done",
                "note_hash": text_hash(note),
                "address_hash": text_hash(address),
                "last_action_at": datetime.now().isoformat(),
            },
        )
        log_action(order_code, "mark_done", "ok", "address exists")
        _close_modal_safely(order_page)
        return progress

    progress["Decision"] = f"unknown:{decision}"
    log_action(order_code, "skip", "warning", f"unknown decision={decision}")
    _close_modal_safely(order_page)
    return progress

