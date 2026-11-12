import { useEffect, useRef, useState } from 'react';
import { useApp } from '../App.jsx';
import WaitForGraph, { deadlockEdges } from '../console/Graph.jsx';
import { ActionButton, Panel, Pill, PlainTable, Seg, Status } from '../components/ui.jsx';
import { api, fmtTime, post, TYPE_LABEL } from '../lib/api.js';
import { toast, usePoll } from '../lib/hooks.js';
import { clearDemo, live } from '../lib/live.js';
import { useStore } from '../lib/store.js';
import Trace from '../components/Trace.jsx';

function Demo({ title, tags, what, controls, children, explain, watch }) {
  const { openConsole, scenario, setScenario } = useApp();
  const i = SCENARIOS.findIndex((s) => s.id === scenario);
  const next = SCENARIOS[i + 1];
  return (
    <article className="stage">
      <h2 className="stage-title">{title}</h2>
      <p className="stage-what">{what}</p>
      {controls && <div className="stage-ctl">{controls}</div>}
      {children && <div className="stage-out">{children}</div>}
      {explain && (
        <details className="why">
          <summary>Why this works</summary>
          <div className="body">{explain}{tags && <p className="muted" style={{ margin: 0 }}>Concepts: {tags.join(', ')}.</p>}</div>
        </details>
      )}
      <div className="stage-foot">
        {watch?.[0] && <button type="button" className="linkbtn" onClick={() => openConsole(watch[0].tab, watch[0])}>See it in the database</button>}
        <span className="grow" />
        {next && <button type="button" className="btn ghost" onClick={() => setScenario(next.id)}>Next: {next.title}</button>}
      </div>
    </article>
  );
}

function useRun() {
  const [busy, setBusy] = useState(false);
  const run = async (fn) => {
    setBusy(true);
    try { return await fn(); } catch (e) { toast(e.message, 'err'); return null; } finally { setBusy(false); }
  };
  return [busy, run];
}

function Side({ title, r }) {
  if (!r) return null;
  const outcome = r.outcome;
  return (
    <div className="side">
      <div className="side-head">
        <b>{title}</b>
        <Status value={outcome} />
        <span className="grow" />
        <span className="mono faint" style={{ fontSize: 10.5 }}>{r.tx}, conn {r.conn}</span>
      </div>
      <div className="side-body">
        {outcome === 'HELD' && <div style={{ marginBottom: 6 }}>Holds bed <b className="mono">{r.bed_id}</b> at {r.hospital}</div>}
        {outcome === 'NO_BED' && <div style={{ marginBottom: 6 }}>SKIP LOCKED skipped the locked bed and found nothing else free. Request stays OPEN.</div>}
        {outcome === 'DONE' && <div style={{ marginBottom: 6 }}>Committed. {r.note}</div>}
        {(outcome === 'REJECTED' || outcome === 'ROLLED_BACK') && (
          <div style={{ marginBottom: 6, color: 'var(--danger)' }}>
            <b>MySQL {r.code}</b> <span className="mono" style={{ fontSize: 11.5 }}>{r.error}</span>
            {r.meaning && <div style={{ color: 'var(--ink-2)', marginTop: 2 }}>{r.meaning}.</div>}
          </div>
        )}
        <Trace trace={r.trace} limit={11} />
      </div>
    </div>
  );
}

