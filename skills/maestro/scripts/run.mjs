#!/usr/bin/env node
// Bookkeeping for a Maestro run. The lead skill calls it; it never calls a model.
//   node run.mjs start <workflow> <slug>                  create the run folder and state.yaml
//   node run.mjs next <slug>                              print what to do now, as JSON
//   node run.mjs end <slug> <step> <result> [options]     record a result and pick the next step
//   node run.mjs status <slug>                            where the run stands, as JSON
//   node run.mjs goto <slug> <step> [--var ...]           the person chose a step to continue from
//   node run.mjs stop <slug>                              the person chose to stop
// <result> is pass or fail for a step, approved or rejected for a gate.
// Options for end: --repo <name>  --note <text>  --details <path>  --var <name>=<value> (repeatable)
//                  --repeat   this failure has the same cause as the step's last failure
// Works from any folder. Needs Node 20+ and .maestro/ui/vendor/js-yaml.mjs (installed with the UI).
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

// The project root: four levels above this file (.claude/skills/maestro/scripts/), else the current folder.
const HERE = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../../..');
const ROOT = fs.existsSync(path.join(HERE, '.maestro')) ? HERE : process.cwd();
const M = path.join(ROOT, '.maestro');
const DEFAULT_MAX_STEPS = 30; // the workflow format's documented default
const EXTRA_STEPS = 10;       // what `goto` adds when the person continues a run that used up its budget

const die = (msg) => { console.error(`run.mjs: ${msg}`); process.exit(1); };
const now = () => new Date().toISOString().replace(/\.\d+Z$/, 'Z');
let yaml;
try { yaml = await import(pathToFileURL(path.join(M, 'ui/vendor/js-yaml.mjs')).href); }
catch { die('cannot load .maestro/ui/vendor/js-yaml.mjs. Run install.sh again.'); }
const readYaml = (file) => yaml.load(fs.readFileSync(file, 'utf8'));
const runDir = (slug) => path.join(M, 'runs', slug);
const statePath = (slug) => path.join(runDir(slug), 'state.yaml');
const load = (slug) => fs.existsSync(statePath(slug ?? '')) ? readYaml(statePath(slug)) : die(`no run '${slug}' under .maestro/runs/`);
const save = (s) => fs.writeFileSync(statePath(s.slug), yaml.dump(s, { lineWidth: 200, flowLevel: 3 }));
const workspace = () => fs.existsSync(path.join(M, 'workspace.yaml')) ? readYaml(path.join(M, 'workspace.yaml')) : { repos: {} };
const wfName = (name) => String(name).replace(/^.*\.maestro\/workflows\//, '').replace(/\.yaml$/, '');

// One change at a time: two `end` calls at once would otherwise lose one of the writes.
function locked(slug, fn) {
  if (!fs.existsSync(runDir(slug))) return fn(); // no run: fn says so
  const lock = path.join(runDir(slug), '.lock');
  for (let i = 0; ; i++) {
    try { fs.mkdirSync(lock); break; } catch {
      if (i > 200 || Date.now() - fs.statSync(lock, { throwIfNoEntry: false })?.mtimeMs > 30_000) { fs.rmSync(lock, { recursive: true, force: true }); continue; }
      Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, 25);
    }
  }
  try { return fn(); } finally { fs.rmSync(lock, { recursive: true, force: true }); }
}

// A workflow becomes a list of units. A unit is one step, or the steps of a `parallel` list.
// A `mode: workflow` step is replaced by that file's units, so a subworkflow shares the run.
function units(name) {
  const file = path.join(M, 'workflows', `${wfName(name)}.yaml`);
  if (!fs.existsSync(file)) die(`workflow file not found: ${file}`);
  const wf = readYaml(file);
  const out = [];
  for (const s of wf.steps) {
    if (s.parallel) out.push(s.parallel);
    else if (s.mode === 'workflow') out.push(...units(s.workflow).list);
    else out.push([s]);
  }
  return { list: out, max: wf.max_steps ?? DEFAULT_MAX_STEPS };
}
const find = (list, id) => {
  for (let u = 0; u < list.length; u++) { const s = list[u].find((x) => x.id === id); if (s) return { u, step: s }; }
  die(`no step '${id}'. Steps are: ${list.flat().map((s) => s.id).join(', ')}`);
};
const isFix = (unit) => unit.length === 1 && unit[0].next; // reached only through on_fail
const repoList = (s, ws) => {
  const r = s.vars.repos ?? Object.keys(ws.repos ?? {});
  return Array.isArray(r) ? r.map(String) : String(r).split(/[\s,]+/).filter(Boolean);
};

