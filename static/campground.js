// Campground page: details, per-site availability calendar, deep link to book.

const params = new URLSearchParams(location.search);
const page = document.getElementById("page");
const SITE_STATUS = {
  available: ["✓", "Available"],
  reserved: ["×", "Reserved"],
  closed: ["–", "Closed / not available"],
  fcfs: ["F", "First-come, first-served"],
  not_released: ["…", "Not yet released"],
};

function siteNeeds(s) {
  const bits = [s.type];
  if (s.max_rv_length_ft) bits.push(`RV ≤ ${s.max_rv_length_ft} ft`);
  if (s.hookups.electric_amps) bits.push(`${s.hookups.electric_amps}A`);
  if (s.hookups.water) bits.push("water");
  if (s.hookups.sewer) bits.push("sewer");
  if (s.ada) bits.push("ADA");
  if (s.price_per_night != null) bits.push(`$${s.price_per_night.toFixed(0)}`);
  return bits.join(" · ");
}

function bookButton(cg) {
  if (!cg.booking_url) return `<p class="meta">No booking link (demo data).</p>`;
  return `<a class="button" href="${esc(cg.booking_url)}" target="_blank" rel="noopener">
    Book on ${esc(cg.booking_system)} →</a>
    <p class="meta">We don't take bookings. Availability changes quickly, so always confirm on the official site.</p>`;
}

function calendar(cg) {
  if (!cg.sites.length) return `<p class="meta">No campsite details for this campground yet.</p>`;
  const nights = new Set();
  const qs = new URLSearchParams(location.search);
  if (qs.get("nights_start") && qs.get("nights_end")) {
    for (let d = qs.get("nights_start"); d < qs.get("nights_end"); d = addDays(d, 1)) nights.add(d);
  }
  const head = cg.dates.map((d) => {
    const day = new Date(d + "T00:00:00Z");
    const label = `${day.toLocaleDateString(undefined, { weekday: "narrow", timeZone: "UTC" })}<br>${day.getUTCDate()}`;
    return `<th title="${d}"${nights.has(d) ? ' style="outline:2px solid var(--accent)"' : ""}>${label}</th>`;
  }).join("");
  const rows = cg.sites.map((s) => {
    const cells = cg.dates.map((d) => {
      const status = s.availability[d] || "unknown";
      const [mark, label] = SITE_STATUS[status] || ["?", "Not checked"];
      return `<td class="s ${status}" title="${d}: ${label}">${mark}</td>`;
    }).join("");
    return `<tr><td class="site"><strong>${esc(s.loop ? `${s.loop} ${s.name}` : s.name)}</strong><br>
      <span class="meta">${esc(siteNeeds(s))}</span></td>${cells}</tr>`;
  }).join("");
  return `<div class="calendar-wrap"><table class="calendar">
    <thead><tr><th class="site">Site</th>${head}</tr></thead><tbody>${rows}</tbody></table></div>
    <p class="meta">✓ available · × reserved · – closed · F first-come · … not yet released · blank = not checked</p>`;
}

async function load(start) {
  const end = addDays(start, 13);
  const cg = await fetchJSON(`/api/campgrounds/${encodeURIComponent(params.get("id"))}?start=${start}&end=${end}`);
  document.title = `${cg.name} · Colorado Campsite Finder`;
  const photos = cg.photos.slice(0, 6).map((p) =>
    `<img src="${esc(p.url)}" alt="${esc(p.title)}" loading="lazy">`).join("");
  const season = cg.season_open ? `Season ${cg.season_open} to ${cg.season_close}` : "";
  page.innerHTML = `
    <h2>${esc(cg.name)}</h2>
    <div class="meta">${[esc(cg.agency), cg.elevation_ft ? `${cg.elevation_ft.toLocaleString()} ft` : "", season,
      cg.reservable ? "" : "First-come, first-served"].filter(Boolean).join(" · ")}</div>
    ${cg.extra.verified === false ? `<p class="meta">Map location is approximate and not yet verified.</p>` : ""}
    <div class="book">${bookButton(cg)}</div>
    ${photos ? `<div class="photos">${photos}</div>` : ""}
    <h3>Site availability</h3>
    <div class="cal-controls">
      <label>From <input type="date" id="calStart" value="${start}"></label>
      <button type="button" id="prev">← 2 weeks</button>
      <button type="button" id="next">2 weeks →</button>
      <span class="meta">Last checked ${timeAgo(cg.last_checked)}</span>
    </div>
    ${calendar(cg)}
    ${cg.amenities.length ? `<h3>Amenities &amp; activities</h3><p>${cg.amenities.map(esc).join(" · ")}</p>` : ""}
    ${cg.description ? `<h3>About</h3><div class="description">${esc(cg.description)}</div>` : ""}
  `;
  document.getElementById("calStart").addEventListener("change", (e) => e.target.value && load(e.target.value));
  document.getElementById("prev").addEventListener("click", () => load(addDays(start, -14)));
  document.getElementById("next").addEventListener("click", () => load(addDays(start, 14)));
}

(async function init() {
  const back = document.getElementById("back");
  if (document.referrer.startsWith(location.origin + "/?")) back.href = document.referrer;
  loadMeta();
  const start = params.get("start") || isoDate(new Date());
  if (params.get("start") && params.get("end") && !params.get("nights_start")) {
    params.set("nights_start", params.get("start"));
    params.set("nights_end", params.get("end"));
    history.replaceState(null, "", `?${params}`);
  }
  try {
    await load(start);
  } catch (err) {
    page.textContent = `Couldn't load campground: ${err.message}`;
  }
})();