// ------------------------------------------------------------------ 1. race
function RaceDemo() {
  const { settings, setSetting, userId } = useApp();
  const [across, setAcross] = useState(false);
  const [busy, run] = useRun();
  const [res, setRes] = useState(null);
  const go = () => run(async () => setRes(await post('/demo/race', { mode: settings.booking_mode, across_instances: across })));
  const freeWinner = () => run(async () => {
    const winner = [res.A, res.B].find((x) => x?.outcome === 'HELD');
    if (winner) { const r = await post(`/reservations/${winner.reservation_id}/cancel`, { user_id: userId }); toast(r.message); }
    setRes(null);
  });
  return (
    <Demo no="1" title="Race for the last bed" tags={['Concurrency control', 'Row locks', 'FOR UPDATE SKIP LOCKED', 'UNIQUE constraint']}
      what="Two ambulances request the only free ventilator bed in the city at the same instant. Exactly one may get it."
      controls={<>
        <Seg value={settings.booking_mode} onChange={(v) => setSetting({ booking_mode: v })}
          options={[{ value: 'safe', label: 'Row lock (safe)' }, { value: 'unsafe', label: 'No lock (unsafe)', bad: true }]} />
        <label className="check"><input type="checkbox" checked={across} onChange={(e) => setAcross(e.target.checked)} />Send request B through app-2</label>
        <ActionButton disabled={busy} onClick={go}>{busy ? 'Racing...' : 'Start the race'}</ActionButton>
        {res?.ok && <button className="btn" disabled={busy} onClick={freeWinner}>Free the bed for a rerun</button>}
      </>}
      watch={[{ label: 'SQL log (two interleaved transactions)', tab: 'sql' }, { label: 'X-Ray row lock', tab: 'xray' }, { label: 'reservation table', tab: 'tables', table: 'reservation' }]}
      explain={<>
        <p style={{ margin: 0 }}><b>Row lock:</b> each request runs <span className="mono">SELECT ... FOR UPDATE SKIP LOCKED</span>. The first to reach bed 104 locks it and holds the lock for 1.5 s. The second does not wait: SKIP LOCKED jumps over the locked row, finds nothing else free and returns no bed.</p>
        <p style={{ margin: 0 }}><b>No lock:</b> both read the bed with a plain SELECT (a consistent snapshot), both see FREE, both sleep 2 s, both INSERT a HELD reservation. The generated column <span className="mono">active_bed_id</span> carries a UNIQUE index, so the second INSERT waits for the first to commit and then fails with error 1062. The database caught what the application missed.</p>
        <pre className="code">{`active_bed_id INT GENERATED ALWAYS AS (CASE WHEN status = 'HELD' THEN bed_id END) STORED,
UNIQUE KEY one_active_booking_per_bed (active_bed_id)   -- NULLs are ignored by UNIQUE`}</pre>
      </>}>
      {res && !res.ok && <div className="verdict warn">{res.message}</div>}
      {res?.ok && (
        <>
          <div className="muted" style={{ marginBottom: 8 }}>Bed <b className="mono">{res.bed_id}</b> ({res.bed_type}) at {res.hospital}, both requests from {res.area}
            {res.across_instances ? ', A served by app-1 and B by app-2: two processes, one database.' : '.'}</div>
          <div className="versus"><Side title="Request A, KA-01" r={res.A} /><Side title="Request B, KA-02" r={res.B} /></div>
          <div className={`verdict ${res.live_holds_on_bed === 1 ? 'ok' : 'bad'}`}>{res.verdict} (SELECT COUNT(*) ... WHERE bed_id = {res.bed_id} AND status = 'HELD' returned {res.live_holds_on_bed})</div>
        </>
      )}
    </Demo>
  );
}

