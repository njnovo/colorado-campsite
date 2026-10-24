// Booking calendar: for the picked campgrounds and trip dates, put every booking day on a month grid.

const MT = "America/Denver";
const COLORS = 8;
const state = { ids: [], mode: "dates", checkin: "", checkout: "", month: "", view: "", data: null };
let countdownTimer = null;
let findTimer = null;

const $ = (id) => document.getElementById(id);

// --- dates (calendar days are plain YYYY-MM-DD strings; times are shown in Mountain Time) ---

function mtDay(iso) {
  return new Date(iso).toLocaleDateString("en-CA", { timeZone: MT });
}

function mtTime(iso) {
  return new Date(iso).toLocaleTimeString("en-US", { timeZone: MT, hour: "numeric", minute: "2-digit" });
}

function todayMT() {
  return mtDay(new Date().toISOString());
}

function monthOf(day) {
  return day.slice(0, 7);
}

function shiftMonth(month, n) {
  const [y, m] = month.split("-").map(Number);
  const d = new Date(Date.UTC(y, m - 1 + n, 1));
  return d.toISOString().slice(0, 7);
}

function monthLabel(month) {
  return new Date(month + "-01T00:00:00Z").toLocaleDateString(undefined, { month: "long", year: "numeric", timeZone: "UTC" });
}

function defaultTrip() {
  // A Friday about seven months out, so the booking day is still ahead.
  const d = new Date();
  d.setUTCMonth(d.getUTCMonth() + 7);
  d.setUTCDate(d.getUTCDate() + ((5 - d.getUTCDay() + 7) % 7));
  const checkin = isoDate(d);
  return { checkin, checkout: addDays(checkin, 2), month: monthOf(checkin) };
}

// --- state <-> URL ---

function readState() {
  const p = new URLSearchParams(location.search);
  const fallback = defaultTrip();
  state.ids = p.has("ids") ? p.get("ids").split(",").map(Number).filter(Number.isInteger) : savedIds();
  state.mode = p.get("month") ? "month" : "dates";
  state.checkin = p.get("checkin") || fallback.checkin;
  state.checkout = p.get("checkout") || fallback.checkout;
  state.month = p.get("month") || monthOf(state.checkin);
  state.view = p.get("view") || "";
}

function query() {
  const p = new URLSearchParams();
  if (state.ids.length) p.set("ids", state.ids.join(","));
  if (state.mode === "month") p.set("month", state.month);
  else {
    p.set("checkin", state.checkin);
    p.set("checkout", state.checkout);
  }
  return p;
}

function writeState() {
  const p = query();
  if (state.view) p.set("view", state.view);
  history.replaceState(null, "", `?${p}`);
  setSavedIds(state.ids);
}

// --- loading ---

async function refresh() {
  writeState();
  clearInterval(countdownTimer);
  if (!state.ids.length) {
    state.data = { campgrounds: [], events: [], stays: [] };
    render();
    return;
  }
  try {
    state.data = await fetchJSON(`/api/booking-calendar?${query()}`);
  } catch (err) {
    $("agenda").innerHTML = `<p class="unverified">${esc(err.message)}</p>`;
    return;
  }
  // Keep only ids the server knows, in its order.
  state.ids = state.data.campgrounds.map((c) => c.id);
  writeState();
  if (!state.view) state.view = monthOf(firstUpcoming()?.day || tripStart() || todayMT());
  render();
}

function colorIndex(id) {
  return state.data.campgrounds.findIndex((c) => c.id === id) % COLORS;
}

function events() {
  return (state.data?.events || []).filter((e) => e.opens_at).map((e) => ({ ...e, day: mtDay(e.opens_at) }));
}

function firstUpcoming() {
  return events().find((e) => e.status === "upcoming");
}

function tripStart() {
  return state.data?.stays?.[0]?.checkin;
}

function tripNights() {
  const nights = new Set();
  for (const s of state.data?.stays || []) {
    for (let d = s.checkin; d < s.checkout; d = addDays(d, 1)) nights.add(d);
  }
  return nights;
}

// --- rendering ---

function render() {
  renderSetup();
  renderNextUp();
  renderMonth();
  renderAgenda();
}

function renderSetup() {
  document.querySelector(`input[name="mode"][value="${state.mode}"]`).checked = true;
  $("datesInputs").hidden = state.mode !== "dates";
  $("monthInputs").hidden = state.mode !== "month";
  $("checkin").value = state.checkin;
  $("checkout").value = state.checkout;
  $("month").value = state.month;
  const cgs = state.data?.campgrounds || [];
  $("chips").innerHTML = cgs.length ? cgs.map((c) => `
    <span class="chip c${colorIndex(c.id)}">
      <a href="/campground.html?id=${c.id}">${esc(shortName(c.name))}</a>
      <button type="button" class="remove" data-id="${c.id}" aria-label="Remove ${esc(c.name)}">×</button>
    </span>`).join("")
    : `<span class="meta">No campgrounds yet. Add some here, or with “+ Booking calendar” on the
       <a href="/">search page</a>.</span>`;
}

