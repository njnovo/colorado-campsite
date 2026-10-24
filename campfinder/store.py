"""Writes normalized adapter output into the database."""
import json

from .adapters.base import Campground
from .db import now_iso


def upsert_agency(conn, agency):
    conn.execute(
        """INSERT INTO agencies (name, booking_system, website) VALUES (?, ?, ?)
           ON CONFLICT(name) DO UPDATE SET booking_system = excluded.booking_system,
                                           website = excluded.website""",
        (agency.name, agency.booking_system, agency.website),
    )
    return conn.execute("SELECT id FROM agencies WHERE name = ?", (agency.name,)).fetchone()[0]


def upsert_campground(conn, cg: Campground):
    """Insert or update a campground and its campsites. Returns the campground id."""
    agency_id = upsert_agency(conn, cg.agency)
    conn.execute(
        """INSERT INTO campgrounds (agency_id, source, source_id, name, state, lat, lng,
               elevation_ft, description, season_open, season_close, booking_url,
               booking_window_days, reservable, amenities, photos, extra, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(source, source_id) DO UPDATE SET
               agency_id = excluded.agency_id, name = excluded.name, state = excluded.state,
               lat = excluded.lat, lng = excluded.lng,
               elevation_ft = COALESCE(excluded.elevation_ft, elevation_ft),
               description = excluded.description,
               season_open = COALESCE(excluded.season_open, season_open),
               season_close = COALESCE(excluded.season_close, season_close),
               booking_url = excluded.booking_url,
               booking_window_days = excluded.booking_window_days,
               reservable = excluded.reservable, amenities = excluded.amenities,
               photos = excluded.photos, extra = excluded.extra,
               updated_at = excluded.updated_at""",
        (agency_id, cg.source, cg.source_id, cg.name, cg.state, cg.lat, cg.lng,
         cg.elevation_ft, cg.description, cg.season_open, cg.season_close, cg.booking_url,
         cg.booking_window_days, int(cg.reservable), json.dumps(cg.amenities),
         json.dumps(cg.photos), json.dumps(cg.extra), now_iso()),
    )
    cg_id = conn.execute(
        "SELECT id FROM campgrounds WHERE source = ? AND source_id = ?", (cg.source, cg.source_id)
    ).fetchone()[0]

    for s in cg.campsites:
        conn.execute(
            """INSERT INTO campsites (campground_id, source_id, name, loop, type,
                   max_rv_length_ft, max_people, hookups, ada, pets, price_per_night, attributes)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(campground_id, source_id) DO UPDATE SET
                   name = excluded.name, loop = excluded.loop, type = excluded.type,
                   max_rv_length_ft = excluded.max_rv_length_ft,
                   max_people = excluded.max_people, hookups = excluded.hookups,
                   ada = excluded.ada, pets = excluded.pets,
                   price_per_night = COALESCE(excluded.price_per_night, price_per_night),
                   attributes = excluded.attributes""",
            (cg_id, s.source_id, s.name, s.loop, s.type, s.max_rv_length_ft, s.max_people,
             json.dumps(s.hookups), int(s.ada), None if s.pets is None else int(s.pets),
             s.price_per_night, json.dumps(s.attributes)),
        )
    conn.commit()
    return cg_id

