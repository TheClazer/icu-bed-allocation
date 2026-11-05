import { useEffect, useState } from 'react';
import { useApp } from '../App.jsx';
import { ActionButton, Panel, Pill, Seg, SqlText, Status } from '../components/ui.jsx';
import { api, fmtClock, post, SEVERITY, TYPE_LABEL } from '../lib/api.js';
import { toast, useNow, usePoll } from '../lib/hooks.js';

const EXAMPLES = [
  'need ventilator bed near Jaynagar, patient 60M critical',
  'Patient Meera Rao, 45 year old female, ICU near koramangla, serious',
  'o2 bed near e city for 66 year old lady, stable',
];

const FIELD_LABEL = { bed_type: 'Bed type', area: 'Area', age: 'Age', gender: 'Sex', severity: 'Severity', name: 'Name' };

function ParsedFields({ parsed }) {
  if (!parsed) return null;
  const val = {
    bed_type: parsed.bed_type_id && TYPE_LABEL[parsed.bed_type_id],
    area: parsed.area, age: parsed.age, gender: parsed.gender,
    severity: parsed.severity && `${parsed.severity} ${SEVERITY[parsed.severity]}`, name: parsed.name,
  };
  const ev = Object.fromEntries(parsed.evidence.map((e) => [e.field, e]));
  return (
    <div className="parsed">
      {Object.keys(FIELD_LABEL).filter((k) => val[k]).map((k) => (
        <span key={k} className={`pf ${parsed.inferred.includes(k) ? 'inferred' : ''}`}>
          {FIELD_LABEL[k]} <b>{val[k]}</b>
          <em>{ev[k] ? `"${ev[k].words}" ${ev[k].how}` : 'default'}</em>
        </span>
      ))}
      {!parsed.area && <span className="pf inferred">Area <b>not found</b></span>}
    </div>
  );
}

