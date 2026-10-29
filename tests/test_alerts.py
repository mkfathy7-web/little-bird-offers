"""الإيميلات كل ساعة: ملف الأسعار مبيتحمّلش لو مفيش منتج مستني عليه عرض جديد."""
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import alerts  # noqa: E402


class R:
    def __init__(self, status, body):
        self.status_code, self._b = status, body

    def json(self):
        return self._b


class AlertsTest(unittest.TestCase):
    def run_with(self, watches):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "offers.json")
            json.dump({"offers": [{"store": "spinneys", "id": "rice", "price": 40, "was_price": 50}]}, open(p, "w"))
            env = {"BREVO_API_KEY": "x", "SUPABASE_URL": "https://s.example", "SUPABASE_SERVICE_KEY": "k"}
            with mock.patch.dict(os.environ, env), \
                    mock.patch.object(alerts.requests, "post", return_value=R(200, watches)) as post, \
                    mock.patch.object(alerts.requests, "get", return_value=R(500, {})) as get:
                alerts.main([p])
            return post, get

    def test_no_download_without_a_hit(self):
        _, get = self.run_with([{"offers": ["spinneys:oil"]}])
        get.assert_not_called()

    def test_downloads_when_a_watched_product_has_an_offer(self):
        _, get = self.run_with([{"offers": ["spinneys:rice"]}])
        get.assert_called_once()

    def test_skips_without_brevo(self):
        with mock.patch.dict(os.environ, {"BREVO_API_KEY": ""}):
            self.assertEqual(alerts.main(["nothing.json"]), 0)


if __name__ == "__main__":
    unittest.main()
