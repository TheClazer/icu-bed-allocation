"""MySQL access with every statement made visible.

Session wraps one PyMySQL connection. Each statement goes through Session.run(),
which records the exact SQL (parameters filled in), duration, row count and any
MySQL error, and streams it to the SQL Log tab. Transactions are written out as
real START TRANSACTION / COMMIT / ROLLBACK statements so they show up too.

No ORM: what you see in the log is exactly what MySQL received.
"""
import itertools
import json
import threading
import time

import pymysql
from pymysql.cursors import DictCursor

from .config import INSTANCE, MYSQL, READONLY_USER, REPLICA
from .hub import hub

_tx_ids = itertools.count(1)
_seq = itertools.count(1)

# connection id -> {"tx": "T12", "label": "...", "instance": "app-1"}; lets X-Ray name transactions.
# Kept locally and mirrored to Redis so every app instance can name every connection.
sessions = {}
_sessions_lock = threading.Lock()

ERROR_MEANING = {
    1062: "UNIQUE index one_active_booking_per_bed rejected a second live hold on the same bed",
    1213: "InnoDB found a deadlock (a cycle in the wait-for graph) and rolled this transaction back",
    1205: "Lock wait timeout: waited too long for a row lock held by another transaction",
    1644: "A trigger raised SIGNAL and refused the change",
    3819: "A CHECK constraint was violated",
    1452: "A FOREIGN KEY constraint was violated",
    1142: "The read-only MySQL user is not allowed to run this command",
    1290: "The server is read-only (super_read_only), writes must go to the primary",
    1792: "This is a READ ONLY transaction, writes are not allowed",
    2013: "Lost connection to MySQL during the query",
    2003: "Cannot connect to MySQL",
    2006: "MySQL server has gone away",
}
CONNECTION_ERRORS = {2003, 2006, 2013, 2055}


def err_code(exc):
    if exc.args and isinstance(exc.args[0], int):
        return exc.args[0]
    return None


def err_text(exc):
    if len(exc.args) > 1:
        return str(exc.args[1])
    return str(exc)


def raw_connect(readonly=False, replica=False, timeout=3):
    cfg = dict(REPLICA if replica else MYSQL)
    if readonly:
        cfg.update(READONLY_USER)
    return pymysql.connect(
        **cfg,
        autocommit=True,
        cursorclass=DictCursor,
        connect_timeout=timeout,
        read_timeout=90,
        write_timeout=30,
        charset="utf8mb4",
    )


# ---------------------------------------------------------------------------
# connection registry
# ---------------------------------------------------------------------------
def register(conn_id, tx, label, target="primary"):
    info = {"tx": tx, "label": label, "instance": INSTANCE, "t": time.time()}
    key = f"{target}:{conn_id}"
    with _sessions_lock:
        sessions[key] = info
        if len(sessions) > 500:
            now = time.time()
            for k in [k for k, v in sessions.items() if now - v["t"] > 600]:
                sessions.pop(k, None)
    try:
        from .redis_client import r
        r.set(f"session:{key}", json.dumps(info), ex=900)
    except Exception:
        pass


def lookup(conn_id, target="primary"):
    key = f"{target}:{conn_id}"
    with _sessions_lock:
        if key in sessions:
            return sessions[key]
    try:
        from .redis_client import r
        raw = r.get(f"session:{key}")
        if raw:
            return json.loads(raw)
    except Exception:
        pass
    return None


def statement_kind(sql):
    head = sql.lstrip().split(None, 2)
    if not head:
        return ""
    word = head[0].upper()
    return "BEGIN" if word == "START" else word


