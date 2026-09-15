"""دریافت آگهی از دیوار. تنها جایی که به دیوار وابسته است.

اگر روش دریافت اطلاعات از دیوار عوض شد، فقط همین فایل اصلاح می‌شود.
"""

import re
import threading
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor

import requests

SEARCH_URL = "https://api.divar.ir/v8/postlist/w/search"
DETAIL_URL = "https://api.divar.ir/v8/posts-v2/web/{token}"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Content-Type": "application/json",
    "Origin": "https://divar.ir",
    "Referer": "https://divar.ir/",
}

# قرارداد فیلترهای دیوار — جزئیات و وضعیت تست در docs/DIVAR_API.md
#
# هشدار: دیوار مقدار یا نوع اشتباه را بی‌صدا نادیده می‌گیرد و ۲۰۰ برمی‌گرداند.
# هر فیلتر جدید باید با diff مجموعه توکن‌ها تست شود، نه با status code.

NUMBER_RANGE_FIELDS = ("size", "credit", "rent", "building-age", "floor",
                       "floors_count", "unit_per_floor")
BOOLEAN_FIELDS = ("parking", "elevator", "warehouse", "balcony", "rebuilt",
                  "has-photo", "has-video")
STR_FIELDS = ("recent_ads", "toilet")
CHOICE_FIELDS = ("heating_system", "cooling_system", "floor_type",
                 "warm_water_provider", "building_direction")

# گزینه‌های مجاز — دیوار مقدار نامعتبر enum را با ۴۰۰ رد می‌کند
CHOICES = {
    "recent_ads": ("3h", "12h", "1d", "3d", "7d"),
    "toilet": ("squat", "seat", "squat_seat"),
    "heating_system": ("heater", "shoofaj", "fan_coil", "floor_heating",
                       "duct_split", "split"),
    "cooling_system": ("water_cooler", "air_conditioner", "duct_split", "split",
                       "fan_coil"),
    "floor_type": ("ceramic", "wood_parquet", "laminate_parquet", "stone",
                   "floor_covering", "carpet"),
    "warm_water_provider": ("water_heater", "powerhouse", "package"),
    "building_direction": ("north", "south", "east", "west"),
}

# «دارای عکس از ملک» — دیوار از آگهی‌دهنده می‌پرسد عکس‌ها مال همین ملک است یا نه،
# و این فیلتر فقط آنهایی را نگه می‌دارد که گفته‌اند بله. حدود ۲۷٪ آگهی‌ها «خیر»اند.
REAL_PHOTO_FIELD = "تصویر‌ها برای همین ملک است؟"

# دیوار تعداد اتاق را با کلمه فارسی می‌خواهد، نه عدد
ROOM_WORDS = ["بدون اتاق", "یک", "دو", "سه", "چهار", "بیشتر"]


def rooms_from(minimum):
    """حداقل تعداد اتاق → مقادیری که دیوار می‌پذیرد. ۴ یعنی «چهار» و «بیشتر»."""
    index = min(int(minimum), len(ROOM_WORDS) - 1)
    return ROOM_WORDS[index:]


def build_form_data(category="apartment-rent", *, ranges=None, districts=None, bbox=None,
                    rooms_min=None, booleans=None, owner_only=False,
                    choices=None):
    """پارامترهای ما → بدنه‌ای که دیوار می‌فهمد.

    ranges:    {"size": (80, 150), "credit": (None, 1.5e9), ...}
    districts: ["68", "72"] شناسه عددی محله
    bbox:      (min_lon, min_lat, max_lon, max_lat)
    booleans:  {"parking": True, ...}
    choices:   {"recent_ads": "1d", "heating_system": ["shoofaj"], ...}
               هر مقدار None یا خالی نادیده گرفته می‌شود — همه اختیاری‌اند.
    """
    data = {"category": {"str": {"value": category}}}

    for key, (lo, hi) in (ranges or {}).items():
        if key not in NUMBER_RANGE_FIELDS:
            raise ValueError(f"فیلتر بازه‌ای ناشناخته: {key}")
        rng = {}
        if lo is not None:
            rng["minimum"] = str(int(lo))
        if hi is not None:
            rng["maximum"] = str(int(hi))
        if rng:
            data[key] = {"number_range": rng}

    if rooms_min is not None:
        data["rooms"] = {"repeated_string": {"value": rooms_from(rooms_min)}}

    if districts:
        data["districts"] = {"repeated_string": {"value": [str(d) for d in districts]}}

    if bbox:
        data["bbox"] = {"repeated_float": {"value": [{"value": float(v)} for v in bbox]}}

    for key, value in (booleans or {}).items():
        if key not in BOOLEAN_FIELDS:
            raise ValueError(f"فیلتر بولی ناشناخته: {key}")
        if value:
            data[key] = {"boolean": {"value": True}}

    for key, value in (choices or {}).items():
        if not value:
            continue  # اختیاری — خالی یعنی اعمال نشود
        allowed = CHOICES.get(key)
        if allowed is None:
            raise ValueError(f"فیلتر گزینه‌ای ناشناخته: {key}")
        values = [value] if isinstance(value, str) else list(value)
        bad = [v for v in values if v not in allowed]
        if bad:
            raise ValueError(f"مقدار نامعتبر برای {key}: {bad} — مجاز: {allowed}")
        if key in STR_FIELDS:
            data[key] = {"str": {"value": values[0]}}
        else:
            data[key] = {"repeated_string": {"value": values}}

    if owner_only:
        data["business-type"] = {"repeated_string": {"value": ["personal"]}}

    return data


