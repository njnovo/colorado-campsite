# Colorado Campsite Finder — Project Plan

*Drafted October 2026*

## 1. The problem

Reservable campsites in Colorado are spread across several unrelated booking systems:

| Who runs the campground | Where you book today | Roughly what's there |
|---|---|---|
| Federal (US Forest Service, National Park Service incl. Rocky Mountain NP, BLM, Bureau of Reclamation, Army Corps) | **Recreation.gov** | The bulk of mountain campgrounds |
| Colorado Parks & Wildlife (state parks) | **cpwshop.com** (run by vendor Aspira) | 40+ state parks, 4,000+ sites, cabins, yurts |
| Counties (e.g. Larimer County: Horsetooth, Carter Lake, Hermit Park, Pinewood, Flatiron) | Each county's own portal — Larimer uses **larimercamping.com** (also Aspira/ReserveAmerica) | Smaller but very popular Front Range sites |
| Cities / special districts / private (KOA, Hipcamp, private RV parks) | Their own sites | Scattered |

Someone looking for "any open tent site within 2 hours of Denver on July 18–20" currently has to search 3–6 websites with different date pickers, site-type labels and maps.

**Goal:** one site where you enter dates, location/radius and what you need (tent, RV length, hookups, pets…), and see live availability from every system on one map/list — then click through to the official site to book.

**Non-goal:** we do not take bookings or payments. We always send the user to the official booking page. This keeps us legally simple and avoids competing with the agencies.

---

## 2. Core features

### MVP (v1)
1. **Search** — date range (check-in/check-out), number of nights, flexible-dates toggle (e.g. "any weekend in July").
2. **Filters** — site type (tent / RV / cabin / yurt / group), max RV length, electric/water/sewer hookups, ADA accessible, pets allowed, managing agency.
3. **Map + list view** — campgrounds as pins colored by availability (green = open for all requested nights, yellow = partial, gray = full). List sortable by distance and price.
4. **Campground page** — description, photos, amenities, elevation, season dates, a per-site availability calendar, and a big **"Book on Recreation.gov / CPW / Larimer County →"** deep link.
5. **"Last checked X minutes ago"** shown everywhere. Availability changes in seconds; honesty about freshness is essential.

### v2
6. **Cancellation alerts** — "Email/text me when any site at Moraine Park opens for Aug 8–10." This is the feature people will actually pay for or come back for.
7. **Booking-window calendar** — "Sites for July 4th at state parks open on Jan 4 at 8am MT." Each system has its own rolling window (CPW: 6 months ahead; Larimer County: ~180 days; Recreation.gov varies by campground).
8. **Saved searches / favorites** (requires accounts).

### Later / nice-to-have
- First-come-first-served and dispersed camping info layer (no availability data, just "here's where it is and the rules").
- Fire-ban and road-closure overlays (county fire restrictions, CDOT).
- Campground closure notices (e.g. Larimer County regularly closes loops for construction).

---

## 3. How we check each website (data sources)

The architecture is one **adapter per booking system**. Every adapter outputs the same normalized format (see §4), so adding a new county later is just writing one more adapter.

### 3.1 Recreation.gov (federal) — easiest, do first

**Campground metadata (official, documented): RIDB API**
- Base URL: `https://ridb.recreation.gov/api/v1`
- Free API key: sign up at ridb.recreation.gov → profile → API key. Sent in the `apikey` header.
- Endpoints we need: `/facilities?state=CO&activity=CAMPING`, `/facilities/{id}/campsites`, `/campsites/{id}` (attributes like driveway length, hookups, max people), `/media` (photos), `/facilities/{id}/facilityaddresses`.
- Data is public, Creative Commons Attribution licensed → credit "Data from Recreation.gov / RIDB".
- Refresh: once a week is plenty.

**Live availability (public but undocumented)**
- `GET https://www.recreation.gov/api/camps/availability/campground/{facilityId}/month?start_date=2027-07-01T00:00:00.000Z`
  - Returns every site in the campground with a status per date for that calendar month: `Available`, `Reserved`, `Not Available`, `Not Reservable` (first-come), `Open` (not yet released), etc.
  - One request = one campground × one month.
- `GET https://www.recreation.gov/api/camps/availability/campsite/{campsiteId}/all` — ~18 months for one site; useful for alerts on a single site.
- No auth needed today, but it is **undocumented and can change or be locked down** without notice. Plan for it:
  - Wrap it in the adapter with schema validation; alert ourselves if the response shape changes.
  - Rate-limit ourselves (start at ~1 request/sec, with jitter), send an honest `User-Agent` with a contact email, and back off on 429/5xx.
  - Read Recreation.gov's Terms of Use before launch; consider emailing their team to ask about sanctioned access.

### 3.2 Colorado Parks & Wildlife (state parks) — hardest, most important

