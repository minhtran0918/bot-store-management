from __future__ import annotations

import io
import math
import random
import shutil
import time
import traceback
import unicodedata
from collections import Counter
from datetime import datetime
from pathlib import Path
from playwright.sync_api import Page, Locator
from PIL import Image
import re

from .constants import (
    ERR, TAG_ONLY_TAGS, OOS_TAGS, STATUS_TO_TAG,
    TAG_0, TAG_1, TAG_1_1, TAG_1_2, TAG_1_3, TAG_1_4,
    TAG_2, TAG_2_1, TAG_2_2, TAG_2_3, TAG_2_4,
    HAVE_ADDR_LOW_SP, HAVE_ADDR_HIGH_SP, HAVE_ADDR_NO_SP,
    HAVE_ADDR_NO_PROD, HAVE_ADDR_OOS,
    NO_ADDR_LOW_SP, NO_ADDR_HIGH_SP, NO_ADDR_NO_SP,
    NO_ADDR_NO_PROD, NO_ADDR_OOS,
)
from .bot_config import BotConfig
from .note_parser import extract_note_prices

from runtime.process_logger import log_console as _log


_STROKE_MAP = str.maketrans({"Đ": "D", "đ": "d"})


def _remove_diacritics(text: str) -> str:
    """Remove Vietnamese diacritics and convert to ASCII-safe filename token."""
    # Đ/đ don't decompose under NFKD so must be replaced explicitly first
    text = text.translate(_STROKE_MAP)
    nfkd = unicodedata.normalize("NFKD", text)
    ascii_str = "".join(ch for ch in nfkd if not unicodedata.combining(ch))
    # Replace non-alphanumeric (except space/dash/underscore) with nothing
    cleaned = re.sub(r"[^\w\s\-]", "", ascii_str)
    # Collapse whitespace to underscore
    cleaned = re.sub(r"\s+", "_", cleaned).strip("_")
    return cleaned


def _normalize_customer_tag_label(text: str) -> str:
    """Normalize customer-tag labels so modal text can match config values reliably."""
    normalized = re.sub(r"\s+", " ", (text or "").strip()).casefold()
    return re.sub(r"^\d+\s*", "", normalized)


def _resolve_product_match_tag(
    have_address: bool,
    total_products: int,
    exact_match: bool,
) -> str:
    """Resolve tag from address presence and exact note/product match state."""
    if exact_match:
        status = HAVE_ADDR_HIGH_SP if have_address else NO_ADDR_HIGH_SP
        if total_products <= 3:
            status = HAVE_ADDR_LOW_SP if have_address else NO_ADDR_LOW_SP
    else:
        status = HAVE_ADDR_NO_SP if have_address else NO_ADDR_NO_SP
    return STATUS_TO_TAG[status]


def _build_match_label(matched_count: int, total_products: int, resolved_tag: str) -> str:
    """Build a human-readable match summary for logs/CSV."""
    if total_products <= 0:
        return "NO PRODUCT (0/0)"
    if resolved_tag in (TAG_1_4, TAG_2_4):
        return f"OOS ({matched_count}/{total_products})"
    if resolved_tag in (TAG_1_2, TAG_2_2):
        if matched_count == 0:
            return f"NO MATCH (0/{total_products})"
        return f"PARTIAL ({matched_count}/{total_products})"
    if total_products >= 4:
        return f"FULL 4+ ({matched_count}/{total_products})"
    return f"FULL 1-3 ({matched_count}/{total_products})"


def _should_skip_for_tag_1_2_only(tag_1_2_only: bool, resolved_tag: str) -> bool:
    """When enabled, only TAG 1 and TAG 2 are actionable."""
    return tag_1_2_only and resolved_tag not in (TAG_1, TAG_2)

