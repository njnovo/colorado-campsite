"""Recreation.gov live availability adapter (PLAN.md §3.1).

DISABLED BY DEFAULT. The endpoint below is undocumented, and recreation.gov's
robots.txt disallows /api/* (Crawl-delay: 10). PLAN.md §3.5 says to respect
robots.txt, so this only runs when RECGOV_AVAILABILITY_ENABLED=true, which
should wait until we have sanctioned access from Recreation.gov.
"""
from datetime import date

from .. import config, fetch
from .base import AdapterDisabled, SchemaError

SOURCE = "recgov"
MONTH_URL = "https://www.recreation.gov/api/camps/availability/campground/{facility_id}/month"

STATUS_MAP = {
    "available": "available",
    "reserved": "reserved",
    "not available": "closed",
    "closed": "closed",
    "not reservable": "fcfs",
    "not reservable management": "closed",
    "open": "not_released",
    "nyr": "not_released",
    "lottery": "not_released",
}


def map_status(raw_status):
    return STATUS_MAP.get((raw_status or "").strip().lower(), "closed")


def parse_month(data):
    """Validate a month response and return {campsite_id: {YYYY-MM-DD: status}}.

    Raises SchemaError if the shape changed, so we notice instead of storing junk.
    """
    if not isinstance(data, dict) or not isinstance(data.get("campsites"), dict):
        raise SchemaError("recgov month: missing 'campsites' object")
    result = {}
    for key, site in data["campsites"].items():
        if not isinstance(site, dict) or not isinstance(site.get("availabilities"), dict):
            raise SchemaError(f"recgov month: site {key} has no 'availabilities' object")
        site_id = str(site.get("campsite_id") or key)
        result[site_id] = {
            ts[:10]: map_status(status) for ts, status in site["availabilities"].items()
        }
    return result


def fetch_month(facility_id, month_start: date):
    """Fetch one campground x one calendar month. Returns (http_status, availability)."""
    if not config.RECGOV_AVAILABILITY_ENABLED:
        raise AdapterDisabled(
            "Recreation.gov availability polling is disabled (robots.txt disallows /api/*). "
            "Set RECGOV_AVAILABILITY_ENABLED=true only once access is sanctioned."
        )
    start = month_start.replace(day=1).strftime("%Y-%m-%dT00:00:00.000Z")
    status, data = fetch.get_json(
        SOURCE, MONTH_URL.format(facility_id=facility_id), {"start_date": start}
    )
    return status, parse_month(data)
