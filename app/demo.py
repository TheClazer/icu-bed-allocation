"""Evaluator demos. Each one provokes a real database behaviour and returns
enough detail for the UI to show what happened and why."""
import json
import threading
import time
import urllib.request

import pymysql

from . import booking, containers, db, meta, state, transfer, xray
from . import redis_client as rc
from .areas import BY_NAME
from .config import (DB_DIR, INSTANCE, INTERNAL_INSTANCES, MYSQL_CONTAINER, REDIS_CONTAINER,
                     parse_instances)
from .hub import hub

_demo_lock = threading.Lock()


def progress(demo, step, text, state_="run", **extra):
    hub.emit({"type": "demo", "demo": demo, "step": step, "text": text, "state": state_, **extra})


def _wait_until(t):
    delay = t - time.time()
    if delay > 0:
        time.sleep(delay)


# ---------------------------------------------------------------------------
# 1. Race for the last bed
# ---------------------------------------------------------------------------
def race_setup():
    rows = db.query(
        "SELECT t.bed_type_id, t.name, COUNT(b.bed_id) AS free, MIN(b.bed_id) AS bed_id, MIN(b.hospital_id) AS hospital_id "
        "FROM bed_type t LEFT JOIN bed b ON b.bed_type_id = t.bed_type_id AND b.status = 'FREE' "
        "GROUP BY t.bed_type_id, t.name ORDER BY t.bed_type_id")
    pick = next((r for r in rows if r["bed_type_id"] == 2 and r["free"] == 1), None) \
        or next((r for r in rows if r["free"] == 1), None)
    return pick, rows


def race(mode=None, across_instances=False):
    mode = mode or state.get()["booking_mode"]
    pick, counts = race_setup()
    if not pick:
        return {"ok": False, "message": "The race needs a bed type with exactly one free bed in the city. "
                                        "Press Reset demo data, or cancel the hold that won the last race.",
                "free_counts": counts}
    hospital = next(h for h in meta.load()["hospitals"] if h["hospital_id"] == pick["hospital_id"])
    area = hospital["zone"] if hospital["zone"] in BY_NAME else "MG Road"
    lat, lon = BY_NAME[area]["lat"], BY_NAME[area]["lon"]
    think = 0.0 if mode == "unsafe" else 1.5
    start_at = time.time() + 0.6
    args = dict(bed_type_id=pick["bed_type_id"], lat=lat, lon=lon, severity=5, area=area,
                mode=mode, think=think)
    results = {}

    def side(key, user_id, name):
        _wait_until(start_at)
        results[key] = booking.book(user_id, name, 58 if key == "A" else 63, "M" if key == "A" else "F",
                                    label=f"Request {key} ({meta.user_name(user_id)}, {INSTANCE})", **args)

    threads = [threading.Thread(target=side, args=("A", 2, "Race Patient A"))]
    remote = None
    if across_instances:
        peers = [p for p in parse_instances(INTERNAL_INSTANCES) if p["name"] != INSTANCE]
        remote = peers[0] if peers else None
    if remote:
        def remote_side():
            payload = {"user_id": 3, "patient_name": "Race Patient B", "age": 63, "gender": "F",
                       "start_at": start_at, "label": f"Request B ({meta.user_name(3)}, {remote['name']})", **args}
            try:
                req = urllib.request.Request(remote["url"] + "/api/internal/book", data=json.dumps(payload).encode(),
                                             headers={"Content-Type": "application/json"}, method="POST")
                with urllib.request.urlopen(req, timeout=30) as resp:
                    results["B"] = json.loads(resp.read())
            except Exception as exc:
                results["B"] = {"outcome": "REJECTED", "error": f"Instance {remote['name']} unreachable: {exc}",
                                "label": "Request B", "trace": []}
        threads.append(threading.Thread(target=remote_side))
    else:
        threads.append(threading.Thread(target=side, args=("B", 3, "Race Patient B")))
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    live = db.query("SELECT COUNT(*) AS n FROM reservation WHERE bed_id = %s AND status = 'HELD'", (pick["bed_id"],))[0]["n"]
    return {
        "ok": True, "mode": mode, "bed_id": pick["bed_id"], "bed_type": pick["name"],
        "hospital": meta.hospital_name(pick["hospital_id"]), "area": area,
        "across_instances": bool(remote), "instances": [INSTANCE, remote["name"] if remote else INSTANCE],
        "A": results.get("A"), "B": results.get("B"),
        "live_holds_on_bed": live,
        "verdict": "Exactly one live hold on the bed" if live == 1 else f"{live} live holds on the bed",
    }


