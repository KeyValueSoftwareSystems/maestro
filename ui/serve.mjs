#!/usr/bin/env node
// Maestro UI server. Serves the UI and a small file API for the project it runs in.
//   node .maestro/ui/serve.mjs [--port 7355]
// Listens on 127.0.0.1 only. Reads only .maestro/ (not worktrees), .claude/skills/ and
// .claude/commands/. Writes only workflow YAML and maestro-* commands. Node built-ins only.
import http from 'node:http';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const UI = path.dirname(fileURLToPath(import.meta.url));
const args = process.argv.slice(2);
const want = Number(args[args.indexOf('--port') + 1]) || 7355;

if (Number(process.versions.node.split('.')[0]) < 20) {
  console.error(`The Maestro UI needs Node 20 or later (this is ${process.version}).`);
  process.exit(1);
}

// The project is the nearest folder, from here up, that has .maestro/.
function findRoot(dir) {
  for (let d = dir; ; d = path.dirname(d)) {
    if (fs.existsSync(path.join(d, '.maestro'))) return d;
    if (path.dirname(d) === d) return null;
  }
}
const ROOT = findRoot(process.cwd()) || findRoot(UI);
if (!ROOT) {
  console.error('No .maestro/ folder here or above. Run this inside a project with Maestro installed.');
  process.exit(1);
}

