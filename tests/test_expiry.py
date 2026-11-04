"""Fast-forward 30 min: the MySQL event expires the hold, the trigger frees the bed,
and the running app instances bring the Redis counter back in line with MySQL."""
from app import booking, db, demo
from app import redis_client as rc
from tests.conftest import wait_for


def test_hold_expires_and_counters_match(fresh):
    res = booking.book(1, "Expiry Test", 50, "F", 3, 13.0358, 77.5970, 3, label="test expiry")
    assert res["outcome"] == "HELD"
    rid, bed = res["reservation_id"], res["bed_id"]
    h, t = res["hospital_id"], 3

    demo.fast_forward(31)

    def expired():
        r = db.query("SELECT status FROM reservation WHERE reservation_id = %s", (rid,))[0]["status"]
        b = db.query("SELECT status FROM bed WHERE bed_id = %s", (bed,))[0]["status"]
        return r == "EXPIRED" and b == "FREE"

    assert wait_for(expired, timeout=15), "expire_holds event did not run"

    def counters_match():
        truth = db.query("SELECT COUNT(*) AS n FROM bed WHERE hospital_id = %s AND bed_type_id = %s AND status = 'FREE'",
                         (h, t))[0]["n"]
        return int(rc.r.get(rc.counter_key(h, t)) or -1) == truth

    assert wait_for(counters_match, timeout=10), "Redis counter does not match MySQL"

    log = db.query("SELECT user_id FROM audit_log WHERE action = 'RESERVATION_EXPIRED' AND entity_id = %s", (rid,))
    assert log and log[0]["user_id"] is None      # done by the scheduler, not by a user


def test_admit_refused_after_expiry_time(fresh):
    res = booking.book(1, "Late Admit", 50, "M", 1, 12.9352, 77.6245, 4, label="test late admit")
    demo.fast_forward(31)
    out = booking.admit(res["reservation_id"], 1)
    assert out["ok"] is False