// A value as text: a list joins with ", ", and a map becomes "key: value" pairs.
const text = (v) => Array.isArray(v) ? v.map(text).join(', ')
  : v && typeof v === 'object' ? Object.entries(v).map(([k, x]) => `${k}: ${text(x)}`).join(', ') : String(v);
// Fill ${name}. Inside a foreach, a per-repo value means that repo's value.
function fill(text_, s, repo, repos) {
  return String(text_).replace(/\$\{(\w+)\}/g, (_, k) => {
    if (k === 'slug') return s.slug;
    if (k === 'run') return runDir(s.slug);
    if (k === 'repo' && repo) return repo;
    const v = s.vars[k];
    if (v === undefined) throw new Error(`missing value for \${${k}}`);
    const perRepo = v && typeof v === 'object' && !Array.isArray(v) && Object.keys(v).some((r) => repos.includes(r));
    if (perRepo && repo) { if (v[repo] === undefined) throw new Error(`missing \${${k}} for repo ${repo}`); return text(v[repo]); }
    return text(v);
  });
}
const wait = (s, reason) => { s.status = 'waiting'; s.reason = reason; s.running = []; save(s); return { action: 'waiting', reason }; };

function describe(step, s, ws, repo) {
  const repos = repoList(s, ws);
  const base = { step: step.id, ...(repo ? { repo } : {}) };
  if (step.mode === 'gate') return { ...base, kind: 'gate', prompt: fill(step.prompt, s, repo, repos) };
  if (step.mode === 'exec') {
    const r = repo ? ws.repos?.[repo] ?? {} : {};
    const names = Array.isArray(step.command) ? step.command : null;
    const commands = names ? names.map((n) => r.commands?.[n]).filter(Boolean) : [fill(step.command, s, repo, repos)];
    const cwd = repo ? (s.vars.worktree?.[repo] ?? path.join(ROOT, r.path ?? '.')) : ROOT;
    return { ...base, kind: 'exec', cwd, commands, log: path.join(runDir(s.slug), 'logs', `${step.id}${repo ? `-${repo}` : ''}.log`) };
  }
  return {
    ...base, kind: 'agent', agent: step.agent ?? 'worker', run: step.run ?? 'subagent',
    ...(step.model ? { model: step.model } : {}),
    instructions: fill(step.instructions, s, repo, repos),
    ...(step.skills ? { skills: step.skills } : {}),
    ...(step.template ? { template: step.template } : {}),
    ...(s.retry ? { previous_failure: s.retry } : {}),
    ...(s.feedback ? { feedback: s.feedback } : {}),
  };
}

function next(slug) {
  const s = load(slug);
  if (s.status === 'done' || s.status === 'stopped') return { action: s.status };
  if (s.status === 'waiting') return { action: 'waiting', reason: s.reason };
  if (!fs.existsSync(path.join(runDir(slug), 'requirements.md'))) die(`write the request, word for word, to ${path.join(runDir(slug), 'requirements.md')} first`);
  const { list, max } = units(s.workflow);
  const ws = workspace();
  s.running ??= []; s.history ??= []; s.vars ??= {}; s.results ??= []; s.max_steps ??= max; s.steps_used ??= 0;
  const { u } = find(list, s.current);
  const steps = s.only ? list[u].filter((x) => x.id === s.only) : list[u];
  const isGate = steps[0].mode === 'gate';
  let todo;
  try {
    todo = steps.flatMap((st) => st.foreach === 'repo'
      ? repoList(s, ws).map((r) => describe(st, s, ws, r))
      : [describe(st, s, ws)]);
  } catch (e) { return wait(s, `${e.message}. Ask the person for it, then run goto ${slug} ${s.current} --var "<name>=<value>".`); }
  if (!todo.length) return wait(s, `no repos to run '${s.current}' in: record repos, or check .maestro/workspace.yaml`);

  // Items started before and never recorded: run only those again, and keep what was recorded.
  if (s.running.length) {
    const key = (x) => `${x.step}/${x.repo ?? ''}`;
    const left = new Set(s.running.map(key));
    for (const r of s.running) s.history.push({ step: r.step, ...(r.repo ? { repo: r.repo } : {}), status: 'interrupted', at: now() });
    todo = todo.filter((t) => left.has(key(t)));
    s.running = todo.map((t) => ({ step: t.step, ...(t.repo ? { repo: t.repo } : {}), since: now() }));
    save(s);
    return { action: isGate ? 'gate' : 'run', interrupted: true, todo };
  }
  if (!isGate && s.steps_used >= s.max_steps) return wait(s, `the run used its whole step budget (${s.max_steps} steps)`);
  if (!isGate) s.steps_used += 1;
  s.running = todo.map((t) => ({ step: t.step, ...(t.repo ? { repo: t.repo } : {}), since: now() }));
  s.results = [];
  save(s);
  return { action: isGate ? 'gate' : 'run', todo };
}

