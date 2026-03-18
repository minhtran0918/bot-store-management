import tempfile
import unittest
from pathlib import Path

from features.confirm_order import load_order_codes_from_csv


class ConfirmCsvTestCase(unittest.TestCase):
    def test_load_order_codes_from_csv_deduplicates_and_skips_blank(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            csv_path = Path(tmp_dir) / "orders_test.csv"
            csv_path.write_text(
                "Order_Code,Customer\n"
                "2601,A\n"
                ",B\n"
                "2602,C\n"
                "2601,D\n",
                encoding="utf-8-sig",
            )

            codes = load_order_codes_from_csv(csv_path)

        self.assertEqual(codes, ["2601", "2602"])

    def test_load_order_codes_from_csv_requires_order_code_header(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            csv_path = Path(tmp_dir) / "orders_test.csv"
            csv_path.write_text("No,Customer\n1,A\n", encoding="utf-8-sig")

            with self.assertRaises(ValueError):
                load_order_codes_from_csv(csv_path)


if __name__ == "__main__":
    unittest.main()

