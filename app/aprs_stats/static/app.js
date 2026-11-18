/* aprs-stats – Oberfläche */
"use strict";

const PALETTE = ["#2563eb", "#dc2626", "#16a34a", "#d97706", "#7c3aed", "#0891b2", "#db2777", "#65a30d",
                 "#ea580c", "#4f46e5", "#0d9488", "#be123c"];
const TRIP_GAP_MS = 20 * 60 * 1000;
const fmtNum = new Intl.NumberFormat("de-CH", { maximumFractionDigits: 1 });
const fmtInt = new Intl.NumberFormat("de-CH");
const fmtDT = new Intl.DateTimeFormat("de-CH", { dateStyle: "short", timeStyle: "short" });
const fmtD = new Intl.DateTimeFormat("de-CH", { dateStyle: "medium" });

const state = {
  stations: [],
  selected: new Set(load("selected", [])),
  range: load("range", "30d"),
  from: null, to: null,
  tab: "map",
  fitNext: true,
};

/* ---------- Hilfen ---------- */
function load(k, d) { try { const v = localStorage.getItem("aprs-stats:" + k); return v ? JSON.parse(v) : d; } catch { return d; } }
function save(k, v) { try { localStorage.setItem("aprs-stats:" + k, JSON.stringify(v)); } catch { /* egal */ } }
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
function esc(s) { return String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])); }
function dt(v) { return v ? fmtDT.format(new Date(v)) : "–"; }
function dur(sec) { const h = Math.floor(sec / 3600), m = Math.round((sec % 3600) / 60); return h ? `${h} h ${m} min` : `${m} min`; }
function ago(v) {
  if (!v) return "–";
  const s = (Date.now() - new Date(v)) / 1000;
  if (s < 90) return "gerade eben";
  if (s < 3600) return `vor ${Math.round(s / 60)} min`;
  if (s < 86400 * 2) return `vor ${Math.round(s / 3600)} h`;
  return `vor ${Math.round(s / 86400)} Tagen`;
}

async function api(path, opts = {}) {
  const r = await fetch("api/" + path, opts);
  if (!r.ok) {
    let msg = r.statusText;
    try { const j = await r.json(); msg = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail); } catch { /* */ }
    throw new Error(msg);
  }
  return r.json();
}

function devices() { return state.stations.filter(s => s.ssid !== "*"); }
function colorOf(call) {
  const list = devices();
  const s = list.find(d => d.full === call);
  if (s && s.color) return s.color;
  const i = list.findIndex(d => d.full === call);
  return PALETTE[(i >= 0 ? i : hash(call)) % PALETTE.length];
}
function hash(s) { let h = 0; for (const c of s) h = (h * 31 + c.charCodeAt(0)) >>> 0; return h; }
function labelOf(call) { const s = devices().find(d => d.full === call); return s && s.label ? `${call} (${s.label})` : call; }

function query(extra = {}) {
  const p = new URLSearchParams();
  const sel = [...state.selected].filter(c => devices().some(d => d.full === c));
  if (sel.length && sel.length < devices().length) p.set("calls", sel.join(","));
  if (state.from) p.set("from", state.from.toISOString());
  if (state.to) p.set("to", state.to.toISOString());
  for (const [k, v] of Object.entries(extra)) p.set(k, v);
  return p.toString();
}

function computeRange() {
  const r = state.range;
  if (r === "custom") {
    const f = $("#from").value, t = $("#to").value;
    state.from = f ? new Date(f + "T00:00:00") : null;
    state.to = t ? new Date(new Date(t + "T00:00:00").getTime() + 86400000) : null;
  } else if (r === "all") {
    state.from = state.to = null;
  } else {
    const days = parseInt(r, 10);
    state.from = new Date(Date.now() - days * 86400000);
    state.to = null;
  }
}
function isLiveRange() { return state.range !== "custom" || !state.to || state.to > new Date(); }

