"""اطلاع‌رسانی تلگرام — یک‌طرفه.

جستجوهای ذخیره‌شده را اجرا می‌کند و فقط تفاوت‌ها را می‌فرستد:
آگهی جدیدِ زیر median، یا آگهی‌ای که رهن معادلش کم شده.

اجرا:
    python -m divar_demo.notify            ارسال واقعی
    python -m divar_demo.notify --dry-run  فقط نمایش، بدون ارسال
"""

import argparse
import json
import sys

import requests

from . import config, search
from .store import Store

API = "https://api.telegram.org/bot{token}/{method}"


def _million(value):
    return "—" if value is None else f"{round(value / 1_000_000):,}"


def check_token():
    """اعتبار توکن را می‌سنجد بدون اینکه پیامی بفرستد."""
    resp = requests.get(API.format(token=config.TELEGRAM_BOT_TOKEN, method="getMe"), timeout=20)
    data = resp.json()
    if not data.get("ok"):
        raise RuntimeError(f"توکن معتبر نیست: {data.get('description')}")
    return data["result"]


def send(text):
    resp = requests.post(
        API.format(token=config.TELEGRAM_BOT_TOKEN, method="sendMessage"),
        json={
            "chat_id": config.TELEGRAM_CHAT_ID,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        },
        timeout=30,
    )
    data = resp.json()
    if not data.get("ok"):
        raise RuntimeError(f"ارسال نشد: {data.get('description')}")
    return data


def format_item(item, median):
    """یک آگهی → متن کوتاه تلگرام."""
    tags = []
    if item.get("is_new"):
        tags.append("🆕 جدید")
    drop = item.get("price_change_pct")
    if drop is not None and drop <= -config.NOTIFY_PRICE_DROP_PCT:
        tags.append(f"📉 {abs(round(drop))}٪ ارزان‌تر شده")

    amenities = " · ".join(filter(None, [
        "پارکینگ" if item.get("parking") else None,
        "آسانسور" if item.get("elevator") else None,
        "انباری" if item.get("storage") else None,
    ])) or "—"

    vs = item.get("vs_market_pct")
    vs_line = ""
    if vs is not None:
        side = "زیر" if vs < 0 else "بالای"
        vs_line = f"\n📊 {abs(round(vs))}٪ {side} median این جستجو"

    title = (item.get("title") or "").strip()
    size = item.get("size")
    rooms = item.get("rooms")

    lines = [f"<b>{title[:70]}</b>"]
    if tags:
        lines.append(" · ".join(tags))
    lines.append(
        f"🏠 {size:.0f} متر"
        + (f" · {rooms:.0f} خواب" if rooms is not None else "")
        + (f" · ساخت {item['year_built']}" if item.get("year_built") else "")
    )
    lines.append(
        f"💰 ودیعه {_million(item.get('deposit'))}م"
        f" + اجاره {_million(item.get('monthly_rent'))}م")
    lines.append(
        f"↔️ رهن معادل {_million(item.get('full_rent_equivalent'))}م"
        f" (متری {_million(item.get('fre_per_meter'))}م){vs_line}")
    lines.append(f"✅ {amenities}")
    lines.append(f"🔗 {item.get('url')}")
    return "\n".join(lines)


def worth_sending(item, median):
    """آیا این آگهی ارزش پیام دادن دارد؟"""
    if item.get("fre_per_meter") is None:
        return False

    drop = item.get("price_change_pct")
    if drop is not None and drop <= -config.NOTIFY_PRICE_DROP_PCT:
        return True  # ارزان شده — همیشه ارزش دارد

    if item.get("is_new") and median and item["fre_per_meter"] < median:
        return True  # جدید و زیر median

    return False


def run_saved_searches(dry_run=False, store_path=None):
    """همه جستجوهای ذخیره‌شده را اجرا و تفاوت‌ها را گزارش می‌کند."""
    sent_total = 0
    store_kwargs = {"path": store_path} if store_path else {}

    with Store(**store_kwargs) as store:
        saved = store.list_searches()
        if not saved:
            print("هیچ جستجوی ذخیره‌شده‌ای نیست.", file=sys.stderr)
            return 0

        for row in saved:
            params = json.loads(row["params_json"])
            polygon = [tuple(p) for p in params.pop("polygon", None) or []] or None
            print(f"اجرای «{row['name']}» ...", file=sys.stderr)

            result = search.run_search(polygon=polygon, store=store, **params)
            median = result["median_per_meter"]
            picks = [i for i in result["results"] if worth_sending(i, median)]
            picks = picks[: config.NOTIFY_MAX_ITEMS]

            if not picks:
                print(f"  چیز تازه‌ای نبود ({len(result['results'])} آگهی بررسی شد).",
                      file=sys.stderr)
                continue

            header = (f"🔎 <b>{row['name']}</b>\n"
                      f"{len(picks)} مورد قابل توجه از {len(result['results'])} آگهی")
            messages = [header] + [format_item(i, median) for i in picks]

            for text in messages:
                if dry_run:
                    print("---\n" + text)
                else:
                    send(text)
                sent_total += 1

            store.mark_search_run(row["id"])

    return sent_total


def main():
    parser = argparse.ArgumentParser(description="اطلاع‌رسانی تلگرام برای جستجوهای ذخیره‌شده")
    parser.add_argument("--dry-run", action="store_true",
                        help="فقط نمایش بده، چیزی نفرست")
    args = parser.parse_args()

    if not args.dry_run:
        gaps = config.missing()
        if gaps:
            print(f"این متغیرها در .env نیستند: {', '.join(gaps)}", file=sys.stderr)
            return 1
        bot = check_token()
        print(f"ربات: @{bot.get('username')}", file=sys.stderr)

    count = run_saved_searches(dry_run=args.dry_run)
    print(f"{count} پیام {'نمایش داده شد' if args.dry_run else 'فرستاده شد'}.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