# ---------------------------------------------------------------------------
# logged session
# ---------------------------------------------------------------------------
class Session:
    """One connection, one label, every statement logged."""

    def __init__(self, label, user_id=None, log=True, readonly=False, replica=False):
        self.label = label
        self.user_id = user_id
        self.log = log
        self.readonly = readonly
        self.target = "replica" if replica else "primary"
        self.tx = f"T{next(_tx_ids)}" if INSTANCE == "app-1" else f"{INSTANCE[-1]}T{next(_tx_ids)}"
        self.conn = None
        self.conn_id = None
        self.in_tx = False
        self.lastrowid = None
        self.rowcount = 0
        self.trace = []
        self.t0 = time.perf_counter()

    def __enter__(self):
        self.conn = raw_connect(readonly=self.readonly, replica=self.target == "replica")
        with self.conn.cursor() as c:
            c.execute("SELECT CONNECTION_ID() AS id")
            self.conn_id = c.fetchone()["id"]
            if self.user_id is not None and not self.readonly:
                c.execute("SET @app_user_id = %s", (self.user_id,))
        register(self.conn_id, self.tx, self.label, self.target)
        return self

    def __exit__(self, exc_type, exc, tb):
        if self.in_tx:
            try:
                self.rollback()
            except Exception:
                pass
        try:
            self.conn.close()
        except Exception:
            pass
        return False

    def run(self, sql, params=None):
        with self.conn.cursor() as cur:
            text = cur.mogrify(sql, params) if params is not None else sql
            seq = next(_seq)
            started = time.perf_counter()
            self._emit(seq, text, "start")
            try:
                cur.execute(sql, params)
                rows = cur.fetchall() if cur.description else []
            except pymysql.MySQLError as exc:
                self._emit(seq, text, "end", started, error=exc)
                raise
            self.lastrowid = cur.lastrowid
            self.rowcount = cur.rowcount
            self._emit(seq, text, "end", started, rows=len(rows) if cur.description else cur.rowcount)
            return list(rows)

    def one(self, sql, params=None):
        rows = self.run(sql, params)
        return rows[0] if rows else None

    def begin(self):
        self.run("START TRANSACTION")
        self.in_tx = True

    def commit(self):
        self.run("COMMIT")
        self.in_tx = False

    def rollback(self):
        self.in_tx = False
        self.run("ROLLBACK")

    def note_redis(self, command, started, error=None, rows=None):
        """Show a Redis command in the same timeline as the SQL."""
        self._emit(next(_seq), command, "end", started, rows=rows, error_text=error, kind="REDIS")

    def _emit(self, seq, text, phase, started=None, rows=None, error=None, error_text=None, kind=None):
        now = time.perf_counter()
        entry = {
            "type": "sql", "phase": phase, "seq": f"{INSTANCE}:{seq}", "ts": time.time(),
            "instance": INSTANCE, "target": self.target, "tx": self.tx, "label": self.label,
            "conn": self.conn_id, "sql": text, "kind": kind or statement_kind(text),
        }
        if phase == "end":
            entry["ms"] = round((now - started) * 1000, 1) if started else 0
            entry["rows"] = rows
            entry["ok"] = error is None and error_text is None
            if error is not None:
                code = err_code(error)
                entry["error"] = f"{code} {err_text(error)}" if code else err_text(error)
                entry["code"] = code
            elif error_text:
                entry["error"] = error_text
            self.trace.append({
                "at_ms": round((started - self.t0) * 1000) if started else 0,
                "ms": entry["ms"], "sql": text, "kind": entry["kind"], "ok": entry["ok"],
                "error": entry.get("error"), "rows": rows,
            })
        if self.log:
            hub.emit(entry)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def query(sql, params=None, readonly=False, replica=False, timeout=2):
    """Unlogged query for background polling (dashboards, X-Ray, metrics)."""
    conn = raw_connect(readonly=readonly, replica=replica, timeout=timeout)
    try:
        with conn.cursor() as c:
            c.execute(sql, params)
            return list(c.fetchall()) if c.description else []
    finally:
        conn.close()


def alive(replica=False):
    try:
        conn = raw_connect(replica=replica, timeout=1)
        try:
            with conn.cursor() as c:
                c.execute("SELECT 1")
            return True
        finally:
            conn.close()
    except Exception:
        return False


def log_system(text, ok=True, error=None, label="System"):
    """A one-line entry in the SQL log for things that are not a single statement."""
    hub.emit({
        "type": "sql", "phase": "end", "seq": f"{INSTANCE}:{next(_seq)}", "ts": time.time(),
        "instance": INSTANCE, "target": "primary", "tx": "SYS", "label": label, "conn": None,
        "sql": text, "kind": "NOTE", "ms": 0, "rows": None, "ok": ok, "error": error,
    })
