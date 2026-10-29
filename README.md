# Little Bird: فحص العروض كل ساعة

ده جزء صغير من **Little Bird** (مقارنة أسعار البقالة في مصر). بيشوف **صفحة العروض بس** في كل متجر كل ساعة،
عشان التطبيق يعرف الخصومات الجديدة بدري من غير ما يستنى الجمع الكبير.

## بيعمل إيه
- لكل متجر بيقرا صفحة/قسم العروض بس (من 1 لـ 20 طلب): سبينيس وجورميه (أقسام العروض)، ومحلات WooCommerce (`on_sale=true`).
- بيطلّع `offers.json`: المتجر، الكود، الاسم، السعر، السعر قبل الخصم، اللينك، وقت ما شفناه.
- بيرفعه على مخزن **مقفول** في Supabase (`prices/offers/latest.json`). الجمع الأساسي اللي بعده بيدمجه في الأسعار.

## القواعد (مش بتتغيّر)
- بنحترم `robots.txt` لكل موقع (ومعاه الـ API)، و`Crawl-delay`.
- طلب كل 3 ثواني أو أبطأ، و20 طلب بالكتير لكل متجر في الساعة.
- لو الموقع رفض (403 / 429 / 503) أو طلب «أنا مش روبوت»: بنوقف المتجر ده. عمرنا ما بنلف حوالين المنع.
- الـ User-Agent صريح (`LittleBirdOffers/1.0`) ومعاه إيميل تواصل.

## الريبو عام، فـ:
- **كود بس.** مفيش أسعار ولا بيانات متاجر ولا ملفات CSV/JSON في الريبو (‎`.gitignore` بيمنعها).
- **مفيش مفاتيح في الكود.** المفاتيح في GitHub → Settings → Secrets and variables → Actions:
  - Secret: `SUPABASE_SERVICE_KEY` (مفتاح service_role القديم، بيبدأ بـ eyJ)، `ARKHAS_CONTACT` (إيميل التواصل).
  - Variable: `SUPABASE_URL`.
- الـ workflow مش بيشتغل على pull requests، عشان المفاتيح متوصلش لحد.

## تجربة على الجهاز
```
pip install -r requirements.txt
python offers.py --store ecart --out offers.json
python -m unittest discover tests
```
