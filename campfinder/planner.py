"""Booking-day planner: when does a stay become bookable, and what are the backups?

Rules come from seed/booking_rules.csv (one row per source default `*`, plus overrides by
source_id). No availability data is used.

Decisions (see tests/test_planner.py):
- "N months before" a day that doesn't exist in the earlier month clamps to that month's
  last day: Aug 31 - 6 months = Feb 28 (Feb 29 in leap years), so Aug 29-31 all open
  together on the last day of February. Matches how Recreation.gov is reported to roll
  forward (never skipping a date); not confirmed on an official page.
- basis=each_night (Recreation.gov): every night opens on its own, so the first night
  opens first and the full stay is bookable only when the last night opens. We report both.
- basis=arrival (CPW, Larimer): the whole stay is bookable once the arrival date opens.
- Release times are stored in the booking system's own zone and shown in Mountain Time;
  zoneinfo handles daylight saving.
"""
import calendar
import csv
import json
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from . import config, search

RULES_CSV = config.ROOT / "seed" / "booking_rules.csv"
MOUNTAIN = ZoneInfo("America/Denver")
NO_RESERVATIONS = ("fcfs", "lottery")


@dataclass
class Rule:
    source: str
    source_id: str
    window_type: str  # rolling_months, rolling_days, fixed_date, lottery, fcfs
    window_amount: int | None = None
    release_time: time | None = None  # None = time of day not published
    release_tz: str = "America/Denver"
    basis: str = "arrival"  # arrival or each_night
    opens_on: date | None = None  # fixed_date only
    notes: str = ""
    url: str = ""
    verified_on: date | None = None
    is_default: bool = False  # matched the source's `*` row, not this campground

    def to_dict(self):
        return {
            "window_type": self.window_type, "window_amount": self.window_amount,
            "release_time": self.release_time.strftime("%H:%M") if self.release_time else None,
            "release_tz": self.release_tz, "basis": self.basis,
            "opens_on": self.opens_on.isoformat() if self.opens_on else None,
            "notes": self.notes, "url": self.url,
            "verified_on": self.verified_on.isoformat() if self.verified_on else None,
            "is_default": self.is_default, "summary": describe_rule(self),
        }


def parse_rule(row):
    def opt(key):
        return (row.get(key) or "").strip() or None

    return Rule(
        source=row["source"].strip(), source_id=row["source_id"].strip(),
        window_type=row["window_type"].strip(),
        window_amount=int(opt("window_amount")) if opt("window_amount") else None,
        release_time=time.fromisoformat(opt("release_time")) if opt("release_time") else None,
        release_tz=opt("release_tz") or "America/Denver",
        basis=opt("basis") or "arrival",
        opens_on=date.fromisoformat(opt("opens_on")) if opt("opens_on") else None,
        notes=opt("notes") or "", url=opt("url") or "",
        verified_on=date.fromisoformat(opt("verified_on")) if opt("verified_on") else None,
    )


_cache = {}


def load_rules(path=RULES_CSV):
    """{(source, source_id): Rule}, re-read whenever the CSV changes."""
    mtime = path.stat().st_mtime
    if _cache.get("key") != (str(path), mtime):
        with open(path, newline="", encoding="utf-8") as fh:
            rules = {(r.source, r.source_id): r for r in map(parse_rule, csv.DictReader(fh))}
        _cache.update(key=(str(path), mtime), rules=rules)
    return _cache["rules"]


def rule_for(source, source_id, reservable=True, rules=None):
    rules = load_rules() if rules is None else rules
    if (source, source_id) in rules:
        return rules[(source, source_id)]
    if not reservable:
        return Rule(source, source_id, "fcfs", notes="Walk-up only in our data.", is_default=True)
    default = rules.get((source, "*"))
    if default is None:
        return None
    return Rule(**{**default.__dict__, "source_id": source_id, "is_default": True})


