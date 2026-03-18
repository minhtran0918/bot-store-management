from __future__ import annotations

import io
import random
import time
import unicodedata
from datetime import datetime
from pathlib import Path
from playwright.sync_api import Page, Locator
from PIL import Image
import re

from .constants import CHECK, COC, ERR, NEW, NO_ADDR, TODO_ADDR, TODO_NO_ADDR


def _log(message: str) -> None:
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {message}")


def _remove_diacritics(text: str) -> str:
    """Remove Vietnamese diacritics and convert to ASCII-safe filename token."""
    nfkd = unicodedata.normalize("NFKD", text)
    ascii_str = "".join(ch for ch in nfkd if not unicodedata.combining(ch))
    # Replace non-alphanumeric (except space/dash/underscore) with nothing
    cleaned = re.sub(r"[^\w\s\-]", "", ascii_str)
    # Collapse whitespace to underscore
    cleaned = re.sub(r"\s+", "_", cleaned).strip("_")
    return cleaned

class OrderPage:
    def __init__(self, page: Page):
        self.page = page

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

    def wait_modal(self, timeout: float = 5000) -> None:
        self.modal().wait_for(timeout=timeout)
        # Wait for modal content to fully load (collapse sections with product info)
        try:
            self.page.locator("div.tds-collapse-content-box").first.wait_for(state="attached", timeout=timeout)
            self.page.wait_for_timeout(800)
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
            "button.\\!rounded-full:has(i.tdsi-send-fill)",
            "button.tds-button-primary.\\!rounded-full",
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
            with self.page.expect_file_chooser() as fc_info:
                image_btn.click(timeout=3000)
            file_chooser = fc_info.value
            file_chooser.set_files([str(p) for p in image_paths])
            self.page.wait_for_timeout(800)
            return True
        except Exception as exc:
            _log(f"  [!] Attach images failed: {exc}")
            return False

    def send_message_to_order(
        self, row: Locator, order_code: str, message: str,
        image_paths: list[Path] | None = None,
        have_address: bool | None = None,
        matched_count: int | None = None,
    ) -> bool:
        try:
            self._dismiss_notifications()
            self.message_button_in_row(row).click(timeout=3000)
            self.page.wait_for_timeout(800)

            # Read partner name early (needed for both message and fallback)
            partner_name = self._read_partner_name() if have_address is not None else ""

            # If have_address is provided, build message with partner name from chat panel
            if have_address is not None:
                message = self._build_message(have_address, matched_count or 0, partner_name)

            # Type text first
            msg_box = self.message_box()
            msg_box.click(timeout=3000)
            msg_box.fill(message)
            self.page.wait_for_timeout(300)

            # Attach images before sending (so text + images go in one message)
            img_count = len(image_paths) if image_paths else 0
            if image_paths:
                self._attach_images_in_chat(image_paths, order_code)

            # Send everything at once
            self.send_message_button().click(timeout=3000)
            send_delay = int((2 + 0.5 * img_count) * 1000)
            self.page.wait_for_timeout(send_delay)

            # Check if message send failed (grey-out + error icon)
            if self._check_message_send_error():
                _log(f"  [!] Inbox message error detected, trying comment fallback...")
                fallback_ok = self._reply_comment_fallback(partner_name)
                if fallback_ok:
                    self.page.wait_for_timeout(random.randint(1000, 3000))

            self.page.keyboard.press("Escape")
            self.page.wait_for_timeout(500)

            msg_short = message[:30] + "..." if len(message) > 30 else message
            _log(f"  SEND MSG: text='{msg_short}' | images={img_count}")
            return True
        except Exception as exc:
            _log(f"  [!] Send message failed: {exc}")
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
                page1.click(timeout=3000)
                self.page.wait_for_timeout(800)
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
            self.page.wait_for_timeout(500)
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
            for raw in re.findall(r"Gia\s*:\s*([\d.,]+)", row_text, flags=re.IGNORECASE):
                prices.extend(self._extract_price_tokens(raw))

        if prices:
            return prices

        # Fallback selector
        product_texts = self.page.locator("div.tds-collapse-content-box span.text-neutral-1-900.font-semibold").all_inner_texts()
        for t in product_texts:
            prices.extend(self._extract_price_tokens(t))
        return prices

    def _extract_product_image_urls_from_modal(self) -> list[tuple[str, str]]:
        """Returns list of (url, product_name) tuples."""
        product_rows = self.page.locator("div.tds-collapse-content-box div.w-full.flex.gap-x-3")
        results: list[tuple[str, str]] = []
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
            # Extract product name from the row text (first line typically)
            try:
                row_text = row_el.inner_text().strip()
                product_name = row_text.split("\n")[0].strip() if row_text else f"product_{i + 1}"
            except Exception:
                product_name = f"product_{i + 1}"
            results.append((src, product_name))
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

    def save_product_images(self, order_code: str, data_dir: Path) -> list[Path]:
        product_dir = data_dir / "product" / order_code
        product_dir.mkdir(parents=True, exist_ok=True)

        items = self._extract_product_image_urls_from_modal()
        saved_paths: list[Path] = []
        total_size = 0
        for i, (url, product_name) in enumerate(items):
            safe_name = _remove_diacritics(product_name) or f"product_{i + 1}"
            file_name = f"{order_code}_{safe_name}.jpg"
            file_path = product_dir / file_name
            if self._download_and_compress_image(url, file_path):
                saved_paths.append(file_path)
                total_size += file_path.stat().st_size

        total_kb = total_size / 1024
        _log(f"  SAVE IMAGE: {len(saved_paths)}/{len(items)} images | total={total_kb:.0f}kb")
        return saved_paths

    def _dismiss_notifications(self) -> None:
        """Close any popup notifications that could intercept clicks."""
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
                self.page.wait_for_timeout(200)
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

    def _evaluate_modal_address_and_product(self) -> tuple[bool, int, int, str]:
        """Returns (have_address, matched_count, total_products, tag)."""
        address_text = self._read_modal_address()
        have_address = bool(address_text)

        note_text = self._read_modal_note()
        note_prices = self._extract_price_tokens(note_text)
        product_prices = self._extract_product_prices_from_modal()

        total_products = len(product_prices)
        matched_count = sum(1 for n, p in zip(note_prices, product_prices) if n == p) if note_prices and product_prices else 0

        # Tag logic
        if not have_address and matched_count == 0:
            tag = TODO_NO_ADDR  # no address + empty product -> manual review
        elif not have_address and matched_count >= 1:
            tag = NO_ADDR       # no address + has product match -> ask for address
        elif have_address and matched_count == 0:
            tag = TODO_ADDR     # have address + empty product -> manual review
        elif matched_count >= 4:
            tag = COC           # have address + 4+ matched
        else:
            tag = CHECK         # have address + 1-3 matched

        return have_address, matched_count, total_products, tag

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

    _NO_ADDR_TEMPLATES = [
        'Dạ chị {name} ! Số lượng đơn chốt đủ bộ\n'
        'Chị "GỬI ĐỊA CHỈ" shop đi đơn ạ ! \n'
        'Chị báo sớm shop cắt tồn soạn hàng cho đỡ thiếu đồ ạ. '
        'Đơn báo trễ hàng tồn kho shop chốt khách khác ạ !',

        'Dạ chị ! Số lượng đơn chốt đủ bộ\n'
        'Chị "GỬI ĐỊA CHỈ" shop đi đơn ạ ! \n'
        'Chị {name} báo sớm shop cắt tồn soạn hàng cho đỡ thiếu đồ ạ. '
        'Đơn báo trễ hàng tồn kho shop chốt khách khác ạ !',

        'Dạ chị {name} ! Số lượng đơn chốt đủ bộ\n'
        'Chị "GỬI ĐỊA CHỈ" shop đi đơn ạ ! \n'
        'Chị báo sớm shop cắt tồn soạn hàng cho đỡ thiếu đồ ạ. '
        'Đơn báo trễ hàng tồn kho shop chốt khách khác ạ ! {name}',
    ]

    _COMMENT_FALLBACK_TEMPLATES = [
        'Dạ chị {name} rep lại shop với ạ ! Shop nhắn chị không được ạ.',
        'Dạ chị {name} rep lại shop với ạ ! Shop gửi tin nhắn cho chị chưa thấy phản hồi ạ.',
        'Dạ chị {name} rep lại shop với ạ ! Tin nhắn bên shop chưa gửi được cho chị ạ.',
        'Dạ chị {name} rep lại shop với ạ ! Bên shop nhắn chị chưa được nên nhờ chị phản hồi giúp ạ.',
        'Dạ chị {name} rep lại shop với ạ ! Shop liên hệ tin nhắn với chị chưa được ạ.',
        'Dạ chị {name} rep lại shop với ạ ! Bên shop gửi tin nhắn cho chị chưa thấy hiển thị ạ.',
        'Dạ chị {name} rep lại shop với ạ ! Shop nhắn chị nhưng hệ thống chưa gửi được ạ.',
        'Dạ chị {name} rep lại shop với ạ ! Tin nhắn shop gửi chị chưa tới được ạ.',
        'Dạ chị {name} rep lại shop với ạ ! Shop liên hệ chị qua tin nhắn chưa được ạ.',
        'Dạ chị {name} rep lại shop với ạ ! Shop nhắn chị nhưng chưa thấy nhận được phản hồi ạ.',
    ]

    def _check_message_send_error(self) -> bool:
        """Check if the last sent message has error (grey-out + exclamation icon)."""
        try:
            # Look for error class on message inner div
            error_msg = self.page.locator(
                "div.message-inner.error, "
                "div.message-inner-medium.error"
            ).last
            if error_msg.count() == 0:
                return False
            # Also check for the error icon nearby
            error_icon = self.page.locator("span.tdsi-info-line.text-error-400").last
            return error_icon.count() > 0
        except Exception:
            return False

    def _reply_comment_fallback(self, partner_name: str) -> bool:
        """When inbox message fails, reply to the first user comment on the post."""
        try:
            # Scroll message area up until the original post (ms-extras-message-item) is visible
            # The container uses flex-col-reverse, so we mouse-wheel scroll up
            scroll_area = self.page.locator("div#scrollMe").first
            post_block = self.page.locator("ms-extras-message-item").first
            if scroll_area.count() > 0:
                box = scroll_area.bounding_box()
                if box:
                    # Hover over center of scroll area
                    cx = box["x"] + box["width"] / 2
                    cy = box["y"] + box["height"] / 2
                    self.page.mouse.move(cx, cy)
                    self.page.wait_for_timeout(300)
                    # Scroll up (negative deltaY) until post block is visible
                    for i in range(30):
                        if post_block.count() > 0 and post_block.is_visible():
                            _log(f"  Scrolled up {i} times to reach post block")
                            break
                        self.page.mouse.wheel(0, -600)
                        self.page.wait_for_timeout(400)
                    self.page.wait_for_timeout(500)

            # Find user comments (is_client class = customer comments)
            user_comments = self.page.locator(
                "div.log-comment.is_client, "
                "div.log-comment.desktop\\:is_client"
            )
            if user_comments.count() == 0:
                _log("  [!] No user comments found for fallback reply")
                return False

            # Click "Phản hồi" on the first user comment
            first_comment = user_comments.first
            reply_btn = first_comment.locator("button:has-text('Phản hồi')").first
            if reply_btn.count() == 0:
                _log("  [!] Reply button not found on first comment")
                return False

            reply_btn.click(timeout=3000)
            self.page.wait_for_timeout(500)

            # Type fallback message into the reply textarea
            reply_textarea = self.page.locator(
                "textarea#inputReply, "
                "textarea[placeholder*='Nhập nội dung trả lời']"
            ).last
            if reply_textarea.count() == 0:
                _log("  [!] Reply textarea not found")
                return False

            name = partner_name or "bạn"
            template = random.choice(self._COMMENT_FALLBACK_TEMPLATES)
            fallback_msg = template.format(name=name)

            reply_textarea.click(timeout=2000)
            reply_textarea.fill(fallback_msg)
            self.page.wait_for_timeout(300)

            # Click send button (the one near the reply textarea)
            send_btn = first_comment.locator(
                "button.tds-button-primary:has(i.tdsi-send-fill), "
                "button:has-text('Gửi')"
            ).last
            if send_btn.count() == 0:
                # Fallback: find any send button visible near reply area
                send_btn = self.page.locator(
                    "button.\\!rounded-full.tds-button-primary:has(i.tdsi-send-fill)"
                ).last
            send_btn.click(timeout=3000)
            self.page.wait_for_timeout(800)

            _log(f"  FALLBACK COMMENT REPLY: '{fallback_msg[:50]}...'")
            return True
        except Exception as exc:
            _log(f"  [!] Fallback comment reply failed: {exc}")
            return False

    def _build_message(self, have_address: bool, matched_count: int, partner_name: str = "") -> str:
        """Build message text based on order conditions."""
        if not have_address:
            template = random.choice(self._NO_ADDR_TEMPLATES)
            name = partner_name or "bạn"
            return template.format(name=name)
        if matched_count >= 4:
            return "Đơn hàng đã xác nhận cọc"
        return "Xin chào!"

    def enrich_collected_rows(self, rows_data: list[dict[str, str]], data_dir: Path | None = None) -> tuple[int, int, int]:
        # Build lookup: order_code -> row_data (only NEW orders)
        new_lookup: dict[str, dict[str, str]] = {}
        for r in rows_data:
            code = str(r.get("Order_Code", "")).strip()
            tag = str(r.get("Tag", "")).strip()
            if code and tag == NEW:
                new_lookup[code] = r

        total = len(new_lookup)
        skipped_existing = len(rows_data) - total
        _log("=" * 60)
        _log(f"ENRICH: {total} NEW orders | skipped {skipped_existing} with existing tags")
        _log("=" * 60)

        processed = 0
        coc_count = 0
        check_count = 0
        no_addr_count = 0
        todo_count = 0
        todo_no_addr_count = 0
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

                if order_code not in new_lookup:
                    continue

                row_data = new_lookup.pop(order_code)
                processed += 1
                customer_name = str(row_data.get("Customer", "")).strip()

                _log("-" * 60)
                _log(f"---- ORDER = {order_code}  ({processed}/{total})  {customer_name} ----")

                order_start = time.time()
                saved_images: list[Path] = []
                try:
                    self._dismiss_notifications()
                    self.open_edit_modal_by_row(row)
                    self.wait_modal(timeout=6000)

                    if not self._verify_modal_order_code(order_code):
                        self._close_edit_modal_safely()
                        raise ValueError(f"modal shows wrong order, expected {order_code}")

                    have_address, matched_count, total_products, resolved_tag = self._evaluate_modal_address_and_product()

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

                    # Step 3: Save images for ALL orders
                    if data_dir is not None:
                        saved_images = self.save_product_images(order_code, data_dir)

                    row_data["Address_Status"] = "VALID" if have_address else "EMPTY"
                    row_data["Match_Product"] = match_label
                    row_data["Tag"] = resolved_tag
                    row_data["Note"] = f"addr={'ok' if have_address else 'empty'} match={matched_count}/{total_products}"

                    self._close_edit_modal_safely()
                    self._dismiss_notifications()

                    # Apply tag
                    if not self._apply_processed_tag_to_order(order_code, resolved_tag):
                        row_data["Tag"] = ERR
                        error_count += 1
                        _log(f"  [!] TAG FAILED: target={resolved_tag}")
                    else:
                        _log(f"  TAG -> {resolved_tag}")

                    if resolved_tag == COC:
                        coc_count += 1
                    elif resolved_tag == CHECK:
                        check_count += 1
                    elif resolved_tag == NO_ADDR:
                        no_addr_count += 1
                    elif resolved_tag == TODO_ADDR:
                        todo_count += 1
                    elif resolved_tag == TODO_NO_ADDR:
                        todo_no_addr_count += 1

                    # Step 4: Send message + images
                    # Only send for NO_ADDR (ask address); COC/CHECK disabled for now
                    if resolved_tag == NO_ADDR:
                        self._dismiss_notifications()
                        msg_row = self.row_by_code(order_code)
                        if msg_row.count() > 0:
                            self.send_message_to_order(
                                msg_row, order_code, "",
                                image_paths=saved_images or None,
                                have_address=have_address,
                                matched_count=matched_count,
                            )
                    else:
                        _log(f"  SKIP MSG: tag={resolved_tag}")

                    order_elapsed = time.time() - order_start
                    _log(f"  DONE ORDER = {order_code} | STT = {processed}/{total} | NAME = {customer_name} | TIME = {order_elapsed:.1f}s")

                except Exception as exc:
                    row_data["Tag"] = ERR
                    row_data["Address_Status"] = ERR
                    row_data["Match_Product"] = ""
                    row_data["Note"] = f"error: {exc}"
                    error_count += 1
                    _log(f"  [!] FAILED: {exc}")
                finally:
                    self._close_edit_modal_safely()

            # All NEW orders processed? Stop early
            if not new_lookup:
                _log(f"[PAGE {page_index}] All NEW orders done")
                break

            marker = self._first_row_marker(rows)
            if not self._go_to_next_page(page_index, marker):
                break
            page_index += 1

        # Mark any remaining unfound orders as error
        for code, rd in new_lookup.items():
            rd["Tag"] = ERR
            rd["Address_Status"] = ERR
            rd["Match_Product"] = ""
            rd["Note"] = "not found in table"
            error_count += 1
            _log(f"  [!] NOT FOUND: {code}")

        total_elapsed = time.time() - enrich_start
        total_min, total_sec = divmod(int(total_elapsed), 60)
        _log("=" * 60)
        _log(
            f"SUMMARY: total={total} | "
            f"[{COC}] = {coc_count}  [{CHECK}] = {check_count}  "
            f"[{NO_ADDR}] = {no_addr_count}  [{TODO_ADDR}] = {todo_count}  [{TODO_NO_ADDR}] = {todo_no_addr_count}  "
            f"[{ERR}] = {error_count} | total_time={total_min}m{total_sec:02d}s"
        )
        _log("=" * 60)
        return processed, coc_count + check_count + no_addr_count + todo_count, error_count

    def _try_add_new_tag_for_row(self, order_cell: Locator, order_code: str) -> tuple[str, bool]:
        tags = self._tag_values_in_order_cell(order_cell)
        if tags:
            return " | ".join(tags), False

        try:
            add_tag_button = order_cell.locator(
                "button[tds-tooltip='Thêm nhãn'], button:has(i.tdsi-price-tag-fill)"
            ).first
            add_tag_button.click(timeout=3000)

            tag_input = self._first([
                ".tds-select-input input.tds-select-search-input:visible",
                "tds-select-search input.tds-select-search-input:visible",
            ])
            tag_input.click(timeout=3000)
            tag_input.fill("")
            tag_input.fill(NEW)
            tag_input.press("Enter")

            confirm_button = self._first([
                "button:has(i.tdsi-check-fill):visible",
                "button:has(span i.tdsi-check-fill):visible",
            ])
            confirm_button.click(timeout=3000)

            self.page.wait_for_timeout(400)
            tags_after = self._tag_values_in_order_cell(order_cell)
            if tags_after:
                return " | ".join(tags_after), False

            _log(f"[TAG] Add NEW did not reflect in row | order_code={order_code}")
            return ERR, True
        except Exception as exc:
            _log(f"[TAG] Add NEW failed | order_code={order_code} | error={exc}")
            return ERR, True

    def _replace_new_with_processed_tag(self, row: Locator, order_code: str, target_tag: str) -> bool:
        order_cell = row.locator("td").nth(4)
        current_tags = self._tag_values_in_order_cell(order_cell)

        if target_tag in current_tags and len(current_tags) == 1:
            return True

        try:
            add_tag_button = order_cell.locator(
                "button[tds-tooltip='Thêm nhãn'], button:has(i.tdsi-price-tag-fill)"
            ).first
            add_tag_button.click(timeout=3000)

            tag_input = self._first([
                ".tds-select-input input.tds-select-search-input:visible",
                "tds-select-search input.tds-select-search-input:visible",
            ])
            tag_input.click(timeout=2000)
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
            ]).click(timeout=3000)

            self.page.wait_for_timeout(300)
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
    ) -> tuple[int, int, int, int]:
        added = 0
        new_tag_count = 0
        existing_tag_count = 0
        error_add_tag_count = 0
        count = rows.count()
        for i in range(count):
            if remaining_limit is not None and added >= remaining_limit:
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

            tags_before = self._tag_values_in_order_cell(order_cell)
            had_existing_tag = bool(tags_before)
            tag_value, add_error = self._try_add_new_tag_for_row(order_cell, order_code)

            if add_error:
                error_add_tag_count += 1
            elif had_existing_tag:
                existing_tag_count += 1
            else:
                new_tag_count += 1

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
            })
            existing_codes.add(order_code)
            added += 1
            _log(f"CSV collect +1: row={len(data)} stt={stt} order_code={order_code} tag={tag_value}")

        return added, new_tag_count, existing_tag_count, error_add_tag_count

    def _go_to_next_page(self, current_page: int, previous_marker: str) -> bool:
        next_btn = self.pagination_next_button()
        if next_btn.count() == 0:
            _log("CSV collect: stop pagination, next-page button not found")
            return False

        if self.pagination_next_disabled():
            _log("CSV collect: stop pagination, next-page button is disabled")
            return False

        _log(f"CSV collect: switching page {current_page} -> {current_page + 1}")
        next_btn.click(timeout=5000)

        for attempt in range(1, 13):
            self.page.wait_for_timeout(350)
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
        _log("[FILTER] Open filter panel")
        self.filter_button().click(timeout=5000)
        _log("[FILTER] Focus campaign select")
        self.campaign_select().click(timeout=5000)
        self.campaign_select().click(timeout=5000)

        # UI is more stable when searching by raw date then pressing Enter.
        campaign_date_text = campaign_label.replace("LIVE", "", 1).strip() if campaign_label.lower().startswith("live") else campaign_label
        search_input = self.campaign_search_input()
        _log(f"[FILTER] Search campaign by date text: {campaign_date_text}")
        search_input.click(timeout=5000)
        search_input.fill("")
        search_input.fill(campaign_date_text)
        search_input.press("Enter")

        _log("[FILTER] Apply filter")
        self.apply_filter_button().click(timeout=5000)
        self.page.wait_for_timeout(800)
        _log(f"[FILTER] Applied campaign filter: {campaign_label}")

    def read_filtered_orders(self, max_records: int | None = None) -> list[dict[str, str]]:
        rows, count = self._wait_for_rows_on_page()
        expected_total = self.pagination_total_count()
        data: list[dict[str, str]] = []
        seen_codes: set[str] = set()
        page_index = 1
        total_new_tags = 0
        total_existing_tags = 0
        total_error_add_tags = 0

        _log(f"CSV collect started: detected {count} table rows on page={page_index}")
        if expected_total is not None:
            _log(f"CSV collect: expected total from tab count={expected_total}")

        while True:
            remaining_limit = None
            if max_records is not None:
                remaining_limit = max(0, max_records - len(data))

            added, new_tag_count, existing_tag_count, error_add_tag_count = self._extract_rows(
                rows,
                seen_codes,
                data,
                remaining_limit=remaining_limit,
            )
            total_new_tags += new_tag_count
            total_existing_tags += existing_tag_count
            total_error_add_tags += error_add_tag_count
            _log(f"CSV collect: page={page_index} added={added} cumulative={len(data)}")

            if max_records is not None and len(data) >= max_records:
                _log(f"CSV collect: reached test cap max_records={max_records}, stop collect early")
                break

            if expected_total is not None and len(data) >= expected_total:
                _log(f"CSV collect: reached expected total={expected_total}, stop pagination")
                break

            marker = self._first_row_marker(rows)
            if not self._go_to_next_page(page_index, marker):
                break

            page_index += 1
            rows, count = self._wait_for_rows_on_page()

        _log(
            f"CSV collect summary: new_tag={total_new_tags} existing_tag={total_existing_tags} "
            f"error_add_tag={total_error_add_tags} total={len(data)}"
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

