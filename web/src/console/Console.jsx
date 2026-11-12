import { useEffect, useMemo, useRef, useState } from 'react';
import { useApp } from '../App.jsx';
import CountUp from '../components/reactbits/CountUp.jsx';
import { Dot, LiveTable, Pill, PlainTable, Seg, Sparkline, SqlText, Status, TxChip } from '../components/ui.jsx';
import { bytes, fmtTime, post, TYPE_LABEL } from '../lib/api.js';
import { usePoll, useNow } from '../lib/hooks.js';
import { clearSql, live } from '../lib/live.js';
import { useStore } from '../lib/store.js';
import WaitForGraph, { deadlockEdges } from './Graph.jsx';

const TABS = [
  ['tables', 'Tables'], ['sql', 'SQL log'], ['xray', 'X-Ray'], ['redis', 'Redis'], ['metrics', 'Metrics'], ['query', 'Query'],
];

// ------------------------------------------------------------------ header strip
export function useMetrics(active = true) {
  return usePoll('/metrics', 1000, { onEvents: false, active });
}

// The database as the patient: six vitals traced on ECG chart paper.
export function Vitals({ m }) {
  const my = m?.mysql || {};
  const rp = m?.replica || {};
  const rd = m?.redis || {};
  const h = m?.history || {};
  const INK = '#13202b';
  const BLUE = '#1f4fd1';
  const RED = '#d23a4a';
  const cells = [
    { k: 'Queries per second', v: my.rates?.qps, s: h.qps, c: INK },
    { k: 'Transactions per second', v: my.tps, s: h.tps, c: BLUE },
    { k: 'Rows waiting on a lock', v: my.row_lock_current_waits, s: h.lock_waits, c: INK, bad: my.row_lock_current_waits > 0 },
    { k: 'Deadlocks since start', v: my.deadlocks_total, s: h.deadlocks, c: RED },
    { k: 'Replica behind by', v: rp.lag_ms, unit: 'ms', s: h.replica_lag_ms, c: BLUE, bad: rp.lag_ms > 1500 },
    { k: 'Redis commands per second', v: rd.ops, s: h.redis_ops, c: INK },
  ];
  return (
    <div className="vitals ecg">
      {cells.map((c) => (
        <div key={c.k} className="vital">
          <div className="vk" style={{ color: c.c === RED ? RED : 'var(--muted)' }}>{c.k}</div>
          <div className={`vv ${c.bad ? 'bad' : ''}`}>{c.v == null ? '-' : Math.round(c.v * 10) / 10}{c.unit && <small>{c.unit}</small>}</div>
          <Sparkline points={(c.s || []).slice(-50)} color={c.c} height={30} />
        </div>
      ))}
    </div>
  );
}

export function Infra() {
  const health = useStore(live, (s) => s.health);
  const sockets = useStore(live, (s) => s.sockets);
  const instances = useStore(live, (s) => s.instances);
  const h = health[instances[0]?.name] || Object.values(health)[0] || {};
  return (
    <div className="infra">
      <span><Dot state={h.mysql} />primary</span>
      <span><Dot state={h.replica} />replica</span>
      <span><Dot state={h.redis} />redis</span>
      {instances.map((i) => <span key={i.name}><Dot state={sockets[i.name] === 'open'} />{i.name}</span>)}
    </div>
  );
}

// ------------------------------------------------------------------ tables
const TABLE_GROUPS = [
  ['Core', ['bed', 'reservation', 'bed_request', 'patient', 'transfer', 'audit_log']],
  ['Reference', ['hospital', 'bed_type', 'user_account']],
  ['Views', ['v_bed_board', 'v_hold_conversion']],
  ['System', ['sim_clock', 'replication_probe']],
];

