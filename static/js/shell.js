// The app shell: one top bar (plain-text app name + version, match crumb, the step bar, saved state, running job,
// Claude cost, Provide feedback, settings). 2.2: the step bar sits in the top bar, only once a match is open. No logos (G2).
import { api } from './core/api.js';
import { isActive } from './core/jobs.js';
import { esc, money } from './core/util.js';
import { $, ic, sheet, toast, toastErr } from './ui.js';

// 'look' stays in the order (2.2 removed the Look step) so a match saved at that step still opens, as arranged.
const ORDER = ['import', 'sheet', 'sync', 'synced', 'review', 'arrange', 'look', 'exported', 'described'];
const at = s => Math.max(0, ORDER.indexOf(s));

export const STEPS = [
  { key: 'import', name: 'Import', icon: 'upload', c: '--blue', href: id => `#import/${id}`, open: 'import', done: 'sync' },
  { key: 'sync', name: 'Sync', icon: 'audio', c: '--teal', href: id => `#sync/${id}`, open: 'sync', done: 'synced' },
  { key: 'review', name: 'Review', icon: 'scissors', c: '--green', href: id => `#review/${id}`, open: 'synced', done: 'arrange' },
  { key: 'arrange', name: 'Arrange', icon: 'layers', c: '--amber', href: id => `#arrange/${id}`, open: 'review', done: 'look' },
  { key: 'export', name: 'Export', icon: 'download', c: '--blue', href: id => `#export/${id}`, open: 'arrange', done: 'exported' },
  { key: 'describe', name: 'Describe', icon: 'type', c: '--purple', href: id => `#describe/${id}`, open: 'exported', done: 'described' },
];
export const stepNo = key => STEPS.findIndex(s => s.key === key) + 1;
/** "Step 3 of 6 · Review" */
export const stepLabel = (key, name) => `Step ${stepNo(key)} of ${STEPS.length} · ${name || STEPS[stepNo(key) - 1].name}`;

export const shell = {
  status: null,     // /api/status
  match: null,      // the open match (or null in the library)
  step: null,       // nav key of the screen ('import', 'sync', …) or null
  title: '',        // crumb text when there is no match
  screen: null,     // the mounted screen: { context(), key(e), unmount() }
  costOpen: false,
};

export function topbar() {
  const m = shell.match;
  return `<header class="topbar">
    <a class="appname" href="#home" aria-label="Cricket Reel, all matches">Cricket Reel<span class="ver">v${esc(shell.status ? shell.status.version : '')}</span></a>
    ${m ? `<div class="crumb"><span class="sep">/</span><b title="${esc(m.name)}">${esc(m.name)}</b></div>`
      : shell.title ? `<div class="crumb"><span class="sep">/</span><b>${esc(shell.title)}</b></div>` : ''}
    ${nav()}
    <div class="tb-right">
      ${m ? `<span class="saved" id="saved" aria-live="polite">${ic('check', 'sm')}<span>Saved</span></span>` : ''}
      <span id="jobchip"></span>
      <div style="position:relative" id="costwrap"><button class="costchip" data-shell="cost" aria-expanded="false" title="Claude API cost">${ic('coins', 'sm')}<span id="costusd">$0.00</span></button></div>
      <button class="btn sm" data-shell="feedback" title="Save a feedback bundle for a later Claude session">${ic('message', 'sm')}<span class="hide-sm">Provide feedback</span></button>
      <a class="btn icon sm ghost" href="#settings" aria-label="Settings" title="Settings">${ic('gear')}</a>
    </div>
  </header>`;
}

/** The step bar: only while a match is open (not on Home, Settings or a new match without one). */
export function nav() {
  const m = shell.match, reached = m ? at(m.step) : -1;
  if (!m) return '';
  const items = STEPS.map(s => {
    const on = shell.step === s.key, ok = m && reached >= at(s.open), done = m && reached >= at(s.done);
    const href = ok ? s.href(m.id) : '#';
    return `<a href="${href}" class="${on ? 'on' : ''} ${done ? 'done' : ''}" style="--c:var(${s.c})" aria-label="${s.name}${done ? ' (done)' : ''}${ok ? '' : ' (not available yet)'}"
      ${on ? 'aria-current="page"' : ''} ${ok ? '' : 'aria-disabled="true" tabindex="-1"'} title="${s.name}">${ic(s.icon)}<span>${s.name}</span></a>`;
  }).join('');
  return `<nav class="nav" aria-label="Workflow">${items}</nav>`;
}

