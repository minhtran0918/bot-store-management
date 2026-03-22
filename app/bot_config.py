"""Typed accessor for bot-specific configuration.

All timeouts, templates, and feature flags are read from config.yaml.
Timeouts and message templates have no defaults — missing keys cause a startup error.
"""
from __future__ import annotations


class BotConfig:
    """Wraps the loaded config dict and exposes named properties with sensible defaults."""

    def __init__(self, config: dict):
        self._bot: dict = config.get("bot") or {}
        self._features: dict = config.get("features") or {}
        self._timeouts: dict = config.get("timeouts") or {}
        self._messages: dict = config.get("messages") or {}
        self._keywords: dict = config.get("keywords") or {}
        self._validate_timeouts()
        self._validate_messages()

    # Required timeout keys — must all be present in config.yaml timeouts section
    _REQUIRED_TIMEOUTS = [
        "click", "click_slow", "modal", "panel_open", "text_fill",
        "image_attach", "send_post_base",
        "send_post_per_image", "overlay_dismiss", "tag_update",
        "pagination", "filter_search", "filter_apply", "escape_close",
        "table_load", "spinner_hide", "error_recheck", "comment_reply_post",
        "notification_click", "inner_text_read", "tag_clear", "tag_backspace",
        "bill_create_step", "bill_image_load",
    ]

    # Required message keys — must all be present in config.yaml messages section
    _REQUIRED_MESSAGES = [
        "ask_address_templates", "ask_address_no_product_templates", "deposit_template",
        "oos_line_format", "oos_templates", "comment_fallback_templates",
    ]

    def _validate_timeouts(self) -> None:
        """Check all required timeout keys exist in config. Raises on missing keys."""
        missing = [k for k in self._REQUIRED_TIMEOUTS if k not in self._timeouts]
        if missing:
            raise ValueError(
                f"Missing required timeout(s) in config.yaml [timeouts]: {', '.join(missing)}"
            )

    def _validate_messages(self) -> None:
        """Check all required message keys exist in config. Raises on missing keys."""
        missing = [k for k in self._REQUIRED_MESSAGES if k not in self._messages]
        if missing:
            raise ValueError(
                f"Missing required message(s) in config.yaml [messages]: {', '.join(missing)}"
            )

    def _t(self, key: str) -> int:
        """Read an integer timeout from the timeouts section. Raises if missing."""
        val = self._timeouts.get(key)
        if val is None:
            raise ValueError(f"Missing required timeout '{key}' in config.yaml [timeouts]")
        try:
            return int(val)
        except (TypeError, ValueError):
            raise ValueError(f"Invalid timeout value for '{key}' in config.yaml: {val!r}")

    # ------------------------------------------------------------------
    # Bot settings
    # ------------------------------------------------------------------

    @property
    def test_max_collect_records(self) -> int | None:
        """Max rows to collect during a run. None = unlimited (full run)."""
        val = self._bot.get("test_max_collect_records")
        if val is None:
            return None
        try:
            return int(val)
        except (TypeError, ValueError):
            return None

    @property
    def max_images_per_send(self) -> int:
        """Max images per send message. Larger sets are split into batches."""
        try:
            return max(1, int(self._bot.get("max_images_per_send", 3)))
        except (TypeError, ValueError):
            return 3

    @property
    def test_order_ids(self) -> list[str]:
        """Whitelist of order codes to process. Empty list = process all."""
        val = self._bot.get("test_order_ids")
        if val and isinstance(val, list):
            return [str(v).strip() for v in val if v]
        return []

    @property
    def reload_every_n_orders(self) -> int:
        """Reload page every N processed orders. 0 = disabled."""
        try:
            return max(0, int(self._bot.get("reload_every_n_orders", 4)))
        except (TypeError, ValueError):
            return 4

    @property
    def comment_reply_max_retries(self) -> int:
        """Number of extra retry attempts for comment reply on failure (0 = no retry)."""
        try:
            return max(0, int(self._bot.get("comment_reply_max_retries", 0)))
        except (TypeError, ValueError):
            return 0

    @property
    def low_delivery_rate_pct(self) -> int:
        """Delivery success rate threshold (%). Below this → TAG 0 (skip). Default 60."""
        try:
            return max(0, min(100, int(self._bot.get("low_delivery_rate_pct", 60))))
        except (TypeError, ValueError):
            return 60

    # ------------------------------------------------------------------
    # Keywords / lists
    # ------------------------------------------------------------------

    @property
    def skip_customer_tags(self) -> list[str]:
        """Customer tags that trigger TAG 0 (skip processing)."""
        val = self._keywords.get("skip_customer_tags")
        if val and isinstance(val, list):
            return [str(v).strip() for v in val if v]
        return []

    # ------------------------------------------------------------------
    # Feature flags
    # ------------------------------------------------------------------

    @property
    def enable_comment_reply(self) -> bool:
        """MESS 3: reply to the customer's FB comment. Disable when the feature is buggy."""
        return bool(self._features.get("enable_comment_reply", False))

    @property
    def enable_send_message(self) -> bool:
        """MESS 1/2: send inbox text messages (ask address, deposit)."""
        return bool(self._features.get("enable_send_message", True))

    @property
    def enable_send_product_image(self) -> bool:
        """Send product images to customer."""
        return bool(self._features.get("enable_send_product_image", True))

    @property
    def enable_send_bill_image(self) -> bool:
        """Send sales bill image (phiếu mua hàng) for TAG 1."""
        return bool(self._features.get("enable_send_bill_image", True))

    @property
    def enable_send_oos_image(self) -> bool:
        """Send product images excluding OOS items (TAG 1.4/2.4)."""
        return bool(self._features.get("enable_send_oos_image", True))

    @property
    def enable_send_oos_message(self) -> bool:
        """Send OOS notification message listing out-of-stock products (TAG 1.4/2.4)."""
        return bool(self._features.get("enable_send_oos_message", True))

    # ------------------------------------------------------------------
    # Timeouts — Playwright click/wait timeouts (milliseconds)
    # ------------------------------------------------------------------

    @property
    def click_timeout(self) -> int:
        """General element click timeout."""
        return self._t("click")

    @property
    def click_slow_timeout(self) -> int:
        """Slow elements (filter panel, Apply button)."""
        return self._t("click_slow")

    @property
    def modal_timeout(self) -> int:
        """Wait for order edit modal to appear."""
        return self._t("modal")

    @property
    def panel_open_ms(self) -> int:
        """Wait after opening the message panel."""
        return self._t("panel_open")

    @property
    def text_fill_ms(self) -> int:
        """Wait after filling a textarea."""
        return self._t("text_fill")

    @property
    def image_attach_ms(self) -> int:
        """Wait after the file chooser sets image files."""
        return self._t("image_attach")

    @property
    def send_post_base_ms(self) -> int:
        """Base wait after clicking the send button."""
        return self._t("send_post_base")

    @property
    def send_post_per_image_ms(self) -> int:
        """Additional ms per image to wait AFTER clicking send."""
        return self._t("send_post_per_image")

    @property
    def overlay_dismiss_ms(self) -> int:
        """Wait after closing a notification or overlay."""
        return self._t("overlay_dismiss")

    @property
    def tag_update_ms(self) -> int:
        """Wait after a tag is applied."""
        return self._t("tag_update")

    @property
    def pagination_ms(self) -> int:
        """Wait after navigating to the next/previous page."""
        return self._t("pagination")

    @property
    def filter_search_ms(self) -> int:
        """Wait after typing in the campaign filter search input (results load)."""
        return self._t("filter_search")

    @property
    def filter_apply_ms(self) -> int:
        """Wait after clicking the Apply filter button."""
        return self._t("filter_apply")

    @property
    def escape_close_ms(self) -> int:
        """Wait after pressing Escape to close a panel."""
        return self._t("escape_close")

    @property
    def table_load_ms(self) -> int:
        """Wait for order table rows to appear after navigation."""
        return self._t("table_load")

    @property
    def spinner_hide_ms(self) -> int:
        """Wait for upload spinner to disappear."""
        return self._t("spinner_hide")

    @property
    def error_recheck_ms(self) -> int:
        """Wait before rechecking if a send error is transient."""
        return self._t("error_recheck")

    @property
    def comment_reply_post_ms(self) -> int:
        """Wait after sending a comment reply."""
        return self._t("comment_reply_post")

    @property
    def notification_click_ms(self) -> int:
        """Click timeout for notification close buttons."""
        return self._t("notification_click")

    @property
    def inner_text_read_ms(self) -> int:
        """Timeout for reading element inner text."""
        return self._t("inner_text_read")

    @property
    def tag_clear_ms(self) -> int:
        """Wait after clearing tags via JS."""
        return self._t("tag_clear")

    @property
    def tag_backspace_ms(self) -> int:
        """Wait after backspace clearing tags."""
        return self._t("tag_backspace")

    @property
    def bill_create_step_ms(self) -> int:
        """Wait between steps when creating sales bill."""
        return self._t("bill_create_step")

    @property
    def bill_image_load_ms(self) -> int:
        """Wait for bill image to load into message box."""
        return self._t("bill_image_load")

    # ------------------------------------------------------------------
    # Message templates
    # ------------------------------------------------------------------

    def _str_list(self, key: str) -> list[str]:
        """Read a list[str] from messages section. Raises if missing or invalid."""
        val = self._messages.get(key)
        if not val or not isinstance(val, list) or not all(isinstance(s, str) for s in val):
            raise ValueError(
                f"Missing or invalid '{key}' in config.yaml [messages]: expected a non-empty list of strings"
            )
        return [s.rstrip("\n") for s in val]

    def _str_val(self, key: str) -> str:
        """Read a string from messages section. Raises if missing or invalid."""
        val = self._messages.get(key)
        if not val or not isinstance(val, str):
            raise ValueError(
                f"Missing or invalid '{key}' in config.yaml [messages]: expected a non-empty string"
            )
        return val.rstrip("\n")

    @property
    def ask_address_templates(self) -> list[str]:
        """MESS 1: ask-for-address templates. Uses {name} placeholder."""
        return self._str_list("ask_address_templates")

    @property
    def ask_address_no_product_templates(self) -> list[str]:
        """MESS 1 (case 2.3): ask-for-address templates when no products in order. Uses {name} placeholder."""
        return self._str_list("ask_address_no_product_templates")

    @property
    def deposit_template(self) -> str:
        """MESS 2: deposit request template. Uses {name} placeholder."""
        return self._str_val("deposit_template")

    @property
    def oos_line_format(self) -> str:
        """Format string for each OOS product line. Placeholders: {price}, {name}, {forecast}."""
        return self._str_val("oos_line_format")

    @property
    def oos_templates(self) -> list[str]:
        """OOS notification templates. Uses {name} and {oos_lines} placeholders."""
        return self._str_list("oos_templates")

    @property
    def comment_fallback_templates(self) -> list[str]:
        """MESS 3: FB comment reply templates. Uses {name} placeholder."""
        return self._str_list("comment_fallback_templates")
