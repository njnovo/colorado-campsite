"""Hand-curated campground list (seed/seed_campgrounds.csv) for systems with no list API:
CPW state parks, Larimer County, Jefferson County Open Space, Denver Mountain Parks.

Metadata only. Edit the lists in
seed/build_seed.py, regenerate the CSV, then run `manage.py import-seed`.
"""
import csv
import re

from .. import config
from .base import Agency, Campground

SEED_CSV = config.ROOT / "seed" / "seed_campgrounds.csv"

# booking_system prefix in the CSV -> (our source name, label shown on "Book on ..." button)
SYSTEMS = {
    "recreation.gov": ("recgov", "Recreation.gov"),
    "cpwshop": ("cpw", "cpwshop.com"),
    "larimercamping": ("larimer", "larimercamping.com"),
    "rec1": ("jeffco", "Jefferson County"),
}
FALLBACK_SYSTEM = ("other", "the operator's website")


def slug(text):
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def _float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def normalize_row(row):
    """Return (Campground, None) or (None, reason it was skipped)."""
    system = (row.get("booking_system") or "").strip()
    source, label = next(
        (v for k, v in SYSTEMS.items() if system.lower().startswith(k)), FALLBACK_SYSTEM
    )
    reservable = row.get("reservable", "").strip().lower() == "yes"
    if not reservable and source != "recgov":
        return None, row.get("notes") or "marked not reservable"

    booking_id = (row.get("source_id") or "").strip()
    name = row["name"].strip()
    lines = [row.get("notes", "").strip()]
    if row.get("park_or_area") and row["park_or_area"] != name:
        lines.append(f"Part of {row['park_or_area']}.")
    if row.get("nearest_town"):
        lines.append(f"Near {row['nearest_town']}.")

    return Campground(
        source=source,
        # recgov rows are keyed by facility ID so they merge with RIDB imports;
        # others by name, so filling in a cpwshop parkID later doesn't duplicate the row.
        source_id=booking_id if source == "recgov" and booking_id else slug(name),
        name=name,
        agency=Agency(row.get("operator") or "Unknown", label, row.get("booking_url", "")),
        lat=_float(row.get("lat")),
        lng=_float(row.get("lng")),
        description="\n".join(l for l in lines if l),
        booking_url=row.get("booking_url", ""),
        reservable=reservable,
        amenities=[row["camping_type"].title()] if row.get("camping_type") else [],
        extra={
            "booking_id": booking_id or None,
            "booking_system_raw": system,
            "verified": row.get("verified", "").strip().lower() == "yes",
            "camping_type": row.get("camping_type") or None,
        },
    ), None


def read_seed(path=SEED_CSV):
    with open(path, newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            yield row, *normalize_row(row)
