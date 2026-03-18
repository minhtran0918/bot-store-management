import unittest
from datetime import datetime, timedelta, timezone

from app.auth import _is_saved_token_expired


class TokenExpiryTestCase(unittest.TestCase):
    def test_expired_by_expires_at_unix(self):
        payload = {"expires_at_unix": int(datetime.now(timezone.utc).timestamp()) - 10}
        self.assertTrue(_is_saved_token_expired(payload, "aaa.bbb.ccc", skew_seconds=0))

    def test_not_expired_by_expires_at_unix(self):
        payload = {"expires_at_unix": int(datetime.now(timezone.utc).timestamp()) + 3600}
        self.assertFalse(_is_saved_token_expired(payload, "aaa.bbb.ccc", skew_seconds=0))

    def test_expired_by_captured_at_and_expires_in(self):
        payload = {
            "captured_at": (datetime.now(timezone.utc) - timedelta(minutes=30)).isoformat(),
            "expires_in_seconds": 60,
        }
        self.assertTrue(_is_saved_token_expired(payload, "aaa.bbb.ccc", skew_seconds=0))


if __name__ == "__main__":
    unittest.main()

