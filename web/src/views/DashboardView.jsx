import { useEffect, useState } from 'react';
import { useApp } from '../App.jsx';
import CountUp from '../components/reactbits/CountUp.jsx';
import GlareHover from '../components/reactbits/GlareHover.jsx';
import { Panel, Pill, Status } from '../components/ui.jsx';
import { fmtClock, post, TYPE_LABEL, TYPE_SHORT } from '../lib/api.js';
import { toast, useNow, usePoll } from '../lib/hooks.js';

function Kpi({ label, value, sub, kind }) {
  return (
    <Panel>
      <div className={`kpi ${kind || ''}`}>
        <div className="k">{label}</div>
        <div className="v"><CountUp to={value || 0} from={0} duration={0.9} trigger="load" /></div>
        <div className="s">{sub}</div>
      </div>
    </Panel>
  );
}

// Hospitals placed by latitude / longitude; ring size = free beds of all types.
function CityMap({ hospitals, areas, selected, onSelect }) {
  const lat = [12.82, 13.12];
  const lon = [77.52, 77.78];
  const W = 420;
  const H = 430;
  const x = (v) => 20 + ((v - lon[0]) / (lon[1] - lon[0])) * (W - 40);
  const y = (v) => 20 + ((lat[1] - v) / (lat[1] - lat[0])) * (H - 40);
  return (
    <svg className="map-svg" viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Hospitals on the city map">
      <rect x="0" y="0" width={W} height={H} fill="#f7f6f2" />
      {[0, 1, 2, 3, 4].map((i) => <line key={`h${i}`} x1="0" x2={W} y1={(i + 1) * (H / 6)} y2={(i + 1) * (H / 6)} stroke="#ecebe5" />)}
      {[0, 1, 2, 3, 4].map((i) => <line key={`v${i}`} y1="0" y2={H} x1={(i + 1) * (W / 6)} x2={(i + 1) * (W / 6)} stroke="#ecebe5" />)}
      {(areas || []).map((a) => (
        <g key={a.name}>
          <circle cx={x(a.lon)} cy={y(a.lat)} r="1.8" fill="#c4c2ba" />
          <text x={x(a.lon) + 4} y={y(a.lat) + 3} fontSize="8.5" fill="#a3a199" fontFamily="IBM Plex Sans">{a.name}</text>
        </g>
      ))}
      {hospitals.map((h) => {
        const free = Object.values(h.types).reduce((n, t) => n + (t.free || 0), 0);
        const sel = selected === h.hospital_id;
        const cx = x(h.longitude);
        const cy = y(h.latitude);
        return (
          <g key={h.hospital_id} style={{ cursor: 'pointer' }} onClick={() => onSelect(h.hospital_id)}>
            <circle cx={cx} cy={cy} r={8 + free * 3} fill={free ? '#1d7a46' : '#b42d24'} opacity="0.12" />
            <circle cx={cx} cy={cy} r={sel ? 7 : 5.5} fill={sel ? '#0f5f4b' : '#fff'} stroke={free ? '#1d7a46' : '#b42d24'} strokeWidth="2" />
            <text x={cx + 10} y={cy - 6} fontSize="10.5" fontWeight="600" fill="#17191c" fontFamily="IBM Plex Sans">{h.zone}</text>
            <text x={cx + 10} y={cy + 6} fontSize="9.5" fill="#6c7078" fontFamily="IBM Plex Mono">{free} free</text>
          </g>
        );
      })}
    </svg>
  );
}

