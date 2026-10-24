"""Clearly-labelled fake data so the UI can be tried before any real source is connected.

Everything here uses source='demo' and can be removed with `manage.py seed-demo --clear`.
"""
import random
from datetime import date, timedelta

from .adapters.base import Agency, Campground, Campsite
from .db import now_iso
from .store import save_availability, upsert_campground

SOURCE = "demo"
AGENCY = Agency("DEMO DATA (not real)", "demo", "")

# (name, lat, lng, elevation_ft) - rough real-world locations, fictional campgrounds
PLACES = [
    ("Demo Campground near Estes Park", 40.36, -105.59, 8100),
    ("Demo Campground near Buena Vista", 38.84, -106.13, 8000),
    ("Demo Campground near Fort Collins", 40.57, -105.17, 5500),
    ("Demo Campground near Steamboat Springs", 40.49, -106.83, 6900),
    ("Demo Campground near Ouray", 38.02, -107.67, 7800),
    ("Demo Campground near Colorado Springs", 38.87, -104.95, 7400),
    ("Demo Campground near Leadville", 39.25, -106.29, 9900),
    ("Demo Campground near Durango", 37.35, -107.85, 7100),
]

SITE_MIX = [
    ("tent", None, {}, 24.0),
    ("tent", None, {}, 24.0),
    ("rv", 35, {"electric_amps": 50, "water": True}, 38.0),
    ("rv", 40, {"electric_amps": 50, "water": True, "sewer": True}, 44.0),
    ("cabin", None, {"electric_amps": 20}, 90.0),
    ("group", 30, {}, 120.0),
]


def build_campgrounds(rng):
    for i, (name, lat, lng, elev) in enumerate(PLACES):
        sites = []
        for n in range(rng.randint(6, 14)):
            kind, rv_len, hookups, price = SITE_MIX[n % len(SITE_MIX)]
            sites.append(Campsite(
                source_id=f"demo-{i}-{n}", name=f"{n + 1:03d}", loop="A" if n < 7 else "B",
                type=kind, max_rv_length_ft=rv_len, max_people=8 if kind != "group" else 25,
                hookups=hookups, ada=n == 0, pets=kind != "cabin", price_per_night=price,
                attributes={"tent_ok": kind in ("tent", "group")},
            ))
        yield Campground(
            source=SOURCE, source_id=f"demo-{i}", name=name, agency=AGENCY,
            lat=lat, lng=lng, elevation_ft=elev,
            description="This is a fictional campground for trying out the app. "
                        "Availability is randomly generated.",
            season_open="05-15", season_close="10-01", booking_url="",
            booking_window_days=180,
            amenities=["Toilets", "Drinking Water", "Fire Rings"], campsites=sites,
        )


def clear(conn):
    conn.execute("DELETE FROM campgrounds WHERE source = ?", (SOURCE,))
    conn.execute("DELETE FROM agencies WHERE name = ?", (AGENCY.name,))
    conn.commit()


def seed(conn, days=120, seed_value=42):
    rng = random.Random(seed_value)
    today = date.today()
    checked_at = now_iso()
    count = 0
    for cg in build_campgrounds(rng):
        cg_id = upsert_campground(conn, cg)
        busyness = rng.uniform(0.3, 0.95)
        availability = {}
        for site in cg.campsites:
            availability[site.source_id] = {
                (today + timedelta(days=d)).isoformat():
                    "reserved" if rng.random() < busyness else "available"
                for d in range(days)
            }
        save_availability(conn, cg_id, availability, checked_at)
        count += 1
    return count
