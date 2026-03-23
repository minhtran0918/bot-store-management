from __future__ import annotations

import unittest
from types import SimpleNamespace

from app.constants import TAG_1, TAG_1_1, TAG_1_2, TAG_2, TAG_2_1, TAG_2_2
from app.order_page import OrderPage, _build_match_label, _resolve_product_match_tag


class _FakeLocator:
    def __init__(self, *, count_value: int = 0, nth_map: dict[int, "_FakeLocator"] | None = None,
                 locator_map: dict[str, "_FakeLocator"] | None = None, locator_error: Exception | None = None):
        self._count_value = count_value
        self._nth_map = nth_map or {}
        self._locator_map = locator_map or {}
        self._locator_error = locator_error

    @property
    def first(self) -> "_FakeLocator":
        return self

    def count(self) -> int:
        return self._count_value

    def nth(self, index: int) -> "_FakeLocator":
        return self._nth_map[index]

    def locator(self, selector: str) -> "_FakeLocator":
        if self._locator_error is not None:
            raise self._locator_error
        return self._locator_map.get(selector, _FakeLocator())


class OrderTaggingTestCase(unittest.TestCase):
    def test_no_address_partial_match_uses_tag_2_2(self):
        tag = _resolve_product_match_tag(have_address=False, total_products=7, exact_match=False)
        self.assertEqual(tag, TAG_2_2)

    def test_have_address_partial_match_uses_tag_1_2(self):
        tag = _resolve_product_match_tag(have_address=True, total_products=4, exact_match=False)
        self.assertEqual(tag, TAG_1_2)

    def test_no_address_full_match_4_plus_uses_tag_2_1(self):
        tag = _resolve_product_match_tag(have_address=False, total_products=4, exact_match=True)
        self.assertEqual(tag, TAG_2_1)

    def test_have_address_full_match_1_to_3_uses_tag_1(self):
        tag = _resolve_product_match_tag(have_address=True, total_products=3, exact_match=True)
        self.assertEqual(tag, TAG_1)

    def test_no_address_full_match_1_to_3_uses_tag_2(self):
        tag = _resolve_product_match_tag(have_address=False, total_products=2, exact_match=True)
        self.assertEqual(tag, TAG_2)

    def test_have_address_full_match_4_plus_uses_tag_1_1(self):
        tag = _resolve_product_match_tag(have_address=True, total_products=5, exact_match=True)
        self.assertEqual(tag, TAG_1_1)

    def test_partial_match_label_is_explicit(self):
        self.assertEqual(_build_match_label(6, 7, TAG_2_2), "PARTIAL (6/7)")

    def test_customer_without_any_tag_is_treated_as_normal(self):
        order_page = OrderPage.__new__(OrderPage)
        order_page._cfg = SimpleNamespace(skip_customer_tags=["skip-tag"])

        customer_cell = _FakeLocator(locator_map={"tds-tag": _FakeLocator(count_value=0)})
        row = _FakeLocator(locator_map={"td": _FakeLocator(nth_map={6: customer_cell})})

        self.assertTrue(order_page._is_customer_normal(row))

    def test_customer_with_skip_tag_is_not_normal(self):
        order_page = OrderPage.__new__(OrderPage)
        order_page._cfg = SimpleNamespace(skip_customer_tags=["skip-tag"])

        customer_cell = _FakeLocator(locator_map={
            "tds-tag": _FakeLocator(count_value=1),
            "tds-tag:has-text('skip-tag')": _FakeLocator(count_value=1),
        })
        row = _FakeLocator(locator_map={"td": _FakeLocator(nth_map={6: customer_cell})})

        self.assertFalse(order_page._is_customer_normal(row))

    def test_customer_locator_error_falls_back_to_normal(self):
        order_page = OrderPage.__new__(OrderPage)
        order_page._cfg = SimpleNamespace(skip_customer_tags=["skip-tag"])

        row = _FakeLocator(locator_error=RuntimeError("locator failed"))

        self.assertTrue(order_page._is_customer_normal(row))


if __name__ == "__main__":
    unittest.main()