def _post(session, url, body, attempts=3):
    """درخواست با تلاش مجدد. دیوار گاهی اتصال را وسط کار می‌بندد."""
    last = None
    for attempt in range(attempts):
        try:
            resp = (session or requests).post(url, headers=HEADERS, json=body, timeout=30)
            resp.raise_for_status()
            return resp
        except (requests.ConnectionError, requests.Timeout) as exc:
            last = exc
            time.sleep(2 * (attempt + 1))
    raise last


def search(city_ids, form_data, pages=1, delay=0.5):
    """آگهی‌های خام لیست را برمی‌گرداند (بدون متراژ — متراژ فقط در جزئیات است).

    form_data از build_form_data() می‌آید.
    """
    session = requests.Session()
    out = []
    pagination = {"@type": "type.googleapis.com/post_list.PaginationData", "page": 1}

    for _ in range(pages):
        body = {
            "city_ids": list(city_ids),
            "search_data": {"form_data": {"data": form_data}},
            "pagination_data": pagination,
        }
        payload = _post(session, SEARCH_URL, body).json()

        for widget in payload.get("list_widgets", []):
            if widget.get("widget_type") != "POST_ROW":
                continue
            data = widget["data"]
            payload_action = data.get("action", {}).get("payload", {})
            web_info = payload_action.get("web_info", {})
            out.append(
                {
                    "token": payload_action.get("token"),
                    "title": data.get("title"),
                    "district": web_info.get("district_persian"),
                    "city": web_info.get("city_persian"),
                    "deposit_text": data.get("top_description_text"),
                    "rent_text": data.get("middle_description_text"),
                    "agency_text": data.get("bottom_description_text"),
                }
            )

        if not payload.get("pagination", {}).get("has_next_page"):
            break
        pagination = payload["pagination"]["data"]
        time.sleep(delay)

    return out


# --- جستجوی نقشه‌ای -------------------------------------------------------
#
# این endpoint تا ۲۰۰ آگهی را با متراژ، اتاق، سن بنا، امکانات و مختصات در یک
# درخواست می‌دهد — بدون نیاز به صفحه جزئیات. ولی قیمتش گرد شده است.

MAP_URL = "https://api.divar.ir/v8/mapview/viewport"
MAP_PAGE_LIMIT = 200  # بیشتر از این برنمی‌گرداند؛ محدوده باید تقسیم شود

_FA_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹", "0123456789")

# کارت نقشه فقط این دو آیکون را دارد. انباری و بالکن در کارت نقشه وجود ندارند —
# برای آنها یا باید فیلتر سمت دیوار را روشن کرد یا صفحه جزئیات را گرفت.
_AMENITY_ICONS = {"parking": "parking.png", "elevator": "elevator.png"}


