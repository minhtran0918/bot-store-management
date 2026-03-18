import unittest
from datetime import date

from app.cli_helpers import resolve_campaign_date, build_campaign_label


class CampaignCliTestCase(unittest.TestCase):
    def test_resolve_yesterday_keyword(self):
        resolved = resolve_campaign_date("yesterday", 2026, now_date=date(2026, 3, 15))
        self.assertEqual(resolved, "14/3/2026")

    def test_resolve_today_keyword(self):
        resolved = resolve_campaign_date("today", 2026, now_date=date(2026, 3, 15))
        self.assertEqual(resolved, "15/3/2026")

    def test_resolve_day_month(self):
        resolved = resolve_campaign_date("14/3", 2026, now_date=date(2026, 3, 15))
        self.assertEqual(resolved, "14/3/2026")

    def test_build_label_from_keyword(self):
        label = build_campaign_label("yesterday", 2026)
        self.assertTrue(label.startswith("LIVE "))

    def test_build_label_from_live_text(self):
        self.assertEqual(build_campaign_label("LIVE 14/3/2026", 2026), "LIVE 14/3/2026")


if __name__ == "__main__":
    unittest.main()

