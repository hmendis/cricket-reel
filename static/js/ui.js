// Shared look-and-feel pieces (design v2, Glow Panels): icons, toasts, dialogs, page heads, pills.
import { esc } from './core/util.js';

export const $ = (s, r = document) => r.querySelector(s);
export const $$ = (s, r = document) => [...r.querySelectorAll(s)];

// Lucide-style stroke icons. Never emoji.
const P = {
  grid: '<rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/>',
  upload: '<path d="M12 15V3"/><path d="m7 8 5-5 5 5"/><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>',
  audio: '<path d="M3 10v4"/><path d="M7 6v12"/><path d="M11 3v18"/><path d="M15 7v10"/><path d="M19 10v4"/>',
  scissors: '<circle cx="6" cy="6" r="3"/><circle cx="6" cy="18" r="3"/><path d="M20 4 8.12 15.88"/><path d="M14.47 14.48 20 20"/><path d="M8.12 8.12 12 12"/>',
  layers: '<path d="m12 2 10 5-10 5L2 7z"/><path d="m2 17 10 5 10-5"/><path d="m2 12 10 5 10-5"/>',
  sun: '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M6.34 17.66l-1.41 1.41M19.07 4.93l-1.41 1.41"/>',
  download: '<path d="M12 3v12"/><path d="m7 10 5 5 5-5"/><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>',
  type: '<path d="M4 7V4h16v3"/><path d="M9 20h6"/><path d="M12 4v16"/>',
  gear: '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 1 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.6 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 1 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.6a1.65 1.65 0 0 0 1-1.51V3a2 2 0 1 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 1 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/>',
  message: '<path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/><path d="M8 9h8M8 13h5"/>',
  check: '<path d="M20 6 9 17l-5-5"/>',
  // 2.1: the clip kinds (told apart by icon + word, never by a new colour)
  bat: '<g transform="rotate(40 12 12)"><rect x="9.5" y="1.5" width="5" height="13" rx="1.6"/><path d="M12 14.5v7"/></g>',
  ball: '<circle cx="12" cy="12" r="8.5"/><path d="M7.5 5.2c2.6 3.7 2.6 9.9 0 13.6M16.5 5.2c-2.6 3.7-2.6 9.9 0 13.6"/>',
  hand: '<path d="M18 11V6a2 2 0 0 0-4 0v5"/><path d="M14 10V4a2 2 0 0 0-4 0v6"/><path d="M10 10.5V6a2 2 0 0 0-4 0v8"/><path d="M18 8a2 2 0 1 1 4 0v6a8 8 0 0 1-8 8h-2c-2.8 0-4.5-.86-5.99-2.34l-3.6-3.6a2 2 0 0 1 2.83-2.82L7 15"/>',
  other: '<circle cx="12" cy="12" r="8.5"/><path d="M12 8v8M8 12h8"/>',
  up: '<path d="m18 15-6-6-6 6"/>',
  down: '<path d="m6 9 6 6 6-6"/>',
  pin: '<path d="M12 17v5"/><path d="M9 3h6l-1 7 4 3v2H6v-2l4-3z"/>',
  flag: '<path d="M4 22V4"/><path d="M4 4h13l-2.5 4L17 12H4"/>',
  play: '<path d="M7 4v16l13-8z"/>',
  pause: '<path d="M8 4v16M16 4v16"/>',
  prev: '<path d="M19 20 9 12l10-8z"/><path d="M5 19V5"/>',
  next: '<path d="m5 4 10 8-10 8z"/><path d="M19 5v14"/>',
  x: '<path d="M18 6 6 18M6 6l12 12"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  copy: '<rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/>',
  ext: '<path d="M15 3h6v6"/><path d="M10 14 21 3"/><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/>',
  star: '<path d="m12 2 3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01z"/>',
  info: '<circle cx="12" cy="12" r="10"/><path d="M12 16v-4M12 8h.01"/>',
  alert: '<path d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><path d="M12 9v4M12 17h.01"/>',
  folder: '<path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/>',
  refresh: '<path d="M21 12a9 9 0 1 1-3-6.7L21 8"/><path d="M21 3v5h-5"/>',
  coins: '<circle cx="8" cy="8" r="6"/><path d="M18.09 10.37A6 6 0 1 1 10.34 18"/><path d="M7 6h1v4"/>',
  film: '<rect x="3" y="2" width="18" height="20" rx="2"/><path d="M7 2v20M17 2v20M3 7h4M3 12h4M3 17h4M17 7h4M17 12h4M17 17h4"/>',
  link: '<path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"/><path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"/>',
  image: '<rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="9" cy="9" r="2"/><path d="m21 15-3.09-3.09a2 2 0 0 0-2.82 0L6 21"/>',
  shield: '<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/><path d="m9 12 2 2 4-4"/>',
  user: '<circle cx="12" cy="8" r="4"/><path d="M4 21a8 8 0 0 1 16 0"/>',
  target: '<circle cx="12" cy="12" r="10"/><circle cx="12" cy="12" r="6"/><circle cx="12" cy="12" r="2"/>',
  chev: '<path d="m9 18 6-6-6-6"/>',
  back: '<path d="m15 18-6-6 6-6"/>',
  clock: '<circle cx="12" cy="12" r="10"/><path d="M12 6v6l4 2"/>',
  trash: '<path d="M3 6h18M8 6V4h8v2M19 6l-1 14H6L5 6"/>',
  swap: '<path d="m17 2 4 4-4 4"/><path d="M3 11v-1a4 4 0 0 1 4-4h14"/><path d="m7 22-4-4 4-4"/><path d="M21 13v1a4 4 0 0 1-4 4H3"/>',
  undo: '<path d="M3 7v6h6"/><path d="M21 17a9 9 0 0 0-15-6.7L3 13"/>',
  table: '<rect x="3" y="3" width="18" height="18" rx="2"/><path d="M3 9h18M3 15h18M9 3v18"/>',
  grip: '<circle cx="9" cy="6" r="1"/><circle cx="15" cy="6" r="1"/><circle cx="9" cy="12" r="1"/><circle cx="15" cy="12" r="1"/><circle cx="9" cy="18" r="1"/><circle cx="15" cy="18" r="1"/>',
  eye: '<path d="M2 12s3-7 10-7 10 7 10 7-3 7-10 7-10-7-10-7z"/><circle cx="12" cy="12" r="3"/>',
  key: '<circle cx="7.5" cy="15.5" r="5.5"/><path d="m21 2-9.6 9.6M15.5 7.5l3 3L22 7l-3-3"/>',
  phone: '<rect x="6" y="2" width="12" height="20" rx="3"/><path d="M10 5h4"/>',
  loop: '<path d="m17 2 4 4-4 4"/><path d="M3 11v-1a4 4 0 0 1 4-4h14"/><path d="m7 22-4-4 4-4"/><path d="M21 13v1a4 4 0 0 1-4 4H3"/>',
  music: '<path d="M9 18V5l12-2v13"/><circle cx="6" cy="18" r="3"/><circle cx="18" cy="16" r="3"/>',
  keyboard: '<rect x="2" y="6" width="20" height="12" rx="2"/><path d="M6 10h.01M10 10h.01M14 10h.01M18 10h.01M7 14h10"/>',
};
export const ic = (n, cls = '') => `<svg class="i ${cls}" viewBox="0 0 24 24" aria-hidden="true">${P[n] || ''}</svg>`;

