"""Runtime configuration, read from environment variables set by app/services.py."""
import os
from pathlib import Path

MYSQL = {
    "host": os.getenv("MYSQL_HOST", "127.0.0.1"),
    "port": int(os.getenv("MYSQL_PORT", "3307")),
    "user": os.getenv("MYSQL_USER", "root"),
    "password": os.getenv("MYSQL_PASSWORD", "rootpass"),
    "database": os.getenv("MYSQL_DATABASE", "icu_beds"),
}
# Read replica (GTID asynchronous replication from the primary)
REPLICA = {
    **MYSQL,
    "host": os.getenv("REPLICA_HOST", "127.0.0.1"),
    "port": int(os.getenv("REPLICA_PORT", "3308")),
}
READONLY_USER = {"user": "icu_readonly", "password": "readonly"}

REDIS_HOST = os.getenv("REDIS_HOST", "127.0.0.1")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))

# This app process, and every app instance the browser should listen to
INSTANCE = os.getenv("INSTANCE_NAME", "app-1")
# "app-1=http://localhost:8000,app-2=http://localhost:8001" as seen from the browser
PUBLIC_INSTANCES = os.getenv("PUBLIC_INSTANCES", "app-1=http://localhost:8000")
# the same instances as the app processes reach each other
INTERNAL_INSTANCES = os.getenv("INTERNAL_INSTANCES", "app-1=http://127.0.0.1:8000")


def parse_instances(spec):
    out = []
    for part in spec.split(","):
        if "=" in part:
            name, url = part.split("=", 1)
            out.append({"name": name.strip(), "url": url.strip().rstrip("/")})
    return out


ROOT = Path(__file__).resolve().parent.parent
DB_DIR = ROOT / "db"
WEB_DIR = ROOT / "web" / "dist"

HOLD_MINUTES = 30
SEARCH_RADIUS_KM = 50
