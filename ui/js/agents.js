// The Agents screen: the cast, and each agent's skill file and templates.
import * as api from './api.js';
import { h, AGENTS, avatar, markdown, icon } from './util.js';

const SKILLS = '.claude/skills';

export function showCast(view) {
  view.dataset.screen = 'agents';
  view.replaceChildren(
    h('div', { style: { display: 'flex', flexDirection: 'column', gap: '8px' } }, h('h1', 'Agents'),
      h('p.hint', 'Each step in a workflow goes to one of these agents. Open one to read its skill file and the templates it writes from.')),
    h('div.cast', Object.entries(AGENTS).map(([k, a]) => h('a.agent', { href: `#/agents/${k}` },
      h('img', { src: avatar(k), alt: '' }), h('b', a.name), h('span.role', a.role), h('p', a.desc))),
    h('div.agent', { style: { cursor: 'default' } }, h('span.tile.gate', { html: icon('gate', 36) }), h('b', 'You'), h('span.role', 'Gates'),
      h('p', 'The run stops at every gate until you approve, or send it back with feedback, in the Claude Code conversation.'))));
}

export async function showAgent(view, key) {
  view.dataset.screen = 'agents';
  const a = AGENTS[key];
  if (!a) { view.replaceChildren(h('div.card.empty', `No agent called ${key}.`)); return; }
  const hasSkill = key !== 'worker';
  const skill = hasSkill ? await api.readOr(`${SKILLS}/${key}/SKILL.md`, '') : '';
  const fm = skill.match(/^---\n([\s\S]*?)\n---/);
  const desc = fm && (fm[1].match(/^description:\s*(.*)$/m) || [])[1];
  const tpls = hasSkill ? (await api.list(`${SKILLS}/${key}/templates`).catch(() => [])).filter((f) => !f.dir) : [];
  const overrides = new Set((await api.list('.maestro/templates').catch(() => [])).map((f) => f.name));
  let tab = 'skill', tpl = tpls[0] && tpls[0].name;

  const body = h('div');
  const draw = async () => {
    const tabs = h('div.seg', { role: 'tablist', 'aria-label': 'Files' },
      [['skill', 'Skill file'], ...(tpls.length ? [['tpl', `Templates (${tpls.length})`]] : [])].map(([t, l]) =>
        h('button', { type: 'button', role: 'tab', 'aria-selected': String(tab === t), onclick: () => { tab = t; draw(); } }, l)));
    let content;
    if (tab === 'skill') {
      content = [h('div.card-head', h('span.mono', { style: { fontSize: '12.5px', color: 'var(--muted)' } }, `${SKILLS}/${key}/SKILL.md`), tabs),
        h('div.doc.md', { html: markdown(skill) })];
    } else {
      const over = overrides.has(tpl);
      const path = over ? `.maestro/templates/${tpl}` : `${SKILLS}/${key}/templates/${tpl}`;
      const text = await api.readOr(path, '');
      content = [h('div.card-head', h('div.chips', tpls.map((t) => h('button', { type: 'button', 'aria-pressed': String(t.name === tpl), onclick: () => { tpl = t.name; draw(); } }, t.name))), tabs),
        h('div', { style: { padding: '0 28px' } }, h('p.hint', over
          ? [`This project overrides it: the agent uses `, h('code', path), '.']
          : ['To change this format for one project, put your own copy in ', h('code', '.maestro/templates/'), ' and pass it with ', h('code', 'template:'), ' on the step.'])),
        h('div.doc.md', { html: markdown(text) })];
    }
    body.replaceChildren(h('section.card', content));
  };

  view.replaceChildren(
    h('div.agent-head', h('img', { src: avatar(key), alt: '' }),
      h('div', { style: { display: 'flex', flexDirection: 'column', gap: '6px', flex: 1, minWidth: '240px' } },
        h('h1', a.name), h('span.role', { style: { color: 'var(--accent-ink)', fontWeight: 600 } }, a.role),
        h('p', { style: { margin: 0, color: 'var(--ink2)', maxWidth: '760px' } }, desc || a.desc))),
    hasSkill ? body : h('section.card', h('div.empty', 'Worker has no skill file and no templates. The lead hands it the step\'s instructions as they are, with the safety rules added, and it does exactly that.')));
  if (hasSkill) {
    if (!skill) body.replaceChildren(h('section.card', h('div.empty', `No skill file at ${SKILLS}/${key}/SKILL.md. Run install.sh again.`)));
    else await draw();
  }
}
