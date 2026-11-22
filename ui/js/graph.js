// Lays out a workflow as columns of step nodes and draws the arrows between them.
// Shared by the Run screen and the Workflows screen.
//
// model = {
//   columns: [{ nodes: [{ key, ... }] }],      // in run order; a foreach or parallel column has several
//   extras:  [{ node, under }],                // steps reached only through on_fail, under column `under`
//   jumps:   [{ from, to, kind, label }],      // from: column index or extra key; to: column index or extra key
// }
// opts = { layout: 'h' | 'v', renderNode(node) -> Element, seqClass(i) -> css class for the arrow into column i }
import { h, esc, raw } from './util.js';

const NW = 120, NH = 136, GAP = 48, CH = 12;

export function renderGraph(model, opts) {
  const horiz = opts.layout !== 'v';
  const uS = horiz ? NW : NH, vS = horiz ? NH : NW; // node size along the flow (u) and across it (v)
  const pU = uS + GAP, pV = vS + GAP;
  const cols = model.columns;
  const maxN = Math.max(1, ...cols.map((c) => c.nodes.length));
  const jumps = model.jumps || [];
  const extras = model.extras || [];
  const above = jumps.filter((j) => j.kind === 'reject');
  const below = jumps.filter((j) => j.kind !== 'reject' && typeof j.from === 'number' && typeof j.to === 'number');
  const top = above.length ? 40 + above.length * CH : 8;
  const coreV = top + maxN * pV - GAP;
  const laneV = coreV + 40 + below.length * CH;
  const pos = new Map(); // node key -> {u, v}

  cols.forEach((c, ci) => c.nodes.forEach((n, i) => pos.set(n.key, { u: ci * pU, v: top + ((maxN - c.nodes.length) * pV) / 2 + i * pV })));
  const perCol = {}; // two fix-only steps under one column stack downwards
  extras.forEach((x) => { const i = perCol[x.under] = (perCol[x.under] ?? -1) + 1; pos.set(x.node.key, { u: x.under * pU, v: laneV + i * pV }); });

  const totalU = Math.max(cols.length, 1) * pU - GAP;
  const depth = Math.max(0, ...Object.values(perCol));
  const totalV = (extras.length ? laneV + depth * pV + vS : coreV + (below.length ? 24 + below.length * CH : 0)) + 28;
  const W = horiz ? totalU : totalV, H = horiz ? totalV : totalU;
  const xy = (u, v) => (horiz ? [u, v] : [v, u]);
  const pt = (u, v) => xy(u, v).join(' ');
  const paths = [], labels = [];
  const line = (pts, cls) => paths.push(`<path class="${cls}" d="M ${pts.map(([u, v]) => pt(u, v)).join(' L ')}"/>`);
  // An arrowhead at (u, v) pointing along +u, -u, +v or -v.
  const arrow = (u, v, dir, cls) => {
    const s = 4.5, tri = { '+u': [[-s * 1.4, -s], [0, 0], [-s * 1.4, s]], '-u': [[s * 1.4, -s], [0, 0], [s * 1.4, s]],
      '+v': [[-s, -s * 1.4], [0, 0], [s, -s * 1.4]], '-v': [[-s, s * 1.4], [0, 0], [s, s * 1.4]] }[dir];
    paths.push(`<path class="${cls}" style="stroke-dasharray:none" d="M ${tri.map(([a, b]) => pt(u + a, v + b)).join(' L ')}"/>`);
  };
  const label = (u, v, text, kind) => { const [x, y] = xy(u, v); labels.push(h('div.edge-label.' + kind, { style: { left: x + 'px', top: y + 'px' } }, text)); };
  const mid = (key) => { const p = pos.get(key); return { u: p.u + uS / 2, v: p.v + vS / 2, u0: p.u, u1: p.u + uS, v0: p.v, v1: p.v + vS }; };

  // Arrows from each column to the next.
  for (let ci = 1; ci < cols.length; ci++) {
    const a = cols[ci - 1].nodes, b = cols[ci].nodes, cls = opts.seqClass ? opts.seqClass(ci) : 'e-todo';
    const paired = a.length > 1 && a.length === b.length && a.every((n, i) => n.repo && n.repo === b[i].repo);
    if (paired || (a.length === 1 && b.length === 1)) {
      a.forEach((n, i) => { const s = mid(n.key), d = mid(b[i].key); line([[s.u1, s.v], [d.u0 - 2, d.v]], cls); arrow(d.u0 - 1, d.v, '+u', cls); });
    } else {
      const bus = (ci - 1) * pU + uS + GAP / 2;
      const vs = [...a, ...b].map((n) => mid(n.key).v);
      a.forEach((n) => { const s = mid(n.key); line([[s.u1, s.v], [bus, s.v]], cls); });
      line([[bus, Math.min(...vs)], [bus, Math.max(...vs)]], cls);
      b.forEach((n) => { const d = mid(n.key); line([[bus, d.v], [d.u0 - 2, d.v]], cls); arrow(d.u0 - 1, d.v, '+u', cls); });
    }
  }

  // Jumps: on_fail and next below the graph, on_reject above it.
  const colEdge = (ci, side) => { // the middle of a column's outer edge
    const ns = cols[ci].nodes.map((n) => mid(n.key));
    return { u: ns[0].u, v: side === 'top' ? Math.min(...ns.map((n) => n.v0)) : Math.max(...ns.map((n) => n.v1)) };
  };
  const endOf = (ref, side) => (typeof ref === 'number' ? colEdge(ref, side) : { u: mid(ref).u, v: side === 'top' ? mid(ref).v0 : mid(ref).v1 });
  let ai = 0, bi = 0;
  for (const j of jumps) {
    const cls = { fail: 'e-fail', reject: 'e-reject', next: 'e-next' }[j.kind];
    const text = j.label || { fail: 'on fail', reject: 'if rejected', next: 'then' }[j.kind];
    if (j.kind === 'reject') {
      const s = endOf(j.from, 'top'), d = endOf(j.to, 'top'), ch = top - 20 - ai++ * CH;
      line([[s.u + 8, s.v], [s.u + 8, ch], [d.u + 8, ch], [d.u + 8, d.v - 2]], cls); arrow(d.u + 8, d.v - 1, '+v', cls);
      label(Math.min(s.u, d.u) + Math.abs(s.u - d.u) / 2 - 30, ch - 18, text, 'reject');
    } else if (typeof j.to === 'string' || typeof j.from === 'string') { // to or from a lane step
      const s = endOf(j.from, 'bottom'), dTop = typeof j.to === 'string';
      const d = dTop ? { u: mid(j.to).u, v: mid(j.to).v0 } : endOf(j.to, 'bottom');
      const off = j.kind === 'next' ? 14 : -14;
      if (dTop && Math.abs(s.u - d.u) < 1) { // straight down to the lane step
        line([[s.u + off, s.v], [d.u + off, d.v - 2]], cls); arrow(d.u + off, d.v - 1, '+v', cls);
      } else if (!dTop) { // from a lane step back up to a column
        const from = { u: mid(j.from).u, v: mid(j.from).v0 };
        if (Math.abs(from.u - d.u) < 1) { line([[from.u + off, from.v], [d.u + off, d.v + 2]], cls); arrow(d.u + off, d.v + 1, '-v', cls); }
        else { const ch = from.v - 16; line([[from.u, from.v], [from.u, ch], [d.u + off, ch], [d.u + off, d.v + 2]], cls); arrow(d.u + off, d.v + 1, '-v', cls); }
        label(d.u + off + 6, (from.v + d.v) / 2 - 8, text, j.kind);
        continue;
      } else { const ch = d.v - 16; line([[s.u + off, s.v], [s.u + off, ch], [d.u + off, ch], [d.u + off, d.v - 2]], cls); arrow(d.u + off, d.v - 1, '+v', cls); }
      label(s.u + off - (j.kind === 'next' ? -6 : 56), (s.v + d.v) / 2 - 8, text, j.kind);
    } else {
      const s = endOf(j.from, 'bottom'), d = endOf(j.to, 'bottom'), ch = coreV + 20 + bi++ * CH;
      line([[s.u - 8, s.v], [s.u - 8, ch], [d.u - 8, ch], [d.u - 8, d.v + 2]], cls); arrow(d.u - 8, d.v + 1, '-v', cls);
      label(Math.min(s.u, d.u) + Math.abs(s.u - d.u) / 2 - 24, ch + 2, text, j.kind);
    }
  }

  const svg = `<svg class="edges" width="${W}" height="${H}" viewBox="0 0 ${W} ${H}" aria-hidden="true">${paths.join('')}</svg>`;
  const nodes = [];
  for (const [key, p] of pos) {
    const n = cols.flatMap((c) => c.nodes).find((x) => x.key === key) || extras.find((x) => x.node.key === key).node;
    const el = opts.renderNode(n);
    const [x, y] = xy(p.u, p.v);
    Object.assign(el.style, { left: x + 'px', top: y + 'px' });
    nodes.push(el);
  }
  return h('div.graph', { style: { width: W + 'px', height: H + 'px' }, html: raw(svg) }, nodes, labels);
}

