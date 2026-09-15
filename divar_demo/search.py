"""موتور جستجو — یک تابع که CLI، پنل وب و اطلاع‌رسانی صدایش می‌زنند.

جریان:
    فیلترها → جستجوی نقشه‌ای (متراژ/اتاق/سن/امکانات/مختصات)
            → join با لیست برای قیمت دقیق، به ازای هر خانه نقشه
            → فیلتر چندضلعی
            → رهن معادل و فیلتر قطعی
            → مقایسه با median و امتیاز
"""

from . import collector, geo, listing
from .store import Store

CITIES = {"tehran": "1", "mashhad": "2", "isfahan": "3",
          "karaj": "4", "shiraz": "5", "tabriz": "6"}


def _ranges(size=None, credit_max=None, rent_max=None, age_max=None,
            floor=None, floors_count_max=None, units_per_floor_max=None):
    """فقط مقادیری که کاربر داده وارد می‌شوند — بقیه اصلاً فرستاده نمی‌شوند."""
    out = {}
    if size:
        out["size"] = size
    if credit_max:
        out["credit"] = (None, credit_max)
    if rent_max:
        out["rent"] = (None, rent_max)
    if age_max is not None:
        out["building-age"] = (None, age_max)
    if floor:
        out["floor"] = floor
    if floors_count_max:
        out["floors_count"] = (None, floors_count_max)
    if units_per_floor_max:
        out["unit_per_floor"] = (None, units_per_floor_max)
    return out


def params_from_request(data):
    """شکل درخواست پنل (size_min/size_max/…) → آرگومان‌های run_search.

    تنها جایی که این تبدیل انجام می‌شود. پنل و اطلاع‌رسانی هر دو از همین استفاده
    می‌کنند تا پارامترهای ذخیره‌شده همیشه قابل اجرا بمانند. کلیدهای ناشناخته
    (مثل refresh) نادیده گرفته می‌شوند.
    """
    d = dict(data or {})
    size_min, size_max = d.pop("size_min", None), d.pop("size_max", None)
    floor_min, floor_max = d.pop("floor_min", None), d.pop("floor_max", None)
    d.pop("refresh", None)

    out = {
        "city": d.pop("city", None) or "tehran",
        "polygon": [tuple(p) for p in d.pop("polygon", None) or []] or None,
        "district_ids": [str(x) for x in d.pop("district_ids", None) or []] or None,
        "size": (size_min, size_max) if (size_min or size_max) else None,
        "floor": (floor_min, floor_max) if (floor_min or floor_max) else None,
    }
    for key in ("heating_system", "cooling_system"):
        val = d.pop(key, None)
        out[key] = [val] if isinstance(val, str) and val else (val or None)

    # اگر شکل قدیمی (size به‌صورت جفت) ذخیره شده بود، همان را نگه دار
    if d.get("size") and out["size"] is None:
        out["size"] = tuple(d["size"])
    d.pop("size", None)

    allowed = set(run_search.__kwdefaults__ or {})
    out.update({k: v for k, v in d.items() if k in allowed})
    return out


def run_search(*, city="tehran", polygon=None, bbox=None, district_ids=None,
               size=None, rooms_min=None, credit_max=None, rent_max=None,
               parking=False, elevator=False, storage=False, owner_only=False,
               real_photos=False, has_video=False,
               balcony=False, rebuilt=False,
               age_max=None, floor=None, floors_count_max=None,
               units_per_floor_max=None, recent_ads=None, toilet=None,
               heating_system=None, cooling_system=None,
               max_fre=None, max_fre_per_meter=None, min_images=None,
               convertible_only=False, below_median_only=False,
               hide_roommate=True, hide_trashed=True, weights=None,
               rate=listing.DEPOSIT_PER_RENT, on_progress=None, store=None):
    """جستجوی کامل. بازگشت یک dict با نتایج و آمار.

    polygon: [(lon, lat), ...] — اولویت با این است
    bbox:    (min_lon, min_lat, max_lon, max_lat)
    اگر هیچ‌کدام نبود، district_ids استفاده می‌شود؛ اگر آن هم نبود، کل شهر.
    """
    city_ids = [CITIES[city]]
    note = lambda msg: on_progress and on_progress(msg)

    ranges = _ranges(size, credit_max, rent_max, age_max, floor,
                     floors_count_max, units_per_floor_max)
    booleans = {"parking": parking, "elevator": elevator, "warehouse": storage,
                "has-photo": real_photos, "has-video": has_video,
                "balcony": balcony, "rebuilt": rebuilt}
    choices = {"recent_ads": recent_ads, "toilet": toilet,
               "heating_system": heating_system, "cooling_system": cooling_system}
    local = {"max_fre": max_fre, "max_fre_per_meter": max_fre_per_meter,
             "min_images": min_images, "convertible_only": convertible_only,
             "below_median_only": below_median_only,
             "hide_roommate": hide_roommate, "hide_trashed": hide_trashed,
             "weights": weights, "city": city}

    if polygon and not bbox:
        bbox = geo.bbox_of(polygon)
    elif not bbox and district_ids:
        # محله هم bbox دارد — مسیر سریع نقشه. فیلتر دقیق محله سمت دیوار می‌ماند.
        bbox = geo.districts_bbox(district_ids, city)
    elif not bbox:
        bbox = geo.city_bbox(city)
        note("بدون محدوده — کل شهر جستجو می‌شود")

    form_data = collector.build_form_data(
        ranges=ranges, rooms_min=rooms_min, booleans=booleans,
        owner_only=owner_only, districts=district_ids, choices=choices)

    # --- مرحله ۱: نقشه ---
    note("جستجوی نقشه‌ای ...")
    total, by_token, complete, leaves = collector.search_map_area(
        city_ids, form_data, bbox,
        on_progress=lambda d, l, f, t: note(f"خانه {d} (مانده {l}) — {f} از {t} آگهی"))
    items = list(by_token.values())
    if not complete:
        note(f"پوشش ناقص: {len(items)} از {total} آگهی — محدوده را کوچک‌تر کنید")

    # --- مرحله ۲: قیمت دقیق، به ازای هر خانه ---
    note(f"گرفتن قیمت دقیق از {len(leaves)} خانه ...")
    exact = collector.exact_prices_for_cells(city_ids, form_data, leaves)
    note(f"قیمت دقیق برای {len(exact)} از {len(items)} آگهی")

    # --- مرحله ۳: نرمال‌سازی ---
    normalized = [listing.from_map_card(card, exact.get(card["token"]), rate=rate)
                  for card in items]

    # --- مرحله ۴: فیلتر چندضلعی ---
    if polygon:
        before = len(normalized)
        normalized = geo.filter_to_polygon(normalized, polygon)
        note(f"فیلتر چندضلعی: {before} → {len(normalized)}")

    districts = geo.districts_in_polygon(polygon, city) if polygon else []
    return _finish(normalized, total, rate, note, districts=districts, store=store,
                   complete=complete,
                   size=size, rooms_min=rooms_min, credit_max=credit_max,
                   rent_max=rent_max, parking=parking, elevator=elevator,
                   storage=storage, real_photos=real_photos, **local)


