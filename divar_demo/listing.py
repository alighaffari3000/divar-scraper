"""نرمال‌سازی داده دیوار + محاسبه رهن کامل معادل.

مقادیر اصلی هیچ‌وقت overwrite نمی‌شوند: deposit و monthly_rent دست‌نخورده
می‌مانند و full_rent_equivalent یک فیلد جداست.
"""

import datetime
import re
import statistics

from . import geo


def _current_jalali_year(today=None):
    """سال شمسی جاری. تقریب کافی: سال نو حدود ۲۱ مارس است."""
    today = today or datetime.date.today()
    return today.year - (621 if (today.month, today.day) >= (3, 21) else 622)

# هر ۱۰۰ میلیون تومان ودیعه = ۳ میلیون تومان اجاره
DEPOSIT_PER_RENT = 100 / 3

_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")


def to_number(text):
    """«‏۱,۰۰۰,۰۰۰,۰۰۰ تومان» → 1000000000 ؛ توافقی/خالی → None"""
    if text is None:
        return None
    cleaned = str(text).translate(_DIGITS)
    cleaned = re.sub(r"[^\d.]", "", cleaned)
    if not cleaned:
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def full_rent_equivalent(deposit, monthly_rent, rate=DEPOSIT_PER_RENT):
    if deposit is None or monthly_rent is None:
        return None
    return deposit + monthly_rent * rate


def normalize(row, detail, rate=DEPOSIT_PER_RENT):
    """یک آگهی لیست + جزئیاتش → یک رکورد تخت و قابل مقایسه."""
    fields = detail.get("fields", {})
    features = detail.get("features", {})

    # قیمت را از ردیف لیست می‌خوانیم: صفحه جزئیات این دو ردیف را همیشه ندارد
    deposit = to_number(row.get("deposit_text"))
    if deposit is None:
        deposit = to_number(fields.get("ودیعه"))

    rent_text = row.get("rent_text") or ""
    if "رهن کامل" in rent_text:
        monthly_rent = 0.0  # رهن کامل یعنی اجاره صفر، نه نامعلوم
    else:
        monthly_rent = to_number(rent_text)
        if monthly_rent is None:
            monthly_rent = to_number(fields.get("اجارهٔ ماهانه"))

    size = to_number(fields.get("متراژ"))
    fre = full_rent_equivalent(deposit, monthly_rent, rate)

    return {
        "token": row.get("token"),
        "url": f"https://divar.ir/v/{row.get('token')}",
        "title": row.get("title"),
        "district": row.get("district"),
        "agency_text": row.get("agency_text"),
        "size": size,
        "rooms": to_number(fields.get("اتاق")),
        "year_built": to_number(fields.get("ساخت")),
        "floor_text": fields.get("طبقه"),
        "convertible": fields.get("ودیعه و اجاره"),
        "real_photos": real_photos_flag(fields),
        "deposit": deposit,
        "monthly_rent": monthly_rent,
        "full_rent_equivalent": fre,
        "fre_per_meter": (fre / size) if (fre is not None and size) else None,
        "elevator": features.get("آسانسور"),
        "parking": features.get("پارکینگ"),
        "storage": features.get("انباری"),
        "balcony": features.get("بالکن"),
        "description": detail.get("description"),
    }


# دیوار از آگهی‌دهنده می‌پرسد عکس‌ها مال همین ملک است یا نه
REAL_PHOTO_FIELD = "تصویر‌ها برای همین ملک است؟"


def real_photos_flag(fields):
    """True یعنی عکس‌ها مال همین ملک است، False یعنی تزئینی، None یعنی نامعلوم."""
    answer = (fields or {}).get(REAL_PHOTO_FIELD)
    if answer is None:
        return None
    return answer.strip() == "بله"


