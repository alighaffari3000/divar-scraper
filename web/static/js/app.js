/* پنل جستجوی آگهی‌های اجاره — نقشه، فیلترها، جدول نتایج */

const fa = (n) => (n == null ? "—" : n.toLocaleString("fa-IR"));
const million = (v) => (v == null ? "—" : fa(Math.round(v / 1e6)));
const pct = (v) => (v == null ? "—" : `${v > 0 ? "+" : ""}${fa(Math.round(v))}٪`);

// متن آگهی محتوای کاربر غریبه است — هیچ‌وقت خام در innerHTML نرود
const esc = (s) =>
  String(s ?? "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]
  );

const SCORE_BASE = 50;
const WEIGHT_LABELS = { deal: "قیمت", age: "نوسازی", metro: "مترو" };

let state = {
  polygon: null,
  districts: [], // {id, name}
  excludeDistricts: [], // {id, name} — هرگز نمایش داده نشوند
  results: [],
  weights: { deal: 30, age: 15, metro: 10 },
  sortKey: "score",
  sortAsc: false,
  markers: null,
  markerByToken: new Map(),
  tab: "results",
  searches: [],
  missingEnv: [],
  lastPayload: null,
};

/* ---------- نقشه ---------- */

const map = L.map("map", {
  // پیش‌فرض لیفلت هر بار یک واحد کامل زوم می‌کند و جهش می‌زند؛ این ریزترش می‌کند
  zoomSnap: 0.25,
  zoomDelta: 0.25,
  wheelPxPerZoomLevel: 240,
}).setView([35.7219, 51.3347], 12);
L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
  maxZoom: 19,
  attribution: "© OpenStreetMap",
}).addTo(map);

const drawnItems = new L.FeatureGroup().addTo(map);
state.markers = L.layerGroup().addTo(map);

map.addControl(
  new L.Control.Draw({
    edit: { featureGroup: drawnItems, edit: false },
    draw: {
      polygon: { showArea: false, shapeOptions: { color: "#465fff" } },
      rectangle: { shapeOptions: { color: "#465fff" } },
      polyline: false,
      circle: false,
      marker: false,
      circlemarker: false,
    },
  })
);

map.on(L.Draw.Event.CREATED, (e) => {
  drawnItems.clearLayers();
  drawnItems.addLayer(e.layer);
  state.polygon = e.layer.getLatLngs()[0].map((p) => [p.lng, p.lat]);
  setProgress(`محدوده انتخاب شد (${fa(state.polygon.length)} نقطه)`);
});

map.on(L.Draw.Event.DELETED, () => {
  state.polygon = null;
});

/* ---------- تمام‌صفحه کردن نقشه ---------- */

const mapCard = document.getElementById("map-card");

function setMapExpanded(on) {
  mapCard.classList.toggle("map-expanded", on);
  document.getElementById("map-expand-label").textContent = on ? "بستن" : "تمام‌صفحه";
  // لیفلت اندازه ظرف را کش می‌کند؛ بعد از تغییر ارتفاع باید دوباره بسنجد
  setTimeout(() => map.invalidateSize(), 0);
}

document.getElementById("map-expand").onclick = () =>
  setMapExpanded(!mapCard.classList.contains("map-expanded"));

document.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && mapCard.classList.contains("map-expanded")) {
    setMapExpanded(false);
  }
});

/* ---------- انتخاب محله ---------- */

/* دو جعبه محله داریم: یکی برای «فقط این محله‌ها»، یکی برای «هیچ‌وقت این‌ها».
   هر دو رفتار یکسانی دارند، پس یک سازنده مشترک. */
function districtPicker({ inputId, boxId, chipsId, stateKey, chipClass, chipBtnClass }) {
  const input = document.getElementById(inputId);
  const suggestionBox = document.getElementById(boxId);
  const chipBox = document.getElementById(chipsId);
  let timer = null;

  function renderChips() {
    chipBox.innerHTML = "";
    state[stateKey].forEach((d) => {
      const chip = document.createElement("span");
      chip.className = chipClass;
      chip.innerHTML = `${esc(d.name)} <button type="button" class="${chipBtnClass}">✕</button>`;
      chip.querySelector("button").onclick = () => {
        state[stateKey] = state[stateKey].filter((x) => x.id !== d.id);
        renderChips();
      };
      chipBox.appendChild(chip);
    });
  }

  input.addEventListener("input", () => {
    clearTimeout(timer);
    const q = input.value.trim();
    if (q.length < 2) {
      suggestionBox.innerHTML = "";
      return;
    }
    timer = setTimeout(async () => {
      const res = await fetch(`/api/districts?q=${encodeURIComponent(q)}`);
      const list = await res.json();
      suggestionBox.innerHTML = "";
      list.forEach((d) => {
        const btn = document.createElement("button");
        btn.type = "button";
        btn.className =
          "rounded-lg border border-gray-200 px-3 py-1.5 text-right text-theme-xs text-gray-700 hover:border-brand-500 hover:text-brand-500 dark:border-gray-700 dark:text-gray-400";
        btn.textContent = d.name;
        btn.onclick = () => {
          if (!state[stateKey].find((x) => x.id === d.id)) state[stateKey].push(d);
          input.value = "";
          suggestionBox.innerHTML = "";
          renderChips();
        };
        suggestionBox.appendChild(btn);
      });
    }, 250);
  });

  return renderChips;
}

