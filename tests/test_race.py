"""Race for the last bed, 50 times: exactly one live hold, every time (safe mode)."""
import threading

from app import booking, db

LAST_VENT_BED = 104      # the only free ventilator bed after seed.sql
JAYANAGAR = (12.9299, 77.5826)


def race_once(mode, think):
    results = {}
    barrier = threading.Barrier(2)

    def side(key, user):
        barrier.wait()
        results[key] = booking.book(user, f"Race {key}", 60, "M", 2, *JAYANAGAR, 5,
                                    label=f"test race {key}", mode=mode, think=think)

    threads = [threading.Thread(target=side, args=("A", 2)), threading.Thread(target=side, args=("B", 3))]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return results


def live_holds(bed_id):
    return db.query("SELECT COUNT(*) AS n FROM reservation WHERE bed_id = %s AND status = 'HELD'", (bed_id,))[0]["n"]


def free_the_bed():
    db.query("UPDATE reservation SET status = 'CANCELLED' WHERE status = 'HELD' AND bed_id = %s", (LAST_VENT_BED,))


def test_race_safe_mode_50_times(fresh):
    for i in range(50):
        res = race_once("safe", think=0.05)
        outcomes = sorted(r["outcome"] for r in res.values())
        assert outcomes == ["HELD", "NO_BED"], f"run {i}: {outcomes}"
        assert live_holds(LAST_VENT_BED) == 1, f"run {i}: more than one live hold"
        free_the_bed()