def from_map_card(card, list_row=None, rate=DEPOSIT_PER_RENT):
    """کارت نقشه (+ ردیف لیست برای قیمت دقیق) → همان رکورد استاندارد.

    کارت نقشه متراژ و اتاق و سن و مختصات دارد ولی قیمتش گرد شده است
    («۳ میلیارد»). اگر ردیف لیست موجود باشد قیمت دقیق از آن می‌آید.
    """
    if list_row:
        deposit = to_number(list_row.get("deposit_text"))
        rent_text = list_row.get("rent_text") or ""
        monthly_rent = 0.0 if "رهن کامل" in rent_text else to_number(rent_text)
        rounded = False
        district = list_row.get("district")
        agency_text = list_row.get("agency_text")
        bumped = list_row.get("bumped")
    else:
        deposit = _from_rounded(card.get("deposit_text"))
        monthly_rent = _from_rounded(card.get("rent_text"))
        rounded = True
        district = None
        agency_text = None
        bumped = None

    size = card.get("size")
    fre = full_rent_equivalent(deposit, monthly_rent, rate)
    age = card.get("age_years")

    return {
        "token": card.get("token"),
        "url": f"https://divar.ir/v/{card.get('token')}",
        "title": card.get("title"),
        "district": district,
        "agency_text": agency_text,
        "bumped": bumped,
        "lat": card.get("lat"),
        "lon": card.get("lon"),
        "approximate_location": card.get("approximate_location"),
        "image_url": card.get("image_url"),
        "image_count": card.get("image_count"),
        # فقط از صفحه جزئیات می‌آید؛ در کارت نقشه نیست
        "real_photos": None,
        "size": size,
        "rooms": card.get("rooms"),
        "year_built": (_current_jalali_year() - int(age)) if age is not None else None,
        "age_years": age,
        "floor_text": None,       # در کارت نقشه نیست
        "convertible": None,      # در کارت نقشه نیست
        "deposit": deposit,
        "monthly_rent": monthly_rent,
        "price_is_rounded": rounded,
        "full_rent_equivalent": fre,
        "fre_per_meter": (fre / size) if (fre is not None and size) else None,
        "elevator": card.get("elevator"),
        "parking": card.get("parking"),
        "storage": card.get("warehouse"),
        "balcony": None,          # در کارت نقشه نیست
        "description": None,
    }


_SCALES = (("میلیارد", 1_000_000_000), ("میلیون", 1_000_000), ("هزار", 1_000))


def _from_rounded(text):
    """«۳ میلیارد» → 3000000000 ؛ «۸۸ میلیون» → 88000000 ؛ «رهن کامل» → 0"""
    if text is None:
        return None
    if "رهن کامل" in text:
        return 0.0
    number = to_number(text)
    if number is None:
        return None
    for word, scale in _SCALES:
        if word in text:
            return number * scale
    return number


def passes_hard_filters(item, size=None, rooms=None, credit=None, rent=None,
                       need_parking=False, need_elevator=False, need_storage=False,
                       need_real_photos=False, max_fre=None, max_fre_per_meter=None,
                       min_images=None, convertible_only=False,
                       exclude_districts=None):
    """فیلترهای قطعی. آگهی‌ای که رد شود اصلاً وارد مرحله بعد نمی‌شود.

    همه پارامترها اختیاری‌اند؛ None یا False یعنی اعمال نشود.
    """
    if item["full_rent_equivalent"] is None or not item["size"]:
        return False  # بدون قیمت یا متراژ قابل مقایسه نیست

    if size:
        lo, hi = size
        if lo is not None and item["size"] < lo:
            return False
        if hi is not None and item["size"] > hi:
            return False
    if rooms:
        lo, _ = rooms
        if lo is not None and (item["rooms"] is None or item["rooms"] < lo):
            return False
    if credit:
        _, hi = credit
        if hi is not None and item["deposit"] > hi:
            return False
    if rent:
        _, hi = rent
        if hi is not None and item["monthly_rent"] > hi:
            return False

    if need_parking and item["parking"] is not True:
        return False
    if need_elevator and item["elevator"] is not True:
        return False
    # کارت نقشه آیکون انباری ندارد، پس storage همیشه None است. فیلتر سمت
    # دیوار کار را کرده؛ این فقط جلوی آگهی‌ای را می‌گیرد که جزئیاتش صریحاً
    # گفته انباری ندارد. با شرط «is not True» هر بار صفر نتیجه می‌ماند.
    if need_storage and item.get("storage") is False:
        return False
    # فیلتر سمت دیوار کار اصلی را کرده؛ این فقط وقتی جزئیات موجود باشد اثر دارد
    if need_real_photos and item.get("real_photos") is False:
        return False

    # --- فیلترهایی که دیوار ندارد ---
    if max_fre is not None and item["full_rent_equivalent"] > max_fre:
        return False
    if max_fre_per_meter is not None and item["fre_per_meter"] > max_fre_per_meter:
        return False
    if min_images is not None and (item.get("image_count") or 0) < min_images:
        return False
    # مثل real_photos فقط وقتی جزئیات موجود باشد اثر دارد
    if convertible_only and item.get("convertible") == "غیر قابل تبدیل":
        return False

    # محله‌های کنارگذاشته — حتی اگر آگهی داخل محدوده نقشه باشد.
    # نام محله همانی است که خود دیوار روی آگهی گذاشته؛ آگهی بدون محله نگه داشته
    # می‌شود چون نمی‌شود اثبات کرد در محله کنارگذاشته است.
    if exclude_districts:
        name = geo.normalize_fa(item.get("district"))
        if name and name in exclude_districts:
            return False

    return True


