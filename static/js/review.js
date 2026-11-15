// Step 3 · Review: check each clip. Dots and leg-side wides start as not kept (K2); turn any back on. Move the
// contact point, change the clip window, keep, star, export as a clip. 2.2: one window, no page scroll - the clip
// list (two columns), a compact inspector and the video. Only the clips the match's reels use are shown. Edits update
// only the row, the inspector and the counts they touch (R14).
import { api } from './core/api.js';
import { exportOn, reelKinds, sectionOf } from './core/reel.js';
import { createAutosave, createHistory } from './core/state.js';
import { clamp, esc, mmss } from './core/util.js';
import { $, ic, kindClass, pill, toast, toastErr } from './ui.js';
import { reached, saving, shell, stepLabel } from './shell.js';

const enc = encodeURIComponent, FRAME = 0.04;
let V = null;

const ROLES = { batting: ['Batting', 'bat'], bowling: ['Bowling', 'ball'], fielding: ['Fielding', 'hand'], other: ['Other', 'other'] };
const role = c => c.role || 'batting';
const isW = c => !!c.wid;
const needsCheck = c => c.conf === 'low' && !c.confirmed;
const bigShot = c => c.source !== 'manual' && !c.wid && /^\d+$/.test(String(c.code).trim()) && +c.code >= 4;
const FILTERS = {
  all: ['All', () => true],
  batting: ['Batting', c => role(c) === 'batting', 'bat'],
  bowling: ['Bowling', c => role(c) === 'bowling', 'ball'],
  fielding: ['Fielding', c => role(c) === 'fielding', 'hand'],
  check: ['Check', c => c.keep && needsCheck(c)],
  drop: ['Not kept', c => !c.keep],
  clip: ['As clip', exportOn, 'film'],
  big: ['Big shots', bigShot],
};
const AUTO = { 'dot ball': 'Dot ball', 'leg-side wide': 'Leg-side wide', 'no-ball': 'No-ball' };
const KEYS = 'Keys: ↑/↓ clip · Space play · , . frame · Shift+←/→ move ¼ s · C at playhead · N snap · X keep · S star · E export as clip · Enter checked · Ctrl+Z undo';

export async function prepare([id]) {
  const d = await api('GET', `/api/matches/${enc(id)}/review`);
  shell.match = d.match; shell.step = 'review';
  return { d };
}

export async function mount(main, { d }) {
  const kinds = reelKinds(d.match);
  V = { main, id: d.match.id, clips: d.clips, cands: d.candidates || [], defaults: d.defaults, dur: d.duration, filter: 'all', sel: null, raf: 0, opened: null,
    kinds, multi: kinds.length > 1 };
  main.classList.add('wide', 'fit');
  const shown = reelClips();
  const firstCheck = shown.find(c => c.keep && needsCheck(c));
  V.sel = (firstCheck || shown.find(c => c.keep) || shown[0] || {}).index;
  V.hist = createHistory(() => V.clips, x => { V.clips = x; });
  V.save = createAutosave({
    key: 'clips', url: () => `/api/matches/${enc(V.id)}/clips`, body: () => ({ clips: V.clips }),
    send: b => api('PUT', `/api/matches/${enc(V.id)}/clips`, b).then(r => { reached('review'); return r; }), onState: (s, e) => { saving(s); if (e) toastErr(e); },
  });
  main.style.setProperty('--accent', 'var(--green)');
  render();
  bind();
  return {
    context: () => { const c = cur(); return c ? `${name(c)} selected · ${reelClips().filter(x => x.keep).length} kept · ${reelClips().filter(exportOn).length} export as clips` : ''; },
    key: onKey,
    unmount: () => { V.save.flush(); cancelAnimationFrame(V.raf); const v = vid(); if (v) { v.pause(); v.removeAttribute('src'); v.load(); } },
  };
}

