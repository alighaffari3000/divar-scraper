/* پنل جستجوی آگهی‌های اجاره — نقشه، فیلترها، جدول نتایج */

const fa = (n) => (n == null ? "—" : n.toLocaleString("fa-IR"));
const million = (v) => (v == null ? "—" : fa(Math.round(v / 1e6)));
const pct = (v) => (v == null ? "—" : `${v > 0 ? "+" : ""}${fa(Math.round(v))}٪`);

let state = {
  polygon: null,
  districts: [], // {id, name}
  results: [],
  sortKey: "fre_per_meter",
  sortAsc: true,
  markers: null,
};

/* ---------- نقشه ---------- */

const map = L.map("map").setView([35.7219, 51.3347], 12);
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
  state.polygon = e.layer
    .getLatLngs()[0]
    .map((p) => [p.lng, p.lat]);
  setProgress(`محدوده انتخاب شد (${fa(state.polygon.length)} نقطه)`);
});

map.on(L.Draw.Event.DELETED, () => {
  state.polygon = null;
});

/* ---------- انتخاب محله ---------- */

const districtInput = document.getElementById("district-search");
const suggestionBox = document.getElementById("district-suggestions");
const chipBox = document.getElementById("district-chips");

let suggestTimer = null;
districtInput.addEventListener("input", () => {
  clearTimeout(suggestTimer);
  const q = districtInput.value.trim();
  if (q.length < 2) {
    suggestionBox.innerHTML = "";
    return;
  }
  suggestTimer = setTimeout(async () => {
    const res = await fetch(`/api/districts?q=${encodeURIComponent(q)}`);
    const list = await res.json();
    suggestionBox.innerHTML = "";
    list.forEach((d) => {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className =
        "rounded-lg border border-gray-200 px-3 py-1.5 text-right text-theme-xs text-gray-700 hover:border-brand-500 hover:text-brand-500 dark:border-gray-700 dark:text-gray-400";
      btn.textContent = d.name;
      btn.onclick = () => addDistrict(d);
      suggestionBox.appendChild(btn);
    });
  }, 250);
});

function addDistrict(d) {
  if (!state.districts.find((x) => x.id === d.id)) state.districts.push(d);
  districtInput.value = "";
  suggestionBox.innerHTML = "";
  renderChips();
}

function renderChips() {
  chipBox.innerHTML = "";
  state.districts.forEach((d) => {
    const chip = document.createElement("span");
    chip.className =
      "inline-flex items-center gap-1.5 rounded-full bg-brand-50 px-3 py-1 text-theme-xs text-brand-600 dark:bg-brand-500/15 dark:text-brand-400";
    chip.innerHTML = `${d.name} <button type="button" class="text-brand-400 hover:text-error-500">✕</button>`;
    chip.querySelector("button").onclick = () => {
      state.districts = state.districts.filter((x) => x.id !== d.id);
      renderChips();
    };
    chipBox.appendChild(chip);
  });
}

/* ---------- دکمه‌های اتاق ---------- */

document.querySelectorAll(".room-btn").forEach((btn) => {
  btn.onclick = () => {
    document.querySelectorAll(".room-btn").forEach((b) => b.classList.remove("active"));
    btn.classList.add("active");
    document.querySelector('[name="rooms_min"]').value = btn.dataset.rooms;
  };
});

/* ---------- اجرای جستجو ---------- */

const form = document.getElementById("filters");
const runBtn = document.getElementById("run-btn");
const progressEl = document.getElementById("progress");

function setProgress(text) {
  progressEl.textContent = text || "";
}

let forceRefresh = false;
document.getElementById("refresh-btn").onclick = () => {
  forceRefresh = true;
  form.requestSubmit();
};

form.addEventListener("submit", async (e) => {
  e.preventDefault();
  const data = new FormData(form);
  const num = (k) => {
    const v = data.get(k);
    return v ? Number(v) : null;
  };

  const payload = {
    polygon: state.polygon,
    district_ids: state.districts.map((d) => d.id),
    size_min: num("size_min"),
    size_max: num("size_max"),
    rooms_min: num("rooms_min"),
    // کاربر میلیون وارد می‌کند، API تومان می‌خواهد
    credit_max: num("credit_max") ? num("credit_max") * 1e6 : null,
    rent_max: num("rent_max") ? num("rent_max") * 1e6 : null,
    parking: data.get("parking") === "on",
    elevator: data.get("elevator") === "on",
    storage: data.get("storage") === "on",
    owner_only: data.get("owner_only") === "on",
    real_photos: data.get("real_photos") === "on",
    has_video: data.get("has_video") === "on",

    // فیلترهای بیشتر — همه اختیاری؛ خالی یعنی اعمال نشود
    balcony: data.get("balcony") === "on",
    rebuilt: data.get("rebuilt") === "on",
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
    convertible_only: data.get("convertible_only") === "on",
    below_median_only: data.get("below_median_only") === "on",
    hide_roommate: data.get("hide_roommate") === "on",
    refresh: forceRefresh,
  };

  state.lastPayload = payload;
  runBtn.disabled = true;
  runBtn.textContent = "در حال جستجو ...";
  setProgress("شروع ...");

  try {
    const res = await fetch("/api/search", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!res.ok) throw new Error(await res.text());
    const out = await res.json();
    render(out);
    setProgress("");
    saveBtn.disabled = false;
  } catch (err) {
    setProgress(`خطا: ${err.message}`);
  } finally {
    forceRefresh = false;
    runBtn.disabled = false;
    runBtn.textContent = "جستجو";
  }
});

