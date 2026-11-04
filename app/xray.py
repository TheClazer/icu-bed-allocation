"""X-Ray: read InnoDB's own bookkeeping while transactions run.

  information_schema.INNODB_TRX          active transactions
  performance_schema.data_locks          every lock held or requested
  performance_schema.data_lock_waits     who waits for whom (edges of the wait-for graph)
  SHOW ENGINE INNODB STATUS              text report; we parse LATEST DETECTED DEADLOCK
"""
import re
import threading
import time

from . import db

_status_cache = {"t": 0.0, "deadlock": None}
_status_lock = threading.Lock()


def _name(thread_id):
    s = db.lookup(thread_id) if thread_id is not None else None
    if s:
        return s["tx"], s["label"]
    return None, None


def snapshot():
    conn = db.raw_connect(timeout=1)
    try:
        with conn.cursor() as c:
            c.execute("SELECT CONNECTION_ID() AS id")
            me = c.fetchone()["id"]
            c.execute(
                "SELECT trx_id, trx_state, trx_mysql_thread_id AS thread_id, "
                "TIMESTAMPDIFF(MICROSECOND, trx_started, NOW(6)) / 1000000 AS age_s, "
                "trx_rows_locked, trx_rows_modified, trx_lock_structs, trx_isolation_level, "
                "trx_query, trx_operation_state, trx_wait_started "
                "FROM information_schema.INNODB_TRX ORDER BY trx_started")
            trx = [t for t in c.fetchall() if t["thread_id"] != me]
            c.execute(
                "SELECT ENGINE_TRANSACTION_ID AS trx_id, OBJECT_NAME AS tbl, INDEX_NAME AS idx, "
                "LOCK_TYPE AS type, LOCK_MODE AS mode, LOCK_STATUS AS status, LOCK_DATA AS data "
                "FROM performance_schema.data_locks WHERE OBJECT_SCHEMA = 'icu_beds' "
                "ORDER BY ENGINE_TRANSACTION_ID, LOCK_TYPE DESC")
            locks = c.fetchall()
            c.execute(
                "SELECT REQUESTING_ENGINE_TRANSACTION_ID AS waiting, BLOCKING_ENGINE_TRANSACTION_ID AS blocking "
                "FROM performance_schema.data_lock_waits")
            waits = c.fetchall()
    finally:
        conn.close()

    by_trx = {}
    for t in trx:
        tx, label = _name(t["thread_id"])
        t["tx"] = tx or f"conn {t['thread_id']}"
        t["label"] = label or "other connection"
        t["age_s"] = float(t["age_s"] or 0)
        by_trx[str(t["trx_id"])] = t
    for lk in locks:
        owner = by_trx.get(str(lk["trx_id"]))
        lk["tx"] = owner["tx"] if owner else str(lk["trx_id"])
    edges = []
    for w in waits:
        a, b = by_trx.get(str(w["waiting"])), by_trx.get(str(w["blocking"]))
        edges.append({"from": a["tx"] if a else str(w["waiting"]), "to": b["tx"] if b else str(w["blocking"])})

    return {
        "ts": time.time(),
        "transactions": trx,
        "locks": locks,
        "waits": edges,
        "deadlock": latest_deadlock(),
    }


# ---------------------------------------------------------------------------
# SHOW ENGINE INNODB STATUS parser
# ---------------------------------------------------------------------------
def latest_deadlock(max_age=2.0, force=False):
    with _status_lock:
        if not force and time.time() - _status_cache["t"] < max_age:
            return _status_cache["deadlock"]
    try:
        rows = db.query("SHOW ENGINE INNODB STATUS")
        text = rows[0]["Status"] if rows else ""
        parsed = parse_deadlock(text)
    except Exception:
        parsed = _status_cache["deadlock"]
    with _status_lock:
        _status_cache.update(t=time.time(), deadlock=parsed)
    return parsed


_MARK = re.compile(r"\*\*\* \((\d+)\) (TRANSACTION|HOLDS THE LOCK\(S\)|WAITING FOR THIS LOCK TO BE GRANTED):")


def _decode_int(hex_str):
    """InnoDB stores signed INT with the sign bit flipped: 80000065 -> 101."""
    try:
        return int(hex_str, 16) - 0x80000000
    except ValueError:
        return None


def _parse_lock(block):
    m = re.search(r"index (\S+) of table `([^`]+)`\.`([^`]+)`.*?lock[_ ]mode (\w+)([^\n]*)", block, re.S)
    if not m:
        return None
    rec = re.search(r"\n\s*0: len 4; hex ([0-9a-f]{8});", block)
    return {
        "index": m.group(1),
        "table": m.group(3),
        "mode": (m.group(4) + m.group(5)).replace(" waiting", "").strip(),
        "record": _decode_int(rec.group(1)) if rec else None,
    }


def parse_deadlock(text):
    m = re.search(r"LATEST DETECTED DEADLOCK\n-+\n(.*?)\n-{6,}\n", text, re.S)
    if not m:
        return None
    sec = m.group(1)
    when = sec.strip().splitlines()[0][:19] if sec.strip() else None
    marks = list(_MARK.finditer(sec))
    txs = {}
    for i, mk in enumerate(marks):
        n, kind = mk.group(1), mk.group(2)
        end = marks[i + 1].start() if i + 1 < len(marks) else len(sec)
        block = sec[mk.end():end]
        t = txs.setdefault(n, {"n": int(n)})
        if kind == "TRANSACTION":
            trx = re.search(r"TRANSACTION (\d+)", block)
            thr = re.search(r"MySQL thread id (\d+)", block)
            t["trx_id"] = trx.group(1) if trx else None
            t["thread_id"] = int(thr.group(1)) if thr else None
            lines = [ln for ln in block.strip().splitlines() if ln.strip()]
            qstart = next((k for k, ln in enumerate(lines) if ln.startswith("MySQL thread id")), None)
            t["query"] = " ".join(lines[qstart + 1:]).strip() if qstart is not None else None
            tx, label = _name(t["thread_id"])
            t["tx"], t["label"] = tx, label
        elif kind.startswith("HOLDS"):
            t["holds"] = _parse_lock(block)
        else:
            t["waits_for"] = _parse_lock(block.split("*** WE ROLL BACK")[0])
    victim = re.search(r"\*\*\* WE ROLL BACK TRANSACTION \((\d+)\)", sec)
    return {
        "when": when,
        "transactions": [txs[k] for k in sorted(txs)],
        "victim": int(victim.group(1)) if victim else None,
    }