/** Short message at the bottom. Optional undo button. Errors get the alert icon. */
export function toast(msg, { undo = null, error = false, ms = 3500 } = {}) {
  const box = $('#toasts');
  const t = document.createElement('div');
  t.className = 'toast' + (error ? ' err' : '');
  t.setAttribute('role', error ? 'alert' : 'status');
  t.innerHTML = `${ic(error ? 'alert' : 'check')}<span>${esc(msg)}</span>${undo ? '<button class="btn sm">Undo</button>' : ''}`;
  if (undo) t.querySelector('button').onclick = () => { t.remove(); undo(); };
  box.appendChild(t);
  setTimeout(() => t.remove(), undo ? Math.max(ms, 6000) : ms);
}
export const toastErr = e => toast(e && e.message ? e.message : String(e), { error: true, ms: 6000 });

/** A dialog sheet. html is the inner content; returns { el, close }. Esc and the scrim close it. */
export function sheet(html, { accent = 'var(--blue)', label = '' } = {}) {
  const sc = document.createElement('div');
  sc.className = 'scrim';
  sc.innerHTML = `<div class="sheet" role="dialog" aria-modal="true" aria-label="${esc(label)}" style="--accent:${accent}">
    <button class="btn icon sm ghost" data-close style="position:absolute;right:14px;top:14px" aria-label="Close">${ic('x')}</button>${html}</div>`;
  const prev = document.activeElement;
  const close = () => { sc.remove(); document.removeEventListener('keydown', onKey, true); if (prev && prev.focus) prev.focus(); };
  const onKey = e => { if (e.key === 'Escape') { e.stopPropagation(); close(); } };
  document.addEventListener('keydown', onKey, true);
  sc.addEventListener('mousedown', e => { if (e.target === sc) close(); });
  sc.addEventListener('click', e => { if (e.target.closest('[data-close]')) close(); });
  document.body.appendChild(sc);
  setTimeout(() => { const f = sc.querySelector('textarea, input, .btn.primary'); if (f) f.focus(); }, 30);
  return { el: sc, close };
}

