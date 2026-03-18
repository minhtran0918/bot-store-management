import tempfile
import unittest
from pathlib import Path

from app.store import save_filtered_orders


class ExportOrdersTestCase(unittest.TestCase):
    def test_save_filtered_orders_writes_expected_headers_and_rows(self):
        rows = [
            {
                "No": "3082",
                "Order_Code": "260303094",
                "Tag": "",
                "Channel": "Linh Đan Shop",
                "Customer": "Lợi Phạm",
                "Total_Amount": "195.000 ₫",
                "Total_Qty": "1",
                "Address_Status": "",
                "Note": "",
                "Match_Product": "",
                "Decision": "",
            }
        ]

        with tempfile.TemporaryDirectory() as tmp_dir:
            output_path = save_filtered_orders(rows, "LIVE 14/3/2026", output_dir=Path(tmp_dir))
            content = output_path.read_text(encoding="utf-8-sig")

        self.assertIn("No,Order_Code,Tag,Channel,Customer,Total_Amount,Total_Qty,Address_Status,Note,Match_Product,Decision", content)
        self.assertIn("3082,260303094,,Linh Đan Shop,Lợi Phạm,195.000 ₫,1", content)


if __name__ == "__main__":
    unittest.main()

