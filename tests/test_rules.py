import unittest
from datetime import datetime, timedelta

from app.rules import decide_action, should_resend_ask


class RulesTestCase(unittest.TestCase):
    def test_pickup_wins(self):
        action = decide_action("khach mai ghé lấy", "", None)
        self.assertEqual(action, "pickup")

    def test_send_ask_when_no_address_and_no_state(self):
        action = decide_action("", "", None)
        self.assertEqual(action, "send_ask_address")

    def test_skip_when_recently_asked(self):
        existing = {
            "state": "asked_address",
            "last_action_at": datetime.now().isoformat(),
        }
        action = decide_action("", "", existing)
        self.assertEqual(action, "skip_already_asked")

    def test_resend_after_cooldown(self):
        existing = {
            "state": "asked_address",
            "last_action_at": (datetime.now() - timedelta(hours=26)).isoformat(),
        }
        self.assertTrue(should_resend_ask(existing, cooldown_hours=24))
        action = decide_action("", "", existing)
        self.assertEqual(action, "send_ask_address")

    def test_mark_done_when_has_address(self):
        action = decide_action("", "123 street", None)
        self.assertEqual(action, "mark_done")


if __name__ == "__main__":
    unittest.main()


