// Wait-for graph: a node per transaction, an arrow "A waits for B".
// A cycle means deadlock; its edges are drawn red.

function findCycleEdges(edges) {
  const adj = new Map();
  edges.forEach((e) => { if (!adj.has(e.from)) adj.set(e.from, []); adj.get(e.from).push(e.to); });
  const onCycle = new Set();
  const visit = (start) => {
    const stack = [[start, [start]]];
    while (stack.length) {
      const [n, path] = stack.pop();
      for (const m of adj.get(n) || []) {
        if (m === start) { for (let i = 0; i < path.length; i++) onCycle.add(`${path[i]}>${path[i + 1] || start}`); }
        else if (!path.includes(m) && path.length < 8) stack.push([m, [...path, m]]);
      }
    }
  };
  [...adj.keys()].forEach(visit);
  return onCycle;
}

export default function WaitForGraph({ nodes, edges, height = 170, victim, labels = {} }) {
  const ids = [...new Set([...(nodes || []), ...edges.flatMap((e) => [e.from, e.to])])];
  if (!ids.length) {
    return (
      <svg className="graph" viewBox="0 0 520 90" role="img" aria-label="No lock waits">
        <text x="260" y="50" textAnchor="middle" fontSize="12" fill="#96a4b0" fontFamily="Barlow">No transaction is waiting for a lock right now</text>
      </svg>
    );
  }
  const W = 520;
  const H = height;
  const cx = W / 2;
  const cy = H / 2;
  const r = ids.length <= 2 ? 150 : Math.min(190, 60 + ids.length * 22);
  const pos = {};
  ids.forEach((id, i) => {
    const a = ids.length === 1 ? 0 : Math.PI + (2 * Math.PI * i) / ids.length;
    pos[id] = { x: cx + (ids.length === 1 ? 0 : r * Math.cos(a)), y: cy + (ids.length <= 2 ? 0 : (r * 0.45) * Math.sin(a)) };
  });
  const cyc = findCycleEdges(edges);
  const pairCount = {};
  return (
    <svg className="graph" viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Wait-for graph">
      <defs>
        <marker id="wf-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0 0L10 5L0 10z" fill="#627485" /></marker>
        <marker id="wf-arrow-red" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0 0L10 5L0 10z" fill="#d23a4a" /></marker>
      </defs>
      {edges.map((e, i) => {
        const a = pos[e.from];
        const b = pos[e.to];
        if (!a || !b) return null;
        const red = cyc.has(`${e.from}>${e.to}`);
        const key = [e.from, e.to].sort().join('|');
        pairCount[key] = (pairCount[key] || 0) + 1;
        const bend = e.from < e.to ? -38 : 38;
        const mx = (a.x + b.x) / 2;
        const my = (a.y + b.y) / 2 + bend;
        const dx = b.x - a.x;
        const dy = b.y - a.y;
        const len = Math.hypot(dx, dy) || 1;
        const sx = a.x + (dx / len) * 30;
        const sy = a.y + (dy / len) * 30 + bend * 0.25;
        const ex = b.x - (dx / len) * 32;
        const ey = b.y - (dy / len) * 32 + bend * 0.25;
        return (
          <g key={i}>
            <path d={`M${sx} ${sy}Q${mx} ${my} ${ex} ${ey}`} fill="none" stroke={red ? '#d23a4a' : '#627485'} strokeWidth={red ? 2 : 1.4}
              strokeDasharray={red ? '' : '5 4'} markerEnd={`url(#${red ? 'wf-arrow-red' : 'wf-arrow'})`} />
            <text x={mx} y={my + (bend < 0 ? -6 : 14)} textAnchor="middle" fontSize="10.5" fill={red ? '#d23a4a' : '#627485'} fontFamily="Geist Mono">
              {e.label || 'waits for'}
            </text>
          </g>
        );
      })}
      {ids.map((id) => {
        const p = pos[id];
        const isVictim = victim === id;
        return (
          <g key={id}>
            <circle cx={p.x} cy={p.y} r="28" fill={isVictim ? '#fcecee' : '#fff'} stroke={isVictim ? '#d23a4a' : '#13202b'} strokeWidth="1.5" />
            <text x={p.x} y={p.y + 4} textAnchor="middle" fontSize="12.5" fontWeight="600" fill="#13202b" fontFamily="Geist Mono">{id}</text>
            {labels[id] && <text x={p.x} y={p.y + 44} textAnchor="middle" fontSize="10.5" fill="#627485" fontFamily="Barlow">{labels[id]}</text>}
            {isVictim && <text x={p.x} y={p.y - 36} textAnchor="middle" fontSize="10" fontWeight="600" fill="#d23a4a" fontFamily="Geist Mono">VICTIM, ROLLED BACK</text>}
          </g>
        );
      })}
    </svg>
  );
}

// Edges of a parsed SHOW ENGINE INNODB STATUS deadlock: each transaction waits for the
// one that holds the record it wants.
export function deadlockEdges(dl) {
  if (!dl?.transactions?.length) return { nodes: [], edges: [], victim: null, labels: {} };
  const txs = dl.transactions;
  const name = (t) => t.tx || `trx ${t.trx_id}`;
  const edges = [];
  txs.forEach((t) => {
    const want = t.waits_for?.record;
    const holder = txs.find((o) => o !== t && o.holds?.record === want);
    if (holder) edges.push({ from: name(t), to: name(holder), label: `wants bed ${want}` });
  });
  const v = txs.find((t) => t.n === dl.victim);
  return { nodes: txs.map(name), edges, victim: v ? name(v) : null, labels: Object.fromEntries(txs.map((t) => [name(t), t.holds?.record != null ? `holds bed ${t.holds.record}` : ''])) };
}
