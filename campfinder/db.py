"""SQLite storage for the normalized data model (PLAN.md §4)."""
import math
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from . import config

SITE_TYPES = ("tent", "rv", "cabin", "yurt", "group", "equestrian", "boat-in")
STATUSES = ("available", "reserved", "closed", "fcfs", "not_released")

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
    watched              INTEGER NOT NULL DEFAULT 0,
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

CREATE TABLE IF NOT EXISTS availability (
    campsite_id  INTEGER NOT NULL REFERENCES campsites(id) ON DELETE CASCADE,
    date         TEXT NOT NULL,
    status       TEXT NOT NULL CHECK (status IN {STATUSES!r}),
    checked_at   TEXT NOT NULL,
    PRIMARY KEY (campsite_id, date)
) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS availability_events (
    id           INTEGER PRIMARY KEY,
    campsite_id  INTEGER NOT NULL REFERENCES campsites(id) ON DELETE CASCADE,
    date         TEXT NOT NULL,
    old_status   TEXT,
    new_status   TEXT NOT NULL,
    detected_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS poll_runs (
    id             INTEGER PRIMARY KEY,
    source         TEXT NOT NULL,
    campground_id  INTEGER REFERENCES campgrounds(id) ON DELETE CASCADE,
    month          TEXT,
    started_at     TEXT NOT NULL,
    finished_at    TEXT,
    ok             INTEGER,
    error          TEXT,
    http_status    INTEGER
);

CREATE TABLE IF NOT EXISTS alerts (
    id                INTEGER PRIMARY KEY,
    email             TEXT NOT NULL,
    campground_id     INTEGER REFERENCES campgrounds(id) ON DELETE CASCADE,
    campsite_id       INTEGER REFERENCES campsites(id) ON DELETE CASCADE,
    date_start        TEXT NOT NULL,
    date_end          TEXT NOT NULL,
    filters           TEXT NOT NULL DEFAULT '{{}}',
    last_notified_at  TEXT,
    active            INTEGER NOT NULL DEFAULT 1
);

CREATE INDEX IF NOT EXISTS idx_campsites_campground ON campsites(campground_id);
CREATE INDEX IF NOT EXISTS idx_availability_date ON availability(date, status);
CREATE INDEX IF NOT EXISTS idx_events_detected ON availability_events(detected_at);
CREATE INDEX IF NOT EXISTS idx_poll_runs_job ON poll_runs(source, campground_id, month, started_at);
"""


def now_iso():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


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
    ("campgrounds", "watched", "INTEGER NOT NULL DEFAULT 0"),
]


def init(conn):
    conn.executescript(SCHEMA)
    for table, column, definition in MIGRATIONS:
        existing = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
        if column not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
    conn.commit()


def prune_old_availability(conn, keep_from_date):
    """Drop availability rows before keep_from_date (PLAN.md: rolling window)."""
    cur = conn.execute("DELETE FROM availability WHERE date < ?", (keep_from_date,))
    conn.commit()
    return cur.rowcount