/** The clips this match's reels use (a Batting match never shows wickets in the field, and so on). */
const reelClips = () => V.clips.filter(c => V.kinds.includes(sectionOf(c)));
const cur = () => V.clips.find(c => c.index === V.sel);
const vid = () => $('#rv');
const name = c => c.source === 'manual' ? (c.label ? c.label.charAt(0) + c.label.slice(1).toLowerCase() : 'Your clip') : `Over ${c.over} · Ball ${c.ball}`;
const ballNo = c => c.source === 'manual' ? mmss(c.t, 0) : `${c.over}.${c.ball}`;
const thumb = c => `/api/matches/${enc(V.id)}/thumb/${Math.max(0, Math.floor(c.t))}`;
const resPill = c => c.source === 'manual' ? pill('normal', esc(c.label || 'Your clip'), false) : pill(kindClass(c.kind), esc(c.label));
const confPill = c => isW(c)
  ? (c.wconf === 'confirmed' || c.confirmed ? pill('keep', 'Confirmed') : c.wconf === 'celebration' ? pill('check', 'Celebration heard') : '<span class="pill check dash"><span class="d"></span>Timing only</span>')
  : c.source === 'manual' ? '' : c.conf === 'high' ? pill('keep', 'High') : c.conf === 'med' ? pill('normal', 'Medium') : pill('check', c.confirmed ? 'Checked' : 'Needs a check');
/** Filters worth showing: All, the kinds (when the reel has more than one), then the rest; a zero count hides a chip unless it's on. */
function filters() {
  const cs = reelClips(), keys = ['all', ...(V.multi ? V.kinds : []), 'check', 'drop', 'clip', ...(V.kinds.includes('batting') ? ['big'] : [])];
  return keys.map(k => { const [l, f, i] = FILTERS[k]; return [k, l, f, i, cs.filter(f).length]; }).filter(([k, , , , n]) => k === 'all' || n > 0 || V.filter === k);
}
const listed = () => reelClips().filter((FILTERS[V.filter] || FILTERS.all)[1]);

function render() {
  V.main.innerHTML = `<div class="studio fit"><div class="smain">
      <div class="fithead">
        <span class="eyebrow"><span class="dot"></span>${stepLabel('review')}</span>
        <span class="sum" id="rsum"></span>
        <span class="acts" id="racts"></span>
      </div>
      <div class="rv-grid">
        <section class="card a-green rv-list" style="--i:0" aria-label="Your clips">
          <div class="chips scroll" style="margin-bottom:8px" id="filters"></div>
          <div class="rows" id="rlist" role="list"></div>
        </section>
        <section class="card a-green rv-insp" style="--i:1" id="insp" aria-label="This clip"></section>
      </div>
    </div>
    <aside class="vcol" aria-label="Video"><div class="vframe"><video id="rv" src="/api/matches/${enc(V.id)}/proxy" preload="auto" playsinline></video><div class="vcap"><span class="tc" id="rtc"></span><span class="tc" id="ropen" hidden>Opens on the celebration</span></div></div></aside>
  </div>`;
  drawHead(); drawFilters(); drawList(); drawInspector();
  const v = vid();
  v.addEventListener('loadedmetadata', () => play(true), { once: true });
  v.addEventListener('play', () => { setPlayBtn(true); loop(); });
  v.addEventListener('pause', () => { setPlayBtn(false); cancelAnimationFrame(V.raf); tc(); });
}

