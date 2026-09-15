"""قالب پیام‌های بات تلگرام. هیچ منطق قیمت/امتیازی اینجا نیست — فقط نمایش.

همه‌ی متن‌ها با parse_mode=HTML فرستاده می‌شوند و هر چیزی که از آگهی می‌آید
(عنوان، محله، نام ایستگاه) escape می‌شود — محتوای کاربر غریبه است.
"""

import html
from datetime import datetime, timezone

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from . import config
from .listing import full_rent_equivalent

LABELS = {"deal": "قیمت", "age": "نوسازی", "metro": "مترو"}


def esc(text):
    return html.escape(str(text if text is not None else ""), quote=False)


def m(value):
    """تومان → «N م» (میلیون، گردشده)"""
    return "—" if value is None else f"{round(value / 1_000_000):,}"


def caption(item, median):
    """متن پست یک آگهی. عنوان آگهی عمداً نیست — نویز است؛ ساختار مهم است."""
    size = item.get("size")
    rooms = item.get("rooms")
    year = item.get("year_built")
    district = item.get("district")

    head = f"🏠 {size:.0f} متر" if size else "🏠"
    if rooms is not None:
        head += f" · {rooms:.0f} خواب"
    if year:
        head += f" · ساخت {year}"
    if district:
        head += f" · {esc(district)}"

    lines = [f"<b>{head}</b>"]
    lines.append(
        f"💰 ودیعه {m(item.get('deposit'))}م + اجاره {m(item.get('monthly_rent'))}م"
        f"  →  رهن معادل <b>{m(item.get('full_rent_equivalent'))}م</b>"
        f" (متری {m(item.get('fre_per_meter'))}م)")

    market = ""
    vs = item.get("vs_market_pct")
    if vs is not None:
        market = f"📊 {abs(round(vs))}٪ {'زیر' if vs < 0 else 'بالای'} median"
    metro = ""
    if item.get("metro_distance_m") is not None:
        metro = f"🚇 {esc(item.get('metro_name'))} {item['metro_distance_m']:,}م"
    if market or metro:
        lines.append("   ·   ".join(filter(None, [market, metro])))

    amenities = " · ".join(filter(None, [
        "پارکینگ" if item.get("parking") else None,
        "آسانسور" if item.get("elevator") else None,
        "انباری" if item.get("storage") else None,
    ])) or "بدون امکانات ثبت‌شده"
    photo = ""
    if item.get("real_photos") is True:
        photo = "   ·   📷 عکس واقعی"
    elif item.get("real_photos") is False:
        photo = "   ·   ⚠️ عکس تزئینی"
    lines.append(f"✅ {amenities}{photo}")

    parts = item.get("score_parts") or {}
    breakdown = " · ".join(
        f"{LABELS.get(k, k)} {'+' if v > 0 else ''}{round(v)}" for k, v in parts.items())
    lines.append(f"⭐ امتیاز <b>{round(item.get('score') or 0)}</b>"
                 + (f"  ({breakdown})" if breakdown else ""))

    if item.get("price_is_rounded"):
        lines.append("<i>قیمت گردشده — دقیق نیست</i>")

    return "\n".join(lines)[:1000]


def keyboard(token, bookmarked=False, url=None):
    star = "★ بوکمارک شد" if bookmarked else "☆ بوکمارک"
    row = [
        InlineKeyboardButton("🗑 حذف", callback_data=f"t:{token}"),
        InlineKeyboardButton(star, callback_data=f"b:{token}"),
    ]
    if url:
        row.append(InlineKeyboardButton("🔗 دیوار", url=url))
    return InlineKeyboardMarkup([row])


def drop_reply(item, old_fre):
    new_fre = item.get("full_rent_equivalent") or 0
    pct = (old_fre - new_fre) / old_fre * 100 if old_fre else 0
    return (f"📉 <b>{round(pct)}٪ ارزان شد</b>\n"
            f"رهن معادل {m(old_fre)}م → <b>{m(new_fre)}م</b>"
            f" (ودیعه {m(item.get('deposit'))}م + اجاره {m(item.get('monthly_rent'))}م)")


def _age_minutes(iso):
    if not iso:
        return None
    try:
        then = datetime.fromisoformat(iso)
        if then.tzinfo is None:
            then = then.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - then).total_seconds() / 60
    except ValueError:
        return None


