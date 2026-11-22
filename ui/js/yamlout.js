// Reads a workflow file keeping its comments, and writes it back in the same style:
// the top comment block, one comment block per step, block text for instructions.
import { load } from '../vendor/js-yaml.mjs';

const ORDER = ['id', 'mode', 'agent', 'run', 'model', 'skills', 'template', 'foreach', 'next', 'command', 'workflow', 'prompt', 'instructions', 'on_fail', 'on_reject'];

export function parseWorkflow(text) {
  const wf = load(text) || {};
  if (!Array.isArray(wf.steps)) wf.steps = [];
  const lines = text.replace(/\r/g, '').split('\n');
  const header = [];
  for (const l of lines) { if (/^#/.test(l)) header.push(l); else break; }
  // Comments right above a top-level step belong to it. Skip lines inside block text.
  let pending = [], k = -1, block = -1;
  const start = lines.findIndex((l) => /^steps:/.test(l)) + 1; // only items under steps: are steps
  for (const l of lines.slice(Math.max(start, header.length))) {
    const ind = l.match(/^ */)[0].length;
    if (block >= 0) { if (!l.trim() || ind > block) continue; block = -1; }
    if (/^\s*#/.test(l)) { pending.push(l.trim()); continue; }
    if (!l.trim()) continue;
    if (/^ {2}- /.test(l)) { k++; if (pending.length && wf.steps[k]) wf.steps[k].__comment = pending; }
    pending = [];
    if (/:\s*[|>][-+]?\s*$/.test(l)) block = ind + (/^\s*- /.test(l) ? 2 : 0);
  }
  return { wf, header };
}

const RESERVED = /^(true|false|yes|no|on|off|null|~|[-+]?(\.\d|\d)[\d_.e+-]*|0x[\da-f]+|0o[0-7]+|[-+]?\.(inf|nan))$/i;
function scalar(v) {
  if (typeof v === 'number' || typeof v === 'boolean') return String(v);
  const s = String(v ?? '');
  const plain = s && !/^[\s\-?:,[\]{}#&*!|>'"%@`]/.test(s) && !/: |\s#|:$|\s$|\n/.test(s) && !RESERVED.test(s);
  return plain ? s : JSON.stringify(s);
}
// Inside [ ] or { }, a comma or bracket ends the value, so quote those; nested values go as JSON.
const inFlow = (v) => (v && typeof v === 'object' ? JSON.stringify(v) : /[,[\]{}]/.test(String(v)) ? JSON.stringify(String(v)) : scalar(v));
const flow = (v) => (Array.isArray(v) ? `[${v.map(inFlow).join(', ')}]`
  : v instanceof Date ? v.toISOString()
  : v && typeof v === 'object' ? `{${Object.entries(v).map(([a, b]) => `${scalar(a)}: ${inFlow(b)}`).join(', ')}}` : scalar(v));

function stepLines(step, pad) {
  const out = [];
  if (step.parallel) {
    out.push(`${pad}- parallel:`);
    for (const c of step.parallel) out.push(...stepLines(c, pad + '    '));
    return out;
  }
  const keys = [...ORDER.filter((k) => k in step), ...Object.keys(step).filter((k) => !ORDER.includes(k) && !k.startsWith('__'))];
  keys.forEach((k, i) => {
    const v = step[k];
    if (v == null || v === '') return;
    const lead = i === 0 ? `${pad}- ` : `${pad}  `;
    const text = typeof v === 'string' ? v.replace(/\n+$/, '') : null;
    if (text != null && (k === 'instructions' || text.includes('\n'))) {
      const first = text.split('\n').find((l) => l.trim()) || '';
      out.push(`${lead}${k}: |${/^\s/.test(first) ? '2' : ''}`); // an indented first line needs the indent stated
      for (const l of text.split('\n')) out.push(l.trim() ? `${pad}    ${l}` : '');
    } else out.push(`${lead}${k}: ${flow(v)}`);
  });
  return out;
}

export function dumpWorkflow(wf, header = []) {
  const out = [...header];
  for (const k of Object.keys(wf)) if (k !== 'steps' && wf[k] != null && wf[k] !== '') out.push(`${k}: ${flow(wf[k])}`);
  out.push(wf.steps.length ? 'steps:' : 'steps: []');
  wf.steps.forEach((s, i) => {
    if (i > 0) out.push('');
    for (const c of s.__comment || []) out.push(`  ${c}`);
    out.push(...stepLines(s, '  '));
  });
  return out.join('\n') + '\n';
}
