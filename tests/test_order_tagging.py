from __future__ import annotations

import unittest

from app.constants import TAG_1, TAG_1_1, TAG_1_2, TAG_2, TAG_2_1, TAG_2_2
from app.order_page import _build_match_label, _resolve_product_match_tag


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


if __name__ == "__main__":
    unittest.main()
