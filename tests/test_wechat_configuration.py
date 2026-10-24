import unittest

from scripts.wechat import configuration


class WechatConfigurationTests(unittest.TestCase):
    def test_configures_real_appid_and_https_without_embedded_credentials(self):
        self.assertEqual(
            configuration("wx38dee0ea03214271", "https://api.example.invalid/"),
            ("wx38dee0ea03214271", "https://api.example.invalid"),
        )

    def test_rejects_tourist_id_and_unsafe_api_origins(self):
        with self.assertRaises(ValueError):
            configuration("touristappid", "https://api.example.invalid")
        for origin in (
            "http://127.0.0.1:18000",
            "https://secret@api.example.invalid",
            "https://api.example.invalid/path",
            "https://api.example.invalid/?key=hidden",
        ):
            with self.assertRaises(ValueError):
                configuration("wx38dee0ea03214271", origin)

    def test_ui_only_has_no_fake_endpoint_and_still_rejects_http(self):
        self.assertEqual(configuration("wx38dee0ea03214271", "", ui_only=True)[1], "")
        with self.assertRaises(ValueError):
            configuration("wx38dee0ea03214271", "http://127.0.0.1", ui_only=True)


if __name__ == "__main__":
    unittest.main()
