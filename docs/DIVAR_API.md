# نقشه‌ی API داخلی دیوار

نتیجه‌ی کشف با مرورگر و پروب مستقیم — ۱۴۰۵/۰۶/۲۴ (2026-09-15).
همه‌ی موارد زیر **تست شده‌اند** مگر جایی که «تأییدنشده» نوشته باشد.

هدر مشترک همه‌ی درخواست‌ها:

```text
User-Agent: (مرورگر معمولی)
Content-Type: application/json
Origin: https://divar.ir
Referer: https://divar.ir/
```

---

## ۱. جستجو — بدون لاگین

```text
POST https://api.divar.ir/v8/postlist/w/search
```

بدنه:

```json
{
  "city_ids": ["1"],
  "search_data": {"form_data": {"data": { ...فیلترها... }}},
  "pagination_data": {"@type": "type.googleapis.com/post_list.PaginationData", "page": 1}
}
```

- هر صفحه ۲۴ آگهی (`list_widgets[].widget_type == "POST_ROW"`).
- برای صفحه‌ی بعد، `pagination.data` پاسخ قبلی را عیناً در `pagination_data` بفرست.
  `pagination.has_next_page` می‌گوید ادامه دارد یا نه.
- هر ردیف: `title`، `action.payload.token`، `web_info.district_persian`،
  `top_description_text` (ودیعه)، `middle_description_text` (اجاره یا «رهن کامل»)،
  `bottom_description_text` (نام آژانس یا زمان انتشار)، `image_count`.
- **متراژ در لیست نیست.** فقط در جزئیات.

شهرها: تهران=۱، مشهد=۲، اصفهان=۳، کرج=۴، شیراز=۵، تبریز=۶.

### قرارداد فیلترها

نکته‌ی حیاتی: **دیوار مقدار یا نوع اشتباه را بی‌صدا نادیده می‌گیرد** و ۲۰۰ برمی‌گرداند
(مگر برای گزینه‌های enum که ۴۰۰ می‌دهد). پس هر فیلتر جدید باید با diff توکن‌ها تست شود،
نه فقط با status code.

| کلید | نوع | مقدار | وضعیت |
|---|---|---|---|
| ‏`category` | `str` | `apartment-rent` | تست شده |
| ‏`districts` | `repeated_string` | شناسه‌ی عددی محله، مثلاً `["68"]` | تست شده |
| ‏`bbox` | `repeated_float` | `[minLon, minLat, maxLon, maxLat]` به شکل `{"value":[{"value":51.44},…]}` — محدوده‌ی جغرافیایی، جایگزین محله | تست شده — نتایج از چند محله برمی‌گردد |
| ‏`size` | `number_range` | `{"minimum":"80","maximum":"150"}` | تست شده |
| ‏`credit` | `number_range` | تومان | تست شده |
| ‏`rent` | `number_range` | تومان | تست شده |
| ‏`rooms` | `repeated_string` | **کلمه‌ی فارسی**: `["دو","سه","چهار"]` | تست شده — `number_range` نادیده گرفته می‌شود |
| ‏`business-type` | `repeated_string` | `personal` یا `real-estate-business` | تست شده |
| ‏`parking` | `boolean` | `{"value": true}` | تست شده |
| ‏`has-photo` | `boolean` | «دارای عکس **از ملک**» — عکس تزئینی را حذف می‌کند | تست شده |
| ‏`has-video` | `boolean` | | تست شده — فقط ~۲٪ آگهی‌ها |
| ‏`balcony` `rebuilt` | `boolean` | همان فرمت | تست شده |
| ‏`elevator` `warehouse` | `boolean` | همان فرمت | از schema، تأییدنشده |
| ‏`building-age` `floor` `floors_count` `unit_per_floor` | `number_range` | | تست شده |
| ‏`building_direction` | `repeated_string` | `north` `south` `east` `west` | از schema |
| ‏`cooling_system` `heating_system` | `repeated_string` | گزینه‌های دقیق پایین | تست شده |
| ‏`floor_type` `warm_water_provider` | `repeated_string` | | `warm_water_provider` تست شده |
| ‏`recent_ads` | `str` | `3h` `12h` `1d` `3d` `7d` | تست شده |
| ‏`toilet` | `str` | `squat` `seat` `squat_seat` | تست شده |
| ‏`rooms` گزینه‌های کامل | | `بدون اتاق` `یک` `دو` `سه` `چهار` `بیشتر` | از schema |

فرمت نمونه:

```json
{
  "category": {"str": {"value": "apartment-rent"}},
  "districts": {"repeated_string": {"value": ["68", "72"]}},
  "size": {"number_range": {"minimum": "80", "maximum": "150"}},
  "rooms": {"repeated_string": {"value": ["دو", "سه"]}},
  "parking": {"boolean": {"value": true}},
  "business-type": {"repeated_string": {"value": ["personal"]}}
}
```

مقادیر `rooms` از schema خود دیوار: `بدون اتاق`، `یک`، `دو`، `سه`، `چهار`، `بیشتر`.
(«پنج یا بیشتر» غلط است — مقدار واقعی فقط `بیشتر` است.)

---

## ۲. جزئیات آگهی — بدون لاگین

```text
GET https://api.divar.ir/v8/posts-v2/web/{token}
```

پاسخ `sections[]` است و هر section چند `widgets[]` دارد. آنچه لازم داریم:

| ویجت | محتوا |
|---|---|
| ‏`GROUP_INFO_ROW` | `items[]` با `title`/`value`: متراژ، ساخت، اتاق |
| ‏`UNEXPANDABLE_ROW` | `title`/`value`: طبقه، «ودیعه و اجاره» (قابل تبدیل یا نه)، **«تصویر‌ها برای همین ملک است؟»** (بله/خیر)، **گاهی** ودیعه و اجاره |
| ‏`GROUP_FEATURE_ROW` | `items[].title`: «آسانسور» یا «آسانسور ندارد» — نبود با پسوند «ندارد» |
| ‏`DESCRIPTION_ROW` | `text`: متن کامل آگهی |
| ‏`IMAGE_CAROUSEL` | `items[].image.url` — برای تشخیص تکراری با هش عکس |
| ‏`MAP_ROW` | مختصات (بررسی‌نشده) |

هشدار: ردیف‌های ودیعه/اجاره در جزئیات **همیشه وجود ندارند**. قیمت را از ردیف لیست بخوان.

اطلاعات مالک/آژانس در `POST /v8/premium-user/post-page/business-data/{token}/lazy` می‌آید
(بدون لاگین، ولی فعلاً استفاده نمی‌کنیم — `business-type` در جستجو کافی است).

---

## ۲.۵. جستجوی نقشه‌ای — بدون لاگین — **مهم‌ترین endpoint برای پنل وب**

```text
POST https://api.divar.ir/v8/mapview/viewport
```

بدنه:

```json
{
  "city_ids": ["1"],
  "search_data": {"form_data": {"data": { ...همان فیلترهای جستجو... }}},
  "camera_info": {
    "bbox": {"minLongitude": 51.4459, "minLatitude": 35.7799,
             "maxLongitude": 51.4764, "maxLatitude": 35.7932},
    "zoom": 14
  }
}
```

پاسخ:

- ‏`count` — تعداد کل آگهی‌های محدوده (مثلاً ۱۳۹۷) و `count_text`.
- ‏`posts[]` — **حداکثر ۲۰۰** آگهی. بیشتر از آن برنمی‌گردد؛ محدوده را تقسیم کن.
- در زوم پایین (≈۱۱ و کمتر) `posts` خالی است و فقط `count` می‌آید (خوشه‌بندی).
  زوم ۱۴ تا ۱۶ تست شده و آگهی می‌دهد.
- هر `posts[i]`:
  - ‏`map_post_card.token`, `title`, `images[]`
  - ‏`map_post_card.price_fields[]` — `{"title":"ودیعه:","value":"۳ میلیارد"}` (عدد **گردشده**؛ برای مقدار دقیق از لیست یا جزئیات)
  - ‏`map_post_card.chips[]` — `«۲۰۰ متر»`, `«۳ اتاق»`, `«۲۰ سال»`, و آیکون‌های `parking.png` / `elevator.png` / … (بدون title)
  - ‏`map_pin_feature.lat`, `.lon`, `.approximate_location` (bool)

چرا مهم است: متراژ، اتاق، سن بنا، امکانات و مختصات **بدون صفحه‌ی جزئیات** می‌آیند.
تا ۲۰۰ آگهی در یک درخواست، به‌جای ۲۰۰ درخواست جزئیات. فیلترها (متراژ و …) اعمال
می‌شوند (تست شده: با `size 80-150` شمارش از ۱۳۹۷ به ۸۲۲ رسید و همه‌ی متراژها در بازه بودند).

**محدودیت نرخ:** ۱۲۰ درخواست پشت‌سرهم در ۲۵ ثانیه، بدون هیچ ۴۲۹ (اندازه‌گیری ۱۴۰۵/۰۶/۲۴).
بر خلاف صفحه‌ی جزئیات، این endpoint عملاً محدود نیست. با این حال با تأخیر کوتاه صدا زده شود.