// ------------------------------------------------------------------ 2. expiry
function ExpiryDemo() {
  const [busy, run] = useRun();
  const [ff, setFf] = useState(null);
  const events = useStore(live, (s) => s.events);
  const since = useRef(0);
  const expired = ff ? events.filter((e) => e.data?.kind === 'audit' && e.data?.action === 'RESERVATION_EXPIRED' && e.data.ts * 1000 >= since.current) : [];
  const { data: dash } = usePoll('/dashboard', 5000);
  const go = () => run(async () => { since.current = Date.now() - 500; setFf(await post('/clock/forward', { minutes: 30 })); });
  return (
    <Demo no="2" title="Holds expire by themselves" tags={['EVENT scheduler', 'Triggers', 'Stored function', 'Simulated clock']}
      what="A hold lasts 30 minutes. Move the clock forward and MySQL itself expires every unconverted hold and frees its bed. The application does nothing."
      controls={<>
        <span className="muted">Live holds right now: <b className="mono">{dash?.status_totals?.HELD || 0}</b></span>
        <ActionButton disabled={busy} onClick={go}>Fast-forward 30 minutes</ActionButton>
      </>}
      watch={[{ label: 'reservation rows turn EXPIRED', tab: 'tables', table: 'reservation' }, { label: 'audit_log (user_id NULL = scheduler)', tab: 'tables', table: 'audit_log' }, { label: 'Redis counters', tab: 'redis' }]}
      explain={<>
        <p style={{ margin: 0 }}>Every expiry check reads <span className="mono">sim_now()</span>, a stored function that adds <span className="mono">sim_clock.offset_minutes</span> to NOW(). The button only runs one UPDATE on sim_clock.</p>
        <pre className="code">{`CREATE EVENT expire_holds ON SCHEDULE EVERY 5 SECOND DO
  UPDATE reservation SET status = 'EXPIRED'
   WHERE status = 'HELD' AND hold_expires_at < sim_now();   -- uses idx_hold_expiry

-- trigger trg_reservation_after_update then runs, for each expired row:
  UPDATE bed SET status = 'FREE' WHERE bed_id = NEW.bed_id AND status = 'HELD';
  INSERT INTO audit_log (...)   -- user_id NULL: done by the scheduler`}</pre>
        <p style={{ margin: 0 }}>Notice the SQL log shows no UPDATE from the app for the expiry: it runs inside MySQL. The app only notices through audit_log, then refreshes the Redis counters.</p>
      </>}>
      {ff && (
        <div className="stack" style={{ gap: 8 }}>
          <div className="verdict warn">Clock is now {fmtTime(ff.sim_now)} (+{ff.offset_minutes} min). {ff.due} hold(s) are past expiry; the expire_holds event will pick them up within 5 s.</div>
          {expired.length > 0 && (
            <div className="verdict ok" style={{ display: 'block' }}>
              The MySQL event expired {expired.length} hold(s):{' '}
              <span className="mono">{expired.map((e) => `reservation ${e.data.entity_id} (bed ${e.data.details?.bed_id})`).join(', ')}</span>
            </div>
          )}
        </div>
      )}
    </Demo>
  );
}

