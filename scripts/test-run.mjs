// Drives skills/maestro/scripts/run.mjs through Maestro's real workflows, with no model.
// Run it from the repo: node scripts/test-run.mjs   (scripts/check.sh runs it too)
import { execFileSync, spawnSync } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const SRC = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const P = fs.mkdtempSync(path.join(os.tmpdir(), 'maestro-run-'));
execFileSync('bash', [path.join(SRC, 'install.sh'), P], { stdio: 'ignore' });
const WS2 = 'repos:\n  api:\n    path: codebase/api\n    commands: {build: npm run build, lint: npm run lint, test: npm test}\n' +
  '  web:\n    path: codebase/web\n    commands: {build: npm run build, test: npm test}\n';
fs.writeFileSync(path.join(P, '.maestro/workspace.yaml'), WS2);
const yaml = await import(path.join(P, '.maestro/ui/vendor/js-yaml.mjs'));
const RUN = path.join(P, '.claude/skills/maestro/scripts/run.mjs');
const run = (...args) => {
  const r = spawnSync('node', [RUN, ...args], { cwd: P, encoding: 'utf8' });
  if (r.status !== 0) return { error: r.stderr.trim() };
  return JSON.parse(r.stdout);
};
const file = (slug) => path.join(P, '.maestro/runs', slug, 'state.yaml');
const state = (slug) => yaml.load(fs.readFileSync(file(slug), 'utf8'));
const edit = (slug, fn) => { const s = state(slug); fn(s); fs.writeFileSync(file(slug), yaml.dump(s)); };
let pass = 0, fail = 0;
const ok = (name, cond, extra = '') => { cond ? pass++ : fail++; if (!cond) console.log(`FAIL ${name} ${extra}`); };
const begin = (wf, slug) => { const r = run('start', wf, slug); fs.writeFileSync(path.join(P, '.maestro/runs', slug, 'requirements.md'), 'req'); return r; };
const ids = (n) => n.todo.map((t) => t.step + (t.repo ? '/' + t.repo : '')).join(',');
// Do the current unit: every item gets `result` unless `per` overrides it; `extra` adds options.
const step = (slug, result, per = {}, extra = {}) => {
  const n = run('next', slug);
  if (!n.todo) return { n };
  let last;
  for (const t of n.todo) {
    const key = t.step + (t.repo ? '/' + t.repo : '');
    const r = per[key] ?? result ?? (t.kind === 'gate' ? 'approved' : 'pass');
    const args = ['end', slug, t.step, r];
    if (t.repo) args.push('--repo', t.repo);
    if (r === 'fail' && !(extra[key] ?? extra[t.step])?.['--note']) args.push('--note', 'it failed');
    for (const [k, v] of Object.entries(extra[key] ?? extra[t.step] ?? {})) args.push(k, v);
    last = run(...args);
  }
  return { n, last };
};

// Step ids are unique in each workflow, subworkflows included.
const flat = (f) => yaml.load(fs.readFileSync(path.join(SRC, 'workflows', f), 'utf8')).steps
  .flatMap((s) => s.parallel ?? (s.mode === 'workflow' ? flat(s.workflow) : [s]));
for (const f of fs.readdirSync(path.join(SRC, 'workflows')).filter((f) => f.endsWith('.yaml'))) {
  const all = flat(f).map((s) => s.id);
  ok(`${f}: unique step ids`, new Set(all).size === all.length, all.join(','));
}

// Errors say what to do.
ok('bad slug refused', run('start', 'bug-fix', 'Bad_Slug').error?.includes('2 to 5 lowercase'));
const st = run('start', '.maestro/workflows/bug-fix.yaml', 'no-request-yet');
ok('a workflow path is saved as its name', state('no-request-yet').workflow === 'bug-fix');
ok('start prints the steps', st.steps?.startsWith('hypothesis → investigate → confirm (you)') && !st.steps.includes('next'));
ok('next without requirements.md refused', run('next', 'no-request-yet').error?.includes('requirements.md'));
ok('existing run: told to resume', run('start', 'bug-fix', 'no-request-yet').error?.includes('already exists. To resume'));
ok('unknown step lists the steps', run('goto', 'no-request-yet', 'nope').error?.includes('Steps are: hypothesis'));
fs.mkdirSync(path.join(P, 'sub/dir'), { recursive: true });
ok('works from another folder', spawnSync('node', [RUN, 'status', 'no-request-yet'], { cwd: path.join(P, 'sub/dir'), encoding: 'utf8' }).status === 0);