function drawHead() {
  const cs = reelClips(), kept = cs.filter(c => c.keep).length, xc = cs.filter(exportOn).length, chk = cs.filter(c => c.keep && needsCheck(c)).length;
  const auto = cs.filter(c => c.auto && !c.keep).length, edited = V.clips.some(c => c.edited || c.confirmed);
  $('#rsum').innerHTML = `<b>${kept}</b> of ${cs.length} kept · <b>${xc}</b> export as clip${xc === 1 ? '' : 's'} · ${chk ? `<span style="color:var(--check)">${chk} need${chk === 1 ? 's' : ''} a check</span>` : 'every clip checked'}${auto ? ` · ${auto} ${esc(autoRule(auto))} off by default` : ''}`;
  $('#rsum').title = auto ? 'Dots and leg-side wides start as not kept. Change the rule in Settings.' : '';
  $('#racts').innerHTML = `${edited ? `<button class="btn sm ghost" data-act="resync" title="Pin every clip you moved or confirmed, then re-run the sync around them">${ic('refresh', 'sm')}<span class="hide-sm">Re-sync with my fixes</span></button>` : ''}<a class="btn sm primary" href="#arrange/${enc(V.id)}">Arrange the reel ${ic('chev', 'sm')}</a>`;
}
/** "dots and wides" (or "dot or wide" for one), from the auto-drop rule in Settings. */
function autoRule(n) {
  const rules = (shell.status.settings.auto_drop) || {}, names = [];
  if (rules.dot) names.push('dots'); if (rules.ls) names.push('wides'); if (rules.nb) names.push('no-balls');
  if (n === 1) return names.map(x => x.replace(/s$/, '')).join(', ').replace(/, ([^,]*)$/, ' or $1') || 'ball';
  return names.join(', ').replace(/, ([^,]*)$/, ' and $1') || 'balls';
}

function drawFilters() {
  $('#filters').innerHTML = filters().map(([k, l, , i, n]) => `<button class="chip" data-act="filter" data-k="${k}" aria-pressed="${V.filter === k}">${i ? ic(i, 'sm') : ''}${l}<b>${n}</b></button>`).join('');
}
function rowHtml(c) {
  const flags = `${V.multi ? `<i title="${ROLES[role(c)][0]}">${ic(ROLES[role(c)][1], 'sm')}</i>` : ''}${c.keep && needsCheck(c) ? '<i class="fdot" title="Needs a check"></i>' : ''}${c.star ? `<i class="fst" title="Starred">${ic('star', 'sm')}</i>` : ''}${exportOn(c) ? `<i class="fclip" title="Exports as a clip">${ic('film', 'sm')}</i>` : ''}`;
  return `<div class="crow ${c.index === V.sel ? 'sel' : ''} ${c.keep ? '' : 'off'}" data-act="sel" data-i="${c.index}" role="button" tabindex="0" aria-label="${name(c)}, ${esc(c.label)}${c.keep ? '' : ', not kept'}">
    <img class="thumb" src="${thumb(c)}" alt="" loading="lazy" width="24" height="43">
    <div class="mid"><span class="l1"><span class="nm mono">${ballNo(c)}</span><span class="fl">${flags}</span></span><span class="rs">${isW(c) ? pill('wicket', esc(c.label.split('·').pop().trim())) : resPill(c)}</span></div>
    <label class="switch sm" data-stop><span class="sr">Keep ${name(c)}</span><input type="checkbox" data-act="keep" data-i="${c.index}" ${c.keep ? 'checked' : ''}></label>
  </div>`;
}
function drawList() {
  $('#rlist').innerHTML = listed().map(rowHtml).join('') || '<p class="muted small" style="padding:12px;grid-column:1/-1">No clips match this filter.</p>';
}
function drawRow(i) {
  const c = V.clips.find(x => x.index === i), el = $(`#rlist [data-i="${i}"]`);
  if (!el || !c) return;
  const t = document.createElement('div'); t.innerHTML = rowHtml(c); el.replaceWith(t.firstElementChild);
}

