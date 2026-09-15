"""پنل وب — یک پوسته نازک روی divar_demo.search.

هیچ منطق قیمت یا فیلتری اینجا نیست.
"""

import asyncio
import os
import sys

from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from divar_demo import config, geo, notify, search  # noqa: E402
from divar_demo.store import Store  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
STATIC = os.path.join(HERE, "static")

app = FastAPI(title="رتبه‌بندی آگهی‌های اجاره دیوار")
app.mount("/static", StaticFiles(directory=STATIC), name="static")

# محدودیت نرخ دیوار روی IP ماست، نه روی کاربر — پس در هر لحظه یک جستجو
search_lock = asyncio.Lock()


@app.on_event("startup")
def start_scheduler():
    """اطلاع‌رسانی دوره‌ای — فقط اگر در .env روشن شده باشد."""
    if not config.NOTIFY_INTERVAL_HOURS or not config.telegram_ready():
        return
    from apscheduler.schedulers.background import BackgroundScheduler

    def job():
        with search_lock_sync():
            notify.run_saved_searches()

    scheduler = BackgroundScheduler()
    scheduler.add_job(job, "interval", hours=config.NOTIFY_INTERVAL_HOURS,
                      id="notify", max_instances=1, coalesce=True)
    scheduler.start()
    app.state.scheduler = scheduler
    print(f"اطلاع‌رسانی تلگرام هر {config.NOTIFY_INTERVAL_HOURS} ساعت فعال شد.")


def search_lock_sync():
    """قفل جداگانه برای زمان‌بند — نخ پس‌زمینه به asyncio.Lock دسترسی ندارد."""
    import threading

    if not hasattr(app.state, "_job_lock"):
        app.state._job_lock = threading.Lock()
    return app.state._job_lock


class SearchRequest(BaseModel):
    city: str = "tehran"
    polygon: list[list[float]] | None = None
    district_ids: list[int] = []
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
    polygon = [(p[0], p[1]) for p in req.polygon] if req.polygon else None
    size = (req.size_min, req.size_max) if (req.size_min or req.size_max) else None

    def work():
        with Store() as store:
            return search.run_search(
                city=req.city, polygon=polygon,
                district_ids=[str(d) for d in req.district_ids] or None,
                size=size, rooms_min=req.rooms_min,
                credit_max=req.credit_max, rent_max=req.rent_max,
                parking=req.parking, elevator=req.elevator,
                storage=req.storage, owner_only=req.owner_only,
                real_photos=req.real_photos, has_video=req.has_video,
                balcony=req.balcony, rebuilt=req.rebuilt,
                recent_ads=req.recent_ads, toilet=req.toilet,
                heating_system=[req.heating_system] if req.heating_system else None,
                cooling_system=[req.cooling_system] if req.cooling_system else None,
                age_max=req.age_max,
                floor=(req.floor_min, req.floor_max)
                      if (req.floor_min or req.floor_max) else None,
                floors_count_max=req.floors_count_max,
                units_per_floor_max=req.units_per_floor_max,
                max_fre=req.max_fre, max_fre_per_meter=req.max_fre_per_meter,
                min_images=req.min_images,
                convertible_only=req.convertible_only,
                below_median_only=req.below_median_only,
                hide_roommate=req.hide_roommate,
                store=store,
            )

    async with search_lock:
        result = await asyncio.to_thread(work)

    result["districts_in_region"] = [
        {"id": d["id"], "name": d["name"]} for d in result["districts_in_region"]]

    top_tokens = [r["token"] for r in result["results"][:PREFETCH_TOP] if r.get("token")]
    if top_tokens:
        background.add_task(_prefetch, top_tokens)

    return result


class SaveRequest(BaseModel):
    name: str
    params: SearchRequest


@app.get("/api/searches")
def searches():
    from divar_demo import config

    with Store() as store:
        rows = store.list_searches()
    return {
        "searches": [{"id": r["id"], "name": r["name"],
                      "created_at": r["created_at"], "last_run_at": r["last_run_at"]}
                     for r in rows],
        "telegram_ready": config.telegram_ready(),
        "missing_env": config.missing(),
        "interval_hours": config.NOTIFY_INTERVAL_HOURS,
    }


@app.post("/api/searches")
def save_search(req: SaveRequest):
    params = req.params.model_dump()
    params.pop("city", None)
    with Store() as store:
        new_id = store.save_search(req.name, params)
    return {"id": new_id}


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
    return {"ok": True}


@app.delete("/api/marks/{kind}/{token}")
def remove_mark(kind: str, token: str):
    """بازگرداندن از سطل آشغال، یا حذف بوکمارک."""
    if kind not in ("trash", "bookmark"):
        raise HTTPException(400, "نوع نامعتبر")
    with Store() as store:
        store.unmark(token, kind)
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
