import { useEffect, useMemo, useRef, useState } from 'react';
import ClickSpark from './reactbits/ClickSpark.jsx';
import SpotlightCard from './reactbits/SpotlightCard.jsx';

// Card surface with a faint React Bits spotlight that follows the pointer.
export function Panel({ children, className = '', style, ...rest }) {
  return (
    <SpotlightCard theme="light" spotlightColor="#0f5f4b" intensity={0.06} spotlightSize={340} borderGlow={0.3}
      flare={false} className={`spot ${className}`} style={{ padding: 0, borderRadius: 8, ...style }} {...rest}>
      {children}
    </SpotlightCard>
  );
}

export function Pill({ children, kind, className = '' }) {
  return <span className={`pill ${kind || ''} ${className}`}>{children}</span>;
}

export function Status({ value }) {
  return <Pill kind={value}>{value}</Pill>;
}

export function Dot({ state }) {
  return <i className={`dot ${state === true ? 'up' : state === false ? 'down' : state || ''}`} />;
}

export function Seg({ value, options, onChange, full, size }) {
  return (
    <div className={`seg ${full ? 'full' : ''}`} role="radiogroup">
      {options.map((o) => (
        <button key={String(o.value)} type="button" role="radio" aria-checked={value === o.value}
          className={`${value === o.value ? 'on' : ''} ${o.bad ? 'bad' : ''}`} title={o.title}
          style={size === 'sm' ? { padding: '3px 8px' } : undefined}
          onClick={() => onChange(o.value)}>{o.label}</button>
      ))}
    </div>
  );
}

// Primary action with a small React Bits spark on click.
export function ActionButton({ children, className = 'btn primary', spark = '#0f5f4b', ...props }) {
  return (
    <ClickSpark sparkColor={spark} sparkSize={7} sparkRadius={16} sparkCount={7} duration={380}
      style={{ display: 'inline-flex' }}>
      <button type="button" className={className} {...props}>{children}</button>
    </ClickSpark>
  );
}

// ---------------------------------------------------------------- SQL highlighting
const KW = new Set(('SELECT FROM WHERE AND OR NOT INSERT INTO VALUES UPDATE SET DELETE JOIN LEFT ON AS IN IS NULL ' +
  'ORDER BY GROUP HAVING LIMIT FOR SKIP LOCKED NOWAIT COUNT SUM CASE WHEN THEN ELSE END INTERVAL MINUTE SECOND ' +
  'DISTINCT EXPLAIN SHOW STATUS DESC ASC CROSS UNION ALL READ ONLY SESSION MAX_EXECUTION_TIME STOP START REPLICA ' +
  'SQL_THREAD JSON_OBJECT TRUNCATE TABLE GEOSEARCH FROMLONLAT BYRADIUS WITHDIST MGET GEOADD').split(' '));
const TXKW = new Set(['START', 'TRANSACTION', 'COMMIT', 'ROLLBACK', 'BEGIN']);
const TOKEN = /('(?:[^'\\]|\\.)*')|(--[^\n]*)|(\b\d+(?:\.\d+)?\b)|([A-Za-z_][A-Za-z0-9_]*)|(\s+)|(.)/g;

export function SqlText({ sql }) {
  const parts = useMemo(() => {
    const out = [];
    let m;
    let i = 0;
    TOKEN.lastIndex = 0;
    const text = String(sql || '');
    while ((m = TOKEN.exec(text)) !== null) {
      const [tok, str, cm, num, word] = m;
      if (str) out.push(<span key={i++} className="str">{tok}</span>);
      else if (cm) out.push(<span key={i++} className="cm">{tok}</span>);
      else if (num) out.push(<span key={i++} className="numl">{tok}</span>);
      else if (word && TXKW.has(word.toUpperCase())) out.push(<span key={i++} className="kw tx">{tok}</span>);
      else if (word && KW.has(word.toUpperCase())) out.push(<span key={i++} className="kw">{tok}</span>);
      else out.push(tok);
    }
    return out;
  }, [sql]);
  return <>{parts}</>;
}

// ---------------------------------------------------------------- sparkline
export function Sparkline({ points, color = '#0f5f4b', height = 30, max }) {
  const vals = (points || []).map((p) => (p && p[1] != null ? Number(p[1]) : null));
  const w = 160;
  const nums = vals.filter((v) => v != null);
  const top = max ?? Math.max(1, ...nums);
  const lo = 0;
  const step = vals.length > 1 ? w / (vals.length - 1) : w;
  let d = '';
  vals.forEach((v, i) => {
    if (v == null) return;
    const x = i * step;
    const y = height - 2 - ((v - lo) / (top - lo || 1)) * (height - 4);
    d += `${d ? 'L' : 'M'}${x.toFixed(1)} ${y.toFixed(1)}`;
  });
  const area = d ? `${d}L${((vals.length - 1) * step).toFixed(1)} ${height}L0 ${height}Z` : '';
  return (
    <svg className="spark" viewBox={`0 0 ${w} ${height}`} preserveAspectRatio="none" aria-hidden="true">
      {area && <path d={area} fill={color} opacity="0.08" />}
      {d && <path d={d} fill="none" stroke={color} strokeWidth="1.4" vectorEffect="non-scaling-stroke" />}
    </svg>
  );
}

