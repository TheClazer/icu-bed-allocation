import { useEffect, useState } from 'react';
import { useApp } from '../App.jsx';
import CountUp from '../components/reactbits/CountUp.jsx';
import { Panel, Pill, Status } from '../components/ui.jsx';
import { fmtClock, post, TYPE_LABEL } from '../lib/api.js';
import { toast, useNow, usePoll } from '../lib/hooks.js';

const INK = '#13202b';
const BLUE = '#1f4fd1';
const GREY = '#96a4b0';
const ORDER = ['FREE', 'HELD', 'OCCUPIED', 'MAINTENANCE'];

function Kpi({ label, value, sub, kind }) {
  return (
    <div className={`kpi ${kind || ''}`}>
      <div className="k">{label}</div>
      <div className="v"><CountUp to={value || 0} from={0} duration={0.8} trigger="load" /></div>
      <div className="s">{sub}</div>
    </div>
  );
}

// One square per bed, in status order: a ward census you can read at a glance.
function Cells({ status }) {
  const cells = [];
  ORDER.forEach((s) => { for (let i = 0; i < (status?.[s] || 0); i++) cells.push(s); });
  return <span className="cells">{cells.map((s, i) => <i key={i} className={`cell ${s}`} title={s} />)}</span>;
}

function Census({ hospitals, selected, onSelect }) {
  return (
    <Panel>
      <table className="census">
        <thead>
          <tr>
            <th>Hospital</th>
            {[1, 2, 3].map((t) => <th key={t}>{TYPE_LABEL[t]}</th>)}
            <th style={{ textAlign: 'right' }}>Free</th>
          </tr>
        </thead>
        <tbody>
          {hospitals.map((h) => {
            const free = Object.values(h.types).reduce((n, t) => n + (t.free || 0), 0);
            return (
              <tr key={h.hospital_id} className={`pick ${selected === h.hospital_id ? 'sel' : ''}`} onClick={() => onSelect(h.hospital_id)}>
                <td><div className="hname">{h.name}</div><div className="hzone">{h.zone}</div></td>
                {[1, 2, 3].map((t) => <td key={t}><Cells status={h.types[t]?.status} /></td>)}
                <td style={{ textAlign: 'right' }}><span className={`free-n ${free ? '' : 'zero'}`}>{free}</span></td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </Panel>
  );
}

// Hospitals placed by latitude and longitude; a blue ring means free beds right now.
function CityMap({ hospitals, areas, selected, onSelect }) {
  const lat = [12.82, 13.12];
  const lon = [77.52, 77.78];
  const W = 420;
  const H = 440;
  const x = (v) => 24 + ((v - lon[0]) / (lon[1] - lon[0])) * (W - 48);
  const y = (v) => 24 + ((lat[1] - v) / (lat[1] - lat[0])) * (H - 48);
  return (
    <svg className="map-svg" viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Hospitals on the city map">
      {(areas || []).filter((a) => !hospitals.some((h) => h.zone === a.name)).map((a) => (
        <g key={a.name}>
          <circle cx={x(a.lon)} cy={y(a.lat)} r="1.6" fill="#c3ccd3" />
          <text x={x(a.lon) + 5} y={y(a.lat) + 3.5} fontSize="9.5" fill="#a4b0ba" fontFamily="Barlow">{a.name}</text>
        </g>
      ))}
      {hospitals.map((h) => {
        const free = Object.values(h.types).reduce((n, t) => n + (t.free || 0), 0);
        const sel = selected === h.hospital_id;
        const cx = x(h.longitude);
        const cy = y(h.latitude);
        return (
          <g key={h.hospital_id} style={{ cursor: 'pointer' }} onClick={() => onSelect(h.hospital_id)}>
            {free > 0 && <circle cx={cx} cy={cy} r={9 + free * 2.5} fill="none" stroke={BLUE} strokeWidth="1" opacity="0.45" />}
            <circle cx={cx} cy={cy} r={sel ? 7 : 5.5} fill={sel ? INK : free ? BLUE : '#fff'} stroke={free ? BLUE : GREY} strokeWidth="1.6" />
            <text x={cx + 12} y={cy - 3} fontSize="12" fontWeight="600" fill={INK} fontFamily="Barlow">{h.zone}</text>
            <text x={cx + 12} y={cy + 10} fontSize="10.5" fill={free ? BLUE : GREY} fontFamily="Geist Mono">{free} free</text>
          </g>
        );
      })}
    </svg>
  );
}

function BedBoard({ hospital, userId }) {
  const { data, reload } = usePoll(hospital ? `/hospitals/${hospital.hospital_id}/beds` : null, 3000, { deps: [hospital?.hospital_id] });
  const now = useNow();
  const [at, setAt] = useState(Date.now());
  const [moving, setMoving] = useState(null);
  const [target, setTarget] = useState('');
  useEffect(() => setAt(Date.now()), [data]);
  if (!hospital) return null;
  const beds = data || [];
  const wards = [...new Set(beds.map((b) => b.ward))];
  const act = async (bed, action) => {
    try { const r = await post(`/beds/${bed}/${action}`, { user_id: userId }); toast(r.message, r.ok ? '' : 'err'); reload(); }
    catch (e) { toast(e.message, 'err'); }
  };
  const move = async (from) => {
    if (!target) return;
    try {
      const r = await post('/transfers', { user_id: userId, from_bed: from, to_bed: Number(target) });
      toast(r.outcome === 'DONE' ? `Transfer done: ${r.note}` : `Transfer ${r.outcome}: ${r.error || ''}`, r.outcome === 'DONE' ? '' : 'err');
      setMoving(null); setTarget(''); reload();
    } catch (e) { toast(e.message, 'err'); }
  };
  return (
    <Panel style={{ marginTop: 18 }}>
      <div className="card-head">
        <span className="card-title">{hospital.name}</span>
        <span className="card-sub">bed board read straight from MySQL</span>
        <span className="grow" />
        {ORDER.map((s) => <Pill key={s} kind={s}>{s} {beds.filter((b) => b.status === s).length}</Pill>)}
      </div>
      <div className="card-body" style={{ paddingTop: 2 }}>
        {wards.map((w) => (
          <div key={w}>
            <div className="ward-title">{w}, {TYPE_LABEL[beds.find((b) => b.ward === w)?.bed_type_id]}</div>
            <div className="beds">
              {beds.filter((b) => b.ward === w).map((b) => {
                const left = b.seconds_left != null ? b.seconds_left - (now - at) / 1000 : null;
                return (
                  <div key={b.bed_id} className={`bed ${b.status}`}>
                    <div className="row" style={{ justifyContent: 'space-between' }}><span className="id">{b.bed_id}</span><Status value={b.status} /></div>
                    <div className="who">{b.patient ? `${b.patient}${b.age ? `, ${b.age}${b.gender || ''}` : ''}` : b.status === 'HELD' ? `hold ${b.reservation_id}` : ' '}</div>
                    {b.status === 'HELD' && left != null && <div className="mono muted" style={{ fontSize: 12 }}>{left > 0 ? `${fmtClock(left)} left` : 'past expiry'}</div>}
                    {moving === b.bed_id ? (
                      <div className="acts">
                        <select className="select sm" value={target} onChange={(e) => setTarget(e.target.value)} style={{ width: '100%' }}>
                          <option value="">Move to bed...</option>
                          {beds.filter((o) => o.bed_id !== b.bed_id && (o.status === 'FREE' || o.status === 'OCCUPIED')).map((o) => (
                            <option key={o.bed_id} value={o.bed_id}>{o.bed_id} {o.status === 'FREE' ? 'free' : `swap with ${o.patient}`}</option>
                          ))}
                        </select>
                        <button className="btn sm primary" onClick={() => move(b.bed_id)}>Move</button>
                        <button className="btn sm ghost" onClick={() => setMoving(null)}>Close</button>
                      </div>
                    ) : (
                      <div className="acts">
                        {b.status === 'OCCUPIED' && <button className="btn sm" onClick={() => act(b.bed_id, 'discharge')}>Discharge</button>}
                        {b.status === 'OCCUPIED' && <button className="btn sm ghost" onClick={() => { setMoving(b.bed_id); setTarget(''); }}>Transfer</button>}
                        {b.status === 'FREE' && <button className="btn sm ghost" onClick={() => act(b.bed_id, 'maintenance')}>Maintenance</button>}
                        {b.status === 'MAINTENANCE' && <button className="btn sm ghost" onClick={() => act(b.bed_id, 'restore')}>Back in service</button>}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          </div>
        ))}
      </div>
    </Panel>
  );
}

export default function BedsView() {
  const { meta, userId } = useApp();
  const { data } = usePoll('/dashboard', 4000);
  const [sel, setSel] = useState(1);
  const hospitals = data?.hospitals || [];
  const freeOf = (t) => hospitals.reduce((n, h) => n + (h.types[t]?.free || 0), 0);
  const st = data?.status_totals || {};
  const selected = hospitals.find((h) => h.hospital_id === sel);
  return (
    <div>
      <div className="view-head">
        <div className="grow">
          <h2 className="h2">Beds across the city</h2>
          <p className="muted">One square per bed. Counts come from Redis, refreshed from MySQL after every commit. Pick a hospital to see its beds.</p>
        </div>
        <span className="pill outline">{data?.source === 'redis' ? 'counts from Redis' : 'counts from MySQL, Redis is down'}</span>
      </div>
      <div className="kpis">
        <Kpi label="Free ICU" value={freeOf(1)} sub="city-wide" kind="free" />
        <Kpi label="Free with ventilator" value={freeOf(2)} sub="city-wide" kind="free" />
        <Kpi label="Free oxygen" value={freeOf(3)} sub="city-wide" kind="free" />
        <Kpi label="On hold" value={st.HELD} sub="30 minute holds" kind="held" />
        <Kpi label="Occupied" value={st.OCCUPIED} sub="admitted patients" />
        <Kpi label="Maintenance" value={st.MAINTENANCE} sub="out of service" />
      </div>
      <div className="dash-grid">
        <div>
          <Census hospitals={hospitals} selected={sel} onSelect={setSel} />
          <div className="legend">
            <span><i className="cell FREE" /> free</span>
            <span><i className="cell HELD" /> on hold</span>
            <span><i className="cell OCCUPIED" /> occupied</span>
            <span><i className="cell MAINTENANCE" /> maintenance</span>
          </div>
        </div>
        <Panel>
          <div className="card-head"><span className="card-title">Bengaluru</span><span className="card-sub">hospitals in the Redis GEO set</span></div>
          <CityMap hospitals={hospitals} areas={meta?.areas} selected={sel} onSelect={setSel} />
        </Panel>
      </div>
      <BedBoard hospital={selected} userId={userId} />
    </div>
  );
}
