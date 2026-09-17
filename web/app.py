"""پنل وب — یک پوسته نازک روی divar_demo.search.

هیچ منطق قیمت یا فیلتری اینجا نیست.
"""

import asyncio
import json
import os
import sys
import time

from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from divar_demo import config, geo, search  # noqa: E402
from divar_demo.store import Store  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
STATIC = os.path.join(HERE, "static")

app = FastAPI(title="رتبه‌بندی آگهی‌های اجاره دیوار")
app.mount("/static", StaticFiles(directory=STATIC), name="static")

# محدودیت نرخ دیوار روی IP ماست، نه روی کاربر — پس در هر لحظه یک جستجو
search_lock = asyncio.Lock()

# کش نتیجه فقط برای محافظت از دیوار در برابر کلیک‌های پشت‌سرهم است، نه برای سرعت.
# عمدا خیلی کوتاه: در بازار اجاره تهران آگهی خوب چند ساعته می‌رود، و نتیجه بیات
# بدتر از نتیجه کند است.
SEARCH_CACHE_TTL = 120.0
_search_cache: dict[str, tuple[float, dict]] = {}


def _cache_key(req):
    payload = req.model_dump()
    payload.pop("refresh", None)
    return json.dumps(payload, sort_keys=True, ensure_ascii=False)


def _cache_get(key):
    hit = _search_cache.get(key)
    if not hit:
        return None
    stamp, value = hit
    if time.monotonic() - stamp > SEARCH_CACHE_TTL:
        _search_cache.pop(key, None)
        return None
    return stamp, value


def _cache_put(key, value):
    _search_cache[key] = (time.monotonic(), value)
    # کش را کوچک نگه دار — این یک حافظه بلندمدت نیست
    if len(_search_cache) > 20:
        oldest = min(_search_cache, key=lambda k: _search_cache[k][0])
        _search_cache.pop(oldest, None)


class SearchRequest(BaseModel):
    city: str = "tehran"
    polygon: list[list[float]] | None = None
    district_ids: list[int] = []
    # فقط برای بازسازی چیپ‌ها موقع ویرایش؛ موتور جستجو نادیده‌اش می‌گیرد
    district_names: list[str] = []
    # محله‌هایی که حتی داخل محدوده نقشه هم نباید بیایند
    exclude_district_ids: list[int] = []
    exclude_district_names: list[str] = []
    size_min: float | None = None
    size_max: float | None = None
    rooms_min: int | None = None
    credit_max: float | None = None
    rent_max: float | None = None
    parking: bool = False
    elevator: bool = False
    storage: bool = False
    owner_only: bool = False
    real_photos: bool = False
    has_video: bool = False
    balcony: bool = False
    rebuilt: bool = False
    recent_ads: str | None = None
    toilet: str | None = None
    heating_system: str | None = None
    cooling_system: str | None = None
    age_max: int | None = None
    floor_min: int | None = None
    floor_max: int | None = None
    floors_count_max: int | None = None
    units_per_floor_max: int | None = None
    max_fre: float | None = None
    max_fre_per_meter: float | None = None
    min_images: int | None = None
    convertible_only: bool = False
    below_median_only: bool = False
    hide_roommate: bool = True
    # وزن معیارهای امتیاز — بدون این، جستجوی ذخیره‌شده وزن‌های پنل را از دست
    # می‌داد و بات همیشه با وزن پیش‌فرض امتیاز می‌داد
    weights: dict[str, float] | None = None
    refresh: bool = False  # کش را دور بزن


@app.get("/")
def index():
    return FileResponse(os.path.join(STATIC, "index.html"))


@app.get("/api/districts")
def districts(q: str = "", city: str = "tehran"):
    """پیشنهاد محله برای جعبه جستجو."""
    if not q:
        return []
    found = geo.resolve_district(q, city=city)
    return [{"id": d["id"], "name": d["name"]} for d in found]


PREFETCH_TOP = 20  # جزئیات چند آگهی برتر را از قبل بگیریم


def _prefetch(tokens):
    """جزئیات آگهی‌های برتر را در پس‌زمینه گرم می‌کند تا کلیک کاربر فوری باشد."""
    from divar_demo import collector

    with Store() as store:
        collector.fetch_details_parallel(tokens, store=store, workers=3)


@app.post("/api/search")
async def run(req: SearchRequest, background: BackgroundTasks):
    key = _cache_key(req)
    if not req.refresh:
        hit = _cache_get(key)
        if hit:
            stamp, cached = hit
            return {**cached, "from_cache": True,
                    "cache_age_s": round(time.monotonic() - stamp)}

    # تبدیل در یک جا (search.params_from_request) تا پارامترهای ذخیره‌شده
    # همیشه با همان منطق اجرا شوند — پنل و اطلاع‌رسانی یکسان.
    kwargs = search.params_from_request(req.model_dump())

    def work():
        with Store() as store:
            return search.run_search(store=store, **kwargs)

    async with search_lock:
        result = await asyncio.to_thread(work)

    result["districts_in_region"] = [
        {"id": d["id"], "name": d["name"]} for d in result["districts_in_region"]]

    top_tokens = [r["token"] for r in result["results"][:PREFETCH_TOP] if r.get("token")]
    if top_tokens:
        background.add_task(_prefetch, top_tokens)

    result["from_cache"] = False
    result["cache_age_s"] = 0
    _cache_put(key, result)
    return result