function drawInspector() {
  const c = cur(), box = $('#insp');
  if (!c) { box.innerHTML = '<p class="muted small">No clips for this reel yet.</p>'; return; }
  const near = nearestHit(c), len = c.before + c.after, chk = needsCheck(c), sheetBall = !isW(c) && c.source !== 'manual';
  const eyebrow = c.source === 'manual' ? `Added in Sync${V.multi ? ` · ${c.phase === 'fielding' ? 'fielding' : 'batting'} phase` : ''}`
    : [V.multi ? (isW(c) ? 'Their innings' : 'Our innings') : '', c.bowler ? esc(c.bowler) + (role(c) === 'bowling' ? ' (you)' : '') : '', isW(c) && c.batter ? esc(c.batter) : ''].filter(Boolean).join(' · ') || 'Our innings';
  const note = c.role_set ? 'Kind changed by you. Re-sync keeps your choice.' : !c.keep && c.auto ? `${AUTO[c.auto] || c.auto}: not kept by default.`
    : isW(c) ? (role(c) === 'bowling' ? 'You bowled this over.' : 'Someone else bowled this over. The sheet has no fielder names.') : c.source === 'manual' ? 'Added by you in Sync. Re-sync never moves it.' : '';
  const kindOpts = [...V.kinds, 'other'];
  box.innerHTML = `<div class="ih">
      <div style="min-width:0"><div class="eyebrow"><span class="dot"></span>${eyebrow}</div><h2>${name(c)}</h2></div>
      <div class="chips">${resPill(c)}${confPill(c)}</div>
    </div>
    <div class="playbar">
      <div class="transport"><button class="btn icon" data-act="step" data-d="-1" aria-label="Previous clip" title="Previous clip (↑)">${ic('prev')}</button><button class="btn icon primary" style="--c:var(--green)" data-act="play" id="rplay" aria-label="Play" title="Play / pause (Space)">${ic(vid() && !vid().paused ? 'pause' : 'play')}</button><button class="btn icon" data-act="step" data-d="1" aria-label="Next clip" title="Next clip (↓)">${ic('next')}</button>
        <span class="cap muted" style="margin-left:6px">${ic('loop', 'sm')} Looping ${len.toFixed(2)} s${c.t_open != null ? ' · opens on the celebration' : ''}</span>
        <span class="kbdhelp" title="${KEYS}" tabindex="0" aria-label="${KEYS}">${ic('keyboard', 'sm')}Keys</span></div>
      ${stripHtml(c)}
    </div>
    <div class="pair">
      <div class="pc"><div class="label">Clip window${isW(c) ? ' · max 8 s' : ''}<span class="mono tot">${len.toFixed(2)} s</span></div>
        ${['before', 'after'].map(k => `<div class="wrow2"><span class="cap muted">${k === 'before' ? 'Before' : 'After'}</span><span class="stepper"><button data-act="win" data-k="${k}" data-d="-0.25" aria-label="Shorter ${k}">−</button><output class="mono">${c[k].toFixed(2)} s</output><button data-act="win" data-k="${k}" data-d="0.25" aria-label="Longer ${k}">+</button></span></div>`).join('')}
        ${c.edited || c.before !== V.defaults.clip_before || c.after !== V.defaults.clip_after ? '<button class="btn sm ghost" style="margin-top:6px;min-height:26px" data-act="reset" title="Back to the sync time and the default window">Reset</button>' : ''}</div>
      <div class="pc"><div class="label">${isW(c) ? 'Wicket moment' : c.source === 'manual' ? 'Clip point' : 'Contact point'}<span class="mono tot" ${c.edited && c.t_sync != null ? `title="Moved by you; the sync had ${mmss(c.t_sync, 2)}"` : ''}>${mmss(c.t, 2)}${c.edited ? ' *' : ''}</span></div>
        <div class="chips tight"><button class="btn sm" data-act="nudge" data-d="-0.25">−¼ s</button><button class="btn sm" data-act="nudge" data-d="${-FRAME}">−1 f</button><button class="btn sm" data-act="nudge" data-d="${FRAME}">+1 f</button><button class="btn sm" data-act="nudge" data-d="0.25">+¼ s</button></div>
        <div class="chips tight" style="margin-top:6px">${sheetBall ? `<button class="btn sm" data-act="snap" ${near ? '' : 'disabled'} title="Nearest bat-hit sound (N)">${ic('audio', 'sm')}${near ? `Snap to hit ${near.t > c.t ? '+' : '−'}${Math.abs(near.t - c.t).toFixed(2)} s` : 'No hit within 2 s'}</button>` : ''}<button class="btn sm" data-act="here" title="Set it to the playhead (C)">${ic('pin', 'sm')}At playhead</button>${isW(c) && chk ? `<a class="btn sm" href="#sync/${enc(V.id)}" title="Check this wicket in Sync">${ic('check', 'sm')}In Sync</a>` : ''}</div></div>
    </div>
    <div class="pair ${V.multi ? '' : 'one'}">
      ${V.multi ? `<div class="pc"><div class="label">Kind</div><div class="seg kinds sm" role="group" aria-label="Kind of clip">${kindOpts.map(k => `<button data-act="role" data-k="${k}" aria-pressed="${role(c) === k}">${ic(ROLES[k][1], 'sm')}${ROLES[k][0]}</button>`).join('')}</div></div>` : ''}
      <div class="pc"><div class="label">Keep</div><div class="tgls">
        <button class="tgl" data-act="tkeep" aria-pressed="${!!c.keep}" title="Keep it for the reel (X)">${ic('check', 'sm')}Kept</button>
        <button class="tgl" data-act="tstar" style="--accent:var(--amber)" aria-pressed="${!!c.star}" title="Always put it in the reel (S)">${ic('star', 'sm')}Star</button>
        <button class="tgl" data-act="texport" style="--accent:var(--blue)" aria-pressed="${exportOn(c)}" title="Also export this clip on its own; it starts ticked in Export (E)">${ic('film', 'sm')}Export as clip</button>
        ${isW(c) && /CAUGHT/.test(c.label) ? `<button class="tgl" data-act="tcatch" style="--accent:var(--purple)" aria-pressed="${!!c.my_catch}" title="The sheet doesn't say who caught">${ic('hand', 'sm')}I took it</button>` : ''}
      </div></div>
    </div>
    ${note ? `<p class="inote">${esc(note)}</p>` : ''}
    ${chk ? `<div class="cbar"><span>${ic('info', 'sm')} ${isW(c) ? 'This wicket moment is only a guess.' : 'The bat hit is faint, so the contact is a guess.'} Scrub to the right moment, then confirm.</span><button class="btn primary sm" style="--c:var(--blue)" data-act="confirm">${ic('check', 'sm')}It's right · next <span class="kbd">Enter</span></button></div>` : ''}`;
  const ro = $('#ropen'); if (ro) ro.hidden = c.t_open == null;
  tc();
}
/** The clip window: the contact (or wicket), where a wicket opens (the celebration) and the playhead. */
function stripHtml(c) {
  const len = c.before + c.after, a = c.t - c.before, p = t => (clamp((t - a) / len, 0, 1) * 100).toFixed(1);
  return `<div class="cstrip" id="cstrip" title="The clip window. Click to move the playhead.">
    <span class="win" style="left:0;right:0"></span>
    <span class="mk ${isW(c) ? 'w' : 'c'}" style="left:${p(c.t)}%"><span>${isW(c) ? 'Wicket' : c.source === 'manual' ? 'Clip point' : 'Contact'}</span></span>
    ${c.t_open != null && c.t_open < c.t + c.after ? `<span class="mk c" style="left:${p(c.t_open)}%"><span>Opens here</span></span>` : ''}
    <span class="mk p" id="cplay" style="left:0%"></span></div>`;
}

