"""Booking: find the nearest free bed of the right type and HOLD it for 30 minutes.

Safe mode (default), one transaction:

    START TRANSACTION
      INSERT patient, INSERT bed_request
      -- for each candidate hospital, nearest first (order comes from Redis GEO):
      SELECT bed_id FROM bed
       WHERE bed_type_id = ? AND status = 'FREE' AND hospital_id = ?
       ORDER BY bed_id LIMIT 1
         FOR UPDATE SKIP LOCKED
      INSERT reservation (status 'HELD', hold_expires_at = sim_now() + 30 min)
      UPDATE bed SET status = 'HELD'
    COMMIT
    -- only now: refresh the Redis counter from MySQL, publish an event

Why one SELECT per hospital instead of one big ORDER BY FIELD(...) query?
A locking read locks every row it scans. With ORDER BY FIELD the server must read
and lock ALL free candidate beds before sorting, so a second request would skip
all of them. Per hospital, idx_bed_search (bed_type_id, status, hospital_id)
already returns rows in bed_id order, LIMIT 1 stops at the first row, and only
that one row gets locked.

Unsafe mode (the "No lock" switch): the same SELECT without FOR UPDATE, then
SLEEP(2) to widen the race window. Two requests both see the bed as FREE and both
INSERT a HELD reservation. The UNIQUE index one_active_booking_per_bed lets only
the first one in; the second gets MySQL error 1062.
"""
from decimal import Decimal

import pymysql

from . import db, meta, state
from . import redis_client as rc
from .config import HOLD_MINUTES, SEARCH_RADIUS_KM


def dec(v):
    """Coordinates as DECIMAL literals in SQL (12.9299, not 12.9299e0)."""
    return Decimal(f"{float(v):.6f}")


def find_candidates(s, lat, lon, bed_type_id):
    """Nearest-first hospitals. Redis GEO + counters, or a MySQL distance query if Redis is down."""
    try:
        near = rc.nearest(lat, lon, SEARCH_RADIUS_KM, session=s)
        counts = rc.free_counts_for([h for h, _ in near], bed_type_id, session=s)
        with_free = [(h, km) for h, km in near if (counts.get(h) or 0) > 0]
        return with_free, near, "Redis GEOSEARCH + free counters"
    except Exception:
        rows = s.run(
            "SELECT hospital_id, ROUND(ST_Distance_Sphere(POINT(longitude, latitude), POINT(%s, %s)) / 1000, 2) AS km "
            "FROM hospital ORDER BY km", (dec(lon), dec(lat)))
        near = [(r["hospital_id"], float(r["km"])) for r in rows if float(r["km"]) <= SEARCH_RADIUS_KM]
        return near, near, "MySQL ST_Distance_Sphere (Redis unavailable)"


def pick_bed(s, candidates, bed_type_id, mode, think=0.0, nearest=None):
    bed = _try_hospitals(s, candidates, bed_type_id, mode, think)
    if bed or not nearest:
        return bed
    # Redis counters are a cache and can lag a commit by a moment. Before giving up, ask
    # MySQL (plain consistent read, no locks) whether any skipped hospital has a free bed.
    tried = {h for h, _ in candidates}
    rest = [(h, km) for h, km in nearest if h not in tried]
    if not rest:
        return None
    marks = ", ".join(["%s"] * len(rest))
    rows = s.run(f"SELECT DISTINCT hospital_id FROM bed WHERE bed_type_id = %s AND status = 'FREE' AND hospital_id IN ({marks})",
                 [bed_type_id] + [h for h, _ in rest])
    has_free = {r["hospital_id"] for r in rows}
    return _try_hospitals(s, [(h, km) for h, km in rest if h in has_free], bed_type_id, mode, think)


def _try_hospitals(s, candidates, bed_type_id, mode, think):
    lock = "\n   FOR UPDATE SKIP LOCKED" if mode == "safe" else ""
    for hid, km in candidates:
        row = s.one(
            "SELECT bed_id, hospital_id, ward FROM bed\n"
            " WHERE bed_type_id = %s AND status = 'FREE' AND hospital_id = %s\n"
            " ORDER BY bed_id LIMIT 1" + lock,
            (bed_type_id, hid))
        if row:
            row["km"] = km
            if mode == "unsafe":
                s.run("SELECT SLEEP(2)")
            elif think:
                s.run(f"SELECT SLEEP({float(think):g})")
            return row
    return None


