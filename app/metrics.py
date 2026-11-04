"""Server metrics, sampled once a second.

MySQL:  SHOW GLOBAL STATUS counters turned into per-second rates, InnoDB
        buffer pool hit ratio, row lock waits, INNODB_METRICS (deadlocks,
        history list length = undo records waiting for purge), table sizes.
Replica: SHOW REPLICA STATUS + a probe row the primary rewrites every second;
        lag = how old the replica's copy of that row is.
Redis:  INFO (memory, ops per second, hit ratio, clients).
"""
import threading
import time
from collections import deque

from . import db
from . import redis_client as rc
from .config import INSTANCE

STATUS_VARS = [
    "Questions", "Com_commit", "Com_rollback", "Com_select", "Com_insert", "Com_update", "Com_delete",
    "Innodb_row_lock_waits", "Innodb_row_lock_current_waits", "Innodb_row_lock_time",
    "Innodb_buffer_pool_read_requests", "Innodb_buffer_pool_reads", "Innodb_buffer_pool_pages_total",
    "Innodb_buffer_pool_pages_free", "Innodb_buffer_pool_pages_dirty",
    "Innodb_rows_read", "Innodb_rows_inserted", "Innodb_rows_updated", "Innodb_rows_deleted",
    "Innodb_os_log_written", "Innodb_data_fsyncs", "Threads_connected", "Threads_running",
    "Max_used_connections", "Uptime", "Bytes_received", "Bytes_sent", "Slow_queries",
]
RATES = {
    "qps": "Questions", "commits": "Com_commit", "rollbacks": "Com_rollback",
    "selects": "Com_select", "inserts": "Com_insert", "updates": "Com_update", "deletes": "Com_delete",
    "rows_read": "Innodb_rows_read", "rows_written": None, "lock_waits": "Innodb_row_lock_waits",
    "redo_bytes": "Innodb_os_log_written", "fsyncs": "Innodb_data_fsyncs",
}
SERIES = ["qps", "tps", "rows_read", "rows_written", "lock_waits", "threads_running", "hit_ratio",
          "replica_lag_ms", "redis_ops", "deadlocks"]

_lock = threading.Lock()
history = {k: deque(maxlen=90) for k in SERIES}
latest = {"ts": 0, "mysql": None, "replica": None, "redis": None, "tables": [], "instance": INSTANCE}
_prev = {"t": None, "status": None}
_tables_at = [0.0]


def _status():
    rows = db.query("SHOW GLOBAL STATUS WHERE Variable_name IN (%s)" % ",".join(["%s"] * len(STATUS_VARS)),
                    STATUS_VARS)
    return {r["Variable_name"]: float(r["Value"]) for r in rows}


def _innodb_metrics():
    rows = db.query("SELECT NAME, COUNT FROM information_schema.INNODB_METRICS "
                    "WHERE NAME IN ('lock_deadlocks', 'lock_timeouts', 'trx_rseg_history_len', 'lock_row_lock_current_waits')")
    return {r["NAME"]: int(r["COUNT"]) for r in rows}


def enable_innodb_monitors():
    for name in ("lock_deadlocks", "lock_timeouts", "trx_rseg_history_len"):
        try:
            db.query("SET GLOBAL innodb_monitor_enable = %s", (name,))
        except Exception:
            pass


def _sample_mysql(now):
    st = _status()
    im = _innodb_metrics()
    out = {"up": True, "uptime_s": int(st.get("Uptime", 0))}
    prev = _prev["status"]
    dt = (now - _prev["t"]) if _prev["t"] else None
    rate = {}
    if prev and dt and dt > 0:
        for k, var in RATES.items():
            if var:
                rate[k] = max(0.0, (st.get(var, 0) - prev.get(var, 0)) / dt)
        rate["rows_written"] = max(0.0, sum(st.get(v, 0) - prev.get(v, 0) for v in
                                            ("Innodb_rows_inserted", "Innodb_rows_updated", "Innodb_rows_deleted")) / dt)
    _prev.update(t=now, status=st)
    req, miss = st.get("Innodb_buffer_pool_read_requests", 0), st.get("Innodb_buffer_pool_reads", 0)
    total_pages = st.get("Innodb_buffer_pool_pages_total", 0) or 1
    out.update({
        "rates": {k: round(v, 2) for k, v in rate.items()},
        "tps": round(rate.get("commits", 0) + rate.get("rollbacks", 0), 2),
        "hit_ratio": round(100 * (1 - miss / req), 3) if req else 100.0,
        "buffer_pool_used_pct": round(100 * (1 - st.get("Innodb_buffer_pool_pages_free", 0) / total_pages), 1),
        "dirty_pages": int(st.get("Innodb_buffer_pool_pages_dirty", 0)),
        "threads_connected": int(st.get("Threads_connected", 0)),
        "threads_running": int(st.get("Threads_running", 0)),
        "max_used_connections": int(st.get("Max_used_connections", 0)),
        "row_lock_waits_total": int(st.get("Innodb_row_lock_waits", 0)),
        "row_lock_current_waits": int(st.get("Innodb_row_lock_current_waits", 0)),
        "row_lock_time_ms": int(st.get("Innodb_row_lock_time", 0)),
        "commits_total": int(st.get("Com_commit", 0)),
        "rollbacks_total": int(st.get("Com_rollback", 0)),
        "questions_total": int(st.get("Questions", 0)),
        "slow_queries": int(st.get("Slow_queries", 0)),
        "deadlocks_total": im.get("lock_deadlocks", 0),
        "lock_timeouts_total": im.get("lock_timeouts", 0),
        "history_list_length": im.get("trx_rseg_history_len", 0),
        "bytes_in": int(st.get("Bytes_received", 0)),
        "bytes_out": int(st.get("Bytes_sent", 0)),
    })
    try:
        g = db.query("SELECT @@GLOBAL.gtid_executed AS gtid, @@server_id AS server_id, @@transaction_isolation AS iso")[0]
        out.update(gtid=g["gtid"], server_id=g["server_id"], isolation=g["iso"])
    except Exception:
        pass
    return out