def internal_book(p):
    _wait_until(float(p.get("start_at") or 0))
    return booking.book(p["user_id"], p["patient_name"], p.get("age"), p.get("gender"), p["bed_type_id"],
                        p["lat"], p["lon"], p.get("severity", 5), area=p.get("area"), label=p.get("label"),
                        think=p.get("think", 0.0), mode=p.get("mode"))


# ---------------------------------------------------------------------------
# 2. Crossing transfers (deadlock)
# ---------------------------------------------------------------------------
def crossing(ordered=None):
    ordered = state.get()["lock_ordering"] if ordered is None else ordered
    pair = db.query(
        "SELECT a.bed_id AS bed_a, a.patient_id AS pat_a, v.bed_id AS bed_b, v.patient_id AS pat_b, a.hospital_id "
        "FROM bed a JOIN bed v ON v.hospital_id = a.hospital_id AND v.bed_type_id = 2 AND v.status = 'OCCUPIED' "
        "WHERE a.bed_type_id = 1 AND a.status = 'OCCUPIED' ORDER BY a.hospital_id, a.bed_id, v.bed_id LIMIT 1")
    if not pair:
        return {"ok": False, "message": "Needs an occupied ICU bed and an occupied ventilator bed in one hospital. Reset demo data."}
    p = pair[0]
    names = {r["patient_id"]: r["name"] for r in db.query(
        "SELECT patient_id, name FROM patient WHERE patient_id IN (%s, %s)", (p["pat_a"], p["pat_b"]))}
    start_at = time.time() + 0.5
    results = {}
    edges_seen = []
    done = threading.Event()

    def run(key, patient, src, dst, pause):
        _wait_until(start_at)
        results[key] = transfer.transfer(
            patient, src, dst, ordered=ordered, pause=pause,
            label=f"Transfer {key}: {names.get(patient, patient)} {src} -> {dst}", user_id=3 + p["hospital_id"])

    def watch():
        while not done.is_set():
            try:
                snap = xray.snapshot()
                for e in snap["waits"]:
                    if e not in edges_seen:
                        edges_seen.append(e)
            except Exception:
                pass
            time.sleep(0.15)

    w = threading.Thread(target=watch, daemon=True)
    w.start()
    ta = threading.Thread(target=run, args=("A", p["pat_a"], p["bed_a"], p["bed_b"], 2.0))
    tb = threading.Thread(target=run, args=("B", p["pat_b"], p["bed_b"], p["bed_a"], 3.0))
    ta.start(); tb.start(); ta.join(); tb.join()
    done.set()
    deadlock = xray.latest_deadlock(force=True)
    after = db.query("SELECT bed_id, status, patient_id FROM bed WHERE bed_id IN (%s, %s) ORDER BY bed_id",
                     (p["bed_a"], p["bed_b"]))
    outcomes = sorted([results["A"]["outcome"], results["B"]["outcome"]])
    return {
        "ok": True, "ordered": ordered, "hospital": meta.hospital_name(p["hospital_id"]),
        "story": {"A": f"{names.get(p['pat_a'])} (ICU bed {p['bed_a']}) worsened and needs ventilator bed {p['bed_b']}",
                  "B": f"{names.get(p['pat_b'])} (ventilator bed {p['bed_b']}) improved and steps down to ICU bed {p['bed_a']}"},
        "A": results["A"], "B": results["B"], "edges_seen": edges_seen,
        "deadlock": deadlock if "ROLLED_BACK" in outcomes else None,
        "beds_after": [{**b, "patient": names.get(b["patient_id"])} for b in after],
        "verdict": ("Deadlock: InnoDB rolled one transfer back (1213), the other completed"
                    if "ROLLED_BACK" in outcomes else "Both transfers completed, no deadlock"),
    }