پوشش واقعی در تست: محدوده‌ی اختیاریه/قیطریه با `size 80-150` و `rooms≥2` →
‏`count=807`، و تقسیم بازگشتی با **۱۳ درخواست در ۱۲ ثانیه** هر ۸۰۷ آگهی را برگرداند
(پوشش ۱۰۰٪). همان کار از راه صفحه‌ی جزئیات ۸۰۷ درخواست و بیش از نیم ساعت می‌خواست.

**چیزی که در کارت نقشه نیست:** انباری، بالکن، طبقه، سال دقیق ساخت، توضیحات، قابل تبدیل بودن.
چیپ‌های موجود فقط `«N متر»`، `«N اتاق»` (یا `«بدون اتاق»`)، `«N سال»` (یا `«نوساز»`) و
آیکون‌های `parking.png` و `elevator.png` هستند. برای انباری یا فیلتر سمت دیوار را روشن کن
یا صفحه‌ی جزئیات را بگیر.

---

## ۳. کاتالوگ محله‌ها — بدون لاگین

```text
GET https://api.divar.ir/v8/places/cities/{city_id}/districts
```

تهران: ۴۵۳ محله. هر مورد: `id`، `name`، `slug`، `second_slug`، `default_location`
(مختصات مرکز)، `bbox`، `neighbors`، `tags` (خیابان‌های اصلی).
کپی ذخیره‌شده: `data/districts_tehran.json`.

- هیچ سطح «منطقه‌ی شهرداری» (منطقه ۷ و …) در کاتالوگ نیست (`level` و `parent` همه خالی).
  اگر «منطقه» لازم است باید دستی به مجموعه‌ی محله‌ها نگاشت شود.
- ‏`/v8/places/districts?city_id=1` → ۴۰۳. از مسیر بالا استفاده کن.

---

## ۴. پشت لاگین

```text
POST https://api.divar.ir/v8/postcontact/web/contact_info_v2/{token}   → 401 بدون لاگین
```

فقط شماره‌ی تماس. برای رتبه‌بندی لازم نیست. لاگین با OTP پیامکی است؛ اگر روزی لازم شد،
کاربر خودش در مرورگر وارد می‌شود و کوکی نشست استفاده می‌شود — هیچ‌وقت خودکار نشود.

---

## ۵. سایر endpointهایی که وب‌اپ می‌زند (بی‌فایده برای ما)

```text
POST /v8/mapview/viewport                       نمایش نقشه (شاید بعداً برای جستجوی جغرافیایی)
GET  /v8/post-stats/receive-post-stats-batch    آمار بازدید
POST /v1/client-exporter/send-report            تله‌متری
POST /v8/actionlog/send                         تله‌متری
GET  /v8/my-divar/web/menu                      منوی کاربر
GET  /v8/search-bookmark/web/get-search-bar-empty-state
POST /v8/auth/open-initiate-page                شروع لاگین
```

---

## ۶. محدودیت نرخ

- جزئیات: بعد از **۳۰ درخواست** پشت‌سرهم، `429 Too Many Requests`.
  طول پنجره اندازه‌گیری نشده (احتمالاً ۶۰ ثانیه). عقب‌نشینی ۱۰/۳۰/۶۰ ثانیه جواب داد.
- جستجو: در ۲۰-۳۰ درخواست متوالی محدودیتی دیده نشد.
- هیچ توکن، امضا یا کوکی اجباری برای جستجو و جزئیات وجود ندارد.


---

## ۷. گزینه‌های enum (تست‌شده روی محدوده اختیاریه، پایه = ۱۳۹۷ آگهی)

```text
recent_ads           3h(4) 12h 1d(123) 3d 7d
heating_system       heater shoofaj(148) fan_coil floor_heating(1) duct_split(150) split
cooling_system       water_cooler air_conditioner duct_split(173) split fan_coil
warm_water_provider  water_heater powerhouse package(107)
floor_type           ceramic wood_parquet laminate_parquet stone floor_covering carpet
building_direction   north south east west
toilet               squat seat(32) squat_seat
rooms                «بدون اتاق» «یک» «دو» «سه» «چهار» «بیشتر»
business-type        personal real-estate-business
```

عدد داخل پرانتز = تعداد نتیجه در آزمون. مقدار خارج از این فهرست ۴۰۰ می‌گیرد
(بر خلاف بقیه فیلترها که بی‌صدا نادیده گرفته می‌شوند).

**اشتباه رایج:** `package` مال `warm_water_provider` است، نه `heating_system`.
