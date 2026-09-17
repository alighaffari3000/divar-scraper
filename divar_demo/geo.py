"""کارهای جغرافیایی: چندضلعی، محدوده، محله‌های داخل یک ناحیه.

هیچ وابستگی خارجی ندارد — دیوار فقط مستطیل می‌فهمد، بقیه را ما فیلتر می‌کنیم.
"""

import json
import os

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")

# پین‌های دیوار وقتی approximate_location باشند تا چند صد متر جابه‌جا هستند
APPROX_TOLERANCE_DEG = 0.002  # ≈ ۲۰۰ متر


def bbox_of(polygon):
    """چندضلعی [(lon, lat), ...] → (min_lon, min_lat, max_lon, max_lat)"""
    lons = [p[0] for p in polygon]
    lats = [p[1] for p in polygon]
    return (min(lons), min(lats), max(lons), max(lats))


def point_in_polygon(lon, lat, polygon):
    """آزمون ray casting. polygon لیستی از (lon, lat) است."""
    inside = False
    count = len(polygon)
    j = count - 1
    for i in range(count):
        xi, yi = polygon[i]
        xj, yj = polygon[j]
        if (yi > lat) != (yj > lat):
            x_cross = (xj - xi) * (lat - yi) / (yj - yi) + xi
            if lon < x_cross:
                inside = not inside
        j = i
    return inside


def point_near_polygon(lon, lat, polygon, tolerance=APPROX_TOLERANCE_DEG):
    """داخل چندضلعی، یا داخلِ نسخه‌ی کمی بزرگ‌شده‌ی آن.

    برای پین‌های تقریبی لازم است: دیوار مختصات را عمداً جابه‌جا می‌کند، پس
    نباید ملکی را فقط به خاطر چند ده متر خطا بیرون بیندازیم.
    """
    if point_in_polygon(lon, lat, polygon):
        return True
    if not tolerance:
        return False
    # چهار جهت را با تلورانس امتحان کن — تقریب ارزان و کافی برای این کار
    for dx, dy in ((tolerance, 0), (-tolerance, 0), (0, tolerance), (0, -tolerance)):
        if point_in_polygon(lon + dx, lat + dy, polygon):
            return True
    return False


def filter_to_polygon(items, polygon, tolerance=APPROX_TOLERANCE_DEG):
    """آگهی‌هایی که مختصاتشان داخل چندضلعی است. بدون مختصات = نگه‌داشتن."""
    kept = []
    for item in items:
        lon, lat = item.get("lon"), item.get("lat")
        if lon is None or lat is None:
            kept.append(item)
            continue
        tol = tolerance if item.get("approximate_location") else 0
        if point_near_polygon(lon, lat, polygon, tol):
            kept.append(item)
    return kept


# --- کاتالوگ محله‌ها -------------------------------------------------------

_CACHE = {}


def load_districts(city="tehran"):
    """لیست محله‌ها از فایل ذخیره‌شده. با refresh_districts.py به‌روز می‌شود."""
    if city in _CACHE:
        return _CACHE[city]
    path = os.path.join(DATA_DIR, f"districts_{city}.json")
    with open(path, encoding="utf-8") as fh:
        raw = json.load(fh)["districts"]
    out = []
    for d in raw:
        loc = d.get("default_location") or {}
        out.append({
            "id": d.get("id"),
            "name": d.get("name"),
            "slug": d.get("slug"),
            "second_slug": d.get("second_slug"),
            "lat": loc.get("latitude"),
            "lon": loc.get("longitude"),
            "bbox": d.get("bbox"),
            "neighbors": d.get("neighbors") or [],
        })
    _CACHE[city] = out
    return out