/* ---------- Seitenleiste ---------- */
function renderDevices() {
  const box = $("#devices");
  const list = devices();
  if (!list.length) {
    box.innerHTML = `<p class="muted">Noch keine Geräte. Unter <b>Stationen &amp; Import</b> ein Rufzeichen eintragen.</p>`;
    return;
  }
  const groups = {};
  for (const d of list) (groups[d.callsign] ||= []).push(d);
  const wild = new Set(state.stations.filter(s => s.ssid === "*" && s.track).map(s => s.callsign));
  box.innerHTML = Object.entries(groups).map(([base, ds]) => {
    const allOn = ds.every(d => state.selected.has(d.full));
    return `<div class="dev-group">
      <label><input type="checkbox" data-group="${esc(base)}" ${allOn ? "checked" : ""}> ${esc(base)}
        ${wild.has(base) ? `<span class="wild">alle SSIDs live</span>` : ""}</label>
      ${ds.map(d => `<label class="dev" title="${esc(d.full)}">
        <input type="checkbox" data-call="${esc(d.full)}" ${state.selected.has(d.full) ? "checked" : ""}>
        <span class="dot" style="background:${colorOf(d.full)}"></span>
        <span>${esc(d.ssid ? "-" + d.ssid : "(ohne)")}</span>
        <span class="lbl">${esc(d.label || "")}</span>
        <span class="cnt" title="Positionen">${fmtInt.format(d.points || 0)}</span>
      </label>`).join("")}
    </div>`;
  }).join("");
  const grpBoxes = $$("input[data-group]", box);
  for (const g of grpBoxes) {
    const ds = groups[g.dataset.group];
    const n = ds.filter(d => state.selected.has(d.full)).length;
    g.indeterminate = n > 0 && n < ds.length;
  }
  $("#sel-hint").textContent = state.selected.size ? `${state.selected.size} von ${list.length} Geräten gewählt.` : "Keine Auswahl = alle Geräte.";
  $("#call-list").innerHTML = list.map(d => `<option value="${esc(d.full)}">`).join("");
}

$("#devices").addEventListener("change", e => {
  const t = e.target;
  if (t.dataset.call) {
    t.checked ? state.selected.add(t.dataset.call) : state.selected.delete(t.dataset.call);
  } else if (t.dataset.group) {
    for (const d of devices().filter(d => d.callsign === t.dataset.group)) {
      t.checked ? state.selected.add(d.full) : state.selected.delete(d.full);
    }
  }
  selectionChanged();
});
$("#select-all").onclick = () => { devices().forEach(d => state.selected.add(d.full)); selectionChanged(); };
$("#select-none").onclick = () => { state.selected.clear(); selectionChanged(); };
function selectionChanged() { save("selected", [...state.selected]); renderDevices(); state.fitNext = true; refresh(); }

$("#ranges").addEventListener("click", e => {
  const b = e.target.closest("button"); if (!b) return;
  setRange(b.dataset.range);
});
function setRange(r) {
  state.range = r; save("range", r);
  $$("#ranges button").forEach(x => x.classList.toggle("active", x.dataset.range === r));
  if (r !== "custom") { $("#from").value = ""; $("#to").value = ""; }
  state.fitNext = true;
  refresh();
}
for (const id of ["#from", "#to"]) $(id).addEventListener("change", () => {
  state.range = "custom";
  $$("#ranges button").forEach(x => x.classList.remove("active"));
  state.fitNext = true;
  refresh();
});

$("#toggle-side").onclick = () => $("#side").classList.toggle("open");

/* ---------- Tabs ---------- */
$(".tabs").addEventListener("click", e => {
  const b = e.target.closest("button"); if (!b) return;
  showTab(b.dataset.tab);
});
function showTab(t, load = true) {
  state.tab = t;
  $$(".tabs button").forEach(x => x.classList.toggle("active", x.dataset.tab === t));
  $$(".tab").forEach(x => x.classList.toggle("active", x.id === "tab-" + t));
  if (t === "map") setTimeout(() => map.invalidateSize(), 0);
  if (load) refreshTab();
}

/* ---------- Kacheln ---------- */
async function loadSummary() {
  const s = await api("stats/summary?" + query());
  const tiles = [
    [fmtNum.format(s.km) + " km", "gefahren"],
    [fmtInt.format(s.points), "Positionen"],
    [fmtInt.format(s.packets), "Pakete (live)"],
    [fmtInt.format(s.days), "Tage mit Daten"],
    [s.max_speed != null ? fmtNum.format(s.max_speed) + " km/h" : "–", "max. Geschwindigkeit"],
    [s.max_alt != null ? fmtInt.format(Math.round(s.max_alt)) + " m" : "–", "max. Höhe"],
    [s.first ? fmtD.format(new Date(s.first)) : "–", "erste Position"],
    [s.last ? ago(s.last) : "–", "letzte Position"],
  ];
  $("#tiles").innerHTML = tiles.map(([v, k]) => `<div class="tile"><div class="v" title="${esc(v)}">${esc(v)}</div><div class="k">${k}</div></div>`).join("");
}