// ------------------------------------------------------------------ 3. deadlock
function CrossingDemo() {
  const { settings, setSetting } = useApp();
  const [busy, run] = useRun();
  const [res, setRes] = useState(null);
  const go = () => run(async () => setRes(await post('/demo/crossing', { ordered: settings.lock_ordering })));
  const g = res?.deadlock ? deadlockEdges(res.deadlock) : null;
  return (
    <Demo no="3" title="Crossing transfers and deadlock" tags={['Deadlock detection', 'Wait-for graph', 'Lock ordering', 'Error 1213']}
      what="Two wards move two patients into each other's beds at the same moment. Each transfer must lock both beds."
      controls={<>
        <Seg value={settings.lock_ordering} onChange={(v) => setSetting({ lock_ordering: v })}
          options={[{ value: true, label: 'Ordered locks (prevention on)' }, { value: false, label: 'Request order (deadlock-prone)', bad: true }]} />
        <ActionButton disabled={busy} onClick={go}>{busy ? 'Transfers running (about 5 s)...' : 'Run both transfers'}</ActionButton>
      </>}
      watch={[{ label: 'X-Ray: locks and wait-for graph', tab: 'xray' }, { label: 'transfer table', tab: 'tables', table: 'transfer' }, { label: 'SQL log', tab: 'sql' }]}
      explain={<>
        <p style={{ margin: 0 }}><b>Request order:</b> A locks its source bed, sleeps 2 s, then asks for its target. B does the same in the opposite direction. A waits for B and B waits for A: a cycle in the wait-for graph. InnoDB detects it immediately, rolls back the transaction that is cheaper to undo (error 1213) and lets the other finish.</p>
        <p style={{ margin: 0 }}><b>Ordered locks:</b> both lock the lower bed_id first. B simply queues behind A on the same row; there is no cycle, so both complete. The second one finds its patient already moved and records a no-op.</p>
        <pre className="code">{`START TRANSACTION;
SELECT ... FROM bed WHERE bed_id = LEAST(:a, :b)    FOR UPDATE;   -- ordered
SELECT ... FROM bed WHERE bed_id = GREATEST(:a, :b) FOR UPDATE;
INSERT INTO transfer (...) VALUES (..., 'PENDING');   -- after the locks: FK checks take S locks on bed
UPDATE bed SET patient_id = ... ;  UPDATE transfer SET status = 'DONE';
COMMIT;`}</pre>
      </>}>
      {res && !res.ok && <div className="verdict warn">{res.message}</div>}
      {res?.ok && (
        <div className="stack" style={{ gap: 10 }}>
          <div className="muted">{res.hospital}. A: {res.story.A}. B: {res.story.B}.</div>
          <div className="versus"><Side title="Transfer A" r={res.A} /><Side title="Transfer B" r={res.B} /></div>
          {g ? (
            <div>
              <div className="label" style={{ marginBottom: 6 }}>Deadlock reported by SHOW ENGINE INNODB STATUS</div>
              <WaitForGraph nodes={g.nodes} edges={g.edges} victim={g.victim} labels={g.labels} />
            </div>
          ) : res.edges_seen.length > 0 && (
            <div>
              <div className="label" style={{ marginBottom: 6 }}>Lock wait observed in performance_schema.data_lock_waits (no cycle)</div>
              <WaitForGraph edges={res.edges_seen} />
            </div>
          )}
          <div className={`verdict ${res.deadlock ? 'bad' : 'ok'}`}>{res.verdict}. Beds now: {res.beds_after.map((b) => `${b.bed_id} ${b.patient}`).join(', ')}</div>
        </div>
      )}
    </Demo>
  );
}

// ------------------------------------------------------------------ 4. crash
const NO_STEPS = [];