def city_bbox(city="tehran"):
    """محدوده کل شهر، از اجتماع bbox محله‌ها. برای جستجوی بدون محله."""
    boxes = [d["bbox"] for d in load_districts(city) if d.get("bbox")]
    if not boxes:
        raise ValueError(f"هیچ محله‌ای با bbox برای {city} نیست")
    return (min(b[0] for b in boxes), min(b[1] for b in boxes),
            max(b[2] for b in boxes), max(b[3] for b in boxes))


def districts_bbox(district_ids, city="tehran", pad=0.004):
    """اجتماع bbox چند محله، با کمی حاشیه تا لبه‌ها جا نمانند.

    این فقط محدوده دوربین نقشه است؛ فیلتر دقیق محله همچنان سمت دیوار اعمال می‌شود.
    """
    wanted = {str(d) for d in district_ids}
    boxes = [d["bbox"] for d in load_districts(city)
             if str(d["id"]) in wanted and d.get("bbox")]
    if not boxes:
        return None
    return (min(b[0] for b in boxes) - pad, min(b[1] for b in boxes) - pad,
            max(b[2] for b in boxes) + pad, max(b[3] for b in boxes) + pad)


def districts_in_polygon(polygon, city="tehran"):
    """محله‌هایی که مرکزشان داخل محدوده است — برای نمایش، نه برای فیلتر."""
    return [d for d in load_districts(city)
            if d["lon"] is not None and point_in_polygon(d["lon"], d["lat"], polygon)]


def normalize_fa(text):
    """ی و ک عربی، نیم‌فاصله، فاصله‌های اضافه."""
    if not text:
        return ""
    table = str.maketrans({"ي": "ی", "ك": "ک", "‌": " ", "ۀ": "ه", "أ": "ا", "إ": "ا"})
    return " ".join(text.translate(table).split())


def resolve_district(query, city="tehran", limit=5):
    """نام (شاید ناقص یا با ی عربی) → کاندیداهای محله.

    هیچ‌وقت خودکار یکی را انتخاب نمی‌کند مگر تطبیق دقیق و یکتا باشد.
    """
    import difflib

    needle = normalize_fa(query)
    if not needle:
        return []
    districts = load_districts(city)

    exact = [d for d in districts
             if normalize_fa(d["name"]) == needle
             or d["slug"] == query or d["second_slug"] == query]
    if exact:
        return exact[:limit]

    prefix = [d for d in districts if normalize_fa(d["name"]).startswith(needle)]
    contains = [d for d in districts
                if needle in normalize_fa(d["name"]) and d not in prefix]

    ranked = prefix + contains
    if len(ranked) < limit:
        names = {normalize_fa(d["name"]): d for d in districts}
        for match in difflib.get_close_matches(needle, names, n=limit, cutoff=0.6):
            if names[match] not in ranked:
                ranked.append(names[match])

    return ranked[:limit]


# --- ایستگاه‌های مترو ------------------------------------------------------

_METRO = {}


def load_metro(city="tehran"):
    """ایستگاه‌های مترو از فایل ذخیره‌شده (OpenStreetMap)."""
    if city in _METRO:
        return _METRO[city]
    path = os.path.join(DATA_DIR, f"metro_{city}.json")
    if not os.path.exists(path):
        _METRO[city] = []
        return []
    with open(path, encoding="utf-8") as fh:
        _METRO[city] = json.load(fh)["stations"]
    return _METRO[city]


def _haversine_m(lat1, lon1, lat2, lon2):
    import math

    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def nearest_metro(lat, lon, city="tehran"):
    """نزدیک‌ترین ایستگاه → (نام، فاصله متر). فاصله مستقیم است، نه پیاده‌روی.

    ضمناً پین دیوار تقریبی است، پس عدد را گرد شده نشان دهید.
    """
    stations = load_metro(city)
    if not stations or lat is None or lon is None:
        return None, None
    best, best_d = None, None
    for st in stations:
        d = _haversine_m(lat, lon, st["lat"], st["lon"])
        if best_d is None or d < best_d:
            best, best_d = st, d
    return best["name"], round(best_d)
