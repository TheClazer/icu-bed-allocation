"""Crossing transfers: request-order locking deadlocks (1213), ordered locking never does."""
from app import db, demo


def beds_consistent(beds):
    patients = [b["patient_id"] for b in beds]
    return all(b["status"] == "OCCUPIED" for b in beds) and len(set(patients)) == 2 and None not in patients


def test_request_order_deadlocks_and_one_rolls_back(fresh):
    res = demo.crossing(ordered=False)
    outcomes = sorted([res["A"]["outcome"], res["B"]["outcome"]])
    assert outcomes == ["DONE", "ROLLED_BACK"]
    victim = res["A"] if res["A"]["outcome"] == "ROLLED_BACK" else res["B"]
    assert victim["code"] == 1213
    assert res["deadlock"] is not None and res["deadlock"]["victim"] in (1, 2)
    assert beds_consistent(res["beds_after"])
    rows = db.query("SELECT status FROM transfer ORDER BY transfer_id")
    assert [r["status"] for r in rows].count("ROLLED_BACK") == 1


def test_ordered_locking_both_complete(fresh):
    for _ in range(2):
        res = demo.crossing(ordered=True)
        assert res["A"]["outcome"] == "DONE" and res["B"]["outcome"] == "DONE"
        assert res["deadlock"] is None
        assert beds_consistent(res["beds_after"])
