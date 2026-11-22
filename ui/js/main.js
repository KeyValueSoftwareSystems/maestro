// Routes #/runs/<slug>, #/workflows/<name> and #/agents/<name>, fills the header picker,
// and redraws when files under .maestro/ change.
import * as api from './api.js';
import { h, AGENTS } from './util.js';
import { listRuns, showRun } from './run.js';
import { listWorkflows, showBuilder, unsaved, askNewWorkflow } from './builder.js';
import { showCast, showAgent } from './agents.js';
import { drawer } from './drawer.js';

const view = document.getElementById('view');
const picker = document.getElementById('picker');
let route = { tab: 'runs', id: '' };

function parse() {
  const [, tab = 'runs', ...rest] = location.hash.replace(/^#/, '').split('/');
  return { tab: ['runs', 'workflows', 'agents'].includes(tab) ? tab : 'runs', id: decodeURIComponent(rest.join('/')) };
}

function fillPicker(options, current, extra) {
  picker.replaceChildren(...options.map(([v, t]) => h('option', { value: v, selected: v === current }, t)), ...(extra || []));
  picker.disabled = !options.length && !extra;
}

async function go() {
  route = parse();
  document.querySelectorAll('.tabs a').forEach((a) => (a.dataset.tab === route.tab ? a.setAttribute('aria-current', 'page') : a.removeAttribute('aria-current')));
  if (route.tab !== 'workflows') view.dataset.screen = route.tab;

  if (route.tab === 'runs') {
    const runs = await listRuns();
    if (!route.id && runs.length) { location.replace(`#/runs/${runs[0].slug}`); return; }
    fillPicker(runs.map((r) => [r.slug, `${r.slug} · ${r.workflow} · ${r.status}`]), route.id);
    if (!runs.length) {
      drawer.close();
      view.replaceChildren(h('div.card.empty', h('h2', 'No runs yet'), h('p', 'Start one in Claude Code, for example ', h('code', '/maestro-fix <the bug>'), ' or ', h('code', '/maestro-feature <the request>'), '. It shows up here as it runs.')));
      return;
    }
    document.title = `${route.id} · Maestro`;
    await showRun(view, route.id, false);
  } else if (route.tab === 'workflows') {
    const names = await listWorkflows();
    if (!route.id) { location.replace(`#/workflows/${names.includes('major-feature') ? 'major-feature' : names[0] || 'new'}`); return; }
    const drafts = unsaved();
    const opts = names.map((n) => [n, `${n}.yaml${drafts.includes(n) ? ' • unsaved' : ''}`]);
    for (const d of drafts) if (!names.includes(d)) opts.push([d, `${d}.yaml • new, unsaved`]);
    if (!names.includes(route.id) && !drafts.includes(route.id)) opts.push([route.id, `${route.id}.yaml (new)`]);
    fillPicker(opts, route.id, [h('option', { value: '__new' }, '+ New workflow…')]);
    document.title = `${route.id} · Workflows · Maestro`;
    await showBuilder(view, route.id);
  } else {
    fillPicker([['', 'All agents'], ...Object.entries(AGENTS).map(([k, a]) => [k, `${a.name} · ${a.role}`])], route.id);
    drawer.close();
    document.title = 'Agents · Maestro';
    if (route.id) await showAgent(view, route.id); else showCast(view);
  }
}

picker.addEventListener('change', () => {
  const v = picker.value;
  if (v === '__new') { picker.value = route.id; askNewWorkflow(); return; }
  location.hash = `#/${route.tab}${v ? '/' + encodeURIComponent(v).replace(/%2F/g, '/') : ''}`;
});

window.addEventListener('hashchange', () => {
  if (parse().tab !== route.tab || parse().id !== route.id) drawer.close();
  go().catch(fail);
});
window.addEventListener('beforeunload', (e) => { if (unsaved().length) { e.preventDefault(); e.returnValue = ''; } });

function fail(e) {
  view.replaceChildren(h('div.card.empty', h('h2', 'Something went wrong'), h('p', String(e.message || e))));
}

// Live updates: redraw the open run when its folder changes; refresh the run list.
let busy = false, again = false;
api.watch(async (paths) => {
  if (route.tab !== 'runs') return;
  if (busy) { again = true; return; }
  busy = true;
  try {
    do {
      again = false;
      const runs = await listRuns();
      fillPicker(runs.map((r) => [r.slug, `${r.slug} · ${r.workflow} · ${r.status}`]), route.id);
      if (route.id && paths.some((p) => p.startsWith(`.maestro/runs/${route.id}/`) || p.startsWith('.maestro/workflows/'))) await showRun(view, route.id, true);
      if (!route.id && runs.length) location.replace(`#/runs/${runs[0].slug}`);
    } while (again);
  } finally { busy = false; }
});

api.info().then((i) => { document.getElementById('project').textContent = i.project; }).catch(() => {});
go().catch(fail);
