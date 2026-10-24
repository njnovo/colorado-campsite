"""Settings, read from environment variables or a .env file in the project root."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def load_env(path=ROOT / ".env"):
    """Minimal .env loader: KEY=VALUE lines, # comments. Real env vars win."""
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


load_env()


def _flag(name, default="false"):
    return os.environ.get(name, default).strip().lower() in ("1", "true", "yes", "on")


DB_PATH = os.environ.get("DB_PATH", str(ROOT / "data" / "campsites.db"))
STATIC_DIR = ROOT / "static"

RIDB_API_KEY = os.environ.get("RIDB_API_KEY", "")
CONTACT_EMAIL = os.environ.get("CONTACT_EMAIL", "")
USER_AGENT = f"ColoradoCampsiteFinder/0.1 (+{CONTACT_EMAIL or 'no-contact-set'})"

# Recreation.gov's robots.txt disallows /api/* (with Crawl-delay: 10).
# Live availability polling stays OFF until we have sanctioned access.
RECGOV_AVAILABILITY_ENABLED = _flag("RECGOV_AVAILABILITY_ENABLED")

# Only campgrounds on the watchlist (`manage.py watch add ...`) are polled, this many days ahead.
WATCH_DAYS = int(os.environ.get("WATCH_DAYS", "90"))

HOST = os.environ.get("HOST", "127.0.0.1")
PORT = int(os.environ.get("PORT", "8000"))
