// Small helpers shared by every screen: element building, icons, markdown, times, toasts.
import { load } from '../vendor/js-yaml.mjs';

export const yaml = (text) => (text ? load(text) : null);

// Markup we built ourselves (icons, escaped markdown). Only this can become HTML.
class Raw { constructor(s) { this.s = s; } }
export const raw = (s) => new Raw(s);

// h('div.a.b', {attr}, ...children). Children are text, never HTML. Values read from files
// can be objects (YAML maps), so attributes only take functions for on*, and plain values.
export function h(tag, attrs, ...kids) {
  const [name, ...cls] = tag.split('.');
  const el = document.createElement(name);
  if (cls.length) el.className = cls.join(' ');
  const isAttrs = attrs != null && typeof attrs === 'object' && !(attrs instanceof Node) && !Array.isArray(attrs) && !(attrs instanceof Date) && !(attrs instanceof Raw);
  if (!isAttrs) { kids.unshift(attrs); attrs = null; }
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v == null || v === false) continue;
    if (k.startsWith('on')) { if (typeof v === 'function') el.addEventListener(k.slice(2), v); }
    else if (k === 'style' && typeof v === 'object') Object.assign(el.style, v);
    else if (k === 'html') { if (v instanceof Raw) el.innerHTML = v.s; }
    else if (['string', 'number', 'boolean'].includes(typeof v)) el.setAttribute(k, v === true ? '' : v);
  }
  for (const kid of kids.flat(Infinity)) {
    if (kid == null || kid === false) continue;
    el.append(kid instanceof Node ? kid : document.createTextNode(String(kid)));
  }
  return el;
}

export const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);

const P = (d) => `<path d="${d}"/>`;
const ICONS = {
  gate: P('M3 20a6 6 0 0 1 12 0') + '<circle cx="9" cy="8" r="3.5"/>' + P('M15.5 11.5l2 2 4-4'),
  exec: P('M5 4h14a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2z') + P('M7.5 9.5l2.5 2.5-2.5 2.5') + P('M13 15h3.5'),
  workflow: P('M12 3 3 8l9 5 9-5z') + P('M3 12.5l9 5 9-5') + P('M3 17l9 5 9-5'),
  close: P('M6 6l12 12M18 6 6 18'),
  check: P('M5 12.5l4.5 4.5L19 7'),
  x: P('M7 7l10 10M17 7 7 17'),
  alert: '<circle cx="12" cy="12" r="9"/>' + P('M12 7.5v5.5') + P('M12 16.5h.01'),
  file: P('M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z') + P('M14 3v5h5'),
  log: P('M4 6h16M4 12h16M4 18h10'),
  plus: P('M12 5v14M5 12h14'),
  horiz: P('M3 12h4M10 12h4M17 12h4') + '<circle cx="5" cy="12" r="0"/>',
  vert: P('M12 3v4M12 10v4M12 17v4'),
  pause: P('M9 6v12M15 6v12'),
  copy: '<rect x="8" y="8" width="12" height="12" rx="2"/>' + P('M16 8V6a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2h2'),
  up: P('m6 15 6-6 6 6'), down: P('m6 9 6 6 6-6'),
};
export function icon(name, size = 16, extra = '') {
  return raw(`<svg width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" ${extra}>${ICONS[name] || ''}</svg>`);
}
export const ico = (name, size) => h('span', { html: icon(name, size), style: { display: 'inline-flex' } });

export const AGENTS = {
  keystone: { name: 'Keystone', role: 'Planner', verb: 'Planning…', desc: 'Brainstorms with you, designs the change and writes the plan.' },
  brew: { name: 'Brew', role: 'Implementer', verb: 'Brewing…', desc: 'Writes the code and its tests, then fixes what checks and reviews find.' },
  birbal: { name: 'Birbal', role: 'Reviewer', verb: 'Reviewing…', desc: 'Reviews plans, code and docs, and keeps a findings table.' },
  litmus: { name: 'Litmus', role: 'Tester', verb: 'Testing…', desc: 'Writes tests from the test plan, or runs them and reports.' },
  sherlock: { name: 'Sherlock', role: 'Debugger', verb: 'Investigating…', desc: 'Reproduces a bug and finds its root cause.' },
  socrates: { name: 'Socrates', role: 'Knowledge keeper', verb: 'Writing docs…', desc: 'Builds the docs from the code, and updates them after a change.' },
  worker: { name: 'Worker', role: 'Does what the step says', verb: 'Working…', desc: 'Has no skill file. It runs the step\'s instructions as they are.' },
};
export const avatar = (agent) => `assets/agents/${AGENTS[agent] ? agent : 'worker'}.svg`;

// The picture for a step: the agent's face, or a tile for a gate, command or workflow.
export function face(step, cls = 'av') {
  const mode = step.mode || 'agent';
  if (mode === 'agent') return h('img.' + cls, { src: avatar(step.agent), alt: '' });
  return h('span.tile.' + mode, { html: icon(mode, 28) });
}

