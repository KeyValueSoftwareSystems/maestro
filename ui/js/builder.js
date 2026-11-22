// The Workflows screen: view and edit a workflow as a graph, check it, and save the YAML.
import * as api from './api.js';
import { h, ico, icon, face, AGENTS, toast } from './util.js';
import { renderGraph, columnsOf } from './graph.js';
import { parseWorkflow, dumpWorkflow } from './yamlout.js';
import { drawer } from './drawer.js';

const DIR = '.maestro/workflows';
const MODES = { agent: 'Agent', exec: 'Command', gate: 'Gate', workflow: 'Workflow' };
let S = null; // { path, name, wf, header, saved, sel, tab, menu, layout, cmd, files }
const drafts = new Map(); // file -> S, so unsaved edits survive switching workflows
let seq = 0;
let pendingNew = null; // a name from "+ New workflow", not saved yet

const dirtyOf = (x) => !!(x && x.wf) && (x.isNew || dumpWorkflow(x.wf, x.header) !== x.saved);
export const isDirty = () => dirtyOf(S);
export const unsaved = () => [...drafts.values()].filter(dirtyOf).map((x) => x.file);

export async function listWorkflows() {
  const top = await api.list(DIR).catch(() => []);
  const sub = await api.list(`${DIR}/subworkflows`).catch(() => []);
  return [...top.filter((f) => f.name.endsWith('.yaml')).map((f) => f.name.replace(/\.yaml$/, '')),
    ...sub.filter((f) => f.name.endsWith('.yaml')).map((f) => 'subworkflows/' + f.name.replace(/\.yaml$/, ''))];
}

// The slash command that runs this workflow, if one exists.
async function commandFor(file) {
  const cmds = (await api.list('.claude/commands').catch(() => [])).filter((f) => f.name.endsWith('.md'));
  for (const c of cmds) {
    const t = await api.readOr(`.claude/commands/${c.name}`, '');
    if (t.includes(`.maestro/workflows/${file}`)) return c.name.replace(/\.md$/, '');
  }
  return null;
}

const all = () => S.wf.steps.flatMap((s) => (s.parallel ? s.parallel : [s]));
const tag = (s) => { if (!s.__k) s.__k = `k${++seq}`; return s; };
const find = (k) => all().find((s) => s.__k === k);
const container = (k) => { // the list a step lives in, and its index there
  for (const s of S.wf.steps) {
    if (s.__k === k) return [S.wf.steps, S.wf.steps.indexOf(s)];
    if (s.parallel) { const i = s.parallel.findIndex((c) => c.__k === k); if (i >= 0) return [s.parallel, i]; }
  }
  return [null, -1];
};

export function problems() {
  const out = [], ids = all().map((s) => s.id), names = new Set(S.files);
  if (!S.wf.name) out.push('The workflow needs a name.');
  ids.forEach((id, i) => { if (!id) out.push(`Step ${i + 1} has no ID.`); else if (ids.indexOf(id) !== i) out.push(`Two steps are called ${id}.`); });
  for (const s of all()) {
    const mode = s.mode || 'agent', id = s.id || '(no ID)';
    if (mode === 'agent' && !AGENTS[s.agent]) out.push(`${id}: pick an agent.`);
    if (mode === 'agent' && !String(s.instructions || '').trim()) out.push(`${id}: write its instructions.`);
    if (mode === 'gate' && !String(s.prompt || '').trim()) out.push(`${id}: write the question it asks.`);
    if (mode === 'exec' && !(Array.isArray(s.command) ? s.command.length : String(s.command || '').trim())) out.push(`${id}: give it a command.`);
    if (mode === 'workflow' && !names.has(String(s.workflow || '').replace(/\.yaml$/, ''))) out.push(`${id}: ${s.workflow || 'no file'} is not a workflow here.`);
    for (const f of ['on_fail', 'on_reject', 'next']) if (s[f] && !ids.includes(s[f])) out.push(`${id}: ${f} points at ${s[f]}, which isn't a step.`);
  }
  return out;
}

