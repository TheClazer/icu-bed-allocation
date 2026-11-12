import { useApp } from '../App.jsx';
import { MetricsTab, QueryTab, RedisTab, SqlTab, TablesTab, useMetrics, Vitals, XrayTab } from '../console/Console.jsx';
import BedsView from './BedsView.jsx';

function HealthView() {
  const { data: m } = useMetrics(true);
  return (
    <>
      <Vitals m={m} />
      <div style={{ marginTop: 22 }}><MetricsTab /></div>
    </>
  );
}

const SUBS = [
  { id: 'beds', label: 'Beds', hint: 'Every bed in the city, live', C: BedsView, own: true },
  { id: 'tables', label: 'Tables', hint: 'Raw rows; changes flash as they happen', C: TablesTab },
  { id: 'activity', label: 'Activity', hint: 'Every statement the app sends, in order', C: SqlTab },
  { id: 'locks', label: 'Locks', hint: 'Open transactions, row locks, deadlocks', C: XrayTab },
  { id: 'redis', label: 'Redis', hint: 'Counters, map and event stream', C: RedisTab },
  { id: 'health', label: 'Health', hint: 'Vitals, replica and server metrics', C: HealthView },
  { id: 'ask', label: 'Ask', hint: 'Run your own read-only SQL', C: QueryTab },
];

export default function DatabaseView({ active = true, standalone }) {
  const { dbSub, setDbSub } = useApp();
  const sub = SUBS.find((s) => s.id === dbSub) || SUBS[0];
  return (
    <div className="db">
      <aside className="db-nav">
        {!standalone && <h1 className="h1">Database</h1>}
        <p className="muted db-lede">What MySQL and Redis are doing right now.</p>
        <nav aria-label="Database views">
          {SUBS.map((s) => (
            <button key={s.id} type="button" className={s.id === sub.id ? 'on' : ''} aria-current={s.id === sub.id ? 'page' : undefined} onClick={() => setDbSub(s.id)}>
              <span className="dn-t">{s.label}</span>
              <span className="dn-h">{s.hint}</span>
            </button>
          ))}
        </nav>
        {!standalone && <a className="linkbtn popout" href={`/console#place=database&sub=${sub.id}`} target="_blank" rel="noreferrer">Open in its own window</a>}
      </aside>
      <section className="db-main">
        {!sub.own && (
          <div className="view-head">
            <div className="grow"><h2 className="h2">{sub.label}</h2><p className="muted">{sub.hint}.</p></div>
            <span className="live-tag"><i className="dot" />live</span>
          </div>
        )}
        {active && <sub.C />}
      </section>
    </div>
  );
}
