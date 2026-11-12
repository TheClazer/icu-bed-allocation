import { Pill, SqlText } from './ui.jsx';

// The statements one transaction ran, in order, with when each started.
export default function Trace({ trace, limit = 14 }) {
  if (!trace?.length) return null;
  return (
    <ul className="timeline">
      {trace.slice(0, limit).map((t, i) => (
        <li key={i}>
          <span className="t">+{t.at_ms} ms</span>
          <span>{t.kind === 'REDIS' ? <Pill kind="redis">REDIS</Pill> : <Pill kind={t.ok ? (t.kind === 'COMMIT' ? 'ok' : t.kind === 'ROLLBACK' ? 'err' : '') : 'err'}>{t.kind}</Pill>}</span>
          <span>
            <span className="sql" title={t.sql}><SqlText sql={t.sql.replace(/^REDIS /, '').replace(/\s+/g, ' ')} /></span>
            {t.error && <div className="err">{t.error}</div>}
          </span>
        </li>
      ))}
    </ul>
  );
}

// One sentence a person can read instead of the list.
export function summarise(trace) {
  if (!trace?.length) return '';
  const sql = trace.filter((t) => t.kind !== 'REDIS');
  const redis = trace.length - sql.length;
  const last = trace[trace.length - 1];
  const ms = Math.round(last.at_ms + (last.ms || 0));
  const committed = trace.some((t) => t.kind === 'COMMIT');
  const rolled = trace.some((t) => t.kind === 'ROLLBACK');
  const locked = trace.some((t) => /FOR UPDATE/.test(t.sql));
  const parts = [`${sql.length} SQL statements and ${redis} Redis commands in ${ms} ms`];
  if (locked) parts.push('the bed row was locked with FOR UPDATE');
  parts.push(committed ? 'committed' : rolled ? 'rolled back' : 'not committed');
  return parts.join(', ');
}