# ---------------------------------------------------------------------------
# 3. Kill the database in the middle of a transfer
# ---------------------------------------------------------------------------
RECOVERY_WORDS = ["not shutdown normally", "crash recovery", "redo log", "rollback", "rolling back",
                  "rolled back", "undo", "xa ", "recover", "ready for connections"]


def crash():
    if not _demo_lock.acquire(blocking=False):
        return {"ok": False, "message": "A crash demo is already running"}
    try:
        return _crash()
    finally:
        _demo_lock.release()


def _crash():
    D = "crash"
    if not containers.available():
        return {"ok": False, "message": "Docker is not reachable from the app, so it cannot kill MySQL. Run the app with docker compose."}
    pick = db.query(
        "SELECT o.bed_id AS from_bed, o.patient_id, f.bed_id AS to_bed, o.hospital_id "
        "FROM bed o JOIN bed f ON f.hospital_id = o.hospital_id AND f.bed_type_id = o.bed_type_id AND f.status = 'FREE' "
        "WHERE o.status = 'OCCUPIED' ORDER BY o.hospital_id DESC, o.bed_id LIMIT 1")
    if not pick:
        return {"ok": False, "message": "Needs an occupied bed and a free bed of the same type in one hospital. Reset demo data."}
    p = pick[0]
    beds_sql = ("SELECT bed_id, status, patient_id FROM bed WHERE bed_id IN (%s, %s) ORDER BY bed_id")
    before = db.query(beds_sql, (p["from_bed"], p["to_bed"]))
    holds_before = db.query("SELECT COUNT(*) AS n FROM reservation WHERE status = 'HELD'")[0]["n"]
    progress(D, 1, f"Committed state: bed {p['from_bed']} OCCUPIED by patient {p['patient_id']}, bed {p['to_bed']} FREE")

    reached = threading.Event()
    box = {}

    def hook(s):
        box["conn"] = s.conn_id
        box["tx"] = s.tx
        reached.set()
        s.run("SELECT SLEEP(60)")           # paused inside the transaction; MySQL dies here

    def run():
        box["result"] = transfer.transfer(p["patient_id"], p["from_bed"], p["to_bed"], ordered=True,
                                          label=f"Transfer (crash demo): bed {p['from_bed']} -> {p['to_bed']}",
                                          user_id=3 + p["hospital_id"], crash_hook=hook)

    t = threading.Thread(target=run)
    t.start()
    if not reached.wait(10):
        return {"ok": False, "message": "Transfer did not reach the pause point"}
    time.sleep(0.8)
    progress(D, 2, f"Inside transaction {box['tx']}: transfer row inserted, bed {p['from_bed']} already set FREE, "
                   f"bed {p['to_bed']} not yet taken. Nothing committed.")

    outside = db.query(beds_sql, (p["from_bed"], p["to_bed"]))
    trx = [x for x in xray.snapshot()["transactions"] if x["thread_id"] == box["conn"]]
    progress(D, 3, "Other sessions still see the old committed values (isolation): the half-done move is invisible",
             "ok", outside=outside)

    killed_at = time.time()
    progress(D, 4, "Sending SIGKILL to the MySQL container (no shutdown, no flush)")
    containers.kill(MYSQL_CONTAINER)
    t.join(15)
    progress(D, 4, "MySQL is down. The paused transaction's connection is gone.", "ok")
    time.sleep(1.5)

    progress(D, 5, "Starting MySQL again: InnoDB runs crash recovery (redo, then undo of uncommitted work)")
    containers.start(MYSQL_CONTAINER)
    up = containers.wait_until(db.alive, timeout=150, every=1.0,
                               on_tick=lambda n: n % 3 == 0 and progress(D, 5, f"Waiting for MySQL to accept connections ({n} s)"))
    if not up:
        return {"ok": False, "message": "MySQL did not come back within 150 s", "before": before}
    recovered_in = round(time.time() - killed_at, 1)
    progress(D, 5, f"MySQL is back after {recovered_in} s", "ok")

    after = db.query(beds_sql, (p["from_bed"], p["to_bed"]))
    holds_after = db.query("SELECT COUNT(*) AS n FROM reservation WHERE status = 'HELD'")[0]["n"]
    tid = (box.get("result") or {}).get("transfer_id")
    transfer_row = db.query("SELECT transfer_id, status, note FROM transfer WHERE transfer_id = %s", (tid,)) if tid else []
    log_lines = []
    try:
        log_lines = containers.logs_since(MYSQL_CONTAINER, killed_at - 1, RECOVERY_WORDS)[-14:]
    except Exception:
        pass

    # The transfer row was inserted inside the killed transaction, so recovery removed it
    # too. Record the failed attempt as history in a fresh, committed row.
    with db.Session("Recovery: record the interrupted transfer", 11) as s:
        transfer._record_failure(s, p["patient_id"], p["from_bed"], p["to_bed"],
                                 "Aborted by database crash; InnoDB undid the uncommitted move")
    try:
        rc.rebuild()
    except Exception:
        pass

    consistent = [(b["bed_id"], b["status"], b["patient_id"]) for b in after] == \
                 [(b["bed_id"], b["status"], b["patient_id"]) for b in before]
    progress(D, 6, "No bed is half-moved: the uncommitted transaction was rolled back" if consistent
             else "State differs from before, inspect the tables", "ok" if consistent else "err")
    return {
        "ok": True, "from_bed": p["from_bed"], "to_bed": p["to_bed"], "patient_id": p["patient_id"],
        "before": before, "inside": [{"bed_id": p["from_bed"], "status": "FREE", "patient_id": None},
                                     {"bed_id": p["to_bed"], "status": "FREE", "patient_id": None}],
        "outside": outside, "after": after, "trx": trx, "transfer": transfer_row,
        "holds_before": holds_before, "holds_after": holds_after, "recovered_in_s": recovered_in,
        "mysql_log": log_lines, "consistent": consistent,
    }