/* ---------- جستجوهای ذخیره‌شده ---------- */

const saveBtn = document.getElementById("save-btn");
const savedBox = document.getElementById("saved-box");

saveBtn.onclick = async () => {
  if (!state.lastPayload) return;
  const name = prompt("نامی برای این جستجو:");
  if (!name) return;
  saveBtn.disabled = true;
  try {
    const res = await fetch("/api/searches", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name, params: state.lastPayload }),
    });
    if (!res.ok) throw new Error(await res.text());
    await loadSaved();
  } catch (err) {
    setProgress(`ذخیره نشد: ${err.message}`);
  } finally {
    saveBtn.disabled = false;
  }
};

async function loadSaved() {
  const res = await fetch("/api/searches");
  const data = await res.json();
  savedBox.innerHTML = "";

  if (data.missing_env.length) {
    const warn = document.createElement("p");
    warn.className = "text-theme-xs text-warning-600 dark:text-warning-400";
    warn.textContent =
      `برای اطلاع‌رسانی، این‌ها را در .env بگذارید: ${data.missing_env.join("، ")}`;
    savedBox.appendChild(warn);
  } else if (!data.interval_hours) {
    const hint = document.createElement("p");
    hint.className = "text-theme-xs text-gray-500 dark:text-gray-400";
    hint.textContent =
      "تلگرام آماده است. برای اجرای خودکار NOTIFY_INTERVAL_HOURS را در .env بگذارید.";
    savedBox.appendChild(hint);
  }

  data.searches.forEach((s) => {
    const row = document.createElement("div");
    row.className =
      "flex items-center justify-between rounded-lg border border-gray-200 px-3 py-2 text-theme-xs text-gray-700 dark:border-gray-700 dark:text-gray-400";
    row.innerHTML = `<span>${s.name}</span><button type="button" class="text-gray-400 hover:text-error-500">✕</button>`;
    row.querySelector("button").onclick = async () => {
      await fetch(`/api/searches/${s.id}`, { method: "DELETE" });
      loadSaved();
    };
    savedBox.appendChild(row);
  });
}

loadSaved();

/* ---------- نمایش نتایج ---------- */

function render(out) {
  state.results = out.results;

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
  note.textContent =
    `${fa(out.results.length)} آگهی پس از فیلترها — از ${fa(out.collected)} جمع‌آوری‌شده`;
  note.className = out.complete === false
    ? "text-theme-xs text-warning-600 dark:text-warning-400"
    : "text-theme-xs text-gray-500 dark:text-gray-400";
  if (out.complete === false) {
    note.textContent += " — پوشش ناقص، محدوده را کوچک‌تر کنید یا فیلتر بیشتری بگذارید";
  }
  if (out.from_cache) {
    note.textContent +=
      ` — از کش، ${out.cache_age_s < 60 ? `${fa(out.cache_age_s)} ثانیه` : "بیش از یک دقیقه"} پیش`;
  }
  if (out.price_rounded_count > 0) {
    note.className = "text-theme-xs text-warning-600 dark:text-warning-400";
    note.textContent +=
      ` — قیمت ${fa(out.price_rounded_count)} آگهی گرد شده است (دقیق نیست)`;
  }

  renderTable();
  renderMarkers();

  const suspCard = document.getElementById("suspicious-card");
  const suspList = document.getElementById("suspicious-list");
  if (out.suspicious.length) {
    suspCard.classList.remove("hidden");
    suspList.innerHTML = out.suspicious
      .map(
        (r) =>
          `<div>متری ${million(r.fre_per_meter)}م · ${fa(r.size)}م² · <a class="text-brand-500 hover:underline" href="${r.url}" target="_blank" rel="noopener">${r.title ?? ""}</a></div>`
      )
      .join("");
  } else {
    suspCard.classList.add("hidden");
  }
}