# Niels [TBD] thses two functions below：
# - months_before(day, months) returns the same day of the month, months earlier. It has two tricky parts:
#   a. Crossing into last year. 6 months before March 2027 is September 2026. Hint: turn the date into one number of months (year * 12 + (month - 1)), subtract, then split it back with divmod(total, 12).
#   b. Short months. 6 months before Aug 31 would be "Feb 31", which doesn't exist, so use the last day of February instead. Hint: calendar.monthrange(year, month)[1] gives the number of days in a month, and min() picks the smaller day.
# - For going back days, timedelta(days=...) is already imported.
# months_before: months-as-one-number, divmod(..., 12), 
# calendar.monthrange, min.
#def months_before(day: date, months: int) -> date:
#    """Same day-of-month `months` earlier, clamped to the end of a shorter month."""

def months_before(day: date, months: int) -> date:
    day_in_months = day.year * 12 + day.month
    new_day_in_months = day_in_months - months
    new_day = date(new_day_in_months // 12, new_day_in_months % 12 + 1, min(day.day, calendar.monthrange(new_day_in_months // 12, new_day_in_months % 12 + 1)[1]))
    return new_day

# - opening_date(night, rule) looks at rule.window_type:
#   - "rolling_months": go back rule.window_amount months from night (calls months_before).
#   - "rolling_days": go back rule.window_amount days.
#   - "fixed_date": always return rule.opens_on.
#   - anything else (first-come or lottery): return None.
# opening_date: one if for each rule.window_type: 
# "rolling_months", "rolling_days", "fixed_date", else None.
def opening_date(night: date, rule: Rule) -> date | None:
    if rule.window_type == "rolling_months":
        return months_before(night, rule.window_amount)
    if rule.window_type == "rolling_days":
        return night - timedelta(days=rule.window_amount)
    if rule.window_type == "fixed_date":
        return rule.opens_on
    return None

# Neils [TBD]： then delete thses months_before and opening_date functions below.:


def opening_time(night: date, rule: Rule) -> datetime | None:
    """When `night` becomes bookable, timezone-aware in the rule's zone (None for fcfs/lottery).
    With no published release time, midnight local is used and callers show the date only."""
    day = opening_date(night, rule)
    if day is None:
        return None
    return datetime.combine(day, rule.release_time or time(0), tzinfo=ZoneInfo(rule.release_tz))


def friendly(dt: datetime, with_time=True) -> str:
    """'Tue, Feb 2, 2027 at 8:00 AM (Mountain Time)' (or date only)."""
    local = dt.astimezone(MOUNTAIN)
    text = f"{local:%a, %b} {local.day}, {local.year}"
    if with_time:
        text += f" at {local.hour % 12 or 12}:{local:%M %p} (Mountain Time)"
    return text


def describe_rule(rule: Rule) -> str:
    if rule.window_type == "fcfs":
        return "No reservations (first-come, first-served)"
    if rule.window_type == "lottery":
        return "Lottery; see the booking site"
    if rule.window_type == "fixed_date":
        return f"Whole season opens {rule.opens_on:%b} {rule.opens_on.day}, {rule.opens_on.year}"
    unit = "months" if rule.window_type == "rolling_months" else "days"
    text = f"{rule.window_amount} {unit} ahead"
    if rule.release_time:
        sample = datetime.combine(date.today(), rule.release_time, tzinfo=ZoneInfo(rule.release_tz))
        local = sample.astimezone(MOUNTAIN)
        text += f", new dates at {local.hour % 12 or 12}:{local:%M %p} MT"
    else:
        text += ", release time not published"
    return text + (" (each night opens separately)" if rule.basis == "each_night" else "")


def stay_opening(checkin: date, checkout: date, rule: Rule | None, now: datetime):
    """Opening info for a stay. `now` must be timezone-aware."""
    search.night_dates(checkin, checkout)  # validates order and length
    if rule is None or rule.window_type in NO_RESERVATIONS:
        status = "lottery" if rule and rule.window_type == "lottery" else "no_reservations"
        return {"status": status, "opens_at": None, "full_stay_opens_at": None}
    first = opening_time(checkin, rule)
    full = opening_time(checkout - timedelta(days=1), rule) if rule.basis == "each_night" else first
    with_time = rule.release_time is not None
    return {
        "status": "open" if now >= first else "upcoming",
        "full_stay_status": "open" if now >= full else "upcoming",
        "opens_at": first.isoformat(),
        "opens_at_utc": first.astimezone(timezone.utc).isoformat(),
        "opens_at_text": friendly(first, with_time),
        "full_stay_opens_at": full.isoformat() if full != first else None,
        "full_stay_opens_at_text": friendly(full, with_time) if full != first else None,
        "time_known": with_time,
        "seconds_until": max(0, int((first - now).total_seconds())),
    }


def _campground(conn, campground_id):
    row = conn.execute(
        """SELECT c.id, c.name, c.source, c.source_id, c.lat, c.lng, c.reservable, c.booking_url,
                  a.name AS agency, a.booking_system
           FROM campgrounds c JOIN agencies a ON a.id = c.agency_id WHERE c.id = ?""",
        (campground_id,),
    ).fetchone()
    return dict(row) if row else None


def site_types(conn, campground_id):
    types = set()
    for r in conn.execute("SELECT type, attributes FROM campsites WHERE campground_id = ?", (campground_id,)):
        if r["type"]:
            types.add(r["type"])
        if json.loads(r["attributes"] or "{}").get("tent_ok"):
            types.add("tent")
    return sorted(types)


def backups(conn, campground_id, checkin, checkout, radius_mi=30, limit=5, now=None, rules=None):
    """Reservable campgrounds within radius_mi sharing a site type, nearest first, each with
    its own opening time. Campgrounds with no site data (e.g. state parks) count as similar."""
    now = now or datetime.now(timezone.utc)
    origin = _campground(conn, campground_id)
    if origin is None or origin["lat"] is None:
        return []
    types = site_types(conn, campground_id)
    origin_rule = rule_for(origin["source"], origin["source_id"], origin["reservable"], rules)
    origin_open = opening_time(checkin, origin_rule) if origin_rule else None

    similar, type_params = "1", []
    if types:
        where, type_params = search.site_filters(types=types)
        similar = f"""(NOT EXISTS (SELECT 1 FROM campsites s WHERE s.campground_id = c.id)
                       OR EXISTS (SELECT 1 FROM campsites s WHERE s.campground_id = c.id
                                  AND {' AND '.join(where)}))"""
    rows = conn.execute(
        f"""SELECT * FROM (
                SELECT c.id, c.name, c.source, c.source_id, c.reservable, c.booking_url,
                       a.name AS agency,
                       distance_mi(?, ?, c.lat, c.lng) AS distance,
                       (SELECT COUNT(*) FROM campsites s WHERE s.campground_id = c.id) AS sites
                FROM campgrounds c JOIN agencies a ON a.id = c.agency_id
                WHERE c.id != ? AND c.reservable = 1 AND c.lat IS NOT NULL AND {similar}
            ) WHERE distance <= ? ORDER BY distance, name""",
        [origin["lat"], origin["lng"], campground_id, *type_params, radius_mi],
    ).fetchall()

    results = []
    for r in rows:
        rule = rule_for(r["source"], r["source_id"], r["reservable"], rules)
        if rule is None or rule.window_type in NO_RESERVATIONS:
            continue
        opening = stay_opening(checkin, checkout, rule, now)
        opens = opening_time(checkin, rule)
        if opening["status"] == "open":
            compare = "already_open"
        elif origin_open is None:
            compare = None
        else:
            compare = "same" if opens == origin_open else "later" if opens > origin_open else "earlier"
        results.append({
            "id": r["id"], "name": r["name"], "agency": r["agency"], "booking_url": r["booking_url"],
            "distance_mi": round(r["distance"], 1), "site_types_known": bool(r["sites"]),
            "rule": rule.to_dict(), **opening, "compared_to_first_choice": compare,
        })
        if len(results) >= limit:
            break
    return results


def plan(conn, campground_id, checkin, checkout, now=None, rules=None):
    now = now or datetime.now(timezone.utc)
    cg = _campground(conn, campground_id)
    if cg is None:
        return None
    if checkin < now.astimezone(MOUNTAIN).date():
        raise search.SearchError("check-in is in the past")
    rule = rule_for(cg["source"], cg["source_id"], cg["reservable"], rules)
    return {
        "campground": {k: cg[k] for k in ("id", "name", "agency", "booking_system", "booking_url")},
        "checkin": checkin.isoformat(), "checkout": checkout.isoformat(),
        "rule": rule.to_dict() if rule else None,
        "verified": bool(rule and rule.verified_on and not rule.is_default),
        **stay_opening(checkin, checkout, rule, now),
        "site_types": site_types(conn, campground_id),
        "backups": backups(conn, campground_id, checkin, checkout, now=now, rules=rules),
    }


# --- Calendar export (RFC 5545) ---

def ics_escape(text):
    return (str(text).replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,")
            .replace("\r\n", "\\n").replace("\n", "\\n"))


def ics_fold(line):
    """Fold to 75 octets per line, continuation lines start with a space (RFC 5545 §3.1)."""
    out, current = [], b""
    for ch in line:
        encoded = ch.encode()
        limit = 75 if not out else 74  # continuation lines carry a leading space
        if len(current) + len(encoded) > limit:
            out.append(current)
            current = b""
        current += encoded
    out.append(current)
    return b"\r\n ".join(out).decode()


def _utc(dt):
    return dt.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _event_lines(plan_data, reminder_minutes, now):
    cg = plan_data["campground"]
    start = datetime.fromisoformat(plan_data["opens_at"])
    rule = plan_data["rule"]
    desc = [
        f"Stay {plan_data['checkin']} to {plan_data['checkout']} at {cg['name']}.",
        f"Rule: {rule['summary']}.",
        f"Rule verified on {rule['verified_on']}." if plan_data["verified"]
        else "Unverified: check the booking site.",
    ]
    if plan_data.get("full_stay_opens_at_text"):
        desc.append(f"Your last night opens {plan_data['full_stay_opens_at_text']}.")
    if not plan_data["time_known"]:
        desc.append("Exact release time isn't published; this reminder is at midnight.")
    if cg["booking_url"]:
        desc.append(f"Book: {cg['booking_url']}")
    lines = [
        "BEGIN:VEVENT",
        f"UID:plan-{cg['id']}-{plan_data['checkin']}-{plan_data['checkout']}@colorado-campsite-finder",
        f"DTSTAMP:{_utc(now)}",
        f"DTSTART:{_utc(start)}",
        f"DTEND:{_utc(start + timedelta(minutes=30))}",
        f"SUMMARY:{ics_escape('Book ' + cg['name'])}",
        f"DESCRIPTION:{ics_escape(chr(10).join(desc))}",
    ]
    if cg["booking_url"]:
        lines.append(f"URL:{cg['booking_url']}")
    return lines + [
        "BEGIN:VALARM", "ACTION:DISPLAY", f"DESCRIPTION:{ics_escape(cg['name'] + ' opens soon')}",
        f"TRIGGER:-PT{int(reminder_minutes)}M", "END:VALARM", "END:VEVENT",
    ]


def ics(plans, reminder_minutes=15, now=None):
    """A calendar with one event per plan that has an opening time, or None if none do.
    `plans` is one plan() result or a list of them."""
    plans = [plans] if isinstance(plans, dict) else plans
    plans = [p for p in plans if p.get("opens_at")]
    if not plans:
        return None
    now = now or datetime.now(timezone.utc)
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Colorado Campsite Finder//Booking Planner//EN",
             "CALSCALE:GREGORIAN", "METHOD:PUBLISH"]
    for p in plans:
        lines += _event_lines(p, reminder_minutes, now)
    lines.append("END:VCALENDAR")
    return "".join(ics_fold(line) + "\r\n" for line in lines)