def _parse_chips(chips):
    """چیپ‌های کارت نقشه → متراژ، اتاق، سن بنا، امکانات.

    چیپ‌های متنی: «۲۰۰ متر»، «۳ اتاق»، «۲۰ سال»، «نوساز»
    چیپ‌های امکانات فقط آیکون دارند؛ از نام فایل تشخیص داده می‌شوند.
    """
    out = {"size": None, "rooms": None, "age_years": None,
           "parking": None, "elevator": None, "warehouse": None}

    for chip in chips or []:
        title = (chip.get("title") or "").strip()
        if title:
            number = re.sub(r"\D", "", title.translate(_FA_DIGITS))
            if "متر" in title and number:
                out["size"] = float(number)
            elif "اتاق" in title:
                out["rooms"] = float(number) if number else 0.0  # «بدون اتاق»
            elif "سال" in title and number:
                out["age_years"] = float(number)
            elif "نوساز" in title:
                out["age_years"] = 0.0
            continue

        icon = chip.get("icon_url_light") or chip.get("icon_url_dark") or ""
        filename = icon.rsplit("/", 1)[-1]
        for key, needle in _AMENITY_ICONS.items():
            if filename == needle:
                out[key] = True

    # نبودِ آیکون یعنی نبودِ امکانات (کارت نقشه آیکون «ندارد» نمی‌گذارد)
    for key in _AMENITY_ICONS:
        if out[key] is None:
            out[key] = False

    return out


def search_map(city_ids, form_data, bbox, zoom=14):
    """یک درخواست نقشه‌ای. بازگشت: (count کل محدوده، لیست آگهی‌ها).

    bbox: (min_lon, min_lat, max_lon, max_lat)
    اگر count > MAP_PAGE_LIMIT باشد فقط بخشی از آگهی‌ها برمی‌گردد — صداکننده
    باید محدوده را تقسیم کند (search_map_area این کار را می‌کند).
    """
    min_lon, min_lat, max_lon, max_lat = bbox
    body = {
        "city_ids": list(city_ids),
        "search_data": {"form_data": {"data": form_data}},
        "camera_info": {
            "bbox": {"minLongitude": min_lon, "minLatitude": min_lat,
                     "maxLongitude": max_lon, "maxLatitude": max_lat},
            "zoom": zoom,
        },
    }
    payload = _post(None, MAP_URL, body).json()

    items = []
    for post in payload.get("posts", []):
        card = post.get("map_post_card", {})
        pin = post.get("map_pin_feature", {})
        prices = {(f.get("title") or "").strip(": ") : f.get("value")
                  for f in card.get("price_fields", [])}
        item = {
            "token": card.get("token"),
            "title": card.get("title"),
            "lat": pin.get("lat"),
            "lon": pin.get("lon"),
            "approximate_location": pin.get("approximate_location"),
            "image_url": (card.get("images") or [None])[0],
            "image_count": len(card.get("images") or []),
            # قیمت گرد شده («۳ میلیارد») — برای مقدار دقیق با لیست join می‌شود
            "deposit_text": prices.get("ودیعه"),
            "rent_text": prices.get("اجاره"),
            "price_is_rounded": True,
        }
        item.update(_parse_chips(card.get("chips")))
        items.append(item)

    return payload.get("count", 0), items


# سقف درخواست نقشه. ۴۰۰ حدود ۹ دقیقه طول می‌کشد که برای پنل غیرقابل
# استفاده است؛ ۱۵۰ حدود دو دقیقه. کل تهران بدون فیلتر به این سقف می‌خورد.
MAX_MAP_REQUESTS = 150


def search_map_area(city_ids, form_data, bbox, zoom=14, max_depth=7, delay=0.3,
                    on_progress=None, max_requests=MAX_MAP_REQUESTS):
    """محدوده را می‌گیرد و اگر بیش از ۲۰۰ آگهی داشت به چهار ربع تقسیم می‌کند.

    بازگشت: (count کل، dict از token به آگهی، complete).
    complete=False یعنی به سقف درخواست خوردیم و پوشش ناقص است — صداکننده
    باید این را به کاربر بگوید، نه اینکه وانمود کند همه را آورده.
    """
    found = {}
    total = None
    stack = [(tuple(bbox), 0)]
    visited = 0
    complete = True

    while stack:
        if visited >= max_requests:
            complete = False
            break
        box, depth = stack.pop()
        count, items = search_map(city_ids, form_data, box, zoom=zoom)
        visited += 1
        if total is None:
            total = count
        for item in items:
            if item["token"]:
                found.setdefault(item["token"], item)

        if on_progress:
            on_progress(visited, len(stack), len(found), total)

        if count > MAP_PAGE_LIMIT and depth < max_depth:
            min_lon, min_lat, max_lon, max_lat = box
            mid_lon = (min_lon + max_lon) / 2
            mid_lat = (min_lat + max_lat) / 2
            stack.extend([
                ((min_lon, min_lat, mid_lon, mid_lat), depth + 1),
                ((mid_lon, min_lat, max_lon, mid_lat), depth + 1),
                ((min_lon, mid_lat, mid_lon, max_lat), depth + 1),
                ((mid_lon, mid_lat, max_lon, max_lat), depth + 1),
            ])
        time.sleep(delay)

    return total or 0, found, complete


