"""Small JSON API + static file server (standard library only).

    GET /api/meta                     agencies, data freshness, demo flag
    GET /api/search?start=&end=&...   campgrounds with availability status
    GET /api/campgrounds/<id>?start=&end=
    GET /api/health                   last poll result per source
    POST /api/campgrounds/<id>/check?start=&end=   check live availability now
"""
import json
import logging
import mimetypes
from datetime import date, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from . import config, db, scheduler, search
from .adapters import AVAILABILITY_ADAPTERS
from .adapters.base import AdapterDisabled

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
                  (SELECT COUNT(*) FROM campsites) AS campsites,
                  (SELECT MAX(checked_at) FROM availability) AS last_checked,
                  (SELECT COUNT(*) FROM campgrounds WHERE source = 'demo') AS demo,
                  (SELECT COUNT(*) FROM campgrounds WHERE source = 'recgov') AS recgov_campgrounds""",
    ).fetchone()
    unchecked = conn.execute(
        """SELECT COUNT(*) FROM campgrounds c WHERE NOT EXISTS (
               SELECT 1 FROM campsites s JOIN availability v ON v.campsite_id = s.id
               WHERE s.campground_id = c.id)"""
    ).fetchone()[0]
    return {
        "agencies": agencies,
        "site_types": db.SITE_TYPES,
        **dict(stats),
        "demo": bool(stats["demo"]),
        "unchecked_campgrounds": unchecked,
        "recgov_availability_enabled": config.RECGOV_AVAILABILITY_ENABLED,
    }


def api_search(conn, params):
    today = date.today()
    start = _date(params, "start", today + timedelta(days=1))
    end = _date(params, "end", start + timedelta(days=2))
    results = search.search(
        conn, start, end,
        lat=_float(params, "lat"), lng=_float(params, "lng"), radius_mi=_float(params, "radius"),
        agency_id=params.get("agency") or None,
        include_fcfs=params.get("fcfs") in TRUE,
        sort=params.get("sort", "distance"),
        types=[t for t in params.get("types", "").split(",") if t],
        min_rv_length=_float(params, "rv_length"),
        electric=params.get("electric") in TRUE, water=params.get("water") in TRUE,
        sewer=params.get("sewer") in TRUE, ada=params.get("ada") in TRUE,
        pets=params.get("pets") in TRUE,
    )
    return {"start": start.isoformat(), "end": end.isoformat(), "results": results}


def api_campground(conn, params, campground_id):
    start = _date(params, "start", date.today())
    end = _date(params, "end", start + timedelta(days=13))
    cg = search.get_campground(conn, campground_id, start, end)
    if cg is None:
        return 404, {"error": "campground not found"}
    cg["live_check"] = live_check_available(cg)
    return 200, cg


def live_check_available(cg):
    if cg["source"] not in AVAILABILITY_ADAPTERS or not cg["reservable"]:
        return False
    return cg["source"] != "recgov" or config.RECGOV_AVAILABILITY_ENABLED


def api_check(conn, params, campground_id):
    start = _date(params, "start", date.today())
    end = _date(params, "end", start + timedelta(days=13))
    if end < start or (end - start).days > 62:
        raise search.SearchError("check at most two months at a time")
    try:
        return 200, scheduler.check_now(conn, campground_id, start, end)
    except LookupError as e:
        return 409, {"error": str(e)}
    except AdapterDisabled:
        return 409, {"error": "live checks for this source are switched off"}


def api_health(conn, _params):
    rows = conn.execute(
        """SELECT source,
                  COUNT(*) AS runs_24h,
                  SUM(ok = 1) AS ok_24h,
                  MAX(CASE WHEN ok = 1 THEN finished_at END) AS last_success,
                  (SELECT error FROM poll_runs p2 WHERE p2.source = p.source AND ok = 0
                   ORDER BY started_at DESC LIMIT 1) AS last_error
           FROM poll_runs p
           WHERE started_at >= datetime('now', '-1 day')
           GROUP BY source"""
    ).fetchall()
    return {"sources": [dict(r) for r in rows]}


class Handler(BaseHTTPRequestHandler):
    server_version = "CampsiteFinder/0.1"

    def log_message(self, fmt, *args):
        log.info("%s - " + fmt, self.address_string(), *args)

    def _send(self, status, body, content_type="application/json"):
        data = json.dumps(body, default=str).encode() if content_type == "application/json" else body
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        url = urlparse(self.path)
        params = {k: v[-1] for k, v in parse_qs(url.query).items()}
        if url.path.startswith("/api/"):
            return self._api(url.path, params)
        return self._static(url.path)

    def do_POST(self):
        url = urlparse(self.path)
        params = {k: v[-1] for k, v in parse_qs(url.query).items()}
        parts = url.path.strip("/").split("/")
        if len(parts) == 4 and parts[:2] == ["api", "campgrounds"] and parts[2].isdigit() and parts[3] == "check":
            return self._api(url.path, params, lambda conn: api_check(conn, params, int(parts[2])))
        return self._send(404, {"error": "not found"})

    def _api(self, path, params, handler=None):
        conn = db.connect()
        try:
            if handler:
                return self._send(*handler(conn))
            parts = path.strip("/").split("/")
            if path == "/api/meta":
                return self._send(200, api_meta(conn, params))
            if path == "/api/search":
                return self._send(200, api_search(conn, params))
            if path == "/api/health":
                return self._send(200, api_health(conn, params))
            if len(parts) == 3 and parts[1] == "campgrounds" and parts[2].isdigit():
                return self._send(*api_campground(conn, params, int(parts[2])))
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
        return self._send(200, target.read_bytes(), content_type)


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
