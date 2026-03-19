from __future__ import annotations

import io
import math
import random
import time
import traceback
import unicodedata
from datetime import datetime
from pathlib import Path
from playwright.sync_api import Page, Locator
from PIL import Image
import re

from .constants import (
    ERR, RECHECK_TAGS, STATUS_TO_TAG,
    TAG_1, TAG_1_1, TAG_1_2, TAG_2, TAG_2_1, TAG_2_2,
    HAVE_ADDR_LOW_SP, HAVE_ADDR_HIGH_SP, HAVE_ADDR_NO_SP,
    NO_ADDR_LOW_SP, NO_ADDR_HIGH_SP, NO_ADDR_NO_SP,
)
from .bot_config import BotConfig


def _log(message: str) -> None:
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {message}")


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
                return True  # proceed anyway
            modal_code = header.inner_text().strip()
            if modal_code == expected_code:
                return True
            _log(f"  [!] Modal mismatch: expected={expected_code} got={modal_code}")
            return False
        except Exception as exc:
            _log(f"  [!] Modal verify error: {exc}")
            return True  # proceed anyway on error

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
            self.page.wait_for_selector("tds-spin", state="hidden", timeout=10000)
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
                    "tds-spin", state="hidden", timeout=10000
                )
            except Exception:
                pass  # spinner may already be gone
        errors_before = self._count_send_errors()
        self.send_message_button().click(timeout=self._cfg.click_timeout, force=True)
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

    def _extract_price_tokens(self, text: str) -> list[int]:
        tokens: list[int] = []
        for match in re.findall(r"\d[\d.,]*", text or ""):
            digits = re.sub(r"\D", "", match)
            if not digits:
                continue
            value = int(digits)
            if value >= 1000:
                value = value // 1000
            if value > 0:
                tokens.append(value)
        return tokens

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
                current_size = buf.tell()
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

    def save_product_images(self, order_code: str, data_dir: Path, note_prices: list[int] | None = None) -> list[Path]:
        product_dir = data_dir / "product" / order_code
        product_dir.mkdir(parents=True, exist_ok=True)

        items = self._extract_product_image_items_from_modal()
        note_price_set = set(note_prices) if note_prices else None
        saved_paths: list[Path] = []
        total_size = 0
        skipped = 0
        for i, (url, product_name, price) in enumerate(items):
            if note_price_set is not None and price not in note_price_set:
                _log(f"  SKIP IMAGE: {product_name} (price={price} not in note)")
                skipped += 1
                continue
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
            # Close open CDK overlay dropdowns (e.g. tag dropdown left open after tag update)
            if self.page.locator("div.cdk-overlay-backdrop").count() > 0:
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
                    close_buttons.nth(i).click(timeout=500, force=True)
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

    def _evaluate_modal_address_and_product(self) -> tuple[bool, int, int, str, list[int]]:
        """Returns (have_address, matched_count, total_products, tag, note_prices)."""
        address_text = self._read_modal_address()
        have_address = bool(address_text)

        note_text = self._read_modal_note()
        note_prices = self._extract_price_tokens(note_text)
        product_prices = self._extract_product_prices_from_modal()

        total_products = len(product_prices)
        matched_count = sum(1 for n, p in zip(note_prices, product_prices) if n == p) if note_prices and product_prices else 0

        # Tag logic — 6 cases
        if have_address:
            if matched_count == 0:
                status = HAVE_ADDR_NO_SP
            elif matched_count >= 4:
                status = HAVE_ADDR_HIGH_SP
            else:
                status = HAVE_ADDR_LOW_SP
        else:
            if matched_count == 0:
                status = NO_ADDR_NO_SP
            elif matched_count >= 4:
                status = NO_ADDR_HIGH_SP
            else:
                status = NO_ADDR_LOW_SP

        tag = STATUS_TO_TAG[status]
        return have_address, matched_count, total_products, tag, note_prices

    def _close_edit_modal_safely(self) -> None:
        try:
            self.close_button().click(timeout=3000)
        except Exception:
            try:
                self.page.keyboard.press("Escape")
            except Exception:
                pass

    def _read_partner_name(self) -> str:
        """Read partner name from the chat/message panel label."""
        try:
            label = self.page.locator(
                "label.text-black.font-semibold.text-title-1, "
                "label.text-black.font-semibold.text-caption-1"
            ).first
            if label.count() > 0:
                return label.inner_text(timeout=2000).strip()
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
            self.page.wait_for_timeout(1500)
            errors_recheck = self._count_send_errors()
            if errors_before >= 0 and errors_recheck <= errors_before:
                return False
            if errors_recheck == 0:
                return False
            error_msg = self.page.locator(
                "div.message-inner.error, div.message-inner-medium.error"
            ).last
            try:
                _log(f"  [!] Error element HTML: {error_msg.inner_html(timeout=2000)[:300]}")
            except Exception:
                pass
            return True
        except Exception:
            return False

    def _reply_comment_fallback(self, partner_name: str, campaign_label: str = "") -> bool:
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

            first_comment = user_comments.first
            reply_btn = first_comment.locator("button:has-text('Phản hồi')").first
            if reply_btn.count() == 0:
                _log("  [!] Reply button not found")
                return False

            reply_btn.click(timeout=self._cfg.click_timeout)
            self.page.wait_for_timeout(self._cfg.escape_close_ms)

            # Type message into reply textarea
            reply_textarea = self.page.locator(
                "textarea#inputReply, "
                "textarea[placeholder*='Nhập nội dung trả lời']"
            ).last
            if reply_textarea.count() == 0:
                _log("  [!] Reply textarea not found")
                return False

            name = partner_name or "bạn"
            template = random.choice(self._cfg.comment_fallback_templates)
            fallback_msg = template.format(name=name)

            reply_textarea.click(timeout=self._cfg.click_timeout)
            reply_textarea.fill(fallback_msg)
            self.page.wait_for_timeout(self._cfg.text_fill_ms)

            # Click send
            send_btn = first_comment.locator(
                "button.tds-button-primary:has(i.tdsi-send-fill), "
                "button:has-text('Gửi')"
            ).last
            if send_btn.count() == 0:
                send_btn = self.page.locator(
                    "button.\\!rounded-full.tds-button-primary:has(i.tdsi-send-fill)"
                ).last
            send_btn.click(timeout=self._cfg.click_timeout)
            self.page.wait_for_timeout(self._cfg.panel_open_ms)

            _log(f"  COMMENT REPLY SENT: '{fallback_msg[:50]}...'")
            return True
        except Exception as exc:
            _log(f"  [!] Comment reply failed: {exc}")
            _log(f"  [!] Stack trace:\n{traceback.format_exc()}")
            return False

    def _build_ask_address_message(self, partner_name: str = "") -> str:
        """MESS 1: Ask for address (no-address cases)."""
        template = random.choice(self._cfg.ask_address_templates)
        name = partner_name or "bạn"
        return template.format(name=name)

    def _build_deposit_message(self, partner_name: str = "") -> str:
        """MESS 2: Ask for deposit (cases 1.1, 2.1)."""
        name = partner_name or "bạn"
        return self._cfg.deposit_template.format(name=name)

    def enrich_collected_rows(self, rows_data: list[dict[str, str]], data_dir: Path | None = None, campaign_label: str = "") -> tuple[int, int, int]:
        # Build lookup: order_code -> row_data (only orders with no tag or recheck tags 1.2/2.2)
        qualify_lookup: dict[str, dict[str, str]] = {}
        for r in rows_data:
            code = str(r.get("Order_Code", "")).strip()
            tag = str(r.get("Tag", "")).strip()
            if code and (not tag or tag in RECHECK_TAGS):
                qualify_lookup[code] = r

        total = len(qualify_lookup)
        skipped_existing = len(rows_data) - total
        _log("=" * 60)
        _log(f"ENRICH: {total} qualifying orders (no tag / 1.2 / 2.2) | skipped {skipped_existing} with other tags")
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

                if order_code not in qualify_lookup:
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
                    self.wait_modal(timeout=6000)

                    if not self._verify_modal_order_code(order_code):
                        self._close_edit_modal_safely()
                        raise ValueError(f"modal shows wrong order, expected {order_code}")

                    have_address, matched_count, total_products, resolved_tag, note_prices = self._evaluate_modal_address_and_product()

                    # Step 1: CHECK ADDRESS
                    _log(f"  CHECK ADDRESS -> {'VALID' if have_address else 'EMPTY'}")

                    # Step 2: CHECK PRODUCT + NOTE
                    if matched_count >= 4:
                        match_label = f"4+ ({matched_count}/{total_products})"
                    elif matched_count >= 1:
                        match_label = f"1-3 ({matched_count}/{total_products})"
                    else:
                        match_label = f"NO MATCH (0/{total_products})"
                    _log(f"  CHECK PRODUCT -> {match_label}")

                    # Case 1.2/2.2: if still 0 matched on re-check, keep existing recheck tag
                    is_recheck = old_tag in RECHECK_TAGS
                    if resolved_tag in RECHECK_TAGS and is_recheck:
                        # Still no match — keep existing tag unchanged
                        resolved_tag = old_tag
                        _log(f"  RECHECK: still 0 match, keeping tag={old_tag}")

                    # Step 3: Save images (skip for manual-review tags 1.2/2.2; only matched products)
                    if resolved_tag not in RECHECK_TAGS and data_dir is not None:
                        saved_images = self.save_product_images(order_code, data_dir, note_prices)

                    row_data["Address_Status"] = "VALID" if have_address else "EMPTY"
                    row_data["Match_Product"] = match_label
                    row_data["Tag"] = resolved_tag
                    row_data["Note"] = f"addr={'ok' if have_address else 'empty'} match={matched_count}/{total_products}"

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

                    # Step 4: Send images + messages per tag
                    # 1.2/2.2 → skip (manual review, tag only)
                    # TAG 1   → images only
                    # TAG 1.1 → images, MESS 2 (deposit), MESS 3 (comment reply)
                    # TAG 2   → images + MESS 1 (ask address), MESS 3 (comment reply)
                    # TAG 2.1 → images + MESS 1, MESS 2, MESS 3 (comment reply)
                    if resolved_tag in RECHECK_TAGS:
                        _log(f"  SKIP MSG: manual review tag={resolved_tag}")
                    else:
                        self._dismiss_notifications()
                        msg_row = self.row_by_code(order_code)

                        if msg_row.count() > 0:
                            # Open panel ONCE for all messages of this order
                            self.message_button_in_row(msg_row).click(
                                timeout=self._cfg.click_timeout, force=True
                            )
                            self._wait_panel_ready()

                            # Read partner name if needed for MESS 1 or MESS 2
                            partner_name = ""
                            if resolved_tag in (TAG_1_1, TAG_2, TAG_2_1):
                                partner_name = self._read_partner_name()

                            # MESS 1 (ask address) for no-address cases + images
                            msg_text = ""
                            if resolved_tag in (TAG_2, TAG_2_1):
                                msg_text = self._build_ask_address_message(partner_name)
                            self._send_batched_in_open_panel(
                                msg_text, saved_images or [], order_code
                            )

                            # MESS 2: deposit message (cases 1.1, 2.1) — sent in same panel
                            if resolved_tag in (TAG_1_1, TAG_2_1):
                                deposit_msg = self._build_deposit_message(partner_name)
                                self._send_in_panel(deposit_msg, None, order_code)

                            self.page.keyboard.press("Escape")
                            self.page.wait_for_timeout(self._cfg.escape_close_ms)
                        else:
                            _log(f"  [!] Row not found for sending: {order_code}")

                        # MESS 3: reply comment (cases 1.1, 2, 2.1) — controlled by features.enable_comment_reply
                        if self._cfg.enable_comment_reply and resolved_tag in (TAG_1_1, TAG_2, TAG_2_1):
                            self._dismiss_notifications()
                            comment_row = self.row_by_code(order_code)
                            if comment_row.count() > 0:
                                comment_ok = self.reply_comment_to_order(comment_row, order_code, campaign_label=campaign_label)
                                row_data["Comment"] = "ok" if comment_ok else "send_fail"
                            else:
                                row_data["Comment"] = "send_fail"
                                _log(f"  [!] COMMENT: row not found for {order_code}")

                    order_elapsed = time.time() - order_start
                    _log(f"  DONE ORDER = {order_code} | STT = {processed}/{total} | NAME = {customer_name} | TIME = {order_elapsed:.1f}s")

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
            if not qualify_lookup:
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

        total_elapsed = time.time() - enrich_start
        total_min, total_sec = divmod(int(total_elapsed), 60)
        _log("=" * 60)
        tag_summary = "  ".join(f"[{t}]={c}" for t, c in sorted(tag_counts.items()))
        _log(
            f"SUMMARY: total={total} | {tag_summary}  "
            f"[{ERR}]={error_count} | total_time={total_min}m{total_sec:02d}s"
        )
        _log("=" * 60)
        action_count = sum(c for t, c in tag_counts.items() if t not in RECHECK_TAGS)
        return processed, action_count, error_count

    def _is_order_status_nhap(self, row: Locator) -> bool:
        """Check if the order row has status 'Nháp' (Draft)."""
        try:
            status_tag = row.locator("tds-tag:has-text('Nháp')").first
            return status_tag.count() > 0
        except Exception:
            return False

    def _is_customer_binh_thuong(self, row: Locator) -> bool:
        """Check if the customer in the row has label 'Bình thường' (Normal)."""
        try:
            customer_cell = row.locator("td").nth(6)
            label_tag = customer_cell.locator("tds-tag:has-text('Bình thường')").first
            return label_tag.count() > 0
        except Exception:
            return False

    def _replace_new_with_processed_tag(self, row: Locator, order_code: str, target_tag: str) -> bool:
        order_cell = row.locator("td").nth(4)
        current_tags = self._tag_values_in_order_cell(order_cell)

        if target_tag in current_tags and len(current_tags) == 1:
            return True

        try:
            add_tag_button = order_cell.locator(
                "button[tds-tooltip='Thêm nhãn'], button:has(i.tdsi-price-tag-fill)"
            ).first
            add_tag_button.click(timeout=self._cfg.click_timeout)

            tag_input = self._first([
                ".tds-select-input input.tds-select-search-input:visible",
                "tds-select-search input.tds-select-search-input:visible",
            ])
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
                self.page.wait_for_timeout(150)

            # Fallback: batch backspaces without checking tags each time
            tag_count = len(current_tags)
            if tag_count > 0:
                for _ in range(tag_count * 3):
                    tag_input.press("Backspace")
                self.page.wait_for_timeout(100)

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
        """Extract qualifying rows: no tag or recheck tag (1.2/2.2) + Nháp status + Bình thường customer.
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

            # Check tag: must be empty or a recheck tag (1.2/2.2)
            tags = self._tag_values_in_order_cell(order_cell)
            tag_value = tags[0] if tags else ""
            if tags and tag_value not in RECHECK_TAGS:
                skipped += 1
                _log(f"CSV collect SKIP: stt={stt} order={order_code} reason=tag '{tag_value}' not qualifying")
                continue

            # Check order status: must be 'Nháp'
            if not self._is_order_status_nhap(row):
                skipped += 1
                _log(f"CSV collect SKIP: stt={stt} order={order_code} reason=status not 'Nháp'")
                continue

            # Check customer label: must be 'Bình thường'
            if not self._is_customer_binh_thuong(row):
                skipped += 1
                _log(f"CSV collect SKIP: stt={stt} order={order_code} reason=customer not 'Bình thường'")
                continue

            channel_cell = cells.nth(5)
            channel_span = channel_cell.locator("span.ml-2").first
            channel_name = channel_span.inner_text().strip() if channel_span.count() > 0 else channel_cell.inner_text().strip()

            customer_cell = cells.nth(6)
            customer_p = customer_cell.locator("p").first
            customer_name = customer_p.inner_text().strip() if customer_p.count() > 0 else customer_cell.inner_text().strip()

            total_amount = cells.nth(7).inner_text().strip()
            total_qty = cells.nth(8).inner_text().strip()

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