function CrashDemo() {
  const [busy, run] = useRun();
  const [res, setRes] = useState(null);
  const steps = useStore(live, (s) => s.demo.crash || NO_STEPS);
  const go = () => {
    if (!window.confirm('This sends SIGKILL to the MySQL container. It restarts and recovers in about 10 to 30 seconds. Continue?')) return;
    clearDemo('crash'); setRes(null);
    run(async () => setRes(await post('/demo/crash')));
  };
  const rowsFor = (list, id) => list?.find((b) => b.bed_id === id) || {};
  return (
    <Demo no="4" title="Kill the database in the middle of a transfer" tags={['Atomicity', 'Durability', 'Crash recovery', 'Redo and undo logs', 'Isolation']}
      what="A transfer has already freed the old bed but not yet taken the new one. Nothing is committed. Then the MySQL server is killed outright."
      controls={<ActionButton className="btn danger" spark="#b42d24" disabled={busy} onClick={go}>{busy ? 'Crash demo running...' : 'Start transfer, then kill MySQL'}</ActionButton>}
      watch={[{ label: 'X-Ray (the paused transaction)', tab: 'xray' }, { label: 'bed table', tab: 'tables', table: 'bed' }, { label: 'metrics (uptime resets)', tab: 'metrics' }]}
      explain={<>
        <p style={{ margin: 0 }}>While paused, other sessions still read the old committed values: the half-done move is invisible to them (isolation). The kill is a SIGKILL: no clean shutdown, no buffer flush.</p>
        <p style={{ margin: 0 }}>On restart InnoDB runs crash recovery. It replays the redo log so every committed change is present (durability), then uses the undo log to roll back every transaction that never committed (atomicity). The transfer and both bed updates vanish together; holds committed before the crash are all still there.</p>
      </>}>
      {(steps.length > 0 || res) && (
        <div className="stack" style={{ gap: 10 }}>
          <ol className="steps">
            {steps.map((s) => <li key={s.step} className={s.state}><span className="si">{s.step}</span><span>{s.text}</span></li>)}
          </ol>
          {res && !res.ok && <div className="verdict warn">{res.message}</div>}
          {res?.ok && (
            <>
              <PlainTable columns={[{ key: 'bed', label: 'Bed' }, { key: 'b', label: 'Committed before' }, { key: 'i', label: 'Inside the killed transaction' }, { key: 'o', label: 'Seen by others meanwhile' }, { key: 'a', label: 'After recovery' }]}
                rows={[res.from_bed, res.to_bed].map((id) => {
                  const f = (x) => (x.status ? `${x.status}${x.patient_id ? ` (patient ${x.patient_id})` : ''}` : '');
                  return { bed: id, b: f(rowsFor(res.before, id)), i: id === res.from_bed ? 'FREE (uncommitted)' : 'FREE, not yet taken', o: f(rowsFor(res.outside, id)), a: f(rowsFor(res.after, id)) };
                })} />
              <div className="muted">Live holds before the kill: <b>{res.holds_before}</b>, after recovery: <b>{res.holds_after}</b> (committed work survived). Transfer row from the killed transaction after recovery: <b>{res.transfer?.length ? 'present' : 'gone, rolled back'}</b>. MySQL was back in {res.recovered_in_s} s.</div>
              {res.mysql_log?.length > 0 && (
                <div>
                  <div className="label">MySQL error log during recovery</div>
                  <div className="loglines">{res.mysql_log.map((l, i) => <div key={i} className={/recover|roll|redo|undo/i.test(l) ? 'hl' : ''}>{l}</div>)}</div>
                </div>
              )}
              <div className={`verdict ${res.consistent ? 'ok' : 'bad'}`}>{res.consistent ? 'No bed is half-moved. The uncommitted transaction was rolled back as one unit.' : 'State differs from before: inspect the bed table.'}</div>
            </>
          )}
        </div>
      )}
    </Demo>
  );
}

// ------------------------------------------------------------------ 5. bed blocking + audit
function BlockingDemo() {
  const [busy, run] = useRun();
  const [spam, setSpam] = useState(null);
  const [audit, setAudit] = useState(null);
  return (
    <Demo no="5" title="Bed blocking and the audit" tags={['BEFORE INSERT trigger', 'SIGNAL SQLSTATE 45000', 'View', 'GROUP BY + aggregates']}
      what="A fake helpline account tries to hoard beds with 8 holds. A trigger refuses everything past 5. The control room then audits hold conversion per account."
      controls={<>
        <ActionButton disabled={busy} onClick={() => run(async () => setSpam(await post('/demo/spam')))}>Spam 8 fake holds</ActionButton>
        <button className="btn" disabled={busy} onClick={() => run(async () => setAudit(await post('/demo/audit')))}>Run audit query</button>
      </>}
      watch={[{ label: 'v_hold_conversion view', tab: 'tables', table: 'v_hold_conversion' }, { label: 'audit_log', tab: 'tables', table: 'audit_log' }]}
      explain={<>
        <pre className="code">{`CREATE TRIGGER trg_reservation_hold_limit BEFORE INSERT ON reservation FOR EACH ROW
  ... IF (live holds of this account) >= 5 THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Hold limit reached ...';

SELECT name, total_holds, admitted, not_converted, failure_pct
  FROM v_hold_conversion            -- JOIN reservation, bed_request, user_account, GROUP BY user
 WHERE total_holds >= 5 AND failure_pct >= 50;`}</pre>
      </>}>
      <div className="stack" style={{ gap: 10 }}>
        {spam && (
          <div>
            <div className="muted" style={{ marginBottom: 6 }}>{spam.held} held, {spam.refused} refused by the trigger.</div>
            <div className="row wrap" style={{ gap: 6 }}>
              {spam.attempts.map((a, i) => (
                <span key={i} className="chip" title={a.error || ''} style={{ cursor: 'default' }}>
                  {i + 1}. <Status value={a.outcome} /> {a.outcome === 'HELD' ? `bed ${a.bed_id}` : a.code ? `MySQL ${a.code}` : ''}
                </span>
              ))}
            </div>
          </div>
        )}
        {audit && (
          <PlainTable highlight={(r) => r.flagged} rows={audit.rows}
            columns={['name', 'role', 'total_holds', 'admitted', 'active', 'not_converted',
              { key: 'failure_pct', label: 'failure %', render: (r) => `${r.failure_pct}%` },
              { key: 'flagged', label: 'flag', render: (r) => (r.flagged ? <Pill kind="err">BED BLOCKING</Pill> : '') }]} />
        )}
      </div>
    </Demo>
  );
}

