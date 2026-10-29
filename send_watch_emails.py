"""«منتجاتي اللي مستنيها»: بعد كل رفع أسعار، بيشوف كل منتج حد مستنيه ولو شرط اتحقق يبعتله إيميل (Brevo).

    set SUPABASE_URL=https://xxxx.supabase.co
    set SUPABASE_SERVICE_KEY=...     (service role، من GitHub Secrets بس)
    set BREVO_API_KEY=...            (من Brevo → SMTP & API → API Keys، GitHub Secrets بس)
    set ALERT_SENDER=alerts@...      (إيميل مأكد في Brevo → Senders)
    set SITE_URL=https://...         (لينك الموقع، للينك المنتج وإلغاء الاشتراك)
    python tools/send_watch_emails.py publish/prices.json [--dry-run]

الشروط (db/product_watches.sql): رجع متوفر، بقى متوفر في محل بيوصّل منطقتي، سعر الكيلو ≤ رقم،
أو أقل سعر في آخر 60 يوم. «رجع» يعني كان مش متوفر آخر مرة شفناه، فأول مرة بنسجّل الحالة بس.
إيميل واحد لكل منتج في اليوم بالكتير، ولكل حساب إيميل واحد في التشغيل فيه كل منتجاته.
المفاتيح والإيميلات مبتتكتبش في اللوج.
"""
from __future__ import annotations

import argparse
import html
import json
import os
import sys
from datetime import datetime, timedelta, timezone

import requests

BREVO_URL = "https://api.brevo.com/v3/smtp/email"
ONE_DAY = timedelta(hours=23)  # تشغيلين في اليوم (كل 12 ساعة): التاني ميبعتش لنفس المنتج


def _supabase_headers(key: str) -> dict:
    h = {"apikey": key, "Content-Type": "application/json"}
    if key.startswith("eyJ"):
        h["Authorization"] = f"Bearer {key}"
    return h


def offers_index(data: dict) -> dict[str, list]:
    """«store:id» ← صف المنتج [id, name, price, was, qty, unit, pack, category, image, in_stock, store]."""
    return {f"{r[-1]}:{r[0]}": r for r in data.get("products") or []}


def covers(data: dict, store: str, area: str | None) -> bool:
    if not area:
        return True
    areas = (data.get("coverage") or {}).get(store)
    if areas is None:
        return True  # تصوير قديم من غير تغطية
    return "*" in areas or area in areas


def state_of(watch: dict, data: dict, index: dict[str, list]) -> dict:
    """الحالة دلوقتي: متوفر؟ متوفر في منطقتي؟ أرخص سعر للكيلو، وهل هو أقل سعر في آخر 60 يوم."""
    rows = [index[k] for k in watch.get("offers") or [] if k in index]
    stock = [r for r in rows if r[9]]
    near = [r for r in stock if covers(data, r[-1], watch.get("area_slug"))]
    pool = near or stock
    best = min(pool, key=lambda r: r[2] / r[4] if r[4] else r[2], default=None)
    price = round(best[2] / best[4], 2) if best and best[4] else (best[2] if best else None)
    low = False
    if best:
        points = (data.get("history") or {}).get(f"{best[-1]}:{best[0]}") or []
        # لازم السعر يكون اتغيّر مرة على الأقل عشان «أقل سعر» يبقى ليه معنى
        low = len(points) >= 2 and best[2] <= min(p[1] for p in points)
    return {
        "stock": bool(stock),
        "area": bool(near),
        "price": price,
        "low": low,
        "store": best[-1] if best else None,
        "total": best[2] if best else None,
    }


def reasons(watch: dict, now: dict) -> list[tuple[str, str]]:
    """الشروط اللي اتحققت دلوقتي ومكانتش متحققة آخر مرة: [(عربي، إنجليزي)]."""
    last = watch.get("last_state") or {}
    out: list[tuple[str, str]] = []
    if watch.get("when_in_stock") and now["stock"] and last.get("stock") is False:
        out.append(("رجع متوفر", "Back in stock"))
    if watch.get("when_in_area") and now["area"] and last.get("area") is False:
        out.append(("بقى متوفر في محل بيوصّل منطقتك", "Now at a store that delivers to your area"))
    limit = watch.get("max_unit_price")
    if limit is not None and now["price"] is not None and now["price"] <= float(limit):
        before = last.get("price")
        if before is None or before > float(limit):
            out.append((f"السعر بقى {now['price']:g} ج (أقل من {float(limit):g})",
                        f"Price is now {now['price']:g} EGP (under {float(limit):g})"))
    if watch.get("when_best_time") and now["low"] and not last.get("low"):
        out.append(("ده أقل سعر شفناه في آخر 60 يوم", "Lowest price we've seen in 60 days"))
    return out


