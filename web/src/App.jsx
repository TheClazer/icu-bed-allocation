import { Component, createContext, useContext, useEffect, useMemo, useState } from 'react';

// One broken view must never blank the whole app during a demo.
class Guard extends Component {
  constructor(props) { super(props); this.state = { error: null }; }
  static getDerivedStateFromError(error) { return { error }; }
  render() {
    if (!this.state.error) return this.props.children;
    return (
      <div className="narrow">
        <div className="notice bad"><b>This view hit an error.</b><div>{String(this.state.error.message || this.state.error)}</div></div>
        <div className="actions"><button className="btn" onClick={() => this.setState({ error: null })}>Try again</button></div>
      </div>
    );
  }
}
import Cover from './views/Cover.jsx';
import BookView from './views/BookView.jsx';
import ScenariosView from './views/ScenariosView.jsx';
import DatabaseView from './views/DatabaseView.jsx';
import { Sparkline } from './components/ui.jsx';
import { api, post } from './lib/api.js';
import { live } from './lib/live.js';
import { useStore } from './lib/store.js';
import { toast, usePoll, useToasts } from './lib/hooks.js';

export const AppCtx = createContext(null);
export const useApp = () => useContext(AppCtx);

const PLACES = [
  { id: 'book', label: 'Book a bed' },
  { id: 'scenarios', label: 'Scenarios' },
  { id: 'database', label: 'Database' },
];
// old console tab names, still used by a few links
const SUB_FOR = { tables: 'tables', sql: 'activity', xray: 'locks', redis: 'redis', metrics: 'health', query: 'ask' };

export function BrandMark() {
  return (
    <svg className="brand-mark" viewBox="0 0 32 32" aria-hidden="true">
      <rect width="32" height="32" rx="6" fill="#13202b" />
      <path d="M7 21h18M7 21v-7M25 21v-4.5a2.5 2.5 0 0 0-2.5-2.5H14v7" stroke="#fff" strokeWidth="1.8" fill="none" strokeLinecap="round" strokeLinejoin="round" />
      <circle cx="10.5" cy="16.5" r="1.7" fill="#fff" />
      <path d="M21 6.5v5M18.5 9h5" stroke="#7d9cf2" strokeWidth="1.8" strokeLinecap="round" />
    </svg>
  );
}

function Toasts() {
  const list = useToasts();
  return <div className="toast-wrap">{list.map((t) => <div key={t.id} className={`toast ${t.kind}`}>{t.text}</div>)}</div>;
}

// One quiet signal in the corner: is the database fine, and is it busy.
function Pulse({ onOpen }) {
  const health = useStore(live, (s) => s.health);
  const { data } = usePoll('/metrics', 2000, { onEvents: false });
  const h = Object.values(health)[0] || {};
  let text = 'Database healthy';
  let state = 'ok';
  if (h.mysql === false) { text = 'MySQL down, recovering'; state = 'bad'; }
  else if (h.redis === false) { text = 'Redis down, using MySQL'; state = 'warn'; }
  else if (h.replica === false) { text = 'Replica unreachable'; state = 'warn'; }
  return (
    <button type="button" className={`pulse ${state}`} onClick={onOpen} title="Open the database">
      <span className="pulse-trace"><Sparkline points={(data?.history?.qps || []).slice(-40)} color={state === 'bad' ? '#d23a4a' : '#1f4fd1'} height={22} /></span>
      <span className="pulse-dot" />
      <span>{text}</span>
    </button>
  );
}

function readLink() {
  const p = new URLSearchParams(window.location.hash.slice(1));
  return {
    place: p.get('place') || null,
    sub: p.get('sub') || null,
    scenario: p.get('scenario') || null,
    table: p.get('table') || null,
  };
}