// Bug-fix across two repos: inline step, gate rejected then approved, foreach, retry, done.
begin('bug-fix', 'login-bug');
let r = step('login-bug');
ok('first item is the inline hypothesis', r.n.todo[0].run === 'inline' && r.n.todo[0].instructions.includes('.maestro/runs/login-bug/hypothesis.md'));
step('login-bug', 'pass', {}, { investigate: { '--var': 'repos=[api, web]' } });
ok('repos recorded as a list', JSON.stringify(state('login-bug').vars.repos) === '["api","web"]');
ok('a gate refuses pass', run('next', 'login-bug') && run('end', 'login-bug', 'confirm', 'pass').error?.includes('is a gate'));
run('end', 'login-bug', 'confirm', 'rejected', '--note', 'look at the cache');
ok('gate not counted', state('login-bug').steps_used === 2);
ok('rejected gate goes back with feedback', state('login-bug').current === 'investigate' && run('next', 'login-bug').todo[0].feedback === 'look at the cache');
run('end', 'login-bug', 'investigate', 'pass');
step('login-bug');
r = step('login-bug', 'pass', {}, { 'worktree/api': { '--var': 'worktree=/wt/api' }, 'worktree/web': { '--var': 'worktree=/wt/web' } });
ok('worktree runs once per repo', ids(r.n) === 'worktree/api,worktree/web');
edit('login-bug', (s) => { s.vars.branch = { api: 'fix/login-bug', web: 'fix/login-bug' }; });
r = step('login-bug');
ok('fix fills per-repo values', r.n.todo[0].instructions.includes('/wt/api') && r.n.todo[1].instructions.includes('/wt/web'));
r = run('next', 'login-bug');
ok('checks: commands, cwd and log per repo', r.todo[0].commands.length === 3 && r.todo[1].commands.length === 2 && r.todo[0].cwd === '/wt/api' && r.todo[1].log.endsWith('logs/checks-web.log'));
ok('a fail needs a note', run('end', 'login-bug', 'checks', 'fail', '--repo', 'web').error?.includes('--note'));
run('end', 'login-bug', 'checks', 'pass', '--repo', 'api');
run('end', 'login-bug', 'checks', 'fail', '--repo', 'web', '--note', 'test X fails', '--details', 'logs/checks-web.log');
ok('checks fail goes to fix with the reason', state('login-bug').current === 'fix' && run('next', 'login-bug').todo[0].previous_failure?.reason === 'web: test X fails');
for (const t of ['api', 'web']) run('end', 'login-bug', 'fix', 'pass', '--repo', t);
step('login-bug', 'pass', { 'checks/web': 'fail' }, { 'checks/web': { '--note': 'test X fails' } });
ok('same failure twice: waiting', state('login-bug').status === 'waiting' && state('login-bug').reason.includes('twice'));
ok('status shows the last failure', run('status', 'login-bug').last_failure === 'checks/web: test X fails');
run('goto', 'login-bug', 'checks');
step('login-bug'); step('login-bug');
ok('subworkflow flattened: learn next', state('login-bug').current === 'learn');
step('login-bug');
run('next', 'login-bug'); run('end', 'login-bug', 'approve-ship', 'rejected', '--note', 'add a test first');
ok('gate without on_reject: waiting, feedback kept', state('login-bug').status === 'waiting' && state('login-bug').feedback === 'add a test first');
run('goto', 'login-bug', 'approve-ship');
step('login-bug');
step('login-bug', 'pass', {}, { 'pr/api': { '--var': 'pr=https://x/api/pull/1' }, 'pr/web': { '--var': 'pr=https://x/web/pull/2' } });
ok('docs-pr gets the pr list', run('next', 'login-bug').todo[0].instructions.includes('api: https://x/api/pull/1, web: https://x/web/pull/2'));
run('end', 'login-bug', 'docs-pr', 'pass');
r = step('login-bug');
ok('done after cleanup', r.last.action === 'done' && run('next', 'login-bug').action === 'done');

// Major feature: parallel list, on_fail into it, fix steps with next, skipped in order.
begin('major-feature', 'tax-feature');
step('tax-feature'); step('tax-feature');
step('tax-feature', 'pass', {}, { plan: { '--var': 'repos=[api]' } });
step('tax-feature', 'fail', {}, { 'plan-review': { '--note': '2 blockers' } });
ok('plan-review fail goes to the gate', state('tax-feature').current === 'approve-plan');
step('tax-feature');
step('tax-feature', 'pass', {}, { 'worktree/api': { '--var': 'worktree=/wt/api' } });
edit('tax-feature', (s) => { s.vars.branch = { api: 'feat/tax-feature' }; });
r = step('tax-feature');
ok('parallel list runs together, counted once', ids(r.n) === 'build/api,write-tests' && state('tax-feature').steps_used === 6);
step('tax-feature');
step('tax-feature', 'fail', {}, { 'checks/api': { '--note': 'lint' } });
ok('checks on_fail re-runs only build of the list', ids(run('next', 'tax-feature')) === 'build/api');
run('end', 'tax-feature', 'build', 'pass', '--repo', 'api');
ok('then continues after the list', state('tax-feature').current === 'commit');
step('tax-feature'); step('tax-feature');
step('tax-feature', 'fail', {}, { 'code-review': { '--note': 'R1 blocker' } });
step('tax-feature');
ok('fix-review returns to code-review', state('tax-feature').current === 'code-review');
step('tax-feature');
step('tax-feature', 'fail', {}, { verify: { '--note': 'e2e 3 fails' } });
step('tax-feature');
ok('fix-tests returns to verify', state('tax-feature').current === 'verify');
for (let i = 0; i < 4; i++) step('tax-feature');
ok('after quiz comes archive', state('tax-feature').current === 'learn');
step('tax-feature'); step('tax-feature');
step('tax-feature', 'pass', {}, { 'pr/api': { '--var': 'pr=https://x/api/pull/3' } });
step('tax-feature'); step('tax-feature');
ok('fix steps skipped at the end: done', state('tax-feature').status === 'done', state('tax-feature').current);