// The columns of a workflow's steps. `repos(step)` gives the repos a foreach step runs for.
// Steps with `next` are reached only through on_fail: they go in the lane under their `next` target.
export function columnsOf(steps, repos, keyOf = (s, r) => (r ? `${s.id}@${r}` : s.id)) {
  const columns = [], extras = [], where = new Map();
  const nodesFor = (s) => (s.foreach ? (repos(s).length ? repos(s) : ['…']).map((r) => ({ key: keyOf(s, r), step: s, repo: r })) : [{ key: keyOf(s), step: s }]);
  steps.forEach((s) => {
    if (s.parallel) { const nodes = s.parallel.flatMap(nodesFor); s.parallel.forEach((p) => where.set(p.id, columns.length)); columns.push({ nodes, group: s }); }
    else if (s.next) extras.push({ step: s });
    else { where.set(s.id, columns.length); columns.push({ nodes: nodesFor(s), step: s }); }
  });
  const lane = extras.map((x) => ({ node: { key: keyOf(x.step), step: x.step, extra: true }, under: where.has(x.step.next) ? where.get(x.step.next) : Math.max(0, columns.length - 1) }));
  lane.forEach((x) => where.set(x.node.step.id, x.node.key));
  const jumps = [];
  const all = steps.flatMap((s) => (s.parallel ? s.parallel : [s]));
  for (const s of all) {
    const from = where.get(s.id);
    if (from == null) continue;
    for (const [field, kind] of [['on_fail', 'fail'], ['on_reject', 'reject'], ['next', 'next']]) {
      const to = s[field] != null ? where.get(s[field]) : null;
      if (to == null) continue;
      if (kind === 'reject' && typeof to !== 'number') continue;
      jumps.push({ from, to, kind });
    }
  }
  return { columns, extras: lane, jumps, where };
}

export const escAttr = esc;