def bookmarks_text(rows, store, interval_minutes, rate):
    """لیست زنده بوکمارک‌ها. rows از store.marked_items('bookmark')."""
    if not rows:
        return "📌 هنوز چیزی بوکمارک نشده."

    lines = [f"📌 <b>بوکمارک‌ها ({len(rows)})</b>", ""]
    for i, r in enumerate(rows, 1):
        token = r["token"]
        now_fre = full_rent_equivalent(r.get("deposit"), r.get("monthly_rent"), rate)
        then = store.snapshot_at(token, r["marked_at"])
        then_fre = full_rent_equivalent(then["deposit"], then["monthly_rent"], rate) if then else None

        delta = "➖"
        if now_fre and then_fre and then_fre:
            d = (now_fre - then_fre) / then_fre * 100
            if abs(d) >= 1:
                delta = f"{'📉' if d < 0 else '📈'} {'+' if d > 0 else '−'}{abs(round(d))}٪"

        age = _age_minutes(store.post_last_seen(token))
        gone = age is not None and age > 2 * interval_minutes + 5
        status = "❌ دیگر در دیوار نیست" if gone else delta

        size = f"{r['size']:.0f}م²" if r.get("size") else "?"
        per_m = f"متری {m(now_fre / r['size'])}م" if (now_fre and r.get("size")) else ""
        title = esc((r.get("title") or "")[:40])
        lines.append(
            f"{i}. <b>{size}</b> · {esc(r.get('district') or '')} · {per_m}   {status}\n"
            f"   {title}\n"
            f"   <a href=\"https://divar.ir/v/{esc(token)}\">دیوار</a>"
            + (f"   💬 {esc(r['note'])}" if r.get("note") else ""))
    return "\n".join(lines)


def trash_text(rows):
    if not rows:
        return "🗑 سطل آشغال خالی است."
    lines = [f"🗑 <b>آخرین حذف‌شده‌ها ({len(rows)})</b>", ""]
    for i, r in enumerate(rows, 1):
        size = f"{r['size']:.0f}م²" if r.get("size") else "?"
        lines.append(f"{i}. {size} · {esc(r.get('district') or '')} · "
                     f"{esc((r.get('title') or '')[:35])}")
    return "\n".join(lines)


def restore_keyboard(rows):
    buttons = [InlineKeyboardButton(f"↩️ بازگردانی {i}", callback_data=f"r:{r['token']}")
               for i, r in enumerate(rows, 1)]
    return InlineKeyboardMarkup([buttons[j:j + 4] for j in range(0, len(buttons), 4)])


def status_text(store, settings, chat_ok):
    last = store.last_ok_run()
    runs = store.last_runs(3)
    lines = ["🤖 <b>وضعیت بات</b>", ""]
    lines.append(f"گروه: {'✅ تنظیم شده' if chat_ok else '⚠️ TELEGRAM_CHAT_ID خالی است — /id بزنید'}")
    lines.append(f"فاصله اجرا: هر {settings['interval_minutes']:.0f} دقیقه")
    lines.append(f"آستانه امتیاز: {settings['score_threshold']:.0f}")
    if settings.get("muted_until"):
        lines.append(f"🔇 ساکت تا {esc(settings['muted_until'][:16])}")
    if last:
        age = _age_minutes(last["finished_at"])
        lines.append(f"آخرین اجرای موفق: {round(age) if age is not None else '?'} دقیقه پیش"
                     f" — {last.get('sent') or 0} پیام")
    else:
        lines.append("هنوز اجرایی نداشته.")
    fails = store.consecutive_failures()
    if fails:
        err = next((r["error"] for r in runs if r.get("error")), "")
        lines.append(f"⚠️ {fails} اجرای اخیر خطا داد: {esc((err or '')[:120])}")
    return "\n".join(lines)


def searches_text(rows):
    if not rows:
        return "هیچ جستجویی در پنل ذخیره نشده."
    lines = [f"🔎 <b>جستجوهای ذخیره‌شده ({len(rows)})</b>", ""]
    for r in rows:
        last = r.get("last_run_at")
        lines.append(f"• {esc(r['name'])}" + (f" — آخرین اجرا {esc(last[:16])}" if last else ""))
    return "\n".join(lines)