const renderChips = districtPicker({
  inputId: "district-search",
  boxId: "district-suggestions",
  chipsId: "district-chips",
  stateKey: "districts",
  chipClass:
    "inline-flex items-center gap-1.5 rounded-full bg-brand-50 px-3 py-1 text-theme-xs text-brand-600 dark:bg-brand-500/15 dark:text-brand-400",
  chipBtnClass: "text-brand-400 hover:text-error-500",
});

const renderExcludeChips = districtPicker({
  inputId: "exclude-search",
  boxId: "exclude-suggestions",
  chipsId: "exclude-chips",
  stateKey: "excludeDistricts",
  chipClass:
    "inline-flex items-center gap-1.5 rounded-full bg-error-50 px-3 py-1 text-theme-xs text-error-600 dark:bg-error-500/15 dark:text-error-400",
  chipBtnClass: "text-error-400 hover:text-error-600",
});

/* ---------- دکمه‌های اتاق ---------- */

document.querySelectorAll(".room-btn").forEach((btn) => {
  btn.onclick = () => {
    document.querySelectorAll(".room-btn").forEach((b) => b.classList.remove("active"));
    btn.classList.add("active");
    document.querySelector('[name="rooms_min"]').value = btn.dataset.rooms;
  };
});

/* ---------- وزن معیارها (بازمحاسبه سمت مرورگر، بدون سرور) ---------- */

document.querySelectorAll("input[data-weight]").forEach((slider) => {
  const key = slider.dataset.weight;
  const label = document.querySelector(`[data-weight-value="${key}"]`);
  const sync = () => {
    state.weights[key] = Number(slider.value);
    if (label) label.textContent = fa(Number(slider.value));
  };
  sync();
  slider.addEventListener("input", () => {
    sync();
    rescore();
    if (state.tab === "results") renderTable();
  });
});

function rescore() {
  for (const r of state.results) {
    const f = r.score_factors ?? {};
    let total = SCORE_BASE;
    const parts = {};
    for (const [k, v] of Object.entries(f)) {
      parts[k] = Math.round(v * (state.weights[k] ?? 0) * 10) / 10;
      total += parts[k];
    }
    r.score = Math.round(Math.max(0, Math.min(100, total)) * 10) / 10;
    r.score_parts = parts;
  }
}

/* ---------- اجرای جستجو ---------- */

const form = document.getElementById("filters");
const runBtn = document.getElementById("run-btn");
const progressEl = document.getElementById("progress");
const loadingEl = document.getElementById("loading");

function setProgress(text) {
  progressEl.textContent = text || "";
}

function setLoading(on) {
  loadingEl.classList.toggle("hidden", !on);
  runBtn.disabled = on;
  runBtn.textContent = on ? "در حال جستجو ..." : "جستجو";
  document.getElementById("refresh-btn").disabled = on;
}

let forceRefresh = false;
document.getElementById("refresh-btn").onclick = () => {
  forceRefresh = true;
  form.requestSubmit();
};

// مقادیری که کاربر به میلیون وارد می‌کند و API تومان می‌خواهد
const MILLION_FIELDS = ["credit_max", "rent_max", "max_fre", "max_fre_per_meter"];

// چیپی که از یک جستجوی فقط-نام آمده شناسه عددی ندارد؛ فیلتر محله سمت دیوار
// فقط عدد می‌فهمد، ولی کنارگذاشتن با نام هم کار می‌کند.
const numericIds = (chips) =>
  chips.map((d) => d.id).filter((x) => Number.isInteger(x));

// یک جا ساخته می‌شود تا هم جستجو و هم ذخیره/ویرایش دقیقاً یک شکل بفرستند
function buildPayload(refresh = false) {
  const data = new FormData(form);
  const num = (k) => {
    const v = data.get(k);
    return v ? Number(v) : null;
  };
  const on = (k) => data.get(k) === "on";

  return {
    polygon: state.polygon,
    district_ids: numericIds(state.districts),
    district_names: state.districts.map((d) => d.name),
    exclude_district_ids: numericIds(state.excludeDistricts),
    exclude_district_names: state.excludeDistricts.map((d) => d.name),
    size_min: num("size_min"),
    size_max: num("size_max"),
    rooms_min: num("rooms_min"),
    // کاربر میلیون وارد می‌کند، API تومان می‌خواهد
    credit_max: num("credit_max") ? num("credit_max") * 1e6 : null,
    rent_max: num("rent_max") ? num("rent_max") * 1e6 : null,
    parking: on("parking"),
    elevator: on("elevator"),
    storage: on("storage"),
    owner_only: on("owner_only"),
    real_photos: on("real_photos"),
    has_video: on("has_video"),

    // فیلترهای بیشتر — همه اختیاری؛ خالی یعنی اعمال نشود
    balcony: on("balcony"),
    rebuilt: on("rebuilt"),
    recent_ads: data.get("recent_ads") || null,
    toilet: data.get("toilet") || null,
    heating_system: data.get("heating_system") || null,
    cooling_system: data.get("cooling_system") || null,
    age_max: num("age_max"),
    floor_min: num("floor_min"),
    floor_max: num("floor_max"),
    floors_count_max: num("floors_count_max"),
    units_per_floor_max: num("units_per_floor_max"),
    max_fre: num("max_fre") ? num("max_fre") * 1e6 : null,
    max_fre_per_meter: num("max_fre_per_meter") ? num("max_fre_per_meter") * 1e6 : null,
    min_images: num("min_images"),
    convertible_only: on("convertible_only"),
    below_median_only: on("below_median_only"),
    hide_roommate: on("hide_roommate"),
    // وزن‌ها برای اطلاع‌رسانی ذخیره می‌شوند؛ پنل خودش بازمحاسبه می‌کند
    weights: { ...state.weights },
    refresh,
  };
}