def due(watch: dict, at: datetime) -> bool:
    sent = watch.get("last_notified_at")
    if not sent:
        return True
    return at - datetime.fromisoformat(sent.replace("Z", "+00:00")) >= ONE_DAY


def email_html(name: str, lines: list[dict], site: str, unsub: str, arabic: bool) -> str:
    """نفس شكل إيميلات الدخول (C:\\dev\\arkhas-website\\emails): المظلة ولافتة Little Bird."""
    e = html.escape
    stripes = "".join(f'<td height="22" style="background:{"#C8102E" if i % 2 == 0 else "#FFFFFF"};">&nbsp;</td>' for i in range(12))
    rows = "".join(
        f'<tr><td style="padding:10px 0;border-bottom:1px dashed #D9CBB0;font-family:Tajawal,Tahoma,Arial,sans-serif;color:#1B2A22;">'
        f'<div style="font-size:17px;font-weight:700;">{e(x["label"])}</div>'
        f'<div style="font-size:14px;color:#0E5A3A;font-weight:700;">{e(" · ".join(x["why"]))}</div>'
        f'<div style="font-size:13px;color:#4A5A50;">{e(x["where"])}</div></td></tr>'
        for x in lines)
    hi = f"أهلًا {name}،" if arabic and name else ("أهلًا،" if arabic else (f"Hi {name}," if name else "Hi,"))
    intro = "في منتجات كنت مستنيها حصلها جديد:" if arabic else "Some products you're waiting for have news:"
    open_btn = "افتح Little Bird" if arabic else "Open Little Bird"
    stop = "مش عايز إيميلات تاني؟ وقّفها من هنا" if arabic else "Don't want these emails? Turn them off"
    d = "rtl" if arabic else "ltr"
    return f"""<!doctype html><html lang="{'ar' if arabic else 'en'}" dir="{d}"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><meta name="color-scheme" content="light"></head>
<body style="margin:0;padding:0;background:#F4EDE1;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="background:#F4EDE1;"><tr><td align="center" style="padding:24px 12px;">
<table role="presentation" width="480" cellpadding="0" cellspacing="0" border="0" style="width:480px;max-width:100%;background:#FFFDF8;border:3px solid #1B2A22;border-radius:18px;overflow:hidden;">
<tr><td style="padding:0;line-height:0;font-size:0;"><table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"><tr>{stripes}</tr></table></td></tr>
<tr><td align="center" style="padding:20px 24px 6px;"><table role="presentation" cellpadding="0" cellspacing="0" border="0" style="background:#0E5A3A;border:4px solid #E9C46A;border-radius:12px;">
<tr><td align="center" style="padding:6px 26px 10px;font-family:Lalezar,Tahoma,Arial,sans-serif;font-size:34px;line-height:1.2;color:#E9C46A;">Little Bird</td></tr></table></td></tr>
<tr><td dir="{d}" style="padding:12px 28px 4px;font-family:Tajawal,Tahoma,Arial,sans-serif;color:#1B2A22;text-align:{'right' if arabic else 'left'};">
<p style="margin:0 0 4px;font-size:18px;font-weight:700;">{e(hi)}</p><p style="margin:0;font-size:15px;color:#4A5A50;">{intro}</p></td></tr>
<tr><td dir="{d}" style="padding:4px 28px 8px;text-align:{'right' if arabic else 'left'};"><table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">{rows}</table></td></tr>
<tr><td align="center" style="padding:12px 24px 20px;"><a href="{e(site)}" style="display:inline-block;background:#C8102E;color:#FFFFFF;text-decoration:none;font-family:Tajawal,Tahoma,Arial,sans-serif;font-weight:700;font-size:16px;padding:12px 28px;border-radius:12px;">{open_btn}</a></td></tr>
<tr><td align="center" style="padding:0 24px 20px;font-family:Tajawal,Tahoma,Arial,sans-serif;font-size:12px;color:#7A857E;"><a href="{e(unsub)}" style="color:#7A857E;">{stop}</a></td></tr>
</table></td></tr></table></body></html>"""


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="send_watch_emails")
    ap.add_argument("prices", help="prices.json اللي لسه اترفع")
    ap.add_argument("--dry-run", action="store_true", help="اطبع اللي هيتبعت (من غير إيميلات) ومتحدّثش الحالة")
    a = ap.parse_args(argv)
    url, key = os.environ.get("SUPABASE_URL", "").rstrip("/"), os.environ.get("SUPABASE_SERVICE_KEY", "")
    brevo, sender = os.environ.get("BREVO_API_KEY", ""), os.environ.get("ALERT_SENDER", "")
    site = os.environ.get("SITE_URL", "").rstrip("/") + "/"
    if not url or not key:
        print("SUPABASE_URL أو SUPABASE_SERVICE_KEY مش متحطين، اتساب")
        return 0
    if not a.dry_run and (not brevo or not sender):
        print("BREVO_API_KEY أو ALERT_SENDER مش متحطين، اتساب")
        return 0
    with open(a.prices, encoding="utf-8") as f:
        data = json.load(f)
    index = offers_index(data)
    r = requests.post(f"{url}/rest/v1/rpc/watch_targets", headers=_supabase_headers(key), json={}, timeout=60)
    if r.status_code >= 300:
        print(f"watch_targets فشل ({r.status_code}). شغّلت db/product_watches.sql؟", file=sys.stderr)
        return 1
    watches = r.json()
    at = datetime.now(timezone.utc)
    by_user: dict[str, dict] = {}
    updates: list[tuple[str, dict, bool]] = []
    for w in watches:
        now = state_of(w, data, index)
        why = reasons(w, now)
        if why and not due(w, at):
            continue  # اتبعتله النهارده: نسيب الحالة القديمة عشان يتبعت بكرة
        updates.append((w["id"], now, bool(why)))
        if not why:
            continue
        arabic = (w.get("lang") or "ar") != "en"
        u = by_user.setdefault(w["user_id"], {"email": w["email"], "name": w.get("name") or "", "arabic": arabic,
                                              "unsub": w.get("unsub_token"), "lines": []})
        where = ""
        if now["store"]:
            where = (f"أرخص عند {now['store']}: {now['total']:g} ج" if arabic else f"Cheapest at {now['store']}: {now['total']:g} EGP")
        u["lines"].append({"label": w["label"], "why": [p[0] if arabic else p[1] for p in why], "where": where})
    sent = 0
    for uid, u in by_user.items():
        unsub = f"{site}unsubscribe?t={u['unsub']}" if u["unsub"] else site
        subject = (f"Little Bird: {u['lines'][0]['label']}" + (f" و{len(u['lines']) - 1} كمان" if len(u["lines"]) > 1 else "")
                   if u["arabic"] else
                   f"Little Bird: {u['lines'][0]['label']}" + (f" and {len(u['lines']) - 1} more" if len(u["lines"]) > 1 else ""))
        body = email_html(u["name"], u["lines"], site, unsub, u["arabic"])
        if a.dry_run:
            print(f"[dry-run] {len(u['lines'])} منتج لحساب {uid[:8]}…: {subject}")
            continue
        res = requests.post(BREVO_URL, timeout=30, headers={"api-key": brevo, "accept": "application/json",
                                                             "content-type": "application/json"}, json={
            "sender": {"name": "Little Bird", "email": sender},
            "to": [{"email": u["email"], **({"name": u["name"]} if u["name"] else {})}],
            "subject": subject,
            "htmlContent": body,
            "headers": {"List-Unsubscribe": f"<{unsub}>"},
            "tags": ["watch"],
        })
        if res.status_code >= 300:
            print(f"Brevo رفض إيميل لحساب {uid[:8]}… ({res.status_code})", file=sys.stderr)
            # منحدّثش حالة منتجاته عشان يتجرّب تاني المرة الجاية
            updates = [x for x in updates if not (x[2] and any(w["id"] == x[0] and w["user_id"] == uid for w in watches))]
            continue
        sent += 1
    if a.dry_run:
        print(f"[dry-run] {len(watches)} منتج متابَع، {len(by_user)} إيميل")
        return 0
    for wid, now, notified in updates:
        patch = {"last_state": now, **({"last_notified_at": at.isoformat()} if notified else {})}
        requests.patch(f"{url}/rest/v1/product_watches?id=eq.{wid}", headers={**_supabase_headers(key), "Prefer": "return=minimal"},
                       json=patch, timeout=30)
    print(f"{len(watches)} منتج متابَع، اتبعت {sent} إيميل")
    return 0


if __name__ == "__main__":
    sys.exit(main())
