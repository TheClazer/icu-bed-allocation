import { useSyncExternalStore } from 'react';

// Tiny external store. Updates are batched to one notify per animation frame,
// so a burst of SQL log messages re-renders once.
export function createStore(initial) {
  let state = initial;
  const subs = new Set();
  let queued = false;
  const flush = () => { queued = false; subs.forEach((fn) => fn()); };
  return {
    get: () => state,
    set(update) {
      state = typeof update === 'function' ? update(state) : { ...state, ...update };
      if (!queued) { queued = true; requestAnimationFrame(flush); }
    },
    subscribe(fn) { subs.add(fn); return () => subs.delete(fn); },
  };
}

export function useStore(store, select) {
  return useSyncExternalStore(store.subscribe, () => select(store.get()));
}
