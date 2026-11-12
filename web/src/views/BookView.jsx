import { useEffect, useState } from 'react';
import { useApp } from '../App.jsx';
import Trace, { summarise } from '../components/Trace.jsx';
import { Seg, Status } from '../components/ui.jsx';
import { fmtClock, post, SEVERITY, TYPE_LABEL } from '../lib/api.js';
import { toast, useNow, usePoll } from '../lib/hooks.js';

const EXAMPLES = [
  'need ventilator bed near Jaynagar, 60M critical',
  'Patient Meera Rao, 45 year old female, ICU near koramangla, serious',
  'o2 bed near e city for 66 year old lady, stable',
];
const STEPS = ['Describe', 'Confirm', 'Bed held'];
const BLANK = { patient_name: '', age: '', gender: 'M', bed_type_id: 1, area: 'Jayanagar', severity: 4 };

function Steps({ at }) {
  return (
    <ol className="flow">
      {STEPS.map((s, i) => <li key={s} className={i === at ? 'on' : i < at ? 'done' : ''}><span>{i + 1}</span>{s}</li>)}
    </ol>
  );
}

function sentence(f) {
  const who = [f.patient_name || 'unnamed patient', f.age && `${f.age}`, f.gender === 'F' ? 'female' : f.gender === 'M' ? 'male' : null].filter(Boolean).join(', ');
  return { what: TYPE_LABEL[f.bed_type_id], where: f.area, who, how: `${f.severity}, ${SEVERITY[f.severity].toLowerCase()}` };
}

function Holds({ userId, refresh }) {
  const { data, reload } = usePoll(`/holds?user_id=${userId}`, 5000, { deps: [userId, refresh] });
  const now = useNow();
  const [at, setAt] = useState(Date.now());
  useEffect(() => setAt(Date.now()), [data]);
  const live = (data || []).filter((r) => r.status === 'HELD');
  if (!live.length) return null;
  const act = async (id, what) => {
    try { const r = await post(`/reservations/${id}/${what}`, { user_id: userId }); toast(r.message, r.ok ? '' : 'err'); reload(); }
    catch (e) { toast(e.message, 'err'); }
  };
  return (
    <details className="quiet-list">
      <summary>{live.length} bed{live.length > 1 ? 's' : ''} on hold for this account</summary>
      {live.map((r) => {
        const left = r.seconds_left - (now - at) / 1000;
        return (
          <div key={r.reservation_id} className="qrow">
            <span className="qbed">{r.bed_id}</span>
            <span className="grow">{r.patient}, {r.hospital}<span className="muted">, {left > 0 ? `${fmtClock(left)} left` : 'past expiry'}</span></span>
            <button className="btn sm" onClick={() => act(r.reservation_id, 'admit')}>Admit</button>
            <button className="btn sm ghost" onClick={() => act(r.reservation_id, 'cancel')}>Cancel</button>
          </div>
        );
      })}
    </details>
  );
}

