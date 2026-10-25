"""SQLite storage for campground metadata (PLAN.md §4, minus availability)."""
import math
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from . import config

SITE_TYPES = ("tent", "rv", "cabin", "yurt", "group", "equestrian", "boat-in")

SCHEMA = f"""
CREATE TABLE IF NOT EXISTS agencies (
    id              INTEGER PRIMARY KEY,
    name            TEXT NOT NULL UNIQUE,
    booking_system  TEXT,
    website         TEXT
);

CREATE TABLE IF NOT EXISTS campgrounds (
    id                   INTEGER PRIMARY KEY,
    agency_id            INTEGER REFERENCES agencies(id),
    source               TEXT NOT NULL,
    source_id            TEXT NOT NULL,
    name                 TEXT NOT NULL,
    state                TEXT NOT NULL DEFAULT 'CO',
    lat                  REAL,
    lng                  REAL,
    elevation_ft         INTEGER,
    description          TEXT,
    season_open          TEXT,
    season_close         TEXT,
    booking_url          TEXT,
    booking_window_days  INTEGER,
    reservable           INTEGER NOT NULL DEFAULT 1,
    popular              INTEGER NOT NULL DEFAULT 0,
    amenities            TEXT NOT NULL DEFAULT '[]',
    photos               TEXT NOT NULL DEFAULT '[]',
    extra                TEXT NOT NULL DEFAULT '{{}}',
    updated_at           TEXT,
    UNIQUE (source, source_id)
);

CREATE TABLE IF NOT EXISTS campsites (
    id                INTEGER PRIMARY KEY,
    campground_id     INTEGER NOT NULL REFERENCES campgrounds(id) ON DELETE CASCADE,
    source_id         TEXT NOT NULL,
    name              TEXT,
    loop              TEXT,
    type              TEXT CHECK (type IN {SITE_TYPES!r}),
    max_rv_length_ft  INTEGER,
    max_people        INTEGER,
    hookups           TEXT NOT NULL DEFAULT '{{}}',
    ada               INTEGER NOT NULL DEFAULT 0,
    pets              INTEGER,
    price_per_night   REAL,
    attributes        TEXT NOT NULL DEFAULT '{{}}',
    UNIQUE (campground_id, source_id)
);

CREATE INDEX IF NOT EXISTS idx_campsites_campground ON campsites(campground_id);
"""


def now_iso():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()

# Avi:
# Distance between two places (Python)
# File: campfinder/db.py, lines 68–75, haversine_mi(lat1, lng1, lat2, lng2). I've just opened it in VS Code.
# This works out how many miles apart two map points are. It powers "campgrounds within 30 miles" on the search page and the backup suggestions.
# What it has to do:
# - If any of the four numbers is None, return None.
# - Otherwise use the haversine formula, which measures distance on a curved Earth:
#   a. Earth's radius is 3958.8 miles.
#   b. Convert the latitudes and the differences to radians with math.radians(...).
#   c. a = sin²(Δlat/2) + cos(lat1) · cos(lat2) · sin²(Δlng/2)
#   d. distance = 2 · radius · asin(√a)
# - He can look up "haversine formula" to see why it works, which is good material for the competition write-up.

# How to check: I added a test, DistanceTest. 
# Denver to Estes Park should come out at about 52.3 miles, a place to itself is 0, and a missing number gives None.
# def haversine_mi(lat1, lng1, lat2, lng2):

def haversine_mi(lat1, lng1, lat2, lng2):
    if None in (lat1, lng1, lat2, lng2):
        return None
    r = 3958.8
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def connect(path=None):
    path = path or config.DB_PATH
    if path != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.create_function("distance_mi", 4, haversine_mi, deterministic=True)
    return conn


# Columns added after the first release: (table, column, definition)
MIGRATIONS = [
    ("campgrounds", "extra", "TEXT NOT NULL DEFAULT '{}'"),
]

# Tables from the old live-availability feature, dropped on startup.
OBSOLETE_TABLES = ("availability", "availability_events", "poll_runs", "alerts")


def init(conn):
    for table in OBSOLETE_TABLES:
        conn.execute(f"DROP TABLE IF EXISTS {table}")
    conn.executescript(SCHEMA)
    for table, column, definition in MIGRATIONS:
        existing = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
        if column not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
    conn.commit()

