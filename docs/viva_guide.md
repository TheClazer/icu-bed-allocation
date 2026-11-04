# Viva guide: City ICU Bed Allocation System

Each section: the idea in two lines, where it lives in this project, and the questions an examiner is
likely to ask, with short answers you can say out loud.

---

## 1. The one-line pitch

"Many helplines book from one shared pool of scarce ICU beds at the same time. Our job is to make sure
the database, not the application, guarantees that no bed is ever given to two patients, even under
concurrency, bugs and crashes."

---

## 2. Data model and normalization

Nine entities: hospital, bed_type, bed, user_account, patient, bed_request, reservation, transfer,
audit_log. Helpers: sim_clock (one row), replication_probe (one row), two views.

Where: `db/schema.sql`.

- **Why is reservation separate from bed_request?** A request is the need ("ventilator bed for this
  patient"); a reservation is one attempt to satisfy it on one bed. One request can have several
  reservations over time (one expires, the next succeeds). Merging them would repeat request data.
- **Why does bed store patient_id?** It is the current occupant, a fact about the bed right now. The
  reservation is history (how the patient got a bed). A CHECK keeps it honest:
  `(status = 'OCCUPIED') = (patient_id IS NOT NULL)`.
- **Which normal form?** 3NF. Every non-key column depends on the key, the whole key and nothing but the
  key; for example hospital name lives only in hospital, never copied into bed.
- **Why INT keys like 104 for beds?** Readable in a demo (hospital 1, bed 04). They are still plain
  surrogate keys with no meaning enforced by the database.

---

## 3. Transactions and ACID

| Property | Where you can see it |
| --- | --- |
| Atomicity | Crash demo: the transfer row and both bed updates disappear together after the kill |
| Consistency | Constraints (PK, FK, UNIQUE, CHECK, NOT NULL) and triggers reject invalid states |
| Isolation | Crash demo: while the transfer is paused, other sessions still read the old committed values |
| Durability | Holds committed before the kill are still there after restart (redo log) |

Where: `app/booking.py`, `app/transfer.py`, every `START TRANSACTION ... COMMIT` in the SQL log.

- **What isolation level do you use?** InnoDB's default, REPEATABLE READ. Plain SELECTs read a
  consistent snapshot (MVCC), locking reads (FOR UPDATE) read the latest committed row and lock it.
- **Why not SERIALIZABLE?** It would turn every plain SELECT into a shared-locking read and serialize far
  more than needed. We lock exactly the rows we change.

---

## 4. Concurrency control: the race for the last bed

```sql
SELECT bed_id FROM bed
 WHERE bed_type_id = ? AND status = 'FREE' AND hospital_id = ?
 ORDER BY bed_id LIMIT 1
   FOR UPDATE SKIP LOCKED;
```

- **What does FOR UPDATE do?** Takes an exclusive (X) row lock on the bed row until COMMIT, so no other
  transaction can lock or change it.
- **What does SKIP LOCKED add?** A second request does not wait for the locked row; it skips it and moves
  to the next free bed. The loser of the race is not blocked, it just looks elsewhere.
- **Why one query per hospital instead of ORDER BY FIELD(hospital_id, ...)?** A locking read locks every
  row it scans. With ORDER BY FIELD the server must read (and lock) all candidate free beds before it can
  sort, so the second request would skip all of them. Per hospital, the composite index already returns
  rows in bed_id order and LIMIT 1 locks exactly one row.
- **What if the application forgets to lock?** That is the "No lock" switch. Both requests read FREE.
  The UNIQUE index on the generated column `active_bed_id` lets only one live hold exist per bed, so the
  second INSERT fails with error 1062. Constraints are the last line of defence.
- **Why a generated column?** UNIQUE(bed_id) on reservation would forbid any history per bed. The column
  is bed_id only while status = 'HELD' and NULL otherwise, and a UNIQUE index ignores NULLs, so history is
  unlimited but live holds are unique.

---

## 5. Deadlocks

- **What is a deadlock?** Two transactions each hold a lock the other needs: a cycle in the wait-for
  graph. Neither can proceed.
- **How does InnoDB handle it?** It checks the wait-for graph whenever a transaction starts waiting. On a
  cycle it rolls back the transaction that is cheaper to undo (fewer rows changed) and returns error 1213
  to it. We show the victim in X-Ray, parsed from `SHOW ENGINE INNODB STATUS`.
- **How do you prevent it?** Lock ordering: every transfer locks the lower bed_id first. Two transfers then
  queue on the same row and a cycle is impossible.
- **Something subtle you found?** Yes. The INSERT into transfer has foreign keys to bed, and InnoDB checks a
  foreign key by taking a shared lock on the parent row. Done before the bed locks, that INSERT could
  deadlock even with ordered locking. We insert the transfer row after the beds are already X-locked.

---

## 6. Crash recovery

- **What happens when you kill MySQL?** SIGKILL, no shutdown. On restart InnoDB replays the redo log so
  every committed change is on disk, then uses the undo log to roll back transactions that never
  committed. The MySQL log in the demo literally prints "Rolling back trx with id ..., 3 rows to undo".
- **Which 3 rows?** The transfer row we inserted, the bed update, and the audit_log row the bed trigger
  wrote. All undone together.
- **What does the binary log have to do with it?** With the binlog on, commit is a two-phase commit
  between binlog and InnoDB (internal XA). The log shows "Starting XA crash recovery" for that reason.

---

## 7. Triggers, scheduled events, stored function, views

Where: `db/triggers.sql`, `db/events.sql`, `db/schema.sql`.

| Object | Does |
| --- | --- |
| `trg_reservation_hold_limit` (BEFORE INSERT) | Refuses a sixth live hold per account with SIGNAL SQLSTATE '45000' |
| `trg_reservation_after_insert` | Writes RESERVATION_HELD to audit_log |
| `trg_reservation_after_update` | Audits status changes; on EXPIRED or CANCELLED sets the bed back to FREE |
| `trg_bed_after_update` | Audits bed status and occupant changes (also the change feed for Redis) |
| `trg_transfer_after_update` | Audits transfer outcomes |
| `expire_holds` event (every 5 s) | Marks HELD reservations past `sim_now()` as EXPIRED |
| `sim_now()` function | NOW() plus the simulated clock offset |
| `v_hold_conversion` view | Holds, admissions and failure % per account (GROUP BY) |
| `v_bed_board` view | Beds joined with hospital, type and patient names |

- **Why put this logic in the database instead of Python?** It holds for every client: two app instances,
  the MySQL event, or someone at the MySQL prompt. An audit trail that the application writes can be
  skipped by a buggy application; a trigger cannot.
- **Trigger on reservation updates bed: is that allowed?** Yes. A trigger may not modify its own table,
  but it can modify other tables, and bed's own trigger then fires (nested triggers).
- **How does the app learn about expiries done by the event?** It tails audit_log (rows written by
  triggers) every 0.6 s, publishes them to Redis pub/sub and refreshes the affected counters.

---

## 8. Indexes and EXPLAIN

- `idx_bed_search (bed_type_id, status, hospital_id)`: the booking query has equality on all three
  columns, and InnoDB secondary indexes end with the primary key, so rows come out already in bed_id
  order. EXPLAIN shows `type: ref`, `key: idx_bed_search`, `Using index`, rows 1.
- `idx_hold_expiry (status, hold_expires_at)`: the expiry event's WHERE status = 'HELD' AND
  hold_expires_at < ? is a range scan on this index.
- `one_active_booking_per_bed`: a UNIQUE index used as a business rule.

---

## 9. SQL plus NoSQL: why Redis, and why it cannot cause a wrong booking

| Redis key | Type | Use |
| --- | --- | --- |
| `hospitals:geo` | GEO (sorted set) | GEOSEARCH nearest hospitals by radius |
| `free:{hospital}:{type}` | String | Free-bed counters for the dashboard and search filter |
| `events` | Pub/sub channel | Every change pushed to every browser via each app instance |
| `settings` | Hash | Shared switches for both app instances |

- **Is Redis the source of truth?** No. Counters are written only after a MySQL COMMIT and always by
  re-reading the count from MySQL, so they cannot drift. Everything can be rebuilt from MySQL.
- **What if a counter is stale?** Before saying "no bed", the booking asks MySQL directly whether any
  skipped hospital has a free bed. A stale cache can cost one extra query, never a missed bed.
- **What if Redis is down?** Search falls back to `ST_Distance_Sphere` in MySQL. Slower, still correct.

---

## 10. Replication and multiple instances

- **How is the replica set up?** GTID-based asynchronous replication. The replica's IO thread pulls the
  primary's binary log into its relay log; its SQL thread applies it. `SOURCE_AUTO_POSITION = 1` means
  the replica asks for every GTID it has not executed, so it replayed the full history on first start.
- **Asynchronous means?** The primary commits without waiting for the replica. The replica can lag, so
  reads there may be stale. That is why bookings, locks and admissions always go to the primary.
- **How do you measure lag?** The app rewrites a probe row on the primary every second; lag is how old
  the replica's copy is. MySQL's own Seconds_Behind_Source is shown too.
- **Why can't anyone write on the replica?** `super_read_only = ON`.
- **Why two app instances?** To show that correctness lives in the database. Request A goes through
  app-1, request B through app-2: separate processes and connection pools, and still only one live hold.

---

## 11. Security and privileges

- The Query tab connects as `icu_readonly` (GRANT SELECT, SHOW VIEW only) inside `START TRANSACTION READ
  ONLY`. A DELETE fails with error 1142 from MySQL itself, not from our code.
- All application SQL uses parameterised queries (PyMySQL escapes values), so no SQL injection.
- All data is simulated.

---

## 12. The innovative component: free-text parser

Where: `app/nlp.py`. Rule-based and offline: keyword rules for bed type and severity, regular
expressions for age and sex ("60M", "45 year old female"), and fuzzy matching with rapidfuzz for area
names ("jaynagar" matches Jayanagar at 94%). Each extracted field is shown with the words it came from.
The original text is stored in `bed_request.raw_text`.

- **Why not a machine learning model?** The vocabulary is small and fixed, rules are explainable and run
  offline, and every decision can be shown to the user.

---

## 13. Numbers worth remembering

- 9 entities, 5 triggers, 1 event, 1 stored function, 2 views, 2 MySQL users besides root.
- 7 hospitals, 56 beds, exactly 1 free ventilator bed after a reset (bed 104).
- Hold time 30 minutes; expiry event every 5 seconds; hold limit 5 per account.
- Tests: race run 50 times, unique guard, deadlock both modes, expiry with Redis consistency, hold limit
  and audit, 12 NLP sentences.