# ---------------------------------------------------------------------------
# 4. Bed blocking and the audit
# ---------------------------------------------------------------------------
def spam(count=8):
    areas = ["Jayanagar", "Koramangala", "Indiranagar", "Whitefield", "Hebbal", "Malleshwaram",
             "Electronic City", "HSR Layout"]
    out = []
    for i in range(count):
        a = BY_NAME[areas[i % len(areas)]]
        res = booking.book(12, f"Fake Patient {i + 1}", None, None, 1 if i % 2 == 0 else 3, a["lat"], a["lon"], 5,
                           raw_text="urgent bed needed", area=a["name"],
                           label=f"Spam hold {i + 1}/{count} (Suspicious Agent)", mode="safe")
        out.append({k: res.get(k) for k in ("outcome", "bed_id", "hospital", "code", "error", "meaning", "reservation_id")})
    return {"ok": True, "attempts": out,
            "held": sum(1 for r in out if r["outcome"] == "HELD"),
            "refused": sum(1 for r in out if r["outcome"] == "REJECTED")}


def audit():
    with db.Session("Audit query (Control Room)", 11) as s:
        rows = s.run(
            "SELECT user_id, name, role, total_holds, admitted, active, not_converted, failure_pct,\n"
            "       (total_holds >= 5 AND failure_pct >= 50) AS flagged\n"
            "  FROM v_hold_conversion\n"
            " ORDER BY failure_pct DESC, total_holds DESC")
        flagged = [r["name"] for r in rows if r["flagged"]]
        s.run("INSERT INTO audit_log (user_id, action, entity_name, entity_id, details)\n"
              "VALUES (%s, 'AUDIT_RUN', 'user_account', NULL, JSON_OBJECT('flagged', %s))",
              (11, json.dumps(flagged)))
    for r in rows:
        r["failure_pct"] = float(r["failure_pct"] or 0)
        r["flagged"] = bool(r["flagged"])
    return {"ok": True, "rows": rows, "flagged": flagged,
            "sql": "SELECT * FROM v_hold_conversion WHERE total_holds >= 5 AND failure_pct >= 50"}


