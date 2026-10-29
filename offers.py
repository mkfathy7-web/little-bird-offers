"""فحص العروض كل ساعة: صفحة العروض بس في كل متجر (1–20 طلب)، مش الكتالوج كله.

    python offers.py --out offers.json            # تجربة على الجهاز (من غير رفع)
    python offers.py --upload                     # GitHub: بيرفع offers/latest.json على المخزن المقفول

القواعد (نفس الريبو الأساسي): robots.txt لكل host (ومعاها الـ API)، Crawl-delay، طلب كل 3 ثواني أو أبطأ،
ووقوف المتجر لو رد 403 أو 429 أو 503 أو طلب «أنا مش روبوت». الـ User-Agent صريح ومبيتغيّرش.
مفيش بيانات بتتحفظ في الريبو ده: الملف بيترفع على Supabase (مقفول) بالمفتاح السري، ومبيتعملش commit.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from urllib.parse import quote, urlsplit

import requests

from robots import Robots

CONTACT = os.environ.get("ARKHAS_CONTACT", "contact-not-set")
USER_AGENT = f"LittleBirdOffers/1.0 (+{CONTACT})"
MIN_DELAY = 3.0
MAX_REQUESTS = 20  # لكل متجر في التشغيل


class Refused(Exception):
    """المتجر رفض (403/429/503 أو تحقق): بنوقف المتجر ده في التشغيل ده."""


class Polite:
    def __init__(self, session=None, sleep=time.sleep, clock=time.monotonic):
        self.s = session or requests.Session()
        self.s.headers.update({"User-Agent": USER_AGENT, "Accept-Language": "ar,en;q=0.8"})
        self._sleep, self._clock = sleep, clock
        self._robots: dict[str, Robots] = {}
        self._last: dict[str, float] = {}
        self.count = 0

    def _host(self, url: str) -> str:
        p = urlsplit(url)
        return f"{p.scheme}://{p.netloc}"

    def robots(self, url: str) -> Robots:
        host = self._host(url)
        if host not in self._robots:
            r = self._raw(f"{host}/robots.txt")
            text = "User-agent: *\nDisallow: /" if r.status_code in (401, 403) else ("" if r.status_code >= 400 else r.text)
            self._robots[host] = Robots(text)
        return self._robots[host]

    def _raw(self, url: str):
        host = self._host(url)
        delay = MIN_DELAY
        rb = self._robots.get(host)
        if rb and (cd := rb.crawl_delay(USER_AGENT)):
            delay = max(delay, cd)
        last = self._last.get(host)
        if last is not None and self._clock() - last < delay:
            self._sleep(delay - (self._clock() - last))
        self._last[host] = self._clock()
        self.count += 1
        return self.s.get(url, timeout=25)

    def get_json(self, url: str):
        if not self.robots(url).allowed(USER_AGENT, url):
            raise Refused(f"robots.txt مش بيسمح: {url}")
        r = self._raw(url)
        if r.status_code in (401, 403, 429, 503):
            raise Refused(f"{url} رجّع {r.status_code}")
        r.raise_for_status()
        if "captcha" in r.text[:3000].lower():
            raise Refused(f"{url} طلب تحقق")
        return r.json()


def _offer(store, pid, name, price, was, url) -> dict | None:
    try:
        price, was = float(price), float(was) if was not in (None, "") else None
    except (TypeError, ValueError):
        return None
    if not price or not was or was <= price:
        return None  # مش عرض
    return {"store": store, "id": str(pid), "name": " ".join(str(name).split()), "price": round(price, 2),
            "was_price": round(was, 2), "url": url}


# ------------------------------------------------------------------ ماجنتو (سبينيس وجورميه): أقسام العروض
def _gourmet_id(it: dict) -> str:
    """نفس كود جورميه في الريبو الأساسي: «القسم/المنتج» لو موجود، وإلا url_key."""
    paths = [r["url"] for r in it.get("url_rewrites") or [] if (r.get("url") or "").count("/") == 1]
    return paths[0] if paths else it["url_key"]


# المتجر ← (الموقع، لينك المنتج، الكود زي الريبو الأساسي)
MAGENTO = {
    "spinneys": ("https://spinneys-egypt.com", "https://spinneys-egypt.com/en/{key}", lambda it: it["url_key"]),
    "gourmet": ("https://gourmetegypt.com", "https://gourmetegypt.com/{key}", _gourmet_id),
}
_OFFER_WORDS = ("offer", "deal", "sale", "promo", "special", "عروض", "خصم")
_CATS = "{categories(filters:{},pageSize:600){items{id url_path product_count}}}"
_PAGE = ("{products(filter:{category_id:{eq:%s}},pageSize:50,currentPage:%d,sort:{name:ASC}){page_info{total_pages}"
         "items{url_key url_rewrites{url} price_range{minimum_price{final_price{value} regular_price{value}}} name}}}")


def magento(c: Polite, store: str) -> list[dict]:
    host, link, id_of = MAGENTO[store]
    cats = c.get_json(f"{host}/graphql?query={quote(_CATS)}")
    items = (((cats.get("data") or {}).get("categories") or {}).get("items")) or []
    offer_cats = sorted((i for i in items if any(w in (i.get("url_path") or "").lower() for w in _OFFER_WORDS)
                         and (i.get("product_count") or 0) > 0), key=lambda i: i.get("product_count") or 0)
    out: dict[str, dict] = {}
    for cat in offer_cats:
        page, total = 1, 1
        while page <= total and c.count < MAX_REQUESTS:
            data = c.get_json(f"{host}/graphql?query={quote(_PAGE % (json.dumps(str(cat['id'])), page))}")
            prod = ((data.get("data") or {}).get("products")) or {}
            total = (prod.get("page_info") or {}).get("total_pages") or 1
            for it in prod.get("items") or []:
                if not isinstance(it, dict) or not it.get("url_key"):
                    continue
                p = ((it.get("price_range") or {}).get("minimum_price")) or {}
                key = id_of(it)
                o = _offer(store, key, it.get("name"), (p.get("final_price") or {}).get("value"),
                           (p.get("regular_price") or {}).get("value"), link.format(key=key))
                if o:
                    out[o["id"]] = o
            page += 1
        if c.count >= MAX_REQUESTS:
            break
    return list(out.values())


# ------------------------------------------------------------------ WooCommerce: Store API ?on_sale=true
WOO = {
    "rdna": "https://rdnastore.com", "neatmeat": "https://neatmeat.net", "koki": "https://kokishoponline.com",
    "alyfarms": "https://alyfarms.com", "freshtokri": "https://freshtokrifoods.com", "ecart": "https://ecart-eg.com",
    "radifarms": "https://radifarms.com", "edamfarms": "https://edamfarms.com", "arkan": "https://arkanfoodsegypt.com",
    "vidasana": "https://vidasana-eg.com", "exception": "https://www.exception-group.com",
}


def woo(c: Polite, store: str) -> list[dict]:
    base = WOO[store]
    out = []
    for page in range(1, 6):
        url = f"{base}/wp-json/wc/store/v1/products?on_sale=true&per_page=50&page={page}"
        try:
            items = c.get_json(url)
        except requests.HTTPError:
            break  # بعد آخر صفحة
        for p in items or []:
            pr = p.get("prices") or {}
            unit = 10 ** int(pr.get("currency_minor_unit") or 0)
            try:
                price, was = int(pr.get("price")) / unit, int(pr.get("regular_price")) / unit
            except (TypeError, ValueError):
                continue
            o = _offer(store, p.get("id"), p.get("name"), price, was, p.get("permalink") or "")
            if o:
                out.append(o)
        if len(items or []) < 50 or c.count >= MAX_REQUESTS:
            break
    return out


SOURCES = {**{s: magento for s in MAGENTO}, **{s: woo for s in WOO}}


def collect(only: list[str] | None = None, session=None, sleep=time.sleep) -> tuple[list[dict], dict]:
    seen_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    offers, report = [], {}
    for store, fn in SOURCES.items():
        if only and store not in only:
            continue
        c = Polite(session=session, sleep=sleep)
        try:
            found = fn(c, store)
            report[store] = {"offers": len(found), "requests": c.count}
            offers += [{**o, "seen_at": seen_at} for o in found]
        except Refused as e:
            report[store] = {"refused": str(e)[:200], "requests": c.count}
        except (requests.RequestException, ValueError) as e:
            report[store] = {"error": type(e).__name__, "requests": c.count}
    return offers, report


def upload(body: bytes) -> None:
    url, key = os.environ.get("SUPABASE_URL", "").rstrip("/"), os.environ.get("SUPABASE_SERVICE_KEY", "")
    if not url or not key:
        sys.exit("SUPABASE_URL و SUPABASE_SERVICE_KEY مش متحطين")
    r = requests.post(f"{url}/storage/v1/object/prices/offers/latest.json", data=body, timeout=60,
                      headers={"apikey": key, "Authorization": f"Bearer {key}", "Content-Type": "application/json",
                               "x-upsert": "true"})
    if r.status_code >= 300:
        sys.exit(f"الرفع فشل ({r.status_code})")  # من غير ما نطبع الرد (ممكن يبقى فيه تفاصيل)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="offers")
    ap.add_argument("--store", action="append", help="متجر واحد أو أكتر (من غير: الكل)")
    ap.add_argument("--out", help="اكتب offers.json على الجهاز (للتجربة)")
    ap.add_argument("--upload", action="store_true", help="ارفع على Supabase (المخزن المقفول)")
    a = ap.parse_args(argv)
    offers, report = collect(a.store)
    body = json.dumps({"taken_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
                       "offers": offers, "report": report}, ensure_ascii=False).encode("utf-8")
    if a.out:
        with open(a.out, "wb") as f:
            f.write(body)
    if a.upload:
        upload(body)
    for store, r in report.items():
        print(f"{store}: {r}")
    print(f"إجمالي العروض: {len(offers)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