def _sample_replica():
    try:
        rows = db.query("SHOW REPLICA STATUS", replica=True, timeout=1)
    except Exception as exc:
        return {"up": False, "error": exc.__class__.__name__}
    if not rows:
        return {"up": True, "configured": False}
    s = rows[0]
    lag_ms = None
    try:
        p = db.query("SELECT written_at FROM replication_probe WHERE id = 1")[0]["written_at"]
        q = db.query("SELECT written_at FROM replication_probe WHERE id = 1", replica=True, timeout=1)[0]["written_at"]
        lag_ms = max(0, int((p - q).total_seconds() * 1000))
    except Exception:
        pass
    try:
        g = db.query("SELECT @@GLOBAL.gtid_executed AS gtid, @@server_id AS server_id, @@super_read_only AS ro",
                     replica=True, timeout=1)[0]
    except Exception:
        g = {}
    return {
        "up": True, "configured": True,
        "io_running": s.get("Replica_IO_Running"), "sql_running": s.get("Replica_SQL_Running"),
        "seconds_behind": s.get("Seconds_Behind_Source"), "lag_ms": lag_ms,
        "source": f"{s.get('Source_Host')}:{s.get('Source_Port')}",
        "last_error": s.get("Last_SQL_Error") or s.get("Last_IO_Error") or "",
        "retrieved_gtid": s.get("Retrieved_Gtid_Set"), "executed_gtid": g.get("gtid"),
        "server_id": g.get("server_id"), "super_read_only": bool(g.get("ro")),
    }


def _sample_redis():
    try:
        info = rc.r.info()
    except Exception:
        return {"up": False}
    hits, misses = info.get("keyspace_hits", 0), info.get("keyspace_misses", 0)
    keys = sum(v.get("keys", 0) for k, v in info.items() if k.startswith("db") and isinstance(v, dict))
    return {
        "up": True, "version": info.get("redis_version"), "used_memory": info.get("used_memory_human"),
        "ops": info.get("instantaneous_ops_per_sec", 0), "clients": info.get("connected_clients", 0),
        "commands_total": info.get("total_commands_processed", 0), "keys": keys,
        "hit_ratio": round(100 * hits / (hits + misses), 1) if hits + misses else None,
        "pubsub_channels": info.get("pubsub_channels", 0), "uptime_s": info.get("uptime_in_seconds", 0),
    }


def _sample_tables():
    rows = db.query(
        "SELECT TABLE_NAME AS name, DATA_LENGTH AS data_bytes, INDEX_LENGTH AS index_bytes "
        "FROM information_schema.TABLES WHERE TABLE_SCHEMA = 'icu_beds' AND TABLE_TYPE = 'BASE TABLE' ORDER BY TABLE_NAME")
    counts = db.query(" UNION ALL ".join(
        f"SELECT '{r['name']}' AS name, COUNT(*) AS n FROM `{r['name']}`" for r in rows)) if rows else []
    n = {c["name"]: c["n"] for c in counts}
    return [{**r, "rows": n.get(r["name"], 0)} for r in rows]


def sample_once():
    now = time.time()
    snap = {"ts": now, "instance": INSTANCE}
    try:
        snap["mysql"] = _sample_mysql(now)
    except Exception as exc:
        snap["mysql"] = {"up": False, "error": exc.__class__.__name__}
        _prev.update(t=None, status=None)
    snap["replica"] = _sample_replica()
    snap["redis"] = _sample_redis()
    if now - _tables_at[0] > 5 and snap["mysql"].get("up"):
        try:
            snap["tables"] = _sample_tables()
            _tables_at[0] = now
        except Exception:
            pass
    with _lock:
        if "tables" not in snap:
            snap["tables"] = latest.get("tables", [])
        latest.update(snap)
        m, rp, rd = snap["mysql"], snap["replica"], snap["redis"]
        point = {
            "qps": m.get("rates", {}).get("qps"), "tps": m.get("tps"),
            "rows_read": m.get("rates", {}).get("rows_read"), "rows_written": m.get("rates", {}).get("rows_written"),
            "lock_waits": m.get("row_lock_current_waits"), "threads_running": m.get("threads_running"),
            "hit_ratio": m.get("hit_ratio"), "replica_lag_ms": rp.get("lag_ms"),
            "redis_ops": rd.get("ops"), "deadlocks": m.get("deadlocks_total"),
        }
        for k in SERIES:
            history[k].append([round(now, 1), point.get(k)])


def write_probe():
    """Only app-1 writes the probe, once a second, so lag can be measured."""
    db.query("INSERT INTO replication_probe (id, written_at) VALUES (1, NOW(6)) "
             "ON DUPLICATE KEY UPDATE written_at = NOW(6)")


def snapshot():
    with _lock:
        return {**latest, "history": {k: list(v) for k, v in history.items()}}
