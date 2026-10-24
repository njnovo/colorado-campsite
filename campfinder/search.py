"""Search queries behind the API. Always served from our database (PLAN.md §3.5)."""
import json
from datetime import date, timedelta

from .db import SITE_TYPES, haversine_mi

MAX_NIGHTS = 30
MAX_CALENDAR_DAYS = 31


class SearchError(ValueError):
    pass


def night_dates(start: date, end: date):
    if end <= start:
        raise SearchError("check-out must be after check-in")
    if (end - start).days > MAX_NIGHTS:
        raise SearchError(f"at most {MAX_NIGHTS} nights")
    return [(start + timedelta(days=i)).isoformat() for i in range((end - start).days)]


def site_filters(types=(), min_rv_length=None, electric=False, water=False, sewer=False,
                 ada=False, pets=False):
    """SQL WHERE fragments for campsite filters on alias `s`."""
    where, params = [], []
    types = [t for t in types if t in SITE_TYPES]
    if types:
        clause = f"s.type IN ({','.join('?' * len(types))})"
        if "tent" in types:  # standard sites that also allow tents
            clause = f"({clause} OR json_extract(s.attributes, '$.tent_ok'))"
        where.append(clause)
        params += types
    if min_rv_length:
        where.append("s.max_rv_length_ft >= ?")
        params.append(int(min_rv_length))
    if electric:
        where.append("COALESCE(json_extract(s.hookups, '$.electric_amps'), 0) > 0")
    if water:
        where.append("json_extract(s.hookups, '$.water')")
    if sewer:
        where.append("json_extract(s.hookups, '$.sewer')")
    if ada:
        where.append("s.ada = 1")
    if pets:
        where.append("COALESCE(s.pets, 1) = 1")  # unknown counts as "maybe"
    return where, params


def search(conn, start: date, end: date, lat=None, lng=None, radius_mi=None,
           agency_id=None, include_fcfs=False, sort="distance", **filters):
    nights = night_dates(start, end)
    first, last = nights[0], nights[-1]
    where, params = site_filters(**filters)
    if where:  # site-level filters need site data; campgrounds without any can't match
        where.append("s.id IS NOT NULL")
    if agency_id:
        where.append("c.agency_id = ?")
        params.append(int(agency_id))
    if not include_fcfs:
        where.append("c.reservable = 1")

    rows = conn.execute(
        f"""SELECT c.id, c.name, c.lat, c.lng, c.source, c.booking_url, c.reservable,
                   a.name AS agency, s.id AS site_id, s.price_per_night,
                   COUNT(v.date) AS known_nights,
                   SUM(v.status = 'available') AS open_nights,
                   SUM(v.status = 'fcfs') AS fcfs_nights,
                   MIN(v.checked_at) AS checked_at
            FROM campgrounds c
            JOIN agencies a ON a.id = c.agency_id
            LEFT JOIN campsites s ON s.campground_id = c.id
            LEFT JOIN availability v ON v.campsite_id = s.id AND v.date BETWEEN ? AND ?
            {"WHERE " + " AND ".join(where) if where else ""}
            GROUP BY c.id, s.id""",
        [first, last, *params],
    ).fetchall()

    results = {}
    for r in rows:
        cg = results.get(r["id"])
        if cg is None:
            distance = haversine_mi(lat, lng, r["lat"], r["lng"]) if lat is not None else None
            if radius_mi and (distance is None or distance > radius_mi):
                continue
            cg = results[r["id"]] = {
                "id": r["id"], "name": r["name"], "lat": r["lat"], "lng": r["lng"],
                "agency": r["agency"], "source": r["source"], "booking_url": r["booking_url"],
                "reservable": bool(r["reservable"]),
                "distance_mi": round(distance, 1) if distance is not None else None,
                "matching_sites": 0, "open_sites": 0, "partial_sites": 0, "fcfs_sites": 0,
                "known": False, "min_price": None, "last_checked": None,
            }
        if r["site_id"] is None:
            continue
        cg["matching_sites"] += 1
        if r["known_nights"]:
            cg["known"] = True
            if cg["last_checked"] is None or r["checked_at"] < cg["last_checked"]:
                cg["last_checked"] = r["checked_at"]
        open_nights = r["open_nights"] or 0
        if open_nights == len(nights):
            cg["open_sites"] += 1
        elif open_nights:
            cg["partial_sites"] += 1
        if r["fcfs_nights"]:
            cg["fcfs_sites"] += 1
        if r["price_per_night"] is not None and (cg["min_price"] is None or r["price_per_night"] < cg["min_price"]):
            cg["min_price"] = r["price_per_night"]

    for cg in results.values():
        if not cg["reservable"]:
            cg["status"] = "fcfs"
        elif cg["open_sites"]:
            cg["status"] = "open"
        elif cg["partial_sites"]:
            cg["status"] = "partial"
        elif cg["fcfs_sites"]:  # nothing bookable, but walk-up sites exist
            cg["status"] = "fcfs"
        elif cg["known"]:
            cg["status"] = "full"
        else:
            cg["status"] = "unknown"

    status_rank = {"open": 0, "partial": 1, "full": 2, "unknown": 3, "fcfs": 4}
    sort_keys = {
        "distance": lambda c: (c["distance_mi"] is None, c["distance_mi"] or 0, c["name"]),
        "price": lambda c: (c["min_price"] is None, c["min_price"] or 0, c["name"]),
        "availability": lambda c: (status_rank[c["status"]], -c["open_sites"], c["name"]),
        "name": lambda c: c["name"],
    }
    return sorted(results.values(), key=sort_keys.get(sort, sort_keys["distance"]))


def get_campground(conn, campground_id, start: date, end: date):
    """Campground details plus a per-site calendar from start to end (inclusive)."""
    if end < start:
        raise SearchError("end must not be before start")
    end = min(end, start + timedelta(days=MAX_CALENDAR_DAYS - 1))
    row = conn.execute(
        """SELECT c.*, a.name AS agency, a.booking_system FROM campgrounds c
           JOIN agencies a ON a.id = c.agency_id WHERE c.id = ?""",
        (campground_id,),
    ).fetchone()
    if row is None:
        return None
    cg = dict(row)
    cg["amenities"] = json.loads(cg["amenities"])
    cg["photos"] = json.loads(cg["photos"])
    cg["extra"] = json.loads(cg["extra"])
    dates = [(start + timedelta(days=i)).isoformat() for i in range((end - start).days + 1)]

    sites = {}
    for s in conn.execute(
        "SELECT * FROM campsites WHERE campground_id = ? ORDER BY loop, name", (campground_id,)
    ):
        site = dict(s)
        site["hookups"] = json.loads(site["hookups"])
        site["attributes"] = json.loads(site["attributes"])
        site["availability"] = {}
        sites[site["id"]] = site

    checked = []
    for v in conn.execute(
        """SELECT v.campsite_id, v.date, v.status, v.checked_at FROM availability v
           JOIN campsites s ON s.id = v.campsite_id
           WHERE s.campground_id = ? AND v.date BETWEEN ? AND ?""",
        (campground_id, dates[0], dates[-1]),
    ):
        sites[v["campsite_id"]]["availability"][v["date"]] = v["status"]
        checked.append(v["checked_at"])

    cg["dates"] = dates
    cg["sites"] = list(sites.values())
    cg["last_checked"] = min(checked) if checked else None
    return cg
