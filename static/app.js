// Search page: filters -> /api/search -> map pins + list, coloured by when booking opens.

const form = document.getElementById("filters");
const sortSelect = document.getElementById("sort");
const list = document.getElementById("results");
const count = document.getElementById("count");
let lastResults = [];
let myLocation = null;

const css = getComputedStyle(document.documentElement);
const STATUS_COLOR = Object.fromEntries(
  ["upcoming", "open", "fcfs"].map((s) => [s, css.getPropertyValue(`--${s}`).trim()])
);
// booking status from the API -> dot/pin class
const DOT = { upcoming: "upcoming", open: "open", lottery: "fcfs", no_reservations: "fcfs" };
const DOT_LABEL = { upcoming: "Booking opens later", open: "Booking already open", fcfs: "No reservations" };

const map = new maplibregl.Map({
  container: "map",
  style: {
    version: 8,
    sources: {
      osm: {
        type: "raster",
        tiles: ["https://tile.openstreetmap.org/{z}/{x}/{y}.png"],
        tileSize: 256,
        maxzoom: 19,
        attribution: "© OpenStreetMap contributors · Data: Recreation.gov / RIDB",
      },
    },
    layers: [{ id: "osm", type: "raster", source: "osm" }],
  },
  center: [-105.55, 39.0],
  zoom: 6,
});
map.addControl(new maplibregl.NavigationControl(), "top-right");

const mapReady = new Promise((resolve) => map.on("load", resolve));
mapReady.then(() => {
  map.addSource("campgrounds", { type: "geojson", data: { type: "FeatureCollection", features: [] } });
  map.addLayer({
    id: "campgrounds",
    type: "circle",
    source: "campgrounds",
    paint: {
      "circle-radius": 7,
      "circle-color": ["match", ["get", "status"],
        "upcoming", STATUS_COLOR.upcoming, "open", STATUS_COLOR.open, STATUS_COLOR.fcfs],
      "circle-stroke-width": 1.5,
      "circle-stroke-color": "#ffffff",
    },
  });
  map.on("click", "campgrounds", (e) => {
    const id = e.features[0].properties.id;
    highlight(id);
    const cg = lastResults.find((r) => r.id === id);
    new maplibregl.Popup().setLngLat(e.lngLat).setHTML(popupHTML(cg)).addTo(map);
  });
  map.on("mouseenter", "campgrounds", () => (map.getCanvas().style.cursor = "pointer"));
  map.on("mouseleave", "campgrounds", () => (map.getCanvas().style.cursor = ""));
});

function detailUrl(cg) {
  const p = new URLSearchParams({ start: form.start.value, end: form.end.value });
  return `/campground.html?id=${cg.id}&${p}`;
}

function summary(cg) {
  if (!cg.matching_sites) return "No site details";
  return `${cg.matching_sites} matching site${cg.matching_sites > 1 ? "s" : ""}`;
}

function calendarButton(cg) {
  if (cg.booking.status === "no_reservations") return "";
  const added = savedIds().includes(cg.id);
  return `<button type="button" class="link add-cal" data-id="${cg.id}"${added ? " disabled" : ""}>
    ${added ? "✓ In booking calendar" : "+ Booking calendar"}</button>`;
}

function bookingLine(cg) {
  const b = cg.booking;
  if (!b || b.status === "no_reservations") return "";
  if (b.status === "lottery") return `<span class="booking">Lottery</span>`;
  if (b.status === "open") return `<span class="booking">Bookable now for these dates</span>`;
  return `<span class="booking upcoming">Bookable ${esc(b.opens_at_text)}${b.verified ? "" : " (unverified)"}</span>`;
}

function popupHTML(cg) {
  return `<strong>${esc(cg.name)}</strong><br>${bookingLine(cg)}<br>
    <a href="${detailUrl(cg)}">Plan my booking →</a>`;
}

function highlight(id) {
  list.querySelectorAll("li").forEach((li) => li.classList.toggle("active", Number(li.dataset.id) === id));
  list.querySelector(`li[data-id="${id}"]`)?.scrollIntoView({ block: "nearest", behavior: "smooth" });
}

function renderList(results) {
  count.textContent = `${results.length} campground${results.length === 1 ? "" : "s"}`;
  if (!results.length) {
    list.innerHTML = `<li class="empty" style="display:block;border:0;background:none">No campgrounds match these filters.</li>`;
    return;
  }
  list.innerHTML = results.map((cg) => `
    <li data-id="${cg.id}">
      <span class="dot ${DOT[cg.booking.status]}" title="${esc(DOT_LABEL[DOT[cg.booking.status]])}"></span>
      <span><a class="name" href="${detailUrl(cg)}">${esc(cg.name)}</a></span>
      <span class="side">
        ${cg.distance_mi != null ? `${cg.distance_mi} mi<br>` : ""}
        ${cg.min_price != null ? `from $${cg.min_price.toFixed(0)}` : ""}
      </span>
      <span class="sub">${esc(cg.agency)} · ${esc(summary(cg))}
        <br>${bookingLine(cg)} ${calendarButton(cg)}</span>
    </li>`).join("");
}