def _finish(items, total, rate, note, districts, store=None, complete=True, **filters):
    kept = [i for i in items if listing.passes_hard_filters(
        i,
        size=filters.get("size"),
        rooms=(filters["rooms_min"], None) if filters.get("rooms_min") else None,
        credit=(None, filters["credit_max"]) if filters.get("credit_max") else None,
        rent=(None, filters["rent_max"]) if filters.get("rent_max") else None,
        need_parking=filters.get("parking", False),
        need_elevator=filters.get("elevator", False),
        need_storage=filters.get("storage", False),
        need_real_photos=filters.get("real_photos", False),
        max_fre=filters.get("max_fre"),
        max_fre_per_meter=filters.get("max_fre_per_meter"),
        min_images=filters.get("min_images"),
        convertible_only=filters.get("convertible_only", False),
    )]
    note(f"{len(kept)} از {len(items)} از فیلترهای قطعی گذشت")

    # آگهی هم‌خانه اجاره واحد نیست و median را خراب می‌کند
    if filters.get("hide_roommate", True):
        before = len(kept)
        kept = [i for i in kept if not listing.looks_like_roommate(i)]
        if before != len(kept):
            note(f"آگهی هم‌خانه: {before - len(kept)} مورد کنار گذاشته شد")

    # سطل آشغال — آنچه کاربر حذف کرده دیگر نمایش داده نمی‌شود
    if store is not None and filters.get("hide_trashed", True):
        trashed = store.marked_tokens("trash")
        if trashed:
            before = len(kept)
            kept = [i for i in kept if i.get("token") not in trashed]
            note(f"سطل آشغال: {before - len(kept)} مورد پنهان شد")

    city_name = filters.get("city", "tehran")
    for item in kept:
        name, dist = geo.nearest_metro(item.get("lat"), item.get("lon"), city_name)
        item["metro_name"] = name
        item["metro_distance_m"] = dist

    if store is not None:
        new_tokens = store.record(kept)
        store.annotate_history(kept, new_tokens, rate)
        note(f"{len(new_tokens)} آگهی جدید نسبت به اجراهای قبلی")

    median = listing.add_market_comparison(kept)

    # این یکی باید بعد از median اعمال شود، نه در فیلترهای قطعی
    if filters.get("below_median_only") and median:
        before = len(kept)
        kept = [i for i in kept if (i["fre_per_meter"] or float("inf")) < median]
        note(f"فقط زیر median: {before} → {len(kept)}")

    # امتیاز بعد از median حساب می‌شود چون به vs_market_pct نیاز دارد
    weights = filters.get("weights")
    bookmarked = store.marked_tokens("bookmark") if store is not None else set()
    for item in kept:
        listing.score_listing(item, weights)
        item["bookmarked"] = item.get("token") in bookmarked

    kept.sort(key=lambda i: -(i.get("score") or 0))
    rounded = sum(1 for i in kept if i.get("price_is_rounded"))

    return {
        "results": [i for i in kept if not i.get("suspicious")],
        "suspicious": [i for i in kept if i.get("suspicious")],
        "median_per_meter": median,
        # شمارش دیوار روی ۱۰۰۰۰ اشباع می‌شود؛ گاهی بیشتر از آن جمع می‌کنیم
        "divar_count": max(total, len(items)),
        "divar_count_saturated": total >= 10000,
        "price_rounded_count": rounded,
        "collected": len(items),
        "districts_in_region": districts,
        "complete": complete,
        "weights": {**listing.DEFAULT_WEIGHTS, **(weights or {})},
        "rate": rate,
    }
