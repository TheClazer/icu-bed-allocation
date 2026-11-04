"""Redis: the NoSQL half of the system.

  hospitals:geo            GEO set, one member per hospital, for nearest-first search
  free:{hospital}:{type}   string counter, free beds, for the dashboard and search filter
  events                   pub/sub channel, every change, forwarded to browsers

Rule: MySQL is the source of truth. Counters are only written after a MySQL
COMMIT, always by re-reading the count from MySQL (idempotent, cannot drift),
and /api/redis/rebuild recreates everything from MySQL. If Redis is down the
app falls back to MySQL for search, so a Redis failure slows things down but
never causes a wrong booking.
"""
import json
import threading
import time
import uuid
from collections import deque

import redis

from . import db
from .config import INSTANCE, REDIS_HOST, REDIS_PORT
from .hub import hub

GEO_KEY = "hospitals:geo"
CHANNEL = "events"

r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True,
                socket_timeout=1, socket_connect_timeout=1)

recent_events = deque(maxlen=60)


def counter_key(hospital_id, bed_type_id):
    return f"free:{hospital_id}:{bed_type_id}"


def alive():
    try:
        return bool(r.ping())
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Build and refresh from MySQL
# ---------------------------------------------------------------------------
def rebuild():
    """Recreate every Redis key from MySQL."""
    hospitals = db.query("SELECT hospital_id, latitude, longitude FROM hospital")
    counts = db.query(
        "SELECT h.hospital_id, t.bed_type_id, COUNT(b.bed_id) AS free "
        "FROM hospital h CROSS JOIN bed_type t "
        "LEFT JOIN bed b ON b.hospital_id = h.hospital_id AND b.bed_type_id = t.bed_type_id AND b.status = 'FREE' "
        "GROUP BY h.hospital_id, t.bed_type_id")
    pipe = r.pipeline()
    pipe.delete(GEO_KEY)
    for k in r.scan_iter("free:*"):
        pipe.delete(k)
    geo = []
    for h in hospitals:
        geo += [float(h["longitude"]), float(h["latitude"]), str(h["hospital_id"])]
    if geo:
        pipe.geoadd(GEO_KEY, geo)
    for c in counts:
        pipe.set(counter_key(c["hospital_id"], c["bed_type_id"]), int(c["free"]))
    pipe.execute()
    db.log_system(f"REDIS rebuilt from MySQL: GEOADD {len(hospitals)} hospitals, SET {len(counts)} counters",
                  label="Redis rebuild")
    return {"hospitals": len(hospitals), "counters": len(counts)}


def refresh_counter(hospital_id, bed_type_id, session=None):
    """Re-read one free-bed count from MySQL and store it. Called after COMMIT."""
    sql = ("SELECT COUNT(*) AS free FROM bed "
           "WHERE hospital_id = %s AND bed_type_id = %s AND status = 'FREE'")
    if session is not None:
        free = session.one(sql, (hospital_id, bed_type_id))["free"]
    else:
        free = db.query(sql, (hospital_id, bed_type_id))[0]["free"]
    key = counter_key(hospital_id, bed_type_id)
    started = time.perf_counter()
    try:
        r.set(key, int(free))
        if session is not None:
            session.note_redis(f"REDIS SET {key} {free}", started)
    except Exception as exc:
        if session is not None:
            session.note_redis(f"REDIS SET {key} {free}", started, error=f"Redis unavailable: {exc.__class__.__name__}")
    return free


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------
def nearest(lat, lon, radius_km, session=None):
    """[(hospital_id, km)] nearest first, via GEOSEARCH. Raises if Redis is down."""
    started = time.perf_counter()
    cmd = f"REDIS GEOSEARCH {GEO_KEY} FROMLONLAT {lon:.4f} {lat:.4f} BYRADIUS {radius_km} km ASC WITHDIST"
    try:
        res = r.geosearch(GEO_KEY, longitude=lon, latitude=lat, radius=radius_km, unit="km",
                          sort="ASC", withdist=True)
    except Exception as exc:
        if session is not None:
            session.note_redis(cmd, started, error=f"Redis unavailable ({exc.__class__.__name__}), falling back to MySQL")
        raise
    out = [(int(m), round(float(d), 2)) for m, d in res]
    if session is not None:
        session.note_redis(cmd, started, rows=len(out))
    return out


def free_counts_for(hospital_ids, bed_type_id, session=None):
    keys = [counter_key(h, bed_type_id) for h in hospital_ids]
    if not keys:
        return {}
    started = time.perf_counter()
    vals = r.mget(keys)
    if session is not None:
        session.note_redis("REDIS MGET " + " ".join(keys), started, rows=len(keys))
    return {h: int(v) if v is not None else None for h, v in zip(hospital_ids, vals)}


def all_counts():
    out = {}
    for k in r.scan_iter("free:*"):
        _, h, t = k.split(":")
        out[(int(h), int(t))] = None
    keys = [counter_key(h, t) for h, t in out]
    vals = r.mget(keys) if keys else []
    for (h, t), v in zip(list(out), vals):
        out[(h, t)] = int(v) if v is not None else None
    return out


def geo_members():
    members = r.zrange(GEO_KEY, 0, -1)
    if not members:
        return []
    pos = r.geopos(GEO_KEY, *members)
    return [{"member": m, "lon": round(p[0], 5), "lat": round(p[1], 5)} for m, p in zip(members, pos) if p]


# ---------------------------------------------------------------------------
# Pub/sub
# ---------------------------------------------------------------------------
def publish(event):
    """Publish to the Redis channel; if Redis is down, deliver directly instead."""
    event.setdefault("ts", time.time())
    event.setdefault("id", uuid.uuid4().hex[:12])     # browsers listening to several instances dedupe on this
    event.setdefault("origin", INSTANCE)
    payload = json.dumps(event, default=str)
    try:
        r.publish(CHANNEL, payload)
    except Exception:
        msg = {"type": "event", "via": "direct (Redis down)", "data": event}
        recent_events.appendleft(msg)
        hub.emit(msg)


def _subscriber_loop():
    while True:
        try:
            ps = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True,
                             socket_connect_timeout=1).pubsub(ignore_subscribe_messages=True)
            ps.subscribe(CHANNEL)
            for message in ps.listen():
                if message.get("type") != "message":
                    continue
                try:
                    data = json.loads(message["data"])
                except ValueError:
                    data = {"raw": message["data"]}
                msg = {"type": "event", "via": "redis pub/sub", "data": data}
                recent_events.appendleft(msg)
                hub.emit(msg)
        except Exception:
            time.sleep(1.0)


def start_subscriber():
    threading.Thread(target=_subscriber_loop, name="redis-subscriber", daemon=True).start()
