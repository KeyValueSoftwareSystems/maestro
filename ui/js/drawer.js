// The side panel. open(key, build) shows what build() returns; Escape or the close button hides it.
const el = () => document.getElementById('drawer');

export const drawer = {
  key: null,
  async open(key, build) {
    const same = this.key === key;
    this.key = key;
    const d = el();
    const content = await build();
    if (this.key !== key) return; // another open() won
    const top = same && !d.hidden ? d.scrollTop : 0;
    d.replaceChildren(content);
    d.hidden = false;
    d.scrollTop = top;
  },
  close() {
    this.key = null;
    el().hidden = true;
    el().replaceChildren();
    document.querySelectorAll('.node.sel').forEach((n) => n.classList.remove('sel'));
  },
};

document.addEventListener('keydown', (e) => { if (e.key === 'Escape' && drawer.key) drawer.close(); });
