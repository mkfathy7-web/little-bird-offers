"""عدد عروض الرادار للموقع (فكرة 98)، ومواعيد الفحص وبصمته في latest.json (فكرة 106). من غير نت."""
import gzip
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import offers  # noqa: E402
import radar  # noqa: E402
import send_watch_emails as swe  # noqa: E402

# نفس أمثلة اختبارات التطبيق (app/test/preseason_test.dart)
BASE = {
    "spinneys:a": [48, "2026-10-29", 48, "2026-10-29"],
    "spinneys:pasta": [14.95, "2026-10-27", 17.75, "2026-10-29"],
}


class R:
    def __init__(self, status, body=None, content=b""):
        self.status_code, self._b, self.content = status, body, content

    def json(self):
        return self._b


class Marks(unittest.TestCase):
    def test_same_marks_as_the_app(self):
        a = BASE["spinneys:a"]
        self.assertEqual(radar.mark(43, a), "real")
        self.assertEqual(radar.mark(50, a), "raised")      # أغلى من قبل الموسم بعد الخصم
        self.assertEqual(radar.mark(48.5, a), "same")      # أغلى بأقل من 2٪
        self.assertEqual(radar.mark(48, a), "same")
        self.assertEqual(radar.mark(47.5, a), "same")      # أرخص بأقل من 2٪
        pasta = BASE["spinneys:pasta"]
        self.assertEqual(radar.mark(15.95, pasta), "raised")  # اترفع جوه الفترة والعرض في النص
        self.assertEqual(radar.mark(14.5, pasta), "real")

    def test_no_baseline_or_bad_reading(self):
        self.assertEqual(radar.mark(10, None), "none")
        self.assertEqual(radar.mark(0.05, BASE["spinneys:a"]), "none")
        self.assertEqual(radar.mark(10, [0, "x", 0, "x"]), "none")

    def test_counts_one_per_product(self):
        offers_ = [
            {"store": "spinneys", "id": "a", "price": 45},
            {"store": "spinneys", "id": "a", "price": 43},   # نفس المنتج مرتين: الأرخص
            {"store": "spinneys", "id": "pasta", "price": 15.95},
            {"store": "metro", "id": "new", "price": 10},
        ]
        self.assertEqual(radar.counts(offers_, BASE),
                         {"offers": 3, "real_deals": 1, "raised": 1, "same_price": 0, "no_baseline": 1})


class Push(unittest.TestCase):
    ENV = {"SUPABASE_URL": "https://s.example", "SUPABASE_SERVICE_KEY": "k"}

    def test_writes_numbers_only(self):
        packed = gzip.compress(json.dumps({"p": BASE}).encode("utf-8"))
        with mock.patch.dict(os.environ, self.ENV), \
                mock.patch.object(radar.requests, "get", return_value=R(200, content=packed)) as get, \
                mock.patch.object(radar.requests, "post", return_value=R(201)) as post:
            row = radar.push([{"store": "spinneys", "id": "a", "price": 43, "name": "رز", "url": "https://x"}],
                             "2026-11-03T22:30:00+00:00")
        self.assertEqual(row["day"], "2026-11-04")  # 00:30 بالقاهرة
        sent = json.loads(post.call_args.kwargs["data"])
        self.assertEqual(sent, {"id": 1, "day": "2026-11-04", "checked_at": "2026-11-03T22:30:00+00:00",
                                "offers": 1, "real_deals": 1, "raised": 0, "same_price": 0, "no_baseline": 0})
        self.assertTrue(post.call_args.args[0].endswith("/rest/v1/radar_stats"))
        self.assertTrue(get.call_args.args[0].endswith("/prices/preseason-2026.json.gz"))  # المضغوط كل ساعة

    def test_plain_file_when_no_gz(self):
        with mock.patch.dict(os.environ, self.ENV), \
                mock.patch.object(radar.requests, "get", side_effect=[R(404), R(200, {"p": BASE})]), \
                mock.patch.object(radar.requests, "post", return_value=R(201)):
            row = radar.push([{"store": "spinneys", "id": "a", "price": 50}], "2026-11-03T10:00:00+00:00")
        self.assertEqual(row["raised"], 1)

    def test_nothing_without_the_baseline(self):
        with mock.patch.dict(os.environ, self.ENV), \
                mock.patch.object(radar.requests, "get", return_value=R(404, {})), \
                mock.patch.object(radar.requests, "post") as post:
            self.assertIsNone(radar.push([{"store": "s", "id": "1", "price": 1}], "2026-11-03T10:00:00+00:00"))
        post.assert_not_called()

    def test_failure_does_not_stop_the_offers_upload(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.object(offers, "collect", return_value=([], {})), \
                mock.patch.object(offers, "upload") as up, \
                mock.patch.object(offers.radar, "push", side_effect=RuntimeError("radar_stats (404)")):
            self.assertEqual(offers.main(["--upload", "--out", os.path.join(d, "o.json")]), 0)
        up.assert_called_once()


class LatestFile(unittest.TestCase):
    def test_cron_and_sha_in_the_file(self):
        found = [{"store": "s", "id": "1", "price": 10, "was_price": 12, "seen_at": "2026-11-03T10:07:00+00:00"}]
        with tempfile.TemporaryDirectory() as d, mock.patch.object(offers, "collect", return_value=(found, {})):
            out = os.path.join(d, "o.json")
            offers.main(["--out", out])
            with open(out, encoding="utf-8") as f:
                body = json.load(f)
        self.assertEqual(body["cron"], "7 6-22 * * *")  # من offers.yml نفسه، مش مكتوب ثابت
        self.assertEqual(len(body["sha"]), 16)
        # البصمة بتتغيّر مع العروض بس، مش مع وقت الفحص
        again = [dict(found[0], seen_at="2026-11-03T11:07:00+00:00")]
        self.assertEqual(offers.offers_sha(again), body["sha"])
        self.assertNotEqual(offers.offers_sha([dict(found[0], price=9)]), body["sha"])


class WatchEmailDates(unittest.TestCase):
    def test_reasons_name_the_days(self):
        data = {"taken_at": "2026-10-30T09:00:00+00:00", "history_start": "2026-10-24",
                "products": [["1", "رز", 45.0, None, 1.0, "kg", 1, "rice", "", True, "spinneys"]],
                "coverage": {"spinneys": ["*"]}, "history": {"spinneys:1": [[0, 50], [5, 45]]}}
        watch = {"offers": ["spinneys:1"], "area_slug": "dokki", "max_unit_price": 55, "when_best_time": True,
                 "last_state": {}}
        why = swe.reasons(watch, swe.state_of(watch, data, swe.offers_index(data)))
        self.assertIn(("السعر بقى 45 ج يوم 30 أكتوبر (أقل من 55)", "Price is 45 EGP on Oct 30 (under 55)"), why)
        self.assertIn(("ده أقل سعر شفناه من يوم 24 أكتوبر", "Lowest price we've seen since Oct 24"), why)


if __name__ == "__main__":
    unittest.main()