/** Saved / Saving… / Not saved, in the top bar. */
export function saving(state) {
  const el = $('#saved');
  if (!el) return;
  el.lastElementChild.textContent = state === 'saving' ? 'Saving…' : state === 'error' ? 'Not saved' : 'Saved';
  el.style.color = state === 'error' ? 'var(--pink)' : '';
}

// ---------- Claude cost (E3) ----------
let usage = null;
export async function refreshCost() {
  try {
    usage = await api('GET', '/api/usage' + (shell.match ? `?match_id=${encodeURIComponent(shell.match.id)}` : ''));
    const el = $('#costusd');
    if (el) el.textContent = money(shell.match ? usage.match.usd : usage.session.usd);
  } catch (e) { /* the chip just keeps its last value */ }
}
function costPop() {
  const u = usage || { match: { usd: 0, calls: 0, steps: [] }, session: { usd: 0, calls: 0 } };
  const rows = u.match.steps.map(s => `<tr><td><b>${esc(s.name)}</b><br><span class="muted">${s.calls} call${s.calls === 1 ? '' : 's'} · ${s.input.toLocaleString('en-AU')} in · ${s.output.toLocaleString('en-AU')} out tokens${s.models.length ? ' · ' + esc(s.models.join(', ')) : ''}</span></td><td>${money(s.usd)}</td></tr>`).join('');
  return `<div class="pop" role="dialog" aria-label="Claude API cost">
    ${shell.match ? `<div class="label" style="margin-top:0">This match</div><table>${rows || '<tr><td class="muted">No Claude calls yet. Spawtz score sheets are free.</td><td></td></tr>'}
      <tr class="tot"><td>Match total · ${u.match.calls} call${u.match.calls === 1 ? '' : 's'}</td><td>${money(u.match.usd)}</td></tr></table>` : ''}
    <div class="label" ${shell.match ? '' : 'style="margin-top:0"'}>Since the app opened</div>
    <table><tr class="tot"><td>Session total · ${u.session.calls} call${u.session.calls === 1 ? '' : 's'}</td><td>${money(u.session.usd)}</td></tr></table>
    <p class="cap muted" style="margin-top:8px">Worked out from the tokens in each response and the model's price list, in US dollars. Video never leaves this laptop.</p>
  </div>`;
}
function toggleCost(force) {
  shell.costOpen = force ?? !shell.costOpen;
  const w = $('#costwrap'); if (!w) return;
  const old = w.querySelector('.pop'); if (old) old.remove();
  w.firstElementChild.setAttribute('aria-expanded', shell.costOpen);
  if (shell.costOpen) { w.insertAdjacentHTML('beforeend', costPop()); refreshCost().then(() => { const p = w.querySelector('.pop'); if (p && shell.costOpen) p.outerHTML = costPop(); }); }
}

