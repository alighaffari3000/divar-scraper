"""خط فرمان: آگهی‌های اجاره دیوار را بگیر، به رهن کامل معادل تبدیل کن، مرتب کن.

نمونه:
  python -m divar_demo.main --district اختیاریه --size 80-150 --rooms 2 --real-photos

همه فیلترها اختیاری‌اند؛ هرکدام را ندهید اصلاً به دیوار فرستاده نمی‌شود.
"""

import argparse
import csv
import json
import sys

from . import geo, listing, search


def parse_range(text):
    if not text:
        return None
    if "-" in text:
        lo, _, hi = text.partition("-")
        return (float(lo) if lo.strip() else None, float(hi) if hi.strip() else None)
    return (float(text), None)


def million(value):
    return "-" if value is None else f"{value / 1_000_000:,.0f}"


def yes_no(value):
    return {True: "دارد", False: "ندارد", None: "؟"}[value]


def build_args():
    p = argparse.ArgumentParser(description="رتبه‌بندی آگهی‌های اجاره دیوار")
    p.add_argument("--city", default="tehran", choices=sorted(search.CITIES))
    p.add_argument("--district", help="نام محله، چندتایی با کاما. ندهید یعنی کل شهر")

    g = p.add_argument_group("فیلترهای دیوار")
    g.add_argument("--size", help="بازه متراژ، مثلاً 80-150")
    g.add_argument("--rooms", type=int, help="حداقل تعداد اتاق")
    g.add_argument("--credit-max", type=float, help="حداکثر ودیعه (تومان)")
    g.add_argument("--rent-max", type=float, help="حداکثر اجاره ماهانه (تومان)")
    g.add_argument("--parking", action="store_true")
    g.add_argument("--elevator", action="store_true")
    g.add_argument("--storage", action="store_true")
    g.add_argument("--balcony", action="store_true")
    g.add_argument("--rebuilt", action="store_true", help="فقط بازسازی‌شده")
    g.add_argument("--owner-only", action="store_true", help="فقط شخصی، بدون مشاور")
    g.add_argument("--real-photos", action="store_true", help="فقط عکس واقعی ملک")
    g.add_argument("--has-video", action="store_true")
    g.add_argument("--age-max", type=int, help="حداکثر سن بنا (سال)")
    g.add_argument("--floor", help="بازه طبقه، مثلاً 1-3")
    g.add_argument("--floors-count-max", type=int, help="حداکثر تعداد کل طبقات")
    g.add_argument("--units-per-floor-max", type=int, help="حداکثر واحد در طبقه")
    g.add_argument("--recent", choices=("3h", "12h", "1d", "3d", "7d"),
                   help="فقط آگهی‌های این بازه اخیر")
    g.add_argument("--toilet", choices=("squat", "seat", "squat_seat"))
    g.add_argument("--heating", action="append",
                   choices=("heater", "shoofaj", "fan_coil", "floor_heating",
                            "duct_split", "split"))
    g.add_argument("--cooling", action="append",
                   choices=("water_cooler", "air_conditioner", "duct_split",
                            "split", "fan_coil"))

    o = p.add_argument_group("فیلترهایی که دیوار ندارد")
    o.add_argument("--max-fre", type=float, help="حداکثر رهن کامل معادل (تومان)")
    o.add_argument("--max-fre-per-meter", type=float, help="حداکثر رهن معادل متری (تومان)")
    o.add_argument("--min-images", type=int, help="حداقل تعداد عکس")
    o.add_argument("--convertible-only", action="store_true",
                   help="فقط ودیعه/اجاره قابل تبدیل")
    o.add_argument("--below-median", action="store_true", help="فقط زیر median بازار")

    p.add_argument("--rate", type=float, default=listing.DEPOSIT_PER_RENT,
                   help="نرخ تبدیل: هر ۱ تومان اجاره چند تومان ودیعه (پیش‌فرض ۳۳.۳)")
    p.add_argument("--top", type=int, default=15, help="چند مورد نمایش داده شود")
    p.add_argument("--out", help="مسیر فایل خروجی، پسوند .csv یا .json")
    return p.parse_args()