form.addEventListener("submit", async (e) => {
  e.preventDefault();
  const payload = buildPayload(forceRefresh);

  state.lastPayload = payload;
  rememberSearch(payload);
  setLoading(true);
  setProgress("");
  showTab("results");

  try {
    const res = await fetch("/api/search", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!res.ok) throw new Error(await res.text());
    render(await res.json());
  } catch (err) {
    setProgress(`خطا: ${err.message}`);
  } finally {
    forceRefresh = false;
    setLoading(false);
  }
});

/* ---------- جستجوهای ذخیره‌شده ---------- */

const saveBtn = document.getElementById("save-btn");
const cancelEditBtn = document.getElementById("cancel-edit-btn");

// وقتی پر باشد، دکمه ذخیره به‌جای ساختن جستجوی تازه همین را به‌روز می‌کند
let editing = null;

function setEditing(s) {
  editing = s;
  saveBtn.textContent = s ? `به‌روزرسانی «${s.name}»` : "ذخیره برای اطلاع‌رسانی";
  cancelEditBtn.classList.toggle("hidden", !s);
  if (s) {
    applyPayload(s.params);
    setProgress(`فیلترهای «${s.name}» بارگذاری شد — تغییر بدهید و به‌روزرسانی بزنید.`);
  }
}

cancelEditBtn.onclick = () => {
  setEditing(null);
  setProgress("");
};

/** فیلترهای یک جستجوی ذخیره‌شده را در فرم و نقشه می‌نشاند — وارونه buildPayload. */
function applyPayload(params) {
  const p = params || {};
  form.reset();

  Object.entries(p).forEach(([key, val]) => {
    const el = form.querySelector(`[name="${key}"]`);
    if (!el) return;
    if (el.type === "checkbox") el.checked = Boolean(val);
    else if (val == null || val === "") el.value = "";
    else el.value = MILLION_FIELDS.includes(key) ? val / 1e6 : val;
  });

  // دکمه‌های اتاق با مقدار مخفی rooms_min هماهنگ شوند
  const rooms = p.rooms_min == null ? "" : String(p.rooms_min);
  document.querySelectorAll(".room-btn").forEach((b) =>
    b.classList.toggle("active", b.dataset.rooms === rooms)
  );

  // اسلایدرهای وزن — رویداد input باعث بازمحاسبه امتیازها می‌شود
  document.querySelectorAll("input[data-weight]").forEach((slider) => {
    const w = (p.weights || {})[slider.dataset.weight];
    if (w != null) slider.value = w;
    slider.dispatchEvent(new Event("input"));
  });

  // محله‌ها — نام‌ها کنار شناسه‌ها ذخیره می‌شوند تا چیپ‌ها خوانا برگردند
  // جستجویی که فقط نام دارد (بدون شناسه) هم باید چیپ‌هایش برگردد
  const pairs = (ids, names) => {
    const count = Math.max((ids || []).length, (names || []).length);
    return Array.from({ length: count }, (_, i) => {
      const id = (ids || [])[i];
      const name = (names || [])[i];
      return { id: id ?? name, name: name || `محله ${id}` };
    });
  };
  state.districts = pairs(p.district_ids, p.district_names);
  state.excludeDistricts = pairs(p.exclude_district_ids, p.exclude_district_names);
  renderChips();
  renderExcludeChips();

  // چندضلعی روی نقشه
  drawnItems.clearLayers();
  state.polygon = p.polygon || null;
  if (state.polygon && state.polygon.length) {
    const layer = L.polygon(
      state.polygon.map(([lng, lat]) => [lat, lng]),
      { color: "#465fff" }
    );
    drawnItems.addLayer(layer);
    map.fitBounds(layer.getBounds(), { padding: [20, 20] });
  }
}

saveBtn.onclick = async () => {
  const params = buildPayload();
  const name = prompt("نامی برای این جستجو:", editing ? editing.name : "");
  if (!name) return;

  saveBtn.disabled = true;
  try {
    const res = editing
      ? await fetch(`/api/searches/${editing.id}`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ name, params }),
        })
      : await fetch("/api/searches", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ name, params }),
        });
    if (!res.ok) throw new Error(await res.text());
    setEditing(null);
    setProgress("ذخیره شد.");
    await loadSaved();
  } catch (err) {
    setProgress(`ذخیره نشد: ${err.message}`);
  } finally {
    saveBtn.disabled = false;
  }
};

