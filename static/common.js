// Helpers shared by the search page and the campground page.

function esc(value) {
  return String(value ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

function isoDate(d) {
  return d.toISOString().slice(0, 10);
}

function addDays(iso, n) {
  const d = new Date(iso + "T00:00:00Z");
  d.setUTCDate(d.getUTCDate() + n);
  return isoDate(d);
}

async function fetchJSON(url) {
  const resp = await fetch(url);
  const body = await resp.json();
  if (!resp.ok) throw new Error(body.error || `HTTP ${resp.status}`);
  return body;
}

// Campgrounds picked for the booking calendar, kept per browser.
const SAVED_KEY = "bookingCalendarIds";

function savedIds() {
  try {
    return JSON.parse(localStorage.getItem(SAVED_KEY) || "[]").filter(Number.isInteger);
  } catch {
    return [];
  }
}

function setSavedIds(ids) {
  try {
    localStorage.setItem(SAVED_KEY, JSON.stringify([...new Set(ids)]));
  } catch {
    // storage blocked: the calendar still works from its URL
  }
}

function calendarUrl(ids, checkin, checkout) {
  const p = new URLSearchParams();
  if (ids.length) p.set("ids", ids.join(","));
  if (checkin && checkout) {
    p.set("checkin", checkin);
    p.set("checkout", checkout);
  }
  return `/calendar.html?${p}`;
}

// "Rocky Mountain National Park Moraine Park Campground" -> "Moraine Park"
function shortName(name) {
  return name.replace(/^Rocky Mountain National Park /, "").replace(/ Campground$/, "");
}

function formatStay(checkin, checkout) {
  const opts = { month: "short", day: "numeric", timeZone: "UTC" };
  const a = new Date(checkin + "T00:00:00Z").toLocaleDateString(undefined, opts);
  const b = new Date(checkout + "T00:00:00Z").toLocaleDateString(undefined, opts);
  return `${a} – ${b}`;
}

function countdownText(target) {
  const secs = Math.max(0, Math.round((new Date(target).getTime() - Date.now()) / 1000));
  if (secs === 0) return "Bookable now";
  const d = Math.floor(secs / 86400), h = Math.floor((secs % 86400) / 3600);
  const m = Math.floor((secs % 3600) / 60), s = secs % 60;
  return `${d ? `${d}d ` : ""}${h}h ${String(m).padStart(2, "0")}m ${String(s).padStart(2, "0")}s`;
}

async function loadMeta() {
  const meta = await fetchJSON("/api/meta");
  const fresh = document.getElementById("freshness");
  if (fresh) fresh.textContent = `${meta.campgrounds} campgrounds`;
  if (meta.campgrounds === 0) {
    const banner = document.getElementById("banner");
    banner.innerHTML = "No campgrounds loaded yet. Run <code>python3 manage.py import-seed</code> or <code>python3 manage.py import-ridb</code>.";
    banner.hidden = false;
  }
  return meta;
}