def resolve_districts(names, city):
    ids = []
    for name in names.split(","):
        name = name.strip()
        if not name:
            continue
        found = geo.resolve_district(name, city=city)
        if not found:
            print(f"محله «{name}» پیدا نشد.", file=sys.stderr)
            continue
        if len(found) > 1:
            others = "، ".join(d["name"] for d in found[1:])
            print(f"«{name}» → {found[0]['name']} (گزینه‌های دیگر: {others})",
                  file=sys.stderr)
        ids.append(str(found[0]["id"]))
    return ids


def main():
    args = build_args()

    district_ids = None
    if args.district:
        district_ids = resolve_districts(args.district, args.city)
        if not district_ids:
            return 1
    else:
        print("بدون --district: کل شهر جستجو می‌شود (کندتر).", file=sys.stderr)

    result = search.run_search(
        city=args.city,
        district_ids=district_ids,
        size=parse_range(args.size),
        rooms_min=args.rooms,
        credit_max=args.credit_max,
        rent_max=args.rent_max,
        parking=args.parking,
        elevator=args.elevator,
        storage=args.storage,
        balcony=args.balcony,
        rebuilt=args.rebuilt,
        owner_only=args.owner_only,
        real_photos=args.real_photos,
        has_video=args.has_video,
        age_max=args.age_max,
        floor=parse_range(args.floor),
        floors_count_max=args.floors_count_max,
        units_per_floor_max=args.units_per_floor_max,
        recent_ads=args.recent,
        toilet=args.toilet,
        heating_system=args.heating,
        cooling_system=args.cooling,
        max_fre=args.max_fre,
        max_fre_per_meter=args.max_fre_per_meter,
        min_images=args.min_images,
        convertible_only=args.convertible_only,
        below_median_only=args.below_median,
        rate=args.rate,
        on_progress=lambda msg: print(f"  {msg}", file=sys.stderr),
    )

    if not result.get("complete", True):
        print("هشدار: پوشش ناقص — محدوده بزرگ بود. فیلتر بیشتری بگذارید.",
              file=sys.stderr)

    normal = result["results"]
    if not normal:
        print("چیزی برای نمایش نماند.", file=sys.stderr)
        return 0

    median = result["median_per_meter"]
    if median:
        print(f"\nmedian رهن معادل متری: {million(median)} میلیون "
              f"(روی {len(normal)} نمونه)\n")
    else:
        print("\nنمونه کمتر از ۵ مورد — مقایسه با بازار انجام نشد\n")

    print_table(normal[:args.top])

    if result["suspicious"]:
        print(f"\nبیش از حد ارزان — احتمالاً اجاره واحد نیست، کنار گذاشته شد "
              f"({len(result['suspicious'])} مورد):")
        print_table(result["suspicious"], compact=True)

    if args.out:
        write_output(args.out, normal)
        print(f"\nخروجی در {args.out} نوشته شد.", file=sys.stderr)
    return 0


def print_table(items, compact=False):
    header = (f"{'متری':>8} {'رهن معادل':>11} {'بازار':>7} {'متراژ':>6} {'اتاق':>5} "
              f"{'ساخت':>6}  {'پارک':<5} {'آسان':<5} عنوان")
    print(header)
    print("-" * len(header))
    for item in items:
        vs = item.get("vs_market_pct")
        vs_text = "-" if vs is None else f"{vs:+.0f}%"
        print(f"{million(item['fre_per_meter']):>8} {million(item['full_rent_equivalent']):>11} "
              f"{vs_text:>7} {item['size']:>6.0f} "
              f"{(item['rooms'] or 0):>5.0f} {(item['year_built'] or 0):>6.0f}  "
              f"{yes_no(item['parking']):<5} {yes_no(item['elevator']):<5} "
              f"{(item['title'] or '')[:32]}")
        if not compact:
            print(f"{'':>8} {item.get('district') or '':<12} "
                  f"ودیعه {million(item['deposit'])}م + "
                  f"اجاره {million(item['monthly_rent'])}م  {item['url']}")


def write_output(path, items):
    if path.endswith(".json"):
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(items, fh, ensure_ascii=False, indent=1)
    else:
        with open(path, "w", encoding="utf-8-sig", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=list(items[0]))
            writer.writeheader()
            writer.writerows(items)


if __name__ == "__main__":
    sys.exit(main())