export async function showBuilder(view, file) {
  if (S && S.path === `${DIR}/${file}.yaml` && view.dataset.screen === 'builder') return render(view);
  if (drafts.has(file) && dirtyOf(drafts.get(file))) { S = drafts.get(file); S.files = await listWorkflows(); drawer.close(); return render(view); }
  const path = `${DIR}/${file}.yaml`;
  const text = await api.readOr(path);
  const files = await listWorkflows();
  const fresh = text == null && pendingNew && pendingNew.name === file ? pendingNew : null;
  pendingNew = null;
  if (text == null && !fresh) { view.replaceChildren(h('div.card.empty', `No workflow called ${file}.`)); return; }
  let wf, header = [];
  if (text != null) ({ wf, header } = parseWorkflow(text));
  else if (fresh.from) { // a copy: same steps, new name and description
    ({ wf } = parseWorkflow((await api.readOr(`${DIR}/${fresh.from}.yaml`)) || ''));
    Object.assign(wf, { name: file, description: fresh.description || wf.description });
  } else wf = { name: file, description: fresh.description, max_steps: 30, steps: [] };
  wf.steps.forEach((s) => { tag(s); if (s.parallel) s.parallel.forEach(tag); });
  S = { path, file, wf, header, saved: text != null ? dumpWorkflow(wf, header) : '', sel: null, tab: 'graph', menu: false, layout: S?.layout || 'h', cmd: await commandFor(`${file}.yaml`), files, isNew: text == null };
  drafts.set(file, S);
  drawer.close();
  render(view);
}

// The "+ New workflow" form, in the side panel.
export async function askNewWorkflow() {
  const names = await listWorkflows();
  const cmds = (await api.list('.claude/commands').catch(() => [])).map((f) => f.name);
  const err = h('p.bad-text', { style: { margin: 0, fontSize: '13px' } });
  const name = h('input', { type: 'text', required: true, spellcheck: 'false', placeholder: 'e.g. hotfix', autocomplete: 'off' });
  const desc = h('input', { type: 'text', placeholder: 'What it does, in one line' });
  const from = h('select', h('option', { value: '' }, 'Empty'), names.map((n) => h('option', { value: n }, `A copy of ${n}.yaml`)));
  const submit = (e) => {
    e.preventDefault();
    const n = name.value.trim().toLowerCase();
    if (!/^[a-z0-9]+(-[a-z0-9]+)*$/.test(n)) { err.textContent = 'Use lowercase letters, digits and dashes, like hotfix or data-fix.'; name.focus(); return; }
    if (names.includes(n)) { err.textContent = `${n}.yaml already exists.`; name.focus(); return; }
    if (cmds.includes(`maestro-${n}.md`)) { err.textContent = `/maestro-${n} is already a command. Pick another name.`; name.focus(); return; }
    pendingNew = { name: n, description: desc.value.trim(), from: from.value };
    drawer.close();
    location.hash = `#/workflows/${n}`;
  };
  await drawer.open('new-workflow', () => h('form.drawer-body', { onsubmit: submit },
    h('div.drawer-head', h('span.tile.workflow', { html: icon('workflow', 28) }), h('div.who', h('b', 'New workflow'), h('span', 'Saved to .maestro/workflows/, with its own slash command')),
      h('button.ghost', { type: 'button', 'aria-label': 'Close', onclick: () => drawer.close(), html: icon('close', 18) })),
    h('div.form',
      h('label.field', h('span', 'Name'), h('small', 'The file name, and the command: /maestro-<name>.'), name),
      h('label.field', h('span', 'Description'), desc),
      h('label.field', h('span', 'Start from'), from),
      err,
      h('div', { style: { display: 'flex', gap: '8px', justifyContent: 'flex-end' } },
        h('button.btn', { type: 'button', onclick: () => drawer.close() }, 'Cancel'),
        h('button.btn.primary', { type: 'submit' }, 'Create')))));
  name.focus();
}