# ---------------------------------------------------------------------------
# 5. Clock
# ---------------------------------------------------------------------------
def fast_forward(minutes=30):
    with db.Session(f"Fast-forward clock {minutes} min", 11) as s:
        s.run("UPDATE sim_clock SET offset_minutes = offset_minutes + %s WHERE id = 1", (minutes,))
        row = s.one("SELECT sim_now() AS sim_now, offset_minutes,\n"
                    "       (SELECT COUNT(*) FROM reservation WHERE status = 'HELD' AND hold_expires_at < sim_now()) AS due\n"
                    "  FROM sim_clock WHERE id = 1")
    rc.publish({"kind": "clock", "offset_minutes": row["offset_minutes"], "due": row["due"]})
    return {"ok": True, **row}


def clock():
    row = db.query("SELECT sim_now() AS sim_now, NOW() AS real_now, offset_minutes FROM sim_clock WHERE id = 1")
    return row[0] if row else {}


# ---------------------------------------------------------------------------
# 6. Reset
# ---------------------------------------------------------------------------
def reset():
    text = (DB_DIR / "seed.sql").read_text(encoding="utf-8")
    statements = []
    for chunk in text.split(";\n"):
        body = "\n".join(ln for ln in chunk.splitlines() if not ln.strip().startswith("--")).strip()
        if body:
            statements.append(body)
    conn = db.raw_connect()
    try:
        with conn.cursor() as c:
            for st in statements:
                c.execute(st)
    finally:
        conn.close()
    db.log_system(f"seed.sql re-run: {len(statements)} statements (TRUNCATE + INSERT demo data)", label="Reset demo data")
    meta.load(force=True)
    try:
        rc.rebuild()
    except Exception:
        pass
    from . import background
    background.watcher_reset()
    rc.publish({"kind": "reset"})
    return {"ok": True, "statements": len(statements)}


# ---------------------------------------------------------------------------
# 7. Redis outage
# ---------------------------------------------------------------------------
def redis_power(action):
    if not containers.available():
        return {"ok": False, "message": "Docker is not reachable from the app."}
    if action == "stop":
        containers.stop(REDIS_CONTAINER)
        db.log_system("docker stop icu_redis: Redis is down, search falls back to MySQL", label="Redis outage")
        return {"ok": True, "redis": False}
    containers.start(REDIS_CONTAINER)
    up = containers.wait_until(rc.alive, timeout=30, every=0.5)
    if up:
        rc.rebuild()
    return {"ok": up, "redis": up}


# ---------------------------------------------------------------------------
# 8. Replication
# ---------------------------------------------------------------------------
def replication(action):
    try:
        with db.Session("Replica control", replica=True) as s:
            if action == "pause":
                s.run("STOP REPLICA SQL_THREAD")
            elif action == "resume":
                s.run("START REPLICA SQL_THREAD")
    except pymysql.MySQLError as exc:
        return {"ok": False, "message": db.err_text(exc)}
    return {"ok": True, **compare()}


def compare():
    sql_res = ("SELECT reservation_id, bed_id, status FROM reservation ORDER BY reservation_id DESC LIMIT 6")
    sql_cnt = ("SELECT SUM(status = 'FREE') AS free, SUM(status = 'HELD') AS held, SUM(status = 'OCCUPIED') AS occupied FROM bed")
    out = {"primary": {}, "replica": {}}
    for name, replica in (("primary", False), ("replica", True)):
        try:
            out[name] = {"reservations": db.query(sql_res, replica=replica),
                         "beds": db.query(sql_cnt, replica=replica)[0],
                         "gtid": db.query("SELECT @@GLOBAL.gtid_executed AS g", replica=replica)[0]["g"]}
        except Exception as exc:
            out[name] = {"error": str(exc)}
    return out