export function ago(iso) {
  if (!iso) return '';
  const t = new Date(iso).getTime();
  if (Number.isNaN(t)) return String(iso);
  const s = Math.round((Date.now() - t) / 1000);
  if (s < 45) return 'just now';
  if (s < 3600) return `${Math.round(s / 60)} min ago`;
  if (s < 86400) return `${Math.round(s / 3600)} h ago`;
  return new Date(t).toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
}
export function took(from, to) {
  const ms = new Date(to) - new Date(from);
  if (!(ms >= 0)) return '';
  const m = Math.round(ms / 60000);
  return m < 1 ? `${Math.round(ms / 1000)} s` : m < 60 ? `${m} min` : `${Math.floor(m / 60)} h ${m % 60} min`;
}

let toastTimer;
export function toast(msg) {
  const el = document.getElementById('toast');
  el.textContent = msg;
  el.classList.add('on');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.remove('on'), 2600);
}

// Markdown to HTML for the files Maestro writes: headings, lists, tables, code, emphasis.
export function markdown(src) {
  const lines = String(src).replace(/\r/g, '').split('\n');
  const out = [];
  const inline = (t) => esc(t)
    .replace(/`([^`]+)`/g, '<code>$1</code>')
    .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
    .replace(/(^|[^*])\*([^*\s][^*]*)\*/g, '$1<em>$2</em>')
    .replace(/\[([^\]]+)\]\((https?:[^)\s]+)\)/g, '<a href="$2" target="_blank" rel="noreferrer">$1</a>');
  let i = 0;
  if (lines[0] === '---') { const end = lines.indexOf('---', 1); if (end > 0) i = end + 1; }
  while (i < lines.length) {
    const l = lines[i];
    if (/^```/.test(l)) {
      const buf = []; i++;
      while (i < lines.length && !/^```/.test(lines[i])) buf.push(lines[i++]);
      i++; out.push(`<pre><code>${esc(buf.join('\n'))}</code></pre>`); continue;
    }
    const hd = l.match(/^(#{1,4})\s+(.*)/);
    if (hd) { out.push(`<h${hd[1].length}>${inline(hd[2])}</h${hd[1].length}>`); i++; continue; }
    if (/^\s*\|.*\|\s*$/.test(l)) {
      const rows = [];
      while (i < lines.length && /^\s*\|.*\|\s*$/.test(lines[i])) rows.push(lines[i++]);
      const cells = (r) => r.trim().replace(/^\||\|$/g, '').split(/(?<!\\)\|/).map((c) => c.trim());
      const body = rows.filter((r) => !/^\s*\|[\s:|-]+\|\s*$/.test(r));
      const [head, ...rest] = body;
      if (!head) continue;
      out.push('<table><thead><tr>' + cells(head).map((c) => `<th>${inline(c)}</th>`).join('') + '</tr></thead><tbody>' +
        rest.map((r) => '<tr>' + cells(r).map((c) => `<td>${inline(c)}</td>`).join('') + '</tr>').join('') + '</tbody></table>');
      continue;
    }
    if (/^\s*([-*]|\d+\.)\s+/.test(l)) {
      const ordered = /^\s*\d+\./.test(l); const items = [];
      while (i < lines.length && (/^\s*([-*]|\d+\.)\s+/.test(lines[i]) || (/^\s{2,}\S/.test(lines[i]) && items.length))) {
        if (/^\s*([-*]|\d+\.)\s+/.test(lines[i])) items.push(lines[i].replace(/^\s*([-*]|\d+\.)\s+/, ''));
        else items[items.length - 1] += ' ' + lines[i].trim();
        i++;
      }
      const tag = ordered ? 'ol' : 'ul';
      out.push(`<${tag}>` + items.map((t) => `<li>${inline(t.replace(/^\[( |x)\]\s*/i, (m, x) => (x.trim() ? '☑ ' : '☐ ')))}</li>`).join('') + `</${tag}>`);
      continue;
    }
    if (/^>\s?/.test(l)) { const buf = []; while (i < lines.length && /^>\s?/.test(lines[i])) buf.push(lines[i++].replace(/^>\s?/, '')); out.push(`<blockquote>${inline(buf.join(' '))}</blockquote>`); continue; }
    if (/^---+\s*$/.test(l)) { out.push('<hr>'); i++; continue; }
    if (!l.trim()) { i++; continue; }
    const buf = [lines[i++]];
    while (i < lines.length && lines[i].trim() && !/^(#{1,4}\s|```|\s*\||\s*([-*]|\d+\.)\s|>)/.test(lines[i])) buf.push(lines[i++]);
    out.push(`<p>${inline(buf.join(' '))}</p>`);
  }
  return raw(out.join('\n'));
}