// ------------------------------------------------------------------ 6. replication
function ReplicationDemo() {
  const { userId } = useApp();
  const { data: m } = usePoll('/metrics', 1000, { onEvents: false });
  const [busy, run] = useRun();
  const [cmp, setCmp] = useState(null);
  const rp = m?.replica || {};
  const compare = () => run(async () => setCmp(await post('/demo/replication/compare')));
  const book = () => run(async () => {
    const r = await post('/requests', { user_id: userId, patient_name: 'Replication Test', age: 50, gender: 'F', bed_type_id: 3, area: 'Hebbal', severity: 3 });
    toast(r.outcome === 'HELD' ? `Primary committed a hold on bed ${r.bed_id}` : r.outcome, r.outcome === 'HELD' ? '' : 'err');
    setCmp(await post('/demo/replication/compare'));
  });
  const side = (name, x) => (
    <div className="side">
      <div className="side-head"><b>{name}</b><span className="grow" />{x?.beds && <span className="mono faint" style={{ fontSize: 11 }}>FREE {x.beds.free}, HELD {x.beds.held}, OCC {x.beds.occupied}</span>}</div>
      <div className="side-body">
        {x?.error ? <div className="muted">{x.error}</div> : (
          <>
            <PlainTable columns={['reservation_id', 'bed_id', { key: 'status', label: 'status', render: (r) => <Status value={r.status} /> }]} rows={x?.reservations || []} />
            <div className="mono faint" style={{ fontSize: 10.5, marginTop: 6, wordBreak: 'break-all' }}>gtid_executed: {x?.gtid}</div>
          </>
        )}
      </div>
    </div>
  );
  return (
    <Demo no="6" title="Read replica and replication lag" tags={['Binary log', 'GTID replication', 'Asynchronous', 'Read scaling', 'super_read_only']}
      what="Every commit on the primary is shipped to a second MySQL server through the binary log. Pause the replica's apply thread, book a bed, and the two servers disagree until you resume."
      controls={<>
        <span className="row" style={{ gap: 6 }}><Pill kind={rp.sql_running === 'Yes' ? 'ok' : 'err'}>apply {rp.sql_running === 'Yes' ? 'running' : 'paused'}</Pill>
          <Pill kind={rp.io_running === 'Yes' ? 'ok' : 'err'}>binlog stream {rp.io_running === 'Yes' ? 'on' : 'off'}</Pill>
          <span className="mono">lag {rp.lag_ms ?? '?'} ms</span></span>
        <button className="btn" disabled={busy} onClick={() => run(async () => setCmp(await post('/demo/replication/pause')))}>Pause replica</button>
        <ActionButton disabled={busy} onClick={book}>Book one bed on the primary</ActionButton>
        <button className="btn" disabled={busy} onClick={() => run(async () => setCmp(await post('/demo/replication/resume')))}>Resume replica</button>
        <button className="btn ghost" disabled={busy} onClick={compare}>Compare</button>
      </>}
      watch={[{ label: 'bed table on the replica', tab: 'tables', table: 'bed', source: 'replica' }, { label: 'replication metrics', tab: 'metrics' }]}
      explain={<>
        <p style={{ margin: 0 }}>The replica pulls the primary's binary log (IO thread) and applies it (SQL thread). GTIDs give every transaction a global id, so the replica knows exactly which ones it still needs. Replication is asynchronous: the primary commits without waiting, which is why bookings and locks always use the primary, and only dashboards or reports may read the replica.</p>
        <pre className="code">{`STOP REPLICA SQL_THREAD;     -- pause applying, keep receiving
START REPLICA SQL_THREAD;    -- catch up from the relay log
SHOW REPLICA STATUS;         -- Replica_IO_Running, Replica_SQL_Running, Seconds_Behind_Source`}</pre>
      </>}>
      {cmp && (cmp.primary || cmp.replica) && <div className="versus">{side('Primary (icu_mysql)', cmp.primary)}{side('Replica (icu_mysql_replica)', cmp.replica)}</div>}
    </Demo>
  );
}