/* ---------- Karte ---------- */
const osm = L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
  maxZoom: 19, attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
});
const swiss = L.tileLayer("https://wmts.geo.admin.ch/1.0.0/ch.swisstopo.pixelkarte-farbe/default/current/3857/{z}/{x}/{y}.jpeg", {
  maxZoom: 19, attribution: '&copy; <a href="https://www.swisstopo.admin.ch/">swisstopo</a>',
});
const swissImg = L.tileLayer("https://wmts.geo.admin.ch/1.0.0/ch.swisstopo.swissimage/default/current/3857/{z}/{x}/{y}.jpeg", {
  maxZoom: 20, attribution: '&copy; <a href="https://www.swisstopo.admin.ch/">swisstopo</a>',
});
const baseName = load("basemap", "OpenStreetMap");
const bases = { "OpenStreetMap": osm, "swisstopo Landeskarte": swiss, "swisstopo Luftbild": swissImg };
const map = L.map("map", { preferCanvas: true, layers: [bases[baseName] || osm] }).setView([46.8, 8.2], 8);
L.control.layers(bases, null, { position: "topright" }).addTo(map);
L.control.scale({ imperial: false }).addTo(map);
map.on("baselayerchange", e => save("basemap", e.name));

const renderer = L.canvas({ padding: 0.3 });
const layers = {
  tracks: L.layerGroup(), points: L.layerGroup(), heat: L.heatLayer([], { radius: 14, blur: 18, minOpacity: 0.3 }),
  latest: L.layerGroup(), highlight: L.layerGroup().addTo(map),
};
const layerBoxes = { tracks: "#lay-tracks", points: "#lay-points", heat: "#lay-heat", latest: "#lay-latest" };
for (const [k, sel] of Object.entries(layerBoxes)) {
  const saved = load("layer-" + k, null);
  if (saved !== null) $(sel).checked = saved;
  if ($(sel).checked) layers[k].addTo(map);
  $(sel).addEventListener("change", e => {
    save("layer-" + k, e.target.checked);
    e.target.checked ? layers[k].addTo(map) : map.removeLayer(layers[k]);
  });
}

function popupFor(r) {
  const [call, t, lat, lon, spd, alt, crs, comment, src] = r;
  return `<b>${esc(labelOf(call))}</b><br>${dt(t)}<br>
    ${lat.toFixed(5)}, ${lon.toFixed(5)}<br>
    ${spd != null ? `Geschwindigkeit: ${fmtNum.format(spd)} km/h<br>` : ""}
    ${crs != null ? `Kurs: ${Math.round(crs)}°<br>` : ""}
    ${alt != null ? `Höhe: ${fmtInt.format(Math.round(alt))} m<br>` : ""}
    ${comment ? `<i>${esc(comment)}</i><br>` : ""}
    <span class="muted">Quelle: ${src === "import" ? "Import" : "APRS-IS"}</span>`;
}

async function loadMap() {
  const data = await api("positions?" + query());
  for (const k of ["tracks", "points", "latest"]) layers[k].clearLayers();
  const rows = data.rows;
  const heat = [];
  let line = [], prev = null;
  const flush = (call) => {
    if (line.length > 1) L.polyline(line, { color: colorOf(call), weight: 3, opacity: 0.75, renderer }).addTo(layers.tracks);
    line = [];
  };
  for (const r of rows) {
    const [call, t, lat, lon] = r;
    if (prev && (prev[0] !== call || t - prev[1] > TRIP_GAP_MS)) flush(prev[0]);
    line.push([lat, lon]);
    heat.push([lat, lon, 1]);
    L.circleMarker([lat, lon], { radius: 3.5, color: colorOf(call), weight: 1, fillOpacity: 0.7, renderer })
      .bindPopup(() => popupFor(r)).addTo(layers.points);
    prev = r;
  }
  if (prev) flush(prev[0]);
  layers.heat.setLatLngs(heat);

  await loadLatest();
  $("#map-info").textContent = data.total
    ? `${fmtInt.format(data.total)} Positionen${data.step > 1 ? `, jede ${data.step}. angezeigt` : ""}`
    : "Keine Positionen im gewählten Zeitraum.";

  if (state.fitNext && rows.length) {
    map.fitBounds(L.latLngBounds(rows.map(r => [r[2], r[3]])), { padding: [30, 30], maxZoom: 15 });
  }
  state.fitNext = false;
}

