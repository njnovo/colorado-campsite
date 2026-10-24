"""Tiered availability polling (PLAN.md §5).

A "job" is one campground x one calendar month. Each job gets a tier that sets
how often it is re-checked:

    hot   popular or has an active alert, month within the next 60 days
    warm  everything else within 60 days, and popular campgrounds further out
    cold  far-future months of unpopular campgrounds

Only campgrounds on the watchlist (campgrounds.watched) are polled, and only
config.WATCH_DAYS ahead: at Recreation.gov's 10 s crawl delay a full statewide
sweep would take hours. Watched campgrounds count as popular for tiering.

Not yet implemented: the booking-window-opening burst and auto-tuning tiers
from availability_events.
"""
import logging
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

from . import config
from .adapters import AVAILABILITY_ADAPTERS
from .adapters.base import AdapterDisabled
from .db import now_iso
from .store import closed_for_month, save_availability

log = logging.getLogger(__name__)

TIER_INTERVALS = {"hot": 10 * 60, "warm": 60 * 60, "cold": 12 * 60 * 60}
TIER_ORDER = {"hot": 0, "warm": 1, "cold": 2}
NEAR_DAYS = 60
DEFAULT_WINDOW_DAYS = 180


@dataclass
class Job:
    source: str
    campground_id: int
    source_id: str
    month: date
    tier: str
    last_ok: datetime | None


def month_starts(today, window_days):
    month = today.replace(day=1)
    end = today + timedelta(days=window_days)
    while month <= end:
        yield month
        month = (month + timedelta(days=32)).replace(day=1)


def tier_for(popular, has_alert, month, today):
    near = month <= today + timedelta(days=NEAR_DAYS)
    if near and (popular or has_alert):
        return "hot"
    if near or popular:
        return "warm"
    return "cold"


def due_jobs(conn, now=None):
    now = now or datetime.now(timezone.utc)
    today = now.date()
    campgrounds = conn.execute(
        f"""SELECT c.id, c.source, c.source_id, c.popular, c.booking_window_days,
                   EXISTS (SELECT 1 FROM alerts a
                           LEFT JOIN campsites s ON s.id = a.campsite_id
                           WHERE a.active AND (a.campground_id = c.id OR s.campground_id = c.id)
                          ) AS has_alert
            FROM campgrounds c
            WHERE c.reservable AND c.watched AND c.source IN ({",".join("?" * len(AVAILABILITY_ADAPTERS))})""",
        list(AVAILABILITY_ADAPTERS),
    ).fetchall()
    last_ok = {
        (r["campground_id"], r["month"]): datetime.fromisoformat(r["last"])
        for r in conn.execute(
            """SELECT campground_id, month, MAX(started_at) AS last FROM poll_runs
               WHERE ok = 1 GROUP BY campground_id, month"""
        )
    }
    jobs = []
    for c in campgrounds:
        window = min(c["booking_window_days"] or DEFAULT_WINDOW_DAYS, config.WATCH_DAYS)
        for month in month_starts(today, window):
            tier = tier_for(True, c["has_alert"], month, today)
            last = last_ok.get((c["id"], month.isoformat()))
            if last is None or (now - last).total_seconds() >= TIER_INTERVALS[tier]:
                jobs.append(Job(c["source"], c["id"], c["source_id"], month, tier, last))
    epoch = datetime.min.replace(tzinfo=timezone.utc)
    jobs.sort(key=lambda j: (TIER_ORDER[j.tier], j.last_ok or epoch, j.month))
    return jobs


def run_job(conn, job):
    run_id = conn.execute(
        "INSERT INTO poll_runs (source, campground_id, month, started_at) VALUES (?, ?, ?, ?)",
        (job.source, job.campground_id, job.month.isoformat(), now_iso()),
    ).lastrowid
    conn.commit()
    ok, error, status = 0, None, None
    try:
        status, availability = AVAILABILITY_ADAPTERS[job.source](job.source_id, job.month)
        if not availability:  # Recreation.gov returns no sites for months a campground is closed
            availability = closed_for_month(conn, job.campground_id, job.month)
        rows, changes = save_availability(conn, job.campground_id, availability)
        ok = 1
        log.info("%s cg=%s %s [%s]: %d rows, %d changes", job.source, job.campground_id,
                 job.month, job.tier, rows, changes)
    except AdapterDisabled as e:
        error = str(e)
        raise
    except Exception as e:  # recorded in poll_runs for the source-health view
        error = f"{type(e).__name__}: {e}"
        status = getattr(e, "status", None)
        log.warning("%s cg=%s %s failed: %s", job.source, job.campground_id, job.month, error)
    finally:
        conn.execute(
            "UPDATE poll_runs SET finished_at = ?, ok = ?, error = ?, http_status = ? WHERE id = ?",
            (now_iso(), ok, error, status, run_id),
        )
        conn.commit()
    return bool(ok)


def run_due(conn, max_jobs=None):
    jobs = due_jobs(conn)[:max_jobs] if max_jobs else due_jobs(conn)
    for job in jobs:
        run_job(conn, job)
    return len(jobs)


def worker_loop(conn, idle_sleep=30):
    while True:
        if run_due(conn, max_jobs=50) == 0:
            time.sleep(idle_sleep)