// ------------------------------------------------------------------ 7. redis outage
function RedisDemo() {
  const { userId } = useApp();
  const health = useStore(live, (s) => s.health);
  const up = Object.values(health)[0]?.redis;
  const [busy, run] = useRun();
  const [r, setR] = useState(null);
  const book = () => run(async () => setR(await post('/requests', { user_id: userId, patient_name: 'Outage Test', age: 44, gender: 'M', bed_type_id: 1, area: 'Indiranagar', severity: 4 })));
  return (
    <Demo no="7" title="Redis outage" tags={['SQL vs NoSQL roles', 'Source of truth', 'Cache rebuild', 'Graceful degradation']}
      what="Stop the Redis container and keep booking. Search falls back to a MySQL distance query; correctness never depended on Redis."
      controls={<>
        <Pill kind={up ? 'ok' : 'err'}>Redis {up ? 'up' : 'down'}</Pill>
        <button className="btn danger" disabled={busy || !up} onClick={() => run(async () => { await post('/demo/redis/stop'); toast('Redis stopped'); })}>Stop Redis</button>
        <ActionButton disabled={busy} onClick={book}>Book an ICU bed now</ActionButton>
        <button className="btn" disabled={busy || up} onClick={() => run(async () => { const x = await post('/demo/redis/start'); toast(x.ok ? 'Redis back, rebuilt from MySQL' : 'Redis did not start', x.ok ? '' : 'err'); })}>Start Redis and rebuild</button>
      </>}
      watch={[{ label: 'SQL log (ST_Distance_Sphere fallback)', tab: 'sql' }, { label: 'Redis keys', tab: 'redis' }]}
      explain={<pre className="code">{`-- Redis up:   GEOSEARCH hospitals:geo FROMLONLAT lon lat BYRADIUS 50 km ASC WITHDIST
-- Redis down: SELECT hospital_id, ST_Distance_Sphere(POINT(longitude, latitude), POINT(?, ?)) / 1000 AS km
--               FROM hospital ORDER BY km;
-- Back up:    every key is recreated from MySQL (GEOADD + SET), nothing is lost.`}</pre>}>
      {r && <div className={`verdict ${r.outcome === 'HELD' ? 'ok' : 'warn'}`}>{r.outcome === 'HELD' ? `Held bed ${r.bed_id} at ${r.hospital}.` : r.outcome} Search used: {r.search?.source}</div>}
    </Demo>
  );
}

// ------------------------------------------------------------------ 8. check yourself
const CHECKS = [
  { label: 'EXPLAIN the booking query', sql: "EXPLAIN SELECT bed_id FROM bed\n WHERE bed_type_id = 2 AND status = 'FREE' AND hospital_id = 1\n ORDER BY bed_id LIMIT 1" },
  { label: 'Try to DELETE (refused)', sql: 'DELETE FROM bed WHERE bed_id = 101' },
  { label: 'Live holds with expiry', sql: "SELECT r.reservation_id, r.bed_id, r.hold_expires_at, sim_now() AS now_sim\n  FROM reservation r WHERE r.status = 'HELD'" },
  { label: 'Read the replica', sql: 'SELECT @@hostname, @@server_id, @@super_read_only, COUNT(*) AS beds FROM bed', target: 'replica' },
];

