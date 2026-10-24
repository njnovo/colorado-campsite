"""Small JSON API + static file server (standard library only).

    GET /api/meta                     agencies, data counts
    GET /api/search?start=&end=&...   campgrounds, each with its booking-day opening time
    GET /api/campgrounds?q=           name search (for pickers)
    GET /api/campgrounds/<id>
    GET /api/campgrounds/<id>/plan?checkin=&checkout=      booking-day planner
    GET /api/campgrounds/<id>/plan.ics?checkin=&checkout=  calendar reminder
    GET /api/booking-calendar?ids=1,2&checkin=&checkout=   opening times for many campgrounds
        (or &month=YYYY-MM for every Fri-Sun weekend that month); .ics variant at
        /api/booking-calendar.ics
"""
import json
import logging
import mimetypes
from datetime import date, datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from . import config, db, planner, search

log = logging.getLogger(__name__)

TRUE = ("1", "true", "yes", "on")


def _date(params, key, default):
    value = params.get(key)
    if not value:
        return default
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise search.SearchError(f"{key} must be YYYY-MM-DD")


def _float(params, key):
    value = params.get(key)
    if value in (None, ""):
        return None
    try:
        return float(value)
    except ValueError:
        raise search.SearchError(f"{key} must be a number")


def api_meta(conn, _params):
    agencies = [dict(r) for r in conn.execute(
        """SELECT a.id, a.name, COUNT(c.id) AS campgrounds FROM agencies a
           JOIN campgrounds c ON c.agency_id = a.id GROUP BY a.id ORDER BY a.name""")]
    stats = conn.execute(
        """SELECT (SELECT COUNT(*) FROM campgrounds) AS campgrounds,
                  (SELECT COUNT(*) FROM campsites) AS campsites""",
    ).fetchone()
    return {"agencies": agencies, "site_types": db.SITE_TYPES, **dict(stats)}


def api_search(conn, params):
    today = date.today()
    start = _date(params, "start", today + timedelta(days=1))
    end = _date(params, "end", start + timedelta(days=2))
    sort = params.get("sort", "distance")
    results = search.search(
        conn, start, end,
        lat=_float(params, "lat"), lng=_float(params, "lng"), radius_mi=_float(params, "radius"),
        agency_id=params.get("agency") or None,
        include_fcfs=params.get("fcfs") in TRUE,
        sort=sort,
        types=[t for t in params.get("types", "").split(",") if t],
        min_rv_length=_float(params, "rv_length"),
        electric=params.get("electric") in TRUE, water=params.get("water") in TRUE,
        sewer=params.get("sewer") in TRUE, ada=params.get("ada") in TRUE,
        pets=params.get("pets") in TRUE,
    )
    add_booking_times(results, start, end)
    if sort == "opens":  # soonest opening first; already bookable, then no reservations, last
        rank = {"upcoming": 0, "open": 1, "lottery": 2, "no_reservations": 3}
        results.sort(key=lambda c: (rank[c["booking"]["status"]], c["booking"]["opens_at_utc"] or "",
                                    c["name"]))
    return {"start": start.isoformat(), "end": end.isoformat(), "results": results}


def add_booking_times(results, start, end):
    """Attach the planner's opening time for this stay to each search result."""
    now = datetime.now(timezone.utc)
    for cg in results:
        rule = planner.rule_for(cg["source"], cg["source_id"], cg["reservable"])
        opening = planner.stay_opening(start, end, rule, now)
        cg["booking"] = {
            "status": opening["status"], "opens_at": opening["opens_at"],
            "opens_at_utc": opening.get("opens_at_utc"),
            "opens_at_text": opening.get("opens_at_text"),
            "verified": bool(rule and rule.verified_on and not rule.is_default),
        }


def api_find(conn, params):
    return {"results": search.find_by_name(conn, params.get("q", ""))}


def api_campground(conn, _params, campground_id):
    cg = search.get_campground(conn, campground_id)
    if cg is None:
        return 404, {"error": "campground not found"}
    return 200, cg


def _plan(conn, params, campground_id):
    checkin = _date(params, "checkin", None)
    checkout = _date(params, "checkout", None)
    if checkin is None or checkout is None:
        raise search.SearchError("checkin and checkout are required (YYYY-MM-DD)")
    return planner.plan(conn, campground_id, checkin, checkout)