class SaveRequest(BaseModel):
    name: str
    params: SearchRequest


@app.get("/api/searches")
def searches():
    with Store() as store:
        rows = store.list_searches()
    return {
        "searches": [{"id": r["id"], "name": r["name"],
                      "created_at": r["created_at"], "last_run_at": r["last_run_at"],
                      "enabled": bool(r.get("enabled", 1)),
                      "params": json.loads(r["params_json"])}
                     for r in rows],
        "telegram_ready": config.telegram_ready(),
        "missing_env": config.missing(),
    }


class SettingsRequest(BaseModel):
    interval_minutes: float | None = None
    score_threshold: float | None = None


@app.get("/api/settings")
def get_settings():
    """تنظیمات بات + وضعیت آخرین اجرا. بات هر دقیقه همین‌ها را می‌خواند."""
    with Store() as store:
        st = store.all_settings()
        last_ok = store.last_ok_run()
        runs = store.last_runs(1)
    return {
        "interval_minutes": float(st.get("interval_minutes") or config.BOT_INTERVAL_MINUTES),
        "score_threshold": float(st.get("score_threshold") or config.BOT_SCORE_THRESHOLD),
        "muted_until": st.get("muted_until"),
        "last_ok_run": last_ok,
        "last_run": runs[0] if runs else None,
    }


@app.put("/api/settings")
def put_settings(req: SettingsRequest):
    with Store() as store:
        if req.interval_minutes is not None:
            store.set_setting("interval_minutes", max(5.0, req.interval_minutes))
        if req.score_threshold is not None:
            store.set_setting("score_threshold", min(100.0, max(0.0, req.score_threshold)))
    return get_settings()


@app.post("/api/searches")
def save_search(req: SaveRequest):
    params = req.params.model_dump()
    params.pop("city", None)
    with Store() as store:
        new_id = store.save_search(req.name, params)
    return {"id": new_id}


class UpdateSearchRequest(BaseModel):
    """هر سه اختیاری — تغییر نام، تغییر فیلترها، فعال/غیرفعال کردن."""

    name: str | None = None
    params: SearchRequest | None = None
    enabled: bool | None = None


@app.patch("/api/searches/{search_id}")
def update_search(search_id: int, req: UpdateSearchRequest):
    params = None
    if req.params is not None:
        params = req.params.model_dump()
        params.pop("city", None)
    with Store() as store:
        if not store.get_search(search_id):
            raise HTTPException(404, "جستجو یافت نشد")
        store.update_search(search_id, name=req.name, params=params, enabled=req.enabled)
    return {"ok": True}


@app.delete("/api/searches/{search_id}")
def delete_search(search_id: int):
    with Store() as store:
        store.delete_search(search_id)
    return {"ok": True}


class MarkRequest(BaseModel):
    token: str
    note: str | None = None


@app.get("/api/marks/{kind}")
def list_marks(kind: str):
    """محتویات تب سطل آشغال یا بوکمارک."""
    if kind not in ("trash", "bookmark"):
        raise HTTPException(400, "نوع نامعتبر")
    with Store() as store:
        return {"items": store.marked_items(kind)}


@app.post("/api/marks/{kind}")
def add_mark(kind: str, req: MarkRequest):
    if kind not in ("trash", "bookmark"):
        raise HTTPException(400, "نوع نامعتبر")
    with Store() as store:
        store.mark(req.token, kind, req.note)
    _search_cache.clear()  # نتیجه کش‌شده دیگر با علامت‌ها همخوان نیست
    return {"ok": True}


@app.delete("/api/marks/{kind}/{token}")
def remove_mark(kind: str, token: str):
    """بازگرداندن از سطل آشغال، یا حذف بوکمارک."""
    if kind not in ("trash", "bookmark"):
        raise HTTPException(400, "نوع نامعتبر")
    with Store() as store:
        store.unmark(token, kind)
    _search_cache.clear()
    return {"ok": True}


@app.get("/api/post/{token}")
async def post_detail(token: str):
    """جزئیات تنبل یک آگهی — با کش."""
    from divar_demo import collector

    def work():
        with Store() as store:
            for detail in collector.fetch_details([token], store=store):
                return detail

    detail = await asyncio.to_thread(work)
    if not detail or "error" in detail:
        raise HTTPException(404, "آگهی یافت نشد")
    return detail
