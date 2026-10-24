# Colorado Campsite Finder

One search across Colorado's campground booking systems. See [PLAN.md](PLAN.md) for the full plan.

Status: **Phase 1 scaffold.** Pure Python 3.12 standard library + SQLite, nothing to install.

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

Want fake data with availability to try the UI? `python3 manage.py seed-demo` (remove with `--clear`).

## Commands

| Command | What it does |
|---|---|
| `python3 manage.py serve` | Website + JSON API |
| `python3 manage.py import-seed` | Load `seed/seed_campgrounds.csv` (re-run after editing it) |
| `python3 manage.py import-ridb` | Import Colorado federal campgrounds + campsites from RIDB: `state=CO` pass plus a 50-mile radius grid so nothing is missed (weekly is plenty) |
| `python3 manage.py watch add "moraine park"` | Add campgrounds to the watchlist (`remove`, `list`; `--all` for every match) |
| `python3 manage.py poll [--loop]` | Check availability for watched campgrounds (`-v` before `poll` for logging) |
| `python3 manage.py status` | Data counts and source health |
| `python3 manage.py prune` | Delete availability for past dates |
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
  adapters/recgov.py   Recreation.gov live availability (OFF by default, see below)
  fetch.py             polite HTTP: per-source rate limits, User-Agent, back-off
  db.py                SQLite schema (PLAN.md §4)
  store.py             writes adapter output, logs availability changes
  scheduler.py         tiered polling (PLAN.md §5)
  search.py            search + campground detail queries
  server.py            JSON API + static files
  demo.py              fake demo data
static/                search page (MapLibre map + list) and campground page
```

## Recreation.gov availability: personal watchlist only

`https://www.recreation.gov/robots.txt` has `Disallow: /api/*` and `Crawl-delay: 10`
(checked 2026-10-23). The availability endpoint (PLAN.md §3.1) is under `/api/`. Decision
(2026-10-23): poll a small personal watchlist only, at 1 request / 10 s, `WATCH_DAYS` ahead.
This goes against robots.txt, so Recreation.gov could block it; it is not OK for a public
launch without sanctioned access. Turn it off with `RECGOV_AVAILABILITY_ENABLED=false`.

At 10 s per request, each watched campground costs ~4 requests per round (one per month),
so keep the list short (5 campgrounds = about 3-4 minutes per round).