// ---------- Provide feedback (G4) ----------
function feedbackSheet() {
  const ctx = (shell.screen && shell.screen.context && shell.screen.context()) || '';
  const where = (STEPS.find(s => s.key === shell.step) || {}).name || (shell.match ? 'Match' : shell.title || 'Matches');
  const env = shell.status ? `v${shell.status.version}${shell.status.desktop ? ', desktop app' : ', browser'}${shell.status.ffprobe ? ', FFmpeg found' : ''}` : '';
  const s = sheet(`<div class="eyebrow"><span class="dot"></span>Provide feedback</div><h2>Save a feedback bundle</h2>
    <p class="small muted" style="margin:6px 0 14px">A later Claude session can read it to fix or improve the app. It's saved on this laptop; nothing is sent anywhere.</p>
    <label class="field"><span>What happened, or what would you change?</span><textarea id="fbtext" maxlength="5000" placeholder="For example: pinning ball 3.4 moved the wrong ball"></textarea></label>
    <div class="label">Included</div>
    <div class="check-list">
      <label class="switch"><span class="t">This screen<small>${esc(where)}${ctx ? ' · ' + esc(ctx) : ''}</small></span><input type="checkbox" data-inc="screen" checked></label>
      <label class="switch"><span class="t">Recent logs<small>The app's last log lines</small></span><input type="checkbox" data-inc="logs" checked></label>
      <label class="switch"><span class="t">App and environment<small>${esc(env)}, Windows and Python versions</small></span><input type="checkbox" data-inc="env" checked></label>
      ${shell.match ? '<label class="switch"><span class="t">This match\'s data<small>match.json, sync.json, scorecard. No video.</small></span><input type="checkbox" data-inc="match" checked></label>' : ''}
    </div>
    <div class="label">Removed before saving</div>
    <div class="redact">API key            → <em>[removed]</em>
Passwords, tokens  → <em>[removed]</em>
Folders outside the app → <em>[outside path]</em>
Matches and app folders → <em>kept</em></div>
    <div style="display:flex;gap:8px;justify-content:flex-end;margin-top:16px;flex-wrap:wrap"><button class="btn ghost" data-close>Cancel</button><button class="btn primary" data-save>${ic('download', 'sm')}Save bundle</button></div>`,
  { accent: 'var(--purple)', label: 'Provide feedback' });
  s.el.querySelector('[data-save]').onclick = async e => {
    e.currentTarget.disabled = true;
    const include = {};
    s.el.querySelectorAll('[data-inc]').forEach(c => { include[c.dataset.inc] = c.checked; });
    try {
      const r = await api('POST', '/api/feedback', {
        message: s.el.querySelector('#fbtext').value,
        screen: include.screen ? { route: shell.step || 'home', hash: location.hash, context: ctx } : { route: shell.step || 'home' },
        match_id: shell.match ? shell.match.id : null, include,
      });
      s.close();
      showSaved(r.name);
    } catch (err) { e.currentTarget.disabled = false; toastErr(err); }
  };
}
function showSaved(name) {
  const s = sheet(`<div class="eyebrow"><span class="dot"></span>Feedback saved</div><h2>${ic('check')} Bundle saved</h2>
    <p class="small muted" style="margin:8px 0 6px">In the app's feedback folder as</p><p class="mono small" style="overflow-wrap:anywhere">${esc(name)}</p>
    <div style="display:flex;gap:8px;justify-content:flex-end;margin-top:16px"><button class="btn ghost" data-close>Close</button><button class="btn primary" data-open>${ic('folder', 'sm')}Open the folder</button></div>`, { accent: 'var(--purple)', label: 'Feedback saved' });
  s.el.querySelector('[data-open]').onclick = async () => { try { const r = await api('POST', '/api/feedback/open-folder'); s.close(); if (!shell.status.desktop) toast('Feedback folder: ' + r.folder, { ms: 8000 }); } catch (err) { toastErr(err); } };
}

// ---------- running job chip (a sync keeps going if you leave its screen) ----------
let jobs = [], jobT = 0;
async function pollJobs() {
  clearTimeout(jobT);
  try { jobs = (await api('GET', '/api/jobs')).filter(isActive); } catch (e) { jobs = []; }
  renderJobChip();
  jobT = setTimeout(pollJobs, jobs.length ? 2000 : 6000);
}
export function renderJobChip() {
  const el = $('#jobchip'); if (!el) return;
  const j = jobs[0];
  const page = j && `#${{ sync: 'sync', render: 'arrange', export: 'export', describe: 'describe' }[j.kind] || 'home'}/${j.match_id}`;
  const here = j && shell.match && shell.match.id === j.match_id && shell.step === ({ sync: 'sync', render: 'arrange', export: 'export', describe: 'describe' }[j.kind]);
  const word = { sync: 'Syncing', render: 'Rendering', export: 'Exporting', describe: 'Writing' }[j && j.kind] || 'Working';
  el.innerHTML = j && !here ? `<a class="jobchip" href="${page}" title="Open the running job"><span class="spin"></span>${word} ${Math.floor((j.progress || 0) * 100)}%</a>` : '';
}

export function bindShell() {
  document.addEventListener('click', e => {
    const b = e.target.closest('[data-shell]');
    if (b) { e.preventDefault(); if (b.dataset.shell === 'cost') toggleCost(); else feedbackSheet(); return; }
    if (shell.costOpen && !e.target.closest('#costwrap')) toggleCost(false);
    const a = e.target.closest('a[aria-disabled="true"]'); if (a) e.preventDefault();
  });
  document.addEventListener('keydown', e => { if (e.key === 'Escape' && shell.costOpen) toggleCost(false); });
  pollJobs();
}
export const kickJobs = () => pollJobs();
/** A save moved the match on (steps only go forward): unlock the next steps in the nav. */
export function reached(step) {
  if (!shell.match || at(shell.match.step) >= at(step)) return;
  shell.match.step = step;
  const nv = $('.topbar .nav'); if (nv) nv.outerHTML = nav();
}
export const openFeedback = () => feedbackSheet();
