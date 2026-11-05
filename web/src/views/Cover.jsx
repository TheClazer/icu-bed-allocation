import { useEffect, useState } from 'react';
import GradientASCII from '../components/reactbits/GradientASCII.jsx';
import TechText from '../components/reactbits/TechText.jsx';
import TextCursor from '../components/reactbits/TextCursor.jsx';
import { api } from '../lib/api.js';

// The one loud moment of the interface: shown when the app opens, then out of the way.
export default function Cover({ onEnter, BrandMark }) {
  const [stats, setStats] = useState(null);
  useEffect(() => {
    let stop = false;
    const load = () => Promise.all([api('/dashboard'), api('/metrics')])
      .then(([d, m]) => {
        if (stop) return;
        const free = d.hospitals.reduce((n, h) => n + Object.values(h.types).reduce((k, t) => k + (t.free || 0), 0), 0);
        setStats({
          free, held: d.status_totals?.HELD || 0, hospitals: d.hospitals.length,
          qps: Math.round(m.mysql?.rates?.qps || 0), lag: m.replica?.lag_ms,
        });
      })
      .catch(() => {});
    load();
    const t = setInterval(load, 3000);
    return () => { stop = true; clearInterval(t); };
  }, []);

  return (
    <div className="cover">
      <div className="cover-ascii">
        <GradientASCII
          lightMode
          shape="rise"
          colors={['#d3def8', '#8eaaea', '#3f69da', '#1f4fd1']}
          characters=" .:-=+x#%@"
          cellSize={15}
          density={0.72}
          glyphOpacity={0.75}
          gradientOpacity={0.55}
          glow={0.05}
          flicker={0.15}
          speed={0.55}
          grain={0.03}
          scale={1.15}
          fontFamily="'Geist Mono', ui-monospace, Consolas, monospace"
        />
      </div>
      <TextCursor
        mode="ribbon"
        text="SELECT bed_id FROM bed WHERE status = 'FREE' FOR UPDATE SKIP LOCKED;"
        fontSize={12}
        fontWeight={500}
        fontFamily="'Geist Mono', ui-monospace, monospace"
        color="#1f4fd1"
        spacing={1}
        shrink={0.3}
        fade={0.75}
        smoothing={0.35}
        randomFloat={false}
        popIn={false}
      >
        <div className="cover-inner">
          <header className="cover-top">
            <BrandMark />
            <div>
              <div className="brand-title">City ICU bed allocation</div>
              <div className="brand-sub">A database systems project on MySQL 8 and Redis 7</div>
            </div>
            <div className="who">DBMS Lab CD252IA, RV College of Engineering<br />Rayyan Shaikh and Pooja Nagesh</div>
          </header>

          <main className="cover-center">
            <div className="cover-word">
              <TechText
                text="ICU DBMS"
                fontFamily="'Barlow Condensed'"
                fontWeight={700}
                fontSize={240}
                letterSpacing={-0.01}
                color="#13202b"
                accentColor="#1f4fd1"
                reveal="letter"
                intro="assemble"
                introDuration={1.8}
                guides
                sweep={false}
                specks={10}
              />
            </div>
            <p className="cover-lede">
              Hospitals across Bengaluru share one MySQL database of ICU, ventilator and oxygen beds.
              Every booking is a transaction you can watch.
            </p>
            <div className="cover-actions">
              <button type="button" className="btn primary lg" onClick={onEnter}>Open the control room</button>
              <a className="btn lg" href="/console" target="_blank" rel="noreferrer">Open the database monitor</a>
            </div>
          </main>

          <footer className="cover-vitals" aria-live="polite">
            <div className="v"><b>{stats ? stats.free : '-'}</b><span>free beds in {stats?.hospitals ?? 7} hospitals</span></div>
            <div className="v"><b>{stats ? stats.held : '-'}</b><span>beds on a 30 minute hold</span></div>
            <div className="v"><b>{stats ? stats.qps : '-'}</b><span>queries a second on the primary</span></div>
            <div className="v"><b>{stats?.lag ?? '-'}<small style={{ fontSize: 16 }}> ms</small></b><span>replica behind the primary</span></div>
          </footer>
        </div>
      </TextCursor>
    </div>
  );
}
