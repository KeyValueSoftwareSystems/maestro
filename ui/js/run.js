// The Run screen: one run's workflow as a graph, coloured by state.yaml, with a details drawer.
import * as api from './api.js';
import { h, ico, icon, face, AGENTS, ago, took, markdown } from './util.js';
import { renderGraph, columnsOf } from './graph.js';
import { drawer } from './drawer.js';

const RUNS = '.maestro/runs';
let layout = localGet('maestro.layout') || 'h';

function localGet(k) { try { return localStorage.getItem(k); } catch { return null; } }
function localSet(k, v) { try { localStorage.setItem(k, v); } catch { /* private mode */ } }

// Every run, active ones first, then newest.
export async function listRuns() {
  const dirs = (await api.list(RUNS).catch(() => [])).filter((d) => d.dir);
  const runs = await Promise.all(dirs.map(async (d) => {
    const st = (await api.readYaml(`${RUNS}/${d.name}/state.yaml`)) || {};
    return { slug: d.name, status: st.status || 'unknown', workflow: st.workflow || '?', mtime: d.mtime };
  }));
  const rank = (s) => (s === 'running' ? 0 : s === 'waiting' ? 1 : 2);
  return runs.sort((a, b) => rank(a.status) - rank(b.status) || b.mtime - a.mtime);
}

async function load(slug) {
  const dir = `${RUNS}/${slug}`;
  const [state, files, logs, req, ws] = await Promise.all([
    api.readYaml(`${dir}/state.yaml`), api.list(dir).catch(() => []), api.list(`${dir}/logs`).catch(() => []),
    api.readOr(`${dir}/requirements.md`, ''), api.readYaml('.maestro/workspace.yaml'),
  ]);
  if (!state || typeof state !== 'object') return null;
  // js-yaml reads unquoted times as Dates; keep them as ISO text so they sort and print right.
  const iso = (v) => (v instanceof Date ? v.toISOString().replace('.000Z', 'Z') : v);
  state.running = Array.isArray(state.running) ? state.running.map((e) => ({ ...e, since: iso(e.since) })) : [];
  state.history = Array.isArray(state.history) ? state.history.map((e) => ({ ...e, at: iso(e.at) })) : [];
  const wf = (await api.readYaml(`.maestro/workflows/${state.workflow}.yaml`)) || { steps: [] };
  // Show a subworkflow's steps in place, as the lead runs them.
  const steps = [];
  for (const s of wf.steps || []) {
    if (s.mode === 'workflow' && s.workflow) {
      const sub = await api.readYaml(`.maestro/workflows/${s.workflow}`);
      if (sub && sub.steps) { steps.push(...sub.steps.map((x) => ({ ...x, from: s.workflow }))); continue; }
    }
    steps.push(s);
  }
  return { slug, dir, state, wf, steps, files, logs, req, ws: ws || {} };
}

