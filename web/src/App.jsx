import { createContext, useContext, useEffect, useMemo, useState } from 'react';
import Cover from './views/Cover.jsx';
import { Seg, Dot } from './components/ui.jsx';
import { api, post } from './lib/api.js';
import { live } from './lib/live.js';
import { useStore } from './lib/store.js';
import { toast, useToasts } from './lib/hooks.js';
import RequestView from './views/RequestView.jsx';
import DashboardView from './views/DashboardView.jsx';
import LabView from './views/LabView.jsx';
import Console from './console/Console.jsx';

export const AppCtx = createContext(null);
export const useApp = () => useContext(AppCtx);

function BrandMark() {
  return (
    <svg className="brand-mark" viewBox="0 0 32 32" aria-hidden="true">
      <rect width="32" height="32" rx="6" fill="#13202b" />
      <path d="M7 21h18M7 21v-7M25 21v-4.5a2.5 2.5 0 0 0-2.5-2.5H14v7" stroke="#fff" strokeWidth="1.8" fill="none" strokeLinecap="round" strokeLinejoin="round" />
      <circle cx="10.5" cy="16.5" r="1.7" fill="#fff" />
      <path d="M21 6.5v5M18.5 9h5" stroke="#7d9cf2" strokeWidth="1.8" strokeLinecap="round" />
    </svg>
  );
}

function Clock() {
  const [c, setC] = useState(null);
  const tick = useStore(live, (s) => s.eventTick);
  const [base, setBase] = useState(Date.now());
  const [, force] = useState(0);
  useEffect(() => {
    api('/clock').then((r) => { setC(r); setBase(Date.now()); }).catch(() => {});
  }, [tick]);
  useEffect(() => { const t = setInterval(() => force((n) => n + 1), 1000); return () => clearInterval(t); }, []);
  if (!c) return null;
  const sim = new Date(new Date(c.sim_now).getTime() + (Date.now() - base));
  return (
    <div className="ctl" title="Simulated clock used for hold expiry (sim_now())">
      <span className="ctl-label">Sim time</span>
      <span className="mono" style={{ fontWeight: 600 }}>{sim.toLocaleTimeString('en-GB', { hour12: false })}</span>
      {c.offset_minutes ? <span className="pill warn">+{c.offset_minutes} min</span> : <span className="pill outline">real time</span>}
    </div>
  );
}

function Toasts() {
  const list = useToasts();
  return <div className="toast-wrap">{list.map((t) => <div key={t.id} className={`toast ${t.kind}`}>{t.text}</div>)}</div>;
}

