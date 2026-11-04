import { useEffect, useRef, useState, useCallback } from 'react';
import { api } from './api.js';
import { live } from './live.js';
import { useStore } from './store.js';

// Poll an endpoint every `ms` while `active`, and also whenever a live event arrives.
export function usePoll(path, ms = 1000, { active = true, onEvents = true, deps = [] } = {}) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const tick = useStore(live, (s) => s.eventTick);
  const busy = useRef(false);

  const load = useCallback(async () => {
    if (!path || busy.current) return;
    busy.current = true;
    try { setData(await api(path)); setError(null); } catch (e) { setError(e); } finally { busy.current = false; }
  }, [path]);

  useEffect(() => { if (active) load(); }, [active, load, ...deps]);
  useEffect(() => {
    if (!active || !ms) return undefined;
    const t = setInterval(load, ms);
    return () => clearInterval(t);
  }, [active, ms, load]);
  useEffect(() => {
    if (!active || !onEvents) return undefined;
    const t = setTimeout(load, 120);
    return () => clearTimeout(t);
  }, [tick]); // eslint-disable-line react-hooks/exhaustive-deps

  return { data, error, reload: load, setData };
}

// A clock that ticks every second (for countdowns).
export function useNow(ms = 1000) {
  const [now, setNow] = useState(Date.now());
  useEffect(() => { const t = setInterval(() => setNow(Date.now()), ms); return () => clearInterval(t); }, [ms]);
  return now;
}

const toasts = { list: [], subs: new Set() };
export function toast(text, kind = '') {
  const id = Math.random().toString(36).slice(2);
  toasts.list = [...toasts.list, { id, text, kind }];
  toasts.subs.forEach((f) => f(toasts.list));
  setTimeout(() => { toasts.list = toasts.list.filter((t) => t.id !== id); toasts.subs.forEach((f) => f(toasts.list)); }, 4200);
}
export function useToasts() {
  const [list, setList] = useState(toasts.list);
  useEffect(() => { toasts.subs.add(setList); return () => toasts.subs.delete(setList); }, []);
  return list;
}