function render(view) {
  view.dataset.screen = 'builder';
  const probs = problems();
  const dirty = isDirty();
  const { columns, extras, jumps } = columnsOf(S.wf.steps, () => ['per repo'], (s, r) => (r ? `${s.__k}@${r}` : s.__k));
  const graph = renderGraph({ columns, extras, jumps }, {
    layout: S.layout,
    seqClass: () => 'e-todo',
    renderNode: (n) => {
      const s = n.step, mode = s.mode || 'agent';
      const cap = mode === 'agent' ? (s.agent === 'worker' ? 'Worker' : (AGENTS[s.agent] || { role: 'Agent' }).role) : MODES[mode];
      return h('button.node.s-edit' + (S.sel === s.__k ? '.sel' : ''), { type: 'button', 'aria-label': `${s.id || 'new step'}: edit`, onclick: () => select(view, s.__k) },
        face(s), h('span', h('b', s.id || '…'), n.repo ? [' ', h('span.repo', 'per repo')] : null, h('br'), h('span.cap', cap)));
    },
  });

  const addMenu = S.menu ? h('div.menu-list', { role: 'menu' }, [
    ['agent', 'Agent step', 'An agent does a task'], ['exec', 'Command', 'Run build, lint, test or a shell command'],
    ['gate', 'Gate', 'Stop and ask the person to approve'], ['workflow', 'Workflow', 'Run another workflow file in place'],
  ].map(([m, t, d]) => h('button', { type: 'button', role: 'menuitem', onclick: () => add(view, m) }, h('b', t), h('small', d)))) : null;

  view.replaceChildren(
    h('div', { style: { display: 'flex', flexDirection: 'column', gap: '10px' } },
      h('h1', S.wf.name || S.file),
      h('input.desc-input', { type: 'text', value: S.wf.description || '', placeholder: 'What this workflow does, in one line', 'aria-label': 'Description',
        oninput: (e) => { S.wf.description = e.target.value; refreshBar(view); } }),
      h('div.meta.wf-meta', h('span', `${all().length} steps`), h('span.dot', '·'),
        h('label', 'max ', h('input', { type: 'number', min: 1, max: 200, value: S.wf.max_steps ?? '', style: { width: '64px' }, 'aria-label': 'Max step runs',
          oninput: (e) => { S.wf.max_steps = e.target.value ? Number(e.target.value) : undefined; refreshBar(view); } }), ' step runs'),
        h('span.dot', '·'), S.file.startsWith('subworkflows/') ? h('span', 'used inside other workflows')
          : h('span.mono', S.cmd ? `/${S.cmd}` : `/maestro-${S.file} (made on save)`),
        h('span.dot', '·'), h('span', { id: 'validity', class: probs.length ? 'bad-text' : 'ok-text' }, probs.length ? `${probs.length} problem${probs.length > 1 ? 's' : ''}` : 'Valid'))),
    h('section.card',
      h('div.card-head',
        h('div.seg', { role: 'tablist', 'aria-label': 'View' }, ['graph', 'yaml'].map((t) => h('button', { type: 'button', role: 'tab', 'aria-selected': String(S.tab === t), onclick: () => { S.tab = t; render(view); } }, t === 'graph' ? 'Graph' : 'YAML'))),
        h('div.tools',
          S.tab === 'graph' ? h('div.seg', { role: 'tablist', 'aria-label': 'Layout' }, ['h', 'v'].map((l) => h('button', { type: 'button', role: 'tab', 'aria-selected': String(S.layout === l), onclick: () => { S.layout = l; render(view); } }, l === 'h' ? 'Horizontal' : 'Vertical'))) : null,
          h('div.menu', h('button.btn', { type: 'button', 'aria-haspopup': 'menu', 'aria-expanded': String(S.menu), onclick: () => { S.menu = !S.menu; render(view); } }, ico('plus', 14), 'Add step'), addMenu),
          h('button.btn', { type: 'button', id: 'discard', disabled: !dirty || S.isNew, onclick: () => discard(view) }, 'Discard'),
          h('button.btn.primary', { type: 'button', id: 'save', disabled: !dirty || probs.length > 0, onclick: () => save(view) }, 'Save'))),
      S.tab === 'graph'
        ? (all().length ? h('div.graph-wrap', graph) : h('div.empty', 'No steps yet. Use Add step.'))
        : h('div.yaml', h('div', { style: { display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px' } },
          h('span.mono', { style: { fontSize: '12.5px', color: 'var(--muted)' } }, S.path),
          h('button.link', { type: 'button', onclick: () => navigator.clipboard.writeText(dumpWorkflow(S.wf, S.header)).then(() => toast('Copied')) }, 'Copy')),
        h('pre.box', dumpWorkflow(S.wf, S.header))),
      probs.length ? h('div', { style: { padding: '0 24px 20px' } }, h('ul.problems', probs.map((p) => h('li', p)))) : null),
    h('p.hint', 'Click a step to edit it. Save writes the YAML file; a run that has already started keeps going with the old one.'));
}

function refreshBar(view) { // cheap update while typing in the header
  const probs = problems(), v = view.querySelector('#validity'), b = view.querySelector('#save');
  if (v) { v.textContent = probs.length ? `${probs.length} problem${probs.length > 1 ? 's' : ''}` : 'Valid'; v.className = probs.length ? 'bad-text' : 'ok-text'; }
  if (b) b.disabled = !isDirty() || probs.length > 0;
}

function add(view, mode) {
  const n = all().length + 1;
  const s = tag({ id: `new-step-${n}`, ...(mode === 'agent' ? { agent: 'worker', instructions: 'Describe the task. You can use ${run}, ${slug} and ${repo}.\n' } : {}),
    ...(mode === 'exec' ? { mode, command: ['lint', 'test'] } : {}), ...(mode === 'gate' ? { mode, prompt: 'Approve, or tell me what to change.' } : {}),
    ...(mode === 'workflow' ? { mode, workflow: 'subworkflows/archive.yaml' } : {}) });
  const at = S.wf.steps.findIndex((x) => x.mode === 'workflow' || x.next); // before the ending and the fix-only steps
  S.wf.steps.splice(at < 0 ? S.wf.steps.length : at, 0, s);
  S.menu = false;
  select(view, s.__k);
}

function select(view, k) {
  S.sel = k;
  render(view);
  drawer.open(k, () => editor(view, k));
}

function editor(view, k) {
  const s = find(k);
  if (!s) return h('div');
  const mode = s.mode || 'agent';
  const others = all().filter((x) => x !== s && x.id).map((x) => x.id);
  const upd = (patch, redraw = true) => {
    for (const [key, v] of Object.entries(patch)) { if (v === undefined || v === '' || v === false) delete s[key]; else s[key] = v; }
    render(view);
    if (redraw) drawer.open(k, () => editor(view, k));
  };
  const rename = (id) => { for (const x of all()) for (const f of ['on_fail', 'on_reject', 'next']) if (x[f] === s.id) x[f] = id; s.id = id; render(view); };
  const target = (field, labelText, help) => h('label.field', h('span', labelText), help ? h('small', help) : null,
    h('select', { onchange: (e) => upd({ [field]: e.target.value || undefined }) }, h('option', { value: '' }, '—'), others.map((o) => h('option', { value: o, selected: s[field] === o }, o))));
  const setMode = (m) => {
    const keep = { id: s.id, __k: s.__k, __comment: s.__comment };
    for (const key of Object.keys(s)) delete s[key];
    Object.assign(s, keep, m === 'agent' ? { agent: 'worker', instructions: '' } : m === 'exec' ? { mode: m, command: ['test'] } : m === 'gate' ? { mode: m, prompt: '' } : { mode: m, workflow: '' });
    render(view); drawer.open(k, () => editor(view, k));
  };
  const cmdText = Array.isArray(s.command) ? `[${s.command.join(', ')}]` : s.command || '';
  const [list, idx] = container(k);
  const move = (d) => { const j = idx + d; if (j < 0 || j >= list.length) return; [list[idx], list[j]] = [list[j], list[idx]]; render(view); drawer.open(k, () => editor(view, k)); };

  return h('div.drawer-body',
    h('div.drawer-head', face(s), h('div.who', h('b', s.id || 'new step'), h('span', mode === 'agent' ? `${(AGENTS[s.agent] || AGENTS.worker).name} · ${(AGENTS[s.agent] || AGENTS.worker).role}` : MODES[mode])),
      h('button.ghost', { type: 'button', 'aria-label': 'Close', onclick: () => { S.sel = null; drawer.close(); render(view); }, html: icon('close', 18) })),
    h('div.form',
      h('div.row',
        h('label.field', h('span', 'Step ID'), h('input', { type: 'text', value: s.id || '', spellcheck: 'false', onchange: (e) => rename(e.target.value.trim()) })),
        h('label.field', h('span', 'Type'), h('select', { onchange: (e) => setMode(e.target.value) }, Object.entries(MODES).map(([m, t]) => h('option', { value: m, selected: m === mode }, t))))),
      mode === 'agent' ? h('div.row',
        h('label.field', h('span', 'Agent'), h('select', { onchange: (e) => upd({ agent: e.target.value }) }, Object.entries(AGENTS).map(([a, x]) => h('option', { value: a, selected: s.agent === a }, `${x.name} · ${x.role}`)))),
        h('label.field', h('span', 'Model'), h('select', { disabled: s.run === 'inline', onchange: (e) => upd({ model: e.target.value || undefined }) },
          ['', 'opus', 'sonnet', 'haiku'].map((m) => h('option', { value: m, selected: (s.model || '') === m }, m || 'Default'))))) : null,
      mode === 'agent' ? h('label.check', h('input', { type: 'checkbox', checked: s.run === 'inline', onchange: (e) => upd({ run: e.target.checked ? 'inline' : undefined }) }),
        h('span', 'Run in the conversation', h('small', 'For agents that need to talk to the person. Model is ignored.'))) : null,
      mode === 'agent' || mode === 'exec' ? h('label.check', h('input', { type: 'checkbox', checked: s.foreach === 'repo', onchange: (e) => upd({ foreach: e.target.checked ? 'repo' : undefined }) }),
        h('span', 'Run once per repo', h('small', 'For each repo the run touches, in parallel. ${repo}, ${worktree} and ${branch} mean that repo\'s value.'))) : null,
      mode === 'agent' ? h('label.field', h('span', 'Instructions'), h('small', 'The task. ${run} is the run folder; ${slug}, ${repo} and recorded values are filled in.'),
        h('textarea', { spellcheck: 'false', oninput: (e) => { s.instructions = e.target.value; refreshBar(view); }, onchange: () => render(view) }, s.instructions || '')) : null,
      mode === 'gate' ? h('label.field', h('span', 'Question asked'), h('textarea', { style: { minHeight: '100px' }, oninput: (e) => { s.prompt = e.target.value; refreshBar(view); }, onchange: () => render(view) }, s.prompt || '')) : null,
      mode === 'exec' ? h('label.field', h('span', 'Command'), h('small', 'Workspace command names in brackets, like [build, lint, test], or a shell command.'),
        h('input', { type: 'text', value: cmdText, spellcheck: 'false', onchange: (e) => { const v = e.target.value.trim(); upd({ command: /^\[.*\]$/.test(v) ? v.slice(1, -1).split(',').map((x) => x.trim()).filter(Boolean) : v }); } })) : null,
      mode === 'workflow' ? h('label.field', h('span', 'Workflow file'), h('select', { onchange: (e) => upd({ workflow: e.target.value }) }, h('option', { value: '' }, '—'),
        S.files.filter((f) => f !== S.file).map((f) => h('option', { value: `${f}.yaml`, selected: s.workflow === `${f}.yaml` }, `${f}.yaml`)))) : null,
      mode === 'gate' ? target('on_reject', 'If the person rejects, go back to') : target('on_fail', 'If it fails, go to'),
      mode === 'agent' || mode === 'exec' ? target('next', 'Fix-only step: after it passes, go back to', 'A step with this set runs only when an on_fail jumps to it.') : null,
      mode === 'agent' ? h('div.row',
        h('label.field', h('span', 'Template'), h('input', { type: 'text', value: s.template || '', placeholder: 'the agent\'s default', onchange: (e) => upd({ template: e.target.value.trim() || undefined }) })),
        h('label.field', h('span', 'Sub-skills'), h('input', { type: 'text', value: s.skills ? Object.entries(s.skills).map(([a, b]) => `${a}: ${b}`).join(', ') : '', placeholder: 'brainstorm: grill-the-idea, design: system-design',
          onchange: (e) => { const m = Object.fromEntries(e.target.value.split(',').map((x) => x.split(':').map((y) => y.trim())).filter(([a, b]) => a && b)); upd({ skills: Object.keys(m).length ? m : undefined }); } }))) : null,
      h('div', { style: { display: 'flex', gap: '8px', flexWrap: 'wrap' } },
        h('button.btn', { type: 'button', disabled: idx <= 0, onclick: () => move(-1) }, ico('up', 14), 'Earlier'),
        h('button.btn', { type: 'button', disabled: idx >= list.length - 1, onclick: () => move(1) }, ico('down', 14), 'Later'),
        h('span', { style: { flex: 1 } }),
        h('button.btn.danger', { type: 'button', onclick: () => { list.splice(idx, 1); if (!list.length) S.wf.steps = S.wf.steps.filter((x) => !x.parallel || x.parallel.length); S.sel = null; drawer.close(); render(view); } }, 'Delete step'),
        h('button.btn.primary', { type: 'button', onclick: () => { S.sel = null; drawer.close(); render(view); } }, 'Done'))));
}

function discard(view) {
  if (!S.armed) { // a second click within 4 s discards
    S.armed = true;
    const b = view.querySelector('#discard'); if (b) b.textContent = 'Click again to discard';
    setTimeout(() => { S.armed = false; const x = view.querySelector('#discard'); if (x) x.textContent = 'Discard'; }, 4000);
    return;
  }
  S.armed = false;
  const { wf, header } = parseWorkflow(S.saved);
  wf.steps.forEach((s) => { tag(s); if (s.parallel) s.parallel.forEach(tag); });
  Object.assign(S, { wf, header, sel: null });
  drawer.close();
  render(view);
}

async function save(view) {
  const text = dumpWorkflow(S.wf, S.header);
  try {
    await api.write(S.path, text);
    const name = `maestro-${S.file}`;
    if (!S.cmd && !S.file.startsWith('subworkflows/') && (await api.readOr(`.claude/commands/${name}.md`)) == null) { // never overwrite a command
      await api.write(`.claude/commands/${name}.md`, `---\ndisable-model-invocation: true\ndescription: ${JSON.stringify(String(S.wf.description || `Run the ${S.file} workflow`))}\nargument-hint: <request, or a run slug to resume>\n---\n\nUse the \`maestro\` skill to run the workflow \`.maestro/workflows/${S.file}.yaml\` for: $ARGUMENTS\n`);
      S.cmd = name;
    }
    S.saved = text; S.isNew = false;
    toast('Saved');
    render(view);
  } catch (e) {
    toast(e.message || 'Could not save');
  }
}
