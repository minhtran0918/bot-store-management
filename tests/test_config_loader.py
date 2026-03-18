import tempfile
import unittest
from pathlib import Path

from app.config_loader import load_config


class ConfigLoaderTestCase(unittest.TestCase):
    def test_raise_when_file_missing(self):
        with self.assertRaises(FileNotFoundError):
            load_config("not_exists_config.yaml")

    def test_merge_partial_config(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "config.yaml"
            path.write_text(
                "base_url: https://example.com\n"
                "credentials:\n"
                "  username: demo\n"
                "  password: secret\n"
                "auth:\n"
                "  capture_enabled: false\n"
                "  bootstrap_from_token: false\n"
                "  indexeddb_token_key: TpageBearerToken\n"
                "  token_file: data/custom_token.json\n",
                encoding="utf-8",
            )
            config = load_config(path)

        self.assertEqual(config["base_url"], "https://example.com")
        self.assertEqual(config["credentials"]["username"], "demo")
        self.assertEqual(config["credentials"]["password"], "secret")
        self.assertFalse(config["auth"]["capture_enabled"])
        self.assertFalse(config["auth"]["bootstrap_from_token"])
        self.assertEqual(config["auth"]["indexeddb_token_key"], "TpageBearerToken")
        self.assertEqual(config["auth"]["token_file"], "data/custom_token.json")
        self.assertEqual(config["auth"]["login_url"], "https://example.com/#/account/login")
        self.assertEqual(config["auth"]["dashboard_url"], "https://example.com/#/dashboard")
        self.assertEqual(config["auth"]["order_url"], "https://example.com/#/order")
        self.assertEqual(config["keywords"]["pickup"], [])
        self.assertIn("keep_open", config["debug"])


if __name__ == "__main__":
    unittest.main()