# زیر این نسبت از median، آگهی احتمالاً اجاره واحد نیست (هم‌خانه، اتاق، اشتباه در داده)
SUSPICIOUS_RATIO = 0.5


def add_market_comparison(items):
    """مقایسه با median قیمت متری همین مجموعه.

    دمو: median ساده، نه رگرسیون. آگهی‌های بیش از حد ارزان علامت suspicious
    می‌گیرند و از محاسبه median بیرون می‌مانند تا median را پایین نکشند.
    """
    per_meter = [i["fre_per_meter"] for i in items if i["fre_per_meter"]]
    if len(per_meter) < 5:
        for item in items:
            item["vs_market_pct"] = None
            item["suspicious"] = False
        return None

    rough = statistics.median(per_meter)
    clean = [p for p in per_meter if p >= rough * SUSPICIOUS_RATIO]
    median = statistics.median(clean) if clean else rough

    for item in items:
        pm = item["fre_per_meter"]
        item["suspicious"] = bool(pm) and pm < median * SUSPICIOUS_RATIO
        item["vs_market_pct"] = ((pm - median) / median * 100) if pm else None
    return median


# --- امتیازدهی -------------------------------------------------------------
#
# امتیاز باید قابل توضیح باشد (بخش ۱۲ سند): مجموع سهم‌های مشخص از یک پایه.
# وزن‌ها اینجا ثابت نیستند — از بیرون قابل تغییرند.

SCORE_BASE = 50.0
DEFAULT_WEIGHTS = {
    "deal": 30.0,   # چقدر زیر median بازار
    "age": 15.0,    # نوسازی
    "metro": 10.0,  # نزدیکی به مترو
}

# سن بنا: صفر سال = بهترین، این عدد و بالاتر = بدترین
AGE_WORST_YEARS = 30.0
# فاصله مترو: این عدد و بیشتر = بدون امتیاز
METRO_WORST_METERS = 2000.0


def _clamp(value, low=-1.0, high=1.0):
    return max(low, min(high, value))


def score_listing(item, weights=None):
    """امتیاز ۰ تا ۱۰۰ به‌همراه تفکیک سهم هر معیار.

    فقط معیارهایی که داده‌شان موجود است سهم می‌گیرند؛ بقیه سهم صفر دارند
    (نه منفی — نباید آگهی را برای نداشتن داده جریمه کنیم).
    """
    w = {**DEFAULT_WEIGHTS, **(weights or {})}

    # ضریب خام هر معیار در بازه [-1, 1]؛ وزن جداگانه ضرب می‌شود.
    # پنل همین ضرایب را می‌گیرد و با وزن‌های اسلایدر، بدون رفتن به سرور،
    # امتیاز را دوباره حساب می‌کند.
    factors = {}

    vs = item.get("vs_market_pct")
    if vs is not None:
        # ۳۰٪ زیر بازار = ضریب کامل مثبت، ۳۰٪ بالا = ضریب کامل منفی
        factors["deal"] = _clamp(-vs / 30.0)

    age = item.get("age_years")
    if age is not None:
        factors["age"] = _clamp(1 - 2 * (age / AGE_WORST_YEARS))

    metro_m = item.get("metro_distance_m")
    if metro_m is not None:
        factors["metro"] = _clamp(1 - metro_m / METRO_WORST_METERS, 0, 1)

    parts = {k: f * w[k] for k, f in factors.items()}
    total = SCORE_BASE + sum(parts.values())
    item["score"] = round(max(0.0, min(100.0, total)), 1)
    item["score_parts"] = {k: round(v, 1) for k, v in parts.items()}
    item["score_factors"] = {k: round(v, 3) for k, v in factors.items()}
    return item["score"]


# --- فیلتر متنی ------------------------------------------------------------

# آگهی هم‌خانه/هم‌اتاقی اجاره واحد نیست و کل median را خراب می‌کند
ROOMMATE_PATTERNS = ("همخانه", "هم خانه", "هم‌خانه", "همخونه", "هم خونه",
                     "هم‌خونه", "هم اتاقی", "هم‌اتاقی", "هماتاقی", "روم میت")


def looks_like_roommate(item):
    text = f"{item.get('title') or ''} {item.get('description') or ''}"
    normalized = text.replace("\u200c", " ")
    return any(p.replace("\u200c", " ") in normalized for p in ROOMMATE_PATTERNS)
