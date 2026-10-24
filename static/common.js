// Helpers shared by the search page and the campground page.

function esc(value) {
  return String(value ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

function timeAgo(iso) {
  if (!iso) return "never";
  const mins = Math.round((Date.now() - new Date(iso).getTime()) / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins} min ago`;
  const hours = Math.round(mins / 60);
  if (hours < 48) return `${hours} h ago`;
  return `${Math.round(hours / 24)} days ago`;
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

const STATUS_LABEL = {
  open: "Open all nights",
  partial: "Some nights open",
  full: "No sites open (full or closed)",
  unknown: "Availability not checked",
  fcfs: "First-come, first-served",
};

async function loadMeta() {
  const meta = await fetchJSON("/api/meta");
  const fresh = document.getElementById("freshness");
  fresh.textContent = `${meta.campgrounds} campgrounds · availability last checked ${timeAgo(meta.last_checked)}`;
  const notes = [];
  if (meta.demo) notes.push("Showing DEMO data with fake campgrounds and random availability. Remove it with <code>python3 manage.py seed-demo --clear</code>.");
  if (meta.unchecked_campgrounds > 0) {
    notes.push(`${meta.unchecked_campgrounds} campgrounds don't have live availability yet and show as “not checked”. Use their link to the official booking site.`);
  }
  if (meta.campgrounds === 0) notes.push("No campgrounds loaded yet. Run <code>python3 manage.py seed-demo</code> or <code>python3 manage.py import-ridb</code>.");
  const banner = document.getElementById("banner");
  if (notes.length) {
    banner.innerHTML = notes.join("<br>");
    banner.hidden = false;
  }
  return meta;
}