def book(user_id, patient_name, age, gender, bed_type_id, lat, lon, severity,
         raw_text=None, area=None, label=None, think=0.0, mode=None, phone=None):
    mode = mode or state.get()["booking_mode"]
    label = label or f"Booking by {meta.user_name(user_id)}"
    result = {"mode": mode, "label": label, "user_id": user_id, "area": area,
              "bed_type_id": bed_type_id, "outcome": None}

    with db.Session(label, user_id) as s:
        result["tx"], result["conn"] = s.tx, s.conn_id
        candidates, near, source = find_candidates(s, lat, lon, bed_type_id)
        result["search"] = {
            "source": source,
            "nearest": [{"hospital_id": h, "name": meta.hospital_name(h), "km": km} for h, km in near],
            "with_free": [h for h, _ in candidates],
        }

        for attempt in range(2):          # retry once if chosen as a deadlock victim
            try:
                s.begin()
                s.run("INSERT INTO patient (name, age, gender, contact_phone) VALUES (%s, %s, %s, %s)",
                      (patient_name, age, gender, phone))
                patient_id = s.lastrowid
                s.run("INSERT INTO bed_request (patient_id, raised_by, bed_type_id, severity, pickup_lat, pickup_lon, raw_text)\n"
                      "VALUES (%s, %s, %s, %s, %s, %s, %s)",
                      (patient_id, user_id, bed_type_id, severity, dec(lat), dec(lon), raw_text))
                request_id = s.lastrowid
                result.update(patient_id=patient_id, request_id=request_id)

                bed = pick_bed(s, candidates, bed_type_id, mode, think,
                               nearest=near if candidates is not near else None)
                if bed is None:
                    s.commit()
                    result.update(outcome="NO_BED",
                                  message="No free bed of this type nearby. The request stays OPEN in bed_request.")
                    break

                s.run("INSERT INTO reservation (request_id, bed_id, status, hold_expires_at)\n"
                      "VALUES (%s, %s, 'HELD', sim_now() + INTERVAL %s MINUTE)",
                      (request_id, bed["bed_id"], HOLD_MINUTES))
                reservation_id = s.lastrowid
                s.run("UPDATE bed SET status = 'HELD' WHERE bed_id = %s", (bed["bed_id"],))
                s.commit()
                result.update(outcome="HELD", reservation_id=reservation_id, bed_id=bed["bed_id"],
                              hospital_id=bed["hospital_id"], hospital=meta.hospital_name(bed["hospital_id"]),
                              ward=bed["ward"], km=bed["km"])
                break
            except pymysql.MySQLError as exc:
                code = db.err_code(exc)
                if s.in_tx:
                    try:
                        s.rollback()
                    except Exception:
                        pass
                if code == 1213 and attempt == 0:
                    continue
                result.update(outcome="REJECTED", code=code, error=db.err_text(exc),
                              meaning=db.ERROR_MEANING.get(code, "MySQL refused the transaction"))
                break

        if result["outcome"] == "HELD":
            rc.refresh_counter(result["hospital_id"], bed_type_id, session=s)
        result["trace"] = s.trace

    if result["outcome"] == "HELD":
        info = db.query("SELECT hold_expires_at, TIMESTAMPDIFF(SECOND, sim_now(), hold_expires_at) AS seconds_left "
                        "FROM reservation WHERE reservation_id = %s", (result["reservation_id"],))[0]
        result.update(hold_expires_at=info["hold_expires_at"], seconds_left=info["seconds_left"])

    rc.publish({"kind": "booking", "outcome": result["outcome"], "user": meta.user_name(user_id),
                "bed_id": result.get("bed_id"), "reservation_id": result.get("reservation_id"),
                "code": result.get("code")})
    return result


# ---------------------------------------------------------------------------
# Hold lifecycle
# ---------------------------------------------------------------------------
def admit(reservation_id, user_id):
    """HELD -> ADMITTED. Locks the reservation row so it cannot race the expiry event."""
    with db.Session(f"Admit reservation {reservation_id}", user_id) as s:
        try:
            s.begin()
            row = s.one(
                "SELECT r.reservation_id, r.bed_id, r.status, r.hold_expires_at >= sim_now() AS in_time,\n"
                "       q.request_id, q.patient_id, b.hospital_id, b.bed_type_id\n"
                "  FROM reservation r\n"
                "  JOIN bed_request q ON q.request_id = r.request_id\n"
                "  JOIN bed b ON b.bed_id = r.bed_id\n"
                " WHERE r.reservation_id = %s\n"
                "   FOR UPDATE", (reservation_id,))
            if not row:
                s.rollback()
                return {"ok": False, "message": "No such reservation"}
            if row["status"] != "HELD":
                s.rollback()
                return {"ok": False, "message": f"Cannot admit: reservation is {row['status']}"}
            if not row["in_time"]:
                s.rollback()
                return {"ok": False, "message": "Cannot admit: the 30 minute hold has run out (the expiry event will free the bed)"}
            s.run("UPDATE reservation SET status = 'ADMITTED', admitted_at = sim_now() WHERE reservation_id = %s",
                  (reservation_id,))
            s.run("UPDATE bed SET status = 'OCCUPIED', patient_id = %s WHERE bed_id = %s",
                  (row["patient_id"], row["bed_id"]))
            s.run("UPDATE bed_request SET status = 'FULFILLED' WHERE request_id = %s", (row["request_id"],))
            s.commit()
        except pymysql.MySQLError as exc:
            return {"ok": False, "code": db.err_code(exc), "message": db.err_text(exc)}
    rc.publish({"kind": "admit", "reservation_id": reservation_id, "bed_id": row["bed_id"]})
    return {"ok": True, "bed_id": row["bed_id"], "message": f"Patient admitted to bed {row['bed_id']}"}