function stayLabel(e) {
  return formatStay(e.checkin, e.checkout);
}

function renderNextUp() {
  const box = $("nextUp");
  const next = firstUpcoming();
  if (!next) {
    box.hidden = true;
    return;
  }
  const others = events().filter((e) => e.status === "upcoming" && e.day === next.day && e !== next);
  box.hidden = false;
  box.innerHTML = `
    <div class="next-label">Next booking day</div>
    <div class="next-when">${esc(next.opens_at_text)}</div>
    <div class="countdown" id="countdown">${countdownText(next.opens_at)}</div>
    <div class="next-what"><span class="swatch c${colorIndex(next.campground.id)}"></span>
      ${esc(next.campground.name)} for ${esc(stayLabel(next))}
      ${others.length ? ` <span class="meta">+ ${others.length} more that day</span>` : ""}</div>
    <div class="plan-actions">
      ${next.campground.booking_url ? `<a class="button" href="${esc(next.campground.booking_url)}" target="_blank"
        rel="noopener">Open ${esc(next.campground.booking_system)}</a>` : ""}
      <a class="button secondary" href="/api/campgrounds/${next.campground.id}/plan.ics?checkin=${next.checkin}&checkout=${next.checkout}">
        Remind me (.ics)</a>
    </div>`;
  countdownTimer = setInterval(() => {
    const el = $("countdown");
    if (!el) return clearInterval(countdownTimer);
    el.textContent = countdownText(next.opens_at);
  }, 1000);
}

function chip(e, kind) {
  const time = e.time_known ? mtTime(kind === "last" ? e.full_stay_opens_at : e.opens_at) : "Time n/a";
  const past = e.status === "open" && kind === "first";
  const title = `${e.campground.name}: ${kind === "last" ? "last night of" : "booking opens for"} ${stayLabel(e)}`
    + (e.verified ? "" : " (unverified rule)");
  return `<a class="ev c${colorIndex(e.campground.id)}${kind === "last" ? " last" : ""}${past ? " past" : ""}"
    href="/campground.html?id=${e.campground.id}&start=${e.checkin}&end=${e.checkout}" title="${esc(title)}">
    <span class="t">${esc(time)}</span>
    <span class="nm">${esc(shortName(e.campground.name))}${kind === "last" ? " (last night)" : ""}</span>
    <span class="st">${esc(stayLabel(e))}${e.verified ? "" : " · unverified"}</span></a>`;
}

function renderMonth() {
  const view = state.view || monthOf(todayMT());
  $("monthTitle").textContent = monthLabel(view);
  const byDay = {};
  for (const e of events()) {
    (byDay[e.day] ||= []).push(chip(e, "first"));
    if (e.full_stay_opens_at) (byDay[mtDay(e.full_stay_opens_at)] ||= []).push(chip(e, "last"));
  }
  const nights = tripNights();
  const today = todayMT();
  const first = `${view}-01`;
  const offset = new Date(first + "T00:00:00Z").getUTCDay();
  const days = new Date(Date.UTC(+view.slice(0, 4), +view.slice(5, 7), 0)).getUTCDate();
  const heads = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"].map((d) => `<div class="dow">${d}</div>`).join("");
  let cells = "";
  for (let i = 0; i < offset; i++) cells += `<div class="day blank"></div>`;
  for (let n = 1; n <= days; n++) {
    const day = `${view}-${String(n).padStart(2, "0")}`;
    const classes = ["day", day === today && "today", day < today && "before", nights.has(day) && "trip",
      byDay[day] && "has"].filter(Boolean).join(" ");
    cells += `<div class="${classes}">
      <div class="num">${n}${nights.has(day) ? `<span class="trip-tag">Trip</span>` : ""}</div>
      ${(byDay[day] || []).join("")}</div>`;
  }
  $("grid").innerHTML = heads + cells;

  const ev = events();
  const upcoming = ev.filter((e) => e.status === "upcoming");
  const dl = $("downloadAll");
  dl.hidden = !upcoming.length;
  dl.href = `/api/booking-calendar.ics?${query()}`;
  $("jumpNext").hidden = !upcoming.length;
  $("jumpTrip").hidden = !tripStart();
  const hasLast = ev.some((e) => e.full_stay_opens_at);
  $("legend").innerHTML = `
    <span><span class="ev-key"></span>Booking opens (time in Mountain Time)</span>
    ${hasLast ? `<span><span class="ev-key last"></span>Last night of the stay opens (each night opens separately)</span>` : ""}
    <span><span class="trip-key"></span>Your trip</span>`;
}

