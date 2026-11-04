// Live connection to every app instance. Each instance streams its own SQL log
// over a WebSocket; Redis pub/sub events arrive from all of them and are de-duplicated.
import { api } from './api.js';
import { createStore } from './store.js';

export const live = createStore({
  sql: [],               // SQL log entries (ordered)
  events: [],            // Redis pub/sub events, newest first
  settings: { booking_mode: 'safe', lock_ordering: true },
  health: {},            // instance -> {mysql, replica, redis, instances}
  sockets: {},           // instance -> 'open' | 'closed'
  instances: [],
  demo: {},              // demo name -> [{step, text, state}]
  eventTick: 0,          // bumps on every event, views refetch on change
});

const MAX_SQL = 600;
const seenEvents = new Set();
const sqlIndex = new Map();

function upsertSql(state, entry) {
  const list = state.sql;
  const at = sqlIndex.get(entry.seq);
  if (at !== undefined && list[at] && list[at].seq === entry.seq) {
    const next = list.slice();
    next[at] = { ...list[at], ...entry };
    return next;
  }
  let next = list.concat([entry]);
  if (next.length > MAX_SQL) {
    next = next.slice(next.length - MAX_SQL);
    sqlIndex.clear();
    next.forEach((e, i) => sqlIndex.set(e.seq, i));
  } else {
    sqlIndex.set(entry.seq, next.length - 1);
  }
  return next;
}

function handle(instance, msg) {
  switch (msg.type) {
    case 'hello':
      live.set((s) => {
        const have = new Set(s.sql.map((e) => e.seq));
        const sql = s.sql.concat((msg.sql || []).filter((e) => !have.has(e.seq)))
          .sort((a, b) => a.ts - b.ts).slice(-MAX_SQL);
        sqlIndex.clear();
        sql.forEach((e, i) => sqlIndex.set(e.seq, i));
        const events = s.events.slice();
        for (const ev of (msg.events || []).slice().reverse()) {
          const id = ev.data?.id;
          if (id && !seenEvents.has(id)) { seenEvents.add(id); events.unshift(ev); }
        }
        return { ...s, sql, events: events.slice(0, 80), settings: msg.settings || s.settings,
          health: { ...s.health, [instance]: msg.health } };
      });
      break;
    case 'sql':
      live.set((s) => ({ ...s, sql: upsertSql(s, msg) }));
      break;
    case 'event': {
      const id = msg.data?.id;
      if (id && seenEvents.has(id)) return;
      if (id) seenEvents.add(id);
      live.set((s) => ({ ...s, events: [msg, ...s.events].slice(0, 80), eventTick: s.eventTick + 1 }));
      break;
    }
    case 'settings':
      live.set({ settings: msg.settings });
      break;
    case 'status':
      live.set((s) => ({ ...s, health: { ...s.health, [msg.instance || instance]: msg } }));
      break;
    case 'demo':
      live.set((s) => {
        const steps = (s.demo[msg.demo] || []).filter((x) => x.step !== msg.step);
        return { ...s, demo: { ...s.demo, [msg.demo]: [...steps, msg].sort((a, b) => a.step - b.step) } };
      });
      break;
    default:
  }
}

function connect(inst) {
  const url = inst.url.replace(/^http/, 'ws') + '/ws';
  let ws;
  try { ws = new WebSocket(url); } catch { setTimeout(() => connect(inst), 2000); return; }
  ws.onopen = () => live.set((s) => ({ ...s, sockets: { ...s.sockets, [inst.name]: 'open' } }));
  ws.onmessage = (e) => { try { handle(inst.name, JSON.parse(e.data)); } catch { /* ignore */ } };
  ws.onclose = () => {
    live.set((s) => ({ ...s, sockets: { ...s.sockets, [inst.name]: 'closed' } }));
    setTimeout(() => connect(inst), 2000);
  };
}

export async function startLive() {
  let instances = [];
  try {
    const r = await api('/instances');
    instances = r.instances;
  } catch {
    instances = [{ name: 'app-1', url: window.location.origin }];
  }
  // when served from the Vite dev server, make sure the API origin is used for app-1
  live.set({ instances });
  instances.forEach(connect);
}

export function clearSql() {
  sqlIndex.clear();
  live.set({ sql: [] });
}

export function clearDemo(name) {
  live.set((s) => ({ ...s, demo: { ...s.demo, [name]: [] } }));
}
