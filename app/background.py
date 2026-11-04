"""Background threads of one app instance.

  health    pings MySQL primary, replica, Redis and peer app instances every second
  watcher   tails audit_log (the trigger-written change feed): publishes each new
            row on Redis pub/sub and refreshes the Redis counter of any bed that changed,
            including changes made by the MySQL event scheduler that the app never saw
  metrics   samples server metrics every second (and app-1 writes the replication probe)
"""
import json
import threading
import time
import urllib.request

from . import db, meta, metrics
from . import redis_client as rc
from .config import INSTANCE, INTERNAL_INSTANCES, parse_instances
from .hub import hub

health = {"mysql": None, "replica": None, "redis": None, "instances": {}}
_watch = {"last_id": None, "seen": set()}
_watch_lock = threading.Lock()


def watcher_reset():
    with _watch_lock:
        _watch["last_id"] = 0
        _watch["seen"] = set()


def _health_loop():
    peers = parse_instances(INTERNAL_INSTANCES)
    while True:
        mysql_up, replica_up, redis_up = db.alive(), db.alive(replica=True), rc.alive()
        inst = {INSTANCE: True}
        for p in peers:
            if p["name"] == INSTANCE:
                continue
            try:
                with urllib.request.urlopen(p["url"] + "/api/ping", timeout=0.8) as resp:
                    inst[p["name"]] = resp.status == 200
            except Exception:
                inst[p["name"]] = False
        changed = (mysql_up, replica_up, redis_up, inst) != (health["mysql"], health["replica"], health["redis"], health["instances"])
        came_back = (redis_up and health["redis"] is False) or (mysql_up and health["mysql"] is False) \
            or (mysql_up and redis_up and health["redis"] is None)
        health.update(mysql=mysql_up, replica=replica_up, redis=redis_up, instances=inst)
        if changed:
            hub.emit({"type": "status", "instance": INSTANCE, **health})
        if came_back and mysql_up and redis_up:
            try:
                meta.load(force=True)
                rc.rebuild()
            except Exception:
                pass
        time.sleep(1.0)


def _watcher_loop():
    while True:
        time.sleep(0.6)
        if not health.get("mysql"):
            continue
        try:
            with _watch_lock:
                last = _watch["last_id"]
            top = int(db.query("SELECT COALESCE(MAX(log_id), 0) AS m FROM audit_log")[0]["m"])
            if last is None:
                with _watch_lock:
                    _watch["last_id"] = top
                continue
            if top < last:            # audit_log was truncated (demo data re-seeded by any process)
                watcher_reset()
                last = 0
            rows = db.query(
                "SELECT log_id, user_id, action, entity_name, entity_id, details, created_at "
                "FROM audit_log WHERE log_id > %s ORDER BY log_id LIMIT 300", (max(0, last - 30),))
            touched = set()
            for r in rows:
                lid = int(r["log_id"])
                with _watch_lock:
                    if lid in _watch["seen"]:
                        continue
                    _watch["seen"].add(lid)
                    _watch["last_id"] = max(_watch["last_id"], lid)
                    if len(_watch["seen"]) > 2000:
                        _watch["seen"] = {x for x in _watch["seen"] if x > _watch["last_id"] - 200}
                details = r["details"]
                if isinstance(details, str):
                    try:
                        details = json.loads(details)
                    except ValueError:
                        pass
                if r["entity_name"] == "bed" and isinstance(details, dict):
                    touched.add((details.get("hospital_id"), details.get("bed_type_id")))
                try:   # several app instances tail the same log: only the first publishes a row
                    first = rc.r.set(f"audit:published:{lid}:{r['created_at']}", 1, nx=True, ex=300)
                except Exception:
                    first = True
                if first:
                    rc.publish({"kind": "audit", "log_id": lid, "action": r["action"], "entity": r["entity_name"],
                            "entity_id": r["entity_id"], "user_id": r["user_id"], "details": details,
                            "by": "mysql event scheduler" if r["user_id"] is None and r["action"].endswith("EXPIRED") else None})
            for h, t in touched:
                if h and t:
                    try:
                        rc.refresh_counter(h, t)
                    except Exception:
                        pass
        except Exception:
            time.sleep(1.0)


def _metrics_loop():
    metrics.enable_innodb_monitors()
    while True:
        t0 = time.time()
        if INSTANCE == "app-1" and health.get("mysql"):
            try:
                metrics.write_probe()
            except Exception:
                pass
        try:
            metrics.sample_once()
        except Exception:
            pass
        time.sleep(max(0.2, 1.0 - (time.time() - t0)))


def start():
    for target, name in ((_health_loop, "health"), (_watcher_loop, "audit-watcher"), (_metrics_loop, "metrics")):
        threading.Thread(target=target, name=name, daemon=True).start()
    rc.start_subscriber()
