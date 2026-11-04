"""Shared switches. Stored in a Redis hash so every app instance and every browser
tab sees the same mode; falls back to this process's memory if Redis is down."""
import threading

from .hub import hub

DEFAULTS = {
    "booking_mode": "safe",     # safe = FOR UPDATE SKIP LOCKED, unsafe = plain SELECT + SLEEP(2)
    "lock_ordering": True,      # transfers lock beds in ascending bed_id order
}
_lock = threading.Lock()
_local = dict(DEFAULTS)
KEY = "settings"


def _decode(raw):
    out = dict(DEFAULTS)
    if raw.get("booking_mode") in ("safe", "unsafe"):
        out["booking_mode"] = raw["booking_mode"]
    if "lock_ordering" in raw:
        out["lock_ordering"] = raw["lock_ordering"] in ("1", "true", "True")
    return out


def get():
    try:
        from .redis_client import r
        raw = r.hgetall(KEY)
        if raw:
            snap = _decode(raw)
            with _lock:
                _local.update(snap)
            return snap
    except Exception:
        pass
    with _lock:
        return dict(_local)


def update(**changes):
    with _lock:
        for k, v in changes.items():
            if k in DEFAULTS and v is not None:
                _local[k] = v
        snap = dict(_local)
    try:
        from .redis_client import r
        r.hset(KEY, mapping={"booking_mode": snap["booking_mode"],
                             "lock_ordering": "1" if snap["lock_ordering"] else "0"})
    except Exception:
        pass
    hub.emit({"type": "settings", "settings": snap})
    return snap