function nearestHit(c) {
  let best = null;
  V.cands.forEach(k => { const d = Math.abs(k.t - c.t); if (d > 0.04 && d < 2 && (!best || d < Math.abs(best.t - c.t))) best = k; });
  return best;
}

// ---------- edits ----------
function counts() { drawHead(); drawFilters(); }
function edit(fn, { list = false, i = V.sel } = {}) {
  const c = V.clips.find(x => x.index === i); if (!c) return;
  V.hist.push();
  fn(c);
  V.save.queue();
  if (list) drawList(); else drawRow(i);
  if (i === V.sel) drawInspector();
  counts();
}
function undoRedo(redo) {
  if (!(redo ? V.hist.redo() : V.hist.undo())) return toast(redo ? 'Nothing to redo' : 'Nothing to undo');
  V.save.queue(); counts(); drawList(); drawInspector(); toast(redo ? 'Redone' : 'Undone');
}
function select(i, { scroll = true } = {}) {
  const prev = V.sel; V.sel = i;
  drawRow(prev); drawRow(i); drawInspector();
  if (scroll) { const r = $(`#rlist [data-i="${i}"]`); if (r) r.scrollIntoView({ block: 'nearest', behavior: 'smooth' }); }
  play(true);
}
function stepClip(d) {
  const list = listed();
  if (!list.length) return;
  const k = list.findIndex(c => c.index === V.sel);
  select(list[clamp((k < 0 ? 0 : k) + d, 0, list.length - 1)].index);
}
const toggleKeep = c => { c.keep = !c.keep; };
const toggleStar = c => { c.star = !c.star; if (c.star) c.keep = true; };
/** Export as clip: stores my choice; turning it on also keeps the clip (only kept clips export). */
const toggleExport = c => { const on = !exportOn(c); c.export_clip = on; if (on) c.keep = true; };

