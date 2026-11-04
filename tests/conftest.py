"""Tests run against the live stack: docker compose exec app python -m pytest -q tests
They reset the demo data first, so do not run them during a live demo."""
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import db, demo, meta  # noqa: E402


@pytest.fixture()
def fresh():
    demo.reset()
    meta.load(force=True)
    yield
    db.query("UPDATE sim_clock SET offset_minutes = 0 WHERE id = 1")


def wait_for(check, timeout=15.0, every=0.5):
    end = time.time() + timeout
    while time.time() < end:
        if check():
            return True
        time.sleep(every)
    return False
