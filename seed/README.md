# Colorado campground list

| File | What it is |
|---|---|
| `seed_campgrounds.csv` | 55 hand-built rows: 37 state parks (CPW), 14 Larimer County campgrounds, 3 Jefferson County Open Space sites, Chief Hosa (Denver) |
| `build_seed.py` | Regenerates the seed CSV — edit the lists in it to add/fix rows |
| `fetch_federal.py` | Pulls every Colorado federal campground (Forest Service, NPS, BLM, etc.) from RIDB and writes `federal_campgrounds.csv` + `all_campgrounds.csv` |

## Get the federal campgrounds

1. Make a free account at https://ridb.recreation.gov, open your profile, copy the API key.
2. Run:
   ```
   pip install requests
   export RIDB_API_KEY=your-key
   python fetch_federal.py
   ```
   Takes a few minutes (it pauses between requests to stay polite). Output: `all_campgrounds.csv`.

## Columns

`name, park_or_area, operator, booking_system, booking_url, source_id, nearest_town, lat, lng, camping_type, reservable, notes, verified`

- `source_id` = the ID used by that booking system (Recreation.gov facility ID; cpwshop parkID where known).
- `verified=no` rows have approximate coordinates and need checking against the booking site.

## Still to do by hand

- Fill in cpwshop `parkID` for each state park (visible in cpwshop.com URLs, e.g. State Forest = 50042).
- Confirm Chief Hosa's booking system, and whether Fishers Peak and Bonny Lake currently have open camping.
- Survey other counties/cities (Boulder, El Paso, Douglas, Mesa, etc.) — none confirmed with reservable camping yet.
