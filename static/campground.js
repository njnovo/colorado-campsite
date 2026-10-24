// Campground page: details, booking-day planner, site list, deep link to book.

const params = new URLSearchParams(location.search);
const page = document.getElementById("page");

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
  if (!cg.booking_url) return `<p class="meta">No booking link on file.</p>`;
  return `<a class="button" href="${esc(cg.booking_url)}" target="_blank" rel="noopener">
    Book on ${esc(cg.booking_system)} →</a>
    <p class="meta">We don't take bookings. Always confirm the rules on the official site.</p>`;
}

function siteList(cg) {
  if (!cg.sites.length) return `<p class="meta">No campsite details for this campground yet.</p>`;
  const counts = {};
  for (const site of cg.sites) counts[site.type] = (counts[site.type] || 0) + 1;
  const rows = cg.sites.map((site) => `<tr><td>${esc(site.loop ? `${site.loop} ${site.name}` : site.name)}</td>
    <td>${esc(siteNeeds(site))}</td></tr>`).join("");
  return `<p>${Object.entries(counts).map(([t, n]) => `${n} ${esc(t)}`).join(" · ")}</p>
    <details><summary>All ${cg.sites.length} sites</summary>
      <div class="calendar-wrap"><table class="sites"><tbody>${rows}</tbody></table></div></details>`;
}

async function load() {
  const cg = await fetchJSON(`/api/campgrounds/${encodeURIComponent(params.get("id"))}`);
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
    <section class="planner">
      <h3>Plan my booking</h3>
      <form id="planForm" class="cal-controls">
        <label>Check-in <input type="date" id="planIn" required value="${esc(planDates.checkin || "")}"></label>
        <label>Check-out <input type="date" id="planOut" required value="${esc(planDates.checkout || "")}"></label>
        <button type="submit" class="primary">When can I book?</button>
      </form>
      <div id="planResult"></div>
    </section>
    ${photos ? `<div class="photos">${photos}</div>` : ""}
    <h3>Sites</h3>
    ${siteList(cg)}
    ${cg.amenities.length ? `<h3>Amenities &amp; activities</h3><p>${cg.amenities.map(esc).join(" · ")}</p>` : ""}
    ${cg.description ? `<h3>About</h3><div class="description">${esc(cg.description)}</div>` : ""}
  `;
  document.getElementById("planIn").addEventListener("change", (e) => {
    const out = document.getElementById("planOut");
    if (e.target.value && (!out.value || out.value <= e.target.value)) out.value = addDays(e.target.value, 2);
  });
  document.getElementById("planForm").addEventListener("submit", (e) => {
    e.preventDefault();
    planDates.checkin = document.getElementById("planIn").value;
    planDates.checkout = document.getElementById("planOut").value;
    showPlan(cg.id);
  });
  if (planDates.checkin && planDates.checkout) showPlan(cg.id);
}

// --- Booking-day planner ---

const planDates = {};
let countdownTimer = null;

function verifiedNote(p) {
  if (p.verified) return `<span class="verified">Rule verified on ${esc(p.rule.verified_on)}</span>`;
  return `<span class="unverified">Unverified: check the booking site</span>`;
}

function openingLine(p) {
  if (p.status === "no_reservations") return "No reservations: first-come, first-served.";
  if (p.status === "lottery") return "Booked by lottery. See the booking site for dates.";
  if (p.status === "open") return "Already bookable.";
  return `Bookable starting <strong>${esc(p.opens_at_text)}</strong>`;
}

function backupLine(b) {
  const compare = {
    already_open: "already bookable",
    same: "opens at the same time",
    later: "opens later: a good fallback",
    earlier: "opens earlier: book this first?",
  }[b.compared_to_first_choice] || "";
  const when = b.status === "open" ? "Already bookable" : `Opens ${esc(b.opens_at_text)}`;
  return `<li><a href="/campground.html?id=${b.id}"><strong>${esc(b.name)}</strong></a>
    <span class="meta">${b.distance_mi} mi · ${esc(b.agency)}${b.site_types_known ? "" : " · site types unknown"}</span><br>
    ${when}${compare ? ` <span class="meta">(${compare})</span>` : ""}
    ${b.time_known ? "" : `<span class="meta"> · time of day not published</span>`}
    · ${b.rule.verified_on && !b.rule.is_default ? `<span class="verified">verified ${esc(b.rule.verified_on)}</span>`
      : `<span class="unverified">unverified</span>`}</li>`;
}

async function showPlan(id) {
  const box = document.getElementById("planResult");
  clearInterval(countdownTimer);
  box.textContent = "Working it out…";
  const qs = `checkin=${planDates.checkin}&checkout=${planDates.checkout}`;
  let p;
  try {
    p = await fetchJSON(`/api/campgrounds/${id}/plan?${qs}`);
  } catch (err) {
    box.innerHTML = `<p class="unverified">${esc(err.message)}</p>`;
    return;
  }
  const upcoming = p.status === "upcoming";
  box.innerHTML = `
    <p class="plan-when">${openingLine(p)}</p>
    ${upcoming ? `<p class="countdown" id="countdown">${countdownText(p.opens_at)}</p>` : ""}
    ${p.rule ? `<p class="meta">${esc(p.rule.summary)} · ${verifiedNote(p)}${p.rule.url
      ? ` · <a href="${esc(p.rule.url)}" target="_blank" rel="noopener">source</a>` : ""}</p>` : ""}
    ${p.rule && p.rule.notes ? `<p class="meta">${esc(p.rule.notes)}</p>` : ""}
    ${p.opens_at && !p.time_known ? `<p class="meta">The booking site doesn't publish a release time; check it on the morning of that day.</p>` : ""}
    ${p.full_stay_opens_at_text ? `<p class="meta">Each night opens separately: your last night opens
      ${esc(p.full_stay_opens_at_text)}${p.full_stay_status === "open" ? " (already open)" : ""}.</p>` : ""}
    <div class="plan-actions">
      ${upcoming ? `<a class="button" href="/api/campgrounds/${id}/plan.ics?${qs}">Add to my calendar (.ics)</a>` : ""}
      ${p.status !== "no_reservations" ? `<a class="button secondary" id="toBookingCal"
        href="${calendarUrl([...new Set([...savedIds(), id])], planDates.checkin, planDates.checkout)}">See it on the booking calendar</a>` : ""}
    </div>
    ${upcoming ? `<p class="meta">The .ics reminder goes off 15 minutes before it opens.</p>` : ""}
    <h4>Backups within 30 miles</h4>
    ${p.backups.length ? `<ul class="backups">${p.backups.map(backupLine).join("")}</ul>`
      : `<p class="meta">No similar reservable campgrounds within 30 miles${p.site_types.length ? "" : " (or this campground has no map location)"}.</p>`}
  `;
  document.getElementById("toBookingCal")?.addEventListener("click", () => setSavedIds([...savedIds(), id]));
  if (upcoming) {
    countdownTimer = setInterval(() => {
      const el = document.getElementById("countdown");
      if (!el) return clearInterval(countdownTimer);
      el.textContent = countdownText(p.opens_at);
    }, 1000);
  }
}

(async function init() {
  const back = document.getElementById("back");
  if (document.referrer.startsWith(location.origin + "/?")) back.href = document.referrer;
  loadMeta();
  if (params.get("start") && params.get("end")) {
    planDates.checkin = params.get("start");
    planDates.checkout = params.get("end");
  }
  try {
    await load();
  } catch (err) {
    page.textContent = `Couldn't load campground: ${err.message}`;
  }
})();