export function TablesTab() {
  const { tableName, setTableName, tableSource, setTableSource } = useApp();
  const [filter, setFilter] = useState('');
  const { data, error } = usePoll(`/tables/${tableName}?source=${tableSource}`, 1000, { deps: [tableName, tableSource] });
  const rows = useMemo(() => {
    const all = data?.name === tableName && data?.source === tableSource ? data.rows : [];
    if (!filter) return all;
    const f = filter.toLowerCase();
    return all.filter((r) => Object.values(r).some((v) => String(v ?? '').toLowerCase().includes(f)));
  }, [data, filter, tableName, tableSource]);
  return (
    <>
      <div className="console-tools">
        <select className="select sm" style={{ width: 180 }} value={tableName} onChange={(e) => setTableName(e.target.value)}>
          {TABLE_GROUPS.map(([g, list]) => <optgroup key={g} label={g}>{list.map((t) => <option key={t}>{t}</option>)}</optgroup>)}
        </select>
        <Seg size="sm" value={tableSource} onChange={setTableSource} options={[{ value: 'primary', label: 'Primary' }, { value: 'replica', label: 'Replica' }]} />
        <input className="input" style={{ height: 28, width: 150 }} placeholder="Filter rows" value={filter} onChange={(e) => setFilter(e.target.value)} />
        <span className="grow" />
        <span className="muted mono" style={{ fontSize: 11 }}>{data ? `${data.total} rows${data.total > data.rows.length ? `, showing ${data.rows.length}` : ''}` : ''}</span>
      </div>
      {error && <div className="verdict bad">{error.message}</div>}
      {data && data.name === tableName && <LiveTable columns={data.columns} rows={rows} pk={data.pk} maxHeight="calc(100vh - 250px)" />}
      <div className="row" style={{ gap: 12, marginTop: 8, fontSize: 11.5 }}>
        <span className="row" style={{ gap: 5 }}><i style={{ width: 10, height: 10, background: '#c9ecd5', borderRadius: 2 }} />inserted</span>
        <span className="row" style={{ gap: 5 }}><i style={{ width: 10, height: 10, background: '#fbe3b4', borderRadius: 2 }} />updated cell</span>
        <span className="row" style={{ gap: 5 }}><i style={{ width: 10, height: 10, background: '#f6cdc8', borderRadius: 2 }} />deleted</span>
        <span className="faint">refreshes every second and on every change event</span>
      </div>
    </>
  );
}