// Interrupted: only the unfinished items run again, recorded ones and their values are kept.
begin('major-feature', 'cut-off');
for (let i = 0; i < 5; i++) step('cut-off', undefined, {}, { plan: { '--var': 'repos=[api, web]' } });
edit('cut-off', (s) => { s.current = 'worktree'; });
run('next', 'cut-off');
run('end', 'cut-off', 'worktree', 'pass', '--repo', 'api', '--var', 'worktree=/wt/api');
const used = state('cut-off').steps_used;
r = run('next', 'cut-off');
ok('interrupted: only the unfinished item', r.interrupted === true && ids(r) === 'worktree/web' && state('cut-off').steps_used === used);
run('end', 'cut-off', 'worktree', 'pass', '--repo', 'web', '--var', 'worktree=/wt/web');
ok('interrupted: values kept, run moves on', state('cut-off').vars.worktree.api === '/wt/api' && state('cut-off').current === 'build');
ok('end for an item not running is refused', run('end', 'cut-off', 'fix-review', 'pass').error?.includes('not running'));

// Values: a single repo, an empty list, a list of "name: reason" items, a bad list.
begin('bug-fix', 'one-repo'); step('one-repo');
step('one-repo', 'pass', {}, { investigate: { '--var': 'repos=api' } }); step('one-repo');
ok('a single repo works as a list', ids(run('next', 'one-repo')) === 'worktree/api');
begin('bug-fix', 'no-repos'); step('no-repos');
step('no-repos', 'pass', {}, { investigate: { '--var': 'repos=[]' } }); step('no-repos');
ok('no repos: waiting, budget kept', run('next', 'no-repos').reason?.includes('no repos') && state('no-repos').steps_used === 2);
begin('init', 'set-up-workspace');
step('set-up-workspace', 'pass', {}, { detect: { '--var': 'failing=[invoice-svc lint: 60 errors, web test: 2 fail]' } });
ok('a list of "name: reason" reads as text', run('next', 'set-up-workspace').todo[0].prompt.includes('invoice-svc lint: 60 errors, web test: 2 fail'));
ok('a bad list is refused with a hint', run('end', 'set-up-workspace', 'confirm', 'approved', '--var', 'x=[a, b').error?.includes('Write a list as'));

// A missing value stops the run, and goto can supply it.
fs.writeFileSync(path.join(P, '.maestro/workspace.yaml'), 'repos:\n  api:\n    path: .\n');
begin('bug-fix', 'no-worktree');
step('no-worktree'); step('no-worktree'); step('no-worktree'); step('no-worktree');
r = run('next', 'no-worktree');
ok('missing value: waiting, says how to give it', r.action === 'waiting' && r.reason.includes('${worktree}') && r.reason.includes('goto'));
run('goto', 'no-worktree', 'fix', '--var', 'worktree={api: /wt/api}', '--var', 'branch={api: fix/no-worktree}');
ok('goto --var supplies it', run('next', 'no-worktree').todo?.[0].instructions.includes('/wt/api'));

// Budget: used up waits, goto gives more steps.
begin('bug-fix', 'budget-run');
edit('budget-run', (s) => { s.steps_used = 30; });
ok('budget used up: waiting', run('next', 'budget-run').reason?.includes('budget'));
ok('goto gives 10 more steps', run('goto', 'budget-run', 'hypothesis').note?.includes('10 more') && run('next', 'budget-run').todo?.length === 1);

// Two `end` calls at once both land.
fs.writeFileSync(path.join(P, '.maestro/workspace.yaml'), WS2);
let lost = 0;
for (let i = 0; i < 5; i++) {
  const slug = `race-run-${'abcde'[i]}`;
  begin('bug-fix', slug); step(slug); step(slug, 'pass', {}, { investigate: { '--var': 'repos=[api, web]' } }); step(slug);
  run('next', slug);
  spawnSync('bash', ['-c', `node ${RUN} end ${slug} worktree pass --repo api --var worktree=/wt/api & node ${RUN} end ${slug} worktree pass --repo web --var worktree=/wt/web & wait`], { cwd: P });
  const s = state(slug);
  if (s.running.length || !s.vars.worktree?.api || !s.vars.worktree?.web) lost++;
}
ok('two ends at once: nothing lost', lost === 0, `${lost} of 5 lost`);

console.log(`run.mjs: ${pass} passed, ${fail} failed`);
fs.rmSync(P, { recursive: true, force: true });
process.exit(fail ? 1 : 0);
