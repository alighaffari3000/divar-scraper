"""بات تلگرام — بهترین آگهی‌ها را در گروه پست می‌کند، با دکمه حذف و بوکمارک.

    python -m divar_demo.bot

هیچ منطق قیمت/فیلتر/امتیاز اینجا نیست؛ فقط search.run_search صدا زده می‌شود.
سطل آشغال و بوکمارک همان جدول marks پنل است — یک دیتابیس، دو رابط.

چرخه:
    هر ۶۰ ثانیه چک می‌کند «وقت اجرا شده؟» (فاصله از settings پنل خوانده می‌شود)
    → هر جستجوی ذخیره‌شده اجرا
    → جدید و امتیاز ≥ آستانه → پست با عکس و دکمه
    → قبلاً پست‌شده و ارزان‌شده → reply روی همان پست
"""

import asyncio
import io
import json
import logging
import re
import sys
from datetime import datetime, timedelta, timezone

import requests
from telegram import InputMediaPhoto, Update
from telegram.error import BadRequest, Forbidden, TelegramError
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes

from . import bot_format as fmt
from . import collector, config, listing, search
from .store import Store

log = logging.getLogger("divar.bot")

TICK_SECONDS = 60
PHOTOS_PER_POST = 3  # تلگرام تا ۱۰ تا در گالری می‌پذیرد؛ ۳ تا گروه را شلوغ نمی‌کند
cycle_lock = asyncio.Lock()


# ---------- کمکی ----------

def chat_id():
    return config.TELEGRAM_CHAT_ID


def allowed(update: Update) -> bool:
    """فقط گروه تنظیم‌شده. /id استثناست تا بشود شناسه گروه را پیدا کرد."""
    return bool(chat_id()) and str(update.effective_chat.id) == str(chat_id())


def settings(store):
    return {
        "interval_minutes": float(store.get_setting("interval_minutes",
                                                     config.BOT_INTERVAL_MINUTES)),
        "score_threshold": float(store.get_setting("score_threshold",
                                                    config.BOT_SCORE_THRESHOLD)),
        "muted_until": store.get_setting("muted_until"),
    }


def _iso(dt):
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds")


def _parse_iso(text):
    if not text:
        return None
    dt = datetime.fromisoformat(text)
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def photo_bytes(url):
    """عکس دیوار (webp) → JPEG. تلگرام webp را به‌عنوان عکس قبول نمی‌کند."""
    try:
        raw = requests.get(url, timeout=20).content
    except requests.RequestException:
        return None
    try:
        from PIL import Image

        img = Image.open(io.BytesIO(raw)).convert("RGB")
        out = io.BytesIO()
        # کیفیت بالا چون منبع حالا webp_post است، نه بندانگشتی
        img.save(out, format="JPEG", quality=92, optimize=True)
        return out.getvalue()
    except Exception:  # Pillow نیست یا فایل خراب است — خام بفرست، شاید قبول کند
        return raw


def photo_urls(store, item):
    """آدرس عکس‌های اندازه کامل. اگر جزئیات در دسترس نبود، بندانگشتی کارت."""
    token = item["token"]
    try:
        urls = (store.get_detail(token) or {}).get("images") or []
        if not urls:
            # کش قبل از افزوده‌شدن images پر شده بود — تازه بگیر و همان را جا بگذار
            detail = collector.fetch_detail(token)
            store.put_detail(token, detail)
            urls = detail.get("images") or []
        if urls:
            return urls
    except Exception:
        log.warning("گرفتن عکس‌های %s نشد", token, exc_info=True)
    return [item["image_url"]] if item.get("image_url") else []


# ---------- ارسال ----------