async function loadLatest() {
  const q = new URLSearchParams(query());
  q.delete("from"); q.delete("to");
  const latest = await api("latest?" + q.toString());
  layers.latest.clearLayers();
  for (const p of latest) {
    L.circleMarker([p.lat, p.lon], { radius: 8, color: "#fff", weight: 2, fillColor: colorOf(p.callsign), fillOpacity: 1, renderer })
      .bindTooltip(`${esc(p.callsign)} · ${ago(p.ts)}`, { permanent: true, direction: "right", offset: [8, 0], className: "call-label" })
      .bindPopup(popupFor([p.callsign, p.ts, p.lat, p.lon, p.speed_kmh, p.altitude_m, p.course, p.comment, p.source]))
      .addTo(layers.latest);
  }
}

function highlight(latlngs, isPoint) {
  layers.highlight.clearLayers();
  if (isPoint) {
    L.circle(latlngs, { radius: 150, color: "#f59e0b", weight: 3, fillOpacity: 0.15 }).addTo(layers.highlight);
    map.setView(latlngs, 16);
  }
}

/* ---------- Statistik ---------- */
const charts = {};
function chartColors() {
  const cs = getComputedStyle(document.documentElement);
  return { text: cs.getPropertyValue("--muted").trim(), grid: cs.getPropertyValue("--border").trim() };
}
function makeChart(id, cfg) {
  if (charts[id]) charts[id].destroy();
  const c = chartColors();
  Chart.defaults.color = c.text;
  Chart.defaults.borderColor = c.grid;
  Chart.defaults.font.family = getComputedStyle(document.body).fontFamily;
  charts[id] = new Chart($("#" + id), cfg);
}

async function loadCharts() {
  const bucket = $("#bucket").value;
  const [dist, act, tl] = await Promise.all([
    api("stats/distance?" + query({ bucket })),
    api("stats/activity?" + query()),
    api("stats/timeline?" + query()),
  ]);

  const labels = [...new Set(dist.map(d => d.bucket))].sort();
  const calls = [...new Set(dist.map(d => d.callsign))];
  makeChart("chart-km", {
    type: "bar",
    data: {
      labels,
      datasets: calls.map(c => ({
        label: labelOf(c), backgroundColor: colorOf(c), borderRadius: 3,
        data: labels.map(l => (dist.find(d => d.bucket === l && d.callsign === c) || {}).km || 0),
      })),
    },
    options: {
      maintainAspectRatio: false, animation: false,
      scales: { x: { stacked: true }, y: { stacked: true, title: { display: true, text: "km" } } },
      plugins: { tooltip: { callbacks: { label: ctx => `${ctx.dataset.label}: ${fmtNum.format(ctx.parsed.y)} km` } } },
    },
  });

  // Wochentag x Stunde
  const grid = Array.from({ length: 7 }, () => Array(24).fill(0));
  let max = 0;
  for (const a of act) { grid[a.dow - 1][a.hour] = a.n; max = Math.max(max, a.n); }
  const days = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"];
  const accent = getComputedStyle(document.documentElement).getPropertyValue("--accent").trim();
  let html = `<div></div>` + Array.from({ length: 24 }, (_, h) => `<div class="h">${h % 3 === 0 ? h : ""}</div>`).join("");
  grid.forEach((row, d) => {
    html += `<div class="d">${days[d]}</div>` + row.map((n, h) => {
      const a = max ? n / max : 0;
      const bg = n ? `background:color-mix(in srgb, ${accent} ${Math.round(12 + a * 88)}%, transparent)` : "";
      return `<div class="c" style="${bg}" title="${days[d]} ${h}:00–${h + 1}:00: ${fmtInt.format(n)} Positionen"></div>`;
    }).join("");
  });
  $("#activity").innerHTML = html;

  // Geschwindigkeit / Höhe
  const tcalls = [...new Set(tl.map(r => r.callsign))];
  const ds = [];
  for (const c of tcalls) {
    const pts = tl.filter(r => r.callsign === c);
    ds.push({ label: `${c} km/h`, yAxisID: "y", borderColor: colorOf(c), backgroundColor: colorOf(c), pointRadius: 0, borderWidth: 1.2,
              data: pts.filter(r => r.speed_kmh != null).map(r => ({ x: +new Date(r.ts), y: r.speed_kmh })) });
    ds.push({ label: `${c} Höhe`, yAxisID: "y1", borderColor: colorOf(c), borderDash: [4, 3], pointRadius: 0, borderWidth: 1,
              data: pts.filter(r => r.altitude_m != null).map(r => ({ x: +new Date(r.ts), y: r.altitude_m })) });
  }
  makeChart("chart-timeline", {
    type: "line",
    data: { datasets: ds.filter(d => d.data.length) },
    options: {
      maintainAspectRatio: false, animation: false, parsing: false, spanGaps: false,
      interaction: { mode: "nearest", intersect: false },
      scales: {
        x: { type: "linear", ticks: { callback: v => fmtD.format(new Date(v)), maxTicksLimit: 8 } },
        y: { position: "left", title: { display: true, text: "km/h" }, beginAtZero: true },
        y1: { position: "right", title: { display: true, text: "Höhe m" }, grid: { drawOnChartArea: false } },
      },
      plugins: { tooltip: { callbacks: { title: items => items.length ? dt(items[0].parsed.x) : "" } } },
    },
  });
}
$("#bucket").addEventListener("change", loadCharts);

