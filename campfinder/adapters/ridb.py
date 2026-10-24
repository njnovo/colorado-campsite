"""RIDB adapter: federal campground + campsite metadata (PLAN.md §3.1).

Documented API, free key: https://ridb.recreation.gov  (key sent in `apikey` header).
Data is CC-BY licensed: credit "Data from Recreation.gov / RIDB".
"""
import html
import re

from .. import config, fetch
from .base import Agency, Campground, Campsite, SchemaError

SOURCE = "recgov"  # campgrounds imported here are polled by the recgov adapter
BASE_URL = "https://ridb.recreation.gov/api/v1"
PAGE_SIZE = 50
DEFAULT_BOOKING_WINDOW_DAYS = 180  # varies per campground on Recreation.gov


def _get(path, params, api_key):
    _, data = fetch.get_json("ridb", BASE_URL + path, params, headers={"apikey": api_key})
    if not isinstance(data, dict) or not isinstance(data.get("RECDATA"), list):
        raise SchemaError(f"RIDB {path}: expected RECDATA list")
    return data


def paginate(path, params, api_key):
    offset = 0
    while True:
        data = _get(path, {**params, "limit": PAGE_SIZE, "offset": offset}, api_key)
        records = data["RECDATA"]
        yield from records
        total = data.get("METADATA", {}).get("RESULTS", {}).get("TOTAL_COUNT", 0)
        offset += len(records)
        if not records or offset >= total:
            return


# --- normalization (pure functions, unit tested) ---------------------------

def clean_html(text):
    text = re.sub(r"<(br|/p|/h\d|/li)\s*/?>", "\n", text or "", flags=re.I)
    text = html.unescape(re.sub(r"<[^>]+>", "", text))
    return re.sub(r"\n\s*\n+", "\n\n", text).strip()


SMALL_WORDS = {"a", "an", "and", "at", "by", "for", "in", "of", "on", "the", "to"}


def title_name(name):
    """RIDB names are ALL CAPS: 'ANGEL OF SHAVANO (CO)' -> 'Angel of Shavano (CO)'."""
    words = (name or "").strip().title().split()
    words = [w.lower() if i and w.lower() in SMALL_WORDS else w for i, w in enumerate(words)]
    return re.sub(r"\((\w{2})\)", lambda m: f"({m.group(1).upper()})", " ".join(words))


def _yes(value):
    return str(value).strip().lower() in ("y", "yes", "true", "1")


def _int(value):
    match = re.search(r"\d+", str(value or ""))
    return int(match.group()) if match else None


def site_type(campsite_type, rv_allowed):
    """Map RIDB CampsiteType (e.g. 'STANDARD ELECTRIC') to our site types.

    Returns None for sites we don't list (management, day use, unknown).
    """
    t = (campsite_type or "").upper()
    if "MANAGEMENT" in t or "DAY USE" in t:
        return None
    for needle, kind in (("CABIN", "cabin"), ("YURT", "yurt"), ("GROUP", "group"),
                         ("EQUESTRIAN", "equestrian"), ("BOAT", "boat-in")):
        if needle in t:
            return kind
    if t.startswith("RV"):
        return "rv"
    if "TENT" in t or "WALK TO" in t or "HIKE TO" in t:
        return "tent"
    if "STANDARD" in t:
        return "rv" if rv_allowed else "tent"
    return None


RV_EQUIPMENT = ("rv", "trailer", "fifth wheel", "motorhome", "pickup camper", "pop up")


def normalize_campsite(raw):
    attrs = {a.get("AttributeName", ""): a.get("AttributeValue", "")
             for a in raw.get("ATTRIBUTES") or []}
    equipment = raw.get("PERMITTEDEQUIPMENT") or []
    rv_lengths = [int(e.get("MaxLength") or 0) for e in equipment
                  if any(k in (e.get("EquipmentName") or "").lower() for k in RV_EQUIPMENT)]
    max_rv = max(rv_lengths) if rv_lengths else None
    if not max_rv:
        max_rv = _int(attrs.get("Max Vehicle Length")) or _int(attrs.get("Driveway Length"))

    kind = site_type(raw.get("CampsiteType"), rv_allowed=bool(rv_lengths))
    if kind is None or (raw.get("TypeOfUse") or "Overnight").lower() == "day":
        return None

    tent_ok = kind == "tent" or any("tent" in (e.get("EquipmentName") or "").lower() for e in equipment)
    pets_raw = attrs.get("Pets Allowed")
    hookups = {}
    amps = [int(a) for a in re.findall(r"\d+", str(attrs.get("Electricity Hookup", "")))]
    if amps:
        hookups["electric_amps"] = max(amps)
    if _yes(attrs.get("Water Hookup", "")):
        hookups["water"] = True
    if _yes(attrs.get("Sewer Hookup", "")):
        hookups["sewer"] = True

    return Campsite(
        source_id=str(raw["CampsiteID"]),
        name=raw.get("CampsiteName") or "",
        loop=raw.get("Loop") or "",
        type=kind,
        max_rv_length_ft=max_rv if kind in ("rv", "group") else None,
        max_people=_int(attrs.get("Max Num of People")),
        hookups=hookups,
        ada=bool(raw.get("CampsiteAccessible")),
        pets=None if pets_raw is None else not str(pets_raw).strip().lower().startswith("n"),
        attributes={"tent_ok": tent_ok, "ridb_type": raw.get("CampsiteType")},
    )