async def post_item(bot, store, item, median, search_id):
    text = fmt.caption(item, median)
    kb = fmt.keyboard(item["token"], item.get("bookmarked"), item.get("url"))

    photos = []
    if item.get("real_photos") is not False:
        urls = await asyncio.to_thread(photo_urls, store, item)
        for url in urls[:PHOTOS_PER_POST]:
            data = await asyncio.to_thread(photo_bytes, url)
            if data:
                photos.append(data)

    msg = None
    media_ids = []

    # کپشن روی خودِ آلبوم می‌نشیند تا عکس و متن یک پست باشند. دکمه‌ها ناچار
    # جدا می‌روند: تلگرام برای media group دکمه شیشه‌ای نمی‌پذیرد.
    # تلگرام کپشن عکس را تا ۱۰۲۴ نویسه می‌پذیرد (متن ساده تا ۴۰۹۶)
    caption = text if len(text) <= 1024 else None

    if len(photos) > 1:
        try:
            media = [InputMediaPhoto(photos[0], caption=caption, parse_mode="HTML")]
            media += [InputMediaPhoto(p) for p in photos[1:]]
            group = await bot.send_media_group(chat_id(), media=media)
            media_ids = [m.message_id for m in group]
            msg = await bot.send_message(chat_id(),
                                         fmt.ACTIONS_LINE if caption else text,
                                         parse_mode="HTML", reply_markup=kb,
                                         reply_to_message_id=media_ids[0],
                                         disable_web_page_preview=True)
        except TelegramError as exc:
            log.warning("send_media_group failed for %s: %s", item["token"], exc)
            msg, media_ids = None, []
    elif len(photos) == 1:
        try:
            msg = await bot.send_photo(chat_id(), photo=photos[0], caption=caption or text[:1024],
                                       parse_mode="HTML", reply_markup=kb)
        except TelegramError as exc:
            log.warning("send_photo failed for %s: %s", item["token"], exc)

    if msg is None:
        msg = await bot.send_message(chat_id(), text, parse_mode="HTML", reply_markup=kb,
                                     disable_web_page_preview=True)

    store.record_sent(item["token"], chat_id(), msg.message_id, search_id,
                      item.get("score"), item.get("full_rent_equivalent"),
                      media_ids=media_ids)
    return msg


async def run_cycle(bot, store, trigger="timer"):
    """یک دور کامل. بازگشت: تعداد پیام فرستاده‌شده."""
    if not chat_id():
        log.warning("TELEGRAM_CHAT_ID خالی است — چرخه رد شد. در گروه /id بزنید.")
        return 0

    run_id = store.start_run()
    sent = 0
    try:
        conf = settings(store)
        threshold = conf["score_threshold"]
        already = store.sent_tokens(chat_id())

        for saved in store.list_searches(only_enabled=True):
            kwargs = search.params_from_request(json.loads(saved["params_json"]))
            log.info("اجرای «%s» (%s)", saved["name"], trigger)
            result = await asyncio.to_thread(
                lambda: search.run_search(store=store, **kwargs))
            median = result["median_per_meter"]

            # جدید و بالای آستانه — به ترتیب امتیاز، با سقف هر دور
            first_run = not already
            fresh = [i for i in result["results"]
                     if i["token"] not in already and (i.get("score") or 0) >= threshold]
            for item in fresh[: config.NOTIFY_MAX_ITEMS]:
                await post_item(bot, store, item, median, saved["id"])
                already.add(item["token"])
                sent += 1

            # اجرای اول: بقیه را «دیده‌شده» ثبت کن تا گروه سیل نگیرد.
            # از این به بعد فقط آگهی‌هایی می‌آیند که واقعاً بعد از شروع بات آمده‌اند.
            if first_run:
                for item in fresh[config.NOTIFY_MAX_ITEMS:]:
                    store.record_sent(item["token"], chat_id(), None, saved["id"],
                                      item.get("score"), item.get("full_rent_equivalent"))
                    already.add(item["token"])
                if len(fresh) > config.NOTIFY_MAX_ITEMS:
                    log.info("اجرای اول: %d آگهی دیگر بدون پست ثبت شد",
                             len(fresh) - config.NOTIFY_MAX_ITEMS)

            # قبلاً پست‌شده و ارزان‌شده — reply روی همان پست
            for item in result["results"]:
                if item["token"] not in already:
                    continue
                prev = store.sent_post(item["token"], chat_id())
                if not prev or not prev.get("last_fre") or not item.get("full_rent_equivalent"):
                    continue
                cut = prev["last_fre"] * (1 - config.NOTIFY_PRICE_DROP_PCT / 100)
                if item["full_rent_equivalent"] <= cut:
                    try:
                        await bot.send_message(
                            chat_id(), fmt.drop_reply(item, prev["last_fre"]),
                            parse_mode="HTML", reply_to_message_id=prev["message_id"])
                    except BadRequest:  # پست اصلی حذف شده — بدون reply
                        await bot.send_message(chat_id(), fmt.drop_reply(item, prev["last_fre"]),
                                               parse_mode="HTML")
                    store.update_sent_fre(item["token"], chat_id(), item["full_rent_equivalent"])
                    sent += 1

            store.mark_search_run(saved["id"])

        store.finish_run(run_id, True, sent=sent)
        log.info("دور تمام شد: %d پیام", sent)
        return sent

    except Exception as exc:
        log.exception("چرخه خطا داد")
        store.finish_run(run_id, False, error=f"{type(exc).__name__}: {exc}"[:500])
        if store.consecutive_failures() == 3:
            await bot.send_message(chat_id(), f"⚠️ سه اجرای اخیر خطا داد:\n<code>{fmt.esc(str(exc)[:200])}</code>",
                                   parse_mode="HTML")
        return sent


