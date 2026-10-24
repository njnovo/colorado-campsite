"""Writes normalized adapter output into the database."""
import json
from datetime import timedelta

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


def month_dates(month_start):
    day, dates = month_start.replace(day=1), []
    while day.month == month_start.month:
        dates.append(day.isoformat())
        day += timedelta(days=1)
    return dates


def closed_for_month(conn, campground_id, month_start):
    """Availability marking every site closed for the month (source returned no sites)."""
    dates = month_dates(month_start)
    return {
        r[0]: dict.fromkeys(dates, "closed")
        for r in conn.execute("SELECT source_id FROM campsites WHERE campground_id = ?", (campground_id,))
    }


def save_availability(conn, campground_id, site_availability, checked_at=None):
    """Store {site source_id: {date: status}} and log status changes.

    Returns (rows_written, changes_recorded). Sites we don't know (e.g. skipped
    management sites) are ignored.
    """
    checked_at = checked_at or now_iso()
    site_ids = dict(conn.execute(
        "SELECT source_id, id FROM campsites WHERE campground_id = ?", (campground_id,)
    ).fetchall())
    rows = changes = 0
    for source_id, dates in site_availability.items():
        site_id = site_ids.get(str(source_id))
        if site_id is None:
            continue
        previous = dict(conn.execute(
            "SELECT date, status FROM availability WHERE campsite_id = ? AND date >= ? AND date <= ?",
            (site_id, min(dates, default=""), max(dates, default="")),
        ).fetchall())
        for day, status in dates.items():
            old = previous.get(day)
            if old != status:
                if old is not None:
                    conn.execute(
                        """INSERT INTO availability_events
                               (campsite_id, date, old_status, new_status, detected_at)
                           VALUES (?, ?, ?, ?, ?)""",
                        (site_id, day, old, status, checked_at),
                    )
                    changes += 1
            conn.execute(
                """INSERT INTO availability (campsite_id, date, status, checked_at)
                   VALUES (?, ?, ?, ?)
                   ON CONFLICT(campsite_id, date) DO UPDATE SET
                       status = excluded.status, checked_at = excluded.checked_at""",
                (site_id, day, status, checked_at),
            )
            rows += 1
    conn.commit()
    return rows, changes