// ---------- playback: loop the clip window ----------
function play(restart) {
  const v = vid(), c = cur(); if (!v || !c || v.readyState === 0) return;
  // 2.1: a wicket clip opens on the celebration the first time, then loops the whole window
  if (restart) v.currentTime = c.t_open != null && V.opened !== c.index && c.t_open < c.t + c.after ? c.t_open : Math.max(0, c.t - c.before);
  if (restart) V.opened = c.index;
  v.play().catch(() => {});
}
function loop() {
  const v = vid(), c = cur();
  if (v && c && v.currentTime >= c.t + c.after) v.currentTime = Math.max(0, c.t - c.before);
  tc(); V.raf = requestAnimationFrame(loop);
}
function tc() {
  const v = vid(), c = cur(); if (!v || !c) return;
  $('#rtc').textContent = `${mmss(v.currentTime, 2)} · ${isW(c) ? 'wicket' : 'contact'} ${v.currentTime >= c.t ? '+' : '−'}${Math.abs(v.currentTime - c.t).toFixed(2)} s`;
  const p = $('#cplay'); if (p) p.style.left = (clamp((v.currentTime - (c.t - c.before)) / (c.before + c.after), 0, 1) * 100).toFixed(1) + '%';
}
function setPlayBtn(on) { const b = $('#rplay'); if (b) { b.innerHTML = ic(on ? 'pause' : 'play'); b.setAttribute('aria-label', on ? 'Pause' : 'Play'); } }
function togglePlay() { const v = vid(); if (v.paused) play(false); else v.pause(); }
function frameStep(d) { const v = vid(); v.pause(); v.currentTime = clamp(v.currentTime + d, 0, V.dur || v.duration); tc(); }

function nudge(d) { edit(c => { c.t = +(c.t + d).toFixed(3); c.edited = true; }); const v = vid(); v.pause(); v.currentTime = cur().t; tc(); }

