"""تنظیمات از فایل .env — تنها جایی که مقادیر محرمانه خوانده می‌شود."""

import os

from dotenv import load_dotenv

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

load_dotenv(os.path.join(ROOT, ".env"))


def _int(name, default):
    raw = os.environ.get(name, "").strip()
    try:
        return int(raw) if raw else default
    except ValueError:
        return default


def _float(name, default):
    raw = os.environ.get(name, "").strip()
    try:
        return float(raw) if raw else default
    except ValueError:
        return default


TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "").strip()

# هر چند ساعت جستجوهای ذخیره‌شده دوباره اجرا شوند. صفر = خاموش.
NOTIFY_INTERVAL_HOURS = _float("NOTIFY_INTERVAL_HOURS", 0)

# فقط آگهی‌هایی که رهن معادلشان دست‌کم این‌قدر درصد کم شده پیام شوند
NOTIFY_PRICE_DROP_PCT = _float("NOTIFY_PRICE_DROP_PCT", 5)

# حداکثر چند آگهی در هر بار اطلاع‌رسانی
NOTIFY_MAX_ITEMS = _int("NOTIFY_MAX_ITEMS", 10)


def telegram_ready():
    return bool(TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID)


def missing():
    """نام متغیرهایی که لازم‌اند ولی ست نشده‌اند."""
    out = []
    if not TELEGRAM_BOT_TOKEN:
        out.append("TELEGRAM_BOT_TOKEN")
    if not TELEGRAM_CHAT_ID:
        out.append("TELEGRAM_CHAT_ID")
    return out