export default function App() {
  const consoleOnly = window.location.pathname.startsWith('/console');
  const link = useMemo(readLink, []);
  const [cover, setCover] = useState(() => {
    if (window.location.hash || consoleOnly) return false;
    try { return sessionStorage.getItem('icu.cover') !== 'seen'; } catch { return true; }
  });
  const [meta, setMeta] = useState(null);
  const [userId, setUserId] = useState(() => Number(localStorage.getItem('icu.user')) || 1);
  const [place, setPlace] = useState(() => link.place || (consoleOnly ? 'database' : 'book'));
  const [dbSub, setDbSub] = useState(() => link.sub || 'beds');
  const [scenario, setScenario] = useState(() => link.scenario || 'race');
  const [tableName, setTableName] = useState(() => link.table || 'bed');
  const [tableSource, setTableSource] = useState('primary');
  const [queryText, setQueryText] = useState(null);
  const [txFilter, setTxFilter] = useState('');
  const settings = useStore(live, (s) => s.settings);

  useEffect(() => {
    let stop = false;
    const load = () => api('/meta').then((m) => !stop && setMeta(m)).catch(() => setTimeout(load, 2000));
    load();
    return () => { stop = true; };
  }, []);
  useEffect(() => { try { localStorage.setItem('icu.user', String(userId)); } catch { /* private mode */ } }, [userId]);
  useEffect(() => {
    if (cover) return;
    const p = new URLSearchParams({ place });
    if (place === 'database') p.set('sub', dbSub);
    if (place === 'scenarios') p.set('scenario', scenario);
    window.history.replaceState(null, '', `${window.location.pathname}#${p}`);
  }, [place, dbSub, scenario, cover]);

  const setSetting = async (patch) => {
    try { live.set({ settings: await post('/settings', patch) }); } catch (e) { toast(e.message, 'err'); }
  };

  const go = (to, opts = {}) => {
    if (opts.sub) setDbSub(opts.sub);
    if (opts.table) { setTableName(opts.table); setTableSource(opts.source || 'primary'); }
    if (opts.query) setQueryText({ ...opts.query, at: Date.now() });
    if (opts.tx !== undefined) setTxFilter(opts.tx);
    if (opts.scenario) setScenario(opts.scenario);
    if (consoleOnly && to !== 'database') { window.open(`/#place=${to}`, '_blank'); return; }
    setPlace(to);
  };

  const ctx = useMemo(() => ({
    meta, userId, setUserId, settings, setSetting, go,
    openConsole: (t, extra = {}) => go('database', { sub: SUB_FOR[t] || t, ...extra }),
    dbSub, setDbSub, scenario, setScenario,
    tableName, setTableName, tableSource, setTableSource, queryText, txFilter, setTxFilter,
  }), [meta, userId, settings, dbSub, scenario, tableName, tableSource, queryText, txFilter]); // eslint-disable-line react-hooks/exhaustive-deps

  if (cover) {
    return <Cover BrandMark={BrandMark} onEnter={() => { try { sessionStorage.setItem('icu.cover', 'seen'); } catch { /* private mode */ } setCover(false); }} />;
  }

  return (
    <AppCtx.Provider value={ctx}>
      <div className="app">
        <header className="nav">
          <button type="button" className="brand" onClick={() => (consoleOnly ? null : setCover(true))} title={consoleOnly ? '' : 'Back to the cover'}>
            <BrandMark />
            <span className="brand-title">{consoleOnly ? 'Live database' : 'City ICU bed allocation'}</span>
          </button>
          {!consoleOnly && (
            <nav className="places" aria-label="Main">
              {PLACES.map((p) => (
                <button key={p.id} type="button" className={`place ${place === p.id ? 'on' : ''}`} aria-current={place === p.id ? 'page' : undefined}
                  onClick={() => setPlace(p.id)}>{p.label}</button>
              ))}
            </nav>
          )}
          <span className="grow" />
          <Pulse onOpen={() => go('database', { sub: 'health' })} />
        </header>
        <main className="page">
          {/* all three stay mounted so a half-finished booking or a scenario result survives a look at the database */}
          {!consoleOnly && <div hidden={place !== 'book'}><Guard><BookView /></Guard></div>}
          {!consoleOnly && <div hidden={place !== 'scenarios'}><Guard><ScenariosView /></Guard></div>}
          <div hidden={place !== 'database'}><Guard><DatabaseView active={place === 'database'} standalone={consoleOnly} /></Guard></div>
        </main>
      </div>
      <Toasts />
    </AppCtx.Provider>
  );
}
