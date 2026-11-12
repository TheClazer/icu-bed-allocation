# CLAUDE.md

Guide for working on this repository. Read it before changing anything.

## What this is

City ICU Bed Allocation System: DBMS lab mini project (CD252IA, RV College of Engineering) by
Rayyan Shaikh (1RV24CY044) and Pooja Nagesh (1RV24CY038). Helplines and ambulances find and hold the
nearest free ICU, ventilator or oxygen bed. The point of the project is that **the database defends
itself** and the interface makes that visible live: every SQL statement, row lock, deadlock, crash
recovery and replication delay.

## Hard rules (lab and team)

- SQL + NoSQL is mandatory: **MySQL 8 (InnoDB) + Redis 7**. **No PHP, no MongoDB**, anywhere.
- **Raw SQL only, no ORM.** Every statement goes through `db.Session.run()` so it shows in the live SQL log.
- MySQL is the source of truth. Redis is written only after a MySQL COMMIT and must be rebuildable from MySQL.
- Plain descriptive names everywhere. No catchy product names.
- **No em dashes** in UI text, docs or comments. Use commas, colons or full stops.
- Git: **never add Claude as co-author or contributor**, no `Co-Authored-By` lines, no "Generated with" lines.
  Commit or push only when asked.
- Documents for submission are short: the requirement spec must fit 1 to 2 handwritten pages.

## Design rules (the user is strict about these)

- **Light theme only.** Never dark.
- **Two to three colours only**: navy ink `#13202b`, clinical blue `#1f4fd1`, signal red `#d23a4a`
  (errors, deadlocks, the ECG trace), plus neutral greys. No green, amber, violet or "circus" colours.
  Bed states map onto these: FREE = solid blue, HELD = blue outline, OCCUPIED = ink, MAINTENANCE = hatched grey.
- Must not look like a generic AI website: no glow/spotlight cards, no gradient washes, no emoji,
  no all-caps eyebrow labels, no middle-dot meta strings, no arrow-suffixed buttons. Sentence case.
- Type: Barlow (interface), Barlow Condensed (numerals, headings), Geist Mono (SQL, ids).
- Signature element: ECG chart paper (faint pink millimetre grid, class `.ecg`) behind the database vitals only.
- React Bits components in use: GradientASCII (light mode, cover only), TechText ("ICU DBMS" wordmark,
  cover only), TextCursor (SQL ribbon, cover only), CountUp (numbers). Keep effects to the cover; the
  working screens stay quiet. Components live in `web/src/components/reactbits/` (copied from reactbits.dev).

## Run, build, test

No Docker. `app/services.py` runs portable MySQL 8.0.40 (primary + replica) and Redis 7.4 from `runtime/`
(gitignored, downloaded on first run) plus two uvicorn processes.

```bash
run.bat                                    # or: .venv\Scripts\python -m app.services up
stop.bat                                   # or: .venv\Scripts\python -m app.services down
.venv\Scripts\python -m app.services status
.venv\Scripts\python -m pytest -q tests  # resets demo data, not during a live demo
.venv\Scripts\python -m app.services fresh   # wipe both MySQL data dirs (needed after schema changes)
```

- App instances: http://localhost:8000 (app-1), http://localhost:8001 (app-2); console only: `/console`.
- Deep links: `/#tab=lab&console=xray&table=reservation` (tabs: request, dashboard, lab;
  console: tables, sql, xray, redis, metrics, query).
- MySQL primary `localhost:3307`, replica `localhost:3308` (root / rootpass), Redis `6379`.
- After editing `app/*.py`: `stop.bat` then `run.bat` (MySQL data is kept). Logs: `runtime/logs/`.
- The app serves `web/dist`. After frontend edits: `cd web && npx vite build`, then reload the browser.
- `db/seed.sql` is generated: edit `tools/make_seed.py`, then `python tools/make_seed.py`.

## Layout

```text
db/     schema.sql triggers.sql events.sql seed.sql readonly_user.sql replication_user.sql
app/    main.py (API + WebSocket)  db.py (logged sessions)  booking.py  transfer.py  xray.py  metrics.py
        redis_client.py  nlp.py  demo.py  background.py (health, audit-log watcher, metrics)  services.py
web/    React 18 + Vite. src/views (Request, Dashboard, Lab, Cover), src/console (live DB panel), src/lib
tests/  race x50, unique guard, deadlock, expiry + Redis consistency, hold limit + audit, NLP
docs/   viva_guide.md, screenshots/
```

## Things that are easy to break

- Booking locks **one SELECT per hospital** with `FOR UPDATE SKIP LOCKED`. A single `ORDER BY FIELD(...)`
  locking read would lock every candidate row before sorting.
- In transfers, `INSERT INTO transfer` must come **after** both beds are X-locked: the FK check takes S locks
  on `bed` and deadlocks otherwise, even with ordered locking.
- The UNIQUE guard is the generated column `reservation.active_bed_id` (bed_id only while `HELD`).
- Hold expiry runs inside MySQL (`expire_holds` event every 5 s, `sim_now()` clock). The app learns about it
  only by tailing `audit_log`; the watcher must handle `audit_log` being truncated by a reset.
- Redis counters can lag a commit: before returning NO_BED the booking re-checks MySQL.
- Store selectors in React (`useStore`) must return stable references (no `|| []` literals), or React loops.
- The crash demo kills the mysqld process by the pid in `runtime/pids/primary.pid` and restarts it via `services.start_mysql`;
  recovery lines are read from `runtime/logs/primary.err`.
