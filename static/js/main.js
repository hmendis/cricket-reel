// Cricket Reel 2: hash router. Each screen is a module: mount(main, args) → { context(), key(e), unmount() }.
import { api } from './core/api.js';
import { esc } from './core/util.js';
import { $, ic, note } from './ui.js';
import { bindShell, refreshCost, renderJobChip, shell, topbar } from './shell.js';

const SCREENS = {
  home: () => import('./home.js'),
  import: () => import('./import.js'),
  sheet: () => import('./sheet.js'),
  sync: () => import('./sync.js'),
  review: () => import('./review.js'),
  arrange: () => import('./arrange.js'),
  export: () => import('./export.js'),
  describe: () => import('./describe.js'),
  settings: () => import('./settings.js'),
};
// Old addresses (bookmarks, the old interface) go to the screen that replaced them. 2.2: the Look step is gone.
const ALIAS = { new: 'import', 'sync-progress': 'sync', look: 'export' };
let seq = 0;

/** Re-draw the top bar with its step bar (after the match changed name or step). */
export function redrawShell() {
  const tb = $('.topbar');
  if (tb) tb.outerHTML = topbar();
  renderJobChip();
  refreshCost();
}

async function route() {
  const my = ++seq;
  const [name, ...rest] = (location.hash.slice(1) || 'home').split('/');
  const load = SCREENS[ALIAS[name] || name] || SCREENS.home;
  if (shell.screen && shell.screen.unmount) { try { shell.screen.unmount(); } catch (e) { /* */ } }
  shell.screen = null; shell.costOpen = false;
  try {
    const [mod, status] = await Promise.all([load(), api('GET', '/api/status')]);
    if (my !== seq) return;
    shell.status = status;
    // the screen sets shell.match / shell.step / shell.title in prepare() before the shell is drawn
    shell.match = null; shell.step = null; shell.title = '';
    const ctx = mod.prepare ? await mod.prepare(rest.map(decodeURIComponent)) : {};
    if (my !== seq || ctx === false) return;
    $('#app').innerHTML = topbar() + '<main class="page" id="main"></main>';
    window.scrollTo(0, 0);
    document.title = shell.match ? `${shell.match.name} · Cricket Reel` : 'Cricket Reel';
    renderJobChip(); refreshCost();
    shell.screen = (await mod.mount($('#main'), ctx)) || {};
    // 2.1: cards fade in when a screen opens, never again on a redraw of the same screen (a redraw used to replay the
    // fade on every card, so frequent redraws - like upload progress - made the whole page flash).
    setTimeout(() => { const m = $('#main'); if (m && my === seq) m.classList.add('settled'); }, 1500);
  } catch (e) {
    if (my !== seq) return;
    $('#app').innerHTML = topbar() + `<main class="page" id="main">${note('bad', 'alert', `<b>Something went wrong.</b> ${esc(e.message)}`, `<a class="btn sm" href="#home">${ic('back', 'sm')}Back to matches</a>`)}</main>`;
  }
}

document.addEventListener('keydown', e => {
  const t = e.target instanceof Element ? e.target : document.body, typing = (t.tagName === 'INPUT' && !['checkbox', 'range', 'radio'].includes(t.type)) || t.tagName === 'TEXTAREA' || t.tagName === 'SELECT' || t.isContentEditable;
  if (typing || document.querySelector('.scrim')) return;
  if ((e.key === 'Enter' || e.key === ' ') && t.matches('[role="button"]')) { e.preventDefault(); t.click(); return; }
  if ((e.key === 'Enter' || e.key === ' ') && ['BUTTON', 'A', 'SUMMARY'].includes(t.tagName)) return;
  if (shell.screen && shell.screen.key) shell.screen.key(e);
});
window.addEventListener('hashchange', route);
bindShell();
route();
