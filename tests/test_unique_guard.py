"""No lock at all: the UNIQUE index on the generated column still allows only one live hold."""
from tests.test_race import LAST_VENT_BED, free_the_bed, live_holds, race_once


def test_unsafe_mode_second_insert_fails_with_1062(fresh):
    for i in range(3):
        res = race_once("unsafe", think=0)
        by_outcome = {r["outcome"]: r for r in res.values()}
        assert set(by_outcome) == {"HELD", "REJECTED"}, f"run {i}: {list(by_outcome)}"
        assert by_outcome["REJECTED"]["code"] == 1062
        assert "one_active_booking_per_bed" in by_outcome["REJECTED"]["error"]
        assert live_holds(LAST_VENT_BED) == 1
        free_the_bed()