/* ---------- Fahrten & Orte ---------- */
async function loadTrips() {
  const [trips, places] = await Promise.all([
    api("stats/trips?" + query()),
    api("stats/places?" + query({ eps: $("#eps").value })),
  ]);
  $("#trips-table").innerHTML = trips.length ? `<thead><tr><th>Gerät</th><th>Start</th><th class="num">km</th><th class="num">Dauer</th><th class="num">⌀ km/h</th><th class="num">max</th></tr></thead><tbody>` +
    trips.map((t, i) => `<tr class="click" data-i="${i}">
      <td><span class="dot" style="display:inline-block;background:${colorOf(t.callsign)}"></span> ${esc(t.callsign)}</td>
      <td>${dt(t.start)}</td><td class="num">${fmtNum.format(t.km)}</td><td class="num">${dur(t.seconds)}</td>
      <td class="num">${t.seconds ? fmtNum.format(t.km / (t.seconds / 3600)) : "–"}</td>
      <td class="num">${t.max_speed != null ? fmtNum.format(t.max_speed) : "–"}</td></tr>`).join("") + "</tbody>"
    : `<tbody><tr><td class="muted">Keine Fahrten im gewählten Zeitraum.</td></tr></tbody>`;
  $("#trips-table").onclick = e => {
    const tr = e.target.closest("tr[data-i]"); if (!tr) return;
    const t = trips[tr.dataset.i];
    state.selected = new Set([t.callsign]); save("selected", [...state.selected]);
    state.range = "custom";
    $$("#ranges button").forEach(x => x.classList.remove("active"));
    // Zeitraum exakt auf die Fahrt setzen (Datumsfelder zeigen den Tag)
    $("#from").value = toDateInput(new Date(t.start));
    $("#to").value = toDateInput(new Date(t.end));
    state.tripRange = [new Date(t.start), new Date(new Date(t.end).getTime() + 1000)];
    renderDevices();
    state.fitNext = true;
    showTab("map", false);
    refresh();
  };

  $("#places-table").innerHTML = places.length ? `<thead><tr><th>#</th><th class="num">Stunden</th><th class="num">Tage</th><th>zuletzt</th><th>Geräte</th><th>Koordinaten</th></tr></thead><tbody>` +
    places.map((p, i) => `<tr class="click" data-i="${i}"><td>${i + 1}</td><td class="num">${fmtNum.format(p.hours)}</td>
      <td class="num">${p.days}</td><td>${dt(p.last)}</td><td>${esc(p.callsigns.join(", "))}</td>
      <td class="mono">${p.lat.toFixed(4)}, ${p.lon.toFixed(4)}</td></tr>`).join("") + "</tbody>"
    : `<tbody><tr><td class="muted">Keine Aufenthaltsorte gefunden.</td></tr></tbody>`;
  $("#places-table").onclick = e => {
    const tr = e.target.closest("tr[data-i]"); if (!tr) return;
    const p = places[tr.dataset.i];
    showTab("map");
    setTimeout(() => highlight([p.lat, p.lon], true), 50);
  };
}
$("#eps").addEventListener("change", loadTrips);
function toDateInput(d) { const z = n => String(n).padStart(2, "0"); return `${d.getFullYear()}-${z(d.getMonth() + 1)}-${z(d.getDate())}`; }

