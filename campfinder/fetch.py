"""Shared polite HTTP client (PLAN.md §3.5).

Every adapter goes through get_json(), which enforces a per-source minimum
interval between requests, sends an honest User-Agent, and backs off on
429 / 5xx responses.
"""
import fcntl
import json
import random
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from . import config

# Minimum seconds between requests, per source.
SOURCE_INTERVALS = {
    "ridb": 1.0,
    "recgov": 10.0,  # matches recreation.gov's robots.txt Crawl-delay
}
DEFAULT_INTERVAL = 5.0
RETRY_STATUSES = {429, 500, 502, 503, 504}


class FetchError(Exception):
    def __init__(self, message, status=None):
        super().__init__(message)
        self.status = status


class RateLimiter:
    """Minimum interval between requests per source.

    With state_dir, the last-request time lives in a locked file, so the web
    server (on-demand checks) and the poller process share one limit.
    """

    def __init__(self, intervals=None, sleep=time.sleep, clock=time.monotonic, state_dir=None):
        self.intervals = intervals if intervals is not None else SOURCE_INTERVALS
        self._last = {}
        self._lock = threading.Lock()
        self._sleep = sleep
        self._clock = time.time if state_dir else clock
        self._state_dir = Path(state_dir) if state_dir else None

    def _delay(self, source, last):
        interval = self.intervals.get(source, DEFAULT_INTERVAL)
        if last is None:
            return 0
        return last + interval * random.uniform(1.0, 1.25) - self._clock()

    def wait(self, source):
        with self._lock:
            if self._state_dir is None:
                delay = self._delay(source, self._last.get(source))
                if delay > 0:
                    self._sleep(delay)
                self._last[source] = self._clock()
                return
            self._state_dir.mkdir(parents=True, exist_ok=True)
            with open(self._state_dir / f"ratelimit-{source}", "a+") as fh:
                fcntl.flock(fh, fcntl.LOCK_EX)  # other processes wait here
                fh.seek(0)
                text = fh.read().strip()
                delay = self._delay(source, float(text) if text else None)
                if delay > 0:
                    self._sleep(delay)
                fh.seek(0)
                fh.truncate()
                fh.write(str(self._clock()))


limiter = RateLimiter(state_dir=Path(config.DB_PATH).parent if config.DB_PATH != ":memory:" else None)


def build_url(url, params=None):
    if not params:
        return url
    # quote_via=quote encodes ':' in ISO timestamps, which recreation.gov requires.
    return f"{url}?{urllib.parse.urlencode(params, quote_via=urllib.parse.quote)}"


def get_json(source, url, params=None, headers=None, retries=4, timeout=30):
    """GET a JSON document. Returns (http_status, parsed_json)."""
    full_url = build_url(url, params)
    req_headers = {"User-Agent": config.USER_AGENT, "Accept": "application/json"}
    req_headers.update(headers or {})

    for attempt in range(retries + 1):
        limiter.wait(source)
        request = urllib.request.Request(full_url, headers=req_headers)
        try:
            with urllib.request.urlopen(request, timeout=timeout) as resp:
                body = resp.read()
                try:
                    return resp.status, json.loads(body)
                except ValueError as e:
                    raise FetchError(f"{source}: response is not JSON", resp.status) from e
        except urllib.error.HTTPError as e:
            if e.code in RETRY_STATUSES and attempt < retries:
                retry_after = e.headers.get("Retry-After", "")
                wait = float(retry_after) if retry_after.isdigit() else 2 ** (attempt + 2)
                time.sleep(wait + random.uniform(0, 1))
                continue
            snippet = e.read(300).decode("utf-8", "replace")
            raise FetchError(f"{source}: HTTP {e.code}: {snippet}", e.code) from e
        except (urllib.error.URLError, TimeoutError) as e:
            if attempt < retries:
                time.sleep(2 ** (attempt + 2) + random.uniform(0, 1))
                continue
            raise FetchError(f"{source}: network error: {e}") from e
    raise FetchError(f"{source}: gave up after {retries} retries")