// ------------------------------------------------------------------ SQL log
export function SqlTab() {
  const sql = useStore(live, (s) => s.sql);
  const instances = useStore(live, (s) => s.instances);
  const { txFilter } = useApp();
  const [q, setQ] = useState(txFilter || '');
  useEffect(() => { if (txFilter) setQ(txFilter); }, [txFilter]);
  const [inst, setInst] = useState('all');
  const [hideSys, setHideSys] = useState(false);
  const [paused, setPaused] = useState(false);
  const [frozen, setFrozen] = useState(null);
  const box = useRef(null);
  const stick = useRef(true);
  const now = useNow(250);
  const list = useMemo(() => {
    let l = paused && frozen ? frozen : sql;
    if (inst !== 'all') l = l.filter((e) => e.instance === inst);
    if (hideSys) l = l.filter((e) => e.kind !== 'NOTE' && e.kind !== 'REDIS');
    if (q && /^\d?T\d+$/.test(q.trim())) l = l.filter((e) => e.tx === q.trim());
    else if (q) { const f = q.toLowerCase(); l = l.filter((e) => `${e.sql} ${e.tx} ${e.label}`.toLowerCase().includes(f)); }
    return l.slice(-300);
  }, [sql, q, inst, hideSys, paused, frozen]);
  useEffect(() => {
    const el = box.current;
    if (el && stick.current) el.scrollTop = el.scrollHeight;
  }, [list]);
  const onScroll = () => {
    const el = box.current;
    if (el) stick.current = el.scrollHeight - el.scrollTop - el.clientHeight < 40;
  };
  return (
    <>
      <div className="console-tools">
        <input className="input" style={{ height: 28, width: 170 }} placeholder="Search SQL, T12, label" value={q} onChange={(e) => setQ(e.target.value)} />
        <select className="select sm" style={{ width: 110 }} value={inst} onChange={(e) => setInst(e.target.value)}>
          <option value="all">all instances</option>
          {instances.map((i) => <option key={i.name}>{i.name}</option>)}
        </select>
        <label className="check"><input type="checkbox" checked={hideSys} onChange={(e) => setHideSys(e.target.checked)} />SQL only</label>
        <span className="grow" />
        <button className="btn sm" onClick={() => { setPaused(!paused); setFrozen(paused ? null : sql); }}>{paused ? 'Resume' : 'Pause'}</button>
        <button className="btn sm ghost" onClick={() => { clearSql(); setFrozen(null); }}>Clear</button>
      </div>
      <div className="tbl-wrap" ref={box} onScroll={onScroll} style={{ maxHeight: 'calc(100vh - 230px)' }}>
        <div className="sqllog">
          {list.length === 0 && <div className="empty">Nothing yet. Book a bed or run a demo; every statement the backend sends to MySQL (and every Redis command) appears here.</div>}
          {list.map((e) => {
            const running = e.phase === 'start';
            const ms = running ? (now / 1000 - e.ts) * 1000 : e.ms;
            return (
              <div key={e.seq} className={`sq ${e.kind} ${e.ok === false ? 'error' : ''} ${running ? 'running' : ''}`}>
                <span className="ts">{fmtTime(e.ts)}</span>
                <div style={{ minWidth: 0 }}>
                  <div className="meta">
                    <TxChip tx={e.tx} /><span>{e.label}</span>
                    {e.conn && <span className="faint">conn {e.conn}</span>}
                    {e.target === 'replica' && <Pill kind="info">replica</Pill>}
                    {instances.length > 1 && <span className="faint">{e.instance}</span>}
                  </div>
                  <div className="code"><SqlText sql={e.sql} /></div>
                  {e.error && <div className="errline">{e.error}</div>}
                </div>
                <span className={`ms ${ms > 500 ? 'slow' : ''}`}>
                  {running ? `running ${Math.round(ms)} ms` : `${e.ms} ms`}
                  {!running && e.rows != null && <div>{e.rows} row{e.rows === 1 ? '' : 's'}</div>}
                </span>
              </div>
            );
          })}
        </div>
      </div>
    </>
  );
}