def api_plan(conn, params, campground_id):
    result = _plan(conn, params, campground_id)
    return (404, {"error": "campground not found"}) if result is None else (200, result)


def _ics_response(body, filename):
    if body is None:
        return 409, {"error": "nothing to remind you about: no reservations, or every date is already open"}
    return 200, body.encode(), "text/calendar; charset=utf-8", {
        "Content-Disposition": f'attachment; filename="{filename}"'}


def api_plan_ics(conn, params, campground_id):
    result = _plan(conn, params, campground_id)
    if result is None:
        return 404, {"error": "campground not found"}
    return _ics_response(planner.ics(result), f"book-campground-{campground_id}-{result['checkin']}.ics")


def _calendar(conn, params):
    try:
        ids = [int(i) for i in params.get("ids", "").split(",") if i]
    except ValueError:
        raise search.SearchError("ids must be a comma-separated list of campground ids")
    if params.get("month"):
        try:
            year, month = map(int, params["month"].split("-"))
            stays = planner.weekends(year, month)
        except ValueError:
            raise search.SearchError("month must be YYYY-MM")
    else:
        checkin = _date(params, "checkin", None)
        checkout = _date(params, "checkout", None)
        if checkin is None or checkout is None:
            raise search.SearchError("give checkin and checkout, or month")
        search.night_dates(checkin, checkout)
        stays = [(checkin, checkout)]
    result = planner.booking_events(conn, ids, stays)
    result["stays"] = [{"checkin": a.isoformat(), "checkout": b.isoformat()} for a, b in stays]
    return result


def api_calendar(conn, params):
    return 200, _calendar(conn, params)


def api_calendar_ics(conn, params):
    events = [e for e in _calendar(conn, params)["events"] if e["status"] == "upcoming"]
    return _ics_response(planner.ics(events), "booking-calendar.ics")


class Handler(BaseHTTPRequestHandler):
    server_version = "CampsiteFinder/0.1"

    def log_message(self, fmt, *args):
        log.info("%s - " + fmt, self.address_string(), *args)

    def _send(self, status, body, content_type="application/json", headers=None):
        data = json.dumps(body, default=str).encode() if content_type == "application/json" else body
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        url = urlparse(self.path)
        params = {k: v[-1] for k, v in parse_qs(url.query).items()}
        if url.path.startswith("/api/"):
            return self._api(url.path, params)
        return self._static(url.path)

    def _api(self, path, params):
        conn = db.connect()
        try:
            parts = path.strip("/").split("/")
            if path == "/api/meta":
                return self._send(200, api_meta(conn, params))
            if path == "/api/search":
                return self._send(200, api_search(conn, params))
            if path == "/api/campgrounds":
                return self._send(200, api_find(conn, params))
            if path == "/api/booking-calendar":
                return self._send(*api_calendar(conn, params))
            if path == "/api/booking-calendar.ics":
                return self._send(*api_calendar_ics(conn, params))
            if len(parts) == 3 and parts[1] == "campgrounds" and parts[2].isdigit():
                return self._send(*api_campground(conn, params, int(parts[2])))
            if len(parts) == 4 and parts[1] == "campgrounds" and parts[2].isdigit():
                if parts[3] == "plan":
                    return self._send(*api_plan(conn, params, int(parts[2])))
                if parts[3] == "plan.ics":
                    return self._send(*api_plan_ics(conn, params, int(parts[2])))
            return self._send(404, {"error": "not found"})
        except search.SearchError as e:
            return self._send(400, {"error": str(e)})
        except Exception:
            log.exception("API error on %s", path)
            return self._send(500, {"error": "internal error"})
        finally:
            conn.close()

    def _static(self, path):
        if path in ("", "/"):
            path = "/index.html"
        root = config.STATIC_DIR.resolve()
        target = (root / path.lstrip("/")).resolve()
        if not target.is_relative_to(root) or not target.is_file():
            return self._send(404, b"Not found", "text/plain")
        content_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        return self._send(200, target.read_bytes(), content_type, {"Cache-Control": "no-cache"})


def serve(host=None, port=None):
    host, port = host or config.HOST, port or config.PORT
    httpd = ThreadingHTTPServer((host, port), Handler)
    print(f"Serving on http://{host}:{port}  (Ctrl+C to stop)")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