function TwoTabSwitch() {
  const { settings, setSetting } = useApp();
  return (
    <Seg value={settings.booking_mode} onChange={(v) => setSetting({ booking_mode: v })}
      options={[{ value: 'safe', label: 'Bookings lock rows' }, { value: 'unsafe', label: 'No lock', bad: true }]} />
  );
}

function CheckDemo() {
  const { openConsole } = useApp();
  return (
    <Demo no="8" title="Check it yourself" tags={['Read-only user', 'Privileges', 'EXPLAIN', 'Multiple instances']}
      what="The Ask view runs your own SQL as icu_readonly inside a READ ONLY transaction: MySQL itself decides what is allowed. Or book from two browser tabs at once."
      controls={<>
        {CHECKS.map((c) => <button key={c.label} className="btn sm" onClick={() => openConsole('query', { query: { sql: c.sql, target: c.target || 'primary' } })}>{c.label}</button>)}
        <a className="btn sm ghost" href="/console" target="_blank" rel="noreferrer">Open console in its own window</a>
        <a className="btn sm ghost" href="http://localhost:8001" target="_blank" rel="noreferrer">Open app-2 (second instance)</a>
      </>}>
      <div className="two-tabs">
        <div className="muted">Two-tab test: open the app twice (or on app-1 and app-2), turn the lock off here, and press Hold in both tabs within 2 seconds.</div>
        <TwoTabSwitch />
      </div>
    </Demo>
  );
}

const SCENARIOS = [
  { id: 'race', title: 'Race for the last bed', line: 'Two requests, one free bed', C: RaceDemo },
  { id: 'expiry', title: 'Holds expire', line: 'MySQL frees unconverted holds', C: ExpiryDemo },
  { id: 'deadlock', title: 'Deadlock', line: 'Two transfers wait on each other', C: CrossingDemo },
  { id: 'crash', title: 'Kill the database', line: 'A crash in the middle of a transfer', C: CrashDemo },
  { id: 'hoarding', title: 'Bed hoarding', line: 'A trigger stops it, an audit flags it', C: BlockingDemo },
  { id: 'replica', title: 'Replica lag', line: 'Two servers disagree for a moment', C: ReplicationDemo },
  { id: 'redis', title: 'Redis outage', line: 'The cache goes, bookings stay correct', C: RedisDemo },
  { id: 'yourself', title: 'Try it yourself', line: 'Your own SQL, two browser tabs', C: CheckDemo },
];

export default function ScenariosView() {
  const { scenario, setScenario } = useApp();
  const [busy, run] = useRun();
  const reset = () => run(async () => { const r = await post('/demo/reset'); toast(`Demo data reset (${r.statements} statements)`); });
  return (
    <div className="scen">
      <aside className="scen-index">
        <h1 className="h1">Scenarios</h1>
        <p className="muted scen-lede">Each one pushes the database somewhere it could go wrong. Pick one, run it, read the result.</p>
        <ol>
          {SCENARIOS.map((s, i) => (
            <li key={s.id}>
              <button type="button" className={scenario === s.id ? 'on' : ''} aria-current={scenario === s.id ? 'step' : undefined} onClick={() => setScenario(s.id)}>
                <span className="si-n">{i + 1}</span>
                <span><span className="si-t">{s.title}</span><span className="si-l">{s.line}</span></span>
              </button>
            </li>
          ))}
        </ol>
        <button type="button" className="linkbtn reset-link" disabled={busy} onClick={reset}>{busy ? 'Resetting...' : 'Reset demo data'}</button>
      </aside>
      <div className="scen-stage">
        {SCENARIOS.map((s) => <div key={s.id} hidden={scenario !== s.id}><s.C /></div>)}
      </div>
    </div>
  );
}
