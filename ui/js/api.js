// Talks to serve.mjs. Every path is relative to the project folder.
import { yaml } from './util.js';

async function call(url, opts) {
  const res = await fetch(url, opts);
  if (!res.ok) {
    let msg = `${res.status}`;
    try { msg = (await res.json()).error || msg; } catch { /* not JSON */ }
    const err = new Error(msg); err.status = res.status; throw err;
  }
  return res;
}
const q = (p) => encodeURIComponent(p);

export const info = () => call('/api/info').then((r) => r.json());
export const list = (path) => call(`/api/list?path=${q(path)}`).then((r) => r.json());
export const read = (path) => call(`/api/file?path=${q(path)}`).then((r) => r.text());
export const readOr = (path, fallback = null) => read(path).catch(() => fallback);
export const readYaml = (path) => readOr(path).then((t) => { try { return yaml(t); } catch { return null; } });
export const write = (path, text) => call(`/api/file?path=${q(path)}`, { method: 'PUT', headers: { 'Content-Type': 'text/plain' }, body: text });

// Calls fn with the changed paths whenever files under .maestro/ change.
export function watch(fn) {
  let es;
  const open = () => {
    es = new EventSource('/api/events');
    es.onmessage = (e) => { try { fn(JSON.parse(e.data)); } catch { /* ignore */ } };
    es.onerror = () => { es.close(); setTimeout(open, 2000); };
  };
  open();
}