export default function BookView() {
  const { meta, userId, setUserId, go } = useApp();
  const [step, setStep] = useState(0);
  const [text, setText] = useState('');
  const [parsed, setParsed] = useState(null);
  const [form, setForm] = useState(BLANK);
  const [editing, setEditing] = useState(false);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState(null);
  const [fetchedAt, setFetchedAt] = useState(Date.now());
  const [refresh, setRefresh] = useState(0);
  const now = useNow();
  const set = (k, v) => setForm((f) => ({ ...f, [k]: v }));

  const read = async (t) => {
    const value = (t ?? text).trim();
    if (!value) { setForm(BLANK); setParsed(null); setEditing(true); setStep(1); return; }
    try {
      const p = await post('/nlp/parse', { text: value });
      setParsed(p);
      setForm({
        patient_name: p.name || '', age: p.age ?? '', gender: p.gender || 'M',
        bed_type_id: p.bed_type_id || 1, area: p.area || 'Jayanagar', severity: p.severity || 3,
      });
      setEditing(!p.name || !p.area);
      setStep(1);
    } catch (e) { toast(e.message, 'err'); }
  };

  const hold = async () => {
    if (!form.patient_name.trim()) { setEditing(true); toast('Add the patient name first', 'err'); return; }
    setBusy(true);
    try {
      const r = await post('/requests', {
        user_id: userId, patient_name: form.patient_name, age: form.age === '' ? null : Number(form.age),
        gender: form.gender, bed_type_id: Number(form.bed_type_id), area: form.area, severity: Number(form.severity),
        raw_text: parsed?.text || null,
      });
      setResult(r); setFetchedAt(Date.now()); setStep(2); setRefresh((n) => n + 1);
    } catch (e) { toast(e.message, 'err'); } finally { setBusy(false); }
  };

  const act = async (what) => {
    try {
      const r = await post(`/reservations/${result.reservation_id}/${what}`, { user_id: userId });
      toast(r.message, r.ok ? '' : 'err');
      if (r.ok) setResult((x) => ({ ...x, outcome: what === 'admit' ? 'ADMITTED' : 'CANCELLED' }));
      setRefresh((n) => n + 1);
    } catch (e) { toast(e.message, 'err'); }
  };

  const restart = () => { setStep(0); setText(''); setParsed(null); setResult(null); setForm(BLANK); setEditing(false); };
  const users = meta?.users || [];
  const s = sentence(form);
  const left = result?.seconds_left != null ? result.seconds_left - (now - fetchedAt) / 1000 : null;

  return (
    <div className="narrow">
      <div className="lead-row">
        <h1 className="h1">Book a bed</h1>
        <label className="as">
          Booking as
          <select className="select-inline" value={userId} onChange={(e) => setUserId(Number(e.target.value))}>
            {users.map((u) => <option key={u.user_id} value={u.user_id}>{u.name}</option>)}
          </select>
        </label>
      </div>
      <Steps at={step} />

      {step === 0 && (
        <section className="step">
          <label className="big-label" htmlFor="describe">Describe the patient and where they are</label>
          <textarea id="describe" className="big-input" rows={3} value={text} autoFocus
            placeholder="For example: need a ventilator bed near Jayanagar, 60 year old man, critical"
            onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); read(); } }} />
          <div className="examples">
            <span className="muted">Try</span>
            {EXAMPLES.map((ex) => <button key={ex} type="button" className="link-chip" onClick={() => { setText(ex); document.getElementById('describe')?.focus(); }}>{ex}</button>)}
          </div>
          <div className="actions">
            <button type="button" className="btn primary lg" onClick={() => read()}>Continue</button>
            <button type="button" className="btn ghost" onClick={() => read('')}>Fill in the details yourself</button>
          </div>
        </section>
      )}

      {step === 1 && (
        <section className="step">
          <p className="confirm-line">
            A <b>{s.what}</b> bed near <b>{s.where}</b> for <b>{s.who}</b>, severity <b>{s.how}</b>.
          </p>
          {parsed && (
            <details className="why-line">
              <summary>How the text was read</summary>
              <ul>
                {parsed.evidence.map((e) => <li key={e.field}><span className="mono">"{e.words}"</span> gave the {e.field.replace('_', ' ')} ({e.how})</li>)}
                {parsed.inferred.length > 0 && <li className="muted">Assumed because it was not in the text: {parsed.inferred.join(', ').replace('_', ' ')}</li>}
              </ul>
            </details>
          )}
          {!editing && <button type="button" className="linkbtn" onClick={() => setEditing(true)}>Change details</button>}
          {editing && (
            <div className="form-grid edit">
              <div className="field span2"><label htmlFor="pn">Patient name</label>
                <input id="pn" className="input" value={form.patient_name} onChange={(e) => set('patient_name', e.target.value)} placeholder="Full name" /></div>
              <div className="field"><label htmlFor="age">Age</label>
                <input id="age" className="input" type="number" value={form.age} onChange={(e) => set('age', e.target.value)} /></div>
              <div className="field"><label>Sex</label>
                <Seg full value={form.gender} onChange={(v) => set('gender', v)} options={[{ value: 'M', label: 'Male' }, { value: 'F', label: 'Female' }, { value: 'O', label: 'Other' }]} /></div>
              <div className="field span2"><label>Bed type</label>
                <Seg full value={Number(form.bed_type_id)} onChange={(v) => set('bed_type_id', v)} options={[1, 2, 3].map((t) => ({ value: t, label: TYPE_LABEL[t] }))} /></div>
              <div className="field"><label htmlFor="area">Pickup area</label>
                <select id="area" className="select" value={form.area} onChange={(e) => set('area', e.target.value)}>
                  {(meta?.areas || []).map((a) => <option key={a.name}>{a.name}</option>)}
                </select></div>
              <div className="field"><label>Severity</label>
                <Seg full value={Number(form.severity)} onChange={(v) => set('severity', v)} options={[1, 2, 3, 4, 5].map((n) => ({ value: n, label: String(n), title: SEVERITY[n] }))} /></div>
            </div>
          )}
          <div className="actions">
            <button type="button" className="btn primary lg" disabled={busy} onClick={hold}>{busy ? 'Holding a bed...' : 'Hold the nearest bed'}</button>
            <button type="button" className="btn ghost" onClick={() => setStep(0)}>Back</button>
          </div>
        </section>
      )}

      {step === 2 && result && (
        <section className="step">
          {result.outcome === 'HELD' || result.outcome === 'ADMITTED' || result.outcome === 'CANCELLED' ? (
            <div className="held">
              <div className="held-bed">
                <span className="held-num">{result.bed_id}</span>
                <Status value={result.outcome} />
              </div>
              <div className="held-text">
                <div className="held-title">{result.hospital}</div>
                <div className="muted">{result.ward}, {TYPE_LABEL[result.bed_type_id]}, {result.km} km from {result.area}</div>
                {result.outcome === 'HELD' && (
                  <>
                    <div className="held-clock">{left > 0 ? `Held for ${fmtClock(left)} more` : 'Hold has run out, the database will free it'}</div>
                    <div className="timer-bar"><i style={{ width: `${Math.max(0, Math.min(100, (left / 1800) * 100))}%` }} /></div>
                  </>
                )}
                {result.outcome === 'ADMITTED' && <div className="held-clock">Patient admitted. The bed is now occupied.</div>}
                {result.outcome === 'CANCELLED' && <div className="held-clock">Hold cancelled. The bed is free again.</div>}
              </div>
            </div>
          ) : result.outcome === 'NO_BED' ? (
            <div className="notice">No free {TYPE_LABEL[result.bed_type_id]} bed within reach. The request is kept as open (number {result.request_id}). Try another bed type or area.</div>
          ) : (
            <div className="notice bad">
              <b>The database refused this booking{result.code ? `, MySQL error ${result.code}` : ''}.</b>
              <div>{result.meaning || result.error}</div>
            </div>
          )}

          <div className="actions">
            {result.outcome === 'HELD' && <button type="button" className="btn primary lg" onClick={() => act('admit')}>Patient arrived, admit</button>}
            {result.outcome === 'HELD' && <button type="button" className="btn" onClick={() => act('cancel')}>Cancel hold</button>}
            <button type="button" className="btn ghost" onClick={restart}>Book another patient</button>
          </div>

          <details className="db-did">
            <summary>
              <span className="db-did-k">What the database did</span>
              <span className="db-did-v">{summarise(result.trace)}</span>
            </summary>
            <Trace trace={result.trace} limit={20} />
            <button type="button" className="linkbtn" onClick={() => go('database', { sub: 'activity', tx: result.tx })}>Open this transaction in the database</button>
          </details>
        </section>
      )}

      <Holds userId={userId} refresh={refresh} />
    </div>
  );
}