class OrderPage:
    def __init__(self, page: Page, bot_config: BotConfig | None = None):
        self.page = page
        self._cfg = bot_config or BotConfig({})

    def _first(self, selectors: list[str]) -> Locator:
        for selector in selectors:
            locator = self.page.locator(selector).first
            if locator.count() > 0:
                return locator
        return self.page.locator(selectors[-1]).first

    def _all(self, selectors: list[str]) -> Locator:
        for selector in selectors:
            locator = self.page.locator(selector)
            if locator.count() > 0:
                return locator
        return self.page.locator(selectors[-1])

    def all_rows(self) -> Locator:
        return self._all([
            "table tbody tr",
            "tbody tr",
        ])

    def filtered_order_rows(self) -> Locator:
        return self._all([
            "table tbody tr.tds-table-row",
            "tbody tr.tds-table-row",
            "table tbody tr",
            "tbody tr",
        ])

    def row_by_code(self, order_code: str) -> Locator:
        return self.all_rows().filter(has_text=order_code).first

    def row_by_index(self, index: int) -> Locator:
        return self.all_rows().nth(index)

    def order_code_in_row(self, row: Locator) -> str:
        order_cell = row.locator("td").nth(4)
        code_span = order_cell.locator("span").first
        if code_span.count() > 0:
            return code_span.inner_text().strip()
        return order_cell.inner_text().strip()

    def edit_button_in_row(self, order_code: str) -> Locator:
        row = self.row_by_code(order_code)
        return row.locator("button[title='Sửa'], [aria-label='Sửa'], button, a").first

    def open_edit_modal_by_row(self, row: Locator) -> None:
        row.locator(
            "button[tds-tooltip='Chỉnh sửa'], button:has(i.tdsi-edit-fill), button[title='Sửa'], [aria-label='Sửa']"
        ).first.click()

    def modal(self) -> Locator:
        return self._first([
            "div[role='dialog']:has-text('Sửa đơn hàng')",
            "div[role='dialog']",
            "text=Sửa đơn hàng",
        ])

    def wait_modal(self, timeout: float | None = None) -> None:
        t = int(timeout) if timeout is not None else self._cfg.modal_timeout
        self.modal().wait_for(timeout=t)
        # Wait for modal content to fully load (collapse sections with product info)
        try:
            self.page.locator("div.tds-collapse-content-box").first.wait_for(state="attached", timeout=t)
            self.page.wait_for_timeout(self._cfg.panel_open_ms)
        except Exception:
            _log("[MODAL] collapse-content-box did not appear within timeout, proceeding anyway")

    def _verify_modal_order_code(self, expected_code: str) -> bool:
        """Verify the modal is showing the correct order by checking the header span."""
        try:
            header = self.page.locator(
                "span.text-primary-1.font-semibold.text-title-1"
            ).first
            if header.count() == 0:
                _log(f"  [!] Modal header not found, cannot verify order code")
                return False
            modal_code = header.inner_text().strip()
            if modal_code == expected_code:
                return True
            _log(f"  [!] Modal mismatch: expected={expected_code} got={modal_code}")
            return False
        except Exception as exc:
            _log(f"  [!] Modal verify error: {exc}")
            return False

    def address_input(self) -> Locator:
        return self._first([
            "label:has-text('Địa chỉ khách hàng') + div input",
            "input[placeholder*='Địa chỉ']",
            "input[name*='address']",
            "input",
        ])

    def note_textarea(self) -> Locator:
        return self._first([
            "textarea[placeholder*='Ghi chú']",
            "textarea[name*='note']",
            "textarea",
        ])

    def read_note(self) -> str:
        return self.note_textarea().input_value().strip()

    def read_address(self) -> str:
        return self.address_input().input_value().strip()

    def save_button(self) -> Locator:
        return self.page.get_by_role("button", name="Lưu")

    def close_button(self) -> Locator:
        return self._first([
            "button:has-text('Đóng')",
            "button:has-text('Close')",
            "button[aria-label='Close']",
        ])

    def message_button_in_row(self, row: Locator) -> Locator:
        return row.locator(
            "a[tds-tooltip='Gửi tin nhắn'], a:has(i.tdsi-messenger-fill)"
        ).first

    def message_box(self) -> Locator:
        return self._first([
            "textarea[data-placeholder*='Nhập nội dung tin nhắn']",
            "textarea[placeholder*='Nhập nội dung tin nhắn']",
            "textarea[placeholder*='Tin nhắn']",
            "textarea[placeholder*='Nhập nội dung']",
            "textarea",
        ])

    def send_message_button(self) -> Locator:
        return self._first([
            "button[tds-button][color='primary']:has(i.tdsi-send-fill)",
            "button.tds-button-primary:has(i.tdsi-send-fill)",
            "button.\\!rounded-full:has(i.tdsi-send-fill)",
            "button:has(i.tdsi-send-fill)",
        ])

    def send_button(self) -> Locator:
        return self._first([
            "button:has-text('Gửi')",
            "button:has-text('Send')",
        ])

    def _attach_images_in_chat(self, image_paths: list[Path], order_code: str) -> bool:
        """Attach all images to the chat input (does not send)."""
        try:
            image_btn = self._first([
                "a[tooltiptitle='Gửi ảnh']",
                "a[title='Hình ảnh']",
                "a:has(div.tdsi-image-line)",
            ])
            # Scroll into view in case the toolbar is off-screen due to window resize
            image_btn.scroll_into_view_if_needed(timeout=self._cfg.click_timeout)
            # Small delay before clicking image button to let panel fully settle
            self.page.wait_for_timeout(1000)
            with self.page.expect_file_chooser() as fc_info:
                image_btn.click(timeout=self._cfg.click_timeout)
            file_chooser = fc_info.value
            file_chooser.set_files([str(p) for p in image_paths])
            # Scale wait with image count so all thumbnails have time to render
            self.page.wait_for_timeout(self._cfg.image_attach_ms * len(image_paths))
            return True
        except Exception as exc:
            _log(f"  [!] Attach images failed: {exc}")
            _log(f"  [!] Stack trace:\n{traceback.format_exc()}")
            return False

    def _wait_panel_ready(self) -> None:
        """Wait for message panel to finish loading (spinner gone), then focus textarea."""
        self.page.wait_for_timeout(self._cfg.panel_open_ms)
        try:
            self.page.wait_for_selector("tds-spin", state="hidden", timeout=self._cfg.spinner_hide_ms)
        except Exception:
            pass
        self.message_box().click(timeout=self._cfg.click_timeout)

    def _send_batched_in_open_panel(self, message: str, img_list: list[Path], order_code: str) -> None:
        """Send images + optional text in an already-open panel, handling batching."""
        if len(img_list) > 3:
            batch_size = min(math.ceil(len(img_list) / 2), 3)
            batches = [img_list[i:i + batch_size] for i in range(0, len(img_list), batch_size)]
            sizes = "+".join(str(len(b)) for b in batches)
            _log(f"  SEND BATCHED: {len(img_list)} images → {sizes} (batch_size={batch_size})")
            for i, batch in enumerate(batches):
                batch_msg = message if i == len(batches) - 1 else ""
                self._send_in_panel(batch_msg, batch, order_code)
        else:
            self._send_in_panel(message, img_list or None, order_code)

    def _has_pending_content_in_panel(self) -> bool:
        """Check if the message panel has content ready to send (text or images)."""
        # Check for image attachment indicator: "Ảnh X/30"
        try:
            img_indicator = self.page.locator("span:has-text('/30')").first
            if img_indicator.count() > 0:
                return True
        except Exception:
            pass
        # Check if textarea has text
        try:
            textarea = self.message_box()
            if textarea.count() > 0:
                val = textarea.input_value(timeout=1000)
                if val and val.strip():
                    return True
        except Exception:
            pass
        return False

    def _click_send_button_reliable(self, order_code: str) -> None:
        """Click the send button multiple times to ensure delivery."""
        max_attempts = 2
        for attempt in range(1, max_attempts + 1):
            try:
                send_btn = self.send_message_button()
                send_btn.scroll_into_view_if_needed(timeout=self._cfg.click_timeout)
                self.page.wait_for_timeout(200)
                try:
                    send_btn.click(timeout=self._cfg.click_timeout)
                except Exception:
                    send_btn.click(timeout=self._cfg.click_timeout, force=True)
                self.page.wait_for_timeout(500)
                if not self._has_pending_content_in_panel():
                    # Content sent — click once more as safety tap
                    try:
                        send_btn = self.send_message_button()
                        send_btn.click(timeout=self._cfg.click_timeout, force=True)
                    except Exception:
                        pass  # button may be gone/disabled after successful send
                    return
                _log(f"  [!] Send attempt {attempt}/{max_attempts}: content still in panel, retrying...")
            except Exception as exc:
                _log(f"  [!] Send attempt {attempt}/{max_attempts} error: {exc}")
            if attempt < max_attempts:
                self.page.wait_for_timeout(500)
        _log(f"  [!] Send button: all {max_attempts} attempts done for {order_code}")

    def _send_in_panel(self, message: str, image_paths: list[Path] | None, order_code: str) -> None:
        """Send one message (images + text) within an already-open message panel."""
        img_count = len(image_paths) if image_paths else 0
        # Fill text FIRST so spinner from image upload doesn't block textarea interaction
        if message:
            msg_box = self.message_box()
            msg_box.click(timeout=self._cfg.click_timeout)
            msg_box.fill(message)
            self.page.wait_for_timeout(self._cfg.text_fill_ms)
        if image_paths:
            self._attach_images_in_chat(image_paths, order_code)
            # Wait for the upload spinner to disappear before sending
            try:
                self.page.wait_for_selector(
                    "tds-spin", state="hidden", timeout=self._cfg.spinner_hide_ms
                )
            except Exception:
                pass  # spinner may already be gone
            # Verify images are attached by checking "Ảnh X/30" indicator
            try:
                self.page.wait_for_selector(
                    "span:has-text('/30')", state="visible", timeout=self._cfg.spinner_hide_ms
                )
                _log(f"  IMG READY: images attached, indicator visible")
            except Exception:
                _log(f"  [!] IMG indicator '/30' not found, proceeding anyway")
        errors_before = self._count_send_errors()
        self._click_send_button_reliable(order_code)
        send_delay = self._cfg.send_post_base_ms + self._cfg.send_post_per_image_ms * img_count
        self.page.wait_for_timeout(send_delay)
        if self._check_message_send_error(errors_before):
            _log("  [!] Inbox message send error detected")
            try:
                error_dir = Path(__file__).parent.parent / "data" / "error"
                error_dir.mkdir(parents=True, exist_ok=True)
                ts = datetime.now().strftime("%H%M%S")
                sc_path = error_dir / f"send_error_{order_code}_{ts}.png"
                self.page.screenshot(path=str(sc_path))
                _log(f"  [!] Screenshot: {sc_path}")
            except Exception as sc_exc:
                _log(f"  [!] Screenshot failed: {sc_exc}")
        msg_short = message[:30] + "..." if len(message) > 30 else message
        _log(f"  SEND: text='{msg_short}' | images={img_count}")

    def send_message_to_order(
        self, row: Locator, order_code: str, message: str,
        image_paths: list[Path] | None = None,
    ) -> bool:
        try:
            self._dismiss_notifications()
            self.message_button_in_row(row).click(timeout=self._cfg.click_timeout, force=True)
            self._wait_panel_ready()
            self._send_batched_in_open_panel(message, image_paths or [], order_code)
            self.page.keyboard.press("Escape")
            self.page.wait_for_timeout(self._cfg.escape_close_ms)
            return True
        except Exception as exc:
            _log(f"  [!] Send message failed: {exc}")
            _log(f"  [!] Stack trace:\n{traceback.format_exc()}")
            return False

    def reply_comment_to_order(self, row: Locator, order_code: str, campaign_label: str = "") -> bool:
        """Open message panel, reply to first comment of campaign-date post, close panel."""
        try:
            self._dismiss_notifications()
            self.message_button_in_row(row).click(timeout=self._cfg.click_timeout)
            self.page.wait_for_timeout(self._cfg.panel_open_ms)

            partner_name = self._read_partner_name()
            ok = self._reply_comment_fallback(partner_name, campaign_label=campaign_label)

            self.page.keyboard.press("Escape")
            self.page.wait_for_timeout(self._cfg.escape_close_ms)

            if ok:
                _log(f"  COMMENT REPLY OK: order={order_code}")
            else:
                _log(f"  [!] COMMENT REPLY FAILED: order={order_code}")
            return ok
        except Exception as exc:
            _log(f"  [!] Comment reply error: {exc}")
            try:
                self.page.keyboard.press("Escape")
            except Exception:
                pass
            return False

    def confirmation_image_button(self) -> Locator:
        return self._first([
            "text=Ảnh chốt",
            "text=Xác nhận",
            "button:has-text('Ảnh')",
        ])

    def filter_button(self) -> Locator:
        return self._first([
            "button[tooltiptitle='Lọc dữ liệu']",
            "button:has(i.tdsi-filter-1-fill)",
            "button:has-text('Lọc')",
        ])

    def campaign_select(self) -> Locator:
        return self._first([
            "tds-select[placeholder='Chọn chiến dịch'].tds-select-open .tds-select-selector",
            "tds-select[placeholder='Chọn chiến dịch'].tds-select-focused .tds-select-selector",
            "tds-select[placeholder='Chọn chiến dịch'] .tds-select-selector",
            "tds-select[placeholder='Chọn chiến dịch']",
            "text=Chọn chiến dịch",
        ])

    def campaign_search_input(self) -> Locator:
        return self._first([
            "tds-select[placeholder='Chọn chiến dịch'].tds-select-open tds-select-search input.tds-select-search-input:visible",
            "tds-select[placeholder='Chọn chiến dịch'].tds-select-focused tds-select-search input.tds-select-search-input:visible",
            "tds-select[placeholder='Chọn chiến dịch'] tds-select-search input.tds-select-search-input:visible",
            "input[id^='tds-select-']",
        ])

    def apply_filter_button(self) -> Locator:
        return self._first([
            "button:has-text('Áp dụng')",
            "button:has-text('Apply')",
        ])

    def pagination_total_count(self) -> int | None:
        locator = self._first([
            "span.tds-tabs-filter-count",
            ".tds-tabs-filter-count",
        ])
        if locator.count() == 0:
            return None
        try:
            raw = locator.inner_text().strip()
        except Exception:
            return None
        digits = re.sub(r"\D+", "", raw)
        return int(digits) if digits else None

    def pagination_next_button(self) -> Locator:
        return self._first([
            "button.tds-pagination-item-link:has(i.tdsi-arrow-right-fill)",
            "button:has(i.tdsi-arrow-right-fill)",
        ])

    def pagination_next_disabled(self) -> bool:
        btn = self.pagination_next_button()
        if btn.count() == 0:
            return True
        disabled_attr = btn.get_attribute("disabled")
        aria_disabled = btn.get_attribute("aria-disabled")
        classes = btn.get_attribute("class") or ""
        return (
            disabled_attr is not None
            or (aria_disabled or "").strip().lower() == "true"
            or "disabled" in classes.lower()
        )

    def go_to_first_page(self) -> None:
        """Click page 1 in pagination to return to the first page."""
        try:
            page1 = self.page.locator(
                "li.tds-pagination-item a:text-is('1'), "
                "li.tds-pagination-item:first-child a"
            ).first
            if page1.count() > 0:
                # Check if already on page 1
                parent = page1.locator("xpath=ancestor::li[1]")
                classes = (parent.get_attribute("class") or "") if parent.count() > 0 else ""
                if "tds-pagination-item-active" in classes:
                    _log("[PAGE] Already on page 1")
                    return
                page1.click(timeout=self._cfg.click_timeout)
                self.page.wait_for_timeout(self._cfg.panel_open_ms)
                _log("[PAGE] Navigated to page 1")
            else:
                _log("[PAGE] Page 1 button not found, may be single-page")
        except Exception as exc:
            _log(f"[PAGE] Go to page 1 failed: {exc}")

    def _first_row_marker(self, rows: Locator) -> str:
        if rows.count() == 0:
            return ""
        first_row = rows.nth(0)
        cells = first_row.locator("td")
        if cells.count() < 5:
            return ""
        code_span = cells.nth(4).locator("span").first
        if code_span.count() > 0:
            return code_span.inner_text().strip()
        return cells.nth(4).inner_text().strip()

    def _wait_for_rows_on_page(self, timeout_attempts: int = 12) -> tuple[Locator, int]:
        rows = self.filtered_order_rows()
        count = rows.count()
        if count > 0:
            return rows, count

        for attempt in range(1, timeout_attempts + 1):
            self.page.wait_for_timeout(self._cfg.escape_close_ms)
            rows = self.filtered_order_rows()
            count = rows.count()
            _log(f"CSV collect: waiting rows... attempt={attempt}/{timeout_attempts} count={count}")
            if count > 0:
                return rows, count

        rows = self.all_rows()
        return rows, rows.count()

    def _tag_values_in_order_cell(self, order_cell: Locator) -> list[str]:
        raw_tags = [t.strip() for t in order_cell.locator("tds-tag div").all_inner_texts() if t and t.strip()]
        tags: list[str] = []
        for tag in raw_tags:
            if tag not in tags:
                tags.append(tag)
        return tags

    def _extract_price_tokens(self, text: str, price_code_mapping: dict[str, int | None] | None = None) -> list[int]:
        return extract_note_prices(text, price_code_mapping)

    def _extract_product_prices_from_modal(self) -> list[int]:
        prices: list[int] = []

        product_rows = self.page.locator("div.tds-collapse-content-box div.w-full.flex.gap-x-3")
        row_count = product_rows.count()
        for i in range(row_count):
            row_text = product_rows.nth(i).inner_text().strip()
            for raw in re.findall(r"Gi[aá]\s*:\s*([\d.,]+)", row_text, flags=re.IGNORECASE):
                prices.extend(self._extract_price_tokens(raw))

        if prices:
            return prices

        # Fallback selector
        product_texts = self.page.locator("div.tds-collapse-content-box span.text-neutral-1-900.font-semibold").all_inner_texts()
        for t in product_texts:
            prices.extend(self._extract_price_tokens(t))
        return prices

    def _extract_product_image_items_from_modal(self) -> list[tuple[str, str, int]]:
        """Returns list of (url, product_name, price_thousands) for rows that have an image."""
        product_rows = self.page.locator("div.tds-collapse-content-box div.w-full.flex.gap-x-3")
        results: list[tuple[str, str, int]] = []
        for i in range(product_rows.count()):
            row_el = product_rows.nth(i)
            img = row_el.locator("img[tds-image]").first
            if img.count() == 0:
                continue
            src = img.get_attribute("src") or ""
            if not src:
                continue
            if "&img=true" not in src:
                src = src + "&img=true"
            try:
                row_text = row_el.inner_text().strip()
                product_name = row_text.split("\n")[0].strip() if row_text else f"product_{i + 1}"
            except Exception:
                row_text = ""
                product_name = f"product_{i + 1}"
            # Extract first price found in this row
            price = 0
            for raw in re.findall(r"Gi[aá]\s*:\s*([\d.,]+)", row_text, flags=re.IGNORECASE):
                tokens = self._extract_price_tokens(raw)
                if tokens:
                    price = tokens[0]
                    break
            results.append((src, product_name, price))
        return results

    def _download_and_compress_image(self, url: str, save_path: Path, max_kb: int = 100) -> bool:
        try:
            response = self.page.context.request.get(url)
            if response.status != 200:
                _log(f"  [!] Image download failed | status={response.status}")
                return False

            img_bytes = response.body()
            original_kb = len(img_bytes) / 1024
            img = Image.open(io.BytesIO(img_bytes))
            orig_w, orig_h = img.width, img.height
            if img.mode == "RGBA":
                img = img.convert("RGB")

            # Compress by reducing JPEG quality until under max_kb
            quality = 85
            while quality >= 10:
                buf = io.BytesIO()
                img.save(buf, format="JPEG", quality=quality, optimize=True)
                if buf.tell() <= max_kb * 1024:
                    save_path.write_bytes(buf.getvalue())
                    _log(f"  -> {save_path.name} | {orig_w}x{orig_h} | {original_kb:.0f}kb -> {buf.tell() // 1024}kb | q={quality}")
                    return True
                quality -= 10

            # Progressively resize until under max_kb
            cur_w, cur_h = orig_w, orig_h
            cur_img = img
            for _ in range(10):
                current_size = len(buf.getvalue())
                ratio = ((max_kb * 1024) / current_size) ** 0.5 * 0.85
                ratio = min(ratio, 0.8)
                cur_w = max(1, int(cur_w * ratio))
                cur_h = max(1, int(cur_h * ratio))
                cur_img = img.resize((cur_w, cur_h), Image.LANCZOS)
                buf = io.BytesIO()
                cur_img.save(buf, format="JPEG", quality=40, optimize=True)
                if buf.tell() <= max_kb * 1024:
                    break

            save_path.write_bytes(buf.getvalue())
            scale_pct = (cur_w / orig_w) * 100
            _log(
                f"  -> {save_path.name} | {orig_w}x{orig_h} -> {cur_w}x{cur_h} ({scale_pct:.0f}%) "
                f"| {original_kb:.0f}kb -> {buf.tell() // 1024}kb | resized"
            )
            return True
        except Exception as exc:
            _log(f"  [!] Image error: {exc}")
            return False

    def save_product_images(
        self, order_code: str, data_dir: Path,
        note_prices: list[int] | None = None,
        oos_prices: list[int] | None = None,
    ) -> list[Path]:
        """Save product images, optionally filtering by note prices and excluding OOS products.

        Args:
            note_prices: When set, only save images for products whose price appears in this list.
            oos_prices: When set, skip images for products whose price appears in this list (OOS).
        """
        product_dir = data_dir / "product" / order_code
        if product_dir.exists():
            shutil.rmtree(product_dir)
            _log(f"  CLEAN IMAGE: removed old images for {order_code}")
        product_dir.mkdir(parents=True, exist_ok=True)

        items = self._extract_product_image_items_from_modal()
        note_price_counter = Counter(note_prices) if note_prices else None
        oos_price_counter = Counter(oos_prices) if oos_prices else None
        saved_paths: list[Path] = []
        total_size = 0
        skipped = 0
        for i, (url, product_name, price) in enumerate(items):
            # Skip OOS products
            if oos_price_counter is not None:
                if oos_price_counter.get(price, 0) > 0:
                    _log(f"  SKIP IMAGE (OOS): {product_name} (price={price})")
                    oos_price_counter[price] -= 1
                    skipped += 1
                    continue
            if note_price_counter is not None:
                if note_price_counter.get(price, 0) <= 0:
                    _log(f"  SKIP IMAGE: {product_name} (price={price} not in note)")
                    skipped += 1
                    continue
                note_price_counter[price] -= 1
            safe_name = _remove_diacritics(product_name) or f"product_{i + 1}"
            file_name = f"{order_code}_{safe_name}.jpg"
            file_path = product_dir / file_name
            if self._download_and_compress_image(url, file_path):
                saved_paths.append(file_path)
                total_size += file_path.stat().st_size

        total_kb = total_size / 1024
        _log(f"  SAVE IMAGE: {len(saved_paths)}/{len(items)} images (skipped={skipped}) | total={total_kb:.0f}kb")
        return saved_paths

    def _dismiss_notifications(self) -> None:
        """Close any popup notifications or open overlays that could intercept clicks."""
        try:
            # Close stacked overlays (chat panel, bill modal, dropdowns) that block clicks
            overlay_indicators = (
                "div.cdk-overlay-backdrop",
                "div.tds-drawer-mask",
                "app-modal-list-bill",
                "div.chat-body",
            )
            for _ in range(3):
                has_overlay = any(
                    self.page.locator(sel).count() > 0
                    and self.page.locator(sel).first.is_visible()
                    for sel in overlay_indicators
                )
                if not has_overlay:
                    break
                self.page.keyboard.press("Escape")
                self.page.wait_for_timeout(self._cfg.overlay_dismiss_ms)
        except Exception:
            pass
        try:
            close_buttons = self.page.locator(
                "tds-notification button.tds-button-close, "
                "tds-notification .tds-notification-notice-close button"
            )
            count = close_buttons.count()
            for i in range(count):
                try:
                    close_buttons.nth(i).click(timeout=self._cfg.notification_click_ms, force=True)
                except Exception:
                    pass
            if count > 0:
                self.page.wait_for_timeout(self._cfg.overlay_dismiss_ms)
        except Exception:
            pass

    def _read_modal_address(self) -> str:
        """Read address input value via JS evaluate — no click needed."""
        value = self.page.evaluate("""
            () => {
                const selectors = [
                    "input[placeholder='Nhập địa chỉ']",
                    "input[data-placeholder='Nhập địa chỉ']",
                    "input[placeholder*='địa chỉ']",
                ];
                for (const sel of selectors) {
                    const el = document.querySelector(sel);
                    if (el && el.value && el.value.trim()) return el.value.trim();
                }
                return '';
            }
        """)
        return str(value or "").strip()

    def _read_modal_note(self) -> str:
        """Read note textarea value via JS evaluate — no click needed."""
        value = self.page.evaluate("""
            () => {
                const selectors = [
                    "textarea[placeholder*='Nhập ghi chú']",
                    "textarea[data-placeholder*='Nhập ghi chú']",
                    "textarea[placeholder*='Ghi chú']",
                ];
                for (const sel of selectors) {
                    const el = document.querySelector(sel);
                    if (el && el.value && el.value.trim()) return el.value.trim();
                }
                return '';
            }
        """)
        return str(value or "").strip()

    def _extract_forecast_stock_from_modal(self) -> list[int]:
        """Extract 'Tồn dự báo' values for each product in the modal."""
        forecasts: list[int] = []
        product_rows = self.page.locator("div.tds-collapse-content-box div.w-full.flex.gap-x-3")
        for i in range(product_rows.count()):
            row_text = product_rows.nth(i).inner_text().strip()
            # Match "Tồn dự báo: <number>" — the number may be negative
            m = re.search(r"T[oồ]n\s+d[uự]\s+b[aá]o\s*:\s*(-?\d+)", row_text, flags=re.IGNORECASE)
            if m:
                forecasts.append(int(m.group(1)))
            else:
                # If not found, assume 0 (treat as out of stock)
                forecasts.append(0)
        return forecasts

    def _check_delivery_rate(self) -> tuple[bool, str]:
        """Check customer delivery success rate from modal.

        Returns (is_low_rate, rate_text).
        - is_low_rate=True when rate < configured threshold (default 60%)
        - 0/0 (first-time customer) is NOT considered low rate
        """
        try:
            el = self.page.locator("span.text-caption-2:has-text('Tỉ lệ giao thành công')").first
            if el.count() == 0:
                return False, ""
            text = el.inner_text(timeout=self._cfg.inner_text_read_ms).strip()

            # Extract (delivered/total) from text like "Tỉ lệ giao thành công: 71% (27/38)"
            m = re.search(r"\((\d+)/(\d+)\)", text)
            if not m:
                return False, text
            delivered, total = int(m.group(1)), int(m.group(2))

            # 0/0 = first-time customer, not low rate
            if total == 0:
                return False, text

            rate_pct = (delivered / total) * 100
            threshold = self._cfg.low_delivery_rate_pct
            # Strictly less than (<), NOT <=. E.g. threshold=60: 59% is low, 60% is OK.
            is_low = rate_pct < threshold
            return is_low, text
        except Exception as exc:
            _log(f"  [WARN] Could not read delivery rate: {exc}")
            return False, ""

    def _read_customer_tag_from_modal(self) -> str:
        """Read the current customer tag/status shown in the modal dropdown trigger."""
        selectors = [
            "span.flex.items-center.font-semibold.font-sans.cursor-pointer:has(i.tdsi-arrow-down-fill)",
            "span.font-semibold.font-sans.cursor-pointer:has(i.tdsi-arrow-down-fill)",
            "span.cursor-pointer:has(i.tdsi-arrow-down-fill)",
        ]
        modal = self.modal()
        for selector in selectors:
            try:
                label = modal.locator(selector).first
                if label.count() == 0:
                    continue
                text = " ".join(label.inner_text(timeout=self._cfg.inner_text_read_ms).split())
                if text:
                    return text
            except Exception:
                continue
        return ""

    def _should_skip_customer_in_modal(self) -> tuple[bool, str]:
        """Return whether the modal customer tag matches a configured skip tag."""
        skip_tags = self._cfg.skip_customer_tags
        if not skip_tags:
            return False, ""

        customer_tag = self._read_customer_tag_from_modal()
        if not customer_tag:
            return False, ""

        normalized_tag = _normalize_customer_tag_label(customer_tag)
        for skip_tag in skip_tags:
            if _normalize_customer_tag_label(skip_tag) == normalized_tag:
                return True, customer_tag
        return False, customer_tag

    def _set_customer_ty_le_thap(self) -> bool:
        """Change customer status from 'Bình thường' to '1 Tỷ lệ thấp' via dropdown in modal."""
        try:
            # Click 'Bình thường' to open dropdown
            btn = self.page.locator("span.cursor-pointer:has-text('Bình thường')").first
            btn.click(timeout=self._cfg.click_timeout)
            self.page.wait_for_timeout(self._cfg.panel_open_ms)

            # Select '1 Tỷ lệ thấp' from dropdown
            item = self.page.locator("div[tds-dropdown-item] a.text-body-2:has-text('Tỷ lệ thấp')").first
            item.click(timeout=self._cfg.click_timeout)
            self.page.wait_for_timeout(self._cfg.tag_update_ms)
            return True
        except Exception as exc:
            _log(f"  [WARN] Failed to set customer 'Tỷ lệ thấp': {exc}")
            return False

    def _evaluate_modal_address_and_product(
        self,
        price_code_mapping: dict[str, int | None] | None = None,
    ) -> tuple[bool, int, int, str, list[int], list[dict]]:
        """Returns (have_address, matched_count, total_products, tag, note_prices, oos_products).

        oos_products: list of {"name": str, "price": int, "forecast": int} for OOS items.
        Empty list when no OOS products detected.
        """
        address_text = self._read_modal_address()
        have_address = bool(address_text)

        note_text = self._read_modal_note()
        note_prices = self._extract_price_tokens(note_text, price_code_mapping)
        product_prices = self._extract_product_prices_from_modal()

        total_products = len(product_prices)

        # Check: no products in order list at all
        if total_products == 0:
            status = HAVE_ADDR_NO_PROD if have_address else NO_ADDR_NO_PROD
            tag = STATUS_TO_TAG[status]
            return have_address, 0, total_products, tag, note_prices, []

        # Match note prices against product prices (quantity-based matching)
        # Exact multiset equality is required before the order is treated as a
        # full match eligible for TAG 1/1.1/2/2.1.
        if note_prices and product_prices:
            product_counter = Counter(product_prices)
            note_counter = Counter(note_prices)
            matched_count = sum(min(product_counter[p], note_counter[p]) for p in product_counter if p in note_counter)
            exact_match = product_counter == note_counter
        else:
            matched_count = 0
            exact_match = False
        _log(
            f"  PRODUCTS={product_prices} NOTE_PRICES={note_prices} "
            f"MATCHED={matched_count}/{len(product_prices)} EXACT={'Y' if exact_match else 'N'}"
        )

        # Check OOS (Tồn dự báo <= 0) AFTER matching
        # Only assign OOS tag (1.4/2.4) when products matched; otherwise stay as mismatch (1.2/2.2)
        forecast_stocks = self._extract_forecast_stock_from_modal()
        oos_products: list[dict] = []
        if forecast_stocks:
            image_items = self._extract_product_image_items_from_modal()
            for idx, fs in enumerate(forecast_stocks):
                if fs <= 0:
                    raw_name = image_items[idx][1] if idx < len(image_items) else f"product_{idx + 1}"
                    # Extract short code from brackets: "[T02 XANH] T02 (Xanh)" -> "T02 XANH"
                    bracket_match = re.match(r"\[([^\]]+)\]", raw_name)
                    name = bracket_match.group(1) if bracket_match else raw_name
                    price = product_prices[idx] if idx < len(product_prices) else 0
                    oos_products.append({"name": name, "price": price, "forecast": fs})

        if oos_products:
            _log(f"  OOS: forecast_stocks={forecast_stocks} oos_count={len(oos_products)}/{total_products}")
            # Any OOS → always TAG 1.4/2.4 (regardless of match status)
            status = HAVE_ADDR_OOS if have_address else NO_ADDR_OOS
            tag = STATUS_TO_TAG[status]
            return have_address, matched_count, total_products, tag, note_prices, oos_products

        tag = _resolve_product_match_tag(have_address, total_products, exact_match)
        return have_address, matched_count, total_products, tag, note_prices, oos_products

    def _close_edit_modal_safely(self) -> None:
        # Dismiss any stacked overlays (message panel, bill modal, popover)
        # before closing the edit modal — prevents "intercepts pointer events" errors
        try:
            blocking_selectors = (
                "app-modal-list-bill",
                "div.cdk-overlay-backdrop",
                "div.tds-drawer-mask",
                "tds-modal-container",
            )
            for _ in range(3):
                has_overlay = any(
                    self.page.locator(sel).first.is_visible()
                    for sel in blocking_selectors
                    if self.page.locator(sel).count() > 0
                )
                if not has_overlay:
                    break
                self.page.keyboard.press("Escape")
                self.page.wait_for_timeout(300)
        except Exception:
            pass
        try:
            self.close_button().click(timeout=self._cfg.click_timeout)
        except Exception:
            try:
                self.page.keyboard.press("Escape")
            except Exception:
                pass

    def _create_order_bill(self, order_code: str) -> bool:
        """Create sales bill (phiếu bán hàng) in the edit modal for TAG_1 orders.

        Steps: tick checkbox → Lưu nháp → wait → Lưu nháp again → status becomes 'Đơn hàng'.
        Must be called while the edit modal is open.
        """
        try:
            step_ms = self._cfg.bill_create_step_ms

            # Tick the "Tạo phiếu bán hàng" checkbox (click the visible label, not the hidden input)
            checkbox_label = self.page.locator("label.tds-checkbox-wrapper:has(span.tds-checkbox-label:has-text('Tạo phiếu bán hàng'))").first
            if checkbox_label.count() == 0:
                _log(f"  [!] BILL: checkbox not found for {order_code}")
                return False
            checkbox_label.click(timeout=self._cfg.click_timeout)
            self.page.wait_for_timeout(step_ms)

            # Wait for "Lưu nháp" button to appear (shows ~1s after checkbox tick)
            btn_selector = "button.tds-button-primary:has-text('Lưu nháp')"
            try:
                self.page.wait_for_selector(btn_selector, state="visible", timeout=self._cfg.click_timeout)
            except Exception:
                _log(f"  [!] BILL: 'Lưu nháp' button not found for {order_code}")
                return False

            # Click "Lưu nháp" (first time)
            self.page.locator(btn_selector).first.click(timeout=self._cfg.click_timeout)
            self.page.wait_for_timeout(step_ms)

            # Click "Lưu nháp" (second time — after notifications)
            save_draft_btn2 = self.page.locator(btn_selector).first
            if save_draft_btn2.count() > 0:
                save_draft_btn2.click(timeout=self._cfg.click_timeout)
                self.page.wait_for_timeout(step_ms)

            # After 2nd click, page returns to order list — wait for it to settle
            self.page.wait_for_timeout(step_ms)

            # Verify status changed to "Đơn hàng" (visible on the order list row)
            status_tag = self.page.locator("tds-tag:has-text('Đơn hàng')").first
            if status_tag.count() > 0:
                _log(f"  BILL: create_order_bill ok for {order_code}")
                return True
            else:
                _log(f"  [!] BILL: status did not change to 'Đơn hàng' for {order_code}")
                return False
        except Exception as exc:
            _log(f"  [!] BILL: create failed for {order_code}: {exc}")
            return False

    def _send_bill_image_in_panel(self, order_code: str) -> bool:
        """Send bill image within the open message panel.

        Steps: click 'Phiếu bán hàng' → first item three-dots → 'Gửi ảnh phiếu bán hàng'
        → wait for modal to disappear (5s) → send. If modal stays visible, retry
        steps 1-2 up to bill_reload_retry_count times.
        """
        max_retries = self._cfg.bill_reload_retry_count
        retry_delay_ms = self._cfg.bill_reload_retry_delay_ms
        modal_timeout_ms = 5000

        try:
            # Click "Phiếu bán hàng" button (file icon)
            bill_btn = self.page.locator(
                "button[tooltiptitle='Phiếu bán hàng'], "
                "button:has(i.tdsi-file-line)"
            ).first
            if bill_btn.count() == 0:
                _log(f"  [!] BILL IMG: 'Phiếu bán hàng' button not found for {order_code}")
                return False
            bill_btn.click(timeout=self._cfg.click_timeout)
            self.page.wait_for_timeout(self._cfg.bill_create_step_ms)
        except Exception as exc:
            _log(f"  [!] BILL IMG: failed to open bill tab for {order_code}: {exc}")
            return False

        # Try clicking three-dots → send bill image, retry if modal doesn't disappear
        for attempt in range(max_retries + 1):
            try:
                # Step 1: Click three-dots button — scope to first bill row to avoid
                # hitting the hidden tds-tabs-nav-more button with same icon
                first_bill_row = self.page.locator(
                    "virtual-scroller .scrollable-content > div, "
                    "div.flex.items-center.border-b"
                ).first
                if first_bill_row.count() > 0:
                    three_dots_btn = first_bill_row.locator(
                        "button:has(i.tdsi-three-dots-horizon-fill)"
                    ).first
                else:
                    three_dots_btn = self.page.locator(
                        "button[tds-popover]:has(i.tdsi-three-dots-horizon-fill)"
                    ).first
                if three_dots_btn.count() == 0:
                    raise RuntimeError("three-dots button not found")
                three_dots_btn.scroll_into_view_if_needed(timeout=self._cfg.click_timeout)
                three_dots_btn.click(timeout=self._cfg.click_timeout)
                self.page.wait_for_timeout(self._cfg.bill_create_step_ms)

                # Step 2: Click "Gửi ảnh phiếu bán hàng" from popover
                popover = self.page.locator("div.tds-popover-content")
                send_bill_img_btn = popover.locator(
                    "span:has(i.tdsi-images-fill)"
                ).first
                if send_bill_img_btn.count() == 0:
                    # Fallback: text-based match
                    send_bill_img_btn = self.page.locator("text=Gửi ảnh phiếu bán hàng").first
                if send_bill_img_btn.count() == 0:
                    raise RuntimeError("'Gửi ảnh phiếu bán hàng' not found")
                send_bill_img_btn.click(timeout=self._cfg.click_timeout)

                # Wait for the bill list modal to disappear (up to 5s)
                modal = self.page.locator("app-modal-list-bill")
                try:
                    modal.wait_for(state="hidden", timeout=modal_timeout_ms)
                except Exception:
                    # Modal still visible — check if it's really there
                    if modal.count() > 0 and modal.is_visible():
                        if attempt < max_retries:
                            _log(
                                f"  [!] BILL IMG: modal still visible after {modal_timeout_ms}ms"
                                f" for {order_code} (attempt {attempt + 1}) — retrying..."
                            )
                            self.page.wait_for_timeout(retry_delay_ms)
                            continue
                        else:
                            _log(
                                f"  [!] BILL IMG: modal still visible after"
                                f" {max_retries + 1} attempt(s) for {order_code}"
                                f" — pressing Escape to close modal"
                            )
                            self.page.keyboard.press("Escape")
                            self.page.wait_for_timeout(500)
                            return False

                # Modal gone — wait for bill image to load then send
                self.page.wait_for_timeout(self._cfg.bill_image_load_ms)
                self._click_send_button_reliable(order_code)
                self.page.wait_for_timeout(self._cfg.bill_image_load_ms)

                _log(f"  BILL IMG: sent for {order_code}")
                return True

            except Exception as exc:
                if attempt < max_retries:
                    _log(
                        f"  [!] BILL IMG: attempt {attempt + 1} failed for {order_code}: {exc}"
                        f" — retrying..."
                    )
                    self.page.wait_for_timeout(retry_delay_ms)
                else:
                    _log(
                        f"  [!] BILL IMG: send failed for {order_code}"
                        f" after {max_retries + 1} attempt(s): {exc}"
                    )

        return False

    def _read_partner_name(self) -> str:
        """Read partner name from the chat/message panel label."""
        try:
            selectors = [
                "#chatOmniHeader label.text-black.font-semibold",
                "div#chatOmniHeader label.text-black.font-semibold",
                "label.text-black.font-semibold.text-title-1",
                "label.text-black.font-semibold.text-caption-1",
            ]
            for selector in selectors:
                label = self.page.locator(selector).first
                if label.count() == 0:
                    continue
                text = label.inner_text(timeout=self._cfg.inner_text_read_ms).strip()
                if text:
                    return text
        except Exception:
            pass
        return ""

    # Message templates are now loaded from config.yaml via BotConfig (self._cfg).
    # See app/bot_config.py for defaults.

    def _count_send_errors(self) -> int:
        """Count error message elements currently visible in the chat panel."""
        try:
            return self.page.locator(
                "div.message-inner.error, div.message-inner-medium.error"
            ).count()
        except Exception:
            return 0

    def _check_message_send_error(self, errors_before: int = -1) -> bool:
        """Return True only if a NEW send error appeared after clicking send.

        Pass errors_before (from _count_send_errors() before clicking) to
        detect only new errors and avoid false positives from old chat history.
        Waits briefly and re-checks to avoid false positives from transient
        'sending' states that temporarily show the error class.
        """
        try:
            errors_after = self._count_send_errors()
            if errors_before >= 0 and errors_after <= errors_before:
                return False
            if errors_after == 0:
                return False
            # Transient error class may appear while message is still being sent.
            # Wait a moment and re-check — if the count drops back, it was not a real error.
            self.page.wait_for_timeout(self._cfg.error_recheck_ms)
            errors_recheck = self._count_send_errors()
            if errors_before >= 0 and errors_recheck <= errors_before:
                return False
            if errors_recheck == 0:
                return False
            error_msg = self.page.locator(
                "div.message-inner.error, div.message-inner-medium.error"
            ).last
            try:
                _log(f"  [!] Error element HTML: {error_msg.inner_html(timeout=self._cfg.inner_text_read_ms)[:300]}")
            except Exception:
                pass
            return True
        except Exception:
            return False

    def _find_comment_reply_send_button(self, reply_textarea: Locator) -> Locator:
        """Find the FB comment-reply send button without colliding with inbox send."""
        scoped_roots = [
            reply_textarea.locator(
                "xpath=ancestor::div[.//button[@type='button'][contains(@tooltiptitle, 'Enter')]][1]"
            ).first,
            reply_textarea.locator(
                "xpath=ancestor::div[.//button[@type='button'][.//i[contains(@class, 'tdsi-send-fill')]]][1]"
            ).first,
        ]

        scoped_selectors = [
            "button[tds-button][type='button'][tooltiptitle*='Nhấn Enter để gửi']",
            "button[tds-button][type='button'][tooltiptitle*='Enter']",
            "button[tds-button][type='button']:has(i.tdsi-send-fill):has-text('Gửi')",
            "button[type='button']:has(i.tdsi-send-fill):has-text('Gửi')",
        ]

        for root in scoped_roots:
            try:
                if root.count() == 0:
                    continue
            except Exception:
                continue
            for selector in scoped_selectors:
                candidate = root.locator(selector).first
                try:
                    if candidate.count() > 0:
                        return candidate
                except Exception:
                    continue

        return self.page.locator(
            "button[tds-button][type='button'][tooltiptitle*='Nhấn Enter để gửi']:has(i.tdsi-send-fill)"
        ).first

    def _reply_submit_succeeded(self, reply_textarea: Locator) -> bool:
        """Treat cleared/hidden reply textarea as a successful FB comment reply send."""
        try:
            if reply_textarea.count() == 0:
                return True
            value = reply_textarea.input_value(timeout=self._cfg.inner_text_read_ms).strip()
            return not value
        except Exception:
            # If the textarea detached or can no longer be read, the reply box likely closed after send.
            return True

    def _reply_comment_fallback(self, partner_name: str, campaign_label: str = "", templates: list | None = None) -> bool:
        """Reply to the first comment of the FB post matching campaign_label date (latest time on that day)."""
        try:
            from datetime import datetime as _dt, date as _date

            # Parse campaign date from label like "LIVE 18/3/2026"
            target_date: _date | None = None
            if campaign_label:
                date_str = campaign_label.upper().replace("LIVE", "").strip()
                for fmt in ("%d/%m/%Y", "%d/%m/%y", "%d/%m"):
                    try:
                        parsed = _dt.strptime(date_str, fmt)
                        if fmt == "%d/%m":
                            parsed = parsed.replace(year=_dt.now().year)
                        target_date = parsed.date()
                        break
                    except ValueError:
                        pass

            # --- Find the post item matching campaign date ---
            # Each post group is: div[id^="item_"] containing ms-extras-message-item
            # tds-tag span inside that element shows the post datetime "dd-MM-yyyy HH:mm"
            def _get_post_items() -> Locator:
                return self.page.locator("div[id^='item_']:has(ms-extras-message-item)")

            def _parse_post_dt(item_loc: Locator) -> _dt | None:
                try:
                    tag_text = item_loc.locator("ms-extras-message-item tds-tag span").first.inner_text().strip()
                    return _dt.strptime(tag_text, "%d-%m-%Y %H:%M")
                except Exception:
                    return None

            scroll_area = self.page.locator("div#scrollMe").first
            best_item: Locator | None = None

            for attempt in range(15):
                post_items = _get_post_items()
                candidates: list[tuple] = []
                for i in range(post_items.count()):
                    item = post_items.nth(i)
                    post_dt = _parse_post_dt(item)
                    if post_dt is None:
                        continue
                    if target_date is None or post_dt.date() == target_date:
                        candidates.append((post_dt, i, item))

                if candidates:
                    best_dt, _, best_item = max(candidates, key=lambda x: x[0])
                    _log(f"  POST MATCH: {best_dt.strftime('%d-%m-%Y %H:%M')}")
                    break

                # Not found — scroll up to load older content
                if scroll_area.count() > 0:
                    box = scroll_area.bounding_box()
                    if box:
                        self.page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
                        self.page.mouse.wheel(0, -600)
                        self.page.wait_for_timeout(self._cfg.filter_search_ms)

            if best_item is None:
                _log(f"  [!] No post found for '{campaign_label}', falling back to first visible comment")

            # --- Find first customer comment in that post item ---
            _COMMENT_SEL = "div.log-comment.is_client, div.log-comment.desktop\\:is_client"
            if best_item is not None:
                user_comments = best_item.locator(_COMMENT_SEL)
            else:
                user_comments = self.page.locator(_COMMENT_SEL)

            if user_comments.count() == 0:
                _log("  [!] No user comments found")
                return False

            # Find reply button: prioritize comment with 5+ '*' anywhere in page,
            # else fall back to first enabled comment in best_item scope.
            # Star comment may live in a sibling div[id^='item_'] outside best_item.
            reply_btn = None
            first_btn = None

            # PASS 1: search full page for a star comment
            full_page_comments = self.page.locator(_COMMENT_SEL)
            for ci in range(full_page_comments.count()):
                comment = full_page_comments.nth(ci)
                btn = comment.locator("button:has-text('Phản hồi')").first
                if btn.count() == 0 or btn.is_disabled():
                    continue
                try:
                    comment_text = comment.inner_text(timeout=self._cfg.inner_text_read_ms).strip()
                    if re.search(r"\*{5,}", comment_text):
                        reply_btn = btn
                        break
                except Exception:
                    pass

            # PASS 2: no star found — pick first enabled comment in scoped range
            if reply_btn is None:
                for ci in range(user_comments.count()):
                    comment = user_comments.nth(ci)
                    btn = comment.locator("button:has-text('Phản hồi')").first
                    if btn.count() == 0 or btn.is_disabled():
                        continue
                    first_btn = btn
                    break
                reply_btn = first_btn

            if reply_btn is None:
                _log("  [!] Reply button not found or all disabled")
                return False

            reply_btn.click(timeout=self._cfg.click_timeout)
            self.page.wait_for_timeout(self._cfg.escape_close_ms)

            # Type message into reply textarea
            reply_textarea = self.page.locator(
                "textarea#inputReply:visible, "
                "textarea[placeholder*='Nhập nội dung trả lời']:visible"
            ).first
            if reply_textarea.count() == 0:
                _log("  [!] Reply textarea not found")
                return False

            name = partner_name or ""
            tpl_list = templates if templates else self._cfg.comment_fallback_templates
            template = random.choice(tpl_list)
            fallback_msg = template.format(name=name)

            reply_textarea.click(timeout=self._cfg.click_timeout)
            reply_textarea.fill(fallback_msg)
            self.page.wait_for_timeout(self._cfg.text_fill_ms)

            # Click the send button inside the reply composer, not the inbox send below.
            reply_submit = self._find_comment_reply_send_button(reply_textarea)
            for attempt in range(1, 4):
                try:
                    reply_submit.scroll_into_view_if_needed(timeout=self._cfg.click_timeout)
                    self.page.wait_for_timeout(200)
                    try:
                        reply_submit.click(timeout=self._cfg.click_timeout)
                    except Exception:
                        reply_submit.click(timeout=self._cfg.click_timeout, force=True)
                except Exception as exc:
                    _log(f"  [!] Comment reply submit attempt {attempt}/3 error: {exc}")
                self.page.wait_for_timeout(self._cfg.panel_open_ms)
                if self._reply_submit_succeeded(reply_textarea):
                    _log(f"  COMMENT REPLY SENT: '{fallback_msg[:50]}...'")
                    return True

                # Fallback: the reply button advertises Enter-to-send.
                try:
                    reply_textarea.press("Enter")
                except Exception as exc:
                    _log(f"  [!] Comment reply Enter fallback attempt {attempt}/3 error: {exc}")
                self.page.wait_for_timeout(self._cfg.panel_open_ms)
                if self._reply_submit_succeeded(reply_textarea):
                    _log(f"  COMMENT REPLY SENT: '{fallback_msg[:50]}...'")
                    return True

                if attempt < 3:
                    _log(f"  [!] Comment reply send attempt {attempt}/3 did not clear reply box, retrying...")
                    self.page.wait_for_timeout(500)

            _log("  [!] Comment reply send button did not submit reply")
            return False
        except Exception as exc:
            _log(f"  [!] Comment reply failed: {exc}")
            _log(f"  [!] Stack trace:\n{traceback.format_exc()}")
            return False

    def _reply_comment_with_retry(self, partner_name: str, campaign_label: str = "", templates: list | None = None) -> bool:
        """Call _reply_comment_fallback with retry on failure (bot.comment_reply_max_retries)."""
        max_retries = self._cfg.comment_reply_max_retries
        for attempt in range(1, max_retries + 2):  # +2: 1 initial + max_retries extras
            try:
                ok = self._reply_comment_fallback(partner_name, campaign_label=campaign_label, templates=templates)
            except Exception as exc:
                _log(f"  [!] Comment reply attempt {attempt}/{max_retries + 1} error: {exc}")
                ok = False
            if ok:
                return True
            if attempt <= max_retries:
                _log(f"  [!] Comment reply attempt {attempt}/{max_retries + 1} failed, retrying...")
                self.page.wait_for_timeout(self._cfg.comment_reply_post_ms)
        return False

    def _build_ask_address_message(self, partner_name: str = "") -> str:
        """ask address: Ask for address (no-address cases)."""
        template = random.choice(self._cfg.ask_address_templates)
        name = partner_name or ""
        return template.format(name=name)

    def _build_ask_address_no_product_message(self, partner_name: str = "") -> str:
        """ask address (case 2.3): Ask for address when no products in order list."""
        template = random.choice(self._cfg.ask_address_no_product_templates)
        name = partner_name or ""
        return template.format(name=name)

    def _build_deposit_message(self, partner_name: str = "") -> str:
        """ask deposit: Ask for deposit (cases 1.1, 2.1)."""
        name = partner_name or ""
        return self._cfg.deposit_template.format(name=name)

    def _build_oos_message(self, oos_products: list[dict], partner_name: str = "") -> str:
        """Build OOS notification message listing out-of-stock products."""
        name = partner_name or ""
        line_fmt = self._cfg.oos_line_format
        oos_lines = "\n".join(
            line_fmt.format(price=p['price'], name=p['name'], forecast=p['forecast'])
            for p in oos_products
        )
        template = random.choice(self._cfg.oos_templates)
        return template.format(name=name, oos_lines=oos_lines)

    def collect_and_enrich_single_pass(
        self,
        csv_writer,
        max_records: int | None = None,
        data_dir: Path | None = None,
        campaign_label: str = "",
        price_code_mapping: dict[str, int | None] | None = None,
        tag_1_2_only: bool = False,
    ) -> tuple[int, int, int]:
        """Single-pass: read each row, enrich immediately, write to CSV.

        Returns (processed, action_count, error_count).
        """
        rows, count = self._wait_for_rows_on_page()
        expected_total = self.pagination_total_count()
        seen_codes: set[str] = set()
        page_index = 1
        total_seen = 0
        total_skipped = 0
        processed = 0
        tag_counts: dict[str, int] = {}
        error_count = 0
        enrich_start = time.time()

        whitelist = set(self._cfg.test_order_ids)
        _log(f"SINGLE-PASS started: rows={count} on page={page_index}")
        if tag_1_2_only:
            _log("TAG FILTER mode: only TAG 1 & TAG 2 will run actions")
        if whitelist:
            _log(f"WHITELIST mode: only processing {len(whitelist)} order(s): {', '.join(whitelist)}")
        if expected_total is not None:
            _log(f"Expected total from tab count={expected_total}")

        while True:
            rows, count = self._wait_for_rows_on_page()
            if count == 0:
                break

            _log(f"[PAGE {page_index}] {count} rows")

            i = 0
            while i < count:
                if max_records is not None and total_seen >= max_records:
                    _log(f"Reached test cap max_records={max_records}, stopping")
                    break

                row = rows.nth(i)
                cells = row.locator("td")
                if cells.count() < 9:
                    i += 1
                    continue

                stt = cells.nth(3).inner_text().strip()
                order_cell = cells.nth(4)
                code_span = order_cell.locator("span").first
                order_code = code_span.inner_text().strip() if code_span.count() > 0 else order_cell.inner_text().strip()

                if not order_code or order_code in seen_codes:
                    i += 1
                    continue

                seen_codes.add(order_code)

                # Whitelist filter: if set, only process listed order codes
                if whitelist and order_code not in whitelist:
                    i += 1
                    continue

                # Check tag: must be empty (no tag)
                tags = self._tag_values_in_order_cell(order_cell)
                tag_value = tags[0] if tags else ""
                if tags:
                    total_skipped += 1
                    total_seen += 1
                    _log(f"SKIP: stt={stt} order={order_code} reason=tag '{tag_value}'")
                    i += 1
                    continue

                # Check status: must be 'Nháp'
                if not self._is_order_status_nhap(row):
                    total_skipped += 1
                    total_seen += 1
                    _log(f"SKIP: stt={stt} order={order_code} reason=status not 'Nháp'")
                    i += 1
                    continue

                total_seen += 1

                # Extract basic row data
                channel_cell = cells.nth(5)
                channel_span = channel_cell.locator("span.ml-2").first
                channel_name = channel_span.inner_text().strip() if channel_span.count() > 0 else channel_cell.inner_text().strip()

                customer_cell = cells.nth(6)
                customer_p = customer_cell.locator("p").first
                customer_name = customer_p.inner_text().strip() if customer_p.count() > 0 else customer_cell.inner_text().strip()

                total_amount = cells.nth(7).inner_text().strip()
                total_qty = cells.nth(8).inner_text().strip()

                # Check visible customer tag on the list row first; modal will re-check hidden customer tags later.
                if not self._is_customer_normal(row):
                    processed += 1
                    row_data_t0: dict[str, str] = {
                        "No": stt,
                        "Order_Code": order_code,
                        "Tag": TAG_0,
                        "Channel": channel_name,
                        "Customer": customer_name,
                        "Total_Amount": total_amount,
                        "Total_Qty": total_qty,
                        "Address_Status": "NOT_BINH_THUONG",
                        "Note": "",
                        "Match_Product": "",
                        "Decision": "skip_not_binh_thuong",
                        "Comment": "",
                    }
                    _log(f"---- ORDER = {order_code}  ({processed})  {customer_name}  customer not 'Bình thường' -> TAG 0 ----")
                    if _should_skip_for_tag_1_2_only(tag_1_2_only, TAG_0):
                        row_data_t0["Decision"] = "skip_tag_1_2_only"
                        row_data_t0["Note"] = "resolved_tag=0 skipped_by_cli"
                        _log("  SKIP ALL ACTIONS: only TAG 1 & TAG 2 mode")
                    else:
                        if not self._apply_processed_tag_to_order(order_code, TAG_0):
                            row_data_t0["Tag"] = ERR
                            error_count += 1
                            _log(f"  [!] TAG 0 FAILED")
                        else:
                            _log(f"  TAG -> 0")
                    tag_counts[TAG_0] = tag_counts.get(TAG_0, 0) + 1
                    csv_writer.write_row(row_data_t0)
                    _log(f"  CSV +1: total={csv_writer.count}")
                    i += 1
                    continue

                row_data: dict[str, str] = {
                    "No": stt,
                    "Order_Code": order_code,
                    "Tag": tag_value,
                    "Channel": channel_name,
                    "Customer": customer_name,
                    "Total_Amount": total_amount,
                    "Total_Qty": total_qty,
                    "Address_Status": "",
                    "Note": "",
                    "Match_Product": "",
                    "Decision": "",
                    "Comment": "",
                }
                old_tag = tag_value
                processed += 1

                _log("-" * 60)
                _log(f"---- ORDER = {order_code}  ({processed})  {customer_name}  old_tag={old_tag or '(none)'} ----")

                order_start = time.time()
                saved_images: list[Path] = []
                try:
                    self._dismiss_notifications()
                    self.open_edit_modal_by_row(row)
                    self.wait_modal()

                    if not self._verify_modal_order_code(order_code):
                        self._close_edit_modal_safely()
                        raise ValueError(f"modal shows wrong order, expected {order_code}")

                    modal_skip_customer, modal_customer_tag = self._should_skip_customer_in_modal()
                    if modal_skip_customer:
                        _log(f"  CUSTOMER TAG (modal): {modal_customer_tag} -> TAG 0, skip")
                        resolved_tag = TAG_0
                        row_data["Tag"] = TAG_0
                        row_data["Address_Status"] = "NOT_BINH_THUONG"
                        row_data["Note"] = f"customer_tag={modal_customer_tag} (modal)"
                        row_data["Decision"] = "skip_not_binh_thuong"
                        self._close_edit_modal_safely()
                        self._dismiss_notifications()
                        if _should_skip_for_tag_1_2_only(tag_1_2_only, TAG_0):
                            row_data["Decision"] = "skip_tag_1_2_only"
                            row_data["Note"] = f"resolved_tag=0 customer_tag={modal_customer_tag} (modal)"
                            _log("  SKIP ALL ACTIONS: only TAG 1 & TAG 2 mode")
                        elif TAG_0 != old_tag:
                            if not self._apply_processed_tag_to_order(order_code, TAG_0):
                                row_data["Tag"] = ERR
                                error_count += 1
                                _log(f"  [!] TAG 0 FAILED")
                            else:
                                _log(f"  TAG -> 0")
                        tag_counts[TAG_0] = tag_counts.get(TAG_0, 0) + 1
                        order_elapsed = time.time() - order_start
                        _log(f"  DONE ORDER = {order_code} | STT = {processed} | TAG = 0 | NAME = {customer_name} | TIME = {order_elapsed:.1f}s")
                        csv_writer.write_row(row_data)
                        _log(f"  CSV +1: total={csv_writer.count}")
                        rows = self.filtered_order_rows()
                        count = rows.count()
                        if i >= count:
                            break
                        continue

                    # Check delivery rate BEFORE address & product matching
                    is_low_rate, rate_text = self._check_delivery_rate()
                    if is_low_rate:
                        _log(f"  LOW DELIVERY RATE: {rate_text} -> TAG 0, skip")
                        self._set_customer_ty_le_thap()
                        resolved_tag = TAG_0
                        row_data["Tag"] = TAG_0
                        row_data["Address_Status"] = "LOW_RATE"
                        row_data["Note"] = rate_text
                        row_data["Decision"] = "skip_low_rate"
                        self._close_edit_modal_safely()
                        self._dismiss_notifications()
                        if _should_skip_for_tag_1_2_only(tag_1_2_only, TAG_0):
                            row_data["Decision"] = "skip_tag_1_2_only"
                            row_data["Note"] = f"resolved_tag=0 low_rate={rate_text}" if rate_text else "resolved_tag=0 low_rate"
                            _log("  SKIP ALL ACTIONS: only TAG 1 & TAG 2 mode")
                        elif TAG_0 != old_tag:
                            if not self._apply_processed_tag_to_order(order_code, TAG_0):
                                row_data["Tag"] = ERR
                                error_count += 1
                                _log(f"  [!] TAG 0 FAILED")
                            else:
                                _log(f"  TAG -> 0")
                        tag_counts[TAG_0] = tag_counts.get(TAG_0, 0) + 1
                        order_elapsed = time.time() - order_start
                        _log(f"  DONE ORDER = {order_code} | STT = {processed} | TAG = 0 | NAME = {customer_name} | TIME = {order_elapsed:.1f}s")
                        # Write CSV + skip rest of try block (finally still runs)
                        csv_writer.write_row(row_data)
                        _log(f"  CSV +1: total={csv_writer.count}")
                        # Re-fetch rows since DOM changed after tag update
                        rows = self.filtered_order_rows()
                        count = rows.count()
                        if i >= count:
                            break
                        continue

                    have_address, matched_count, total_products, resolved_tag, note_prices, oos_products = self._evaluate_modal_address_and_product(price_code_mapping)

                    _log(f"  CHECK ADDRESS -> {'VALID' if have_address else 'EMPTY'}")

                    # OOS summary
                    in_stock_count = total_products - len(oos_products)
                    if oos_products:
                        oos_names = ", ".join(f"{p['name']}({p['price']})" for p in oos_products)
                        _log(f"  CHECK OOS -> {len(oos_products)} hết hàng, {in_stock_count} còn hàng | {oos_names}")
                    else:
                        _log(f"  CHECK OOS -> all in stock ({total_products})")

                    match_label = _build_match_label(matched_count, total_products, resolved_tag)
                    _log(f"  CHECK PRODUCT -> {match_label}")

                    row_data["Address_Status"] = "VALID" if have_address else "EMPTY"
                    row_data["Match_Product"] = match_label
                    row_data["Tag"] = resolved_tag
                    row_data["Note"] = f"addr={'ok' if have_address else 'empty'} match={matched_count}/{total_products}"

                    if _should_skip_for_tag_1_2_only(tag_1_2_only, resolved_tag):
                        row_data["Decision"] = "skip_tag_1_2_only"
                        row_data["Note"] = f"resolved_tag={resolved_tag} skipped_by_cli"
                        _log(f"  SKIP ALL ACTIONS: resolved_tag={resolved_tag} (only TAG 1 & TAG 2 mode)")
                        self._close_edit_modal_safely()
                        self._dismiss_notifications()
                        tag_counts[resolved_tag] = tag_counts.get(resolved_tag, 0) + 1
                        order_elapsed = time.time() - order_start
                        _log(f"  DONE ORDER = {order_code} | STT = {processed} | TAG = {resolved_tag} | NAME = {customer_name} | TIME = {order_elapsed:.1f}s")
                        csv_writer.write_row(row_data)
                        _log(f"  CSV +1: total={csv_writer.count}")
                        rows = self.filtered_order_rows()
                        count = rows.count()
                        if i >= count:
                            break
                        continue

                    # Save images for actionable tags (not tag-only 1.3)
                    # OOS tags (1.4/2.4): send only in-stock product images
                    # Mismatch tags (1.2/2.2): send only in-stock product images (skip OOS)
                    # Normal tags: filter by note_prices
                    # Skip saving if the corresponding send feature is disabled
                    if resolved_tag not in TAG_ONLY_TAGS and data_dir is not None:
                        oos_price_list = [p["price"] for p in oos_products] if oos_products else None
                        if resolved_tag in OOS_TAGS:
                            # OOS tags: send only in-stock product images
                            if self._cfg.enable_send_oos_image:
                                saved_images = self.save_product_images(order_code, data_dir, oos_prices=oos_price_list)
                        elif resolved_tag in (TAG_1_2, TAG_2_2):
                            # Mismatch (all in-stock): send ALL product images
                            if self._cfg.enable_send_product_image:
                                saved_images = self.save_product_images(order_code, data_dir)
                        else:
                            if self._cfg.enable_send_product_image:
                                saved_images = self.save_product_images(order_code, data_dir, note_prices)


                    bill_created = False
                    if resolved_tag == TAG_1:
                        if self._cfg.enable_create_bill:
                            bill_created = self._create_order_bill(order_code)
                        elif self._cfg.enable_send_bill_image:
                            # Skip create but allow send (test mode: assume bill already exists)
                            bill_created = True
                            _log(f"  BILL: create skipped, send enabled — assuming bill exists")

                    self._close_edit_modal_safely()
                    self._dismiss_notifications()

                    if resolved_tag != old_tag:
                        if not self._apply_processed_tag_to_order(order_code, resolved_tag):
                            row_data["Tag"] = ERR
                            error_count += 1
                            _log(f"  [!] TAG FAILED: target={resolved_tag}")
                        else:
                            _log(f"  TAG -> {resolved_tag}")
                    else:
                        _log(f"  TAG unchanged: {resolved_tag}")

                    tag_counts[resolved_tag] = tag_counts.get(resolved_tag, 0) + 1

                    # Send messages per tag
                    # 1.3 → tag only, no messages
                    if resolved_tag in TAG_ONLY_TAGS:
                        _log(f"  SKIP MSG: tag-only tag={resolved_tag}")
                    else:
                        self._dismiss_notifications()
                        msg_row = self.row_by_code(order_code)

                        if msg_row.count() > 0:
                            self.message_button_in_row(msg_row).click(
                                timeout=self._cfg.click_timeout, force=True
                            )
                            self._wait_panel_ready()

                            partner_name = self._read_partner_name()

                            # IMAGE: send product images first (in-stock only for OOS/mismatch tags)
                            if resolved_tag in OOS_TAGS:
                                if self._cfg.enable_send_oos_image and saved_images:
                                    self._send_batched_in_open_panel("", saved_images, order_code)
                            elif self._cfg.enable_send_product_image and saved_images:
                                self._send_batched_in_open_panel("", saved_images, order_code)

                            # OOS MSG: send OOS notification (TAG 1.4, 2.4)
                            if self._cfg.enable_send_oos_message and resolved_tag in OOS_TAGS and oos_products:
                                oos_msg = self._build_oos_message(oos_products, partner_name)
                                self._send_in_panel(oos_msg, None, order_code)

                            # ask address (no-address tags: TAG 2, 2.1, 2.2, 2.3, 2.4)
                            # TAG 2.3: no products → use dedicated no-product template
                            # For TAG 2.2: only ask if there are in-stock products
                            # For TAG 2.4: only ask if there are in-stock products
                            if self._cfg.enable_send_message:
                                if resolved_tag == TAG_2_3:
                                    ask_msg = self._build_ask_address_no_product_message(partner_name)
                                    self._send_in_panel(ask_msg, None, order_code)
                                elif resolved_tag in (TAG_2, TAG_2_1):
                                    ask_msg = self._build_ask_address_message(partner_name)
                                    self._send_in_panel(ask_msg, None, order_code)
                                elif resolved_tag in (TAG_2_2, TAG_2_4) and in_stock_count > 0:
                                    ask_msg = self._build_ask_address_message(partner_name)
                                    self._send_in_panel(ask_msg, None, order_code)
                                elif resolved_tag in (TAG_2_2, TAG_2_4):
                                    _log(f"  SKIP ask address: all products OOS, no point asking address")

                            # ask deposit (TAG 1.1, 2.1, and 1.4/2.4 with 4+ in-stock)
                            if self._cfg.enable_send_message:
                                if resolved_tag in (TAG_1_1, TAG_2_1):
                                    deposit_msg = self._build_deposit_message(partner_name)
                                    self._send_in_panel(deposit_msg, None, order_code)
                                elif resolved_tag in OOS_TAGS and in_stock_count >= 4:
                                    deposit_msg = self._build_deposit_message(partner_name)
                                    self._send_in_panel(deposit_msg, None, order_code)

                            # reply comment (TAG 1, 1.1, 1.2, 1.4, 2, 2.1, 2.2, 2.4)
                            if self._cfg.enable_comment_reply and resolved_tag in (TAG_1, TAG_1_1, TAG_1_2, TAG_1_4, TAG_2, TAG_2_1, TAG_2_2, TAG_2_4):
                                _tpls = self._cfg.comment_order_done_templates if resolved_tag == TAG_1 else None
                                comment_ok = self._reply_comment_with_retry(partner_name, campaign_label=campaign_label, templates=_tpls)
                                row_data["Comment"] = "ok" if comment_ok else "send_fail"
                                self.page.wait_for_timeout(self._cfg.comment_reply_post_ms)

                            # BILL: send bill image after reply comment (TAG 1 only)
                            if self._cfg.enable_send_bill_image and resolved_tag == TAG_1 and bill_created:
                                self._send_bill_image_in_panel(order_code)
                                self.page.wait_for_timeout(self._cfg.bill_image_load_ms)

                            self.page.keyboard.press("Escape")
                            self.page.wait_for_timeout(self._cfg.escape_close_ms)
                        else:
                            _log(f"  [!] Row not found for sending: {order_code}")

                    order_elapsed = time.time() - order_start
                    oos_label = f" | OOS = {len(oos_products)}/{total_products}" if oos_products else ""
                    _log(f"  DONE ORDER = {order_code} | STT = {processed} | TAG = {resolved_tag} | MATCH = {matched_count}/{total_products}{oos_label} | NAME = {customer_name} | TIME = {order_elapsed:.1f}s")

                except Exception as exc:
                    row_data["Tag"] = ERR
                    row_data["Address_Status"] = ERR
                    row_data["Match_Product"] = ""
                    row_data["Note"] = f"error: {exc}"
                    error_count += 1
                    _log(f"  [!] FAILED: {exc}")
                    _log(f"  [!] Stack trace:\n{traceback.format_exc()}")
                finally:
                    self._close_edit_modal_safely()

                # Write row to CSV immediately
                csv_writer.write_row(row_data)
                _log(f"  CSV +1: total={csv_writer.count}")

                # Reload page periodically to prevent memory/performance degradation
                reload_n = self._cfg.reload_every_n_orders
                if reload_n > 0 and processed % reload_n == 0:
                    _log(f"  [RELOAD] Refreshing page after {processed} orders to free memory")
                    self.page.reload(wait_until="networkidle")
                    self.page.wait_for_timeout(self._cfg.table_load_ms)
                    self.apply_campaign_filter(campaign_label)
                    rows, count = self._wait_for_rows_on_page()
                    _log(f"  [RELOAD] Done — {count} rows loaded on page")
                    i = 0
                    continue

                # Re-fetch rows since DOM may have changed after modal/tag/message interactions
                rows = self.filtered_order_rows()
                count = rows.count()
                # Don't increment i — re-scan from same index since rows may have shifted
                # But if count dropped, adjust
                if i >= count:
                    break

            if max_records is not None and total_seen >= max_records:
                break

            marker = self._first_row_marker(rows)
            if not self._go_to_next_page(page_index, marker):
                break
            page_index += 1

        total_elapsed = time.time() - enrich_start
        total_min, total_sec = divmod(int(total_elapsed), 60)
        _log("=" * 60)
        tag_summary = "  ".join(f"[{t}]={c}" for t, c in sorted(tag_counts.items()))
        _log(
            f"SUMMARY: processed={processed} skipped={total_skipped} | {tag_summary}  "
            f"[{ERR}]={error_count} | total_time={total_min}m{total_sec:02d}s"
        )
        _log("=" * 60)
        action_count = sum(c for t, c in tag_counts.items() if t not in TAG_ONLY_TAGS)
        return processed, action_count, error_count

    def enrich_collected_rows(self, rows_data: list[dict[str, str]], data_dir: Path | None = None, campaign_label: str = "", price_code_mapping: dict[str, int | None] | None = None) -> tuple[int, int, int]:
        # Build lookups: qualify (no tag) and tag0 (not-binh-thuong, need TAG 0 applied)
        whitelist = set(self._cfg.test_order_ids)
        qualify_lookup: dict[str, dict[str, str]] = {}
        tag0_lookup: dict[str, dict[str, str]] = {}
        for r in rows_data:
            code = str(r.get("Order_Code", "")).strip()
            tag = str(r.get("Tag", "")).strip()
            decision = str(r.get("Decision", "")).strip()
            if not code:
                continue
            if decision == "skip_not_binh_thuong":
                if whitelist and code not in whitelist:
                    continue
                tag0_lookup[code] = r
            elif not tag:
                if whitelist and code not in whitelist:
                    continue
                qualify_lookup[code] = r

        total = len(qualify_lookup)
        skipped_existing = len(rows_data) - total - len(tag0_lookup)
        _log("=" * 60)
        if whitelist:
            _log(f"WHITELIST mode: only processing {len(whitelist)} order(s): {', '.join(whitelist)}")
        _log(f"ENRICH: {total} qualifying orders (no tag) | {len(tag0_lookup)} not-binh-thuong (TAG 0) | skipped {skipped_existing} with tags")
        _log("=" * 60)

        processed = 0
        tag_counts: dict[str, int] = {}
        error_count = 0
        page_index = 1
        enrich_start = time.time()

        # Process page by page sequentially (assumes we start at page 1)
        while True:
            rows, count = self._wait_for_rows_on_page()
            if count == 0:
                break

            _log(f"[PAGE {page_index}] {count} rows")

            for i in range(count):
                row = rows.nth(i)
                try:
                    order_code = self.order_code_in_row(row)
                except Exception:
                    continue

                if order_code not in qualify_lookup and order_code not in tag0_lookup:
                    continue

                # Not-binh-thuong: apply TAG 0 without opening modal
                if order_code in tag0_lookup:
                    rd = tag0_lookup.pop(order_code)
                    _log(f"TAG 0: order={order_code} customer not 'Bình thường'")
                    if not self._apply_processed_tag_to_order(order_code, TAG_0):
                        rd["Tag"] = ERR
                        error_count += 1
                        _log(f"  [!] TAG 0 FAILED")
                    else:
                        _log(f"  TAG -> 0")
                    tag_counts[TAG_0] = tag_counts.get(TAG_0, 0) + 1
                    continue

                row_data = qualify_lookup.pop(order_code)
                old_tag = str(row_data.get("Tag", "")).strip()
                processed += 1
                customer_name = str(row_data.get("Customer", "")).strip()

                _log("-" * 60)
                _log(f"---- ORDER = {order_code}  ({processed}/{total})  {customer_name}  old_tag={old_tag or '(none)'} ----")

                order_start = time.time()
                saved_images: list[Path] = []
                try:
                    self._dismiss_notifications()
                    self.open_edit_modal_by_row(row)
                    self.wait_modal()

                    if not self._verify_modal_order_code(order_code):
                        self._close_edit_modal_safely()
                        raise ValueError(f"modal shows wrong order, expected {order_code}")

                    modal_skip_customer, modal_customer_tag = self._should_skip_customer_in_modal()
                    if modal_skip_customer:
                        _log(f"  CUSTOMER TAG (modal): {modal_customer_tag} -> TAG 0, skip")
                        row_data["Tag"] = TAG_0
                        row_data["Address_Status"] = "NOT_BINH_THUONG"
                        row_data["Note"] = f"customer_tag={modal_customer_tag} (modal)"
                        row_data["Decision"] = "skip_not_binh_thuong"
                        self._close_edit_modal_safely()
                        self._dismiss_notifications()
                        if TAG_0 != old_tag:
                            if not self._apply_processed_tag_to_order(order_code, TAG_0):
                                row_data["Tag"] = ERR
                                error_count += 1
                                _log(f"  [!] TAG 0 FAILED")
                            else:
                                _log(f"  TAG -> 0")
                        tag_counts[TAG_0] = tag_counts.get(TAG_0, 0) + 1
                        order_elapsed = time.time() - order_start
                        _log(f"  DONE ORDER = {order_code} | STT = {processed}/{total} | TAG = 0 | NAME = {customer_name} | TIME = {order_elapsed:.1f}s")
                        continue

                    # Check delivery rate BEFORE address & product matching
                    is_low_rate, rate_text = self._check_delivery_rate()
                    if is_low_rate:
                        _log(f"  LOW DELIVERY RATE: {rate_text} -> TAG 0, skip")
                        self._set_customer_ty_le_thap()
                        row_data["Tag"] = TAG_0
                        row_data["Address_Status"] = "LOW_RATE"
                        row_data["Note"] = rate_text
                        row_data["Decision"] = "skip_low_rate"
                        self._close_edit_modal_safely()
                        self._dismiss_notifications()
                        if TAG_0 != old_tag:
                            if not self._apply_processed_tag_to_order(order_code, TAG_0):
                                row_data["Tag"] = ERR
                                error_count += 1
                                _log(f"  [!] TAG 0 FAILED")
                            else:
                                _log(f"  TAG -> 0")
                        tag_counts[TAG_0] = tag_counts.get(TAG_0, 0) + 1
                        order_elapsed = time.time() - order_start
                        _log(f"  DONE ORDER = {order_code} | STT = {processed}/{total} | TAG = 0 | NAME = {customer_name} | TIME = {order_elapsed:.1f}s")
                        continue

                    have_address, matched_count, total_products, resolved_tag, note_prices, oos_products = self._evaluate_modal_address_and_product(price_code_mapping)

                    # Step 1: CHECK ADDRESS
                    _log(f"  CHECK ADDRESS -> {'VALID' if have_address else 'EMPTY'}")

                    # Step 2: CHECK OOS
                    in_stock_count = total_products - len(oos_products)
                    if oos_products:
                        oos_names = ", ".join(f"{p['name']}({p['price']})" for p in oos_products)
                        _log(f"  CHECK OOS -> {len(oos_products)} hết hàng, {in_stock_count} còn hàng | {oos_names}")
                    else:
                        _log(f"  CHECK OOS -> all in stock ({total_products})")

                    # Step 3: CHECK PRODUCT + NOTE
                    match_label = _build_match_label(matched_count, total_products, resolved_tag)
                    _log(f"  CHECK PRODUCT -> {match_label}")

                    # Save images for actionable tags (not tag-only 1.3)
                    # OOS tags (1.4/2.4): send only in-stock product images
                    # Mismatch tags (1.2/2.2): all in-stock, send ALL product images
                    # Normal tags: filter by note_prices
                    # Skip saving if the corresponding send feature is disabled
                    if resolved_tag not in TAG_ONLY_TAGS and data_dir is not None:
                        oos_price_list = [p["price"] for p in oos_products] if oos_products else None
                        if resolved_tag in OOS_TAGS:
                            if self._cfg.enable_send_oos_image:
                                saved_images = self.save_product_images(order_code, data_dir, oos_prices=oos_price_list)
                        elif resolved_tag in (TAG_1_2, TAG_2_2):
                            # Mismatch (all in-stock): send ALL product images
                            if self._cfg.enable_send_product_image:
                                saved_images = self.save_product_images(order_code, data_dir)
                        else:
                            if self._cfg.enable_send_product_image:
                                saved_images = self.save_product_images(order_code, data_dir, note_prices)

                    row_data["Address_Status"] = "VALID" if have_address else "EMPTY"
                    row_data["Match_Product"] = match_label
                    row_data["Tag"] = resolved_tag
                    row_data["Note"] = f"addr={'ok' if have_address else 'empty'} match={matched_count}/{total_products}"

                    # TAG 1: create sales bill (phiếu bán hàng) while modal is open
                    bill_created = False
                    if resolved_tag == TAG_1:
                        if self._cfg.enable_create_bill:
                            bill_created = self._create_order_bill(order_code)
                        elif self._cfg.enable_send_bill_image:
                            # Skip create but allow send (test mode: assume bill already exists)
                            bill_created = True
                            _log(f"  BILL: create skipped, send enabled — assuming bill exists")

                    self._close_edit_modal_safely()
                    self._dismiss_notifications()

                    # Apply tag (only if tag changed or is new)
                    if resolved_tag != old_tag:
                        if not self._apply_processed_tag_to_order(order_code, resolved_tag):
                            row_data["Tag"] = ERR
                            error_count += 1
                            _log(f"  [!] TAG FAILED: target={resolved_tag}")
                        else:
                            _log(f"  TAG -> {resolved_tag}")
                    else:
                        _log(f"  TAG unchanged: {resolved_tag}")

                    tag_counts[resolved_tag] = tag_counts.get(resolved_tag, 0) + 1

                    # Send messages per tag
                    # 1.3 → tag only, no messages
                    if resolved_tag in TAG_ONLY_TAGS:
                        _log(f"  SKIP MSG: tag-only tag={resolved_tag}")
                    else:
                        self._dismiss_notifications()
                        msg_row = self.row_by_code(order_code)

                        if msg_row.count() > 0:
                            self.message_button_in_row(msg_row).click(
                                timeout=self._cfg.click_timeout, force=True
                            )
                            self._wait_panel_ready()

                            partner_name = self._read_partner_name()

                            # IMAGE: send product images first (in-stock only for OOS/mismatch tags)
                            if resolved_tag in OOS_TAGS:
                                if self._cfg.enable_send_oos_image and saved_images:
                                    self._send_batched_in_open_panel("", saved_images, order_code)
                            elif self._cfg.enable_send_product_image and saved_images:
                                self._send_batched_in_open_panel("", saved_images, order_code)

                            # OOS MSG: send OOS notification (TAG 1.4, 2.4)
                            if self._cfg.enable_send_oos_message and resolved_tag in OOS_TAGS and oos_products:
                                oos_msg = self._build_oos_message(oos_products, partner_name)
                                self._send_in_panel(oos_msg, None, order_code)

                            # ask address (no-address tags: TAG 2, 2.1, 2.2, 2.3, 2.4)
                            # TAG 2.3: no products → use dedicated no-product template
                            # For TAG 2.2: only ask if there are in-stock products
                            # For TAG 2.4: only ask if there are in-stock products
                            if self._cfg.enable_send_message:
                                if resolved_tag == TAG_2_3:
                                    ask_msg = self._build_ask_address_no_product_message(partner_name)
                                    self._send_in_panel(ask_msg, None, order_code)
                                elif resolved_tag in (TAG_2, TAG_2_1):
                                    ask_msg = self._build_ask_address_message(partner_name)
                                    self._send_in_panel(ask_msg, None, order_code)
                                elif resolved_tag in (TAG_2_2, TAG_2_4) and in_stock_count > 0:
                                    ask_msg = self._build_ask_address_message(partner_name)
                                    self._send_in_panel(ask_msg, None, order_code)
                                elif resolved_tag in (TAG_2_2, TAG_2_4):
                                    _log(f"  SKIP ask address: all products OOS, no point asking address")

                            # ask deposit (TAG 1.1, 2.1, and 1.4/2.4 with 4+ in-stock)
                            if self._cfg.enable_send_message:
                                if resolved_tag in (TAG_1_1, TAG_2_1):
                                    deposit_msg = self._build_deposit_message(partner_name)
                                    self._send_in_panel(deposit_msg, None, order_code)
                                elif resolved_tag in OOS_TAGS and in_stock_count >= 4:
                                    deposit_msg = self._build_deposit_message(partner_name)
                                    self._send_in_panel(deposit_msg, None, order_code)

                            # reply comment (TAG 1, 1.1, 1.2, 1.4, 2, 2.1, 2.2, 2.4)
                            if self._cfg.enable_comment_reply and resolved_tag in (TAG_1, TAG_1_1, TAG_1_2, TAG_1_4, TAG_2, TAG_2_1, TAG_2_2, TAG_2_4):
                                _tpls = self._cfg.comment_order_done_templates if resolved_tag == TAG_1 else None
                                comment_ok = self._reply_comment_with_retry(partner_name, campaign_label=campaign_label, templates=_tpls)
                                row_data["Comment"] = "ok" if comment_ok else "send_fail"
                                if comment_ok:
                                    _log(f"  COMMENT REPLY OK: order={order_code}")
                                else:
                                    _log(f"  [!] COMMENT REPLY FAILED: order={order_code}")
                                self.page.wait_for_timeout(self._cfg.comment_reply_post_ms)

                            # BILL: send bill image after reply comment (TAG 1 only)
                            if self._cfg.enable_send_bill_image and resolved_tag == TAG_1 and bill_created:
                                self._send_bill_image_in_panel(order_code)
                                self.page.wait_for_timeout(self._cfg.bill_image_load_ms)

                            self.page.keyboard.press("Escape")
                            self.page.wait_for_timeout(self._cfg.escape_close_ms)
                        else:
                            _log(f"  [!] Row not found for sending: {order_code}")

                    order_elapsed = time.time() - order_start
                    oos_label = f" | OOS = {len(oos_products)}/{total_products}" if oos_products else ""
                    _log(f"  DONE ORDER = {order_code} | STT = {processed}/{total} | TAG = {resolved_tag} | MATCH = {matched_count}/{total_products}{oos_label} | NAME = {customer_name} | TIME = {order_elapsed:.1f}s")

                except Exception as exc:
                    row_data["Tag"] = ERR
                    row_data["Address_Status"] = ERR
                    row_data["Match_Product"] = ""
                    row_data["Note"] = f"error: {exc}"
                    error_count += 1
                    _log(f"  [!] FAILED: {exc}")
                    _log(f"  [!] Stack trace:\n{traceback.format_exc()}")
                finally:
                    self._close_edit_modal_safely()

            # All qualifying orders processed? Stop early
            if not qualify_lookup and not tag0_lookup:
                _log(f"[PAGE {page_index}] All qualifying orders done")
                break

            marker = self._first_row_marker(rows)
            if not self._go_to_next_page(page_index, marker):
                break
            page_index += 1

        # Mark any remaining unfound orders as error
        for code, rd in qualify_lookup.items():
            rd["Tag"] = ERR
            rd["Address_Status"] = ERR
            rd["Match_Product"] = ""
            rd["Note"] = "not found in table"
            error_count += 1
            _log(f"  [!] NOT FOUND: {code}")
        for code, rd in tag0_lookup.items():
            rd["Tag"] = ERR
            rd["Note"] = "not found in table"
            error_count += 1
            _log(f"  [!] NOT FOUND (not-binh-thuong): {code}")

        total_elapsed = time.time() - enrich_start
        total_min, total_sec = divmod(int(total_elapsed), 60)
        _log("=" * 60)
        tag_summary = "  ".join(f"[{t}]={c}" for t, c in sorted(tag_counts.items()))
        _log(
            f"SUMMARY: total={total} | {tag_summary}  "
            f"[{ERR}]={error_count} | total_time={total_min}m{total_sec:02d}s"
        )
        _log("=" * 60)
        action_count = sum(c for t, c in tag_counts.items() if t not in TAG_ONLY_TAGS)
        return processed, action_count, error_count

    def _is_order_status_nhap(self, row: Locator) -> bool:
        """Check if the order row has status 'Nháp' (Draft)."""
        try:
            status_tag = row.locator("tds-tag:has-text('Nháp')").first
            return status_tag.count() > 0
        except Exception:
            return False

    def _is_customer_normal(self, row: Locator) -> bool:
        """Check visible customer tags on the list row only.

        Returns False (= TAG 0) when a visible skip_customer_tag is found.
        If no customer tag is visible in the list, treat it as normal here and
        re-check inside the edit modal before address/product processing.
        """
        try:
            skip_tags = self._cfg.skip_customer_tags
            if not skip_tags:
                return True
            customer_cell = row.locator("td").nth(6)
            customer_tags = customer_cell.locator("tds-tag")
            if customer_tags.count() == 0:
                return True
            for tag_text in skip_tags:
                if customer_cell.locator(f"tds-tag:has-text('{tag_text}')").first.count() > 0:
                    return False
            return True
        except Exception:
            return True

    def _replace_new_with_processed_tag(self, row: Locator, order_code: str, target_tag: str) -> bool:
        order_cell = row.locator("td").nth(4)
        current_tags = self._tag_values_in_order_cell(order_cell)

        if target_tag in current_tags and len(current_tags) == 1:
            return True

        try:
            add_tag_button = order_cell.locator(
                "button[tds-tooltip='Thêm nhãn'], button:has(i.tdsi-price-tag-fill)"
            ).first
            # Scroll the button into view before clicking so it is inside the viewport
            try:
                add_tag_button.scroll_into_view_if_needed(timeout=self._cfg.click_timeout)
            except Exception:
                pass
            add_tag_button.click(timeout=self._cfg.click_timeout)

            tag_input = self._first([
                ".tds-select-input input.tds-select-search-input:visible",
                "tds-select-search input.tds-select-search-input:visible",
            ])
            # Use JS focus+click to avoid viewport boundary issues
            try:
                tag_input.evaluate("el => { el.scrollIntoView({block: 'center'}); el.focus(); }")
            except Exception:
                pass
            tag_input.click(timeout=self._cfg.click_timeout)
            tag_input.fill("")

            # Clear ALL existing tags: click all X buttons at once via JS
            cleared = self.page.evaluate("""
                () => {
                    const closes = document.querySelectorAll(
                        'tds-select .tds-select-selection-item-remove, '
                        + 'tds-select span[tds-button-close], '
                        + 'tds-select .tds-clear-wrapper span[tds-button-close]'
                    );
                    closes.forEach(el => el.click());
                    return closes.length;
                }
            """)
            if cleared:
                self.page.wait_for_timeout(self._cfg.tag_clear_ms)

            # Fallback: batch backspaces without checking tags each time
            tag_count = len(current_tags)
            if tag_count > 0:
                for _ in range(tag_count * 3):
                    tag_input.press("Backspace")
                self.page.wait_for_timeout(self._cfg.tag_backspace_ms)

            # Add the target tag
            tag_input.fill(target_tag)
            tag_input.press("Enter")

            self._first([
                "button:has(i.tdsi-check-fill):visible",
                "button:has(span i.tdsi-check-fill):visible",
            ]).click(timeout=self._cfg.click_timeout)

            self.page.wait_for_timeout(self._cfg.tag_update_ms)
            tags_after = self._tag_values_in_order_cell(order_cell)
            ok = tags_after == [target_tag]
            if not ok:
                _log(
                    f"[TAG] Update failed verify | order={order_code} "
                    f"target={target_tag} current={tags_after}"
                )
            return ok
        except Exception as exc:
            _log(f"[TAG] Update failed | order={order_code} target={target_tag} error={exc}")
            return False

    def _apply_processed_tag_to_order(self, order_code: str, target_tag: str) -> bool:
        row = self.row_by_code(order_code)
        if row.count() == 0:
            row, _ = self.find_row_by_code_paginated(order_code)
            if row is None:
                return False
        return self._replace_new_with_processed_tag(row, order_code, target_tag)

    def _extract_rows(
        self,
        rows: Locator,
        existing_codes: set[str],
        data: list[dict[str, str]],
        remaining_limit: int | None = None,
    ) -> tuple[int, int]:
        """Extract qualifying rows: no tag + Nháp status + Bình thường customer.
        remaining_limit counts ALL rows (added + skipped) toward the cap.
        Returns (added_count, skipped_count).
        """
        added = 0
        skipped = 0
        count = rows.count()
        for i in range(count):
            if remaining_limit is not None and (added + skipped) >= remaining_limit:
                break

            row = rows.nth(i)
            cells = row.locator("td")
            if cells.count() < 9:
                continue

            stt = cells.nth(3).inner_text().strip()
            order_cell = cells.nth(4)
            code_span = order_cell.locator("span").first
            order_code = code_span.inner_text().strip() if code_span.count() > 0 else order_cell.inner_text().strip()
            if not order_code or order_code in existing_codes:
                continue

            # Whitelist filter: if set, only collect listed order codes
            whitelist = set(self._cfg.test_order_ids)
            if whitelist and order_code not in whitelist:
                continue

            # Check tag: must be empty (no tag)
            tags = self._tag_values_in_order_cell(order_cell)
            tag_value = tags[0] if tags else ""
            if tags:
                skipped += 1
                _log(f"CSV collect SKIP: stt={stt} order={order_code} reason=tag '{tag_value}'")
                continue

            # Check order status: must be 'Nháp'
            if not self._is_order_status_nhap(row):
                skipped += 1
                _log(f"CSV collect SKIP: stt={stt} order={order_code} reason=status not 'Nháp'")
                continue

            channel_cell = cells.nth(5)
            channel_span = channel_cell.locator("span.ml-2").first
            channel_name = channel_span.inner_text().strip() if channel_span.count() > 0 else channel_cell.inner_text().strip()

            customer_cell = cells.nth(6)
            customer_p = customer_cell.locator("p").first
            customer_name = customer_p.inner_text().strip() if customer_p.count() > 0 else customer_cell.inner_text().strip()

            total_amount = cells.nth(7).inner_text().strip()
            total_qty = cells.nth(8).inner_text().strip()

            # Check visible customer tag on list row; if none is shown here, modal will re-check it later.
            if not self._is_customer_normal(row):
                _log(f"CSV collect: stt={stt} order={order_code} customer not 'Bình thường' -> TAG 0")
                data.append({
                    "No": stt,
                    "Order_Code": order_code,
                    "Tag": TAG_0,
                    "Channel": channel_name,
                    "Customer": customer_name,
                    "Total_Amount": total_amount,
                    "Total_Qty": total_qty,
                    "Address_Status": "NOT_BINH_THUONG",
                    "Note": "",
                    "Match_Product": "",
                    "Decision": "skip_not_binh_thuong",
                    "Comment": "",
                })
                existing_codes.add(order_code)
                added += 1
                continue

            data.append({
                "No": stt,
                "Order_Code": order_code,
                "Tag": tag_value,
                "Channel": channel_name,
                "Customer": customer_name,
                "Total_Amount": total_amount,
                "Total_Qty": total_qty,
                "Address_Status": "",
                "Note": "",
                "Match_Product": "",
                "Decision": "",
                "Comment": "",
            })
            existing_codes.add(order_code)
            added += 1
            _log(f"CSV collect +1: row={len(data)} stt={stt} order_code={order_code} tag={tag_value or '(none)'}")

        return added, skipped

    def _go_to_next_page(self, current_page: int, previous_marker: str) -> bool:
        next_btn = self.pagination_next_button()
        if next_btn.count() == 0:
            _log("CSV collect: stop pagination, next-page button not found")
            return False

        if self.pagination_next_disabled():
            _log("CSV collect: stop pagination, next-page button is disabled")
            return False

        _log(f"CSV collect: switching page {current_page} -> {current_page + 1}")
        self._dismiss_notifications()
        next_btn.click(timeout=self._cfg.click_slow_timeout)

        for attempt in range(1, 13):
            self.page.wait_for_timeout(self._cfg.pagination_ms)
            rows = self.filtered_order_rows()
            count = rows.count()
            marker = self._first_row_marker(rows)
            if count > 0 and marker and marker != previous_marker:
                _log(f"CSV collect: entered page {current_page + 1}, rows={count}")
                return True
            if count > 0 and not previous_marker:
                _log(f"CSV collect: entered page {current_page + 1}, rows={count}")
                return True
            if attempt == 12 and count > 0:
                _log(f"CSV collect: page {current_page + 1} loaded with same first row marker, rows={count}")
                return True

        _log(f"CSV collect: page {current_page + 1} did not stabilize in time")
        return False

    def apply_campaign_filter(self, campaign_label: str) -> None:
        # Wait for filter button to be interactive before clicking
        try:
            self.page.wait_for_selector(
                "button:has(i.tdsi-filter-1-fill), button[tooltiptitle='Lọc dữ liệu']",
                state="visible",
                timeout=self._cfg.click_slow_timeout,
            )
        except Exception:
            pass
        _log("[FILTER] Open filter panel")
        self.filter_button().click(timeout=self._cfg.click_slow_timeout)
        # Wait for the filter panel to finish opening before interacting with it
        try:
            self.page.wait_for_selector(
                "tds-select[placeholder='Chọn chiến dịch']",
                state="visible",
                timeout=self._cfg.click_slow_timeout,
            )
        except Exception:
            self.page.wait_for_timeout(self._cfg.panel_open_ms)
        _log("[FILTER] Focus campaign select")
        self.campaign_select().click(timeout=self._cfg.click_slow_timeout)

        # UI is more stable when searching by raw date then pressing Enter.
        campaign_date_text = campaign_label.replace("LIVE", "", 1).strip() if campaign_label.lower().startswith("live") else campaign_label
        _log(f"[FILTER] Search campaign by date text: {campaign_date_text}")
        search_input = self.campaign_search_input()
        search_input.fill(campaign_date_text)
        # Wait for dropdown results to load before confirming selection
        self.page.wait_for_timeout(self._cfg.filter_search_settle_ms)
        self.page.wait_for_timeout(self._cfg.filter_search_ms)
        search_input.press("Enter")

        _log("[FILTER] Apply filter")
        self.apply_filter_button().click(timeout=self._cfg.click_slow_timeout)
        self.page.wait_for_timeout(self._cfg.filter_apply_ms)
        _log(f"[FILTER] Applied campaign filter: {campaign_label}")

    def read_filtered_orders(self, max_records: int | None = None) -> list[dict[str, str]]:
        rows, count = self._wait_for_rows_on_page()
        expected_total = self.pagination_total_count()
        data: list[dict[str, str]] = []
        seen_codes: set[str] = set()
        page_index = 1
        total_skipped = 0
        total_seen = 0

        _log(f"CSV collect started: detected {count} table rows on page={page_index}")
        if expected_total is not None:
            _log(f"CSV collect: expected total from tab count={expected_total}")

        while True:
            remaining_limit = None
            if max_records is not None:
                remaining_limit = max(0, max_records - total_seen)

            added, skipped = self._extract_rows(
                rows,
                seen_codes,
                data,
                remaining_limit=remaining_limit,
            )
            total_skipped += skipped
            total_seen += added + skipped
            _log(f"CSV collect: page={page_index} added={added} skipped={skipped} cumulative={len(data)} total_seen={total_seen}")

            if max_records is not None and total_seen >= max_records:
                _log(f"CSV collect: reached test cap max_records={max_records} (seen {total_seen} rows incl. skipped), stop collect early")
                break

            marker = self._first_row_marker(rows)
            if not self._go_to_next_page(page_index, marker):
                break

            page_index += 1
            rows, count = self._wait_for_rows_on_page()

        _log(
            f"CSV collect summary: qualifying={len(data)} skipped={total_skipped} total_seen={total_seen}"
        )
        return data

    def find_row_by_code_paginated(self, order_code: str, max_pages: int = 500) -> tuple[Locator | None, int]:
        rows, count = self._wait_for_rows_on_page()
        page_index = 1
        _log(f"[CONFIRM] Search order across pagination | order={order_code} | start_rows={count}")

        while page_index <= max_pages:
            row = rows.filter(has_text=order_code).first
            if row.count() > 0:
                _log(f"[CONFIRM] Found order in table | order={order_code} | page={page_index}")
                return row, page_index

            marker = self._first_row_marker(rows)
            if not self._go_to_next_page(page_index, marker):
                break

            page_index += 1
            rows, _ = self._wait_for_rows_on_page()

        _log(f"[CONFIRM] Order not found after pagination scan | order={order_code} | last_page={page_index}")
        return None, page_index
