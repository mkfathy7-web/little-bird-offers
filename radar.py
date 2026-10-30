"""عدد عروض «رادار الجمعة البيضاء» للموقع (فكرة 98): بعد كل فحص، كام عرض ومنهم كام خصم حقيقي.

أرقام بس (من غير أسعار ولا أسامي منتجات ولا محلات) في جدول radar_stats على Supabase، والموقع بيقراها بـ
public_radar_stats() (db/radar_stats.sql في الريبو الأساسي). العلامات نفس التطبيق (app/lib/src/preseason.dart):
كل عرض قصاد سعره قبل الموسم (26 أكتوبر ← 1 نوفمبر، prices/preseason-2026.json في المخزن المقفول):
  real    ✓ أرخص من أي سعر شفناه قبل الموسم بـ 2٪ أو أكتر
  raised  ⚠ السعر بعد الخصم أغلى من سعر قبل الموسم بـ 2٪، أو اترفع جوه الفترة والعرض مانزلش تحت سعره الأولاني
  same    ⓘ نفس سعر قبل الموسم تقريبًا
  none    مكانش عندنا سعره قبل الموسم، أو سعره بعيد عنه 3 أضعاف (غلط قراية)
اللوج عام: مفيش أرقام بتتطبع.
"""
from __future__ import annotations

import gzip
import json
import os
from datetime import datetime, timedelta, timezone

import requests

PRESEASON = "preseason-2026.json"
REAL_FLOOR, RAISED_FLOOR, MAX_JUMP = 0.98, 1.02, 3

try:
    from zoneinfo import ZoneInfo
    CAIRO = ZoneInfo("Africa/Cairo")
except Exception:  # من غير tzdata: توقيت الشتا
    CAIRO = timezone(timedelta(hours=2))


def _num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0


def mark(price: float, entry) -> str:
    """علامة عرض بسعر [price] قصاد [أقل سعر، يومه، آخر سعر، يومه] قبل الموسم (نفس seasonCheck في التطبيق)."""
    if not isinstance(entry, list) or len(entry) < 4 or not _num(entry[0]) or not _num(entry[2]) or not _num(price):
        return "none"
    low, last = entry[0], entry[2]
    if price * MAX_JUMP < last or price > last * MAX_JUMP:
        return "none"
    if price <= low * REAL_FLOOR:
        return "real"
    if price >= last * RAISED_FLOOR or (low != last and last >= low * RAISED_FLOOR):
        return "raised"
    return "same"


_COLUMN = {"real": "real_deals", "raised": "raised", "same": "same_price", "none": "no_baseline"}


def counts(offers: list[dict], baseline: dict) -> dict:
    """عرض واحد لكل «متجر:كود» (الأرخص لو اتكرر، زي التطبيق)."""
    best: dict[str, float] = {}
    for o in offers:
        key, price = f"{o.get('store')}:{o.get('id')}", o.get("price")
        if _num(price) and (key not in best or price < best[key]):
            best[key] = price
    out = {"offers": len(best), "real_deals": 0, "raised": 0, "same_price": 0, "no_baseline": 0}
    for key, price in best.items():
        out[_COLUMN[mark(price, baseline.get(key))]] += 1
    return out


def cairo_day(iso: str) -> str:
    return datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(CAIRO).date().isoformat()


def _baseline(url: str, auth: dict, timeout: int):
    """النسخة المضغوطة (حوالي 600 KB بدل 4 MB، كل ساعة)، ولو مش موجودة العادية."""
    base = f"{url}/storage/v1/object/prices/{PRESEASON}"
    r = requests.get(base + ".gz", headers=auth, timeout=timeout)
    if r.status_code == 200:
        return json.loads(gzip.decompress(r.content).decode("utf-8")).get("p")
    r = requests.get(base, headers=auth, timeout=timeout)
    return r.json().get("p") if r.status_code == 200 else None


def push(offers: list[dict], taken_at: str, timeout: int = 60) -> dict | None:
    """بيجيب سعر قبل الموسم من المخزن المقفول ويكتب الأرقام في radar_stats. من غير ملف قبل الموسم مبيكتبش حاجة."""
    url = os.environ.get("SUPABASE_URL", "").rstrip("/")
    key = os.environ.get("SUPABASE_SERVICE_KEY", "")
    if not url or not key:
        return None
    auth = {"apikey": key, "Authorization": f"Bearer {key}"}
    baseline = _baseline(url, auth, timeout)
    if not isinstance(baseline, dict):
        return None  # لسه مترفعش: أرقام من غير مقارنة تبقى غلط
    row = {"id": 1, "day": cairo_day(taken_at), "checked_at": taken_at, **counts(offers, baseline)}
    r = requests.post(f"{url}/rest/v1/radar_stats", data=json.dumps(row), timeout=30,
                      headers={**auth, "Content-Type": "application/json", "Prefer": "resolution=merge-duplicates"})
    if r.status_code >= 300:
        raise RuntimeError(f"radar_stats ({r.status_code})")  # من غير الرد نفسه (ممكن يبقى فيه تفاصيل)
    return row
