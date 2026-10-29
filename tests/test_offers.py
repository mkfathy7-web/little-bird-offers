"""من غير نت: صفحات مزيّفة. عرض = السعر أقل من السعر قبل الخصم. الرفض بيوقف المتجر."""
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import offers  # noqa: E402


class Resp:
    def __init__(self, status=200, body=None, text=None):
        self.status_code = status
        self._body = body
        self.text = text if text is not None else json.dumps(body)

    def json(self):
        return self._body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise offers.requests.HTTPError(response=self)


class Session:
    def __init__(self, routes):
        self.routes = routes
        self.headers = {}
        self.got = []

    def get(self, url, timeout=None):
        self.got.append(url)
        for key, resp in self.routes.items():
            if key in url:
                return resp
        return Resp(404, text="")


class OffersTest(unittest.TestCase):
    def test_woo_on_sale_only_real_discounts(self):
        items = [{"id": 1, "name": "رز", "permalink": "https://x/1", "prices": {"price": "4000", "regular_price": "5000", "currency_minor_unit": 2}},
                 {"id": 2, "name": "سكر", "permalink": "https://x/2", "prices": {"price": "3000", "regular_price": "3000", "currency_minor_unit": 2}}]
        s = Session({"robots.txt": Resp(404, text=""), "on_sale=true": Resp(200, items)})
        found, report = offers.collect(["ecart"], session=s, sleep=lambda _: None)
        self.assertEqual([(o["id"], o["price"], o["was_price"]) for o in found], [("1", 40.0, 50.0)])
        self.assertIn("on_sale=true", s.got[1])
        self.assertEqual(s.headers["User-Agent"].split("/")[0], "LittleBirdOffers")

    def test_refusal_stops_store(self):
        s = Session({"robots.txt": Resp(404, text=""), "wp-json": Resp(429, text="slow down")})
        found, report = offers.collect(["ecart"], session=s, sleep=lambda _: None)
        self.assertEqual(found, [])
        self.assertIn("refused", report["ecart"])
        self.assertEqual(len(s.got), 2)  # robots + أول طلب، وبعدين وقف

    def test_robots_disallow(self):
        s = Session({"robots.txt": Resp(200, text="User-agent: *\nDisallow: /wp-json/")})
        found, report = offers.collect(["ecart"], session=s, sleep=lambda _: None)
        self.assertIn("robots", report["ecart"]["refused"])

    # ---- فحص الأمان (الجولة 3)
    def test_prices_must_be_finite_and_reasonable(self):
        self.assertIsNone(offers._offer("ecart", 1, "x", "nan", "50", ""))
        self.assertIsNone(offers._offer("ecart", 1, "x", "40", "1e999", ""))
        self.assertIsNone(offers._offer("ecart", 1, "x", "-5", "50", ""))
        self.assertIsNone(offers._offer("ecart", 1, "x", "10", "50", ""))  # «كان» أكتر من 3 أضعاف
        o = offers._offer("ecart", 1, "x", "40", "50", "http://evil.com/x")
        self.assertEqual(o["url"], "")  # لينك برّه المتجر بيتشال
        self.assertEqual(offers._offer("ecart", 1, "x", "40", "50", "https://www.ecart-eg.com/p")["url"],
                         "https://www.ecart-eg.com/p")

    def test_woo_bad_minor_unit_and_junk_items(self):
        items = ["junk", {"id": 3, "prices": "x"},
                 {"id": 1, "name": "رز", "prices": {"price": "4000", "regular_price": "5000", "currency_minor_unit": 999999}}]
        s = Session({"robots.txt": Resp(404, text=""), "on_sale=true": Resp(200, items)})
        found, report = offers.collect(["ecart"], session=s, sleep=lambda _: None)
        self.assertEqual([(o["id"], o["price"]) for o in found], [("1", 0.4)])  # الحد 4 أرقام عشرية

    def test_redirect_to_other_site_refused(self):
        r = Resp(200, [])
        r.url = "https://evil.example/wp-json/x"
        s = Session({"robots.txt": Resp(404, text=""), "on_sale=true": r})
        found, report = offers.collect(["ecart"], session=s, sleep=lambda _: None)
        self.assertIn("refused", report["ecart"])

    def test_robots_server_error_means_disallow(self):
        s = Session({"robots.txt": Resp(500, text="")})
        found, report = offers.collect(["ecart"], session=s, sleep=lambda _: None)
        self.assertIn("robots", report["ecart"]["refused"])
        self.assertEqual(len(s.got), 1)

    def test_huge_crawl_delay_stops_store(self):
        s = Session({"robots.txt": Resp(200, text="User-agent: *\nCrawl-delay: 99999")})
        slept = []
        found, report = offers.collect(["ecart"], session=s, sleep=slept.append)
        self.assertIn("refused", report["ecart"])
        self.assertEqual(slept, [])

    def test_unexpected_error_stops_one_store_only(self):
        s = Session({"robots.txt": Resp(404, text=""), "on_sale=true": Resp(200, {"not": "a list"}),
                     "graphql": Resp(200, ["not", "a", "dict"])})
        found, report = offers.collect(["ecart", "spinneys"], session=s, sleep=lambda _: None)
        self.assertEqual(found, [])
        self.assertEqual(set(report), {"ecart", "spinneys"})


if __name__ == "__main__":
    unittest.main()