/** Yes/no question for things that can't be undone. Resolves true on OK. */
export function confirmSheet(title, body, okLabel, { danger = false } = {}) {
  return new Promise(resolve => {
    let done = false;
    const s = sheet(`<h2 style="padding-right:40px">${esc(title)}</h2><p class="small muted" style="margin:8px 0 18px">${body}</p>
      <div style="display:flex;gap:8px;justify-content:flex-end;flex-wrap:wrap"><button class="btn ghost" data-close>Cancel</button><button class="btn primary" data-ok ${danger ? 'style="--c:var(--pink)"' : ''}>${esc(okLabel)}</button></div>`,
    { accent: danger ? 'var(--pink)' : 'var(--blue)', label: title });
    s.el.querySelector('[data-ok]').onclick = () => { done = true; s.close(); resolve(true); };
    new MutationObserver((_, o) => { if (!document.body.contains(s.el)) { o.disconnect(); if (!done) resolve(false); } }).observe(document.body, { childList: true });
  });
}

export const head = (eyebrow, title, sub, acts = '') =>
  `<div class="page-head"><div class="lead"><div class="eyebrow"><span class="dot"></span>${eyebrow}</div><h1>${title}</h1>${sub ? `<p>${sub}</p>` : ''}</div><div class="acts">${acts}</div></div>`;

export const pill = (cls, text, dot = true) => `<span class="pill ${cls}">${dot ? '<span class="d"></span>' : ''}${text}</span>`;
export const note = (cls, icon, html, acts = '') => `<div class="note ${cls}">${ic(icon, 'sm')}<div>${html}${acts ? `<div class="acts">${acts}</div>` : ''}</div></div>`;

/** Kind of result → pill class (fixed colour meanings: big = amber, wicket = pink, extras = purple). */
export const kindClass = k => k === 'wicket' ? 'wicket' : k === 'big' ? 'big' : k === 'extra' ? 'purple' : 'normal';

export function countUp(root = document) {
  const reduce = matchMedia('(prefers-reduced-motion: reduce)').matches;
  $$('[data-count]', root).forEach(el => {
    const to = +el.dataset.count, dec = +(el.dataset.dec || 0);
    if (reduce) { el.textContent = to.toFixed(dec); return; }
    const t0 = performance.now();
    const step = now => { const p = Math.min(1, (now - t0) / 900), e = 1 - Math.pow(1 - p, 3); el.textContent = (to * e).toFixed(dec); if (p < 1) requestAnimationFrame(step); };
    requestAnimationFrame(step);
  });
}

export const gb = b => b >= 1e9 ? (b / 1e9).toFixed(2) + ' GB' : (b / 1e6).toFixed(1) + ' MB';