// Matched case-insensitively: macOS and Windows file systems ignore case.
const READ = [/^\.maestro\/(?!worktrees(\/|$))/i, /^\.claude\/skills\//i, /^\.claude\/commands\//i];
const WRITE = [/^\.maestro\/workflows\/[\w./-]+\.yaml$/i, /^\.claude\/commands\/maestro-[\w-]+\.md$/i];
const SECRET = /(^|\/)(\.env[^/]*|[^/]*\.(pem|key|p12|pfx))$/i;
const TYPES = { '.html': 'text/html', '.css': 'text/css', '.js': 'text/javascript', '.mjs': 'text/javascript',
  '.svg': 'image/svg+xml', '.woff2': 'font/woff2', '.json': 'application/json' };

// A project-relative path, or null when it is outside the allowed folders.
const REAL_ROOT = fs.realpathSync(ROOT);
const ok = (p, rules) => !SECRET.test(p) && rules.some((r) => r.test(p) || r.test(p + '/'));
function allowed(rel, rules) {
  if (typeof rel !== 'string' || !rel || rel.includes('\0')) return null;
  const norm = path.posix.normalize(rel.replace(/\\/g, '/'));
  if (norm.startsWith('/') || norm.startsWith('..') || !ok(norm, rules)) return null;
  const abs = path.join(ROOT, norm);
  // Follow symlinks from the nearest folder that exists, and check the real path too.
  let base = abs, rest = '';
  while (!fs.existsSync(base)) { rest = path.join(path.basename(base), rest); base = path.dirname(base); }
  const real = path.join(fs.realpathSync(base), rest);
  const realRel = path.relative(REAL_ROOT, real).split(path.sep).join('/');
  if (realRel.startsWith('..') || path.isAbsolute(realRel) || !ok(realRel, rules)) return null;
  return abs;
}

function send(res, code, body, type = 'application/json') {
  res.writeHead(code, { 'Content-Type': type, 'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff' });
  res.end(typeof body === 'string' || Buffer.isBuffer(body) ? body : JSON.stringify(body));
}

function list(abs) {
  return fs.readdirSync(abs, { withFileTypes: true }).filter((e) => !e.name.startsWith('.')).map((e) => {
    const st = fs.statSync(path.join(abs, e.name));
    return { name: e.name, dir: e.isDirectory(), size: st.size, mtime: st.mtimeMs };
  });
}

// A workflow must not change while a run of it is running.
function runningWith(rel) {
  const runs = path.join(ROOT, '.maestro/runs');
  if (!fs.existsSync(runs)) return null;
  const name = path.basename(rel, '.yaml');
  for (const slug of fs.readdirSync(runs)) {
    let s = '';
    try { s = fs.readFileSync(path.join(runs, slug, 'state.yaml'), 'utf8'); } catch { continue; }
    if (!/^status:\s*running\b/m.test(s)) continue;
    if (rel.includes('/subworkflows/') || new RegExp(`^workflow:\\s*${name}\\s*$`, 'm').test(s)) return slug;
  }
  return null;
}

const clients = new Set();
let pending = new Set(), timer = null;
function changed(rel) {
  pending.add(rel);
  clearTimeout(timer);
  timer = setTimeout(() => {
    const data = `data: ${JSON.stringify([...pending])}\n\n`;
    pending = new Set();
    for (const c of clients) c.write(data);
  }, 150);
}
// Watch these folders, including ones that appear later (the first run makes .maestro/runs).
const watched = new Set();
function watchAll() {
  for (const dir of ['.maestro/runs', '.maestro/workflows', '.maestro/templates']) {
    const abs = path.join(ROOT, dir);
    if (watched.has(dir) || !fs.existsSync(abs)) continue;
    watched.add(dir);
    fs.watch(abs, { recursive: true }, (_e, f) => f && changed(`${dir}/${String(f).replace(/\\/g, '/')}`));
    changed(`${dir}/`);
  }
}
watchAll();
setInterval(watchAll, 3000).unref();

let port = want;
const server = http.createServer((req, res) => {
  try { handle(req, res); } catch (e) { if (!res.headersSent) send(res, 400, { error: String(e.message || e) }); else res.end(); }
});

function handle(req, res) {
  // Only this machine, by name: a page on another site can't reach us through DNS tricks.
  const host = req.headers.host || '';
  if (host !== `127.0.0.1:${port}` && host !== `localhost:${port}`) return send(res, 403, { error: 'bad host' });
  const url = new URL(req.url, `http://${host}`);

  if (url.pathname.startsWith('/api/')) {
    if (req.method !== 'GET') { // writes only from our own page
      const origin = req.headers.origin;
      if (origin !== `http://127.0.0.1:${port}` && origin !== `http://localhost:${port}`) return send(res, 403, { error: 'bad origin' });
    }
    const rel = url.searchParams.get('path');
    try {
      if (url.pathname === '/api/info' && req.method === 'GET') return send(res, 200, { project: path.basename(ROOT), root: ROOT });
      if (url.pathname === '/api/events' && req.method === 'GET') {
        res.writeHead(200, { 'Content-Type': 'text/event-stream', 'Cache-Control': 'no-store', Connection: 'keep-alive' });
        res.write(': hi\n\n');
        clients.add(res);
        req.on('close', () => clients.delete(res));
        return;
      }
      if (url.pathname === '/api/list' && req.method === 'GET') {
        const abs = allowed(rel, READ);
        if (!abs) return send(res, 403, { error: 'not allowed' });
        if (!fs.existsSync(abs)) return send(res, 200, []);
        return send(res, 200, list(abs));
      }
      if (url.pathname === '/api/file' && req.method === 'GET') {
        const abs = allowed(rel, READ);
        if (!abs) return send(res, 403, { error: 'not allowed' });
        if (!fs.existsSync(abs)) return send(res, 404, { error: 'not found' });
        const st = fs.statSync(abs);
        if (!st.isFile()) return send(res, 400, { error: 'not a file' });
        const max = 2 * 1024 * 1024; // big logs: send the end
        const fd = fs.openSync(abs, 'r');
        const len = Math.min(st.size, max);
        const buf = Buffer.alloc(len);
        fs.readSync(fd, buf, 0, len, st.size - len);
        fs.closeSync(fd);
        return send(res, 200, buf, 'text/plain; charset=utf-8');
      }
      if (url.pathname === '/api/file' && req.method === 'PUT') {
        const abs = allowed(rel, WRITE);
        if (!abs) return send(res, 403, { error: 'Only workflow YAML and maestro-* commands can be saved.' });
        const busy = rel.endsWith('.yaml') && runningWith(rel);
        if (busy) return send(res, 409, { error: `Run ${busy} is running this workflow. Save when it stops.` });
        let body = '';
        req.setEncoding('utf8');
        req.on('data', (c) => { body += c; if (body.length > 1e6) req.destroy(); });
        req.on('end', () => {
          try {
            fs.mkdirSync(path.dirname(abs), { recursive: true });
            fs.writeFileSync(abs, body);
            send(res, 200, { ok: true });
          } catch (e) { send(res, 500, { error: String(e.message || e) }); }
        });
        return;
      }
      return send(res, 404, { error: 'unknown' });
    } catch (e) {
      return send(res, 500, { error: String(e.message || e) });
    }
  }

  if (req.method !== 'GET') return send(res, 405, { error: 'method' });
  const file = url.pathname === '/' ? 'index.html' : decodeURIComponent(url.pathname.slice(1));
  const abs = path.join(UI, path.normalize(file));
  if (!abs.startsWith(UI + path.sep) || !fs.existsSync(abs) || !fs.statSync(abs).isFile() || abs.endsWith('serve.mjs')) {
    return send(res, 404, 'not found', 'text/plain');
  }
  send(res, 200, fs.readFileSync(abs), TYPES[path.extname(abs)] || 'application/octet-stream');
}

server.on('error', (e) => {
  if (e.code === 'EADDRINUSE' && port !== 0) {
    // Already serving this project? Then say where, and stop. Otherwise take any free port.
    http.get({ host: '127.0.0.1', port, path: '/api/info', timeout: 1000 }, (r) => {
      let b = ''; r.on('data', (c) => { b += c; });
      r.on('end', () => {
        try { if (JSON.parse(b).root === ROOT) { console.log(`Maestro UI for ${path.basename(ROOT)} is already running: http://127.0.0.1:${port}/`); process.exit(0); } } catch { /* not ours */ }
        port = 0; server.listen(0, '127.0.0.1');
      });
    }).on('error', () => { port = 0; server.listen(0, '127.0.0.1'); });
    return;
  }
  console.error(e.message);
  process.exit(1);
});
server.on('listening', () => {
  port = server.address().port;
  console.log(`Maestro UI for ${path.basename(ROOT)}: http://127.0.0.1:${port}/`);
});
server.listen(port, '127.0.0.1');