export function Trace({ trace, limit = 14 }) {
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

function ResultCard({ result, onAdmit, onCancel, now, fetchedAt }) {
  if (!result) {
    return (
      <Panel>
        <div className="card-body">
          <div className="card-title">Allocation result</div>
          <p className="muted" style={{ margin: '6px 0 0' }}>
            Submit a request. The nearest free bed of the right type is locked and held for 30 minutes, and every
            statement the transaction ran is listed here and in the SQL log.
          </p>
        </div>
      </Panel>
    );
  }
  const left = result.seconds_left != null ? result.seconds_left - (now - fetchedAt) / 1000 : null;
  return (
    <Panel>
      <div className="card-head">
        <span className="card-title">Allocation result</span>
        <Status value={result.outcome} />
        <span className="grow" />
        <span className="muted mono" style={{ fontSize: 11 }}>{result.tx}, conn {result.conn}, {result.mode === 'safe' ? 'row lock' : 'no lock'}</span>
      </div>
      <div className="card-body stack">
        {result.outcome === 'HELD' && (
          <>
            <div className="result-bed">
              <div className="bed-badge"><div><b>{result.bed_id}</b><span>HELD</span></div></div>
              <dl className="kv">
                <dt>Hospital</dt><dd>{result.hospital}</dd>
                <dt>Ward</dt><dd>{result.ward}, {TYPE_LABEL[result.bed_type_id]}</dd>
                <dt>Distance</dt><dd className="mono">{result.km} km from {result.area}</dd>
                <dt>Hold</dt><dd className="mono">{left > 0 ? `${fmtClock(left)} left` : 'expired, waiting for the MySQL event'}</dd>
              </dl>
            </div>
            <div className="timer-bar"><i style={{ width: `${Math.max(0, Math.min(100, (left / 1800) * 100))}%` }} /></div>
            <div className="row">
              <ActionButton onClick={() => onAdmit(result.reservation_id)}>Patient arrived: admit</ActionButton>
              <button className="btn" onClick={() => onCancel(result.reservation_id)}>Cancel hold</button>
            </div>
          </>
        )}
        {result.outcome === 'NO_BED' && (
          <div className="verdict warn">No free bed of this type within reach. Request #{result.request_id} is stored as OPEN (waiting list).</div>
        )}
        {result.outcome === 'REJECTED' && (
          <div className="verdict bad" style={{ display: 'block' }}>
            <div>The database refused this booking{result.code ? ` (MySQL error ${result.code})` : ''}.</div>
            <div className="mono" style={{ fontSize: 11.5, marginTop: 4, fontWeight: 400 }}>{result.error}</div>
            {result.meaning && <div style={{ marginTop: 4, fontWeight: 400 }}>{result.meaning}.</div>}
          </div>
        )}
        <div>
          <div className="label" style={{ marginBottom: 6 }}>How it was decided, {result.search?.source}</div>
          <Trace trace={result.trace} />
        </div>
      </div>
    </Panel>
  );
}

function Holds({ userId, refreshKey }) {
  const { data, reload } = usePoll(`/holds?user_id=${userId}`, 5000, { deps: [userId, refreshKey] });
  const now = useNow();
  const [fetchedAt, setFetchedAt] = useState(Date.now());
  useEffect(() => setFetchedAt(Date.now()), [data]);
  const act = async (id, what) => {
    try {
      const r = await post(`/reservations/${id}/${what}`, { user_id: userId });
      toast(r.message, r.ok ? '' : 'err');
      reload();
    } catch (e) { toast(e.message, 'err'); }
  };
  const rows = data || [];
  return (
    <Panel>
      <div className="card-head">
        <span className="card-title">Recent holds by this account</span>
        <span className="card-sub">{rows.filter((r) => r.status === 'HELD').length} live, limit 5 (trigger)</span>
      </div>
      <div className="holds">
        {rows.length === 0 && <div className="empty">No holds yet for this account.</div>}
        {rows.map((r) => {
          const left = r.seconds_left - (now - fetchedAt) / 1000;
          return (
            <div key={r.reservation_id} className="hold">
              <div className="bid">{r.bed_id}</div>
              <div style={{ minWidth: 0 }}>
                <div className="row" style={{ gap: 6 }}><Status value={r.status} />
                  <span style={{ fontWeight: 500, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{r.patient}</span></div>
                <div className="muted" style={{ fontSize: 11.5 }}>{r.hospital}, {TYPE_LABEL[r.bed_type_id]}, res #{r.reservation_id}
                  {r.status === 'HELD' && <span className="mono">, {left > 0 ? `${fmtClock(left)} left` : 'past expiry'}</span>}</div>
              </div>
              {r.status === 'HELD' && (
                <div className="row" style={{ gap: 4 }}>
                  <button className="btn sm" onClick={() => act(r.reservation_id, 'admit')}>Admit</button>
                  <button className="btn sm ghost" onClick={() => act(r.reservation_id, 'cancel')}>Cancel</button>
                </div>
              )}
            </div>
          );
        })}
      </div>
    </Panel>
  );
}

export default function RequestView() {
  const { meta, userId, settings, openConsole } = useApp();
  const [text, setText] = useState('');
  const [parsed, setParsed] = useState(null);
  const [form, setForm] = useState({ patient_name: '', age: '', gender: 'M', bed_type_id: 1, area: 'Jayanagar', severity: 4 });
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState(null);
  const [fetchedAt, setFetchedAt] = useState(Date.now());
  const [refresh, setRefresh] = useState(0);
  const now = useNow();
  const set = (k, v) => setForm((f) => ({ ...f, [k]: v }));

  const read = async (t = text) => {
    if (!t.trim()) return;
    try {
      const p = await post('/nlp/parse', { text: t });
      setParsed(p);
      setForm((f) => ({
        ...f,
        patient_name: p.name || f.patient_name,
        age: p.age ?? f.age,
        gender: p.gender || f.gender,
        bed_type_id: p.bed_type_id || f.bed_type_id,
        area: p.area || f.area,
        severity: p.severity || f.severity,
      }));
    } catch (e) { toast(e.message, 'err'); }
  };

  const submit = async () => {
    if (!form.patient_name.trim()) { toast('Enter a patient name', 'err'); return; }
    setBusy(true);
    try {
      const r = await post('/requests', {
        user_id: userId, patient_name: form.patient_name, age: form.age === '' ? null : Number(form.age),
        gender: form.gender, bed_type_id: Number(form.bed_type_id), area: form.area, severity: Number(form.severity),
        raw_text: parsed?.text || null,
      });
      setResult(r); setFetchedAt(Date.now()); setRefresh((n) => n + 1);
    } catch (e) { toast(e.message, 'err'); } finally { setBusy(false); }
  };

  const act = async (id, what) => {
    try {
      const r = await post(`/reservations/${id}/${what}`, { user_id: userId });
      toast(r.message, r.ok ? '' : 'err');
      if (r.ok) setResult((x) => x && { ...x, outcome: what === 'admit' ? 'ADMITTED' : 'CANCELLED', seconds_left: null });
      setRefresh((n) => n + 1);
    } catch (e) { toast(e.message, 'err'); }
  };

  const user = meta?.users?.find((u) => u.user_id === userId);

  return (
    <div>
      <div className="page-head">
        <div className="grow">
          <h1>Request an ICU bed</h1>
          <p>Booking as <b>{user?.name || '...'}</b>. Search uses Redis GEO, the hold is a MySQL transaction
            {settings.booking_mode === 'safe' ? ' with a row lock (FOR UPDATE SKIP LOCKED).' : ' with NO lock: only the UNIQUE index protects the bed.'}</p>
        </div>
        <button className="linkbtn" onClick={() => openConsole('sql')}>Watch the SQL log</button>
      </div>
      <div className="req-grid">
        <div className="stack">
          <Panel>
            <div className="card-head"><span className="card-title">Describe the patient</span><span className="tag">NLP parser</span></div>
            <div className="card-body">
              <textarea className="textarea" rows={2} value={text} placeholder="Type like a helpline operator would, e.g. need ventilator bed near jaynagar, 60M critical"
                onChange={(e) => setText(e.target.value)} onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); read(); } }} />
              <div className="row wrap" style={{ marginTop: 8 }}>
                <button className="btn sm" onClick={() => read()}>Read text into form</button>
                <span className="faint" style={{ fontSize: 11.5 }}>Try:</span>
                {EXAMPLES.map((ex) => (
                  <button key={ex} className="chip" onClick={() => { setText(ex); read(ex); }}>{ex.length > 38 ? ex.slice(0, 36) + '...' : ex}</button>
                ))}
              </div>
              <ParsedFields parsed={parsed} />
            </div>
          </Panel>
          <Panel>
            <div className="card-head"><span className="card-title">Bed request</span><span className="card-sub">becomes rows in patient and bed_request</span></div>
            <div className="card-body">
              <div className="form-grid">
                <div className="field"><label>Patient name</label>
                  <input className="input" value={form.patient_name} onChange={(e) => set('patient_name', e.target.value)} placeholder="Full name" /></div>
                <div className="row" style={{ gap: 12, alignItems: 'flex-end' }}>
                  <div className="field" style={{ width: 80 }}><label>Age</label>
                    <input className="input" type="number" value={form.age} onChange={(e) => set('age', e.target.value)} /></div>
                  <div className="field grow"><label>Sex</label>
                    <Seg full value={form.gender} onChange={(v) => set('gender', v)} options={[{ value: 'M', label: 'M' }, { value: 'F', label: 'F' }, { value: 'O', label: 'Other' }]} /></div>
                </div>
                <div className="field span2"><label>Bed type</label>
                  <Seg full value={Number(form.bed_type_id)} onChange={(v) => set('bed_type_id', v)}
                    options={[1, 2, 3].map((t) => ({ value: t, label: TYPE_LABEL[t] }))} /></div>
                <div className="field"><label>Pickup area</label>
                  <select className="select" value={form.area} onChange={(e) => set('area', e.target.value)}>
                    {(meta?.areas || []).map((a) => <option key={a.name}>{a.name}</option>)}
                  </select></div>
                <div className="field"><label>Severity</label>
                  <Seg full value={Number(form.severity)} onChange={(v) => set('severity', v)}
                    options={[1, 2, 3, 4, 5].map((n) => ({ value: n, label: String(n), title: SEVERITY[n] }))} /></div>
              </div>
              <div className="row" style={{ marginTop: 14 }}>
                <ActionButton className="btn primary lg" disabled={busy} onClick={submit}>
                  {busy ? 'Locking a bed...' : 'Find nearest bed and hold it'}
                </ActionButton>
                <span className="muted" style={{ fontSize: 12 }}>{SEVERITY[form.severity]}, {TYPE_LABEL[form.bed_type_id]} near {form.area}</span>
              </div>
            </div>
          </Panel>
        </div>
        <div className="stack">
          <ResultCard result={result} now={now} fetchedAt={fetchedAt} onAdmit={(id) => act(id, 'admit')} onCancel={(id) => act(id, 'cancel')} />
          <Holds userId={userId} refreshKey={refresh} />
        </div>
      </div>
    </div>
  );
}