function renderAgenda() {
  const all = state.data?.events || [];
  if (!all.length) {
    $("agenda").innerHTML = `<p class="meta">${state.ids.length
      ? "No upcoming trips: pick dates in the future."
      : "Add campgrounds to see their booking days."}</p>`;
    return;
  }
  const groups = { upcoming: [], open: [], none: [] };
  for (const e of all) (e.status === "upcoming" ? groups.upcoming : e.status === "open" ? groups.open : groups.none).push(e);
  const row = (e) => `<li>
    <span class="swatch c${colorIndex(e.campground.id)}"></span>
    <div>
      <strong>${e.opens_at_text ? esc(e.opens_at_text) : e.status === "lottery" ? "Lottery" : "No reservations"}</strong>
      <div><a href="/campground.html?id=${e.campground.id}&start=${e.checkin}&end=${e.checkout}">${esc(e.campground.name)}</a>
        · ${esc(stayLabel(e))}</div>
      <div class="meta">${e.rule ? esc(e.rule.summary) : "No booking rule on file"} ·
        ${e.verified ? `<span class="verified">verified ${esc(e.rule.verified_on)}</span>`
          : `<span class="unverified">unverified, check the booking site</span>`}
        ${e.full_stay_opens_at_text ? `<br>Last night opens ${esc(e.full_stay_opens_at_text)}` : ""}</div>
    </div>
    ${e.status === "upcoming" ? `<a class="button secondary small" href="/api/campgrounds/${e.campground.id}/plan.ics?checkin=${e.checkin}&checkout=${e.checkout}">.ics</a>` : ""}
  </li>`;
  $("agenda").innerHTML = [
    groups.upcoming.length ? `<h3>Coming up</h3><ul class="agenda">${groups.upcoming.map(row).join("")}</ul>` : "",
    groups.open.length ? `<h3>Already bookable</h3><ul class="agenda">${groups.open.map(row).join("")}</ul>` : "",
    groups.none.length ? `<h3>No online booking day</h3><ul class="agenda">${groups.none.map(row).join("")}</ul>` : "",
  ].join("");
}

// --- campground picker ---

async function findCampgrounds(q) {
  const list = $("suggestions");
  if (q.trim().length < 2) {
    list.hidden = true;
    return;
  }
  const { results } = await fetchJSON(`/api/campgrounds?q=${encodeURIComponent(q)}`);
  list.innerHTML = results.length ? results.map((r) => `<li><button type="button" data-id="${r.id}">
      ${esc(r.name)} <span class="meta">${esc(r.agency)}${r.reservable ? "" : " · first-come"}</span></button></li>`).join("")
    : `<li class="meta">No campgrounds match “${esc(q)}”.</li>`;
  list.hidden = false;
}

function addIds(ids) {
  state.ids = [...new Set([...state.ids, ...ids])];
  refresh();
}

// --- events ---

document.querySelectorAll('input[name="mode"]').forEach((el) => el.addEventListener("change", () => {
  state.mode = el.value;
  state.view = "";
  refresh();
}));
$("checkin").addEventListener("change", (e) => {
  if (!e.target.value) return;
  state.checkin = e.target.value;
  if (!state.checkout || state.checkout <= state.checkin) state.checkout = addDays(state.checkin, 2);
  state.view = "";
  refresh();
});
$("checkout").addEventListener("change", (e) => {
  if (!e.target.value || e.target.value <= state.checkin) return;
  state.checkout = e.target.value;
  refresh();
});
$("month").addEventListener("change", (e) => {
  if (!e.target.value) return;
  state.month = e.target.value;
  state.view = "";
  refresh();
});
$("find").addEventListener("input", (e) => {
  clearTimeout(findTimer);
  findTimer = setTimeout(() => findCampgrounds(e.target.value), 200);
});
$("suggestions").addEventListener("click", (e) => {
  const button = e.target.closest("button[data-id]");
  if (!button) return;
  $("find").value = "";
  $("suggestions").hidden = true;
  addIds([Number(button.dataset.id)]);
});
document.addEventListener("click", (e) => {
  if (!e.target.closest(".picker")) $("suggestions").hidden = true;
});
$("chips").addEventListener("click", (e) => {
  const button = e.target.closest("button.remove");
  if (!button) return;
  state.ids = state.ids.filter((id) => id !== Number(button.dataset.id));
  refresh();
});
$("addRmnp").addEventListener("click", async () => {
  const { results } = await fetchJSON(`/api/campgrounds?q=${encodeURIComponent("rocky mountain national park")}`);
  addIds(results.filter((r) => r.reservable).map((r) => r.id));
});
$("clearAll").addEventListener("click", () => {
  state.ids = [];
  refresh();
});
$("prevMonth").addEventListener("click", () => {
  state.view = shiftMonth(state.view || monthOf(todayMT()), -1);
  writeState();
  renderMonth();
});
$("nextMonth").addEventListener("click", () => {
  state.view = shiftMonth(state.view || monthOf(todayMT()), 1);
  writeState();
  renderMonth();
});
$("jumpNext").addEventListener("click", () => {
  const next = firstUpcoming();
  if (next) state.view = monthOf(next.day);
  writeState();
  renderMonth();
});
$("jumpTrip").addEventListener("click", () => {
  if (tripStart()) state.view = monthOf(tripStart());
  writeState();
  renderMonth();
});

(function init() {
  loadMeta();
  readState();
  refresh();
})();