// ------------------------------------------------------------------ X-Ray
export function XrayTab() {
  const { data, error } = usePoll('/xray', 400, { onEvents: false });
  const trx = data?.transactions || [];
  const locks = (data?.locks || []).filter((l) => l.type === 'RECORD' || l.status === 'WAITING');
  const g = deadlockEdges(data?.deadlock);
  return (
    <div className="xray-grid">
      {error && <div className="verdict bad">{error.message}</div>}
      <div>
        <div className="section-title"><h2 style={{ fontSize: 15 }}>Active transactions</h2><p className="mono" style={{ fontSize: 11 }}>information_schema.INNODB_TRX</p></div>
        <PlainTable rows={trx} columns={[
          { key: 'tx', label: 'tx', render: (r) => <TxChip tx={r.tx} /> },
          { key: 'label', label: 'who' },
          { key: 'trx_state', label: 'state', render: (r) => <Pill kind={r.trx_state === 'LOCK WAIT' ? 'err' : 'info'}>{r.trx_state}</Pill> },
          { key: 'age_s', label: 'age', render: (r) => `${r.age_s.toFixed(1)} s` },
          { key: 'trx_rows_locked', label: 'rows locked' },
          { key: 'trx_rows_modified', label: 'rows modified' },
          { key: 'trx_query', label: 'running now', render: (r) => <span title={r.trx_query}>{r.trx_query || 'idle in transaction'}</span> },
        ]} />
      </div>
      <div>
        <div className="section-title"><h2 style={{ fontSize: 15 }}>Wait-for graph</h2><p className="mono" style={{ fontSize: 11 }}>performance_schema.data_lock_waits</p></div>
        <WaitForGraph nodes={trx.map((t) => t.tx)} edges={data?.waits || []} labels={Object.fromEntries(trx.map((t) => [t.tx, t.label.slice(0, 28)]))} />
      </div>
      <div>
        <div className="section-title"><h2 style={{ fontSize: 15 }}>Row locks</h2><p className="mono" style={{ fontSize: 11 }}>performance_schema.data_locks</p></div>
        <PlainTable rows={locks} columns={[
          { key: 'tx', label: 'tx', render: (r) => <TxChip tx={r.tx} /> }, 'tbl', 'idx',
          { key: 'mode', label: 'mode' },
          { key: 'status', label: 'status', render: (r) => <Pill kind={r.status === 'WAITING' ? 'err' : 'ok'}>{r.status}</Pill> },
          { key: 'data', label: 'locked row' },
        ]} />
      </div>
      <div>
        <div className="section-title"><h2 style={{ fontSize: 15 }}>Latest deadlock</h2><p className="mono" style={{ fontSize: 11 }}>SHOW ENGINE INNODB STATUS</p></div>
        {!data?.deadlock ? <div className="empty">No deadlock since MySQL started. Run demo 3 in request order.</div> : (
          <div className="dl-card">
            <div className="row"><Pill kind="err">DEADLOCK</Pill><span className="mono" style={{ fontSize: 11.5 }}>{data.deadlock.when}</span>
              <span className="muted">InnoDB rolled back transaction ({data.deadlock.victim})</span></div>
            <div style={{ marginTop: 8 }}><WaitForGraph nodes={g.nodes} edges={g.edges} victim={g.victim} labels={g.labels} /></div>
            <div className="dl-tx">
              {data.deadlock.transactions.map((t) => (
                <div key={t.n} className={t.n === data.deadlock.victim ? 'victim' : ''}>
                  <div className="row"><b>({t.n})</b>{t.tx && <TxChip tx={t.tx} />}<span className="mono faint">trx {t.trx_id}, thread {t.thread_id}</span></div>
                  <div className="mono" style={{ fontSize: 11, margin: '4px 0', wordBreak: 'break-word' }}>{t.query}</div>
                  {t.holds && <div>holds <b>{t.holds.mode}</b> on {t.holds.table}.{t.holds.index} row <b className="mono">{t.holds.record}</b></div>}
                  {t.waits_for && <div>waits for <b>{t.waits_for.mode}</b> on row <b className="mono">{t.waits_for.record}</b></div>}
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

// ------------------------------------------------------------------ Redis
export function RedisTab() {
  const { data } = usePoll('/redis', 2000);
  const events = useStore(live, (s) => s.events);
  const [busy, setBusy] = useState(false);
  if (data && !data.up) return <div className="verdict bad">Redis is down. The app is using MySQL for search and dashboards.</div>;
  return (
    <div className="stack">
      <div className="row">
        <Pill kind={data?.all_match ? 'ok' : 'err'}>{data?.all_match ? 'every counter matches MySQL' : 'counters differ from MySQL'}</Pill>
        <span className="grow" />
        <button className="btn sm" disabled={busy} onClick={async () => { setBusy(true); try { await post('/redis/rebuild'); } finally { setBusy(false); } }}>Rebuild from MySQL</button>
      </div>
      <div>
        <div className="section-title"><h2 style={{ fontSize: 15 }}>Pub/sub channel <span className="mono">events</span></h2><p>newest first</p></div>
        <div className="tbl-wrap" style={{ maxHeight: 220 }}>
          <div className="sqllog">
            {events.slice(0, 40).map((e, i) => {
              const d = e.data || {};
              return (
                <div key={d.id || i} className="sq REDIS" style={{ gridTemplateColumns: '64px 1fr auto' }}>
                  <span className="ts">{fmtTime(d.ts)}</span>
                  <div className="code" style={{ color: 'var(--ink-2)' }}>
                    <b>{d.kind === 'audit' ? d.action : d.kind}</b>{' '}
                    {d.kind === 'audit' ? `${d.entity} ${d.entity_id ?? ''}${d.by ? `, by ${d.by}` : ''}` : Object.entries(d).filter(([k]) => !['kind', 'id', 'ts', 'origin'].includes(k) && d[k] != null).map(([k, v]) => `${k}=${typeof v === 'object' ? JSON.stringify(v) : v}`).join(' ')}
                  </div>
                  <span className="ms">{e.via}</span>
                </div>
              );
            })}
            {!events.length && <div className="empty">No events yet</div>}
          </div>
        </div>
      </div>
      <div>
        <div className="section-title"><h2 style={{ fontSize: 15 }}>Free-bed counters</h2><p className="mono">free:hospital:type vs SELECT COUNT(*) in MySQL</p></div>
        <PlainTable rows={data?.counters || []} maxHeight={260} highlight={(r) => !r.match} columns={[
          'key', { key: 'bed_type_id', label: 'type', render: (r) => TYPE_LABEL[r.bed_type_id] }, 'redis', 'mysql',
          { key: 'match', label: '', render: (r) => (r.match ? <Pill kind="ok">match</Pill> : <Pill kind="err">stale</Pill>) },
        ]} />
      </div>
      <div>
        <div className="section-title"><h2 style={{ fontSize: 15 }}>GEO set <span className="mono">hospitals:geo</span></h2></div>
        <PlainTable rows={data?.geo || []} columns={['member', 'lon', 'lat']} />
      </div>
    </div>
  );
}

// ------------------------------------------------------------------ Metrics
export function Topology({ m }) {
  const health = useStore(live, (s) => s.health);
  const sockets = useStore(live, (s) => s.sockets);
  const instances = useStore(live, (s) => s.instances);
  const h = Object.values(health)[0] || {};
  const rp = m?.replica || {};
  const col = (ok) => (ok === false ? '#d23a4a' : ok ? '#13202b' : '#96a4b0');
  const box = (x, y, w, title, sub, ok, key) => (
    <g key={key}>
      <rect x={x} y={y} width={w} height="46" rx="7" fill="#fff" stroke={col(ok)} strokeWidth="1.4" />
      <circle cx={x + 13} cy={y + 15} r="3.5" fill={col(ok)} />
      <text x={x + 23} y={y + 19} fontSize="11.5" fontWeight="600" fill="#13202b" fontFamily="Barlow">{title}</text>
      <text x={x + 12} y={y + 36} fontSize="10" fill="#627485" fontFamily="Geist Mono">{sub}</text>
    </g>
  );
  const apps = instances.length ? instances : [{ name: 'app-1' }];
  return (
    <svg className="topo" viewBox="0 0 560 196" role="img" aria-label="System topology">
      <defs><marker id="tp-a" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse"><path d="M0 0L10 5L0 10z" fill="#96a4b0" /></marker></defs>
      {box(10, 75, 92, 'Browser', 'WebSocket x' + apps.length, true, 'b')}
      {apps.slice(0, 2).map((a, i) => box(150, 30 + i * 90, 120, a.name, 'FastAPI :' + (8000 + i), sockets[a.name] === 'open', a.name))}
      {box(330, 10, 220, 'MySQL primary', `InnoDB, server ${m?.mysql?.server_id ?? '?'}, binlog+GTID`, h.mysql, 'p')}
      {box(330, 94, 220, 'MySQL replica', `lag ${rp.lag_ms ?? '?'} ms, apply ${rp.sql_running === 'Yes' ? 'on' : 'off'}`, h.replica && rp.sql_running === 'Yes', 'r')}
      {box(330, 146, 220, 'Redis 7', `${m?.redis?.keys ?? '?'} keys, ${m?.redis?.used_memory ?? ''}`, h.redis, 'd')}
      <g stroke="#96a4b0" strokeWidth="1.2" fill="none">
        <path d="M102 98H126V53H150" markerEnd="url(#tp-a)" />
        {apps.length > 1 && <path d="M126 98V143H150" markerEnd="url(#tp-a)" />}
        <path d="M270 53H300V33H330" markerEnd="url(#tp-a)" />
        <path d="M270 53H300V169H330" markerEnd="url(#tp-a)" />
        {apps.length > 1 && <path d="M270 143H300" />}
        <path d="M440 56V94" strokeDasharray="4 3" markerEnd="url(#tp-a)" />
      </g>
      <text x="446" y="80" fontSize="9.5" fill="#627485" fontFamily="Geist Mono">binlog</text>
    </svg>
  );
}

function MCard({ k, v, unit, s, points, color, max }) {
  return (
    <div className="mcard">
      <div className="k">{k}</div>
      <div className="v">{typeof v === 'number' ? <CountUp to={v} from={v} duration={0.4} decimals={Number.isInteger(v) ? 0 : 1} trigger="load" /> : (v ?? '-')}{unit && <small> {unit}</small>}</div>
      {s && <div className="s">{s}</div>}
      {points && <Sparkline points={points} color={color} max={max} />}
    </div>
  );
}

export function MetricsTab() {
  const { data: m } = useMetrics();
  const my = m?.mysql || {};
  const rp = m?.replica || {};
  const rd = m?.redis || {};
  const h = m?.history || {};
  return (
    <div className="stack">
      <Topology m={m} />
      <div className="section-title"><h2 style={{ fontSize: 15 }}>MySQL primary</h2><p>SHOW GLOBAL STATUS, INNODB_METRICS, uptime {my.uptime_s ?? '-'} s, {my.isolation}</p></div>
      <div className="mcards">
        <MCard k="Queries per second" v={my.rates?.qps} points={h.qps} color="#13202b" s="includes this console's own polling" />
        <MCard k="Transactions per second" v={my.tps} points={h.tps} color="#13202b" s={`${my.commits_total ?? '-'} commits, ${my.rollbacks_total ?? '-'} rollbacks`} />
        <MCard k="Rows read per second" v={my.rates?.rows_read} points={h.rows_read} color="#13202b" />
        <MCard k="Rows written per second" v={my.rates?.rows_written} points={h.rows_written} color="#13202b" s="inserted + updated + deleted" />
        <MCard k="Buffer pool hit ratio" v={my.hit_ratio} unit="%" points={h.hit_ratio} color="#13202b" max={100} s={`${my.buffer_pool_used_pct ?? '-'}% of pages used, ${my.dirty_pages ?? '-'} dirty`} />
        <MCard k="Row lock waits" v={my.row_lock_waits_total} s={`${my.row_lock_current_waits ?? 0} waiting now, ${my.row_lock_time_ms ?? 0} ms waited`} points={h.lock_waits} color="#13202b" />
        <MCard k="Deadlocks detected" v={my.deadlocks_total} s={`${my.lock_timeouts_total ?? 0} lock wait timeouts`} points={h.deadlocks} color="#d23a4a" />
        <MCard k="History list length" v={my.history_list_length} s="undo records waiting for purge (MVCC)" />
        <MCard k="Connections" v={my.threads_connected} s={`${my.threads_running ?? 0} running, max used ${my.max_used_connections ?? '-'}`} points={h.threads_running} color="#13202b" />
        <MCard k="Network" v={bytes(my.bytes_in)} s={`in, ${bytes(my.bytes_out)} out`} />
      </div>
      <div className="section-title"><h2 style={{ fontSize: 15 }}>Replication</h2><p>SHOW REPLICA STATUS on icu_mysql_replica</p></div>
      <div className="mcards">
        <MCard k="Replica lag" v={rp.lag_ms} unit="ms" points={h.replica_lag_ms} color="#13202b" s={`Seconds_Behind_Source ${rp.seconds_behind ?? '-'}`} />
        <MCard k="Threads" v={`${rp.io_running === 'Yes' ? 'IO on' : 'IO off'}, ${rp.sql_running === 'Yes' ? 'SQL on' : 'SQL off'}`} s={`source ${rp.source || '-'}, super_read_only ${rp.super_read_only ? 'ON' : 'OFF'}`} />
        <div className="mcard" style={{ gridColumn: 'span 2' }}>
          <div className="k">GTID executed</div>
          <div className="mono" style={{ fontSize: 11, wordBreak: 'break-all', marginTop: 4 }}>primary: {my.gtid}</div>
          <div className="mono" style={{ fontSize: 11, wordBreak: 'break-all', marginTop: 2 }}>replica: {rp.executed_gtid}</div>
          {rp.last_error && <div className="errline" style={{ color: 'var(--danger)' }}>{rp.last_error}</div>}
        </div>
      </div>
      <div className="section-title"><h2 style={{ fontSize: 15 }}>Redis</h2><p>INFO</p></div>
      <div className="mcards">
        <MCard k="Ops per second" v={rd.ops} points={h.redis_ops} color="#13202b" />
        <MCard k="Memory" v={rd.used_memory} s={`${rd.keys ?? '-'} keys, ${rd.clients ?? '-'} clients`} />
        <MCard k="Keyspace hit ratio" v={rd.hit_ratio} unit="%" s={`${rd.commands_total ?? '-'} commands since start`} />
      </div>
      <div className="section-title"><h2 style={{ fontSize: 15 }}>Table sizes</h2><p>information_schema.TABLES + COUNT(*)</p></div>
      <PlainTable rows={m?.tables || []} columns={['name', 'rows', { key: 'data_bytes', label: 'data', render: (r) => bytes(r.data_bytes) }, { key: 'index_bytes', label: 'indexes', render: (r) => bytes(r.index_bytes) }]} />
    </div>
  );
}

// ------------------------------------------------------------------ Query
const SAMPLES = [
  ['Free beds by hospital and type', "SELECT h.name, t.name AS bed_type, COUNT(*) AS free\n  FROM bed b JOIN hospital h USING (hospital_id) JOIN bed_type t USING (bed_type_id)\n WHERE b.status = 'FREE'\n GROUP BY h.name, t.name\n ORDER BY h.name"],
  ['Live holds and time left', "SELECT reservation_id, bed_id, hold_expires_at,\n       TIMESTAMPDIFF(SECOND, sim_now(), hold_expires_at) AS seconds_left\n  FROM reservation WHERE status = 'HELD'"],
  ['EXPLAIN the booking search', "EXPLAIN SELECT bed_id FROM bed\n WHERE bed_type_id = 2 AND status = 'FREE' AND hospital_id = 1\n ORDER BY bed_id LIMIT 1"],
  ['Hold conversion audit', 'SELECT * FROM v_hold_conversion ORDER BY failure_pct DESC'],
  ['Last 20 audit entries', 'SELECT log_id, user_id, action, entity_name, entity_id, details, created_at\n  FROM audit_log ORDER BY log_id DESC LIMIT 20'],
  ['Indexes on bed', 'SHOW INDEX FROM bed'],
  ['Triggers', 'SELECT TRIGGER_NAME, ACTION_TIMING, EVENT_MANIPULATION, EVENT_OBJECT_TABLE\n  FROM information_schema.TRIGGERS WHERE TRIGGER_SCHEMA = DATABASE()'],
  ['Try a write (refused)', "UPDATE bed SET status = 'FREE' WHERE bed_id = 101"],
];

export function QueryTab() {
  const { queryText } = useApp();
  const [sql, setSql] = useState(SAMPLES[0][1]);
  const [target, setTarget] = useState('primary');
  const [res, setRes] = useState(null);
  const [busy, setBusy] = useState(false);
  const run = async (text = sql, tgt = target) => {
    setBusy(true);
    try { setRes(await post('/query', { sql: text, target: tgt })); } catch (e) { setRes({ ok: false, error: e.message }); } finally { setBusy(false); }
  };
  useEffect(() => {
    if (queryText?.sql) { setSql(queryText.sql); setTarget(queryText.target || 'primary'); run(queryText.sql, queryText.target || 'primary'); }
  }, [queryText?.at]); // eslint-disable-line react-hooks/exhaustive-deps
  return (
    <div className="stack">
      <div className="console-tools" style={{ marginBottom: 0 }}>
        <select className="select sm" style={{ width: 230 }} value="" onChange={(e) => { const s = SAMPLES.find((x) => x[0] === e.target.value); if (s) setSql(s[1]); }}>
          <option value="">Sample queries...</option>
          {SAMPLES.map(([n]) => <option key={n}>{n}</option>)}
        </select>
        <Seg size="sm" value={target} onChange={setTarget} options={[{ value: 'primary', label: 'Primary' }, { value: 'replica', label: 'Replica' }]} />
        <span className="grow" />
        <span className="muted" style={{ fontSize: 11.5 }}>user <span className="mono">icu_readonly</span>, READ ONLY transaction</span>
      </div>
      <textarea className="textarea mono" rows={6} value={sql} spellCheck={false} style={{ fontSize: 12 }}
        onChange={(e) => setSql(e.target.value)} onKeyDown={(e) => { if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) run(); }} />
      <div className="row"><button className="btn primary" disabled={busy} onClick={() => run()}>Run <span className="kbd">Ctrl+Enter</span></button>
        {res?.ok && <span className="muted">{res.count} row(s)</span>}</div>
      {res && !res.ok && (
        <div className="verdict bad" style={{ display: 'block' }}>
          <div>MySQL {res.code}: <span className="mono" style={{ fontWeight: 400 }}>{res.error}</span></div>
          {res.meaning && <div style={{ fontWeight: 400, marginTop: 3 }}>{res.meaning}.</div>}
        </div>
      )}
      {res?.ok && <PlainTable columns={res.columns} rows={res.rows} maxHeight="calc(100vh - 470px)" />}
    </div>
  );
}

// ------------------------------------------------------------------ shell
export default function Console({ onCollapse, standalone }) {
  const { consoleTab, setConsoleTab } = useApp();
  const sqlCount = useStore(live, (s) => s.sql.length);
  const { data: m } = useMetrics(true);
  return (
    <aside className="console">
      <div className="console-head">
        <span className="title">Database monitor</span>
        <span className="live-tag"><i className="dot" />live</span>
        <span className="grow" />
        <Infra />
        {!standalone && <a className="btn sm ghost" href="/console" target="_blank" rel="noreferrer" title="Open in its own window">Pop out</a>}
        {onCollapse && <button className="btn sm ghost" onClick={onCollapse} title="Collapse">⟩</button>}
      </div>
      <Vitals m={m} />
      <nav className="tabs small">
        {TABS.map(([k, label]) => (
          <button key={k} className={`tab ${consoleTab === k ? 'active' : ''}`} onClick={() => setConsoleTab(k)}>
            {label}{k === 'sql' && <span className="count">{sqlCount}</span>}
          </button>
        ))}
      </nav>
      <div className="console-body">
        {consoleTab === 'tables' && <TablesTab />}
        {consoleTab === 'sql' && <SqlTab />}
        {consoleTab === 'xray' && <XrayTab />}
        {consoleTab === 'redis' && <RedisTab />}
        {consoleTab === 'metrics' && <MetricsTab />}
        {consoleTab === 'query' && <QueryTab />}
      </div>
    </aside>
  );
}
