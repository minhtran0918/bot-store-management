"""Tests for app.note_parser — extract_note_prices."""
from __future__ import annotations

import unittest

from app.note_parser import extract_note_prices


class TestExtractNotePrices(unittest.TestCase):
    """Note price extraction from Vietnamese ecommerce order notes."""

    # --- Basic number extraction ---

    def test_single_price(self):
        self.assertEqual(extract_note_prices("185"), [185])

    def test_multiple_prices(self):
        self.assertEqual(extract_note_prices("185\n133"), [185, 133])

    def test_price_with_k_suffix(self):
        self.assertEqual(extract_note_prices("185k"), [185])

    def test_price_with_K_suffix(self):
        self.assertEqual(extract_note_prices("185K"), [185])

    # --- Phone number exclusion ---

    def test_phone_number_excluded(self):
        """Phone numbers (10+ digits starting with 0) should be excluded."""
        result = extract_note_prices("185 0968796393\n133")
        self.assertIn(185, result)
        self.assertIn(133, result)
        self.assertNotIn(968, result)
        self.assertNotIn(96879, result)

    def test_phone_with_slash_separator(self):
        result = extract_note_prices("185/0968796393\n133")
        self.assertIn(185, result)
        self.assertIn(133, result)

    def test_phone_with_plus_separator(self):
        result = extract_note_prices("185+0379549302")
        self.assertIn(185, result)

    def test_phone_at_start(self):
        result = extract_note_prices("0868474748/ 185 k")
        self.assertIn(185, result)

    def test_phone_at_start_no_space(self):
        result = extract_note_prices("0868474748/  185")
        self.assertIn(185, result)

    # --- Text mixed with prices ---

    def test_price_with_trailing_text(self):
        """'185da' — the number 185 should still be extracted."""
        result = extract_note_prices("185da\n133")
        self.assertIn(185, result)
        self.assertIn(133, result)

    def test_price_with_vietnamese_text_prefix(self):
        result = extract_note_prices("Đầm chấm bi 185 + 0397780384")
        self.assertIn(185, result)

    def test_price_with_name_prefix(self):
        result = extract_note_prices("Ngo 185")
        self.assertIn(185, result)

    def test_price_with_jeans_prefix(self):
        result = extract_note_prices("Jesn dai 185")
        self.assertIn(185, result)

    def test_price_with_plus_and_phone(self):
        result = extract_note_prices("185+0379549302")
        self.assertIn(185, result)

    # --- A1-A9 code mapping ---

    def test_a1_code_replaced(self):
        mapping = {"A1": 150, "A2": None}
        result = extract_note_prices("A1\n133", mapping)
        self.assertIn(150, result)
        self.assertIn(133, result)

    def test_multiple_codes_replaced(self):
        mapping = {"A1": 150, "A2": 200}
        result = extract_note_prices("A1\nA2", mapping)
        self.assertIn(150, result)
        self.assertIn(200, result)

    def test_code_case_insensitive(self):
        mapping = {"A1": 150}
        result = extract_note_prices("a1\n133", mapping)
        self.assertIn(150, result)

    def test_null_code_ignored(self):
        mapping = {"A1": None}
        result = extract_note_prices("A1\n185", mapping)
        self.assertNotIn(0, result)
        self.assertIn(185, result)

    def test_code_not_partial_match(self):
        """A1 should not match inside 'BA1' or 'A10'."""
        mapping = {"A1": 150}
        result = extract_note_prices("BA1 A10 A1", mapping)
        # Only the standalone A1 should be replaced
        self.assertIn(150, result)

    # --- Edge cases ---

    def test_empty_text(self):
        self.assertEqual(extract_note_prices(""), [])

    def test_none_text(self):
        self.assertEqual(extract_note_prices(None), [])

    def test_no_numbers(self):
        self.assertEqual(extract_note_prices("hello world"), [])

    def test_formatted_price_with_dot_thousands(self):
        """'185.000' should normalize to 185."""
        result = extract_note_prices("185.000")
        self.assertIn(185, result)

    def test_formatted_price_with_comma_thousands(self):
        """'185,000' should normalize to 185."""
        result = extract_note_prices("185,000")
        self.assertIn(185, result)

    def test_zero_excluded(self):
        """Value 0 should not be in results."""
        result = extract_note_prices("0")
        self.assertEqual(result, [])

    # --- Real-world patterns from user examples ---

    def test_real_pattern_1(self):
        """'185 0968796393\n133' → [185, 133]"""
        result = extract_note_prices("185 0968796393\n133")
        self.assertEqual(sorted(result), [133, 185])

    def test_real_pattern_2(self):
        """'185k 0968796393\n133'"""
        result = extract_note_prices("185k 0968796393\n133")
        self.assertIn(185, result)
        self.assertIn(133, result)

    def test_real_pattern_3(self):
        """'Đầm chấm bi 185 + 0397780384'"""
        result = extract_note_prices("Đầm chấm bi 185 + 0397780384")
        self.assertIn(185, result)

    def test_real_pattern_4(self):
        """'0868474748/ 185 k'"""
        result = extract_note_prices("0868474748/ 185 k")
        self.assertIn(185, result)

    def test_real_pattern_5(self):
        """'0868474748/  185'"""
        result = extract_note_prices("0868474748/  185")
        self.assertIn(185, result)

    def test_real_pattern_with_a_code(self):
        """Note contains A1 code that maps to price."""
        mapping = {"A1": 185, "A2": 133}
        result = extract_note_prices("A1 0968796393\nA2", mapping)
        self.assertIn(185, result)
        self.assertIn(133, result)

    def test_matching_against_product_prices(self):
        """Integration-style: note prices should match against product price list."""
        product_prices = [185, 133]
        note_prices = extract_note_prices("185 0968796393\n133")
        matched = set(note_prices) & set(product_prices)
        self.assertEqual(matched, {185, 133})

    # --- Time / weight exclusion ---

    def test_time_pattern_excluded(self):
        """'7h30' should not extract 7 or 30 — it's a time, not prices."""
        self.assertEqual(extract_note_prices("7h30"), [])

    def test_time_in_sentence_excluded(self):
        """Time in a sentence should not produce prices."""
        result = extract_note_prices("mai e báo bên giao hàng 7h30 tối")
        self.assertEqual(result, [])

    def test_weight_kg_excluded(self):
        """'49kg' is a weight, not a price."""
        result = extract_note_prices("162 158 49kg")
        self.assertEqual(result, [162, 158])

    def test_k_suffix_not_kg(self):
        """'185k' is a price (k=thousands), '49kg' is a weight."""
        result = extract_note_prices("185k 49kg")
        self.assertEqual(result, [185])

    # --- Dotted & spaced phone numbers ---

    def test_dotted_phone_excluded(self):
        """'0918.677.633' is a phone with dot separators."""
        result = extract_note_prices("A1 0918.677.633", {"A1": 170})
        self.assertEqual(result, [170])

    def test_spaced_phone_excluded(self):
        """'0947 729 097' is a phone with spaces."""
        result = extract_note_prices("199 0947 729 097")
        self.assertEqual(result, [199])

    # --- A-code with spaces ---

    def test_code_with_space(self):
        """'A 1' should match A1 code."""
        result = extract_note_prices("A 1", {"A1": 170})
        self.assertIn(170, result)

    def test_code_with_space_a2(self):
        """'A 2 kem' should match A2 code."""
        result = extract_note_prices("A 2 kem", {"A2": 190})
        self.assertIn(190, result)

    # --- A-code glued to phone ---

    def test_code_glued_to_phone(self):
        """'A10972643331' → A1 + phone 0972643331."""
        result = extract_note_prices("A10972643331", {"A1": 170})
        self.assertIn(170, result)

    def test_code_with_phone_after_slash(self):
        result = extract_note_prices("A1/0968442599", {"A1": 170})
        self.assertEqual(result, [170])

    def test_code_with_phone_after_plus(self):
        result = extract_note_prices("A1+0337232576", {"A1": 170})
        self.assertEqual(result, [170])

    def test_code_with_dot_phone(self):
        result = extract_note_prices("A1. 0348955227", {"A1": 170})
        self.assertEqual(result, [170])

    def test_code_with_dash(self):
        result = extract_note_prices("A1-m_0982710155", {"A1": 170})
        self.assertEqual(result, [170])

    # --- A-code should NOT match ---

    def test_a11_not_a1(self):
        """A11 is NOT A1 — should not match A1 code."""
        result = extract_note_prices("A11 0962301005", {"A1": 170})
        self.assertNotIn(170, result)

    def test_a10_not_a1(self):
        """A10 is NOT A1."""
        result = extract_note_prices("A10", {"A1": 170})
        self.assertNotIn(170, result)

    def test_a170_not_a1(self):
        """A170 should not match A1 — the '70' after A1 is not a phone."""
        result = extract_note_prices("A170 0868587668", {"A1": 170})
        # A1 should NOT match (170 is extracted as standalone number)
        self.assertIn(170, result)
        self.assertEqual(len(result), 1)

    # --- Deduplication ---

    def test_code_plus_explicit_price_deduplicated(self):
        """'A1 170' with A1→170 should return [170], not [170, 170]."""
        result = extract_note_prices("A1 170", {"A1": 170})
        self.assertEqual(result, [170])

    def test_a2_plus_explicit_price_deduplicated(self):
        result = extract_note_prices("A2 190 dt 0379420187", {"A2": 190})
        self.assertEqual(result, [190])

    def test_repeated_price_deduplicated(self):
        """Same price on multiple lines should appear once."""
        result = extract_note_prices("133\n133")
        self.assertEqual(result, [133])

    # --- Size / text suffixes ---

    def test_price_with_size_suffix(self):
        """'140 L' — size L after price."""
        self.assertEqual(extract_note_prices("140 L"), [140])

    def test_price_with_bo_suffix(self):
        """'158 bộ' — Vietnamese text after price."""
        self.assertIn(158, extract_note_prices("158 bộ"))

    def test_price_with_don_don(self):
        """'133 dồn đơn' — Vietnamese text after price."""
        self.assertIn(133, extract_note_prices("133 dồn đơn"))

    def test_m_prefix(self):
        """'M158' — M prefix before price."""
        self.assertIn(158, extract_note_prices("M158"))

    # --- Colon / dot separator ---

    def test_colon_before_phone(self):
        """'Set 163:0963747839' — colon separating price and phone."""
        result = extract_note_prices("Set 163:0963747839")
        self.assertIn(163, result)

    def test_dot_then_phone(self):
        """'144. 0358395433' — price with dot then phone."""
        self.assertIn(144, extract_note_prices("144. 0358395433"))

    # --- No-price text ---

    def test_pure_text_no_price(self):
        self.assertEqual(extract_note_prices("Cho mình set sau 0987679926"), [])

    def test_question_text_no_price(self):
        self.assertEqual(extract_note_prices("E có bộ mặc ko chị"), [])

    def test_complaint_no_price(self):
        result = extract_note_prices("Shop ơi đơn em mới nhận mà bị chật shop hỗ trợ đổi trả giúp em")
        self.assertEqual(result, [])

    # --- Bulk real-world patterns ---

    def test_real_multiline_prices(self):
        result = extract_note_prices("157\n180\n173")
        self.assertEqual(sorted(result), [157, 173, 180])

    def test_real_multiple_k_prices(self):
        result = extract_note_prices("159k\n158k\n175k")
        self.assertEqual(sorted(result), [158, 159, 175])

    def test_real_plus_phone_multiple(self):
        result = extract_note_prices("145+0379549302\n165+0379549302\n118+0379549302\n144+0379549302")
        self.assertEqual(sorted(result), [118, 144, 145, 165])

    def test_real_phone_at_line_start_with_prices(self):
        result = extract_note_prices("0898931929. 166\n157")
        self.assertEqual(sorted(result), [157, 166])

    def test_real_a1_with_multiple_prices(self):
        mapping = {"A1": 170}
        result = extract_note_prices("A1 0832109727\n105 dt 0832109727\n133k 0832109727\n134k 0832109727", mapping)
        self.assertEqual(sorted(result), [105, 133, 134, 170])

    def test_real_a1_a2_mixed(self):
        mapping = {"A1": 170, "A2": 190}
        result = extract_note_prices("A1 0329266618\n135\n133", mapping)
        self.assertEqual(sorted(result), [133, 135, 170])

    def test_real_spaced_phone_with_prices(self):
        result = extract_note_prices("199 0947 729 097\n118k\n133")
        self.assertEqual(sorted(result), [118, 133, 199])

    def test_real_a1_explicit_170(self):
        """'A1 170 0374101059' — A1 maps to 170, explicit 170 should be deduplicated."""
        mapping = {"A1": 170}
        result = extract_note_prices("A1 170 0374101059", mapping)
        self.assertEqual(result, [170])

    def test_real_a1_lowercase_size(self):
        mapping = {"A1": 170}
        result = extract_note_prices("a1 size m 0982971613", mapping)
        self.assertIn(170, result)

    def test_real_price_with_sdt(self):
        result = extract_note_prices("199 sdt 0344681555")
        self.assertEqual(result, [199])

    def test_real_ngo_jesn(self):
        result = extract_note_prices("Ngo 162\nJesn dai 174")
        self.assertEqual(sorted(result), [162, 174])

    def test_real_a2_in_note(self):
        mapping = {"A2": 190}
        result = extract_note_prices("165\nA2\n165", mapping)
        self.assertIn(165, result)
        self.assertIn(190, result)
        self.assertEqual(len(result), 2)  # 165 deduplicated

    def test_real_tri_an_prices(self):
        result = extract_note_prices("tri ân 98\n124")
        self.assertEqual(sorted(result), [98, 124])


if __name__ == "__main__":
    unittest.main()