function HospitalCard({ h, selected, onSelect }) {
  return (
    <GlareHover background="#fff" borderRadius="8px" borderColor="transparent" glareColor="#0f5f4b" glareOpacity={0.07}
      glareSize={220} transitionDuration={700} style={{ width: '100%', height: 'auto', display: 'block' }}>
      <button className={`hosp ${selected ? 'sel' : ''}`} onClick={() => onSelect(h.hospital_id)}>
        <div className="name">{h.name}</div>
        <div className="zone">{h.zone} · hospital {h.hospital_id}</div>
        {[1, 2, 3].map((t) => {
          const info = h.types[t] || { status: {}, total: 0 };
          const st = info.status || {};
          const total = info.total || 1;
          return (
            <div key={t} className="typebar">
              <span className="muted">{TYPE_LABEL[t]}</span>
              <span className="bar">
                <i style={{ width: `${((st.FREE || 0) / total) * 100}%`, background: 'var(--free)' }} />
                <i style={{ width: `${((st.HELD || 0) / total) * 100}%`, background: 'var(--held)' }} />
                <i style={{ width: `${((st.OCCUPIED || 0) / total) * 100}%`, background: '#9aa3b1' }} />
                <i style={{ width: `${((st.MAINTENANCE || 0) / total) * 100}%`, background: '#cfd1d5' }} />
              </span>
              <span className="n" style={{ color: info.free ? 'var(--free)' : 'var(--faint)' }}>{info.free ?? '?'}</span>
            </div>
          );
        })}
      </button>
    </GlareHover>
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
    <Panel style={{ marginTop: 16 }}>
      <div className="card-head">
        <span className="card-title">{hospital.name}</span>
        <span className="card-sub">bed board, live from MySQL · {beds.length} beds</span>
        <span className="grow" />
        {['FREE', 'HELD', 'OCCUPIED', 'MAINTENANCE'].map((s) => <Pill key={s} kind={s}>{s} {beds.filter((b) => b.status === s).length}</Pill>)}
      </div>
      <div className="card-body" style={{ paddingTop: 2 }}>
        {wards.map((w) => (
          <div key={w}>
            <div className="ward-title">{w} · {TYPE_LABEL[beds.find((b) => b.ward === w)?.bed_type_id]}</div>
            <div className="beds">
              {beds.filter((b) => b.ward === w).map((b) => {
                const left = b.seconds_left != null ? b.seconds_left - (now - at) / 1000 : null;
                return (
                  <div key={b.bed_id} className={`bed ${b.status}`}>
                    <div className="row" style={{ justifyContent: 'space-between' }}><span className="id">{b.bed_id}</span><Status value={b.status} /></div>
                    <div className="who">{b.patient ? `${b.patient}${b.age ? `, ${b.age}${b.gender || ''}` : ''}` : b.status === 'HELD' ? `hold #${b.reservation_id}` : ' '}</div>
                    {b.status === 'HELD' && left != null && <div className="mono muted" style={{ fontSize: 11 }}>{left > 0 ? `${fmtClock(left)} left` : 'past expiry'}</div>}
                    {moving === b.bed_id ? (
                      <div className="acts">
                        <select className="select sm" value={target} onChange={(e) => setTarget(e.target.value)} style={{ width: '100%' }}>
                          <option value="">Move to bed...</option>
                          {beds.filter((x) => x.bed_id !== b.bed_id && (x.status === 'FREE' || x.status === 'OCCUPIED')).map((x) => (
                            <option key={x.bed_id} value={x.bed_id}>{x.bed_id} {x.status === 'FREE' ? 'free' : `swap with ${x.patient}`}</option>
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

export default function DashboardView() {
  const { meta, userId, openConsole } = useApp();
  const { data } = usePoll('/dashboard', 4000);
  const [sel, setSel] = useState(1);
  const hospitals = data?.hospitals || [];
  const freeOf = (t) => hospitals.reduce((n, h) => n + (h.types[t]?.free || 0), 0);
  const st = data?.status_totals || {};
  const selected = hospitals.find((h) => h.hospital_id === sel);
  return (
    <div>
      <div className="page-head">
        <div className="grow">
          <h1>City dashboard</h1>
          <p>Free-bed numbers come from Redis counters (<span className="mono">free:hospital:type</span>), refreshed from MySQL after every commit.
            Bed boards read MySQL directly.</p>
        </div>
        <Pill kind={data?.source === 'redis' ? 'redis' : 'warn'}>{data?.source === 'redis' ? 'source: Redis counters' : 'source: MySQL fallback'}</Pill>
        <button className="linkbtn" onClick={() => openConsole('redis')}>Compare with MySQL</button>
      </div>
      <div className="kpis">
        <Kpi label="Free ICU" value={freeOf(1)} sub={TYPE_SHORT[1] + ' beds city-wide'} kind="free" />
        <Kpi label="Free ventilator" value={freeOf(2)} sub="ICU + ventilator" kind="free" />
        <Kpi label="Free oxygen" value={freeOf(3)} sub="oxygen-supported" kind="free" />
        <Kpi label="Held" value={st.HELD} sub="30 min holds" kind="held" />
        <Kpi label="Occupied" value={st.OCCUPIED} sub="admitted patients" />
        <Kpi label="Maintenance" value={st.MAINTENANCE} sub="out of service" />
      </div>
      <div className="dash-grid">
        <Panel>
          <div className="card-head"><span className="card-title">Bengaluru</span><span className="card-sub">hospitals in the Redis GEO set</span></div>
          <CityMap hospitals={hospitals} areas={meta?.areas} selected={sel} onSelect={setSel} />
        </Panel>
        <div className="hosp-list">
          {hospitals.map((h) => <HospitalCard key={h.hospital_id} h={h} selected={sel === h.hospital_id} onSelect={setSel} />)}
        </div>
      </div>
      <BedBoard hospital={selected} userId={userId} />
    </div>
  );
}