# --- Booking calendar: many campgrounds x many stays ---

MAX_CALENDAR_CAMPGROUNDS = 20


def booking_events(conn, campground_ids, stays, now=None, rules=None):
    """One plan per (campground, stay), without backups, sorted by opening time.
    Stays with a check-in in the past are skipped."""
    now = now or datetime.now(timezone.utc)
    today = now.astimezone(MOUNTAIN).date()
    events, campgrounds = [], []
    for cg_id in list(dict.fromkeys(campground_ids))[:MAX_CALENDAR_CAMPGROUNDS]:
        cg = _campground(conn, cg_id)
        if cg is None:
            continue
        rule = rule_for(cg["source"], cg["source_id"], cg["reservable"], rules)
        info = {k: cg[k] for k in ("id", "name", "agency", "booking_system", "booking_url")}
        campgrounds.append({**info, "rule": rule.to_dict() if rule else None})
        for checkin, checkout in stays:
            if checkin < today:
                continue
            events.append({
                "campground": info, "checkin": checkin.isoformat(), "checkout": checkout.isoformat(),
                "rule": rule.to_dict() if rule else None,
                "verified": bool(rule and rule.verified_on and not rule.is_default),
                **stay_opening(checkin, checkout, rule, now),
            })
    events.sort(key=lambda e: (e["opens_at_utc"] if e.get("opens_at") else "~", e["campground"]["name"]))
    return {"campgrounds": campgrounds, "events": events}


