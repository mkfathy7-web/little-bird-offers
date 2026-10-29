"""العروض اللي اتشافت في فحص كل ساعة (ريبو little-bird-offers) بتدخل في الأسعار.

    python -m pipeline.offers_merge publish/prices.json offers.json

لكل منتج في prices.json عنده عرض أحدث من وقت الجمع (نفس المتجر ونفس الكود): السعر والسعر قبل الخصم من العرض.
العرض الأقدم من الجمع نفسه بنسيبه (الجمع أحدث). وتاريخ الأسعار مبيتغيّرش هنا: بيتحدّث في الجمع اللي بعده.
"""
from __future__ import annotations

import json
import math
import sys
from datetime import datetime


def _when(s: str | None) -> datetime | None:
    try:
        return datetime.fromisoformat((s or "").replace("Z", "+00:00"))
    except ValueError:
        return None


def merge(prices: dict, offers: dict) -> int:
    """بيعدّل prices في مكانه، وبيرجّع عدد المنتجات اللي اتغيّرت."""
    taken = _when(prices.get("taken_at"))
    by_key = {f"{o.get('store')}:{o.get('id')}": o for o in offers.get("offers") or []}
    changed = 0
    for row in prices.get("products") or []:
        o = by_key.get(f"{row[-1]}:{row[0]}")
        if not o:
            continue
        seen = _when(o.get("seen_at"))
        if taken and seen and seen.astimezone() <= taken.astimezone():
            continue
        price, was = o.get("price"), o.get("was_price")
        # أرقام حقيقية محدودة، والخصم معقول (نفس حد الـ 3 أضعاف بتاع الجمع)، وإلا منلمسش السعر (فحص الأمان)
        if not all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) for v in (price, was)) \
                or not 0 < price < was <= price * 3 or (row[2] == price and row[3] == was):
            continue
        row[2], row[3] = price, was
        changed += 1
    if changed:
        prices["offers_merged_at"] = offers.get("taken_at")
    return changed


if __name__ == "__main__":
    prices_path, offers_path = sys.argv[1], sys.argv[2]
    with open(prices_path, encoding="utf-8") as f:
        prices = json.load(f)
    with open(offers_path, encoding="utf-8") as f:
        offers = json.load(f)
    n = merge(prices, offers)
    with open(prices_path, "w", encoding="utf-8") as f:
        json.dump(prices, f, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    print(f"عروض الساعة: اتحدّث {n} منتج", file=sys.stderr)