function parseVar(kv) {
  const eq = kv.indexOf('='); if (eq < 1) die(`--var needs name=value, got '${kv}'`);
  const k = kv.slice(0, eq), raw = kv.slice(eq + 1).trim();
  if (!/^[[{]/.test(raw)) return [k, raw]; // a list or map only when written as one
  try { return [k, yaml.load(raw)]; } catch { die(`--var ${k}: '${raw}' is not a valid list or map. Write a list as [a, b].`); }
}
const setVars = (s, vars, repo) => {
  for (const [k, v] of vars.map(parseVar)) s.vars[k] = repo ? { ...(s.vars[k] ?? {}), [repo]: v } : v;
};

function end(slug, stepId, result, opt) {
  const s = load(slug);
  s.running ??= []; s.results ??= []; s.vars ??= {};
  const { list } = units(s.workflow);
  const isGate = find(list, stepId).step.mode === 'gate';
  if (isGate && !['approved', 'rejected'].includes(result)) die(`'${stepId}' is a gate: record approved or rejected`);
  if (!isGate && !['pass', 'fail'].includes(result)) die(`'${stepId}' is a step: record pass or fail`);
  if (result === 'fail' && !opt.note) die('a fail needs --note "<one line on why>"');
  const i = s.running.findIndex((r) => r.step === stepId && (r.repo ?? '') === (opt.repo ?? ''));
  if (i < 0) die(`'${stepId}'${opt.repo ? ` for repo ${opt.repo}` : ''} is not running. Running: ${s.running.map((r) => r.step + (r.repo ? `/${r.repo}` : '')).join(', ') || 'nothing'}`);
  s.running.splice(i, 1);
  s.history.push({ step: stepId, ...(opt.repo ? { repo: opt.repo } : {}), status: result, at: now(), ...(opt.note ? { note: opt.note } : {}) });
  setVars(s, opt.vars, opt.repo);
  s.results.push({ step: stepId, ...(opt.repo ? { repo: opt.repo } : {}), result, note: opt.note ?? '', details: opt.details ?? '' });
  if (s.running.length) { save(s); return { action: 'more', still_running: s.running }; }

  // Every item of this unit has ended: decide where the run goes.
  const { u } = find(list, s.current);
  const results = s.results;
  const bad = results.filter((r) => r.result === 'fail' || r.result === 'rejected');
  const after = (from) => { let n = from + 1; while (n < list.length && isFix(list[n])) n++; return n; };
  const go = (id, only) => { s.current = id; if (only) s.only = only; else delete s.only; };
  s.results = [];
  if (!bad.length) {
    delete s.retry; delete s.feedback;
    if (s.fails) for (const r of results) delete s.fails[r.step];
    const step = find(list, stepId).step;
    if (step.next) go(step.next);                               // a fix step returns to the step that failed
    else { const n = after(u); if (n >= list.length) { s.status = 'done'; s.current = null; delete s.only; } else go(list[n][0].id); }
    save(s); return { action: s.status === 'done' ? 'done' : 'continue' };
  }
  const first = bad[0];
  const failed = find(list, first.step).step;
  if (first.result === 'rejected') {
    s.feedback = first.note;
    if (!failed.on_reject) return wait(s, `the person rejected '${first.step}', which has no step to go back to`);
    go(failed.on_reject); save(s); return { action: 'continue' };
  }
  const reason = bad.map((r) => (r.repo ? `${r.repo}: ` : '') + r.note).join('; ');
  s.fails ??= {};
  if (first.step in s.fails && (opt.repeat || s.fails[first.step] === reason))
    return wait(s, `'${first.step}' failed twice in a row for the same reason: ${reason}`);
  s.fails[first.step] = reason;
  const details = bad.map((r) => r.details).filter(Boolean).join(', ');
  if (!failed.on_fail) return wait(s, `'${first.step}' failed: ${reason}${details ? `. Details: ${details}` : ''}`);
  s.retry = { step: first.step, reason, ...(details ? { details } : {}) };
  const target = find(list, failed.on_fail);
  if (list[target.u].length > 1) go(list[target.u][0].id, failed.on_fail); // re-run only that step of a parallel list
  else go(failed.on_fail);
  save(s); return { action: 'continue' };
}

function start(workflow, slug) {
  if (!/^[a-z0-9]+(-[a-z0-9]+){1,4}$/.test(slug ?? '')) die('the slug must be 2 to 5 lowercase words joined by "-", for example login-timeout');
  const name = wfName(workflow ?? '');
  if (name !== 'init' && !fs.existsSync(path.join(M, 'workspace.yaml'))) die('.maestro/workspace.yaml is missing. Ask the person to run /maestro-init first.');
  if (fs.existsSync(statePath(slug))) die(`run '${slug}' already exists. To resume it, run status ${slug}, then next ${slug}.`);
  const wtPath = workspace().worktrees?.path; // the workspace's own worktree tool, if it has one
  const wtDir = wtPath ? [path.join(ROOT, wtPath.replaceAll('{slug}', slug).split('{repo}')[0])] : [];
  for (const taken of [runDir(slug), path.join(M, 'worktrees', slug), path.join(ROOT, 'docs/plans', `${slug}.md`), ...wtDir])
    if (fs.existsSync(taken)) die(`slug '${slug}' is taken (${path.relative(ROOT, taken)}). Choose another.`);
  const { list, max } = units(name);
  fs.mkdirSync(path.join(runDir(slug), 'logs'), { recursive: true });
  save({ workflow: name, slug, status: 'running', current: list[0][0].id, steps_used: 0, max_steps: max, vars: {}, running: [], results: [], history: [] });
  const outline = list.filter((x) => !isFix(x)).map((x) => x.map((s) => s.id + (s.mode === 'gate' ? ' (you)' : '')).join(' + '));
  return { slug, run: runDir(slug), steps: outline.join(' → '), then: `write the request, word for word, to ${path.join(runDir(slug), 'requirements.md')}` };
}

function status(slug) {
  const s = load(slug);
  const lastFail = [...(s.history ?? [])].reverse().find((h) => h.status === 'fail' || h.status === 'rejected');
  return {
    slug, workflow: s.workflow, status: s.status, ...(s.reason ? { reason: s.reason } : {}), at: s.current ?? 'the end',
    steps_used: `${s.steps_used} of ${s.max_steps}`,
    ...(s.running?.length ? { started_not_recorded: s.running.map((r) => r.step + (r.repo ? `/${r.repo}` : '')) } : {}),
    ...(lastFail ? { last_failure: `${lastFail.step}${lastFail.repo ? `/${lastFail.repo}` : ''}: ${lastFail.note ?? lastFail.status}` } : {}),
  };
}

function goto(slug, stepId, opt) {
  const s = load(slug);
  find(units(s.workflow).list, stepId);
  setVars(s, opt.vars);
  Object.assign(s, { status: 'running', current: stepId, running: [], results: [] });
  for (const k of ['reason', 'only', 'fails']) delete s[k];
  let extra = 0;
  if (s.steps_used >= s.max_steps) { extra = EXTRA_STEPS; s.max_steps = s.steps_used + extra; }
  save(s);
  return { action: 'continue', ...(extra ? { note: `the step budget was used up; this run now has ${extra} more steps` } : {}) };
}

function stop(slug) {
  const s = load(slug);
  Object.assign(s, { status: 'stopped', running: [] });
  save(s);
  return { action: 'stopped' };
}

const [cmd, a, b, c, ...rest] = process.argv.slice(2);
const opts = cmd === 'goto' ? [c, ...rest].filter((x) => x !== undefined) : rest;
const opt = { vars: [] };
for (let i = 0; i < opts.length; i += 2) {
  const [k, v] = [opts[i], opts[i + 1]];
  if (k === '--repeat') { opt.repeat = true; i -= 1; continue; }
  if (v === undefined) die(`${k} needs a value`);
  if (k === '--var') opt.vars.push(v); else if (['--repo', '--note', '--details'].includes(k)) opt[k.slice(2)] = v; else die(`unknown option ${k}`);
}
const withLock = (fn) => (a ? locked(a, fn) : fn());
let out;
if (cmd === 'start') out = start(a, b);
else if (cmd === 'next') out = withLock(() => next(a));
else if (cmd === 'end') out = withLock(() => end(a, b, c, opt));
else if (cmd === 'status') out = status(a);
else if (cmd === 'goto') out = withLock(() => goto(a, b, opt));
else if (cmd === 'stop') out = withLock(() => stop(a));
else die('commands: start, next, end, status, goto, stop');
console.log(JSON.stringify(out, null, 2));