// ---------- input ----------
function bind() {
  const main = V.main;
  main.addEventListener('click', async e => {
    if (e.target.closest('[data-stop]')) { e.stopPropagation(); return; }
    const strip = e.target.closest('#cstrip');
    if (strip) { const c = cur(), r = strip.getBoundingClientRect(), v = vid(); v.pause(); v.currentTime = Math.max(0, c.t - c.before + (e.clientX - r.left) / r.width * (c.before + c.after)); tc(); return; }
    const b = e.target.closest('[data-act]'); if (!b || b.disabled || b.tagName === 'INPUT') return;
    const act = b.dataset.act;
    if (act === 'sel') select(+b.dataset.i, { scroll: false });
    else if (act === 'filter') { V.filter = b.dataset.k; drawFilters(); drawList(); }
    else if (act === 'step') stepClip(+b.dataset.d);
    else if (act === 'play') togglePlay();
    else if (act === 'nudge') nudge(+b.dataset.d);
    else if (act === 'snap') { const n = nearestHit(cur()); if (n) { edit(c => { c.t = n.t; c.edited = true; }); play(true); toast(`Snapped to the hit at ${mmss(n.t, 2)}`); } }
    else if (act === 'here') { const t = vid().currentTime; edit(c => { c.t = +t.toFixed(3); c.edited = true; }); toast(`${isW(cur()) ? 'Wicket' : 'Contact'} set to ${mmss(t, 2)}`); }
    else if (act === 'confirm') confirmAndNext();
    else if (act === 'win') edit(c => { const k = b.dataset.k, o = k === 'before' ? 'after' : 'before'; c[k] = clamp(Math.round((c[k] + +b.dataset.d) * 100) / 100, 0.25, isW(c) ? 8 - c[o] : 8); });
    else if (act === 'role') { const k = b.dataset.k, c = cur(); if (role(c) === k) return; const from = ROLES[role(c)][0]; edit(x => { x.role = k; x.role_set = true; }, { list: true }); toast(`${name(c)} is now a ${ROLES[k][0].toLowerCase()} clip (was ${from.toLowerCase()})`); }
    else if (act === 'reset') edit(c => { c.before = V.defaults.clip_before; c.after = V.defaults.clip_after; if (c.t_sync != null) c.t = c.t_sync; c.edited = false; });
    else if (act === 'tkeep') { edit(toggleKeep, { list: V.filter === 'drop' }); toast(`${name(cur())} ${cur().keep ? 'kept' : 'not kept'}`); }
    else if (act === 'tstar') edit(toggleStar);
    else if (act === 'texport') { edit(toggleExport, { list: V.filter === 'clip' }); toast(exportOn(cur()) ? `${name(cur())} exports as a clip too` : `${name(cur())} won't export as a clip`); }
    else if (act === 'tcatch') { edit(c => { c.my_catch = !c.my_catch; }); toast(cur().my_catch ? 'Marked as your catch' : 'Not your catch now'); }
    else if (act === 'resync') {
      try { await V.save.flush(); await api('POST', `/api/matches/${enc(V.id)}/resync-fixes`); location.hash = '#sync/' + enc(V.id); } catch (err) { toastErr(err); }
    }
  });
  main.addEventListener('change', e => {
    const t = e.target;
    if (t.dataset.act !== 'keep') return;
    const i = +t.dataset.i;
    edit(c => { c.keep = t.checked; }, { i, list: V.filter === 'drop' });
    const c = V.clips.find(x => x.index === i);
    toast(`${name(c)} ${c.keep ? 'kept' : 'not kept'}`);
  });
}
function confirmAndNext() {
  const c = cur();
  if (needsCheck(c)) edit(x => { x.confirmed = true; });
  const next = reelClips().find(x => x.index !== c.index && x.keep && needsCheck(x));
  if (next) select(next.index); else toast('Every clip is checked');
}

function onKey(e) {
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'z') { e.preventDefault(); undoRedo(e.shiftKey); return; }
  if (e.ctrlKey || e.metaKey || !cur()) return;
  const k = e.key;
  if (k === 'ArrowDown' || k === 'ArrowUp') { e.preventDefault(); stepClip(k === 'ArrowDown' ? 1 : -1); }
  else if (k === ' ') { e.preventDefault(); togglePlay(); }
  else if (k === ',' || k === '.') { e.preventDefault(); if (e.altKey) nudge(k === ',' ? -FRAME : FRAME); else frameStep(k === ',' ? -FRAME : FRAME); }
  else if (e.shiftKey && (k === 'ArrowLeft' || k === 'ArrowRight')) { e.preventDefault(); nudge(k === 'ArrowLeft' ? -0.25 : 0.25); }
  else if (k === 'n' || k === 'N') { e.preventDefault(); const b = $('[data-act="snap"]', V.main); if (b) b.click(); }
  else if (k === 'c' || k === 'C') { e.preventDefault(); $('[data-act="here"]', V.main).click(); }
  else if (k === 'x' || k === 'X') { e.preventDefault(); edit(toggleKeep, { list: V.filter === 'drop' }); }
  else if (k === 's' || k === 'S') { e.preventDefault(); edit(toggleStar); }
  else if (k === 'e' || k === 'E') { e.preventDefault(); edit(toggleExport, { list: V.filter === 'clip' }); }
  else if (k === 'Enter') { e.preventDefault(); confirmAndNext(); }
}