/* ---------- Pfade ---------- */
async function loadPaths() {
  const [p, pk] = await Promise.all([api("stats/paths?" + query()), api("packets?" + query({ limit: 100 }))]);
  const tbl = (rows, empty) => rows.length
    ? `<thead><tr><th>Rufzeichen</th><th class="num">Pakete</th><th>zuletzt</th></tr></thead><tbody>` +
      rows.map(r => `<tr><td><a href="https://aprs.fi/info/a/${encodeURIComponent(r.call)}" target="_blank" rel="noopener">${esc(r.call)}</a></td><td class="num">${fmtInt.format(r.n)}</td><td>${dt(r.last)}</td></tr>`).join("") + "</tbody>"
    : `<tbody><tr><td class="muted">${empty}</td></tr></tbody>`;
  $("#digis-table").innerHTML = tbl(p.digis, "Keine Digipeater im Pfad.");
  $("#igates-table").innerHTML = tbl(p.igates, "Noch keine Live-Pakete.");
  makeChart("chart-routes", {
    type: "doughnut",
    data: { labels: p.routes.map(r => r.route), datasets: [{ data: p.routes.map(r => r.n), backgroundColor: PALETTE, borderWidth: 0 }] },
    options: { maintainAspectRatio: false, animation: false, plugins: { legend: { position: "bottom" } } },
  });
  $("#packets-table").innerHTML = pk.length
    ? `<thead><tr><th>Zeit</th><th>Rufzeichen</th><th>iGate</th><th>Rohpaket</th></tr></thead><tbody>` +
      pk.map(r => `<tr><td>${dt(r.received_at)}</td><td>${esc(r.callsign)}</td><td>${esc(r.igate || "")}</td><td class="wrap">${esc(r.raw)}</td></tr>`).join("") + "</tbody>"
    : `<tbody><tr><td class="muted">Noch keine Live-Pakete im gewählten Zeitraum.</td></tr></tbody>`;
}

/* ---------- Stationen ---------- */
(function fillSsid() {
  const sel = $("#station-form select[name=ssid]");
  for (let i = 1; i <= 15; i++) sel.insertAdjacentHTML("beforeend", `<option value="${i}">-${i}</option>`);
})();

async function loadStations() {
  state.stations = await api("stations");
  // neue Geräte in eine bestehende Auswahl nicht automatisch aufnehmen; ungültige entfernen
  for (const c of [...state.selected]) if (!devices().some(d => d.full === c)) state.selected.delete(c);
  renderDevices();
  renderStationsTable();
}

function renderStationsTable() {
  const rows = state.stations;
  $("#stations-table").innerHTML = rows.length
    ? `<thead><tr><th>Station</th><th>Bezeichnung</th><th>Farbe</th><th>live</th><th class="num">Positionen</th><th>letzte Position</th><th></th></tr></thead><tbody>` +
      rows.map(s => `<tr data-id="${s.id}">
        <td><b>${esc(s.full)}</b>${s.ssid === "*" ? ` <span class="muted small">alle SSIDs</span>` : ""}${s.auto ? ` <span class="muted small">automatisch</span>` : ""}</td>
        <td><input type="text" data-f="label" value="${esc(s.label || "")}" placeholder="–"></td>
        <td>${s.ssid === "*" ? "" : `<input type="color" data-f="color" value="${s.color || colorOf(s.full)}">`}</td>
        <td><input type="checkbox" data-f="track" ${s.track ? "checked" : ""} title="live über APRS-IS verfolgen"></td>
        <td class="num">${s.ssid === "*" ? "" : fmtInt.format(s.points || 0)}</td>
        <td>${s.last ? `${dt(s.last)} <span class="muted small">(${ago(s.last)})</span>` : ""}</td>
        <td><button class="btn danger" data-del="${s.id}">Entfernen</button></td>
      </tr>`).join("") + "</tbody>"
    : `<tbody><tr><td class="muted">Noch keine Stationen eingetragen.</td></tr></tbody>`;
}