async def maybe_cycle(app):
    """هر دقیقه: اگر فاصله گذشته و ساکت نیست، اجرا کن."""
    with Store() as store:
        conf = settings(store)
        muted = _parse_iso(conf["muted_until"])
        if muted and muted > datetime.now(timezone.utc):
            return
        last = store.last_ok_run()
        if last:
            finished = _parse_iso(last["finished_at"])
            if finished and datetime.now(timezone.utc) - finished < timedelta(minutes=conf["interval_minutes"]):
                return
        if cycle_lock.locked():
            return
        async with cycle_lock:
            await run_cycle(app.bot, store)


async def ticker(app):
    await asyncio.sleep(10)
    while True:
        try:
            await maybe_cycle(app)
        except Exception:
            log.exception("ticker")
        await asyncio.sleep(TICK_SECONDS)


# ---------- دستورها ----------

async def cmd_id(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """در هر چتی کار می‌کند — برای پیدا کردن شناسه گروه."""
    c = update.effective_chat
    await update.message.reply_text(
        f"شناسه این چت: <code>{c.id}</code>\nنوع: {c.type}\n\n"
        f"همین عدد را در .env بگذارید:\nTELEGRAM_CHAT_ID={c.id}", parse_mode="HTML")


async def cmd_help(update: Update, ctx):
    if not allowed(update):
        return
    await update.message.reply_text(
        "/run — اجرای فوری\n/status — وضعیت\n/bookmarks — بوکمارک‌ها (زنده)\n"
        "/trash — آخرین حذف‌شده‌ها\n/mute 2h — سکوت موقت، /mute off\n"
        "/searches — جستجوهای ذخیره‌شده\n/id — شناسه چت")


async def cmd_status(update: Update, ctx):
    if not allowed(update):
        return
    with Store() as store:
        await update.message.reply_text(
            fmt.status_text(store, settings(store), bool(chat_id())), parse_mode="HTML")


async def cmd_run(update: Update, ctx):
    if not allowed(update):
        return
    if cycle_lock.locked():
        await update.message.reply_text("یک اجرا در جریان است.")
        return
    await update.message.reply_text("⏳ در حال اجرا ...")
    async with cycle_lock:
        with Store() as store:
            sent = await run_cycle(ctx.bot, store, trigger="/run")
    if sent == 0:
        await update.message.reply_text("چیز تازه‌ای نبود.")


async def cmd_bookmarks(update: Update, ctx):
    if not allowed(update):
        return
    with Store() as store:
        rows = store.marked_items("bookmark")
        text = fmt.bookmarks_text(rows, store, settings(store)["interval_minutes"],
                                  listing.DEPOSIT_PER_RENT)
    await update.message.reply_text(text, parse_mode="HTML", disable_web_page_preview=True)


async def cmd_trash(update: Update, ctx):
    if not allowed(update):
        return
    with Store() as store:
        rows = store.marked_items("trash")[:8]
    await update.message.reply_text(fmt.trash_text(rows), parse_mode="HTML",
                                    reply_markup=fmt.restore_keyboard(rows) if rows else None)


async def cmd_mute(update: Update, ctx):
    if not allowed(update):
        return
    arg = (ctx.args or ["2h"])[0].lower()
    with Store() as store:
        if arg in ("off", "0"):
            store.set_setting("muted_until", None)
            await update.message.reply_text("🔔 صدا وصل شد.")
            return
        m = re.fullmatch(r"(\d+)([hmd])", arg)
        if not m:
            await update.message.reply_text("مثلاً /mute 2h یا /mute 30m یا /mute off")
            return
        n, unit = int(m.group(1)), m.group(2)
        delta = {"m": timedelta(minutes=n), "h": timedelta(hours=n), "d": timedelta(days=n)}[unit]
        until = datetime.now(timezone.utc) + delta
        store.set_setting("muted_until", _iso(until))
    await update.message.reply_text(f"🔇 ساکت تا {n}{unit} دیگر.")


async def cmd_searches(update: Update, ctx):
    if not allowed(update):
        return
    with Store() as store:
        await update.message.reply_text(fmt.searches_text(store.list_searches()),
                                        parse_mode="HTML")


# ---------- دکمه‌ها ----------

async def on_callback(update: Update, ctx):
    q = update.callback_query
    if not allowed(update):
        await q.answer()
        return
    kind, _, token = (q.data or "").partition(":")
    if not token:
        await q.answer()
        return

    with Store() as store:
        if kind == "t":
            store.mark(token, "trash")
            for mid in store.sent_media_ids(token, chat_id()):
                try:
                    await ctx.bot.delete_message(chat_id(), mid)
                except (BadRequest, Forbidden):
                    pass  # قدیمی‌تر از ۴۸ ساعت یا از قبل حذف شده
            try:
                await q.message.delete()
            except (BadRequest, Forbidden):
                # محدودیت ۴۸ ساعته تلگرام یا نبود دسترسی — پست را خالی کن
                try:
                    if q.message.photo:
                        await q.edit_message_caption("🗑 حذف شد", reply_markup=None)
                    else:
                        await q.edit_message_text("🗑 حذف شد", reply_markup=None)
                except BadRequest:
                    pass
            await q.answer("حذف شد — در پنل هم به سطل آشغال رفت")

        elif kind == "b":
            on = token not in store.marked_tokens("bookmark")
            if on:
                store.mark(token, "bookmark")
            else:
                store.unmark(token, "bookmark")
            try:
                await q.edit_message_reply_markup(
                    fmt.keyboard(token, on, f"https://divar.ir/v/{token}"))
            except BadRequest:
                pass
            await q.answer("★ بوکمارک شد" if on else "بوکمارک برداشته شد")

        elif kind == "r":
            store.unmark(token, "trash")
            await q.answer("بازگردانده شد — در جستجوی بعدی دوباره می‌آید")
            rows = store.marked_items("trash")[:8]
            try:
                await q.edit_message_text(fmt.trash_text(rows), parse_mode="HTML",
                                          reply_markup=fmt.restore_keyboard(rows) if rows else None)
            except BadRequest:
                pass
        else:
            await q.answer()


# ---------- راه‌اندازی ----------

async def post_init(app):
    me = await app.bot.get_me()
    log.info("بات @%s بالا آمد. گروه: %s", me.username, chat_id() or "تنظیم نشده")
    app.create_task(ticker(app))


def main():
    logging.basicConfig(level=logging.INFO, stream=sys.stderr,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)

    if not config.TELEGRAM_BOT_TOKEN:
        print("TELEGRAM_BOT_TOKEN در .env نیست.", file=sys.stderr)
        return 1

    app = Application.builder().token(config.TELEGRAM_BOT_TOKEN).post_init(post_init).build()
    app.add_handler(CommandHandler("id", cmd_id))
    app.add_handler(CommandHandler(["start", "help"], cmd_help))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("run", cmd_run))
    app.add_handler(CommandHandler("bookmarks", cmd_bookmarks))
    app.add_handler(CommandHandler("trash", cmd_trash))
    app.add_handler(CommandHandler("mute", cmd_mute))
    app.add_handler(CommandHandler("searches", cmd_searches))
    app.add_handler(CallbackQueryHandler(on_callback))

    app.run_polling(allowed_updates=["message", "callback_query"], drop_pending_updates=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