export default function App() {
  const consoleOnly = window.location.pathname.startsWith('/console');
  const [cover, setCover] = useState(() => {
    if (window.location.hash) return false;
    try { return sessionStorage.getItem('icu.cover') !== 'seen'; } catch { return true; }
  });
  const [meta, setMeta] = useState(null);
  const [userId, setUserId] = useState(() => Number(localStorage.getItem('icu.user')) || 1);
  // deep links: /#tab=lab&console=xray&table=reservation
  const link = useMemo(() => new URLSearchParams(window.location.hash.slice(1)), []);
  const [tab, setTab] = useState(() => link.get('tab') || localStorage.getItem('icu.tab') || 'request');
  const [consoleTab, setConsoleTab] = useState(() => link.get('console') || 'tables');
  const [consoleOpen, setConsoleOpen] = useState(true);
  const [tableName, setTableName] = useState(() => link.get('table') || 'bed');
  const [tableSource, setTableSource] = useState('primary');
  const [queryText, setQueryText] = useState(null);
  const settings = useStore(live, (s) => s.settings);
  const health = useStore(live, (s) => s.health);

  useEffect(() => {
    let stop = false;
    const load = () => api('/meta').then((m) => !stop && setMeta(m)).catch(() => setTimeout(load, 2000));
    load();
    return () => { stop = true; };
  }, []);
  useEffect(() => { try { localStorage.setItem('icu.user', String(userId)); } catch { /* private mode */ } }, [userId]);
  useEffect(() => { try { localStorage.setItem('icu.tab', tab); } catch { /* private mode */ } }, [tab]);

  const h = Object.values(health)[0] || {};
  const mysqlDown = h.mysql === false;
  const redisDown = h.redis === false;

  const setSetting = async (patch) => {
    try { live.set({ settings: await post('/settings', patch) }); } catch (e) { toast(e.message, 'err'); }
  };

  const ctx = useMemo(() => ({
    meta, userId, setUserId, settings, setSetting,
    openConsole: (t, extra) => {
      setConsoleOpen(true); setConsoleTab(t);
      if (extra?.table) { setTableName(extra.table); setTableSource(extra.source || 'primary'); }
      if (extra?.query) setQueryText({ ...extra.query, at: Date.now() });
    },
    consoleTab, setConsoleTab, tableName, setTableName, tableSource, setTableSource, queryText,
  }), [meta, userId, settings, consoleTab, tableName, tableSource, queryText]); // eslint-disable-line react-hooks/exhaustive-deps

  if (consoleOnly) {
    return (
      <AppCtx.Provider value={ctx}>
        <div className="console-page">
          <header className="topbar">
            <div className="brand"><BrandMark /><div><div className="brand-title">Live database console</div>
              <div className="brand-sub">City ICU bed allocation, MySQL 8 and Redis 7</div></div></div>
          </header>
          <Console standalone />
        </div>
        <Toasts />
      </AppCtx.Provider>
    );
  }

  if (cover) {
    return <Cover BrandMark={BrandMark} onEnter={() => { try { sessionStorage.setItem('icu.cover', 'seen'); } catch { /* private mode */ } setCover(false); }} />;
  }

  const users = meta?.users || [];
  const groups = ['HELPLINE', 'AMBULANCE', 'HOSPITAL_STAFF', 'CONTROL_ROOM'];

  return (
    <AppCtx.Provider value={ctx}>
      <div className="shell">
        <header className="topbar">
          <button type="button" className="brand" onClick={() => setCover(true)} title="Back to the cover">
            <BrandMark />
            <div>
              <div className="brand-title">City ICU bed allocation</div>
              <div className="brand-sub">MySQL 8 and Redis 7, DBMS Lab CD252IA</div>
            </div>
          </button>
          <div className="spacer" />
          <div className="ctl">
            <span className="ctl-label">Acting as</span>
            <select className="select sm" style={{ width: 196 }} value={userId} onChange={(e) => setUserId(Number(e.target.value))}>
              {groups.map((g) => (
                <optgroup key={g} label={g.replace('_', ' ').toLowerCase()}>
                  {users.filter((u) => u.role === g).map((u) => <option key={u.user_id} value={u.user_id}>{u.name}</option>)}
                </optgroup>
              ))}
            </select>
          </div>
          <div className="ctl" title="How bookings lock the bed row">
            <span className="ctl-label">Booking</span>
            <Seg value={settings.booking_mode} onChange={(v) => setSetting({ booking_mode: v })}
              options={[{ value: 'safe', label: 'Row lock' }, { value: 'unsafe', label: 'No lock', bad: true }]} />
          </div>
          <div className="ctl" title="In which order transfers lock their two beds">
            <span className="ctl-label">Transfers</span>
            <Seg value={settings.lock_ordering} onChange={(v) => setSetting({ lock_ordering: v })}
              options={[{ value: true, label: 'Ordered locks' }, { value: false, label: 'Request order', bad: true }]} />
          </div>
          <Clock />
        </header>

        <div>
          {mysqlDown && <div className="banner"><Dot state={false} /> MySQL primary is not reachable. If the crash demo is running, InnoDB is recovering; the page reconnects by itself.</div>}
          {!mysqlDown && redisDown && <div className="banner warn"><Dot state="warn" /> Redis is down. Search falls back to MySQL (ST_Distance_Sphere); bookings stay correct, dashboards read MySQL.</div>}
        </div>

        <div className={`layout ${consoleOpen ? '' : 'console-closed'}`}>
          <main className="main">
            <nav className="tabs">
              {[['request', 'Request a bed'], ['dashboard', 'City dashboard'], ['lab', 'Demo lab']].map(([k, label]) => (
                <button key={k} className={`tab ${tab === k ? 'active' : ''}`} onClick={() => setTab(k)}>{label}</button>
              ))}
            </nav>
            <div className="main-body">
              {tab === 'request' && <RequestView />}
              {tab === 'dashboard' && <DashboardView />}
              {tab === 'lab' && <LabView />}
            </div>
          </main>
          {consoleOpen
            ? <Console onCollapse={() => setConsoleOpen(false)} />
            : (
              <aside className="collapsed-rail">
                <button className="btn sm ghost" onClick={() => setConsoleOpen(true)} title="Open live database">⟨</button>
                <span className="vt">LIVE DATABASE</span>
              </aside>
            )}
        </div>
      </div>
      <Toasts />
    </AppCtx.Provider>
  );
}