# --- Stretch: every weekend in a month, and upcoming openings ---
# Avi： 
# What it has to do:
# - Return a list of pairs: (Friday, the Sunday 2 days later) for every Friday in that month.
# - Hints:
#   - calendar.monthrange(year, month)[1] gives the number of days in the month.
#   - Loop over day 1 up to that number, making each date with date(year, month, day).
#   - .weekday() == 4 means Friday (Monday is 0).
#   - d + timedelta(days=2) gives the Sunday.
# How to check: StretchTest checks July 2027: the first weekend is Jul 2 – Jul 4, and there are 5 weekends.
# def weekends(year, month):

# delete this one：   
def weekends(year, month):
    """(Friday, Sunday) check-in/check-out pairs whose Friday falls in the month."""
    days = calendar.monthrange(year, month)[1]
    return [(d, d + timedelta(days=2)) for d in (date(year, month, i) for i in range(1, days + 1))
            if d.weekday() == 4]


def openings_between(conn, campground_ids, start: datetime, end: datetime, rules=None):
    """Arrival nights whose opening falls in [start, end), per campground."""
    out = []
    for cg_id in campground_ids:
        cg = _campground(conn, cg_id)
        rule = cg and rule_for(cg["source"], cg["source_id"], cg["reservable"], rules)
        if not rule or rule.window_type not in ("rolling_months", "rolling_days"):
            continue
        # A night opens roughly window ahead; scan nights near that offset.
        approx = (rule.window_amount * 31 if rule.window_type == "rolling_months" else rule.window_amount)
        night = start.date() + timedelta(days=approx - 40)
        while night <= end.date() + timedelta(days=approx + 5):
            opens = opening_time(night, rule)
            if start <= opens < end:
                out.append({"campground": cg["name"], "night": night, "opens_at": opens,
                            "time_known": rule.release_time is not None})
            night += timedelta(days=1)
    return sorted(out, key=lambda o: (o["opens_at"], o["campground"], o["night"]))