function title(req, slug) {
  const lines = req.split('\n').map((l) => l.trim()).filter(Boolean);
  const heading = lines.find((l) => /^#\s/.test(l) && !/^#\s*(requirements|request)\b/i.test(l));
  const line = heading ? heading.replace(/^#+\s*/, '') : lines.find((l) => !l.startsWith('#') && !l.startsWith('|')) || slug;
  return line.length > 110 ? line.slice(0, 107) + '…' : line;
}

const word = (v) => String(v ?? 'unknown').replace(/[^\w-]/g, ''); // safe as a class name
const matches = (e, step, repo) => e && e.step === step.id && (!repo || !e.repo || e.repo === repo);

// What a node's history says: its attempts and where it stands now.
function statusOf(R, step, repo) {
  const st = R.state, hist = (st.history || []).filter((e) => matches(e, step, repo));
  const last = hist[hist.length - 1];
  const run = (st.running || []).find((e) => matches(e, step, repo));
  const gate = step.mode === 'gate';
  const ended = last && last.at && run && run.since && last.at > run.since; // the lead writes history a moment before it clears running
  if (run && gate && !ended) return { s: 'waiting', hist };
  if (run && !ended) return { s: 'running', hist, since: run.since };
  if (st.current === step.id && !last && (gate || st.status === 'waiting') && st.status !== 'done') return { s: 'waiting', hist };
  if (st.current === step.id && st.status === 'waiting' && last && last.status !== 'pass' && last.status !== 'approved') return { s: last.status === 'fail' ? 'failed' : 'waiting', hist, last };
  if (!last) return { s: 'pending', hist };
  const s = { pass: 'done', approved: 'done', fail: 'failed', rejected: 'rejected', interrupted: 'interrupted' }[last.status] || 'done';
  return { s, hist, last };
}

function label(step, S) {
  const gate = step.mode === 'gate';
  return { done: gate ? 'Approved' : 'Done', running: step.mode === 'exec' ? 'Running…' : (AGENTS[step.agent] || AGENTS.worker).verb,
    failed: 'Failed', waiting: gate ? 'Waiting on you' : 'Needs you', rejected: 'Rejected', interrupted: 'Interrupted', pending: 'Pending' }[S.s];
}
const cls = (s) => ({ done: 's-done', running: 's-running', failed: 's-failed', pending: 's-pending' }[s] || 's-waiting');

function repos(R) {
  const v = R.state.vars && R.state.vars.repos;
  return Array.isArray(v) && v.length ? v : Object.keys(R.ws.repos || {});
}

// ${name} -> its value, as the lead fills it in.
function fill(text, R, repo) {
  return String(text || '').replace(/\$\{(\w+)\}/g, (m, k) => {
    if (k === 'slug') return R.slug;
    if (k === 'run') return R.dir;
    if (k === 'repo' && repo) return repo;
    const v = (R.state.vars || {})[k];
    if (v == null) return m;
    if (typeof v === 'object' && !Array.isArray(v)) return repo && v[repo] != null ? v[repo] : Object.entries(v).map(([a, b]) => `${a}: ${b}`).join(', ');
    return Array.isArray(v) ? v.join(', ') : String(v);
  });
}

let showing = 0;
export async function showRun(view, slug, keepOpen) {
  const me = ++showing;
  const R = await load(slug);
  if (me !== showing) return null; // a newer redraw, or another run, took over
  if (!R) { view.replaceChildren(h('div.card.empty', `No run called ${slug}.`)); return null; }
  const { columns, extras, jumps } = columnsOf(R.steps, () => repos(R));
  const nodes = [...columns.flatMap((c) => c.nodes), ...extras.map((x) => x.node)];
  for (const n of nodes) n.S = statusOf(R, n.step, n.repo);
  const core = columns.flatMap((c) => c.nodes);
  const done = core.filter((n) => n.S.s === 'done').length;
  const st = R.state;
  const pillT = st.status !== 'done' && core.some((n) => n.S.s === 'waiting' && n.step.mode === 'gate') ? 'Waiting on you' : String(st.status || 'unknown');

  const open = (n) => { drawer.open(n.key, () => details(R, n)); showRun.sel = n.key; graphEl.querySelectorAll('.node').forEach((b) => b.classList.toggle('sel', b.dataset.key === n.key)); };
  const graph = () => renderGraph({ columns, extras, jumps }, {
    layout,
    seqClass: (i) => (columns[i].nodes.some((n) => n.S.s === 'running') ? 'e-run' : columns[i].nodes.some((n) => n.S.s !== 'pending') ? 'e-done' : 'e-todo'),
    renderNode: (n) => h('button.node.' + cls(n.S.s), { type: 'button', 'data-key': n.key, class: 'node ' + cls(n.S.s) + (drawer.key === n.key ? ' sel' : ''),
      'aria-label': `${n.step.id}${n.repo ? ' ' + n.repo : ''}, ${label(n.step, n.S).replace(/…$/, '')}. Show details`, onclick: () => open(n) },
    face(n.step), h('span', h('b', n.step.id), n.repo ? [' ', h('span.repo', n.repo)] : null, h('br'),
      h('span.st', n.S.s === 'running' ? h('span.spin') : null, n.S.s === 'done' ? ico('check', 14) : n.S.s === 'failed' ? ico('x', 14) : null, label(n.step, n.S)))),
  });
  let graphEl = h('div.graph-wrap', graph());
  const seg = h('div.seg', { role: 'tablist', 'aria-label': 'Layout' },
    ['h', 'v'].map((l) => h('button', { type: 'button', role: 'tab', 'aria-selected': String(layout === l), onclick: () => {
      layout = l; localSet('maestro.layout', l);
      seg.querySelectorAll('button').forEach((b, i) => b.setAttribute('aria-selected', String(['h', 'v'][i] === l)));
      const g = h('div.graph-wrap', graph()); graphEl.replaceWith(g); graphEl = g;
    } }, l === 'h' ? 'Horizontal' : 'Vertical')));

  const last = (st.history || [])[(st.history || []).length - 1];
  const waitingGate = core.find((n) => n.S.s === 'waiting' && n.step.mode === 'gate');
  const failed = nodes.find((n) => n.S.s === 'failed' && st.status === 'waiting');
  let banner = null;
  if (waitingGate) banner = h('div.banner.warn', ico('pause'), h('span.msg', `Waiting for you at ${waitingGate.step.id}. Answer in the Claude Code conversation.`), h('button.link', { type: 'button', onclick: () => open(waitingGate) }, 'Open'));
  else if (failed) banner = h('div.banner.bad', ico('alert'), h('span.msg', `${failed.step.id}${failed.repo ? ' failed on ' + failed.repo : ' failed'}: ${(failed.S.last && failed.S.last.note) || 'see details'}`), h('button.link', { type: 'button', onclick: () => open(failed) }, failed.step.mode === 'exec' ? 'View log' : 'Details'));
  else if (st.status === 'waiting') banner = h('div.banner.warn', ico('pause'), h('span.msg', `Paused at ${st.current}${last && last.note ? ': ' + last.note : ''}. Answer in Claude Code.`));
  else if (st.status === 'done') banner = h('div.banner', ico('check'), h('span.msg', 'This run is finished.'));

  const lastAt = [...(st.history || []).map((e) => e.at), ...(st.running || []).map((e) => e.since)].filter(Boolean).sort().pop();
  view.replaceChildren(
    h('div', { style: { display: 'flex', flexDirection: 'column', gap: '12px' } },
      h('h1', title(R.req, slug)),
      h('div.meta', h('span.pill.t-' + (pillT === 'Waiting on you' ? 'waiting' : word(st.status)), pillT[0].toUpperCase() + pillT.slice(1)),
        h('span.mono', st.workflow), h('span.dot', '·'), h('span', repos(R).join(', ') || 'no repos yet'),
        h('span.dot', '·'), h('span', `${st.steps_used || 0} of ${st.max_steps || 30} steps`),
        lastAt ? [h('span.dot', '·'), h('span', `updated ${ago(lastAt)}`)] : null),
      h('div.progress', h('div.bar', { role: 'img', 'aria-label': `${done} of ${core.length} steps done` },
        core.map((n) => h('span', { class: { done: 'd', failed: 'f', running: 'shimmer', pending: '' }[n.S.s] ?? 'w', style: n.S.s === 'running' ? { background: 'var(--accent)' } : null }))),
      h('span', h('b', done), ` of ${core.length} done`))),
    h('section.card', { 'aria-label': 'Workflow' },
      h('div.card-head', h('h2', 'Workflow', h('span.file', `${st.workflow}.yaml`)),
        h('div.tools', h('div.legend', [['Done', 'var(--ok)'], ['Running', 'var(--accent)'], ['Failed', 'var(--bad)'], ['Needs you', 'var(--warn)'], ['Pending', 'var(--line2)']]
          .map(([t, c]) => h('span', h('i', { style: { borderColor: c, borderStyle: t === 'Pending' ? 'dashed' : 'solid' } }), t))), seg)),
      graphEl, banner),
    h('p.hint', 'Click a step to see its instructions, what it wrote and each attempt.'));

  if (keepOpen && drawer.key) { const n = nodes.find((x) => x.key === drawer.key); if (n) drawer.open(n.key, () => details(R, n)); else drawer.close(); }
  return R;
}

async function details(R, n) {
  const step = n.step, mode = step.mode || 'agent', S = n.S;
  const who = mode === 'agent' ? `${(AGENTS[step.agent] || AGENTS.worker).name} · ${(AGENTS[step.agent] || AGENTS.worker).role}`
    : mode === 'gate' ? 'Gate · asks you' : mode === 'exec' ? 'Command · runs in the shell' : 'Workflow';
  const runs = mode === 'agent' ? (step.run === 'inline' ? 'In the conversation' : 'Subagent') : mode === 'exec' ? 'Shell' : mode === 'gate' ? 'In the conversation' : 'In place';
  const v = R.state.vars || {};
  const per = (k) => (v[k] && typeof v[k] === 'object' && n.repo ? v[k][n.repo] : null);
  const kv = [['Type', { agent: 'Agent', exec: 'Command', gate: 'Gate', workflow: 'Workflow' }[mode]], ['Runs', runs],
    mode === 'agent' && step.run !== 'inline' ? ['Model', step.model || 'default'] : null,
    n.repo ? ['Repo', n.repo] : null, per('branch') ? ['Branch', per('branch')] : null, per('worktree') ? ['Worktree', per('worktree')] : null,
    step.on_fail ? ['On fail', `go to ${step.on_fail}`] : null, step.on_reject ? ['If rejected', `back to ${step.on_reject}`] : null,
    step.next ? ['Then', `back to ${step.next}`] : null, step.template ? ['Template', step.template] : null,
    step.skills ? ['Skills', Object.entries(step.skills).map(([a, b]) => `${a}: ${b}`).join(', ')] : null,
    step.from ? ['Part of', step.from] : null].filter(Boolean);

  const text = mode === 'gate' ? step.prompt : mode === 'exec' ? (Array.isArray(step.command) ? `[${step.command.join(', ')}]` : step.command) : mode === 'workflow' ? step.workflow : step.instructions;
  const textLabel = { gate: 'Question asked', exec: 'Command', workflow: 'Runs' }[mode] || 'Instructions';

  // Files the step names under ${run}, and its command logs.
  const src = `${step.instructions || ''}\n${step.prompt || ''}`;
  const names = [...new Set([...src.matchAll(/\$\{run\}\/([\w./-]+\.[A-Za-z]+)/g)].map((m) => m[1]))];
  const have = new Set(R.files.map((f) => f.name));
  const outs = names.filter((f) => have.has(f) || have.has(f.split('/')[0])).map((f) => ({ path: `${R.dir}/${f}`, name: f }));
  const logs = R.logs.filter((f) => f.name.startsWith(`${step.id}-${n.repo ? n.repo + '.' : ''}`) || f.name === `${step.id}.log`)
    .map((f) => ({ path: `${R.dir}/logs/${f.name}`, name: `logs/${f.name}`, log: true }));
  const outputs = await Promise.all([...outs, ...logs].map(async (o) => ({ ...o, text: await api.readOr(o.path, '') })));

  const recorded = [...new Set([...(step.instructions || '').matchAll(/\bas `(\w+)`/g)].map((m) => m[1]))]
    .map((k) => [k, v[k] == null ? '—' : typeof v[k] === 'object' && !Array.isArray(v[k]) ? (n.repo ? v[k][n.repo] : Object.entries(v[k]).map(([a, b]) => `${a}: ${b}`).join(', ')) : Array.isArray(v[k]) ? v[k].join(', ') : v[k]]);

  const lastEntry = S.hist[S.hist.length - 1];
  const when = S.s === 'running' ? `Attempt ${S.hist.length + 1} · started ${ago(S.since)}`
    : lastEntry ? `${S.s === 'done' && mode === 'gate' ? 'Answered' : 'Finished'} ${ago(lastEntry.at)} · attempt ${S.hist.length}` : S.s === 'waiting' ? 'Now' : 'Not started';
  let note = null;
  if (S.s === 'waiting' && mode === 'gate') note = h('div.note.warn', ico('pause'), h('span', 'The run is waiting for your answer. Approve it, or send it back with feedback, in the Claude Code conversation.'));
  else if (lastEntry && lastEntry.note) note = h('div.note.' + ({ failed: 'bad', done: 'info' }[S.s] || 'warn'), ico(S.s === 'failed' ? 'alert' : 'file'), h('span', lastEntry.note));
  else if (S.s === 'running' && S.hist.length) note = h('div.note.bad', ico('alert'), h('span', `Retrying. Last attempt: ${S.hist[S.hist.length - 1].note || S.hist[S.hist.length - 1].status}`));

  const outEl = (o) => {
    const lines = o.text.split('\n');
    const n2 = lines.length - (o.text.endsWith('\n') ? 1 : 0);
    const preview = o.log ? lines.slice(-16).join('\n') : lines.slice(0, 14).join('\n');
    const short = () => h('pre', n2 > 14 ? (o.log ? '…\n' + preview : preview + '\n…') : preview);
    const long = () => (o.name.endsWith('.md') ? h('div.md', { html: markdown(o.text) }) : h('pre', o.text));
    const small = h('small', `${n2} lines · show all`);
    let full = false;
    const head = h('button.out-head', { type: 'button', 'aria-expanded': 'false', onclick: () => {
      full = !full;
      head.setAttribute('aria-expanded', String(full));
      small.textContent = `${n2} lines · ${full ? 'hide' : 'show all'}`;
      wrap.lastChild.replaceWith(full ? long() : short());
    } }, ico(o.log ? 'log' : 'file'), h('span.name', o.name), small);
    const wrap = h('div.out' + (o.log ? '.log' : ''), head, short());
    return wrap;
  };

  return h('div.drawer-body',
    h('div.drawer-head', face(step), h('div.who', h('b', step.id, n.repo ? [' ', h('span', { style: { fontSize: '14px', color: 'var(--muted)' } }, n.repo)] : null), h('span', who)),
      h('button.ghost', { type: 'button', 'aria-label': 'Close details', onclick: () => drawer.close(), html: icon('close', 18) })),
    h('div', { style: { display: 'flex', alignItems: 'center', gap: '10px', flexWrap: 'wrap' } },
      h('span.pill.big.t-' + ({ done: 'done', running: 'running', failed: 'failed', pending: 'pending' }[S.s] || 'waiting'), label(step, S)), h('span', { style: { fontSize: '13px', color: 'var(--muted)' } }, when)),
    note,
    h('section.sec', h('h3', 'Details'), h('dl.kv', kv.map(([k, val]) => [h('dt', k), h('dd', val)]))),
    text ? h('section.sec', h('h3', textLabel), h('pre.box', fill(text, R, n.repo).trimEnd())) : null,
    h('section.sec', h('div.sec-head', h('h3', 'Output'), h('small', 'from the run folder')),
      outputs.length ? outputs.map(outEl) : h('p.dashed', mode === 'gate' ? 'Gates write nothing.' : S.s === 'running' ? 'Still working. Files appear here when the step writes them.' : S.s === 'pending' ? 'Not run yet.' : 'This step wrote no file in the run folder.')),
    recorded.length ? h('section.sec', h('h3', 'Recorded for later steps'), h('div.vars', recorded.map(([k, val]) => h('div', h('span', k), h('span', val))))) : null,
    S.hist.length ? h('section.sec', h('h3', 'Attempts'), h('ol.attempts', [...S.hist].reverse().map((e) =>
      h('li', h('span.pill.nodot.t-' + word(e.status), String(e.status ?? '')), h('time', { datetime: String(e.at || ''), title: String(e.at || '') }, ago(e.at)), h('span', String(e.note ?? '')))))) : null,
  );
}
export { took };