# دیوار بعد از حدود ۳۰ درخواست جزئیات، 429 می‌دهد
RETRY_WAITS = (10, 30, 60)

# اندازه‌گیری‌شده: ۴۲۹ در درخواست ۳۱ام، و پنجره بعد از ~۳۰ ثانیه باز می‌شود.
# کمی زیر حد واقعی می‌مانیم تا اصلاً به ۴۲۹ نرسیم.
DETAIL_BUDGET = 25
DETAIL_WINDOW = 30.0


class RateLimiter:
    """سطل توکن ساده و امن برای چند نخ.

    هدف این است که اصلاً به ۴۲۹ نرسیم، نه اینکه بعدش صبر کنیم.
    """

    def __init__(self, budget=DETAIL_BUDGET, window=DETAIL_WINDOW):
        self.budget = budget
        self.window = window
        self.hits = deque()
        self.lock = threading.Lock()

    def acquire(self):
        while True:
            with self.lock:
                now_ = time.monotonic()
                while self.hits and now_ - self.hits[0] > self.window:
                    self.hits.popleft()
                if len(self.hits) < self.budget:
                    self.hits.append(now_)
                    return
                sleep_for = self.window - (now_ - self.hits[0]) + 0.05
            time.sleep(max(sleep_for, 0.05))


def fetch_detail(token, session=None):
    """اطلاعات ساختاریافته یک آگهی: متراژ، اتاق، ساخت، طبقه، امکانات، توضیحات."""
    session = session or requests
    url = DETAIL_URL.format(token=token)

    for wait in RETRY_WAITS + (None,):
        resp = session.get(url, headers=HEADERS, timeout=30)
        if resp.status_code != 429 or wait is None:
            break
        time.sleep(wait)

    resp.raise_for_status()
    payload = resp.json()

    fields = {}
    features = {}
    description = None

    for section in payload.get("sections", []):
        for widget in section.get("widgets", []):
            kind = widget.get("widget_type")
            data = widget.get("data", {})

            if kind == "GROUP_INFO_ROW":
                for item in data.get("items", []):
                    fields[item.get("title")] = item.get("value")
            elif kind == "UNEXPANDABLE_ROW":
                fields[data.get("title")] = data.get("value")
            elif kind == "GROUP_FEATURE_ROW":
                for item in data.get("items", []):
                    title = (item.get("title") or "").strip()
                    # دیوار نبودِ امکانات را با پسوند «ندارد» نشان می‌دهد
                    if title.endswith("ندارد"):
                        features[title[: -len("ندارد")].strip()] = False
                    else:
                        features[title] = True
            elif kind == "DESCRIPTION_ROW" and description is None:
                description = data.get("text")

    return {"token": token, "fields": fields, "features": features, "description": description}


def fetch_details(tokens, delay=0.4, store=None):
    """جزئیات چند آگهی، ترتیبی. اگر store داده شود ابتدا از کش خوانده می‌شود."""
    session = requests.Session()
    for token in tokens:
        if store is not None:
            cached = store.get_detail(token)
            if cached is not None:
                yield cached
                continue
        try:
            detail = fetch_detail(token, session)
            if store is not None:
                store.put_detail(token, detail)
            yield detail
        except Exception as exc:  # آگهی حذف‌شده یا خطای شبکه — دمو نباید بایستد
            yield {"token": token, "error": f"{type(exc).__name__}: {exc}"}
        time.sleep(delay)


def fetch_details_parallel(tokens, store=None, workers=3, limiter=None):
    """همان کار، موازی و پشت یک محدودکننده نرخ مشترک.

    ترتیب خروجی همان ترتیب ورودی است. نوشتن در store داخل قفل خودش انجام
    می‌شود چون sqlite3 از چند نخ هم‌زمان خوش‌اش نمی‌آید.
    """
    tokens = list(tokens)
    limiter = limiter or RateLimiter()
    write_lock = threading.Lock()

    def one(token):
        if store is not None:
            with write_lock:
                cached = store.get_detail(token)
            if cached is not None:
                return cached
        limiter.acquire()
        try:
            detail = fetch_detail(token)
            if store is not None:
                with write_lock:
                    store.put_detail(token, detail)
            return detail
        except Exception as exc:
            return {"token": token, "error": f"{type(exc).__name__}: {exc}"}

    with ThreadPoolExecutor(max_workers=workers) as pool:
        return list(pool.map(one, tokens))
