# Colorado Campsite Finder

Find Colorado campgrounds and know exactly when each one opens for booking. See [PLAN.md](PLAN.md) for the original plan
and [PLANNER.md](PLANNER.md) for the booking-day planner (current direction).

Status: **Booking-day planner prototype.** Pure Python 3.12 standard library +
SQLite, nothing to install.

## Booking calendar

`/calendar.html` (the **Booking calendar** link at the top). Pick your trip (specific dates, or every
weekend in a month) and the campgrounds you want; it puts every booking day on a month grid with the
time in Mountain Time, highlights your trip, counts down to the next booking day, and exports all of
them as one `.ics`. Add campgrounds with **+ Booking calendar** on the search page, from a campground
page, or by name on the calendar itself. The list is remembered in your browser and in the URL.

## Booking-day planner

Open any campground page, enter check-in/check-out, and click **When can I book?** You get the
exact opening time in Mountain Time with a countdown, an **Add to calendar** `.ics` reminder
(15 minutes before), and backups within 30 miles with their own opening times. Every time shows
whether its rule was verified, and when.

- Rules: `seed/booking_rules.csv` (one `*` default row per source, plus per-campground overrides).
  Edit it and reload; the app re-reads it when the file changes. Only rows with a `verified_on` date
  that match the campground itself count as verified.
- Logic and edge cases (end-of-month, leap years, daylight saving, each-night vs arrival windows):
  `campfinder/planner.py`, tests in `tests/test_planner.py`.
- API: `GET /api/campgrounds/<id>/plan?checkin=&checkout=` and `.../plan.ics?checkin=&checkout=`;
  `GET /api/booking-calendar?ids=1,2&checkin=&checkout=` (or `&month=YYYY-MM`) and `.../booking-calendar.ics`.

## Quick start

```bash
python3 manage.py import-seed    # 53 state park / county / city campgrounds from seed/
python3 manage.py serve          # open http://127.0.0.1:8000 in your Windows browser
```

Add every federal campground (needs a free key from https://ridb.recreation.gov in `.env`):

```bash
python3 manage.py import-ridb --limit 5 --no-grid   # quick test first
python3 manage.py import-ridb                       # full run, takes a while (polite 1 req/sec)
```

## Commands

| Command | What it does |
|---|---|
| `python3 manage.py serve` | Website + JSON API |
| `python3 manage.py import-seed` | Load `seed/seed_campgrounds.csv` (re-run after editing it) |
| `python3 manage.py import-ridb` | Import Colorado federal campgrounds + campsites from RIDB: `state=CO` pass plus a 50-mile radius grid so nothing is missed (weekly is plenty) |
| `python3 manage.py plan "moraine park" 2027-08-14 2027-08-16` | When a stay opens, plus backups (`--month 2027-07` for every weekend) |
| `python3 manage.py openings "moraine park" --days 7` | Nights opening for booking in the next N days |
| `python3 manage.py status` | Data counts |
| `python3 -m unittest discover -s tests` | Run tests |

## Seed data (`seed/`)

Hand-curated list for systems with no public list API. See `seed/README.md`.

- To add or fix rows: edit the lists in `seed/build_seed.py`, run `cd seed && python3 build_seed.py`,
  then `python3 manage.py import-seed`.
- Rows with `reservable=no` are skipped (e.g. closed Larimer campgrounds).
- Recreation.gov rows (Sweetwater) are skipped if RIDB already imported them; RIDB data wins.
- `seed/fetch_federal.py` is the original standalone script; `manage.py import-ridb` does the
  same thing into the app's database without needing `pip install requests`.

## Layout

```
campfinder/
  adapters/base.py     normalized format every adapter outputs
  adapters/ridb.py     federal metadata (documented RIDB API)
  adapters/seed.py     hand-curated state/county/city list from seed/
  fetch.py             polite HTTP: per-source rate limits, User-Agent, back-off
  db.py                SQLite schema (campgrounds + campsites)
  store.py             writes adapter output
  planner.py           booking-day planner: opening times, backups, .ics export
  search.py            search + campground detail queries
  server.py            JSON API + static files
static/                search page (map + list), campground page, booking calendar (calendar.html)
```

## No availability data

Live availability checking (Recreation.gov polling, the watchlist, demo data) was removed: it went
against Recreation.gov's robots.txt and isn't part of the planner. The app only uses campground
metadata plus the booking rules. Old `availability` tables are dropped from the database on startup.