function renderTable() {
  const body = document.getElementById("results-body");
  const empty = document.getElementById("empty-state");

  const rows = [...state.results].sort((a, b) => {
    const x = a[state.sortKey], y = b[state.sortKey];
    if (x == null) return 1;
    if (y == null) return -1;
    return state.sortAsc ? x - y : y - x;
  });

  empty.classList.toggle("hidden", rows.length > 0);
  body.innerHTML = rows
    .map((r, i) => {
      const deal =
        r.vs_market_pct == null
          ? ""
          : r.vs_market_pct < -10
            ? "text-success-600"
            : r.vs_market_pct > 10
              ? "text-error-500"
              : "text-gray-500";
      const photo =
        r.real_photos === false
          ? '<span class="text-warning-600" title="آگهی‌دهنده گفته عکس‌ها مال این ملک نیست">تزئینی</span>'
          : r.real_photos === true
            ? '<span class="text-success-600">واقعی</span>'
            : `${fa(r.image_count ?? 0)} عکس`;
      const amen = [
        r.parking ? "پارکینگ" : null,
        r.elevator ? "آسانسور" : null,
        r.storage ? "انباری" : null,
      ].filter(Boolean).join(" · ") || "—";
      const change =
        r.price_change_pct == null || Math.abs(r.price_change_pct) < 0.5
          ? "—"
          : `<span class="${r.price_change_pct < 0 ? "text-success-600" : "text-error-500"}">${pct(r.price_change_pct)}</span>`;
      const badge = r.is_new
        ? '<span class="me-1.5 rounded-full bg-success-50 px-2 py-0.5 text-theme-xs text-success-700 dark:bg-success-500/15 dark:text-success-400">جدید</span>'
        : "";
      const metro = r.metro_distance_m == null
        ? "—"
        : `${fa(r.metro_distance_m)}م<span class="text-gray-400"> ${r.metro_name ?? ""}</span>`;
      const scoreTitle = Object.entries(r.score_parts ?? {})
        .map(([k, v]) => `${({deal: "قیمت", age: "نوسازی", metro: "مترو"})[k] ?? k}: ${v > 0 ? "+" : ""}${v}`)
        .join(" · ");
      return `<tr data-idx="${i}" class="border-b border-gray-100 hover:bg-gray-50 dark:border-gray-800 dark:hover:bg-white/3">
        <td class="td font-bold" title="پایه ۵۰ — ${scoreTitle}">${fa(r.score)}</td>
        <td class="td font-medium">${million(r.fre_per_meter)}</td>
        <td class="td">${million(r.full_rent_equivalent)}</td>
        <td class="td ${deal}">${pct(r.vs_market_pct)}</td>
        <td class="td">${fa(r.size)}</td>
        <td class="td">${fa(r.rooms)}</td>
        <td class="td">${fa(r.year_built)}</td>
        <td class="td text-theme-xs">${amen}</td>
        <td class="td text-theme-xs">${photo}</td>
        <td class="td text-theme-xs">${metro}</td>
        <td class="td">${change}</td>
        <td class="td">${badge}<a class="text-brand-500 hover:underline" href="${r.url}" target="_blank" rel="noopener">${(r.title ?? "").slice(0, 34)}</a></td>
        <td class="td whitespace-nowrap">
          <button type="button" data-act="bookmark" data-token="${r.token}" class="row-action ${r.bookmarked ? "text-warning-500" : ""}" title="بوکمارک">${r.bookmarked ? "★" : "☆"}</button>
          <button type="button" data-act="trash" data-token="${r.token}" class="row-action hover:text-error-500" title="حذف به سطل آشغال">🗑</button>
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
        await fetch(on ? "/api/marks/bookmark" : `/api/marks/bookmark/${token}`, {
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
    tr.onclick = (e) => {
      if (e.target.tagName === "A" || e.target.dataset.act) return;
      const r = rows[Number(tr.dataset.idx)];
      if (r.lat) map.setView([r.lat, r.lon], 16);
      toggleDetail(tr, r);
    };
  });
}

/* ---------- جزئیات تنبل ---------- */

async function toggleDetail(tr, r) {
  const next = tr.nextElementSibling;
  if (next && next.classList.contains("detail-row")) {
    next.remove();
    return;
  }
  document.querySelectorAll(".detail-row").forEach((el) => el.remove());

  const row = document.createElement("tr");
  row.className = "detail-row bg-gray-50 dark:bg-white/3";
  row.innerHTML = `<td colspan="13" class="px-4 py-3 text-theme-sm text-gray-500">در حال گرفتن جزئیات ...</td>`;
  tr.after(row);

  try {
    const res = await fetch(`/api/post/${r.token}`);
    if (!res.ok) throw new Error("جزئیات در دسترس نیست");
    const d = await res.json();
    const f = d.fields || {};
    const feats = Object.entries(d.features || {})
      .map(([k, v]) => `${k}: ${v ? "دارد" : "ندارد"}`)
      .join(" · ");
    row.innerHTML = `<td colspan="13" class="px-4 py-4">
      <div class="grid gap-3 md:grid-cols-3">
        <div class="text-theme-sm text-gray-700 dark:text-gray-300">
          <div><b>طبقه:</b> ${f["طبقه"] ?? "—"}</div>
          <div><b>ساخت:</b> ${f["ساخت"] ?? "—"}</div>
          <div><b>ودیعه و اجاره:</b> ${f["ودیعه و اجاره"] ?? "—"}</div>
        </div>
        <div class="text-theme-xs text-gray-600 dark:text-gray-400">${feats || "—"}</div>
        <div class="text-theme-xs leading-6 whitespace-pre-line text-gray-600 dark:text-gray-400">${(d.description ?? "").slice(0, 400)}</div>
      </div>
    </td>`;
  } catch (err) {
    row.innerHTML = `<td colspan="13" class="px-4 py-3 text-theme-sm text-error-500">${err.message}</td>`;
  }
}

function renderMarkers() {
  state.markers.clearLayers();
  state.results.forEach((r) => {
    if (!r.lat) return;
    const color =
      r.vs_market_pct == null
        ? "#98a2b3"
        : r.vs_market_pct < -15
          ? "#12b76a"
          : r.vs_market_pct > 15
            ? "#f04438"
            : "#f79009";
    L.circleMarker([r.lat, r.lon], {
      radius: 6,
      color,
      fillColor: color,
      fillOpacity: 0.7,
      weight: 1,
    })
      .bindPopup(
        `<div style="font-family:Vazirmatn,Tahoma;direction:rtl;text-align:right">
          <b>${r.title ?? ""}</b><br>
          متری ${million(r.fre_per_meter)}م · ${fa(r.size)}م² · ${fa(r.rooms)} خواب<br>
          ${pct(r.vs_market_pct)} نسبت به بازار<br>
          <a href="${r.url}" target="_blank" rel="noopener">دیدن در دیوار</a>
        </div>`
      )
      .addTo(state.markers);
  });
}

document.querySelectorAll("#table-head th[data-sort]").forEach((th) => {
  th.style.cursor = "pointer";
  th.onclick = () => {
    const key = th.dataset.sort;
    state.sortAsc = state.sortKey === key ? !state.sortAsc : true;
    state.sortKey = key;
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
  document.querySelectorAll(".tab-btn").forEach((b) =>
    b.classList.toggle("active", b.dataset.tab === tab)
  );
  const body = document.getElementById("results-body");
  const empty = document.getElementById("empty-state");

  if (tab === "results") {
    renderTable();
    return;
  }

  const res = await fetch(`/api/marks/${tab}`);
  const { items } = await res.json();
  empty.classList.toggle("hidden", items.length > 0);
  empty.textContent =
    tab === "trash" ? "سطل آشغال خالی است." : "هنوز چیزی بوکمارک نکرده‌اید.";

  const label = tab === "trash" ? "بازگرداندن" : "حذف بوکمارک";
  body.innerHTML = items
    .map(
      (m) => `<tr class="border-b border-gray-100 dark:border-gray-800">
        <td class="td" colspan="9">
          <a class="text-brand-500 hover:underline" href="https://divar.ir/v/${m.token}" target="_blank" rel="noopener">${m.title ?? m.token}</a>
          <span class="text-theme-xs text-gray-400">
            ${m.district ?? ""} ${m.size ? `· ${fa(m.size)}م²` : ""}
            ${m.deposit != null ? `· ودیعه ${million(m.deposit)}م` : ""}
            ${m.monthly_rent != null ? `+ اجاره ${million(m.monthly_rent)}م` : ""}
          </span>
        </td>
        <td class="td whitespace-nowrap">
          <button type="button" data-restore="${m.token}" class="rounded-lg border border-gray-300 px-2.5 py-1 text-theme-xs text-gray-600 hover:border-brand-500 hover:text-brand-500 dark:border-gray-700 dark:text-gray-400">${label}</button>
        </td>
      </tr>`
    )
    .join("");

  body.querySelectorAll("[data-restore]").forEach((btn) => {
    btn.onclick = async () => {
      await fetch(`/api/marks/${tab}/${btn.dataset.restore}`, { method: "DELETE" });
      await loadCounts();
      showTab(tab);
    };
  });
}

document.querySelectorAll(".tab-btn").forEach((btn) => {
  btn.onclick = () => showTab(btn.dataset.tab);
});

loadCounts();
