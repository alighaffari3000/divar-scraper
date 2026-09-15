# Divar Rental Ranking Engine

Collects rental listings from Divar, converts every one of them to a **full-deposit
equivalent**, compares each against the market median, and ranks them — on a map and
in a table.

Divar does the searching. This does the analysis, comparison and ranking.

**[فارسی ↓](#موتور-رتبهبندی-آگهیهای-اجاره-دیوار)**

- Project spec: [docs/SPEC.md](docs/SPEC.md)
- Build plan: [docs/PLAN.md](docs/PLAN.md)
- Divar API map: [docs/DIVAR_API.md](docs/DIVAR_API.md)
- Telegram bot plan: [docs/TELEGRAM_PLAN.md](docs/TELEGRAM_PLAN.md)

---

## Why

In Iran, rent is quoted as two numbers: an interest-free deposit (`ودیعه`) and a
monthly rent (`اجاره`). A 500M deposit + 15M rent and a 700M deposit + 9M rent are
the *same price*, but no listing site tells you that. Comparing listings by eye is
guesswork.

This converts everything to one number:

```text
full-deposit equivalent = deposit + monthly_rent × (100 / 3)
```

Every 100M of deposit is worth 3M of monthly rent — the prevailing market rate. The
rate is configurable; original `deposit` and `monthly_rent` are never overwritten.

Then it divides by floor area, compares against the median of the same search, and
scores each listing 0–100 with a visible breakdown.

## Setup

```bash
pip install requests fastapi uvicorn python-dotenv python-telegram-bot pillow
npm install
npm run css
python -m uvicorn web.app:app --port 8420
```

Then open <http://localhost:8420>. While working on the UI, keep `npm run css:watch`
running alongside.

## Web panel

Draw a rectangle or polygon on the map (or type a district name in the sidebar), set
your filters, hit search. Each row expands on click to show floor, amenities and the
full ad text. Pin colour reflects distance from the market median.

Over twenty optional filters, all off by default — nothing you leave blank is ever
sent to Divar. Highlights:

| Filter | Note |
|---|---|
| Real photos only | Divar asks advertisers whether the photos are of the actual property. ~29% say no. |
| Owner only | Excludes real-estate agencies. |
| Listing freshness | 3h / 12h / 1d / 3d / 7d |
| Max equivalent per m² | Divar has no such filter — this is the number that actually matters. |
| Below median only | Hides the expensive half. |
| Hide roommate ads | Shared-housing ads are not unit rentals and wreck the median. |

Scoring weights (price / newness / metro) are sliders. The server sends raw factors
and the browser recomputes — dragging a slider is instant, no round trip.

## Telegram bot

Posts the best listings into a group with delete and bookmark buttons. The bot's
trash and bookmarks are the **same database** as the panel's.

```text
1. Create a bot in BotFather, put the token in .env: TELEGRAM_BOT_TOKEN=...
2. Add the bot to your group and make it admin (Delete messages permission)
3. Run:  python -m divar_demo.bot
4. Send /id in the group; put the negative group id in .env: TELEGRAM_CHAT_ID=-100...
5. Restart. To keep it alive, schedule run_bot.cmd at logon with restart-on-failure.
```

Interval and score threshold are set **from the panel**; the bot re-reads the
database every minute, so no restart is needed. What gets posted: **new** listings
scoring ≥ threshold (default 70), at most 10 per cycle. The first run posts only the
top 10 and marks the rest as seen, so the group is not flooded. A price drop on an
already-posted listing arrives as a reply to the original post.

Commands: `/run` `/status` `/bookmarks` `/trash` `/mute 2h` `/searches` `/id`

`/bookmarks` is built live from the database each time — it shows the current price,
how much it moved since you bookmarked it, and whether the listing is still up.

## Command line

```bash
python -m divar_demo.main --district اختیاریه --size 80-150 --rooms 2 --real-photos
```

`--district` is optional; omit it to search the whole city.

## Layout

```text
divar_demo/collector.py   the only file that talks to Divar
divar_demo/listing.py     normalization, equivalent rent, hard filters, median, scoring
divar_demo/geo.py         polygons, district catalogue, metro distance
divar_demo/store.py       detail cache, price history, marks, bot state (SQLite)
divar_demo/search.py      search engine — CLI, panel and bot all call this
divar_demo/main.py        command line
divar_demo/bot.py         Telegram bot (polling + internal scheduler)
web/app.py                web panel (FastAPI)
web/static/               page, map, TailAdmin styling
data/districts_tehran.json   453 Tehran districts
data/metro_tehran.json       124 metro stations (OpenStreetMap)
```

## How it works

Divar's own map endpoint returns up to 200 listings per request with floor area,
rooms, building age, amenities and coordinates — no per-listing detail fetch needed.
The area is subdivided recursively until every cell is under that limit, and sibling
cells run in parallel.

In testing: **807 listings in 13 requests and 12 seconds, 100% coverage.** Going
through detail pages would have needed 807 requests and over half an hour.

Map-card prices are rounded (`۳ میلیارد`), so exact prices are joined from the list
endpoint per map cell. Detail pages (floor, storage, ad text) are fetched lazily on
click, cached for 7 days, behind a rate limiter — Divar returns 429 after 30 detail
requests in a ~30 second window.

## Known limitations

- The median is computed over the results of that same search, so your own price cap
  biases it. Read "% vs market" as an approximation, not a fact.
- Divar's pins are approximate (`approximate_location`); polygon filtering uses a
  ~200m tolerance.
- Metro distance is straight-line, not walking distance.
- "Real photos" is the advertiser's own answer, not image analysis. Someone lying is
  not detected — but the ~29% who tell the truth are filtered out.
- Map cards carry no storage, balcony, floor or description — those come from the
  detail page on click.
- Listings with negotiable ("توافقی") prices have no equivalent rent and are dropped.
- Divar's result count saturates at 10,000.
- A city-wide search with no filters hits the 150-request cap and reports incomplete
  coverage. Add a filter or draw a smaller area.
- Municipal zones ("منطقه ۷") do not exist in Divar's data — only districts. Draw an
  area instead.

## Not built yet

Duplicate-listing detection, ad-text analysis, market regression (the current median
is biased by the user's own price cap).

## Note

Personal use, on localhost. This uses Divar's internal API rather than the official
Kenar API. Do not make the panel public and do not raise the request rate.

---
---

<div dir="rtl">

# موتور رتبه‌بندی آگهی‌های اجاره دیوار

آگهی‌های اجاره را از دیوار می‌گیرد، همه را به **رهن کامل معادل** تبدیل می‌کند،
با median بازار مقایسه می‌کند و رتبه‌بندی‌شده نشان می‌دهد — روی نقشه و در جدول.

دیوار کار جستجو را می‌کند؛ این یکی کار تحلیل و مقایسه و رتبه‌بندی را.

**[English ↑](#divar-rental-ranking-engine)**

- مشخصات پروژه: [docs/SPEC.md](docs/SPEC.md)
- پلن اجرایی: [docs/PLAN.md](docs/PLAN.md)
- نقشه‌ی API دیوار: [docs/DIVAR_API.md](docs/DIVAR_API.md)
- پلن بات تلگرام: [docs/TELEGRAM_PLAN.md](docs/TELEGRAM_PLAN.md)

## چرا

قیمت اجاره با دو عدد گفته می‌شود: ودیعه و اجاره‌ی ماهانه. «۵۰۰ میلیون ودیعه + ۱۵
میلیون اجاره» و «۷۰۰ میلیون ودیعه + ۹ میلیون اجاره» *یک قیمت‌اند*، ولی هیچ سایتی
این را به شما نمی‌گوید. مقایسه‌ی چشمی آگهی‌ها حدس زدن است.

اینجا همه‌چیز به یک عدد تبدیل می‌شود:

```text
رهن کامل معادل = ودیعه + اجاره × (100 / 3)
```

هر ۱۰۰ میلیون ودیعه معادل ۳ میلیون اجاره — نرخ عرفی بازار. نرخ قابل تنظیم است و
مقادیر اصلی `deposit` و `monthly_rent` هیچ‌وقت overwrite نمی‌شوند.

بعد بر متراژ تقسیم می‌شود، با median همان جستجو مقایسه می‌شود، و هر آگهی امتیاز
۰ تا ۱۰۰ می‌گیرد با تفکیک قابل دیدن.

## راه‌اندازی

```bash
pip install requests fastapi uvicorn python-dotenv python-telegram-bot pillow
npm install
npm run css
python -m uvicorn web.app:app --port 8420
```

سپس <http://localhost:8420>. هنگام کار روی ظاهر، `npm run css:watch` را کنارش باز
بگذارید.

## پنل وب

روی نقشه مستطیل یا چندضلعی بکشید (یا در سایدبار نام محله را بنویسید)، فیلترها را
تنظیم کنید و «جستجو» بزنید. هر ردیف با کلیک باز می‌شود و طبقه، امکانات و متن کامل
آگهی را نشان می‌دهد. رنگ پین‌ها بر اساس فاصله از median بازار است.

بیش از بیست فیلتر اختیاری، همه پیش‌فرض خاموش — هر فیلتری که خالی بگذارید اصلاً به
دیوار فرستاده نمی‌شود. مهم‌ترین‌ها:

| فیلتر | توضیح |
|---|---|
| فقط عکس واقعی | دیوار از آگهی‌دهنده می‌پرسد عکس‌ها مال همین ملک است یا نه. حدود ۲۹٪ می‌گویند نه. |
| فقط مالک | آگهی‌های مشاور املاک حذف می‌شوند. |
| تازگی آگهی | ۳ ساعت / ۱۲ ساعت / ۱ روز / ۳ روز / ۷ روز |
| حداکثر رهن معادل متری | دیوار چنین فیلتری ندارد — و همین عدد است که واقعاً اهمیت دارد. |
| فقط زیر median | نیمه‌ی گران پنهان می‌شود. |
| پنهان کردن هم‌خانه | آگهی هم‌خانه اجاره‌ی واحد نیست و median را خراب می‌کند. |

وزن‌های امتیازدهی (قیمت / نوسازی / مترو) اسلایدر دارند. سرور ضرایب خام را می‌فرستد و
مرورگر خودش دوباره حساب می‌کند — کشیدن اسلایدر فوری است، بدون رفت‌وبرگشت.

## بات تلگرام

بهترین آگهی‌ها را در گروه پست می‌کند، با دکمه‌ی حذف و بوکمارک. سطل آشغال و بوکمارک
بات **همان دیتابیس** پنل است.

```text
۱. در BotFather یک بات بسازید و توکن را در .env بگذارید: TELEGRAM_BOT_TOKEN=...
۲. بات را به گروه اضافه و ادمین کنید (اجازه‌ی Delete messages)
۳. اجرا:  python -m divar_demo.bot
۴. در گروه /id بزنید؛ شناسه‌ی منفی گروه را در .env بگذارید: TELEGRAM_CHAT_ID=-100...
۵. دوباره اجرا کنید. برای همیشه‌روشن ماندن، run_bot.cmd را در Task Scheduler با
   «At log on» و «Restart on failure» بگذارید.
```

فاصله‌ی اجرا و آستانه‌ی امتیاز **از پنل** تنظیم می‌شوند؛ بات هر دقیقه دیتابیس را
می‌خواند، پس ری‌استارت لازم نیست. چه چیزی پست می‌شود: آگهی **جدید** با امتیاز ≥
آستانه (پیش‌فرض ۷۰)، حداکثر ۱۰ تا در هر دور. اجرای اول فقط ۱۰ تای برتر را
می‌فرستد و بقیه را «دیده‌شده» ثبت می‌کند تا گروه سیل نگیرد. ارزان‌شدن آگهی
پست‌شده به‌صورت reply روی همان پست می‌آید.

دستورها: `/run` `/status` `/bookmarks` `/trash` `/mute 2h` `/searches` `/id`

دستور `/bookmarks` هر بار زنده از دیتابیس ساخته می‌شود — قیمت الان، تغییر نسبت به
زمانی که بوکمارک کردید، و اینکه آگهی هنوز در دیوار هست یا نه.

## خط فرمان

```bash
python -m divar_demo.main --district اختیاریه --size 80-150 --rooms 2 --real-photos
```

گزینه‌ی `--district` اختیاری است؛ ندهید یعنی کل شهر.

## ساختار

```text
divar_demo/collector.py   تنها فایلی که با دیوار حرف می‌زند
divar_demo/listing.py     نرمال‌سازی، رهن معادل، فیلتر قطعی، median، امتیاز
divar_demo/geo.py         چندضلعی، کاتالوگ محله، فاصله مترو
divar_demo/store.py       کش جزئیات، تاریخچه قیمت، علامت‌ها، وضعیت بات (SQLite)
divar_demo/search.py      موتور جستجو — خط فرمان و پنل و بات هر سه همین را صدا می‌زنند
divar_demo/main.py        خط فرمان
divar_demo/bot.py         بات تلگرام (polling + زمان‌بند داخلی)
web/app.py                پنل وب (FastAPI)
web/static/               صفحه، نقشه، استایل TailAdmin
data/districts_tehran.json   ۴۵۳ محله تهران
data/metro_tehran.json       ۱۲۴ ایستگاه مترو (OpenStreetMap)
```

## چطور کار می‌کند

‏endpoint نقشه‌ی خود دیوار تا ۲۰۰ آگهی در هر درخواست می‌دهد، با متراژ، اتاق، سن
بنا، امکانات و مختصات — بدون نیاز به گرفتن صفحه‌ی جزئیات هر آگهی. محدوده به‌صورت
بازگشتی تقسیم می‌شود تا هر خانه زیر این سقف بماند، و خانه‌های هم‌سطح موازی اجرا
می‌شوند.

در تست: **۸۰۷ آگهی در ۱۳ درخواست و ۱۲ ثانیه، پوشش ۱۰۰٪.** همین کار از راه صفحه‌ی
جزئیات ۸۰۷ درخواست و بیش از نیم ساعت می‌خواست.

قیمت کارت نقشه گرد شده است («۳ میلیارد»)، پس قیمت دقیق به ازای هر خانه‌ی نقشه از
endpoint لیست join می‌شود. صفحه‌ی جزئیات (طبقه، انباری، متن آگهی) با کلیک و به‌صورت
تنبل گرفته می‌شود، ۷ روز کش می‌ماند، و پشت یک محدودکننده‌ی نرخ است — دیوار بعد از
۳۰ درخواست جزئیات در پنجره‌ی ~۳۰ ثانیه‌ای، ۴۲۹ می‌دهد.

## محدودیت‌های شناخته‌شده

- ‏median روی نتایج همان جستجو حساب می‌شود، پس سقف قیمت خودتان رویش اثر می‌گذارد.
  عدد «٪ بازار» یک تقریب است، نه واقعیت.
- پین‌های دیوار تقریبی‌اند (`approximate_location`)؛ فیلتر چندضلعی با تلورانس حدود
  ۲۰۰ متر کار می‌کند.
- فاصله‌ی مترو مستقیم است، نه پیاده‌روی.
- ‏«عکس واقعی» حرف خودِ آگهی‌دهنده است، نه تشخیص تصویر. اگر کسی دروغ بگوید سیستم
  نمی‌فهمد؛ ولی آن ۲۹٪ که راستش را می‌گویند حذف می‌شوند.
- کارت نقشه انباری، بالکن، طبقه و توضیحات ندارد — این‌ها با کلیک از صفحه‌ی جزئیات
  می‌آیند.
- آگهی «توافقی» رهن معادل ندارد و در فیلتر قطعی حذف می‌شود.
- شمارش دیوار روی ۱۰۰۰۰ اشباع می‌شود.
- جستجوی کل شهر بدون فیلتر به سقف ۱۵۰ درخواست می‌خورد و «پوشش ناقص» نشان می‌دهد.
  فیلتر بگذارید یا محدوده بکشید.
- ‏«منطقه ۷» در داده‌ی دیوار وجود ندارد؛ فقط محله. به‌جایش محدوده بکشید.

## چه چیزی هنوز نیست

تشخیص آگهی تکراری، تحلیل متن آگهی، رگرسیون بازار (median فعلی با سقف قیمت کاربر
سوگیری دارد).

## نکته

استفاده‌ی شخصی روی localhost. این پروژه از API داخلی دیوار استفاده می‌کند، نه API
رسمی کنار. پنل را عمومی نکنید و نرخ درخواست را بالا نبرید.

</div>
