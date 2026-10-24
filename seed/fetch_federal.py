"""Pulls every Colorado federal campground from RIDB (the database behind Recreation.gov)
and merges it with seed_campgrounds.csv into all_campgrounds.csv.

Usage:
    pip install requests
    export RIDB_API_KEY=your-key      # free: sign in at ridb.recreation.gov -> profile -> API key
    python fetch_federal.py

Two passes so nothing is missed:
  1. state=CO filter (relies on each facility's listed address)
  2. a grid of radius searches across Colorado, keeping anything whose
     coordinates fall inside the state's borders
"""
import csv
import os
import sys
import time

import requests

BASE = "https://ridb.recreation.gov/api/v1/facilities"
PAGE = 50
PAUSE = 1.2  # seconds between requests; RIDB rate-limits
USER_AGENT = "ColoradoCampsiteFinder/0.1 (campground list build)"

# Colorado bounding box (the state is a rectangle)
LAT_MIN, LAT_MAX = 36.99, 41.01
LNG_MIN, LNG_MAX = -109.06, -102.04

COLUMNS = [
    "name", "park_or_area", "operator", "booking_system", "booking_url",
    "source_id", "nearest_town", "lat", "lng", "camping_type",
    "reservable", "notes", "verified",
]


def in_colorado(lat, lng):
    return LAT_MIN <= lat <= LAT_MAX and LNG_MIN <= lng <= LNG_MAX


def get_pages(session, params):
    offset = 0
    while True:
        p = dict(params, limit=PAGE, offset=offset, full="true")
        for attempt in range(5):
            r = session.get(BASE, params=p, timeout=30)
            if r.status_code == 429 or r.status_code >= 500:
                time.sleep(2 ** attempt * 5)
                continue
            r.raise_for_status()
            break
        else:
            raise RuntimeError(f"RIDB kept failing for {p}")
        data = r.json()
        yield from data.get("RECDATA", [])
        total = data.get("METADATA", {}).get("RESULTS", {}).get("TOTAL_COUNT", 0)
        offset += PAGE
        time.sleep(PAUSE)
        if offset >= total:
            break


def to_row(f):
    org = (f.get("ORGANIZATION") or [{}])[0].get("OrgName", "")
    area = (f.get("RECAREA") or [{}])[0].get("RecAreaName", "")
    fid = str(f["FacilityID"])
    reservable = bool(f.get("Reservable"))
    return {
        "name": f.get("FacilityName", "").strip(),
        "park_or_area": area,
        "operator": org,
        "booking_system": "recreation.gov" if reservable else "none (first-come)",
        "booking_url": f"https://www.recreation.gov/camping/campgrounds/{fid}",
        "source_id": fid,
        "nearest_town": "",
        "lat": f.get("FacilityLatitude"),
        "lng": f.get("FacilityLongitude"),
        "camping_type": "developed",
        "reservable": "yes" if reservable else "no",
        "notes": "",
        "verified": "yes",  # comes straight from the agency's own data
    }


def main():
    key = os.environ.get("RIDB_API_KEY")
    if not key:
        sys.exit("Set RIDB_API_KEY first (free key from ridb.recreation.gov).")
    s = requests.Session()
    s.headers.update({"apikey": key, "User-Agent": USER_AGENT})

    found = {}

    def keep(f):
        if f.get("FacilityTypeDescription") != "Campground":
            return
        lat, lng = f.get("FacilityLatitude") or 0, f.get("FacilityLongitude") or 0
        addr_states = {a.get("AddressStateCode") for a in f.get("FACILITYADDRESS") or []}
        if in_colorado(lat, lng) or "CO" in addr_states:
            found[str(f["FacilityID"])] = f

    print("Pass 1: state=CO ...")
    for f in get_pages(s, {"state": "CO"}):
        keep(f)
    print(f"  {len(found)} campgrounds")

    print("Pass 2: radius grid ...")
    lat = LAT_MIN + 0.5
    while lat < LAT_MAX:
        lng = LNG_MIN + 0.5
        while lng < LNG_MAX:
            for f in get_pages(s, {"latitude": round(lat, 2), "longitude": round(lng, 2), "radius": 50}):
                keep(f)
            lng += 1.0
        lat += 1.0
    print(f"  {len(found)} campgrounds after grid")

    rows = sorted((to_row(f) for f in found.values()), key=lambda r: r["name"])
    with open("federal_campgrounds.csv", "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=COLUMNS)
        w.writeheader()
        w.writerows(rows)

    # Merge with the hand-built state/county list (skip duplicates by Recreation.gov ID)
    fed_ids = {r["source_id"] for r in rows}
    with open("seed_campgrounds.csv", newline="") as fh:
        seed = [r for r in csv.DictReader(fh)
                if not (r["booking_system"] == "recreation.gov" and r["source_id"] in fed_ids)]
    with open("all_campgrounds.csv", "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=COLUMNS)
        w.writeheader()
        w.writerows(seed + rows)

    res = sum(r["reservable"] == "yes" for r in rows)
    print(f"Done: {len(rows)} federal campgrounds ({res} reservable). "
          f"all_campgrounds.csv has {len(seed) + len(rows)} rows.")


if __name__ == "__main__":
    main()
