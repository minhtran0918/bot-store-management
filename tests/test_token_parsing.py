import unittest

from app.auth import _extract_bearer_from_value, _extract_token_metadata


class TokenParsingTestCase(unittest.TestCase):
    def test_extract_token_from_envelope_json_string(self):
        raw = (
            '{"date":"2026-03-15T10:14:00.629Z","value":{"access_token":"aaa.bbb.ccc",'
            '"token_type":"bearer","expires_in":1295999,"refresh_token":"r1",'
            '".issued":"Sun, 15 Mar 2026 10:13:59 GMT",".expires":"Mon, 30 Mar 2026 10:13:59 GMT"}}'
        )

        token = _extract_bearer_from_value(raw)
        self.assertEqual(token, "aaa.bbb.ccc")

    def test_extract_metadata_from_envelope_json_string(self):
        raw = (
            '{"date":"2026-03-15T10:14:00.629Z","value":{"access_token":"aaa.bbb.ccc",'
            '"token_type":"bearer","expires_in":1295999,"refresh_token":"r1",'
            '".issued":"Sun, 15 Mar 2026 10:13:59 GMT",".expires":"Mon, 30 Mar 2026 10:13:59 GMT"}}'
        )

        meta = _extract_token_metadata(raw)
        self.assertEqual(meta["token_type"], "bearer")
        self.assertEqual(meta["expires_in_seconds"], 1295999)
        self.assertTrue(meta["has_refresh_token"])
        self.assertTrue(meta["issued_at_raw"])
        self.assertTrue(meta["expires_at_raw"])


if __name__ == "__main__":
    unittest.main()

