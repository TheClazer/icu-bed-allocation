"""Small cached lookups (hospital names, users, bed types) for labels in the UI."""
import threading

from . import db
from .areas import AREAS

_lock = threading.Lock()
_cache = {}


def load(force=False):
    with _lock:
        if _cache and not force:
            return _cache
        hospitals = db.query("SELECT hospital_id, name, zone, latitude, longitude FROM hospital ORDER BY hospital_id")
        users = db.query("SELECT user_id, name, role, hospital_id FROM user_account ORDER BY user_id")
        types = db.query("SELECT bed_type_id, name, has_ventilator FROM bed_type ORDER BY bed_type_id")
        _cache.clear()
        _cache.update({
            "hospitals": [{**h, "latitude": float(h["latitude"]), "longitude": float(h["longitude"])} for h in hospitals],
            "users": users,
            "bed_types": [{**t, "has_ventilator": bool(t["has_ventilator"])} for t in types],
            "areas": [{"name": a["name"], "lat": a["lat"], "lon": a["lon"]} for a in AREAS],
        })
        return _cache


def hospital_name(hid):
    for h in load().get("hospitals", []):
        if h["hospital_id"] == hid:
            return h["name"]
    return f"Hospital {hid}"


def user_name(uid):
    for u in load().get("users", []):
        if u["user_id"] == uid:
            return u["name"]
    return f"User {uid}"


def type_name(tid):
    for t in load().get("bed_types", []):
        if t["bed_type_id"] == tid:
            return t["name"]
    return f"Type {tid}"