// ---------------------------------------------------------------- live data table
function cell(v) {
  if (v === null || v === undefined) return { text: 'NULL', null: true };
  if (typeof v === 'object') return { text: JSON.stringify(v) };
  const s = String(v);
  return { text: /^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d/.test(s) ? s.replace('T', ' ').slice(0, 19) : s };
}

const STATUS_COLS = new Set(['status', 'trx_state', 'LOCK_STATUS']);

// Rows are compared with the previous render by primary key: new rows flash green,
// changed cells flash amber, removed rows flash red and fade out.
export function LiveTable({ columns, rows, pk, maxHeight, highlight }) {
  const prev = useRef(null);
  const versions = useRef(new Map());
  const [gone, setGone] = useState([]);
  const marks = useMemo(() => {
    const out = new Map();
    const before = prev.current;
    if (before) {
      const nowKeys = new Set();
      for (const r of rows) {
        const k = String(r[pk]);
        nowKeys.add(k);
        const old = before.get(k);
        if (!old) { out.set(k, { kind: 'ins' }); versions.current.set(k, (versions.current.get(k) || 0) + 1); }
        else {
          const changed = columns.filter((c) => JSON.stringify(old[c]) !== JSON.stringify(r[c]));
          if (changed.length) { out.set(k, { kind: 'upd', cols: new Set(changed) }); versions.current.set(k, (versions.current.get(k) || 0) + 1); }
        }
      }
      const removed = [...before.entries()].filter(([k]) => !nowKeys.has(k)).map(([, r]) => r);
      if (removed.length) setTimeout(() => setGone((g) => [...removed.map((r) => ({ r, t: Date.now() })), ...g].slice(0, 12)), 0);
    }
    prev.current = new Map(rows.map((r) => [String(r[pk]), r]));
    return out;
  }, [rows, pk, columns]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (!gone.length) return undefined;
    const t = setTimeout(() => setGone((g) => g.filter((x) => Date.now() - x.t < 2400)), 2500);
    return () => clearTimeout(t);
  }, [gone]);

  return (
    <div className="tbl-wrap" style={{ maxHeight }}>
      <table className="tbl">
        <thead><tr>{columns.map((c) => <th key={c}>{c}</th>)}</tr></thead>
        <tbody>
          {gone.map(({ r, t }) => (
            <tr key={`gone-${r[pk]}-${t}`} className="del">{columns.map((c) => <td key={c}>{cell(r[c]).text}</td>)}</tr>
          ))}
          {rows.map((r) => {
            const k = String(r[pk]);
            const m = marks.get(k);
            const flagged = highlight && highlight(r);
            return (
              <tr key={`${k}:${versions.current.get(k) || 0}`} className={`${m ? m.kind : ''} ${flagged ? 'flag' : ''}`}>
                {columns.map((c) => {
                  const v = cell(r[c]);
                  const isStatus = STATUS_COLS.has(c) && !v.null;
                  return (
                    <td key={c} className={`${v.null ? 'null' : ''} ${m?.kind === 'upd' && m.cols.has(c) ? 'changed' : ''}`} title={v.text}>
                      {isStatus ? <Pill kind={v.text}>{v.text}</Pill> : v.text}
                    </td>
                  );
                })}
              </tr>
            );
          })}
        </tbody>
      </table>
      {!rows.length && <div className="empty">No rows</div>}
    </div>
  );
}

// Static table for query results and small lists
export function PlainTable({ columns, rows, maxHeight, highlight }) {
  return (
    <div className="tbl-wrap" style={{ maxHeight }}>
      <table className="tbl">
        <thead><tr>{columns.map((c) => <th key={c.key || c}>{c.label || c}</th>)}</tr></thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i} className={highlight && highlight(r) ? 'flag' : ''}>
              {columns.map((c) => {
                const key = c.key || c;
                const val = c.render ? c.render(r) : cell(r[key]).text;
                return <td key={key} className={r[key] === null && !c.render ? 'null' : ''}>{val}</td>;
              })}
            </tr>
          ))}
        </tbody>
      </table>
      {!rows.length && <div className="empty">No rows</div>}
    </div>
  );
}

export function TxChip({ tx }) {
  const colors = ['#2a55c9', '#0f5f4b', '#a8650f', '#7a3fa8', '#b42d24', '#1f7a8c', '#5b6b1f', '#8a4b2a'];
  const n = parseInt(String(tx).replace(/\D/g, ''), 10) || 0;
  const bg = tx === 'SYS' ? '#5b49b8' : colors[n % colors.length];
  return <span className="txid" style={{ background: bg }}>{tx}</span>;
}