- Booking runs on **cpwshop.com**, operated by vendor **Aspira** (the ReserveAmerica lineage). There is **no public API**.
- **Heads-up:** CPW has been selecting a new licensing & reservations vendor (it was on the Parks & Wildlife Commission agenda in 2025), and industry reporting says a contract with Brandt was signed in 2026 with a launch planned for 2027. **Treat the current CPW integration as temporary** — keep that adapter isolated so it can be rewritten when the platform changes. Verify the timeline with CPW directly.
- How to check it:
  1. **Investigate first (Phase 0):** open cpwshop.com in a browser with DevTools → Network tab, run a campsite search, and see what requests the page makes. Aspira sites usually load availability via JSON/XHR calls behind the page; if so, the adapter calls those same endpoints.
  2. If availability is only in server-rendered HTML, parse the HTML (e.g. with Cheerio / BeautifulSoup).
  3. If it requires JavaScript rendering, fall back to a headless browser (Playwright). Slower and heavier — use only if needed.
- Be gentle: CPW is a small state agency's system. Low request rates, cache aggressively, poll popular parks more often than quiet ones.
- **Best option long-term: ask.** Email CPW (and, later, Brandt) explaining the project and asking for a data feed or permission. Public agencies sometimes welcome tools that send them bookings, and the vendor switch is a natural time to ask for an API.
- CPW also publishes a "weekend availability" view — useful as a quick sanity check against our data.

### 3.3 County systems

- **Larimer County** — larimercamping.com, also on the Aspira/ReserveAmerica platform. Likely the same adapter logic as CPW with different site IDs. ~400 campsites. Rules worth surfacing: 180-day window, 14-night max in 30 days, $8.75 reservation fee, no walk-ups.
- **Phase 0 task:** survey other counties and cities with reservable camping and record which platform each uses (candidates to check: Boulder County, Jefferson County Open Space, Denver Mountain Parks, El Paso County, Douglas County, Mesa County, Grand County, Pueblo, municipal reservoirs). Many use the same handful of vendors (Aspira, Brandt, Camis, Tyler/RecDesk, US eDirect), so one adapter per *vendor* may cover several agencies.

### 3.4 Private campgrounds (KOA, Hipcamp, private RV parks)

- Most prohibit scraping in their terms. **Don't scrape them in v1.**
- List them as "Private — check availability on their site" with a link. Revisit affiliate/partner programs later (some offer them, which could also fund the site).

### 3.5 Polite-scraping rules (apply to every adapter)

- Respect `robots.txt` and terms of use; read them for each source before building its adapter.
- Hard per-source rate limits in a shared limiter; exponential back-off on errors.
- Identify ourselves: `User-Agent: ColoradoCampsiteFinder/1.0 (contact@yourdomain)`.
- Never log in as a user, never automate booking, never hold carts.
- Cache everything; serve user searches **from our database**, never by hitting the source live per user request.

---

## 4. Normalized data model

```
agencies        id, name, booking_system, website
campgrounds     id, agency_id, source, source_id, name, lat, lng, elevation_ft,
                description, season_open, season_close, booking_url_template,
                booking_window_days, amenities (json), photos (json), updated_at
campsites       id, campground_id, source_id, name/number, loop, type
                (tent|rv|cabin|yurt|group|equestrian|boat-in), max_rv_length_ft,
                max_people, hookups (json: electric_amps, water, sewer),
                ada, pets, price_per_night, attributes (json)
availability    campsite_id, date, status (available|reserved|closed|fcfs|not_released),
                checked_at                       -- PRIMARY KEY (campsite_id, date)
poll_runs       id, source, campground_id, month, started_at, ok, error, http_status
alerts          id, user_id/email, campground_id or campsite_id, date_start, date_end,
                filters (json), last_notified_at, active
```

Notes:
- Store availability per **site per night**. "Available for July 18–20" = every night in range is `available` for the same site.
- Keep only a rolling window (today → ~13 months); delete old rows nightly.
- Record status **changes** in a small `availability_events` table — that's what powers alerts and tells you which campgrounds churn the most.

---

## 5. Polling schedule (how often to check)

Rough sizing (verify in Phase 0): a few hundred reservable campgrounds statewide on Recreation.gov, ~40 state parks, a dozen-plus county campgrounds.

Example for Recreation.gov: 300 campgrounds × 7 months = **2,100 requests for one full sweep**. Doing that every 15 minutes is ~200k requests/day — too aggressive. So tier it:

| Tier | Which campgrounds/months | How often |
|---|---|---|
| Hot | Popular campgrounds (RMNP, Front Range state parks, Horsetooth) + anything with an active user alert, next 60 days | every 5–10 min |
| Warm | Everything else, next 60 days; popular ones further out | every 30–60 min |
| Cold | Far-future months, unpopular campgrounds, off-season | every 6–24 h |
| Window opening | The exact date that just came into the booking window (e.g. 6 months out) | burst right at release time, then drop to normal |

