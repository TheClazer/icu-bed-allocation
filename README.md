# City ICU Bed Allocation System

DBMS Lab mini project (CD252IA), RV College of Engineering.
Rayyan Shaikh (1RV24CY044), Pooja Nagesh (1RV24CY038).

Helplines and ambulances find and hold the nearest free ICU, ventilator or oxygen bed across Bengaluru
hospitals. MySQL guarantees a bed is never booked twice; Redis gives fast geo search and live updates.
The interface exists to make the database's behaviour visible: every SQL statement, row lock, deadlock
and replication delay shows up live while you use it.

## Run it

Needs Docker Desktop (Windows, macOS or Linux). From this folder:

```bash
docker compose up -d --build
```

First start takes 1 to 3 minutes (image build, MySQL initialisation, replica catch-up). Then open:

| What | Where |
| --- | --- |
| Application (instance app-1) | http://localhost:8000 |
| Second application instance (app-2) | http://localhost:8001 |
| Live database console on its own | http://localhost:8000/console |
| MySQL primary (Workbench) | localhost:3307, root / rootpass |
| MySQL replica | localhost:3308, root / rootpass |
| Redis | localhost:6379 |

Run the automated tests (they reset the demo data, so not during a live demo):

```bash
docker compose exec app python -m pytest -q tests
```

Start completely fresh (deletes both MySQL data volumes):

```bash
docker compose down -v
```

## Architecture

```text
browser --> app-1 (FastAPI :8000) --+--> MySQL 8 primary   InnoDB, binlog + GTID     :3307
        --> app-2 (FastAPI :8001) --+        | asynchronous replication
                                    |        v
                                    +--> MySQL 8 replica   super_read_only           :3308
                                    +--> Redis 7           GEO, counters, pub/sub    :6379
```

| Layer | Technology | Role |
| --- | --- | --- |
| Source of truth | MySQL 8.0, InnoDB, REPEATABLE READ | Tables, constraints, row locks, triggers, scheduled event, crash recovery |
| Read replica | MySQL 8.0, GTID replication | Reports and the replication demo; never used for bookings |
| NoSQL | Redis 7 | `hospitals:geo` GEO set, `free:{hospital}:{type}` counters, `events` pub/sub channel |
| Backend | Python 3.11, FastAPI, PyMySQL (raw SQL, no ORM) | Two identical, stateless instances |
| Frontend | React 18 + Vite, React Bits components | Built into static files served by FastAPI |

### Project layout

```text
db/        schema.sql, triggers.sql, events.sql, seed.sql, readonly_user.sql,
           replication_user.sql, replica_init.sql
app/       main.py (API + WebSocket), db.py (logged SQL sessions), booking.py, transfer.py,
           xray.py (InnoDB internals), metrics.py, redis_client.py, nlp.py, demo.py,
           background.py (health, audit-log watcher, metrics), containers.py (docker control)
web/       React app (src/views, src/console, src/components/reactbits)
tests/     test_race.py, test_unique_guard.py, test_deadlock.py, test_expiry.py, test_audit_and_nlp.py
docs/      viva_guide.md
tools/     make_seed.py (regenerates db/seed.sql)
```

## Demo script (about 12 minutes)

Keep the **Live database** panel open on the right the whole time. Every step names what to point at.

1. **Normal booking (1 min).** Request tab. Click the example "need ventilator bed near Jaynagar...",
   type a name, press *Find nearest bed and hold it*. Point at: the parsed fields with the words they came
   from (NLP), the result card's statement list (Redis GEOSEARCH, MGET, then START TRANSACTION ... COMMIT,
   then the Redis counter SET after the commit), and the bed row flashing HELD in the Tables tab.
   Then *Cancel hold* so bed 104 is free again (or Reset demo data).
2. **Race for the last bed (2 min).** Demo lab, demo 1, *Row lock*. Start the race. One request holds bed 104,
   the other gets no bed without waiting (SKIP LOCKED). Free the bed, switch to *No lock*, race again:
   both read FREE, the second INSERT fails with **1062 on one_active_booking_per_bed**. The database caught
   what the application missed. Tick *Send request B through app-2* to show two server processes, one database.
3. **Hold expiry (1 min).** Demo 2, *Fast-forward 30 minutes*. Within 5 s the `expire_holds` event expires
   the holds. Point at: no app SQL in the log for it, audit_log rows with user_id NULL, Redis tab still all
   "match".
4. **Deadlock (2 min).** Demo 3 in *Request order*, run. One transfer fails with **1213**, the wait-for graph
   shows the cycle and the victim. Switch to *Ordered locks*, run again: one waits, both complete.
   Open the X-Ray tab while it runs to see the lock wait live.
5. **Crash recovery (2 min).** Demo 4. The transfer pauses mid-way; X-Ray shows the open transaction with
   rows modified while other sessions still see the old values. MySQL is SIGKILLed and restarts. Point at:
   the before / after table (identical), the transfer row gone, and MySQL's own log line
   "Rolling back trx with id ..., 3 rows to undo".
6. **Bed blocking and audit (1 min).** Demo 5. Spam 8 holds: 5 held, 3 refused by the trigger (1644).
   Run the audit: Suspicious Agent is flagged.
7. **Replication (1.5 min).** Demo 6. Pause replica, book one bed, Compare: primary shows the hold, replica
   does not, lag grows in the header strip. Resume: they converge.
8. **Redis outage (1 min).** Demo 7. Stop Redis, book: search source says MySQL ST_Distance_Sphere.
   Start Redis: every key is rebuilt from MySQL.
9. **Let the evaluator try (open).** Query tab: `DELETE FROM bed` is refused (1142, read-only user).
   EXPLAIN the booking query to show `idx_bed_search`. Open a second tab or app-2 and book against each other.
10. **Reset demo data** (demo 9) between evaluators.

## Notes

- All data is simulated (tools/make_seed.py). No real patients or hospitals.
- Simulated clock: hold expiry uses `sim_now()` (NOW() plus `sim_clock.offset_minutes`).
- Schema changes need a fresh volume: `docker compose down -v` then `docker compose up -d --build`.
- No PHP and no MongoDB anywhere.