def normalize_facility(raw):
    orgs = raw.get("ORGANIZATION") or []
    agency_name = (orgs[0].get("OrgName") if orgs else None) or "Federal (Recreation.gov)"
    photos = [
        {"url": m["URL"], "title": m.get("Title") or ""}
        for m in sorted(raw.get("MEDIA") or [], key=lambda m: not m.get("IsPrimary"))
        if m.get("MediaType") == "Image" and m.get("URL")
    ]
    amenities = sorted({a.get("ActivityName", "").title() for a in raw.get("ACTIVITY") or []
                        if a.get("ActivityName")})
    fid = str(raw["FacilityID"])
    return Campground(
        source=SOURCE,
        source_id=fid,
        name=title_name(raw.get("FacilityName")),
        agency=Agency(agency_name, "Recreation.gov", "https://www.recreation.gov"),
        lat=raw.get("FacilityLatitude") or None,
        lng=raw.get("FacilityLongitude") or None,
        description=clean_html(raw.get("FacilityDescription")),
        booking_url=f"https://www.recreation.gov/camping/campgrounds/{fid}",
        booking_window_days=DEFAULT_BOOKING_WINDOW_DAYS,
        reservable=bool(raw.get("Reservable")),
        amenities=amenities,
        photos=photos,
    )


def is_campground(raw):
    return (raw.get("FacilityTypeDescription") or "").lower() == "campground" and raw.get("Enabled", True)


# Colorado is a rectangle.
CO_LAT = (36.99, 41.01)
CO_LNG = (-109.06, -102.04)
GRID_RADIUS_MI = 50


def in_colorado(raw):
    lat, lng = raw.get("FacilityLatitude") or 0, raw.get("FacilityLongitude") or 0
    if CO_LAT[0] <= lat <= CO_LAT[1] and CO_LNG[0] <= lng <= CO_LNG[1]:
        return True
    return any(a.get("AddressStateCode") == "CO" for a in raw.get("FACILITYADDRESS") or [])


def grid_points():
    """1-degree grid across Colorado; 50-mile radius searches around each point overlap."""
    lat = CO_LAT[0] + 0.5
    while lat < CO_LAT[1]:
        lng = CO_LNG[0] + 0.5
        while lng < CO_LNG[1]:
            yield round(lat, 2), round(lng, 2)
            lng += 1.0
        lat += 1.0


def find_colorado_facilities(api_key, grid=True, log=print):
    """Two passes so nothing is missed (from seed/fetch_federal.py):
    1. state=CO filter (relies on each facility's listed address)
    2. radius searches on a grid, keeping anything whose coordinates are in Colorado
    """
    found = {}

    def keep(raw):
        if is_campground(raw) and in_colorado(raw):
            found[str(raw["FacilityID"])] = raw

    for raw in paginate("/facilities", {"state": "CO", "full": "true"}, api_key):
        keep(raw)
    log(f"Pass 1 (state=CO): {len(found)} campgrounds")
    if grid:
        for lat, lng in grid_points():
            params = {"latitude": lat, "longitude": lng, "radius": GRID_RADIUS_MI, "full": "true"}
            for raw in paginate("/facilities", params, api_key):
                keep(raw)
        log(f"Pass 2 (radius grid): {len(found)} campgrounds")
    return found


# --- entry point ----------------------------------------------------------------

def iter_colorado_campgrounds(api_key=None, limit=None, with_campsites=True, grid=True, log=print):
    api_key = api_key or config.RIDB_API_KEY
    if not api_key:
        raise RuntimeError("RIDB_API_KEY is not set. Add it to .env (see .env.example).")
    facilities = find_colorado_facilities(api_key, grid=grid, log=log)
    for count, raw in enumerate(sorted(facilities.values(), key=lambda f: f.get("FacilityName", "")), 1):
        campground = normalize_facility(raw)
        if with_campsites:
            for site in paginate(f"/facilities/{campground.source_id}/campsites", {}, api_key):
                normalized = normalize_campsite(site)
                if normalized:
                    campground.campsites.append(normalized)
        yield campground
        if limit and count >= limit:
            return