Adjust tiers automatically using `availability_events` (campgrounds that change a lot get checked more).

---

## 6. Tech stack (suggested — swap for what you know)

- **Frontend:** Next.js (React) + Tailwind; map with MapLibre GL + free OpenStreetMap/MapTiler tiles (avoids Google Maps costs).
- **API:** Next.js API routes or a small FastAPI/Express service.
- **Database:** Postgres (with PostGIS for "within X miles" queries). Supabase or Neon are cheap hosted options.
- **Pollers:** a separate worker process (Node or Python) with a job queue (BullMQ + Redis, or Postgres-based like pg-boss / Celery). Each adapter = one job type.
- **Headless browser (only if needed for CPW/counties):** Playwright, run on the worker only.
- **Alerts:** email via Resend/Postmark/SES; SMS via Twilio later.
- **Hosting:** Vercel/Netlify for the site; Fly.io / Railway / Render for the worker and Redis. Expect ~$20–60/month at MVP scale.
- **Monitoring:** Sentry for errors, plus a simple internal "source health" page: last successful poll per source, error rate, response-shape changes.

---

## 7. Build phases

**Phase 0 — Research (1–2 weeks)**
- [ ] Get a RIDB API key; pull all Colorado camping facilities; count them.
- [ ] Hit the Recreation.gov month-availability endpoint for 3–4 campgrounds; document the response.
- [ ] Inspect cpwshop.com network traffic; document how availability loads and how site IDs / park IDs work.
- [ ] Same for larimercamping.com.
- [ ] Survey other Colorado counties/cities; build a spreadsheet: agency → platform → URL → # sites → booking window.
- [ ] Read terms of use / robots.txt for each source; note restrictions.
- [ ] Email CPW about data access and the upcoming platform change.

**Phase 1 — Federal-only MVP (3–4 weeks)**
- [ ] Database schema + RIDB import job.
- [ ] Recreation.gov availability adapter + tiered scheduler.
- [ ] Search page, filters, map/list, campground page, deep links.
- [ ] Deploy; use it yourself for real trips.

**Phase 2 — State parks + Larimer (3–4 weeks)**
- [ ] CPW adapter (and Larimer, likely shared Aspira logic).
- [ ] Metadata for state parks (CPW site lists, amenities, photos — may need manual curation).
- [ ] Source-health dashboard.

**Phase 3 — Alerts (2–3 weeks)**
- [ ] Simple accounts (email magic link).
- [ ] Alert creation UI; change-detection → email notifications; unsubscribe; rate-limit notifications.

**Phase 4 — More sources & polish**
- [ ] Additional counties/cities by vendor.
- [ ] Booking-window calendar, flexible-date search, fire-ban layer.
- [ ] Rewrite CPW adapter when the new platform launches.

---

## 8. Risks & how to handle them

| Risk | Mitigation |
|---|---|
| Recreation.gov changes or locks the undocumented endpoint | Schema checks + alerting; keep RIDB metadata working so the site degrades to "check on Recreation.gov" links instead of breaking; ask for sanctioned access |
| CPW moves to a new reservation platform (expected ~2027) | Isolated adapter; contact CPW early; show "temporarily unavailable — book at CPW" banner during the switch |
| Getting blocked for too many requests | Conservative rate limits, caching, tiered polling, honest User-Agent, back-off |
| Terms-of-use / legal issues | Read ToS for every source; read-only, no bookings, always link to the official site; take down any source that objects; consider a quick consult with a lawyer before monetizing |
| Stale data frustrates users ("it said open but it's gone") | Always show "last checked"; recheck a campground on demand (rate-limited) when someone opens its page |
| Alert spam / bots creating thousands of alerts | Cap alerts per user, require email verification, CAPTCHA on signup |
| Bad metadata (wrong RV lengths, missing hookups) | Prefer per-site data from the source; "report a problem" link on each campground |

---

## 9. Open questions

- Free forever, donation-supported, or a paid tier for alerts (like Campnab / Campflare-style services)? Decide before Phase 3.
- Colorado-only, or design for expansion to Utah / Wyoming / New Mexico later? (The adapter design makes this easy; just keep `state` in the schema.)
- Include first-come-first-served campgrounds in the map from day one (with "no reservations — arrive early" labels)?
- Domain name and branding.

---

## 10. References

- RIDB (federal recreation data API): https://ridb.recreation.gov
- Recreation.gov: https://www.recreation.gov
- CPW camping / reservations info: https://cpw.state.co.us/thingstodo/Pages/camping.aspx
- CPW online reservations (Aspira): https://cpw.state.co.us/buyapply/Pages/ReservationOnline.aspx
- Larimer County campgrounds & reservation rules: https://www.larimer.gov/naturalresources/reservations/campgrounds
