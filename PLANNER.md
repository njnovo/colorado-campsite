# Booking-Day Planner: what Niels builds

> **Pitch:** Colorado campsites sell out the minute they open, so this tells you exactly when to click and what your backups are.

This is a plan, not code. Everything listed under "You write" is yours to build. The existing app (database, importers, search, map, server) was built with AI help; see [Disclosure](#disclosure) at the end.

---

## 1. What the user does

1. Opens a campground page (for example Moraine Park).
2. Enters the check-in and check-out dates they want.
3. Sees:
   - **"Bookable starting Tue, Feb 2, 2027 at 8:00 AM (Mountain Time)"**, plus a countdown.
   - An **"Add to calendar"** button that downloads a `.ics` reminder (for example, 15 minutes before opening).
   - **Backups within 30 miles**: similar campgrounds nearby, each with its own opening time.

No availability data is involved. It only uses campground data that's already loaded, plus published booking rules.

---

## 2. What already exists (use it, don't rebuild it)

| Thing | Where | Use it for |
|---|---|---|
| 328 campgrounds with lat/lng, agency and booking URL | `campgrounds` table (`data/campsites.db`) | The campground being planned and the backup candidates |
| 4,873 federal campsites with type, RV length and hookups | `campsites` table | "Similar" backups (same site type) |
| Distance math | `db.haversine_mi()`, plus the SQL function `distance_mi(lat1, lng1, lat2, lng2)` available on every `db.connect()` | Backups within 30 miles |
| Site-type filters as SQL | `search.site_filters()` | Matching tent/RV/etc. for backups |
| Date parsing in the API | `server._date()`, `search.SearchError` | Reading `checkin` / `checkout` |
| Campground page | `static/campground.html`, `static/campground.js` | Where the planner UI goes |
| Test setup | `tests/test_campfinder.py` (`memory_db()`, `make_campground()`) | Fast tests with an in-memory database |

Run tests: `python3 -m unittest discover -s tests`
Run the app: `python3 manage.py serve`, then open http://127.0.0.1:8000

---

## 3. You write

### 3.1 Booking rules data: `seed/booking_rules.csv` (do this first)

**Problem:** every federal campground in the database has `booking_window_days = 180`. That's a placeholder default, not real data. RIDB does not publish each campground's booking window.

Build a small hand-checked table:

```
source, source_id_or_*, window_type, window_amount, release_time, release_tz, notes, verified_on
```

Ideas for `window_type`: `rolling_months` (Recreation.gov style), `rolling_days` (for example a county's 180 days), `fixed_date` (a whole season opens on one day), `lottery`, `fcfs` (no reservations).

- **Default row for Recreation.gov:** most campgrounds use a rolling 6-month window, with new dates released at 10:00 AM Eastern. Verify this on Recreation.gov's help pages and write down the URL.
- **Override rows:** add rows for the campgrounds you demo (RMNP's five, a couple of Front Range favorites). Check each one's page on recreation.gov by hand. Some differ.
- **CPW:** look up the state-park reservation window and release time on cpw.state.co.us. Don't trust any number in this plan or in `PLAN.md`; verify it and record the date you checked.
- **Larimer County:** `PLAN.md` says about 180 days. Verify it on larimer.gov.
- **Fallback:** unknown campgrounds fall back to the source default and show **"usually ___, verify on the booking site"**. Never show a made-up exact time as if it's certain.

Then write a loader: a `manage.py` command, or read the CSV when the app starts.

### 3.2 Opening-time math: `campfinder/planner.py` (the hard part)

The core function, which you design:

```
opening_time(checkin_date, rule) -> timezone-aware datetime  (or None for fcfs/lottery)
```

Things to decide, implement and **test**:

- **Which night matters.** For a multi-night stay, the date that opens *last* is the one that matters, which is usually the check-in night. Confirm how Recreation.gov treats a stay that spans the window edge, and document what you find.
- **"6 months before" when there's no matching day.** What opens the arrival date Aug 31? There's no Feb 31. Do the same for Mar 29–31 (leap and non-leap years) and Dec 31. Find out what Recreation.gov actually does, pick a rule that matches it, and write it in a comment and a test.
- **Rolling days vs months.** 180 days and 6 months give different answers. Both kinds of rules need to work.
- **Time zones.** The release is at 10:00 Eastern. Show it in Mountain Time. Use `zoneinfo` (standard library). Don't hard-code "minus 2 hours"; let `zoneinfo` handle it, and add a test across a daylight-saving change date.
- **Already open.** If the opening time is in the past, show "Already bookable", not a negative countdown.
- **Too far out.** Dates beyond the window should say "opens on ___" and still work.

**Suggested test cases (write these first):**

| Check-in | Rule | Expect |
|---|---|---|
| a normal mid-month date | 6 months, 10 AM ET | same day-of-month, 6 months earlier, 8 AM MT |
| Aug 31 | 6 months | *your researched answer* |
| Mar 31 in a leap year vs a non-leap year | 6 months | *your researched answer* |
| a date whose opening falls the day after a DST change | 6 months | correct Mountain Time |
| any | 180 days | exactly 180 days earlier |
| any | fcfs | `None` / "no reservations" |
| yesterday's opening | any | "already bookable" |

### 3.3 Calendar reminder: `.ics` export

- Endpoint idea: `GET /api/campgrounds/<id>/plan.ics?checkin=YYYY-MM-DD&checkout=YYYY-MM-DD`
- Write it yourself (it's plain text; no library needed). Read the basics of RFC 5545:
  - The `VCALENDAR` → `VEVENT` structure, with `UID`, `DTSTAMP`, `DTSTART`, `SUMMARY`, `DESCRIPTION` and `URL` (the booking link).
  - A `VALARM` reminder, for example 15 minutes before.
  - **CRLF line endings**, and long-line folding at 75 octets. Calendars are picky about both.
  - Times in UTC (`...Z`) are the simplest correct choice.
- Serve it with `Content-Type: text/calendar` and `Content-Disposition: attachment; filename=...`
- Test it by importing it into Google Calendar and your phone.

### 3.4 Backups within 30 miles

```
backups(conn, campground_id, checkin, checkout, radius_mi=30, limit=5) -> list
```

- Candidates: other reservable campgrounds within the radius, using `distance_mi` in SQL.
- "Similar": shares at least one site type with the original (tent/rv/…). Reuse `search.site_filters()` or a simple `EXISTS` on `campsites`.
- For each backup, include **its own** opening time, which may differ. A backup that opens *later* than your first choice is a great backup, and you can say so.
- Sort by distance. Exclude the original campground.
- Edge cases: campgrounds with no coordinates (3 exist), no sites in the database (51 exist), and state parks (no site types, only an agency).

### 3.5 API and UI wiring

- `server.py`: add the plan endpoint, returning JSON with the opening time (ISO format plus a friendly string), the rule used, whether it's verified, the booking URL, and the backups. Add the `.ics` endpoint.
- `campground.js`: a "Plan my booking" box with the dates, the result, a countdown, an "Add to calendar" link and the backups list.
- Show **"Rule verified on ___"** or **"Unverified: check the booking site"** next to every time.

---

## 4. Suggested weekend order

**Saturday**
1. Booking rules research plus the CSV (2–3 h). Do the demo campgrounds first.
2. Write `planner.py` tests first, then `opening_time()` until they pass (3–4 h).

**Sunday**
3. Backups query plus tests (1–2 h).
4. `.ics` export, then import it into a real calendar (1–2 h).
5. API endpoint plus the campground-page UI (2 h).
6. Record the demo (below).

**Stretch:** an "any weekend in July" mode that lists every opening day, CPW windows for all parks, and a `manage.py` command that prints this week's openings for the watchlist.

---

## 5. Cleanup before submitting (done)

Done: the live-availability code, watchlist, scheduler, demo data and availability tables were removed.

That code (`adapters/recgov.py`, the watchlist, `scheduler.py` and the "Check live availability now" button) went against Recreation.gov's robots.txt and wasn't part of the new pitch. The README's "No availability data" section explains the removal, so the repo matches the story.

---

## 6. Video demo script (about 60 s)

1. "Colorado campsites sell out the minute they open." Show a sold-out calendar.
2. Search near Estes Park, open Moraine Park, and enter Aug 14–16.
3. "Bookable Feb __ at 8:00 AM." Click **Add to calendar** and show it on your phone.
4. Scroll to the backups: "If I miss it, these open at the same time, or later."
5. The technical difficulty: the Aug 31 / leap-year / time-zone edge cases, and the tests that prove them.

---

## Disclosure

Say this accurately:

- **Built with AI (Claude Code):** the campground database and importers (RIDB federal data, the hand-curated state/county list), the search API, the map and list UI, the campground pages and the existing tests.
- **Also built with AI (Claude Code), as a first prototype of this plan:** `seed/booking_rules.csv` and its research, the rest of `campfinder/planner.py` (opening-time math, backups, `.ics` export; except the hand-written functions listed below), `tests/test_planner.py`, the plan and booking-calendar endpoints in `server.py`, the planner box in `campground.js`, the booking calendar page (`calendar.html`, `calendar.js`), removing the availability code, and the `plan` / `openings` commands.
- **Built by Niels:** `planner.months_before()` (same day N months earlier, clamped to the end of a shorter month) and `planner.opening_date()` (the day a night becomes bookable under each kind of booking rule: rolling months, rolling days, fixed date, or none).
- **Built by Avi:** `db.haversine_mi()` (miles between two map points, used for "within 30 miles" search and backups) and `planner.weekends()` (every Friday–Sunday stay in a month, used by the booking calendar's weekend mode).
