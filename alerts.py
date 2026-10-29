"""إيميلات «منتجاتي اللي مستنيها» كل ساعة: لو منتج حد مستنيه نزل عليه عرض جديد في فحص الساعة دي.

بيشتغل بس لو BREVO_API_KEY متحط. عشان نوفّر استهلاك Supabase: الأول بنجيب قايمة المنتجات المستنية (صغيرة)،
ولو مفيش ولا واحد منها في العروض الجديدة، منحمّلش ملف الأسعار خالص. ملف الأسعار بيتحمّل على جهاز GitHub
المؤقت ويتمسح معاه: مبيتعملوش commit ولا artifact.

    python alerts.py offers.json
"""
from __future__ import annotations

import json
import os
import sys
import tempfile

import requests

import send_watch_emails
from offers_merge import merge


def _headers(key: str) -> dict:
    return {"apikey": key, "Authorization": f"Bearer {key}"}


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    url, key = os.environ.get("SUPABASE_URL", "").rstrip("/"), os.environ.get("SUPABASE_SERVICE_KEY", "")
    if not os.environ.get("BREVO_API_KEY") or not url or not key:
        print("BREVO_API_KEY أو Supabase مش متحطين، اتساب")
        return 0
    with open(argv[0], encoding="utf-8") as f:
        offers = json.load(f)
    keys = {f"{o['store']}:{o['id']}" for o in offers.get("offers") or []}
    r = requests.post(f"{url}/rest/v1/rpc/watch_targets", headers={**_headers(key), "Content-Type": "application/json"},
                      json={}, timeout=60)
    if r.status_code >= 300:
        print(f"watch_targets فشل ({r.status_code})")
        return 0
    watched = {k for w in r.json() for k in w.get("offers") or []}
    hit = watched & keys
    print(f"منتجات مستنية فيها عرض جديد: {len(hit)}")
    if not hit:
        return 0
    p = requests.get(f"{url}/storage/v1/object/prices/prices.json", headers=_headers(key), timeout=120)
    if p.status_code >= 300:
        print(f"ملف الأسعار مجاش ({p.status_code})")
        return 0
    prices = p.json()
    merge(prices, offers)
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "prices.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(prices, f, ensure_ascii=False)
        return send_watch_emails.main([path])


if __name__ == "__main__":
    sys.exit(main())
