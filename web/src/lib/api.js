export async function api(path, { method = 'GET', body } = {}) {
  const res = await fetch('/api' + path, {
    method,
    headers: body ? { 'Content-Type': 'application/json' } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  });
  let data = null;
  try { data = await res.json(); } catch { data = null; }
  if (!res.ok) {
    const msg = (data && (data.detail?.[0]?.msg || data.detail)) || res.statusText;
    const err = new Error(typeof msg === 'string' ? msg : JSON.stringify(msg));
    err.status = res.status;
    throw err;
  }
  return data;
}

export const post = (path, body = {}) => api(path, { method: 'POST', body });

export const TYPE_LABEL = { 1: 'ICU', 2: 'ICU + ventilator', 3: 'Oxygen' };
export const TYPE_SHORT = { 1: 'ICU', 2: 'Vent', 3: 'O2' };
export const SEVERITY = { 1: 'Mild', 2: 'Stable', 3: 'Moderate', 4: 'Serious', 5: 'Critical' };

export function fmtTime(v) {
  if (!v) return '';
  const d = typeof v === 'number' ? new Date(v * 1000) : new Date(v);
  return d.toLocaleTimeString('en-GB', { hour12: false });
}

export function fmtClock(sec) {
  if (sec == null) return '';
  const s = Math.max(0, Math.floor(sec));
  const m = Math.floor(s / 60);
  return `${String(m).padStart(2, '0')}:${String(s % 60).padStart(2, '0')}`;
}

export function bytes(n) {
  if (n == null) return '';
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / 1048576).toFixed(1)} MB`;
}
