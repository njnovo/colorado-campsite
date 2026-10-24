"""Search queries behind the API. Always served from our database."""
import json
from datetime import date, timedelta

from .db import SITE_TYPES, haversine_mi

MAX_NIGHTS = 30


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
    """Campgrounds matching the filters. The dates are only validated here; the server adds
    each result's booking-day opening time for them."""
    night_dates(start, end)
    where, params = site_filters(**filters)
    if where:  # site-level filters need site data; campgrounds without any can't match
        where.append("s.id IS NOT NULL")
    if agency_id:
        where.append("c.agency_id = ?")
        params.append(int(agency_id))
    if not include_fcfs:
        where.append("c.reservable = 1")

    rows = conn.execute(
        f"""SELECT c.id, c.name, c.lat, c.lng, c.source, c.source_id, c.booking_url, c.reservable,
                   a.name AS agency, COUNT(s.id) AS matching_sites, MIN(s.price_per_night) AS min_price
            FROM campgrounds c
            JOIN agencies a ON a.id = c.agency_id
            LEFT JOIN campsites s ON s.campground_id = c.id
            {"WHERE " + " AND ".join(where) if where else ""}
            GROUP BY c.id""",
        params,
    ).fetchall()

    results = []
    for r in rows:
        distance = haversine_mi(lat, lng, r["lat"], r["lng"]) if lat is not None else None
        if radius_mi and (distance is None or distance > radius_mi):
            continue
        results.append({
            **dict(r), "reservable": bool(r["reservable"]),
            "distance_mi": round(distance, 1) if distance is not None else None,
        })

    sort_keys = {
        "distance": lambda c: (c["distance_mi"] is None, c["distance_mi"] or 0, c["name"]),
        "price": lambda c: (c["min_price"] is None, c["min_price"] or 0, c["name"]),
        "name": lambda c: c["name"],
    }
    return sorted(results, key=sort_keys.get(sort, sort_keys["distance"]))


def find_by_name(conn, query, limit=20):
    """Campgrounds whose name contains every word of `query` (for pickers)."""
    words = query.split()
    if not words:
        return []
    return [dict(r) for r in conn.execute(
        """SELECT c.id, c.name, a.name AS agency, c.reservable FROM campgrounds c
           JOIN agencies a ON a.id = c.agency_id WHERE """
        + " AND ".join("c.name LIKE ?" for _ in words) + " ORDER BY c.name LIMIT ?",
        [*(f"%{w}%" for w in words), limit],
    )]


def get_campground(conn, campground_id):
    """Campground details plus its campsites."""
    row = conn.execute(
        """SELECT c.*, a.name AS agency, a.booking_system FROM campgrounds c
           JOIN agencies a ON a.id = c.agency_id WHERE c.id = ?""",
        (campground_id,),
    ).fetchone()
    if row is None:
        return None
    cg = dict(row)
    for key in ("amenities", "photos", "extra"):
        cg[key] = json.loads(cg[key])
    cg["sites"] = []
    for s in conn.execute(
        "SELECT * FROM campsites WHERE campground_id = ? ORDER BY loop, name", (campground_id,)
    ):
        site = dict(s)
        site["hookups"] = json.loads(site["hookups"])
        site["attributes"] = json.loads(site["attributes"])
        cg["sites"].append(site)
    return cg
