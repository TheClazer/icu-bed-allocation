"""FastAPI entry point: REST API, WebSocket stream and the built frontend."""
import asyncio
import json
from contextlib import asynccontextmanager
from typing import Optional

import pymysql
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.encoders import jsonable_encoder
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import background, booking, containers, db, demo, meta, metrics, nlp, state, transfer, xray
from . import redis_client as rc
from .areas import BY_NAME
from .config import INSTANCE, PUBLIC_INSTANCES, WEB_DIR, parse_instances
from .hub import hub


@asynccontextmanager
async def lifespan(app):
    hub.attach(asyncio.get_running_loop())
    pump = asyncio.create_task(hub.pump())
    background.start()
    try:
        meta.load()
    except Exception:
        pass
    yield
    pump.cancel()


app = FastAPI(title="City ICU Bed Allocation", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


def ok(data):
    return JSONResponse(jsonable_encoder(data))


def mysql_guard(fn, *a, **kw):
    try:
        return ok(fn(*a, **kw))
    except pymysql.MySQLError as exc:
        code = db.err_code(exc)
        status = 503 if code in db.CONNECTION_ERRORS else 400
        raise HTTPException(status, detail=f"MySQL {code}: {db.err_text(exc)}")


# ---------------------------------------------------------------------------
# basics
# ---------------------------------------------------------------------------
@app.get("/api/ping")
def ping():
    return {"ok": True, "instance": INSTANCE}


@app.get("/api/meta")
def get_meta():
    return mysql_guard(meta.load)


@app.get("/api/health")
def get_health():
    return {"instance": INSTANCE, **background.health, "docker": containers.available()}


@app.get("/api/instances")
def get_instances():
    return {"self": INSTANCE, "instances": parse_instances(PUBLIC_INSTANCES)}


class SettingsIn(BaseModel):
    booking_mode: Optional[str] = Field(None, pattern="^(safe|unsafe)$")
    lock_ordering: Optional[bool] = None


@app.get("/api/settings")
def get_settings():
    return state.get()


@app.post("/api/settings")
def set_settings(body: SettingsIn):
    return state.update(**body.model_dump())


class TextIn(BaseModel):
    text: str = Field(..., max_length=255)


@app.post("/api/nlp/parse")
def parse_text(body: TextIn):
    return nlp.parse(body.text)


# ---------------------------------------------------------------------------
# booking
# ---------------------------------------------------------------------------
class RequestIn(BaseModel):
    user_id: int
    patient_name: str = Field(..., min_length=1, max_length=60)
    age: Optional[int] = None
    gender: Optional[str] = None
    bed_type_id: int
    area: str
    severity: int
    raw_text: Optional[str] = Field(None, max_length=255)
    phone: Optional[str] = Field(None, max_length=15)


@app.post("/api/requests")
def create_request(body: RequestIn):
    area = BY_NAME.get(body.area)
    if not area:
        raise HTTPException(400, detail="Unknown area")
    return mysql_guard(booking.book, body.user_id, body.patient_name.strip(), body.age, body.gender or None,
                       body.bed_type_id, area["lat"], area["lon"], body.severity, raw_text=body.raw_text,
                       area=body.area, phone=body.phone)


@app.get("/api/holds")
def get_holds(user_id: int):
    return mysql_guard(booking.holds_for, user_id)


class UserIn(BaseModel):
    user_id: int


@app.post("/api/reservations/{rid}/admit")
def admit(rid: int, body: UserIn):
    return mysql_guard(booking.admit, rid, body.user_id)


@app.post("/api/reservations/{rid}/cancel")
def cancel(rid: int, body: UserIn):
    return mysql_guard(booking.cancel, rid, body.user_id)


@app.post("/api/beds/{bed_id}/{action}")
def bed_action(bed_id: int, action: str, body: UserIn):
    return mysql_guard(booking.set_bed_status, bed_id, action, body.user_id)


class TransferIn(BaseModel):
    user_id: int
    from_bed: int
    to_bed: int


@app.post("/api/transfers")
def make_transfer(body: TransferIn):
    occ = db.query("SELECT patient_id FROM bed WHERE bed_id = %s", (body.from_bed,))
    if not occ or occ[0]["patient_id"] is None:
        raise HTTPException(400, detail="The source bed has no patient")
    s = state.get()
    return mysql_guard(transfer.transfer, occ[0]["patient_id"], body.from_bed, body.to_bed,
                       ordered=s["lock_ordering"], user_id=body.user_id)


@app.get("/api/clock")
def get_clock():
    return mysql_guard(demo.clock)


class MinutesIn(BaseModel):
    minutes: int = Field(30, ge=1, le=600)


@app.post("/api/clock/forward")
def forward(body: MinutesIn):
    return mysql_guard(demo.fast_forward, body.minutes)


# ---------------------------------------------------------------------------
# dashboard
# ---------------------------------------------------------------------------
@app.get("/api/dashboard")
def dashboard():
    def build():
        m = meta.load()
        totals = db.query("SELECT hospital_id, bed_type_id, status, COUNT(*) AS n FROM bed GROUP BY hospital_id, bed_type_id, status")
        source = "redis"
        try:
            counts = rc.all_counts()
            if not counts:
                raise RuntimeError("empty")
        except Exception:
            source = "mysql"
            counts = {(t["hospital_id"], t["bed_type_id"]): 0 for t in totals}
            for t in totals:
                if t["status"] == "FREE":
                    counts[(t["hospital_id"], t["bed_type_id"])] = t["n"]
        hospitals = []
        for h in m["hospitals"]:
            per_type = {}
            for bt in m["bed_types"]:
                k = (h["hospital_id"], bt["bed_type_id"])
                st = {t["status"]: t["n"] for t in totals if (t["hospital_id"], t["bed_type_id"]) == k}
                per_type[bt["bed_type_id"]] = {"free": counts.get(k), "status": st, "total": sum(st.values())}
            hospitals.append({**h, "types": per_type})
        status_totals = {}
        for t in totals:
            status_totals[t["status"]] = status_totals.get(t["status"], 0) + t["n"]
        return {"source": source, "hospitals": hospitals, "status_totals": status_totals}
    return mysql_guard(build)


@app.get("/api/hospitals/{hid}/beds")
def hospital_beds(hid: int):
    return mysql_guard(db.query,
        "SELECT b.bed_id, b.bed_type_id, b.ward, b.status, b.patient_id, b.updated_at, p.name AS patient, p.age, p.gender,\n"
        "       r.reservation_id, r.hold_expires_at, TIMESTAMPDIFF(SECOND, sim_now(), r.hold_expires_at) AS seconds_left\n"
        "  FROM bed b LEFT JOIN patient p ON p.patient_id = b.patient_id\n"
        "  LEFT JOIN reservation r ON r.active_bed_id = b.bed_id\n"
        " WHERE b.hospital_id = %s ORDER BY b.bed_id", (hid,))


# ---------------------------------------------------------------------------
# live database console
# ---------------------------------------------------------------------------
TABLES = {
    "bed": ("bed_id", "ORDER BY bed_id", 200),
    "reservation": ("reservation_id", "ORDER BY reservation_id DESC", 120),
    "bed_request": ("request_id", "ORDER BY request_id DESC", 120),
    "patient": ("patient_id", "ORDER BY patient_id DESC", 120),
    "transfer": ("transfer_id", "ORDER BY transfer_id DESC", 120),
    "audit_log": ("log_id", "ORDER BY log_id DESC", 150),
    "hospital": ("hospital_id", "ORDER BY hospital_id", 50),
    "bed_type": ("bed_type_id", "ORDER BY bed_type_id", 10),
    "user_account": ("user_id", "ORDER BY user_id", 50),
    "sim_clock": ("id", "", 5),
    "replication_probe": ("id", "", 5),
    "v_hold_conversion": ("user_id", "ORDER BY failure_pct DESC", 50),
    "v_bed_board": ("bed_id", "ORDER BY bed_id", 200),
}


@app.get("/api/tables")
def list_tables():
    return {"tables": list(TABLES)}


@app.get("/api/tables/{name}")
def table_rows(name: str, source: str = "primary"):
    if name not in TABLES:
        raise HTTPException(404, detail="Unknown table")
    pk, order, limit = TABLES[name]

    def run():
        conn = db.raw_connect(replica=source == "replica", timeout=2)
        try:
            with conn.cursor() as c:
                c.execute(f"SELECT COUNT(*) AS n FROM `{name}`")
                total = c.fetchone()["n"]
                c.execute(f"SELECT * FROM `{name}` {order} LIMIT {limit}")
                cols = [d[0] for d in c.description]
                rows = c.fetchall()
        finally:
            conn.close()
        return {"name": name, "pk": pk, "columns": cols, "rows": rows, "total": total, "source": source}
    try:
        return ok(run())
    except pymysql.MySQLError as exc:
        raise HTTPException(503, detail=f"{source} unavailable: {db.err_text(exc)}")


@app.get("/api/xray")
def get_xray():
    return mysql_guard(xray.snapshot)


@app.get("/api/redis")
def redis_view():
    if not rc.alive():
        return {"up": False}
    counts = rc.all_counts()
    truth = {(r["hospital_id"], r["bed_type_id"]): r["free"] for r in db.query(
        "SELECT h.hospital_id, t.bed_type_id, COUNT(b.bed_id) AS free FROM hospital h CROSS JOIN bed_type t "
        "LEFT JOIN bed b ON b.hospital_id = h.hospital_id AND b.bed_type_id = t.bed_type_id AND b.status = 'FREE' "
        "GROUP BY h.hospital_id, t.bed_type_id")}
    rows = [{"key": rc.counter_key(h, t), "hospital_id": h, "bed_type_id": t, "redis": counts.get((h, t)),
             "mysql": v, "match": counts.get((h, t)) == v} for (h, t), v in sorted(truth.items())]
    return ok({"up": True, "geo": rc.geo_members(), "counters": rows,
               "events": list(rc.recent_events)[:40], "all_match": all(r["match"] for r in rows)})


@app.post("/api/redis/rebuild")
def redis_rebuild():
    return mysql_guard(rc.rebuild)


class QueryIn(BaseModel):
    sql: str = Field(..., max_length=4000)
    target: str = Field("primary", pattern="^(primary|replica)$")


@app.post("/api/query")
def run_query(body: QueryIn):
    """Runs as icu_readonly inside a READ ONLY transaction: MySQL itself refuses writes."""
    label = f"Query console ({body.target}, icu_readonly)"
    try:
        with db.Session(label, readonly=True, replica=body.target == "replica") as s:
            s.run("SET SESSION MAX_EXECUTION_TIME = 5000")
            s.run("START TRANSACTION READ ONLY")
            s.in_tx = True
            rows = s.run(body.sql.strip().rstrip(";"))
            s.rollback()
        cols = list(rows[0].keys()) if rows else []
        return ok({"ok": True, "columns": cols, "rows": rows[:500], "count": len(rows)})
    except pymysql.MySQLError as exc:
        code = db.err_code(exc)
        return ok({"ok": False, "code": code, "error": db.err_text(exc), "meaning": db.ERROR_MEANING.get(code)})


@app.get("/api/metrics")
def get_metrics():
    return ok(metrics.snapshot())


# ---------------------------------------------------------------------------
# demos
# ---------------------------------------------------------------------------
class RaceIn(BaseModel):
    mode: Optional[str] = Field(None, pattern="^(safe|unsafe)$")
    across_instances: bool = False


@app.post("/api/demo/race")
def demo_race(body: RaceIn):
    return mysql_guard(demo.race, body.mode, body.across_instances)


class CrossIn(BaseModel):
    ordered: Optional[bool] = None


@app.post("/api/demo/crossing")
def demo_crossing(body: CrossIn):
    return mysql_guard(demo.crossing, body.ordered)


@app.post("/api/demo/crash")
def demo_crash():
    return ok(demo.crash())


@app.post("/api/demo/spam")
def demo_spam():
    return mysql_guard(demo.spam)


@app.post("/api/demo/audit")
def demo_audit():
    return mysql_guard(demo.audit)


@app.post("/api/demo/reset")
def demo_reset():
    return mysql_guard(demo.reset)


@app.post("/api/demo/redis/{action}")
def demo_redis(action: str):
    if action not in ("stop", "start"):
        raise HTTPException(400, detail="stop or start")
    return ok(demo.redis_power(action))


@app.post("/api/demo/replication/{action}")
def demo_replication(action: str):
    if action == "compare":
        return ok(demo.compare())
    if action not in ("pause", "resume"):
        raise HTTPException(400, detail="pause, resume or compare")
    return ok(demo.replication(action))


@app.post("/api/internal/book")
def internal_book(body: dict):
    return mysql_guard(demo.internal_book, body)


# ---------------------------------------------------------------------------
# websocket
# ---------------------------------------------------------------------------
@app.websocket("/ws")
async def ws(socket: WebSocket):
    await socket.accept()
    sql_hist, events = hub.history()
    await socket.send_text(json.dumps({
        "type": "hello", "instance": INSTANCE, "settings": state.get(), "health": background.health,
        "sql": sql_hist[-200:], "events": events[-40:],
    }, default=str))
    hub.clients.add(socket)
    try:
        while True:
            await socket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        hub.clients.discard(socket)


# ---------------------------------------------------------------------------
# frontend (built by Vite into web/dist)
# ---------------------------------------------------------------------------
if WEB_DIR.exists():
    @app.get("/console")
    def console_page():
        return FileResponse(WEB_DIR / "index.html")

    app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")