def cancel(reservation_id, user_id):
    """HELD -> CANCELLED. The AFTER UPDATE trigger gives the bed back."""
    with db.Session(f"Cancel reservation {reservation_id}", user_id) as s:
        try:
            s.begin()
            row = s.one(
                "SELECT r.status, r.bed_id, r.request_id, b.hospital_id, b.bed_type_id\n"
                "  FROM reservation r JOIN bed b ON b.bed_id = r.bed_id\n"
                " WHERE r.reservation_id = %s FOR UPDATE", (reservation_id,))
            if not row or row["status"] != "HELD":
                s.rollback()
                return {"ok": False, "message": "Only a live (HELD) reservation can be cancelled"}
            s.run("UPDATE reservation SET status = 'CANCELLED' WHERE reservation_id = %s", (reservation_id,))
            s.run("UPDATE bed_request SET status = 'CANCELLED' WHERE request_id = %s", (row["request_id"],))
            s.commit()
            rc.refresh_counter(row["hospital_id"], row["bed_type_id"], session=s)
        except pymysql.MySQLError as exc:
            return {"ok": False, "code": db.err_code(exc), "message": db.err_text(exc)}
    rc.publish({"kind": "cancel", "reservation_id": reservation_id, "bed_id": row["bed_id"]})
    return {"ok": True, "bed_id": row["bed_id"], "message": f"Hold cancelled, bed {row['bed_id']} is FREE again"}


def set_bed_status(bed_id, action, user_id):
    """Ward actions from the bed board: discharge, maintenance on/off."""
    rules = {
        "discharge": ("OCCUPIED", "FREE"),
        "maintenance": ("FREE", "MAINTENANCE"),
        "restore": ("MAINTENANCE", "FREE"),
    }
    if action not in rules:
        return {"ok": False, "message": "Unknown action"}
    need, new = rules[action]
    with db.Session(f"Bed {bed_id}: {action}", user_id) as s:
        try:
            s.begin()
            row = s.one("SELECT status, hospital_id, bed_type_id FROM bed WHERE bed_id = %s FOR UPDATE", (bed_id,))
            if not row or row["status"] != need:
                s.rollback()
                return {"ok": False, "message": f"Bed must be {need} for this action (it is {row['status'] if row else 'missing'})"}
            s.run("UPDATE bed SET status = %s, patient_id = NULL WHERE bed_id = %s", (new, bed_id))
            s.commit()
            rc.refresh_counter(row["hospital_id"], row["bed_type_id"], session=s)
        except pymysql.MySQLError as exc:
            return {"ok": False, "code": db.err_code(exc), "message": db.err_text(exc)}
    rc.publish({"kind": "bed", "action": action, "bed_id": bed_id})
    return {"ok": True, "message": f"Bed {bed_id} is now {new}"}


def holds_for(user_id):
    return db.query(
        "SELECT r.reservation_id, r.bed_id, r.status, r.hold_expires_at, r.created_at, r.admitted_at,\n"
        "       TIMESTAMPDIFF(SECOND, sim_now(), r.hold_expires_at) AS seconds_left,\n"
        "       b.ward, b.bed_type_id, h.name AS hospital, p.name AS patient\n"
        "  FROM reservation r\n"
        "  JOIN bed_request q ON q.request_id = r.request_id\n"
        "  JOIN bed b ON b.bed_id = r.bed_id\n"
        "  JOIN hospital h ON h.hospital_id = b.hospital_id\n"
        "  JOIN patient p ON p.patient_id = q.patient_id\n"
        " WHERE q.raised_by = %s AND (r.status = 'HELD' OR r.created_at >= NOW() - INTERVAL 2 HOUR)\n"
        " ORDER BY r.reservation_id DESC LIMIT 12", (user_id,))