async function renderMap(results) {
  await mapReady;
  const features = results.filter((r) => r.lat != null && r.lng != null).map((r) => ({
    type: "Feature",
    geometry: { type: "Point", coordinates: [r.lng, r.lat] },
    properties: { id: r.id, status: DOT[r.booking.status] },
  }));
  map.getSource("campgrounds").setData({ type: "FeatureCollection", features });
  if (features.length) {
    const bounds = new maplibregl.LngLatBounds();
    features.forEach((f) => bounds.extend(f.geometry.coordinates));
    map.fitBounds(bounds, { padding: 50, maxZoom: 10, duration: 0 });
  }
}

async function getLocation() {
  if (myLocation) return myLocation;
  myLocation = await new Promise((resolve, reject) =>
    navigator.geolocation.getCurrentPosition(
      (pos) => resolve([pos.coords.latitude, pos.coords.longitude]), reject));
  return myLocation;
}

async function buildQuery() {
  const fd = new FormData(form);
  const q = new URLSearchParams();
  q.set("start", fd.get("start"));
  q.set("end", fd.get("end"));
  const near = fd.get("near");
  if (near) {
    const [lat, lng] = near === "here" ? await getLocation() : near.split(",").map(Number);
    q.set("lat", lat);
    q.set("lng", lng);
    if (fd.get("radius")) q.set("radius", fd.get("radius"));
  }
  const types = fd.getAll("types");
  if (types.length) q.set("types", types.join(","));
  for (const key of ["rv_length", "agency"]) if (fd.get(key)) q.set(key, fd.get(key));
  for (const key of ["electric", "water", "sewer", "ada", "pets", "fcfs"]) if (fd.get(key)) q.set(key, "1");
  q.set("sort", sortSelect.value);
  return q;
}

async function runSearch() {
  let q;
  try {
    q = await buildQuery();
  } catch {
    count.textContent = "Couldn't get your location. Pick a town instead.";
    return;
  }
  history.replaceState(null, "", `?${q}`);
  count.textContent = "Searching…";
  try {
    const data = await fetchJSON(`/api/search?${q}`);
    lastResults = data.results;
    renderList(lastResults);
    renderMap(lastResults);
  } catch (err) {
    count.textContent = `Error: ${err.message}`;
  }
}

function restoreForm() {
  const params = new URLSearchParams(location.search);
  const tomorrow = addDays(isoDate(new Date()), 1);
  form.start.value = params.get("start") || tomorrow;
  form.end.value = params.get("end") || addDays(form.start.value, 2);
  for (const key of ["radius", "rv_length", "agency"]) if (params.get(key)) form[key].value = params.get(key);
  for (const key of ["electric", "water", "sewer", "ada", "pets", "fcfs"]) form[key].checked = params.get(key) === "1";
  const types = (params.get("types") || "").split(",");
  form.querySelectorAll('input[name="types"]').forEach((el) => (el.checked = types.includes(el.value)));
  if (params.get("lat")) {
    const match = [...form.near.options].find((o) => o.value === `${params.get("lat")},${params.get("lng")}`);
    if (match) form.near.value = match.value;
  }
  if (params.get("sort")) sortSelect.value = params.get("sort");
}

form.start.addEventListener("change", () => {
  if (form.end.value <= form.start.value) form.end.value = addDays(form.start.value, 1);
});
form.addEventListener("submit", (e) => { e.preventDefault(); runSearch(); });
sortSelect.addEventListener("change", runSearch);
list.addEventListener("click", (e) => {
  const button = e.target.closest("button.add-cal");
  if (!button) return;
  setSavedIds([...savedIds(), Number(button.dataset.id)]);
  button.textContent = "✓ In booking calendar";
  button.disabled = true;
});
list.addEventListener("mouseover", (e) => {
  const li = e.target.closest("li[data-id]");
  if (li) list.querySelectorAll("li").forEach((el) => el.classList.toggle("active", el === li));
});

(async function init() {
  const meta = await loadMeta();
  for (const a of meta.agencies) form.agency.add(new Option(`${a.name} (${a.campgrounds})`, a.id));
  restoreForm();
  runSearch();
})();
