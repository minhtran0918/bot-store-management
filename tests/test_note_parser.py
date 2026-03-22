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
        mapping = {"A1": 991, "A2": None}
        result = extract_note_prices("A1\n133", mapping)
        self.assertIn(991, result)
        self.assertIn(133, result)

    def test_multiple_codes_replaced(self):
        mapping = {"A1": 991, "A2": 992}
        result = extract_note_prices("A1\nA2", mapping)
        self.assertIn(991, result)
        self.assertIn(992, result)

    def test_code_case_insensitive(self):
        mapping = {"A1": 991}
        result = extract_note_prices("a1\n133", mapping)
        self.assertIn(991, result)

    def test_null_code_ignored(self):
        mapping = {"A1": None}
        result = extract_note_prices("A1\n185", mapping)
        self.assertNotIn(0, result)
        self.assertIn(185, result)

    def test_code_not_partial_match(self):
        """A1 should not match inside 'BA1' or 'A10'."""
        mapping = {"A1": 991}
        result = extract_note_prices("BA1\nA10\nA1", mapping)
        # Only the standalone A1 should be replaced
        self.assertEqual(result, [10, 991])

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
        mapping = {"A1": 991, "A2": 992}
        result = extract_note_prices("A1 0968796393\nA2", mapping)
        self.assertIn(991, result)
        self.assertIn(992, result)

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
        """'49kg' is a weight, not a price. Two remaining prices → ambiguous."""
        result = extract_note_prices("162 158 49kg")
        self.assertEqual(result, [])

    def test_k_suffix_not_kg(self):
        """'185k' is a price (k=thousands), '49kg' is a weight."""
        result = extract_note_prices("185k 49kg")
        self.assertEqual(result, [185])

    # --- Dotted & spaced phone numbers ---

    def test_dotted_phone_excluded(self):
        """'0918.677.633' is a phone with dot separators."""
        result = extract_note_prices("A1 0918.677.633", {"A1": 991})
        self.assertEqual(result, [991])

    def test_spaced_phone_excluded(self):
        """'0947 729 097' is a phone with spaces."""
        result = extract_note_prices("199 0947 729 097")
        self.assertEqual(result, [199])

    # --- A-code with spaces (optional space between letter and digit is valid) ---

    def test_code_with_space_valid(self):
        """'A 1' has optional space between A and digit → recognized as A-code → mapped price."""
        result = extract_note_prices("A 1", {"A1": 991})
        self.assertEqual(result, [991])

    def test_code_with_space_a2_valid(self):
        """'A 2 kem' has optional space → recognized as A-code → mapped price."""
        result = extract_note_prices("A 2 kem", {"A2": 992})
        self.assertEqual(result, [992])

    # --- A-code glued to phone ---

    def test_code_glued_to_phone(self):
        """'A10972643331' → A1 + phone 0972643331."""
        result = extract_note_prices("A10972643331", {"A1": 991})
        self.assertIn(991, result)

    def test_code_with_phone_after_slash(self):
        result = extract_note_prices("A1/0968442599", {"A1": 991})
        self.assertEqual(result, [991])

    def test_code_with_phone_after_plus(self):
        result = extract_note_prices("A1+0337232576", {"A1": 991})
        self.assertEqual(result, [991])

    def test_code_with_dot_phone(self):
        result = extract_note_prices("A1. 0348955227", {"A1": 991})
        self.assertEqual(result, [991])

    def test_code_with_dash(self):
        result = extract_note_prices("A1-m_0982710155", {"A1": 991})
        self.assertEqual(result, [991])

    # --- A-code should NOT match ---

    def test_a11_not_a1(self):
        """A11 is NOT A1 — should not match A1 code."""
        result = extract_note_prices("A11 0962301005", {"A1": 991})
        self.assertNotIn(991, result)

    def test_a10_not_a1(self):
        """A10 is NOT A1."""
        result = extract_note_prices("A10", {"A1": 991})
        self.assertNotIn(991, result)

    def test_a170_a_code_wins(self):
        """A170 → A1 detected + explicit price 70 on same line → A-code wins."""
        result = extract_note_prices("A170 0868587668", {"A1": 991})
        self.assertEqual(result, [991])

    # --- One price per line (quantity matching) ---

    def test_code_plus_explicit_price_same_line(self):
        """'A1 170' → A1-code + explicit price on same line → A-code wins."""
        result = extract_note_prices("A1 170", {"A1": 991})
        self.assertEqual(result, [991])

    def test_a2_plus_explicit_price_same_line(self):
        """'A2 190 dt' → A2-code + explicit price on same line → A-code wins."""
        result = extract_note_prices("A2 190 dt 0379420187", {"A2": 992})
        self.assertEqual(result, [992])

    def test_repeated_price_preserved(self):
        """Same price on multiple lines should appear multiple times."""
        result = extract_note_prices("133\n133")
        self.assertEqual(result, [133, 133])

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
        mapping = {"A1": 991}
        result = extract_note_prices("A1 0832109727\n105 dt 0832109727\n133k 0832109727\n134k 0832109727", mapping)
        self.assertEqual(sorted(result), [105, 133, 134, 991])

    def test_real_a1_a2_mixed(self):
        mapping = {"A1": 991, "A2": 992}
        result = extract_note_prices("A1 0329266618\n135\n133", mapping)
        self.assertEqual(sorted(result), [133, 135, 991])

    def test_real_spaced_phone_with_prices(self):
        result = extract_note_prices("199 0947 729 097\n118k\n133")
        self.assertEqual(sorted(result), [118, 133, 199])

    def test_real_a1_explicit_price_wins(self):
        """'A1 170 0374101059' — A1-code + explicit price → A-code wins."""
        mapping = {"A1": 991}
        result = extract_note_prices("A1 170 0374101059", mapping)
        self.assertEqual(result, [991])

    def test_real_a1_lowercase_size(self):
        mapping = {"A1": 991}
        result = extract_note_prices("a1 size m 0982971613", mapping)
        self.assertIn(991, result)

    def test_real_price_with_sdt(self):
        result = extract_note_prices("199 sdt 0344681555")
        self.assertEqual(result, [199])

    def test_real_ngo_jesn(self):
        result = extract_note_prices("Ngo 162\nJesn dai 174")
        self.assertEqual(sorted(result), [162, 174])

    def test_real_a2_in_note(self):
        mapping = {"A2": 992}
        result = extract_note_prices("165\nA2\n165", mapping)
        self.assertEqual(result, [165, 992, 165])  # duplicates preserved

    def test_real_tri_an_prices(self):
        result = extract_note_prices("tri ân 98\n124")
        self.assertEqual(sorted(result), [98, 124])

    # --- Per-line extraction (1 line = 1 product) ---

    def test_one_price_per_line(self):
        """Multiple prices on one line → ambiguous, extract nothing for that line."""
        result = extract_note_prices("103 0933398421\n123 dsqw 173k 158\n123+158\n158")
        self.assertEqual(result, [103, 158])

    def test_full_match_7_lines(self):
        """7 lines = 7 products, each line has one price."""
        note = "103 0933398421\n123 dsqw\n123+\n173k\n158\n158\n158"
        result = extract_note_prices(note)
        self.assertEqual(result, [103, 123, 123, 173, 158, 158, 158])

    def test_line_count_matters_not_total_prices(self):
        """Line with 3 numbers (no A-code) → ambiguous, extract nothing."""
        result = extract_note_prices("185 133 170")
        self.assertEqual(result, [])


    # --- Two-price ambiguity (extract nothing) ---

    def test_two_prices_ambiguous(self):
        """'185+ 164. 0972363927' → 2 prices (185, 164), ambiguous → []."""
        result = extract_note_prices("185+ 164. 0972363927")
        self.assertEqual(result, [])

    def test_two_prices_with_text(self):
        """'185 ao trang quan zin 158 49kg 0918936227' → 2 prices (185, 158), ambiguous."""
        result = extract_note_prices("185 ao trang quan zin 158 49kg 0918936227")
        self.assertEqual(result, [])

    # --- A-code + explicit price → A-code wins ---

    def test_a2_glued_to_price_wins(self):
        """'A2185/0335729742' → A2 + explicit price 185 → A-code wins."""
        result = extract_note_prices("A2185/0335729742", {"A2": 992})
        self.assertEqual(result, [992])

    def test_a1_slash_price_wins(self):
        """'A1/185 0989898043' → A1 + explicit price 185 → A-code wins."""
        result = extract_note_prices("A1/185 0989898043", {"A1": 991})
        self.assertEqual(result, [991])

    def test_a1_gia_price_wins(self):
        """'A1 giá 185k sđt 0332677603' → A1 + explicit price 185 → A-code wins."""
        result = extract_note_prices("A1 giá 185k sđt 0332677603", {"A1": 991})
        self.assertEqual(result, [991])

    def test_a2_dot_price_wins(self):
        """'A2.185' → A2 + explicit price 185 → A-code wins."""
        result = extract_note_prices("A2.185", {"A2": 992})
        self.assertEqual(result, [992])

    def test_a1_dot_price_wins(self):
        """'A1 .185 .0389026248' → A1 + explicit price 185 → A-code wins."""
        result = extract_note_prices("A1 .185 .0389026248", {"A1": 991})
        self.assertEqual(result, [991])

    def test_a1_space_price_wins(self):
        """'A1 185 0374101059' → A1 + explicit price 185 → A-code wins."""
        result = extract_note_prices("A1 185 0374101059", {"A1": 991})
        self.assertEqual(result, [991])

    # --- Special A-code detection ---

    def test_a185_a_code_wins(self):
        """'A185 0868587668' → A1 detected + explicit price 85 → A-code wins."""
        result = extract_note_prices("A185 0868587668", {"A1": 991})
        self.assertEqual(result, [991])

    def test_a117_a_code_wins(self):
        """'A117/0978971998' → A1 detected + explicit price 17 → A-code wins."""
        result = extract_note_prices("A117/0978971998", {"A1": 991})
        self.assertEqual(result, [991])

    def test_a1_jean(self):
        """'a1 jean' → A1 detected (case insensitive, text suffix), no explicit price."""
        result = extract_note_prices("a1 jean", {"A1": 991})
        self.assertEqual(result, [991])

    def test_a2_kem_full_text_valid(self):
        """'A 2 kem...' → optional space between A and 2 → A2 recognized, no explicit price → mapped price."""
        result = extract_note_prices("A 2 kem..ren kem đơn...e nhé", {"A2": 992})
        self.assertEqual(result, [992])

    # --- New separator / phone patterns ---

    def test_price_with_k_and_phone(self):
        """'185k 0968796393' → 185."""
        result = extract_note_prices("185k 0968796393")
        self.assertEqual(result, [185])

    def test_phone_dot_space_price(self):
        """'0898931929. 185' → 185."""
        result = extract_note_prices("0898931929. 185")
        self.assertEqual(result, [185])

    def test_voi_prefix(self):
        """'Với 185 đầm trắng' → 185."""
        result = extract_note_prices("Với 185 đầm trắng")
        self.assertEqual(result, [185])

    def test_price_space_phone(self):
        """'185 0386870095' → 185."""
        result = extract_note_prices("185 0386870095")
        self.assertEqual(result, [185])

    def test_price_dash_phone(self):
        """'160-0938087170' → 160."""
        result = extract_note_prices("160-0938087170")
        self.assertEqual(result, [160])

    def test_price_space_slash_phone(self):
        """'185 /0374752624' → 185."""
        result = extract_note_prices("185 /0374752624")
        self.assertEqual(result, [185])

    def test_price_dash_text_phone(self):
        """'185- váy trắng 0395822203' → 185."""
        result = extract_note_prices("185- váy trắng 0395822203")
        self.assertEqual(result, [185])

    def test_price_comma_phone(self):
        """'185, 0353407957' → 185."""
        result = extract_note_prices("185, 0353407957")
        self.assertEqual(result, [185])

    def test_price_text_kem(self):
        """'Chấm bi kem 185 0366408205' → 185."""
        result = extract_note_prices("Chấm bi kem 185 0366408205")
        self.assertEqual(result, [185])

    def test_price_dash_phone_no_space(self):
        """'185-0948676491' → 185."""
        result = extract_note_prices("185-0948676491")
        self.assertEqual(result, [185])

    def test_price_dot_phone_no_space(self):
        """'185.0328019689' → 185 (dot-separated phone removed)."""
        result = extract_note_prices("185.0328019689")
        self.assertEqual(result, [185])

    def test_price_at_phone(self):
        """'185 @0905836873' → 185."""
        result = extract_note_prices("185 @0905836873")
        self.assertEqual(result, [185])

    def test_price_adjacent_phone_185(self):
        """'1850979404214' → 185 (phone 0979404214 glued after price)."""
        result = extract_note_prices("1850979404214")
        self.assertEqual(result, [185])

    def test_price_adjacent_phone_165_trailing_dot(self):
        """'1650979404214.' → 165 (phone 0979404214 glued after price, trailing dot)."""
        result = extract_note_prices("1650979404214.")
        self.assertEqual(result, [165])


if __name__ == "__main__":
    unittest.main()