$("#stations-table").addEventListener("change", async e => {
  const f = e.target.dataset.f; if (!f) return;
  const id = e.target.closest("tr").dataset.id;
  const v = f === "track" ? e.target.checked : e.target.value;
  try { await api(`stations/${id}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ [f]: v }) }); }
  catch (err) { alert(err.message); }
  await loadStations();
  if (f === "color") refresh();
});
$("#stations-table").addEventListener("click", async e => {
  const id = e.target.dataset.del; if (!id) return;
  const s = state.stations.find(x => String(x.id) === id);
  if (!confirm(`Station ${s.full} entfernen?`)) return;
  const purge = s.ssid !== "*" && s.points > 0 &&
    confirm(`Auch die ${fmtInt.format(s.points)} gespeicherten Positionen von ${s.full} löschen?\n\nOK = Daten löschen, Abbrechen = Daten behalten`);
  try { await api(`stations/${id}?purge=${purge}`, { method: "DELETE" }); } catch (err) { alert(err.message); }
  await loadStations(); refresh();
});

$("#station-form").addEventListener("submit", async e => {
  e.preventDefault();
  const fd = new FormData(e.target);
  const call = fd.get("callsign").trim();
  const body = {
    callsign: call,
    ssid: call.includes("-") ? "" : fd.get("ssid"),
    label: fd.get("label"), color: fd.get("color"), track: fd.get("track") === "on",
  };
  if (body.ssid === "*") body.color = null;
  const msg = $("#station-msg");
  try {
    const s = await api("stations", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    msg.className = "msg ok";
    msg.textContent = `${s.full} eingetragen.` + (s.track ? " Der Collector verbindet sich innert 15 s mit dem neuen Filter." : "");
    e.target.reset();
    await loadStations(); loadStatus();
  } catch (err) { msg.className = "msg err"; msg.textContent = err.message; }
});

$("#import-form").addEventListener("submit", async e => {
  e.preventDefault();
  const form = e.target;
  const files = form.file.files;
  const out = $("#import-result");
  out.innerHTML = "";
  const btn = form.querySelector("button"); btn.disabled = true;
  for (const file of files) {
    const fd = new FormData();
    fd.append("file", file);
    fd.append("callsign", form.callsign.value);
    const div = document.createElement("div");
    div.className = "result"; div.textContent = `${file.name}: wird importiert …`;
    out.append(div);
    try {
      const r = await api("import", { method: "POST", body: fd });
      div.innerHTML = `<b>${esc(file.name)}</b>: <span class="ok">${fmtInt.format(r.imported)} neu</span>,
        ${fmtInt.format(r.duplicate)} schon vorhanden${r.errors ? `, <span class="err">${fmtInt.format(r.errors)} fehlerhaft</span>` : ""}
        <br><span class="muted">${esc(r.callsigns.join(", "))} · ${dt(r.first)} – ${dt(r.last)}</span>
        ${r.error_samples.length ? `<ul>${r.error_samples.map(x => `<li>${esc(x)}</li>`).join("")}</ul>` : ""}`;
    } catch (err) {
      div.innerHTML = `<b>${esc(file.name)}</b>: <span class="err">${esc(err.message)}</span>`;
    }
  }
  btn.disabled = false;
  form.file.value = "";
  await loadStations();
  state.fitNext = true;
  refresh();
});

/* ---------- Status ---------- */
async function loadStatus() {
  const s = await api("status");
  const c = s.collector || {};
  const pill = $("#live-pill");
  const fresh = c.updated_at && (Date.now() - new Date(c.updated_at)) < 90000;
  if (c.state === "connected" && fresh) { pill.className = "pill ok"; pill.textContent = "● live"; }
  else if (c.state === "idle") { pill.className = "pill"; pill.textContent = "keine Stationen live"; }
  else if (c.state === "error" || !fresh) { pill.className = "pill err"; pill.textContent = c.state ? "Collector: Fehler" : "Collector: aus"; }
  else { pill.className = "pill warn"; pill.textContent = "verbinde …"; }
  pill.title = c.last_packet_at ? `letztes Paket ${ago(c.last_packet_at)}` : "noch kein Paket";
  const states = { connected: "verbunden", connecting: "verbinde", idle: "untätig (keine Station live)", error: "Fehler" };

  if (state.tab !== "status") return;
  $("#collector").innerHTML = `
    <dt>Zustand</dt><dd>${esc(states[c.state] || c.state || "noch nie gestartet")}${fresh ? "" : " <span class='err'>(kein Lebenszeichen)</span>"}</dd>
    <dt>Server</dt><dd>${esc(c.server || "–")}</dd>
    <dt>Login</dt><dd>${esc(c.login || "–")}</dd>
    <dt>Filter</dt><dd class="mono">${esc(c.filter || "–")}</dd>
    <dt>verbunden seit</dt><dd>${dt(c.connected_since)}</dd>
    <dt>letztes Paket</dt><dd>${dt(c.last_packet_at)} ${c.last_packet_at ? `(${ago(c.last_packet_at)})` : ""}</dd>
    <dt>Pakete gesamt</dt><dd>${fmtInt.format(c.packets_total || 0)}</dd>
    <dt>letzter Fehler</dt><dd>${esc(c.last_error || "–")}</dd>`;
  $("#dbinfo").innerHTML = `
    <dt>Positionen</dt><dd>${fmtInt.format(s.counts.positions)}</dd>
    <dt>Pakete</dt><dd>${fmtInt.format(s.counts.packets)}</dd>
    <dt>Stationen</dt><dd>${fmtInt.format(s.counts.stations)}</dd>
    <dt>Grösse</dt><dd>${esc(s.counts.db_size)}</dd>
    <dt>Version</dt><dd>${esc(s.version)}</dd>`;
  $("#imports-table").innerHTML = s.imports.length
    ? `<thead><tr><th>Zeit</th><th>Datei</th><th>Rufzeichen</th><th class="num">Zeilen</th><th class="num">neu</th><th class="num">doppelt</th><th class="num">Fehler</th></tr></thead><tbody>` +
      s.imports.map(i => `<tr><td>${dt(i.imported_at)}</td><td>${esc(i.filename)}</td><td>${esc(i.callsign || "")}</td>
        <td class="num">${i.rows_total}</td><td class="num">${i.rows_imported}</td><td class="num">${i.rows_duplicate}</td><td class="num">${i.rows_error}</td></tr>`).join("") + "</tbody>"
    : `<tbody><tr><td class="muted">Noch keine Importe.</td></tr></tbody>`;
}

/* ---------- Ablauf ---------- */
function exportLink() { $("#export-link").href = "api/export.csv?" + query(); }

async function refreshTab() {
  try {
    if (state.tab === "map") await loadMap();
    else if (state.tab === "charts") await loadCharts();
    else if (state.tab === "trips") await loadTrips();
    else if (state.tab === "paths") await loadPaths();
    else if (state.tab === "stations") await loadStations();
    else if (state.tab === "status") await loadStatus();
  } catch (err) { console.error(err); }
}

async function refresh() {
  computeRange();
  if (state.tripRange) { [state.from, state.to] = state.tripRange; state.tripRange = null; }
  exportLink();
  await Promise.all([loadSummary().catch(console.error), refreshTab()]);
}

// Live: alle 30 s Kacheln, letzte Positionen und Status aktualisieren
setInterval(async () => {
  loadStatus().catch(() => {});
  if (!$("#auto-refresh").checked || !isLiveRange() || document.hidden) return;
  if (state.range !== "custom") computeRange();
  loadSummary().catch(() => {});
  if (state.tab === "map") loadMap().catch(() => {});
  if (state.tab === "stations") loadStations().catch(() => {});
}, 30000);

(async function init() {
  $$("#ranges button").forEach(x => x.classList.toggle("active", x.dataset.range === state.range));
  if (!["1d", "7d", "30d", "365d", "all"].includes(state.range)) state.range = "30d";
  await loadStations().catch(console.error);
  if (!devices().length) showTab("stations");
  loadStatus().catch(console.error);
  refresh();
})();