async function patchSearch(id, body) {
  const res = await fetch(`/api/searches/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) setProgress(`انجام نشد: ${await res.text()}`);
  await loadSaved();
}

const ICON_BTN =
  "flex h-8 w-8 shrink-0 items-center justify-center rounded-md border border-gray-300 text-gray-500 transition dark:border-gray-700 dark:text-gray-400";

async function loadSaved() {
  const res = await fetch("/api/searches");
  const data = await res.json();
  state.searches = data.searches;
  state.missingEnv = data.missing_env;

  const badge = document.querySelector('[data-count="searches"]');
  if (badge) badge.textContent = fa(data.searches.length);

  // جستجویی که ویرایش می‌شد ممکن است حذف شده باشد
  if (editing && !data.searches.find((s) => s.id === editing.id)) setEditing(null);

  if (state.tab === "searches") renderSearches();
}

/** تب «جستجوها» — همان چیزی که بات هر دور اجرا می‌کند. */
function renderSearches() {
  const body = document.getElementById("results-body");
  const empty = document.getElementById("empty-state");
  document.getElementById("table-head").classList.add("hidden");

  empty.classList.toggle("hidden", state.searches.length > 0);
  empty.textContent =
    "هنوز جستجویی ذخیره نشده. در نوار کناری فیلترها را تنظیم کنید و «ذخیره برای اطلاع‌رسانی» را بزنید.";

  const note = state.missingEnv.length
    ? `<tr><td class="td text-warning-600 dark:text-warning-400" colspan="${COLS}">
         برای اطلاع‌رسانی، این‌ها را در .env بگذارید: ${esc(state.missingEnv.join("، "))}
       </td></tr>`
    : "";

  body.innerHTML =
    note +
    state.searches
      .map(
        (s, i) => `<tr class="border-b border-gray-100 dark:border-gray-800" data-sid="${s.id}">
        <td class="td" colspan="${COLS - 1}">
          <span class="${s.enabled ? "text-gray-800 dark:text-white/90" : "text-gray-400 line-through dark:text-gray-600"}">${esc(s.name)}</span>
          ${editing && editing.id === s.id
            ? '<span class="ms-2 rounded-full bg-brand-50 px-2 py-0.5 text-theme-xs text-brand-600 dark:bg-brand-500/15 dark:text-brand-400">در حال ویرایش</span>'
            : ""}
          <span class="block text-theme-xs text-gray-400">
            ${s.enabled ? "فعال" : "متوقف"}
            ${s.last_run_at ? `· آخرین اجرا ${esc(s.last_run_at.slice(0, 16).replace("T", " "))}` : "· هنوز اجرا نشده"}
            ${describeParams(s.params)}
          </span>
        </td>
        <td class="td whitespace-nowrap">
          <div class="flex items-center gap-1.5">
            <button type="button" data-act="toggle" data-idx="${i}" class="${ICON_BTN} hover:border-brand-500 hover:text-brand-500"
              title="${s.enabled ? "موقتاً متوقف کن" : "دوباره فعال کن"}">${s.enabled ? "⏸" : "▶"}</button>
            <button type="button" data-act="edit" data-idx="${i}" class="${ICON_BTN} hover:border-brand-500 hover:text-brand-500"
              title="فیلترها را در نوار کناری باز کن">✎</button>
            <button type="button" data-act="del" data-idx="${i}" class="${ICON_BTN} hover:border-error-500 hover:text-error-500"
              title="حذف">✕</button>
          </div>
        </td>
      </tr>`
      )
      .join("");

  body.querySelectorAll("[data-act]").forEach((btn) => {
    const s = state.searches[Number(btn.dataset.idx)];
    btn.onclick = async () => {
      if (btn.dataset.act === "toggle") {
        await patchSearch(s.id, { enabled: !s.enabled });
      } else if (btn.dataset.act === "edit") {
        setEditing(s);
        renderSearches();
        // فرم در نوار کناری پر شد — دکمه «به‌روزرسانی» را جلوی چشم بیاور
        saveBtn.scrollIntoView({ behavior: "smooth", block: "center" });
      } else if (confirm(`«${s.name}» حذف شود؟`)) {
        await fetch(`/api/searches/${s.id}`, { method: "DELETE" });
        if (editing && editing.id === s.id) setEditing(null);
        await loadSaved();
      }
    };
  });
}

/** خلاصه یک‌خطی از فیلترها، تا بشود جستجوها را از هم تشخیص داد. */
function describeParams(p) {
  const bits = [];
  if (p.polygon?.length) bits.push("محدوده نقشه");
  if (p.district_names?.length) bits.push(esc(p.district_names.join("، ")));
  if (p.exclude_district_names?.length)
    bits.push(`بجز ${esc(p.exclude_district_names.join("، "))}`);
  if (p.size_min || p.size_max)
    bits.push(`${fa(p.size_min ?? 0)}–${p.size_max ? fa(p.size_max) : "∞"}م²`);
  if (p.rooms_min) bits.push(`${fa(p.rooms_min)}+ خواب`);
  if (p.credit_max) bits.push(`ودیعه تا ${million(p.credit_max)}م`);
  return bits.length ? `· ${bits.join(" · ")}` : "";
}

/* ---------- نمایش نتایج ---------- */

function render(out) {

  state.results = out.results;
  rescore();

  document.getElementById("stat-count").textContent = fa(out.divar_count);
  document.getElementById("stat-median").textContent =
    out.median_per_meter ? `${million(out.median_per_meter)} م` : "—";
  document.getElementById("stat-new").textContent = fa(
    out.results.filter((r) => r.is_new).length
  );
  document.getElementById("stat-suspicious").textContent = fa(out.suspicious.length);

  const regionChips = document.getElementById("region-chips");
  regionChips.innerHTML = "";
  (out.districts_in_region || []).forEach((d) => {
    const s = document.createElement("span");
    s.className =
      "rounded-full bg-gray-100 px-2.5 py-1 text-theme-xs text-gray-600 dark:bg-white/5 dark:text-gray-400";
    s.textContent = d.name;
    regionChips.appendChild(s);
  });

  const note = document.getElementById("result-note");
  const warnings = [];
  if (out.complete === false) warnings.push("پوشش ناقص — محدوده را کوچک‌تر کنید یا فیلتر بگذارید");
  if (out.price_rounded_count > 0) warnings.push(`قیمت ${fa(out.price_rounded_count)} آگهی گرد شده است`);
  if (out.from_cache) {
    warnings.push(`از کش، ${out.cache_age_s < 60 ? `${fa(out.cache_age_s)} ثانیه` : "بیش از یک دقیقه"} پیش`);
  }
  note.textContent =
    `${fa(out.results.length)} آگهی از ${fa(out.collected)} جمع‌آوری‌شده` +
    (warnings.length ? ` — ${warnings.join(" · ")}` : "");
  note.className = warnings.length && !out.from_cache
    ? "text-theme-xs text-warning-600 dark:text-warning-400"
    : "text-theme-xs text-gray-500 dark:text-gray-400";

  const countEl = document.querySelector('[data-count="results"]');
  if (countEl) countEl.textContent = fa(out.results.length);

  renderTable();
  renderMarkers();

  const suspCard = document.getElementById("suspicious-card");
  const suspList = document.getElementById("suspicious-list");
  if (out.suspicious.length) {
    suspCard.classList.remove("hidden");
    suspList.innerHTML = out.suspicious
      .map(
        (r) =>
          `<div>متری ${million(r.fre_per_meter)}م · ${fa(r.size)}م² · <a class="text-brand-500 hover:underline" href="${esc(r.url)}" target="_blank" rel="noopener">${esc(r.title)}</a></div>`
      )
      .join("");
  } else {
    suspCard.classList.add("hidden");
  }
}

// برای این ستون‌ها «بیشتر = بهتر»، پس اولین کلیک نزولی باشد
const DESC_FIRST = new Set(["score", "year_built", "image_count"]);

function scorePill(score) {
  const cls =
    score >= 80 ? "bg-success-50 text-success-700 dark:bg-success-500/15 dark:text-success-400"
    : score >= 60 ? "bg-brand-50 text-brand-600 dark:bg-brand-500/15 dark:text-brand-400"
    : score >= 40 ? "bg-gray-100 text-gray-600 dark:bg-white/10 dark:text-gray-300"
    : "bg-error-50 text-error-600 dark:bg-error-500/15 dark:text-error-400";
  return `<span class="inline-block min-w-11 rounded-full px-2 py-0.5 text-center text-theme-sm font-bold ${cls}">${fa(score)}</span>`;
}

function renderTable() {
  const body = document.getElementById("results-body");
  const empty = document.getElementById("empty-state");
  empty.textContent = "محدوده‌ای بکشید یا محله‌ای انتخاب کنید، سپس «جستجو» بزنید.";

  const rows = [...state.results].sort((a, b) => {
    const x = a[state.sortKey], y = b[state.sortKey];
    if (x == null) return 1;
    if (y == null) return -1;
    return state.sortAsc ? x - y : y - x;
  });

  document.querySelectorAll("#table-head th[data-sort]").forEach((th) => {
    const active = th.dataset.sort === state.sortKey;
    th.classList.toggle("text-brand-500", active);
    const arrow = th.querySelector(".sort-arrow");
    if (arrow) arrow.textContent = active ? (state.sortAsc ? "↑" : "↓") : "";
  });

  empty.classList.toggle("hidden", rows.length > 0);
  body.innerHTML = rows
    .map((r, i) => {
      const deal =
        r.vs_market_pct == null ? "text-gray-400"
        : r.vs_market_pct < -10 ? "text-success-600 font-medium"
        : r.vs_market_pct > 10 ? "text-error-500"
        : "text-gray-500";
      const photo =
        r.real_photos === false
          ? '<span class="tag tag-warn" title="آگهی‌دهنده گفته عکس‌ها مال این ملک نیست">تزئینی</span>'
          : r.real_photos === true
            ? '<span class="tag tag-ok">عکس واقعی</span>'
            : `<span class="tag">${fa(r.image_count ?? 0)} عکس</span>`;
      const amen = [
        r.parking ? '<span class="tag tag-ok">پارکینگ</span>' : "",
        r.elevator ? '<span class="tag tag-ok">آسانسور</span>' : "",
        r.storage ? '<span class="tag tag-ok">انباری</span>' : "",
      ].join("");
      const change =
        r.price_change_pct == null || Math.abs(r.price_change_pct) < 0.5
          ? '<span class="text-gray-300">—</span>'
          : `<span class="${r.price_change_pct < 0 ? "text-success-600" : "text-error-500"}">${pct(r.price_change_pct)}</span>`;
      const badge =
        (r.is_new ? '<span class="tag tag-new me-1">جدید</span>' : "") +
        (r.bumped
          ? '<span class="tag tag-warn me-1" title="آگهی قدیمی که دوباره بالا آورده شده — فیلتر «آگهی‌های اخیر» دیوار بر همین پایه است، نه تاریخ انتشار">نردبان</span>'
          : "");
      const metro = r.metro_distance_m == null
        ? "—"
        : `<span class="${r.metro_distance_m <= 800 ? "text-success-600" : ""}">${fa(r.metro_distance_m)}م</span>
           <span class="block text-theme-xs text-gray-400">${esc(r.metro_name)}</span>`;
      const scoreTitle = Object.entries(r.score_parts ?? {})
        .map(([k, v]) => `${WEIGHT_LABELS[k] ?? k}: ${v > 0 ? "+" : ""}${v}`)
        .join(" · ");
      return `<tr data-idx="${i}" data-token="${esc(r.token)}" class="row cursor-pointer border-b border-gray-100 transition hover:bg-brand-50/40 dark:border-gray-800 dark:hover:bg-white/3">
        <td class="td" title="پایه ۵۰ — ${esc(scoreTitle)}">${scorePill(r.score)}</td>
        <td class="td font-semibold">${million(r.fre_per_meter)}</td>
        <td class="td">${million(r.full_rent_equivalent)}
          <span class="block text-theme-xs text-gray-400">${million(r.deposit)} + ${million(r.monthly_rent)}</span></td>
        <td class="td ${deal}">${pct(r.vs_market_pct)}</td>
        <td class="td">${fa(r.size)}م² · ${fa(r.rooms)}خ
          <span class="block text-theme-xs text-gray-400">ساخت ${fa(r.year_built)}</span></td>
        <td class="td"><div class="flex flex-wrap gap-1">${amen}${photo}</div></td>
        <td class="td text-theme-xs">${metro}</td>
        <td class="td">${change}</td>
        <td class="td max-w-64">${badge}<a class="text-gray-800 hover:text-brand-500 dark:text-white/90" href="${esc(r.url)}" target="_blank" rel="noopener" title="${esc(r.title)}">${esc((r.title ?? "").slice(0, 40))}</a>
          <span class="block text-theme-xs text-gray-400">${esc(r.district ?? "")}</span></td>
        <td class="td whitespace-nowrap">
          <button type="button" data-act="bookmark" data-token="${esc(r.token)}" class="row-action ${r.bookmarked ? "text-warning-500" : ""}" title="بوکمارک">${r.bookmarked ? "★" : "☆"}</button>
          <button type="button" data-act="trash" data-token="${esc(r.token)}" class="row-action hover:text-error-500" title="حذف به سطل آشغال">🗑</button>
        </td>
      </tr>`;
    })
    .join("");

  body.querySelectorAll("button[data-act]").forEach((btn) => {
    btn.onclick = async (e) => {
      e.stopPropagation();
      const kind = btn.dataset.act;
      const token = btn.dataset.token;
      if (kind === "trash") {
        await fetch("/api/marks/trash", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ token }),
        });
        // فوری از نتایج حذف شود تا کاربر دوباره نبیندش
        state.results = state.results.filter((x) => x.token !== token);
        renderTable();
        renderMarkers();
      } else {
        const r = state.results.find((x) => x.token === token);
        const on = !r?.bookmarked;
        await fetch(on ? "/api/marks/bookmark" : `/api/marks/bookmark/${encodeURIComponent(token)}`, {
          method: on ? "POST" : "DELETE",
          headers: { "Content-Type": "application/json" },
          body: on ? JSON.stringify({ token }) : undefined,
        });
        if (r) r.bookmarked = on;
        renderTable();
      }
      loadCounts();
    };
  });

  body.querySelectorAll("tr[data-idx]").forEach((tr) => {
    const r = rows[Number(tr.dataset.idx)];
    tr.onclick = (e) => {
      if (e.target.tagName === "A" || e.target.dataset.act) return;
      if (r.lat) map.setView([r.lat, r.lon], 16);
      toggleDetail(tr, r);
    };
    // ردیف ↔ پین: hover روی ردیف، پین را برجسته می‌کند
    tr.onmouseenter = () => highlightMarker(r.token, true);
    tr.onmouseleave = () => highlightMarker(r.token, false);
  });
}

function highlightMarker(token, on) {
  const m = state.markerByToken.get(token);
  if (!m) return;
  m.setStyle({ radius: on ? 11 : 6, weight: on ? 3 : 1, fillOpacity: on ? 1 : 0.7 });
  if (on) m.bringToFront();
}

/* ---------- جزئیات تنبل ---------- */

const COLS = 10;

async function toggleDetail(tr, r) {
  const next = tr.nextElementSibling;
  if (next && next.classList.contains("detail-row")) {
    next.remove();
    return;
  }
  document.querySelectorAll(".detail-row").forEach((el) => el.remove());

  const row = document.createElement("tr");
  row.className = "detail-row bg-gray-50 dark:bg-white/3";
  row.innerHTML = `<td colspan="${COLS}" class="px-4 py-3 text-theme-sm text-gray-500">در حال گرفتن جزئیات ...</td>`;
  tr.after(row);

  try {
    const res = await fetch(`/api/post/${encodeURIComponent(r.token)}`);
    if (!res.ok) throw new Error("جزئیات در دسترس نیست");
    const d = await res.json();
    const f = d.fields || {};
    const feats = Object.entries(d.features || {})
      .map(([k, v]) => `<span class="tag ${v ? "tag-ok" : ""}">${esc(k)}${v ? "" : " ✕"}</span>`)
      .join("");
    const img = r.image_url
      ? `<img src="${esc(r.image_url)}" alt="" class="h-28 w-40 rounded-lg object-cover" loading="lazy" />`
      : "";
    row.innerHTML = `<td colspan="${COLS}" class="px-4 py-4">
      <div class="flex flex-col gap-4 md:flex-row">
        ${img}
        <div class="grid flex-1 gap-3 md:grid-cols-3">
          <div class="text-theme-sm text-gray-700 dark:text-gray-300">
            <div><b>منتشر شده:</b> ${esc(d.published_text ?? "—")}${r.bumped ? " (نردبان‌شده)" : ""}</div>
            <div><b>طبقه:</b> ${esc(f["طبقه"] ?? "—")}</div>
            <div><b>ساخت:</b> ${esc(f["ساخت"] ?? "—")}</div>
            <div><b>ودیعه و اجاره:</b> ${esc(f["ودیعه و اجاره"] ?? "—")}</div>
            <div><b>عکس‌ها:</b> ${esc(f["تصویر‌ها برای همین ملک است؟"] ?? "—")}</div>
          </div>
          <div class="flex flex-wrap content-start gap-1">${feats || "—"}</div>
          <div class="text-theme-xs leading-6 whitespace-pre-line text-gray-600 dark:text-gray-400">${esc((d.description ?? "").slice(0, 500))}</div>
        </div>
      </div>
    </td>`;
  } catch (err) {
    row.innerHTML = `<td colspan="${COLS}" class="px-4 py-3 text-theme-sm text-error-500">${esc(err.message)}</td>`;
  }
}

function renderMarkers() {
  state.markers.clearLayers();
  state.markerByToken.clear();
  state.results.forEach((r) => {
    if (!r.lat) return;
    const color =
      r.vs_market_pct == null ? "#98a2b3"
      : r.vs_market_pct < -15 ? "#12b76a"
      : r.vs_market_pct > 15 ? "#f04438"
      : "#f79009";
    const m = L.circleMarker([r.lat, r.lon], {
      radius: 6, color, fillColor: color, fillOpacity: 0.7, weight: 1,
    })
      .bindPopup(
        `<div style="font-family:Vazirmatn,Tahoma;direction:rtl;text-align:right">
          <b>${esc(r.title)}</b><br>
          امتیاز ${fa(r.score)} · متری ${million(r.fre_per_meter)}م · ${fa(r.size)}م² · ${fa(r.rooms)} خواب<br>
          ${pct(r.vs_market_pct)} نسبت به بازار<br>
          <a href="${esc(r.url)}" target="_blank" rel="noopener">دیدن در دیوار</a>
        </div>`
      )
      .on("click", () => {
        // پین → ردیف: کلیک روی پین، ردیف را می‌آورد و لحظه‌ای روشن می‌کند
        const tr = document.querySelector(`tr[data-token="${CSS.escape(r.token)}"]`);
        if (!tr) return;
        tr.scrollIntoView({ block: "center", behavior: "smooth" });
        tr.classList.add("bg-brand-50");
        setTimeout(() => tr.classList.remove("bg-brand-50"), 1500);
      })
      .addTo(state.markers);
    state.markerByToken.set(r.token, m);
  });
}

document.querySelectorAll("#table-head th[data-sort]").forEach((th) => {
  th.style.cursor = "pointer";
  if (!th.querySelector(".sort-arrow")) {
    const arrow = document.createElement("span");
    arrow.className = "sort-arrow ms-1 text-theme-xs";
    th.appendChild(arrow);
  }
  th.onclick = () => {
    const key = th.dataset.sort;
    if (state.sortKey === key) {
      state.sortAsc = !state.sortAsc;
    } else {
      state.sortKey = key;
      state.sortAsc = !DESC_FIRST.has(key);
    }
    renderTable();
  };
});

/* ---------- تب‌ها: نتایج / بوکمارک / سطل آشغال ---------- */

async function loadCounts() {
  for (const kind of ["bookmark", "trash"]) {
    const res = await fetch(`/api/marks/${kind}`);
    const data = await res.json();
    const el = document.querySelector(`[data-count="${kind}"]`);
    if (el) el.textContent = fa(data.items.length);
  }
}

async function showTab(tab) {
  state.tab = tab;
  document.querySelectorAll(".tab-btn").forEach((b) =>
    b.classList.toggle("active", b.dataset.tab === tab)
  );
  const body = document.getElementById("results-body");
  const empty = document.getElementById("empty-state");
  const head = document.getElementById("table-head");

  if (tab === "results") {
    head.classList.remove("hidden");
    renderTable();
    return;
  }

  if (tab === "searches") {
    await loadSaved();
    renderSearches();
    return;
  }

  head.classList.add("hidden");
  const res = await fetch(`/api/marks/${tab}`);
  const { items } = await res.json();
  empty.classList.toggle("hidden", items.length > 0);
  empty.textContent =
    tab === "trash" ? "سطل آشغال خالی است." : "هنوز چیزی بوکمارک نکرده‌اید.";

  const label = tab === "trash" ? "بازگرداندن" : "حذف بوکمارک";
  body.innerHTML = items
    .map(
      (m) => `<tr class="border-b border-gray-100 dark:border-gray-800">
        <td class="td" colspan="${COLS - 1}">
          <a class="text-gray-800 hover:text-brand-500 dark:text-white/90" href="https://divar.ir/v/${esc(m.token)}" target="_blank" rel="noopener">${esc(m.title ?? m.token)}</a>
          <span class="block text-theme-xs text-gray-400">
            ${esc(m.district ?? "")} ${m.size ? `· ${fa(m.size)}م²` : ""}
            ${m.deposit != null ? `· ودیعه ${million(m.deposit)}م` : ""}
            ${m.monthly_rent != null ? `+ اجاره ${million(m.monthly_rent)}م` : ""}
            · ${esc((m.marked_at ?? "").slice(0, 10))}
          </span>
        </td>
        <td class="td whitespace-nowrap">
          <button type="button" data-restore="${esc(m.token)}" class="rounded-lg border border-gray-300 px-2.5 py-1 text-theme-xs text-gray-600 hover:border-brand-500 hover:text-brand-500 dark:border-gray-700 dark:text-gray-400">${label}</button>
        </td>
      </tr>`
    )
    .join("");

  body.querySelectorAll("[data-restore]").forEach((btn) => {
    btn.onclick = async () => {
      await fetch(`/api/marks/${tab}/${encodeURIComponent(btn.dataset.restore)}`, { method: "DELETE" });
      await loadCounts();
      showTab(tab);
    };
  });
}

document.querySelectorAll(".tab-btn").forEach((btn) => {
  btn.onclick = () => showTab(btn.dataset.tab);
});

/* ---------- تنظیمات بات (بات هر دقیقه از دیتابیس می‌خواند) ---------- */

const setInterval_ = document.getElementById("set-interval");
const setThreshold = document.getElementById("set-threshold");
const botStatus = document.getElementById("bot-status");

function renderBotStatus(s) {
  setInterval_.value = s.interval_minutes;
  setThreshold.value = s.score_threshold;
  const parts = [];
  if (s.last_ok_run?.finished_at) {
    const mins = Math.round((Date.now() - new Date(s.last_ok_run.finished_at)) / 60000);
    parts.push(`آخرین اجرای موفق ${fa(mins)} دقیقه پیش، ${fa(s.last_ok_run.sent ?? 0)} پیام`);
  } else {
    parts.push("بات هنوز اجرایی نداشته");
  }
  if (s.last_run && !s.last_run.ok && s.last_run.finished_at) {
    parts.push(`⚠️ آخرین اجرا خطا داد: ${(s.last_run.error ?? "").slice(0, 60)}`);
  }
  if (s.muted_until) parts.push(`🔇 ساکت تا ${s.muted_until.slice(0, 16)}`);
  botStatus.textContent = parts.join(" · ");
}

async function loadSettings() {
  try {
    const res = await fetch("/api/settings");
    renderBotStatus(await res.json());
  } catch {
    botStatus.textContent = "";
  }
}

async function saveSettings() {
  const body = {
    interval_minutes: Number(setInterval_.value) || null,
    score_threshold: Number(setThreshold.value),
  };
  const res = await fetch("/api/settings", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  renderBotStatus(await res.json());
}

setInterval_.addEventListener("change", saveSettings);
setThreshold.addEventListener("change", saveSettings);

/* ---------- آخرین جستجو ---------- */

// دفعه بعد که پنل را باز می‌کنید همان فیلترها آماده‌اند. فقط در همین مرورگر
// می‌ماند؛ چیزی سمت سرور ذخیره نمی‌شود.
const LAST_SEARCH_KEY = "divar:last-search";

function rememberSearch(payload) {
  try {
    const { refresh, ...rest } = payload;
    localStorage.setItem(LAST_SEARCH_KEY, JSON.stringify(rest));
  } catch {
    // حالت ناشناس مرورگر یا فضای پر — فراموش‌کاری اینجا ایرادی ندارد
  }
}

function restoreLastSearch() {
  let saved = null;
  try {
    saved = JSON.parse(localStorage.getItem(LAST_SEARCH_KEY) || "null");
  } catch {
    saved = null;
  }
  if (!saved) return;
  applyPayload(saved);
  setProgress("فیلترهای آخرین جستجو بازگردانده شد — «جستجو» را بزنید.");
}

restoreLastSearch();
loadSaved();
loadCounts();
loadSettings();
