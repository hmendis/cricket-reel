// Step 2 · Sync: every ball on the sheet lined up with the video. S1 over slots and first/last ball markers, S2 your
// first/last shot tags, S3 "you at the crease" (stance reference), S4 fix one ball: move the playhead onto its hit,
// pin it, and only that over is re-lined up. V1/V2: the portrait video stays in view while the overs scroll.
import { api } from './core/api.js';
import { reelKinds } from './core/reel.js';
import { follow, isActive, remaining } from './core/jobs.js';
import { clamp, esc, mmss } from './core/util.js';
import { $, $$, confirmSheet, head, ic, kindClass, note, pill, toast, toastErr } from './ui.js';
import { kickJobs, saving, shell, stepLabel } from './shell.js';
import { redrawShell } from './main.js';

const enc = encodeURIComponent;
const FRAME = 0.04, ZW = 16;      // one frame at 25 fps; the fix panel shows 16 s around the ball
let Y = null;

export async function prepare([id]) {
  const [full, ov] = await Promise.all([api('GET', `/api/matches/${enc(id)}`), api('GET', `/api/matches/${enc(id)}/sync`)]);
  shell.match = full.match; shell.step = 'sync';
  return { full, ov };
}

export async function mount(main, { full, ov }) {
  Y = { main, id: full.match.id, match: full.match, sc: full.scorecard, ov, sel: null, t: 0, wave: null, marking: false, stop: null, busyOver: null, raf: 0,
    view: 'all', panel: null, qi: null, qt: 0, noise: null, loop: null, addRole: 'fielding', addLabel: '', fr: null, dragEnd: 0,
    zr: null, speed: 1, dockMin: false, keyOpen: false, folds: readFolds(), ro: null };
  main.style.setProperty('--accent', 'var(--teal)');
  main.classList.add('wide');
  if (ov.job && isActive(ov.job)) showJob(ov.job); else renderAll();
  return {
    context: () => { const d = cur(); return `playhead ${mmss(Y.t, 2)}${d ? ` · ball ${d.over}.${d.ball} selected` : ''}`; },
    key: onKey,
    unmount: () => { if (Y.stop) Y.stop(); cancelAnimationFrame(Y.raf); if (Y.ro) Y.ro.disconnect(); Y.main.classList.remove('wide'); document.body.classList.remove('dockpage'); document.body.style.removeProperty('--dock'); const v = vid(); if (v) { v.pause(); v.removeAttribute('src'); v.load(); } },
  };
}

const res = () => Y.ov.sync;
const dels = () => (res() && res().deliveries) || [];
const cur = () => dels().find(d => d.index === Y.sel) || null;
const vid = () => $('#pv');
const dur = () => Y.ov.duration || (res() && res().duration) || 1;
const who = d => d.facer === 'me' ? 'You' : (Y.sc && Y.sc.partner.name.split(' ')[0]) || 'Partner';
const mine = () => dels().filter(d => d.facer === 'me');
// A ball you pinned yourself (vs one placed by a first/last shot tag, which also lands as a pin in the result).
const ownPin = d => d.pinned != null && (Y.ov.pins || {})[String(d.index)] != null;
const tagged = d => d.pinned != null && !ownPin(d);
// 2.1: the fielding phase (their innings): split, over starts, wickets. Null for a batting-only match.
const fld = () => (res() && res().fielding) || null;
const wkts = () => (fld() && fld().wickets) || [];
const needCheck = () => wkts().filter(w => w.conf !== 'confirmed');
const wBy = id => wkts().find(w => w.id === id);
const theirs = () => Y.sc && (Y.sc.innings || []).find(i => i.side === 'fielding');
const ROLES = { batting: ['Batting', 'bat'], bowling: ['Bowling', 'ball'], fielding: ['Fielding', 'hand'], other: ['Other', 'other'] };
const confPill = c => c === 'confirmed' ? pill('keep', 'Confirmed') : c === 'celebration' ? pill('check', 'Celebration heard') : `<span class="pill check dash"><span class="d"></span>Timing only</span>`;
const fieldRange = () => fld() ? fld().range : null;
const batRange = () => { const f = fld(); return !f ? [0, dur()] : f.fielded_first ? [f.bound, dur()] : [0, f.bound]; };
function phaseAt(t) { const f = fld(); if (!f) return 'bat'; const [a, b] = f.range; return t >= a && t < b ? 'field' : 'bat'; }
// A Bowling + Fielding reel treats the whole recording as fielding (feedback 13/11): no split, no batting part.
const fieldOnly = () => { const f = fld(); return !!(f && f.whole); };
// 2.2: a Batting reel shows only your batting (no wickets table, over starts or fielding), from reelKinds.
const batOnly = () => !fld() && reelKinds(Y.match).every(k => k === 'batting');
/** Check balls (2.2): your balls whose bat-hit sync is a guess. Pinned or tagged balls count as checked. */
const ballChecked = d => d.conf !== 'low' || d.pinned != null;
const ballsToCheck = () => mine().filter(d => d.t != null && !ballChecked(d));
function views() {
  const out = { all: ['Whole match', [0, dur()]] }, f = fld();
  if (f && !fieldOnly()) { out.field = ['Fielding', [Math.max(0, f.start - 90), Math.min(dur(), f.range[1] + 60)]]; out.bat = ['Batting', batRange()]; }
  const ds = dels().filter(d => d.t != null);
  if (!f && ds.length) { const st = res().batting_start ?? res().auto_start ?? ds[0].t; out.bat = ['Batting', [Math.max(0, Math.min(st, ds[0].t) - 30), Math.min(dur(), ds[ds.length - 1].t + 30)]]; }
  const my = mine().filter(d => d.t != null);
  if (my.length) out.mine = ['Your overs', [Math.max(0, my[0].t - 45), Math.min(dur(), my[my.length - 1].t + 45)]];
  out.near = ['Around playhead', [Y.t - 20, Y.t + 20]];
  return out;
}
const range = () => Y.fr || Y.zr || (views()[Y.view] || views().all)[1];
/** Show [a, b] on the docked timeline (at least 8 s, inside the recording). */
function setRange(a, b) {
  const span = clamp(b - a, 8, dur());
  a = clamp(a, 0, dur() - span);
  Y.zr = [a, a + span]; Y.view = null;
}
function readFolds() { try { return JSON.parse(localStorage.getItem('cr.sync.folds')) || {}; } catch (e) { return {}; } }
function setFold(k, v) { Y.folds[k] = v; try { localStorage.setItem('cr.sync.folds', JSON.stringify(Y.folds)); } catch (e) { /* storage blocked */ } }
const foldBtn = (k, what) => `<button class="btn icon sm ghost" data-act="fold" data-k="${k}" style="margin-left:${Y.folds[k] ? '8px' : 'auto'}" aria-expanded="${!Y.folds[k]}" aria-label="${Y.folds[k] ? 'Show' : 'Fold away'} ${what}" title="${Y.folds[k] ? 'Show' : 'Fold away'}">${ic(Y.folds[k] ? 'down' : 'up', 'sm')}</button>`;

// ---------- the sync job ----------
async function startSync(body = {}) {
  try {
    const j = await api('POST', `/api/matches/${enc(Y.id)}/sync`, body);
    kickJobs(); showJob(j);
  } catch (e) { toastErr(e); }
}

function showJob(j) {
  const v = vid(); if (v) v.pause();
  const n = Y.sc ? Y.sc.overs.reduce((a, o) => a + o.balls.length, 0) : 0;
  Y.main.innerHTML = `${head(stepLabel('sync'), 'Syncing the video with the score sheet', `Finding bat-on-ball sounds and matching them to all ${n} balls your pair faced. You can leave this screen; the sync keeps going and shows in the top bar.`)}
    <section class="card a-teal" style="--i:0;max-width:760px" id="jobcard"></section>`;
  const draw = j => {
    const box = $('#jobcard'); if (!box) return;
    const si = j.status === 'done' ? j.steps.length : j.step;
    box.innerHTML = `<div class="card-head"><span class="ic">${isActive(j) ? '<span class="spin"></span>' : ic(j.status === 'done' ? 'check' : 'alert')}</span><h3>${isActive(j) ? (j.status === 'waiting' ? 'Waiting for another job to finish' : 'Working…') : j.status === 'done' ? 'Finished' : j.status === 'cancelled' ? 'Cancelled' : 'Sync failed'}</h3><span class="meta mono">${Math.floor((j.progress || 0) * 100)}%</span></div>
      <div class="prog big"><i style="width:${(j.progress || 0) * 100}%"></i></div>
      <p class="cap muted mono" style="margin-top:6px">Elapsed ${mmss(j.elapsed || 0, 0)}${remaining(j) ? ' · about ' + remaining(j) : ''}</p>
      <ol class="jobsteps">${j.steps.map((s, i) => { const c = j.status === 'failed' && i === si ? 'fail' : i < si ? 'ok' : i === si && isActive(j) ? 'on' : ''; return `<li class="${c}"><span class="n">${c === 'ok' ? ic('check', 'sm') : c === 'fail' ? '!' : i + 1}</span><span>${esc(s)}</span><span class="r">${i === si ? esc(j.detail || '') : ''}</span></li>`; }).join('')}</ol>
      ${j.status === 'failed' ? note('bad', 'alert', `<b>The sync stopped.</b> ${esc(j.error || 'Something went wrong.')}`, `<button class="btn sm" data-job="retry">Try again</button><a class="btn sm" href="#import/${enc(Y.id)}">Check the videos</a>`) : ''}
      ${j.status === 'cancelled' ? '<p class="small muted" style="margin-top:10px">Work already done is kept, so starting again is quicker.</p>' : ''}
      <div style="display:flex;gap:8px;margin-top:14px;flex-wrap:wrap">${isActive(j) ? '<button class="btn" data-job="cancel">Cancel</button>' : j.status !== 'done' ? `<a class="btn" href="#sheet/${enc(Y.id)}">Back to the score sheet</a><button class="btn primary" data-job="retry">Start again</button>` : ''}</div>`;
  };
  draw(j);
  Y.main.onclick = async e => {
    const b = e.target.closest('[data-job]'); if (!b) return;
    if (b.dataset.job === 'retry') startSync();
    else if (await confirmSheet('Cancel the sync?', 'The preview video and audio made so far are kept, so starting again is quicker.', 'Cancel sync')) { try { await api('POST', `/api/jobs/${j.id}/cancel`); } catch (err) { toastErr(err); } }
  };
  if (Y.stop) Y.stop();
  if (!isActive(j)) return;
  Y.stop = follow(j.id, async x => {
    draw(x);
    if (isActive(x)) return;
    Y.stop = null; kickJobs();
    if (x.status !== 'done') return;
    try {
      const [full, ov] = await Promise.all([api('GET', `/api/matches/${enc(Y.id)}`), api('GET', `/api/matches/${enc(Y.id)}/sync`)]);
      Y.match = full.match; Y.sc = full.scorecard; Y.ov = ov; shell.match = full.match; Y.wave = null;
      redrawShell();
      const s = res() && res().stats;
      toast(res() && res().ok ? `Sync finished · ${s.mine_matched} of your ${s.mine} balls matched to a hit` : 'Sync finished · some balls need your help');
      renderAll();
    } catch (err) { toastErr(err); }
  });
}

// ---------- page ----------
function renderAll() {
  const r = res(), m = Y.match;
  Y.main.onclick = null;
  if (!r) {
    Y.main.innerHTML = `${head(stepLabel('sync'), 'Line up every ball', 'The app finds each bat-on-ball sound and matches it to the balls on the sheet.')}
      ${m.videos.length ? `<section class="card a-teal" style="max-width:640px"><div class="card-head"><span class="ic">${ic('audio')}</span><h3>Not synced yet</h3></div><p class="small muted">It takes a few minutes the first time (a preview video and the sound are made); after that, changes take seconds.</p><button class="btn primary" style="margin-top:12px" data-act="resync">Start the sync ${ic('chev')}</button></section>`
        : note('warn', 'alert', '<b>No video yet.</b> Add the match video before syncing.', `<a class="btn sm" href="#import/${enc(Y.id)}">Add the video</a>`)}`;
    bind(); return;
  }
  const st = r.stats || {}, ds = dels();
  if (Y.sel == null) { const low = ds.find(d => d.facer === 'me' && d.conf === 'low'); Y.sel = (low || ds.find(d => d.facer === 'me') || ds[0] || {}).index ?? null; }
  const f = fld(), hasBat = ds.length > 0, bo = batOnly();
  if (!Y.panel) Y.panel = f && needCheck().length ? 'check' : hasBat ? 'fix' : 'add';
  if (hasBat && Y.panel === 'fix' && Y.sel != null && !cur()) Y.sel = (ballsToCheck()[0] || mine()[0] || {}).index ?? null;
  if (f && Y.qi == null && needCheck().length) openW(needCheck()[0].id, { quiet: true });
  if (!views()[Y.view]) Y.view = 'all';
  const sub = f
    ? `${fieldOnly() ? 'Your reel is Bowling + Fielding, so the whole recording is fielding' : f.fielded_first ? 'Fielding came first, then batting' : 'Batting came first, then fielding'}. In the field, wickets are placed from the sheet order and the noise after them${hasBat ? '; your balls are matched to bat-hit sounds' : ''}. Check the wickets that aren't confirmed, flag an over start with F, add any clip with A.`
    : `Found ${st.matched ?? ds.filter(d => d.candidate != null).length} of the ${ds.length} balls your pair faced (${st.mine_matched ?? 0} of your ${st.mine ?? 0}). To fix one: click it, move the playhead onto its hit with the controls next to the video, then Pin. Only that over is re-synced.`;
  const nv = m.videos.length;
  const line = `${nv} file${nv === 1 ? '' : 's'} · ${mmss(dur(), 0)} · ${f ? (fieldOnly() ? 'all fielding' : f.fielded_first ? 'fielding first, then batting' : 'batting first, then fielding') + ' · wickets from the sheet order and the noise after them' : `${st.mine_matched ?? 0} of your ${st.mine ?? 0} balls matched to a bat hit`}`;
  Y.main.innerHTML = `<div class="studio sync">
    <div class="smain">
      <div class="synchead" title="${esc(sub)}">
        <span class="eyebrow"><span class="dot"></span>${stepLabel('sync')}</span>
        <span class="sum">${esc(line)}</span>
        <span class="acts">${f ? `<button class="btn sm" data-act="openq" ${needCheck().length ? '' : 'disabled'}>${ic('check', 'sm')}Check wickets <span class="mono" id="nchk2">${needCheck().length}</span></button>` : hasBat ? `<button class="btn sm" data-act="bcheck" ${ballsToCheck().length ? '' : 'disabled'}>${ic('check', 'sm')}Check balls <span class="mono" id="nbchk2">${ballsToCheck().length}</span></button>` : ''}<button class="btn sm ghost" data-act="resync" title="Re-sync everything">${ic('refresh', 'sm')}<span class="hide-sm">Re-sync</span></button><a class="btn sm primary" href="#review/${enc(Y.id)}">Review clips ${ic('chev', 'sm')}</a></span>
      </div>
      <div id="notes"></div>
      ${bo && hasBat ? batCard() : ''}
      ${f ? '<section class="card a-pink wtable" style="--i:0" id="fwk"></section><section class="card a-teal" style="--i:1" id="fhow"></section>' : ''}
      ${hasBat ? '<section class="card a-teal" style="--i:1" id="how"></section>' : ''}
      ${f ? '<div class="grid"><section class="card a-teal span-7" style="--i:2" id="fovers"></section><section class="card a-teal span-5" style="--i:3" id="fmanual"></section></div>'
        : '<section class="card a-teal" style="--i:2" id="fmanual"></section>'}
      ${hasBat ? '<div class="grid"><section class="card a-teal span-7" style="--i:5" id="tags"></section><section class="card a-purple span-5" style="--i:6" id="stance"></section></div>' : ''}
      ${hasBat && !bo ? batCard() : ''}
    </div>
    <aside class="sctrl" aria-label="Sync controls"><div class="card a-teal" style="--i:1">
      <div class="overnow static" id="overnow"></div>
      <div class="transport">
        <button class="btn icon sm" data-act="${f ? 'wstep' : 'step'}" data-d="-1" aria-label="${f ? 'Previous wicket' : 'Previous ball'}" title="${f ? 'Previous wicket' : 'Previous ball (↑)'}">${ic('prev', 'sm')}</button>
        <button class="btn icon primary" data-act="play" id="playbtn" aria-label="Play" title="Play / pause (Space)" style="--c:var(--teal)">${ic('play')}</button>
        <button class="btn icon sm" data-act="${f ? 'wstep' : 'step'}" data-d="1" aria-label="${f ? 'Next wicket' : 'Next ball'}" title="${f ? 'Next wicket' : 'Next ball (↓)'}">${ic('next', 'sm')}</button>
        <div class="seg speed" role="group" aria-label="Playback speed">${[1, 1.5, 2].map(s => `<button data-act="speed" data-v="${s}" aria-pressed="${Y.speed === s}" title="Play at ${s}×">${s}×</button>`).join('')}</div>
        ${f ? `<button class="btn icon sm" data-act="flag" title="Over start: flag the first ball of an over at the playhead (F)" aria-label="Over start at the playhead (F)">${ic('flag', 'sm')}</button>` : ''}
      </div>
      <div class="finebar" role="group" aria-label="Fine-tune the playhead">
        ${[[-5, '−5 s', '{'], [-1, '−1 s', '['], [-FRAME, '−1 f', ','], [FRAME, '+1 f', '.'], [1, '+1 s', ']'], [5, '+5 s', '}']].map(([d, l, k]) => `<button class="chip" data-act="pnudge" data-d="${d}" title="${l} (${k})">${l}</button>`).join('')}
      </div>
      <div class="ptabs" style="margin-top:8px" role="tablist" aria-label="Panel">
        ${f ? `<button class="chip" data-act="ptab" data-k="check" aria-pressed="${Y.panel === 'check'}">Check wickets <b id="nchk">${needCheck().length}</b></button>` : ''}
        ${hasBat ? `<button class="chip" data-act="ptab" data-k="fix" aria-pressed="${Y.panel === 'fix'}">Check balls <b id="nbchk">${ballsToCheck().length}</b></button>` : ''}
        <button class="chip" data-act="ptab" data-k="add" aria-pressed="${Y.panel === 'add'}">${ic('plus', 'sm')}Add clip here <span class="kbd">A</span></button>
      </div>
      <div id="queue" ${Y.panel === 'check' ? '' : 'hidden'}></div><div id="fix" ${Y.panel === 'fix' ? '' : 'hidden'}></div><div id="addp" ${Y.panel === 'add' ? '' : 'hidden'}></div>
    </div></aside>
    <aside class="vcol" aria-label="Video"><div class="vframe" id="sframe">${Y.ov.has_proxy ? `<video id="pv" src="/api/matches/${enc(Y.id)}/proxy" preload="auto" playsinline></video>` : '<div class="empty">No preview video yet. Re-sync to make it.</div>'}<div class="vcap"><span class="tc" id="tc"></span></div></div></aside>
    <section class="tldock ${Y.dockMin ? 'min' : ''}" id="tldock" aria-label="Timeline">
      <div class="dockhead">
        <span class="dt">${ic('audio', 'sm')}Timeline</span>
        <div class="chips" role="group" aria-label="Show" id="tlzoom"></div>
        <span class="zoomctl"><button class="btn icon sm ghost" data-act="zoom" data-d="1.6" aria-label="Zoom out" title="Zoom out (or scroll down on the timeline)">−</button><span class="zl" id="zlabel"></span><button class="btn icon sm ghost" data-act="zoom" data-d="0.625" aria-label="Zoom in" title="Zoom in (or scroll up on the timeline)">+</button></span>
        <span class="hint" id="tlhint">Scroll to zoom · Shift+scroll to move · drag to scrub</span>
        <button class="chip" data-act="key" aria-pressed="${Y.keyOpen}" title="What the marks mean">Key</button>
        <button class="btn icon sm ghost" data-act="dockmin" aria-label="${Y.dockMin ? 'Show' : 'Hide'} the timeline" title="${Y.dockMin ? 'Show' : 'Hide'} the timeline (more room for the video)">${ic(Y.dockMin ? 'up' : 'down', 'sm')}</button>
      </div>
      <div class="dockbody">
        <div class="ovbar" id="tlov" title="The whole recording. Drag the box to move along; click to jump."></div>
        <div class="tl ${f ? 'tl3' : ''} docked" id="tl"></div><div class="tl-axis" id="tlaxis"></div>
        <div class="tl-legend" id="tllegend" ${Y.keyOpen ? '' : 'hidden'}></div>
      </div>
    </section>
  </div>`;
  placeDock();
  refresh();
  const v = vid();
  if (v) {
    v.addEventListener('loadedmetadata', () => { const d = cur(); const t0 = Y.panel === 'check' && Y.qi ? Y.qt : d && d.t; if (t0 != null && !Y.t) seek(t0); }, { once: true });
    v.addEventListener('play', () => { setPlay(true); tick(); });
    v.addEventListener('pause', () => { setPlay(false); cancelAnimationFrame(Y.raf); onTime(); });
    v.addEventListener('seeked', onTime);
  }
  loadWave();
  bind();
}

/** Your batting: every ball of your pair, by over, folded away on request (2.2). First on a Batting reel. */
const batCard = () => `<section class="card a-green batcard" style="--i:4" id="batcard"></section>`;
function drawBatCard() {
  const box = $('#batcard'); if (!box) return;
  const my = mine(), overs = [...new Set(dels().map(d => d.over))];
  box.classList.toggle('folded', !!Y.folds.bat);
  box.innerHTML = `<div class="card-head"><span class="ic">${ic('bat')}</span><h3>Your batting · overs ${overs.join(', ')}</h3><span class="meta mono">${my.length} balls · ${ballsToCheck().length} to check</span>${foldBtn('bat', 'your batting')}</div>
    ${Y.folds.bat ? '' : '<div class="overs-grid" id="overs"></div>'}`;
  if (!Y.folds.bat) drawOvers();
}

// The timeline docks along the bottom of the window on a desktop; on a phone it sits under the controls. The page
// leaves room for it. 2.2: on a wide window it stops at the video column, which is as tall as the window.
function placeDock() {
  const dock = $('#tldock'); if (!dock) return;
  const desk = matchMedia('(min-width: 861px)').matches;
  document.body.classList.toggle('dockpage', desk);
  if (desk) {
    const set = () => document.body.style.setProperty('--dock', dock.offsetHeight + 'px');
    set();
    if (Y.ro) Y.ro.disconnect();
    Y.ro = new ResizeObserver(set); Y.ro.observe(dock);
  }
}

function drawNotes() {
  const r = res(), out = [];
  if (Y.ov.stale) out.push(note('warn', 'alert', '<b>The videos changed since this sync.</b> Re-sync so the times match the current files.', '<button class="btn sm" data-act="resync">Re-sync</button>'));
  if (!r.ok) out.push(note('bad', 'alert', `<b>The audio sync didn't work.</b> ${esc(r.error || '')} Usually the camera mic was covered, or the batting part of the video is missing.`,
    '<button class="btn sm" data-act="mark">Mark when batting started</button><button class="btn sm" data-act="sensitive">Listen harder for hits</button><button class="btn sm" data-act="even">Space the balls evenly</button>'));
  if (r.start_warning) out.push(note('warn', 'alert', '<b>Check the batting start.</b> The first ball was placed very early in the video. If the recording starts before play, mark where your pair\'s first ball was bowled.', '<button class="btn sm" data-act="mark">Mark when batting started</button>'));
  if (r.even) out.push(note('warn', 'info', 'These times are spread evenly, not found from the sound. Every ball needs checking.'));
  $('#notes').innerHTML = out.join('');
  $('#notes').hidden = !out.length;
}

function drawHow() {
  if (!$('#how')) return;
  const r = res(), ds = dels(), start = r.batting_start ?? r.auto_start;
  const overs = new Set(ds.map(d => d.over)).size;
  $('#how').innerHTML = `<div class="card-head"><span class="ic">${ic('info')}</span><h3>How the sync was worked out</h3></div>
    <div class="howsteps">
      <div class="howstep"><div class="k">Video</div><div class="v">${mmss(dur(), 0)}</div><div class="s">Length of the match video</div></div>
      <div class="howstep"><div class="k">Batting starts</div><div class="v">${start != null ? mmss(start, 0) : '–'}</div><div class="s">${fld() && r.batting_start === fld().bound ? 'From the phase split' : r.batting_start != null ? 'Marked by you' : 'Camera goes still, then moves'}</div></div>
      <div class="howstep"><div class="k">Score sheet</div><div class="v">${overs} · ${ds.length}</div><div class="s">Overs · balls for your pair</div></div>
      <div class="howstep"><div class="k">Per ball</div><div class="v">${r.gap_ball != null ? (+r.gap_ball).toFixed(1) + ' s' : '–'}</div><div class="s">Learned from this match${r.gap_over_extra ? ` · +${(+r.gap_over_extra).toFixed(0)} s at an over change` : ''}</div></div>
    </div>
    <p class="small muted" style="margin-top:12px">Each over gets an estimated time slot from those numbers (the teal bands on the timeline). Bat-hit sounds in each slot are then matched to the balls in sheet order${Y.ov.stance && Y.ov.stance.moments.length ? ', helped by the moments you were at the crease' : ''}.${r.first_ball != null ? ` First ball <b class="mono" style="color:var(--teal)">${mmss(r.first_ball)}</b>, last ball <b class="mono" style="color:var(--teal)">${mmss(r.last_ball)}</b>.` : ''}</p>`;
}

// ---------- timeline ----------
async function loadWave() {
  if (Y.wave) return;
  try {
    const r = await fetch(`/api/matches/${enc(Y.id)}/waveform`);
    if (!r.ok) return;
    Y.wave = { peaks: new Uint8Array(await r.arrayBuffer()), step: +(r.headers.get('X-Step') || 0.05) };
    drawTimeline();
  } catch (e) { /* the timeline works without it */ }
}
const xp = t => { const [a, b] = range(); return (clamp((t - a) / (b - a), 0, 1) * 100).toFixed(3); };
const inR = t => { const [a, b] = range(); return t >= a && t <= b; };

function drawZoom() {
  const z = $('#tlzoom'); if (!z) return;
  z.innerHTML = Object.entries(views()).map(([k, [l]]) => `<button class="chip" data-act="tview" data-k="${k}" aria-pressed="${Y.view === k}">${l}</button>`).join('');
  const [a, b] = range(), zl = $('#zlabel');
  if (zl) zl.innerHTML = `${mmss(a, 0)} – ${mmss(b, 0)} <span class="muted">· ${b - a >= 120 ? mmss(b - a, 0) : Math.round(b - a) + ' s'} shown</span>`;
}
function drawOverview() {
  const ov = $('#tlov'); if (!ov) return;
  const [a, b] = range(), D = dur(), p = t => (clamp(t / D, 0, 1) * 100).toFixed(3), f = fld();
  ov.innerHTML = `${f ? `<i class="ovf" style="left:${p(f.range[0])}%;width:${p(f.range[1] - f.range[0])}%"></i>` : ''}
    ${!f || fieldOnly() ? '' : `<i class="ovb" style="left:${p(batRange()[0])}%;width:${p(batRange()[1] - batRange()[0])}%"></i>`}
    ${wkts().map(w => `<i class="ovw ${w.conf}" style="left:${p(w.t)}%"></i>`).join('')}
    ${mine().filter(d => d.t != null).map(d => `<i class="ovm" style="left:${p(d.t)}%"></i>`).join('')}
    <i class="ovp" style="left:${p(Y.t)}%"></i><span class="ovwin" id="ovwin" style="left:${p(a)}%;width:${p(b - a)}%"></span>`;
}
function redrawTimeline() { drawZoom(); drawTimeline(); drawOverview(); }

function drawTimeline() {
  const tl = $('#tl'); if (!tl) return;
  const W = 1000, [A, B] = range(), D = B - A, sx = t => clamp((t - A) / D, 0, 1) * W, r = res(), ds = dels(), f = fld();
  const H = 150, y0 = 40, fo = fieldOnly();
  let wave = '';
  if (Y.wave) {
    const p = Y.wave.peaks, st = Y.wave.step;
    for (let x = 0; x < W; x++) {
      const i0 = Math.floor((A + x / W * D) / st), i1 = Math.max(i0 + 1, Math.floor((A + (x + 1) / W * D) / st));
      let v = 0; for (let i = i0; i < i1 && i < p.length; i++) v = Math.max(v, p[i]);
      const h = Math.max(.5, v / 255 * 34); wave += `M${x + .5} ${H - 50 - h}V${H - 50 + h}`;
    }
  }
  const slots = r.slots || [];
  const bands = slots.map((s, i) => `<rect x="${sx(s.start)}" y="${y0}" width="${Math.max(1, sx(s.end) - sx(s.start))}" height="${H - y0}" fill="var(--teal)" opacity="${i % 2 ? .08 : .14}"/>`).join('');
  const cands = Y.ov.candidates.filter(c => !f || phaseAt(c.t) === 'bat').filter(c => inR(c.t)).map(c => `M${sx(c.t).toFixed(1)} ${H - c.s * 12}V${H}`).join('');
  const lines = ds.filter(d => d.t != null && inR(d.t)).map(d => {
    const col = d.facer !== 'me' ? 'var(--faint)' : d.conf === 'low' ? 'var(--blue)' : d.kind === 'wicket' ? 'var(--wicket)' : d.kind === 'big' ? 'var(--big)' : d.kind === 'extra' ? 'var(--purple)' : 'var(--green)';
    return `<path d="M${sx(d.t).toFixed(1)} ${y0 + 4}V${H}" stroke="${col}" stroke-width="${d.index === Y.sel ? 3.5 : d.facer === 'me' ? 2 : 1.2}" vector-effect="non-scaling-stroke"/>`;
  }).join('');
  const st = Y.ov.stance, start = r.batting_start ?? r.auto_start;
  const tags = Y.ov.anchors || {}, dots = D > 3000;
  // the fielding phase: hatched band, over lines, wicket lines
  let fsvg = '', fhtml = '';
  if (f) {
    const [fa, fb] = f.range, ba = fo ? [0, 0] : batRange();
    fsvg = `<defs><pattern id="hatch" width="8" height="8" patternUnits="userSpaceOnUse" patternTransform="rotate(45)"><rect width="3" height="8" fill="var(--teal)" opacity=".13"/></pattern></defs>
      <rect x="${sx(fa)}" y="0" width="${Math.max(0, sx(fb) - sx(fa))}" height="${H}" fill="url(#hatch)"/>
      <rect x="${sx(fa)}" y="0" width="${Math.max(0, sx(fb) - sx(fa))}" height="${y0}" fill="var(--teal)" opacity=".1"/>
      ${fo ? `<rect x="${sx(f.end + 60)}" y="0" width="${Math.max(0, sx(D + A) - sx(f.end + 60))}" height="${H}" fill="#000" opacity=".35"/>` : `<rect x="${sx(ba[0])}" y="0" width="${Math.max(0, sx(ba[1]) - sx(ba[0]))}" height="${y0}" fill="var(--teal)" opacity=".22"/>`}
      ${f.overs.filter(o => inR(o.s)).map(o => `<path d="M${sx(o.s).toFixed(1)} ${y0}V${H}" stroke="var(--teal)" stroke-width="1" ${o.set ? '' : 'stroke-dasharray="3 3"'} opacity=".55" vector-effect="non-scaling-stroke"/>`).join('')}
      ${f.wickets.filter(w => inR(w.t)).map(w => `<path d="M${sx(w.t).toFixed(1)} 68V${H}" stroke="var(--wicket)" stroke-width="1.6" ${w.conf === 'timing' ? 'stroke-dasharray="4 3"' : ''} vector-effect="non-scaling-stroke"/>`).join('')}`;
    const half = (f.bound - Math.max(A, fa)) / D;
    fhtml = `${half > .25 || !f.fielded_first ? `<span class="pbl" style="left:${xp(Math.max(A, fa))}%">Fielding<small>${esc((theirs() || {}).team || 'their')} batting</small></span>` : ''}
      ${fo ? (inR(f.end + 61) ? `<span class="pbl muted" style="left:${xp(f.end + 60)}%">After their innings<small>not used by this reel</small></span>` : '')
        : inR(f.bound) ? `<span class="pbl" style="left:${xp(f.fielded_first ? f.bound : Math.max(A, 0))}%;margin-left:16px">Batting<small>our innings</small></span>` : ''}
      ${(Y.ov.offsets || []).slice(1).filter(o => inR(o.start)).map((o, k) => `<span class="seam" style="left:${xp(o.start)}%"><span>File ${k + 2}</span></span>`).join('')}
      ${!fo && inR(f.bound) ? `<button class="bound" id="bound" style="left:${xp(f.bound)}%" aria-label="Phase split at ${mmss(f.bound, 0)}. Drag, or use the arrow keys, to move it." title="Drag to move where fielding and batting meet"><i></i><b>${mmss(f.bound, 0)}</b></button>` : ''}
      ${f.overs.filter(o => inR(o.s)).map(o => `<button class="oflag ${o.set ? 'set' : ''} ${dots ? 'tiny' : ''}" style="left:${xp(o.s)}%" data-act="ovseek" data-n="${o.n}" title="Over ${o.n}: ${o.set ? 'flagged by you' : 'spread evenly'} · ${mmss(o.s, 0)} · drag to move" aria-label="Over ${o.n} start, ${o.set ? 'flagged' : 'estimated'}">${o.set ? ic('flag') : ''}<span>${o.n}</span></button>`).join('')}
      ${f.wickets.filter(w => inR(w.t)).map(w => `<button class="wk ${w.conf} ${dots ? 'dot' : ''} ${Y.panel === 'check' && Y.qi === w.id ? 'cur' : ''}" style="left:${xp(w.t)}%" data-act="wopen" data-id="${w.id}" title="Wicket ${w.id} · ${esc(w.how)} · ${w.conf === 'confirmed' ? 'confirmed' : w.conf === 'celebration' ? 'celebration heard' : 'timing only'} · drag to move" aria-label="Wicket ${w.id}, ${esc(w.how)}, ${w.conf}"><i></i><span>${w.id} <b class="code">${esc(w.code)}</b></span></button>`).join('')}`;
  }
  const man = (Y.ov.manual || []).filter(m => inR(m.t)).map(m => `<button class="mc" style="left:${xp(m.t)}%" data-act="mseek" data-id="${m.id}" title="Your clip: ${esc(m.label || ROLES[m.role][0])} · ${mmss(m.t, 0)} · drag to move" aria-label="Added clip ${esc(m.label || m.role)}"></button>`).join('');
  const inn = theirs();
  const balls = f && D <= 120 ? f.overs.flatMap(o => { const io = inn && inn.overs.find(x => x.number === o.n), n = io ? io.balls.length : 6; return Array.from({ length: n }, (_, k) => [o.n, k + 1, o.s + k * o.len / n]); })
    .filter(([, , t]) => inR(t)).map(([on, bn, t]) => `<span class="ballmk" style="left:${xp(t)}%"><span>${on}.${bn}</span></span>`).join('') : '';
  // 2.2: every guessed ball, at every zoom (from the same over spread); numbered when 2-7 minutes show
  const bticks = f ? f.overs.flatMap(o => { const io = inn && inn.overs.find(x => x.number === o.n), n = io ? io.balls.length : 6; return Array.from({ length: n }, (_, k) => [o.n, k + 1, o.s + k * o.len / n]); })
    .filter(([, , t]) => inR(t)).map(([on, bn, t]) => { const w = f.wickets.some(x => x.over === on && x.ball === bn), lab = D > 120 && D <= 400;
      return `<span class="ballt ${w ? 'w' : ''}" style="left:${xp(t)}%" title="Ball ${on}.${bn} · guessed at ${mmss(t, 0)}${w ? ' · wicket' : ''}">${lab ? `<i>${on}.${bn}</i>` : ''}</span>`; }).join('') : '';
  const codes = D <= 900 ? mine().filter(d => d.t != null && inR(d.t)).map(d => `<button class="bcode ${d.conf === 'high' ? 'ok' : ''}" style="left:${xp(d.t)}%" data-act="sel" data-i="${d.index}" title="Over ${d.over}.${d.ball} · you · ${esc(d.label)} · bat hit ${d.conf === 'high' ? 'confirmed' : d.conf === 'med' ? 'likely' : 'to check'}">${esc(d.code)}</button>`).join('') : '';
  tl.style.height = H + 'px';
  tl.innerHTML = `<div class="strip" id="strip"></div>
    <svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" aria-hidden="true">
      ${fsvg}
      ${!f && start != null ? `<rect x="0" y="${y0}" width="${sx(start)}" height="${H - y0}" fill="#000" opacity=".35"/>` : ''}${bands}
      <path d="${wave}" stroke="var(--muted)" stroke-width="1" opacity=".55" vector-effect="non-scaling-stroke"/>
      <path d="${cands}" stroke="var(--blue)" stroke-width="1" opacity=".5" vector-effect="non-scaling-stroke"/>
      ${lines}
      ${st ? st.moments.filter(([a, b]) => b >= A && a <= B).map(([a, b]) => `<rect x="${sx(a)}" y="${H - 22}" width="${Math.max(2, sx(b) - sx(a))}" height="8" rx="2" fill="var(--purple)" opacity=".9"/>`).join('') : ''}
      ${!f && start != null ? `<path d="M${sx(start)} ${y0}V${H}" stroke="var(--text)" stroke-dasharray="3 3" stroke-width="1" vector-effect="non-scaling-stroke"/>` : ''}
      ${[r.first_ball, r.last_ball].filter(t => t != null && inR(t)).map(t => `<path d="M${sx(t)} ${y0}V${H}" stroke="var(--teal)" stroke-width="2.5" vector-effect="non-scaling-stroke"/>`).join('')}
    </svg>
    ${slots.filter(s => inR(s.start)).map(s => `<span class="bandlbl" style="left:${xp(s.start)}%;top:${f ? 92 : 44}px">Over ${s.over}</span>`).join('')}
    ${!f && r.first_ball != null ? `<span class="flag" style="left:${xp(r.first_ball)}%">${ic('flag', 'sm')}First ball</span><span class="flag end" style="left:${xp(r.last_ball)}%">Last ball${ic('flag', 'sm')}</span>` : ''}
    ${tags.first != null && inR(tags.first) ? `<span class="tagmark" style="left:${xp(tags.first)}%" title="Your first shot (tag)">1st</span>` : ''}${tags.last != null && inR(tags.last) ? `<span class="tagmark" style="left:${xp(tags.last)}%" title="Your last shot (tag)">Last</span>` : ''}
    ${fhtml}${man}${codes}${balls}${bticks}
    <div class="ph" id="ph" style="left:${xp(Y.t)}%"><i title="Drag the playhead"></i><b class="phl" id="phl">${mmss(Y.t, 1)}</b></div><span class="hover" id="tlhover" hidden></span>`;
  const n = 24, strip = $('#strip');
  strip.innerHTML = Array.from({ length: n }, (_, i) => `<img src="/api/matches/${enc(Y.id)}/thumb/${Math.floor(A + (i + .5) / n * D)}" alt="" loading="lazy" onerror="this.style.visibility='hidden'">`).join('');
  const step = [600, 300, 120, 60, 30, 10, 5, 2, 1].find(s => D / s >= 6) || 1;
  const ticks = []; for (let t = Math.ceil(A / step) * step; t <= B; t += step) ticks.push(`<span style="position:absolute;left:${xp(t)}%;transform:translateX(-50%)">${mmss(t, 0)}</span>`);
  $('#tlaxis').style.position = 'relative'; $('#tlaxis').style.height = '16px';
  $('#tlaxis').innerHTML = ticks.join('');
  $('#tllegend').innerHTML = `${f ? '<span><i class="hatch"></i>Fielding phase</span>' + (fo ? '' : '<span><i style="background:var(--teal)"></i>Phase split (drag)</span>') + '<span><i class="flg"></i>Over start, spread</span><span><i style="background:var(--teal)"></i>Over start, flagged</span><span><i class="wkl"></i>Wicket + sheet code</span><span><i style="background:var(--green);border-radius:50%"></i>Confirmed</span><span><i style="background:var(--check);border-radius:50%"></i>Needs check</span>' : ''}<span><i class="dia"></i>Your added clip</span>${slots.length ? '<span><i style="background:color-mix(in srgb,var(--teal) 35%,transparent)"></i>Estimated batting over</span>' : ''}${dels().length ? `<span><i style="background:var(--green)"></i>Your ball</span>${D <= 900 ? '<span><i class="bcl"></i>Your ball + sheet code (solid = bat hit confirmed)</span>' : ''}<span><i style="background:var(--big)"></i>Big shot</span><span><i style="background:var(--blue)"></i>Needs a check</span><span><i style="background:var(--faint)"></i>${esc(who({ facer: 'partner' }))}'s ball</span><span><i style="background:var(--blue);opacity:.5"></i>Bat-hit sound</span>` : ''}${st && st.moments.length ? '<span><i style="background:var(--purple)"></i>You at the crease</span>' : ''}`;
  bindMarkers();
}

// ---------- the fielding phase: cards ----------
function drawFieldHow() {
  const box = $('#fhow'), f = fld(); if (!box || !f) return;
  const c = f.counts, n = f.wickets.length || 1, my = mine(), hi = my.filter(d => d.conf === 'high').length, med = my.filter(d => d.conf === 'med').length, lo = my.filter(d => d.conf === 'low').length;
  const fo = fieldOnly(), hl = Y.ov.highlights;
  if (Y.folds.split) {
    box.classList.add('folded');
    box.innerHTML = `<div class="card-head" style="flex-wrap:wrap"><span class="ic">${ic('info')}</span><h3>How the match was split</h3><span class="meta">${fo ? `Whole recording is fielding · ${mmss(f.start, 0)}–${mmss(f.end, 0)}` : `Fielding ${mmss(f.range[0], 0)}–${mmss(f.range[1], 0)} · batting ${mmss(batRange()[0], 0)}–${mmss(batRange()[1], 0)}`} · ${c.timing + c.celebration ? `${c.timing + c.celebration} wickets to check` : 'all wickets confirmed'}</span>${foldBtn('split', 'how the match was split')}</div>`;
    return;
  }
  box.classList.remove('folded');
  const why = fo ? 'Your reel is <b>Bowling + Fielding</b>, so the whole recording is treated as fielding: no split to set, no batting on the timeline.' : f.bound_set ? 'You set the split.' : f.split.source === 'gap' ? `Guessed from the sheet (${f.fielded_first ? 'they' : 'we'} batted first) and the ${mmss(f.split.gap, 0)} gap between the video files.` : f.split.source === 'seam' ? `Guessed from the sheet (${f.fielded_first ? 'they' : 'we'} batted first) and where one video file ends.` : `Guessed from the sheet (${f.fielded_first ? 'they' : 'we'} batted first): half way through the video.`;
  box.innerHTML = `<div class="card-head"><span class="ic">${ic('info')}</span><h3>How the match was split</h3>${foldBtn('split', 'how the match was split')}</div>
    <div class="howsteps">
      <div class="howstep"><div class="k">Recording</div><div class="v">${mmss(dur(), 0)}</div><div class="s">${Y.match.videos.length} file${Y.match.videos.length === 1 ? '' : 's'}${Y.match.videos.length > 1 ? ' joined' : ''}</div></div>
      <div class="howstep"><div class="k">Fielding</div><div class="v">${mmss(fo ? f.start : f.range[0], 0)}</div><div class="s">to ${mmss(fo ? f.end : f.range[1], 0)} · their ${f.overs.length} overs</div></div>
      <div class="howstep"><div class="k">Batting</div><div class="v">${fo ? '–' : mmss(batRange()[0], 0)}</div><div class="s">${fo ? 'not in this reel' : `to ${mmss(batRange()[1], 0)} · our innings`}</div></div>
      <div class="howstep"><div class="k">Per over</div><div class="v">${mmss(f.overs[1] ? f.overs[1].len : 125, 0)}</div><div class="s">in the field, ~20 s a ball</div></div>
    </div>
    <p class="small muted" style="margin-top:12px">${why}${fo ? '' : ` Drag the teal handle on the timeline if it's wrong.${f.bound_set ? ' <button class="btn sm ghost" data-act="unbound" style="min-height:24px;padding:0 6px">Back to the guess</button>' : ''}`}</p>
    ${hl === 'bowlfield' ? `<label class="switch" style="margin-top:6px"><span class="t">This video has our batting too<small>${fo ? 'Shows the split and the batting part again' : 'Off: the whole recording is fielding'}</small></span><input type="checkbox" data-act="hasbat" ${fo ? '' : 'checked'}></label>` : ''}
    <div class="phaseconf">
      <div><span class="k">${ic('hand', 'sm')}Fielding · wickets ${c.timing + c.celebration ? pill('check', `${c.timing + c.celebration} to check`) : pill('keep', 'All confirmed')}</span>
        <div class="bar"><i style="width:${c.confirmed / n * 100}%;background:var(--green)"></i><i style="width:${c.celebration / n * 100}%;background:var(--check)"></i><i style="width:${c.timing / n * 100}%;background:repeating-linear-gradient(90deg,var(--check) 0 3px,transparent 3px 5px)"></i></div>
        <span class="cap muted"><span class="mono">${c.confirmed}</span> confirmed · <span class="mono">${c.celebration}</span> celebration heard · <span class="mono">${c.timing}</span> timing only</span></div>
      ${my.length ? `<div><span class="k">${ic('bat', 'sm')}Batting · your balls ${pill('keep', 'Bat-hit sync')}</span>
        <div class="bar"><i style="width:${hi / my.length * 100}%;background:var(--green)"></i><i style="width:${med / my.length * 100}%;background:var(--muted)"></i><i style="width:${lo / my.length * 100}%;background:var(--check)"></i></div>
        <span class="cap muted"><span class="mono">${hi}</span> high · <span class="mono">${med}</span> medium · <span class="mono">${lo}</span> check</span></div>` : ''}
    </div>`;
}

function drawFieldOvers() {
  const box = $('#fovers'), f = fld(); if (!box || !f) return;
  const inn = theirs(), me = Y.sc && Y.sc.batter.name, near = Object.entries((Y.ov.field_user || {}).flags || {}).find(([, t]) => Math.abs(t - Y.t) < 3);
  const fo = phaseAt(Y.t) === 'field' ? f.overs.reduce((p, o) => Math.abs(o.s - Y.t) < Math.abs(p.s - Y.t) ? o : p) : null;
  const sameName = (a, b) => (a || '').toLowerCase().replace(/[^a-z ]/g, '').trim() === (b || '').toLowerCase().replace(/[^a-z ]/g, '').trim();
  box.classList.toggle('folded', !!Y.folds.overs);
  const headO = `<div class="card-head"><span class="ic">${ic('flag')}</span><h3>Over starts · fielding</h3><span class="meta mono">${f.overs.filter(o => o.set).length} flagged</span>${foldBtn('overs', 'over starts')}</div>`;
  if (Y.folds.overs) { box.innerHTML = headO; return; }
  box.innerHTML = `${headO}
    <div class="ovgrid">${f.overs.map(o => { const io = inn && inn.overs.find(x => x.number === o.n), nw = f.wickets.filter(w => w.over === o.n).length; return `<button class="ovchip ${o.set ? 'set' : ''} ${io && sameName(io.bowler, me) ? 'mine' : ''} ${fo && fo.n === o.n ? 'now' : ''}" data-act="ovseek" data-n="${o.n}" aria-label="Over ${o.n}, ${o.set ? 'flagged' : 'spread'}, ${mmss(o.s, 0)}"><span class="n">${o.n}${o.set ? ic('flag') : ''}</span><span class="t">${mmss(o.s, 0)}</span><span class="w">${'<i></i>'.repeat(nw)}</span></button>`; }).join('')}</div>
    <p class="cap muted" style="margin-top:10px">Press <span class="kbd">F</span> on the first ball of an over. Overs you haven't flagged are spread evenly between your flags: about 2:05 an over, with a longer break after overs 4, 8 and 12.</p>
    <div style="display:flex;gap:8px;margin-top:10px;flex-wrap:wrap">${near && +near[0] > 0 ? `<button class="btn sm" data-act="unflag" data-n="${near[0]}">${ic('x', 'sm')}Remove flag on over ${near[0]}</button>` : `<button class="btn sm" data-act="flag" ${fo ? '' : 'disabled'}>${ic('flag', 'sm')}${fo ? `Over ${fo.n} starts here` : 'Move the playhead into fielding'}</button>`}</div>`;
}

function drawManual() {
  const box = $('#fmanual'); if (!box) return;
  const ms = Y.ov.manual || [];
  box.classList.toggle('folded', !!Y.folds.manual);
  const headM = `<div class="card-head"><span class="ic">${ic('plus')}</span><h3>Clips you added</h3><span class="meta mono">${ms.length}</span>${foldBtn('manual', 'clips you added')}</div>`;
  if (Y.folds.manual) { box.innerHTML = headM; return; }
  box.innerHTML = `${headM}
    <div class="mlist">${ms.map(m => `<div class="mrow" data-act="mseek" data-id="${m.id}" role="button" tabindex="0"><span class="dia"></span><span style="min-width:0"><span class="nm">${esc(m.label || ROLES[m.role][0] + ' moment')}</span> <span class="cap muted">${ROLES[m.role][0].toLowerCase()}</span></span><span class="t">${mmss(m.t, 0)}</span><button class="btn icon sm ghost" data-act="mdel" data-id="${m.id}" aria-label="Remove ${esc(m.label || 'clip')}">${ic('trash', 'sm')}</button></div>`).join('') || '<p class="cap muted">None yet.</p>'}</div>
    <p class="cap muted" style="margin-top:10px">Press <span class="kbd">A</span> or use <b>Add clip here</b> next to the video, in any phase. Re-sync never moves these.</p>`;
}

function drawWkTable() {
  const box = $('#fwk'), f = fld(); if (!box || !f) return;
  box.classList.toggle('folded', !!Y.folds.wk);
  const headW = `<div class="card-head"><span class="ic">${ic('ball')}</span><h3>Wickets</h3><span class="meta mono">${f.counts.confirmed}/${f.wickets.length} confirmed</span>${foldBtn('wk', 'the wickets table')}</div>`;
  if (Y.folds.wk) { box.innerHTML = headW; return; }
  box.innerHTML = `${headW}
    <div class="wlist"><div class="wrow head"><span>Ball</span><span>Out</span><span class="how">How</span><span class="bw">Bowler</span><span>Timing</span><span class="t">Time</span></div>
    ${f.wickets.map(w => `<div class="wrow ${w.role === 'bowling' ? 'mine' : ''} ${Y.qi === w.id && Y.panel === 'check' ? 'sel' : ''}" data-act="wopen" data-id="${w.id}" role="button" tabindex="0" title="${w.role === 'bowling' ? 'Bowling clip: you bowled this over' : 'Fielding clip'}"><span class="bn">${w.id}</span><span class="nm">${esc(w.batter)}</span><span class="how">${esc(w.how)}</span><span class="bw">${esc(w.bowler)}${w.role === 'bowling' ? ' <b>(you)</b>' : ''}</span><span>${confPill(w.conf)}</span><span class="t">${mmss(w.t, 0)}</span></div>`).join('')}</div>`;
}

// ---------- Check wickets queue ----------
function openW(id, { quiet = false, play = false } = {}) {
  const w = wBy(id); if (!w) return;
  Y.qi = id; Y.qt = w.t; Y.panel = 'check'; Y.loop = [Math.max(0, w.t - 5), w.t + 5];
  if (quiet) return;
  setRange(w.t - 15, w.t + 15);   // the docked timeline zooms to 30 s around the wicket
  if (vid()) seek(Math.max(0, w.t - 3));
  setPanel('check'); redrawTimeline(); drawWkTable();
  if (play) { const vv = vid(); if (vv) vv.play().catch(() => {}); }
}
function drawQueue() {
  const box = $('#queue'), f = fld(); if (!box || !f) return;
  const list = needCheck(), total = f.wickets.length, done = total - list.length;
  const nc = $('#nchk'); if (nc) nc.textContent = list.length;
  if (!Y.qi || !wBy(Y.qi)) {
    box.innerHTML = list.length ? `<div class="qbox"><p class="small muted">Pick a wicket on the timeline or in the list, or start with the first one.</p><button class="btn sm primary" style="--c:var(--teal)" data-act="openq">Check ${list.length} wicket${list.length === 1 ? '' : 's'}</button></div>`
      : `<div class="qbox"><div class="qdone"><span class="ok">${ic('check')}</span><b>All ${total} wickets checked</b><p class="cap muted">Every wicket clip is confirmed. Clips you add are never moved by re-sync.</p><a class="btn primary sm" style="--c:var(--teal)" href="#review/${enc(Y.id)}">Review clips ${ic('chev', 'sm')}</a></div></div>`;
    return;
  }
  const w = wBy(Y.qi), o = f.overs[w.over - 1], bl = o.len / w.balls_in_over;
  const moved = Y.qt - w.t, ballNow = clamp(Math.floor((Y.qt - o.s) / bl) + 1, 1, w.balls_in_over);
  const n2 = $('#nchk2'); if (n2) n2.textContent = list.length;
  box.innerHTML = `<div class="qbox" title="Keys: W wicket at the playhead · Enter confirm · ← / → one ball · S skip">
    <button class="btn primary sm qhere" style="--c:var(--wicket)" data-act="qhere" title="Set this wicket to the playhead and confirm it (W)">${ic('flag', 'sm')}<span class="ql">Wicket is at the playhead · <span class="mono" id="qhere-t">${mmss(Y.t, 2)}</span></span> <span class="kbd">W</span></button>
    <div class="qkeys">
      <button class="btn sm" data-act="qball" data-d="-1">${ic('prev', 'sm')}<span class="ql">Ball earlier</span> <span class="kbd">←</span></button>
      <button class="btn sm" data-act="qball" data-d="1"><span class="ql">Ball later</span> <span class="kbd">→</span>${ic('next', 'sm')}</button>
      <button class="btn sm ghost" data-act="qskip"><span class="ql">Skip</span> <span class="kbd">S</span></button>
      <button class="btn primary sm" style="--c:var(--green)" data-act="qok" title="Keep the wicket where it was placed and confirm it">${ic('check', 'sm')}<span class="ql">Confirm guess</span> <span class="kbd">Enter</span></button>
    </div>
    <div class="cap muted qinfo"><span>${ic('loop', 'sm')} Loops 10 s · timeline zoomed to it</span><span class="mono">${Math.abs(moved) < .05 ? 'at the guess' : `${moved > 0 ? '+' : '−'}${Math.abs(moved).toFixed(1)} s · ball ${w.over}.${ballNow}`}</span></div>
    <div class="qh"><b>Check wickets</b><div class="prog"><i style="width:${done / total * 100}%"></i></div><span class="mono cap muted">${done}/${total}</span></div>
    <div class="qwho">
      <div class="l1"><span class="mono">${w.id}</span>${esc(w.batter)} · ${esc(w.how)}</div>
      <div class="l2">Bowler ${esc(w.bowler)}${w.role === 'bowling' ? ' (you)' : ''} · ${confPill(w.conf)}</div>
      <div class="l2">${esc(w.why || '')}</div>
    </div>
    ${w.conf === 'confirmed' ? `<button class="btn sm ghost" data-act="qundo">Un-confirm ${w.id}</button>` : ''}
  </div>`;
}
function qball(d) { const w = wBy(Y.qi), f = fld(); if (!w) return; const bl = f.overs[w.over - 1].len / w.balls_in_over; Y.qt = Math.round((Y.qt + d * bl) * 10) / 10; Y.loop = [Y.qt - 5, Y.qt + 5]; setRange(Y.qt - 15, Y.qt + 15); seek(Math.max(0, Y.qt - 3)); drawQueue(); redrawTimeline(); }
function qnext(fromId) {
  const list = needCheck(); if (!list.length) { Y.qi = null; return; }
  const all = wkts(), i = all.findIndex(w => w.id === fromId);
  const nx = list.find(w => all.indexOf(w) > i) || list[0];
  openW(nx.id, { quiet: true }); setRange(nx.t - 15, nx.t + 15); if (vid()) seek(Math.max(0, Y.qt - 3));
}
function wicketHere() { if (!Y.qi) return; const v = vid(); if (v) v.pause(); Y.qt = Math.round(Y.t * 100) / 100; qok(); }
function nudgePlayhead(d) { const v = vid(); if (v) v.pause(); seek(Y.t + d); }
async function qok() {
  const w = wBy(Y.qi); if (!w) return;
  const id = w.id, t = Math.round(Y.qt * 100) / 100, prev = (Y.ov.field_user.confirmed || {})[id] ?? null;
  await setWicket(id, t, `Wicket ${id} confirmed at ${mmss(t, 1)}${Math.abs(t - w.t_guess) > 5 ? ` · unconfirmed wickets in overs ${w.over}${w.over < 16 ? '–' + (w.over + 1) : ''} re-spread` : ''}`, prev);
  qnext(id); refresh();
}
async function setWicket(id, t, msg, prev) {
  saving('saving');
  try { Y.ov = await api('PUT', `/api/matches/${enc(Y.id)}/fielding/wicket`, { id, t }); saving('saved'); } catch (e) { saving('error'); return toastErr(e); }
  refresh();
  if (msg) toast(msg, { undo: () => setWicket(id, prev, null).then(() => toast('Undone')) });
}

// ---------- Add clip here ----------
function drawAdd() {
  const box = $('#addp'); if (!box) return;
  const ph = phaseAt(Y.t);
  box.innerHTML = `<div class="qbox addbox">
    <div class="qh"><b>Add clip at <span class="mono" id="addt">${mmss(Y.t, 1)}</span></b></div>
    <div class="seg kinds" role="group" aria-label="Kind">${Object.entries(ROLES).map(([k, [l, i]]) => `<button data-act="akind" data-k="${k}" aria-pressed="${Y.addRole === k}">${ic(i, 'sm')}${l}</button>`).join('')}</div>
    <label class="field" style="margin:0"><span>Label (optional)</span><input id="alabel" value="${esc(Y.addLabel)}" placeholder="e.g. Good stop" autocomplete="off" maxlength="40"></label>
    <div class="chips">${['Good stop', 'Catch', 'Huddle', 'Celebration'].map(l => `<button class="chip" data-act="alab" data-l="${l}">${l}</button>`).join('')}</div>
    <p class="cap muted">3 s before the playhead to 3 s after; trim it in Review. ${fld() ? (ph === 'field' ? 'In the fielding phase.' : 'In the batting phase.') : ''} Re-sync never moves clips you add.</p>
    <div style="display:flex;gap:6px;justify-content:flex-end"><button class="btn primary sm" style="--c:var(--teal)" data-act="addclip">${ic('plus', 'sm')}Add clip</button></div>
  </div>`;
  const l = $('#alabel'); if (l) l.oninput = () => { Y.addLabel = l.value; };
}
async function addClip() {
  const label = (Y.addLabel || '').trim(), t = Math.round(Y.t * 100) / 100, role = Y.addRole;
  try { Y.ov = await api('POST', `/api/matches/${enc(Y.id)}/manual-clips`, { t, role, label }); } catch (e) { return toastErr(e); }
  const added = (Y.ov.manual || []).reduce((b, m) => !b || m.id.localeCompare(b.id, undefined, { numeric: true }) > 0 ? m : b, null);
  Y.addLabel = ''; refresh();
  toast(`${esc(label || ROLES[role][0] + ' moment')} added at ${mmss(t, 1)}`, { undo: async () => { try { Y.ov = await api('DELETE', `/api/matches/${enc(Y.id)}/manual-clips/${enc(added.id)}`); refresh(); toast('Undone'); } catch (e) { toastErr(e); } } });
}

// ---------- over flags and the split ----------
async function setFlag(n, t, msg, prev) {
  try { Y.ov = await api('PUT', `/api/matches/${enc(Y.id)}/fielding/flag`, { over: n, t }); } catch (e) { return toastErr(e); }
  refresh();
  if (msg) toast(msg, { undo: () => setFlag(n, prev ?? null, null).then(() => toast('Undone')) });
}
function flagHere() {
  const f = fld(); if (!f) return;
  if (phaseAt(Y.t) !== 'field') return toast('Move the playhead into the fielding phase first');
  const o = f.overs.reduce((p, x) => Math.abs(x.s - Y.t) < Math.abs(p.s - Y.t) ? x : p), prev = ((Y.ov.field_user || {}).flags || {})[o.n] ?? null;
  setFlag(o.n, Math.round(Y.t * 100) / 100, `First ball of over ${o.n} flagged at ${mmss(Y.t, 1)} · the overs near it re-spread`, prev);
}
async function setBound(t, msg, prev) {
  try { Y.ov = await api('PUT', `/api/matches/${enc(Y.id)}/fielding/bound`, { t }); } catch (e) { return toastErr(e); }
  refresh();
  if (msg) toast(msg, { undo: () => setBound(prev ?? null, null).then(() => toast('Undone')) });
}

// ---------- drag markers on the timeline ----------
function bindMarkers() {
  const tl = $('#tl'); if (!tl) return;
  $$('.oflag, .wk, .mc, #bound', tl).forEach(h => {
    h.onpointerdown = e => {
      if (e.button !== 0) return;
      e.preventDefault(); e.stopPropagation();
      const rc = tl.getBoundingClientRect(), [a, b] = range(), x0 = e.clientX; let moved = false, t = null;
      Y.fr = [a, b];
      const mv = ev => {
        if (!moved && Math.abs(ev.clientX - x0) < 4) return;
        moved = true; h.classList.add('drag');
        t = Math.round((a + clamp((ev.clientX - rc.left) / rc.width, 0, 1) * (b - a)) * 10) / 10;
        h.style.left = ((t - a) / (b - a) * 100) + '%';
        if (h.id !== 'bound') { const v = vid(); if (v) v.pause(); seek(t); }
      };
      const up = () => {
        window.removeEventListener('pointermove', mv); window.removeEventListener('pointerup', up); Y.fr = null;
        if (!moved) { h.click(); return; }
        Y.dragEnd = Date.now(); commitDrag(h, t);
      };
      window.addEventListener('pointermove', mv); window.addEventListener('pointerup', up);
    };
  });
  const bd = $('#bound');
  if (bd) bd.onkeydown = e => { if (e.key !== 'ArrowLeft' && e.key !== 'ArrowRight') return; e.preventDefault(); e.stopPropagation(); const f = fld(); setBound(Math.round((f.bound + (e.key === 'ArrowLeft' ? -5 : 5)) * 10) / 10); };
}
async function commitDrag(h, t) {
  const f = fld();
  if (h.id === 'bound') return setBound(t, `${f.fielded_first ? 'Fielding ends' : 'Batting ends'} at ${mmss(t, 0)} · unflagged overs re-spread. Re-sync to re-match your balls.`, (Y.ov.field_user || {}).bound ?? null);
  if (h.classList.contains('wk')) { const id = h.dataset.id; return setWicket(id, t, `Wicket ${id} moved to ${mmss(t, 1)} and confirmed`, (Y.ov.field_user.confirmed || {})[id] ?? null); }
  if (h.classList.contains('oflag')) { const n = +h.dataset.n; return setFlag(n, t, `Over ${n} starts at ${mmss(t, 1)} · flagged, the overs either side re-spread`, ((Y.ov.field_user || {}).flags || {})[n] ?? null); }
  if (h.classList.contains('mc')) {
    const id = h.dataset.id, prev = (Y.ov.manual || []).find(m => m.id === id).t;
    const put = async (x, msg) => { try { Y.ov = await api('PUT', `/api/matches/${enc(Y.id)}/manual-clips/${enc(id)}`, { t: x }); refresh(); if (msg) toast(msg, { undo: () => put(prev, 'Undone') }); else toast('Undone'); } catch (e) { toastErr(e); } };
    return put(t, `Clip moved to ${mmss(t, 1)}`);
  }
}

function setPanel(k) {
  Y.panel = k;
  ['queue', 'fix', 'addp'].forEach(id => { const el = $('#' + id); if (el) el.hidden = !(k === (id === 'queue' ? 'check' : id === 'addp' ? 'add' : 'fix')); });
  $$('.ptabs .chip').forEach(b => b.setAttribute('aria-pressed', b.dataset.k === k));
  if (k === 'add' && fld()) { Y.addRole = phaseAt(Y.t) === 'field' ? 'fielding' : 'batting'; drawAdd(); }
  if (k === 'check') drawQueue();
}

// ---------- video ----------
function seek(t) {
  Y.t = clamp(Math.round(t * 1000) / 1000, 0, dur());
  const v = vid(); if (v && v.readyState > 0) v.currentTime = Y.t;
  onTime(true);
}
function onTime(fromSeek) {
  const v = vid();
  if (v && fromSeek !== true && v.readyState > 0) Y.t = v.currentTime;
  if (Y.view === 'near' && !Y.fr) { drawTimeline(); drawZoom(); }
  const ph = $('#ph'); if (ph) ph.style.left = xp(Y.t) + '%';
  const pl = $('#phl'); if (pl) pl.textContent = mmss(Y.t, 1);
  const op = $('#tlov .ovp'); if (op) op.style.left = (clamp(Y.t / dur(), 0, 1) * 100) + '%';
  const qt = $('#qhere-t'); if (qt) qt.textContent = mmss(Y.t, 2);
  drawNow(); drawFixLive();
}
function tick() {
  const v = vid();
  // Check wickets plays about 10 s around the wicket, on a loop
  if (v && Y.panel === 'check' && Y.qi && Y.loop && v.currentTime > Y.loop[1]) v.currentTime = Math.max(0, Y.loop[0]);
  onTime(); Y.raf = requestAnimationFrame(tick);
}
function setPlay(on) { const b = $('#playbtn'); if (b) { b.innerHTML = ic(on ? 'pause' : 'play'); b.setAttribute('aria-label', on ? 'Pause' : 'Play'); } }
function togglePlay() { const v = vid(); if (!v) return; if (v.paused) v.play().catch(() => {}); else v.pause(); }

function nowBall(t) {
  const ds = dels().filter(d => d.t != null);
  if (!ds.length) return null;
  const r = res(), first = ds[0].t, gap = r.gap_ball || 15;
  if (t < first - gap / 2) return null;
  return ds.reduce((b, d) => Math.abs(d.t - t) < Math.abs(b.t - t) ? d : b);
}
function fieldNow(el) {
  const f = fld(), inn = theirs();
  const o = [...f.overs].reverse().find(x => Y.t >= x.s - 2) || f.overs[0], io = inn && inn.overs.find(x => x.number === o.n);
  if (Y.t < f.overs[0].s - 30) { el.innerHTML = `<span class="o"><i></i>Before the innings</span><span class="b">Warm-up</span><span class="s">Over 1 starts at ${mmss(f.overs[0].s, 0)}</span>`; return; }
  const n = io ? io.balls.length : 6, bi = clamp(Math.floor((Y.t - o.s) / (o.len / n)), 0, n - 1), b = io && io.balls[bi];
  if (Y.t > o.s + o.len + 4 && o.n === f.overs.length) { el.innerHTML = `<span class="o"><i></i>Fielding · after over ${o.n}</span><span class="b">Innings over</span>`; return; }
  el.innerHTML = `<span class="o"><i></i>Fielding · over ${o.n} · ball ${bi + 1} of ${n}</span><span class="b">${b ? `${esc(b.batter.split(' ')[0])} · ${esc(b.code)}` : '–'}</span><span class="s">${io ? 'Bowler ' + esc(io.bowler) : ''} · ${o.set ? 'from your flag' : 'spread evenly'}</span>`;
}
function drawNow() {
  const el = $('#overnow'); if (!el) return;
  const d = nowBall(Y.t), r = res();
  $('#tc').textContent = `${mmss(Y.t, 2)} / ${mmss(dur(), 0)}`;
  const at = $('#addt'); if (at) at.textContent = mmss(Y.t, 1);
  if (fld() && phaseAt(Y.t) === 'field') return fieldNow(el);
  if (!d) { el.innerHTML = `<span class="o"><i></i>${fld() ? 'Batting' : 'Before your innings'}</span><span class="b">${fld() ? 'Between balls' : 'Warm-up'}</span>${(r.batting_start ?? r.auto_start) != null ? `<span class="s">Batting starts at ${mmss(r.batting_start ?? r.auto_start)}</span>` : ''}`; return; }
  const inOver = dels().filter(x => x.over === d.over), o = Y.sc && Y.sc.overs.find(x => x.number === d.over);
  el.innerHTML = `<span class="o"><i></i>Over ${d.over} · ball ${d.ball} of ${inOver.length}</span><span class="b">${esc(who(d))} · ${esc(d.label)}</span><span class="s">${o && o.bowler ? 'Bowler ' + esc(o.bowler) : ''}</span>`;
}

// ---------- fix one ball (S4) ----------
function drawFix() {
  const box = $('#fix'); if (!box) return;
  const d = cur();
  if (!d) { box.innerHTML = ''; return; }
  const t0 = d.t ?? Y.t, a = Math.max(0, t0 - ZW / 2), zx = t => ((t - a) / ZW * 100).toFixed(2);
  const hits = Y.ov.candidates.filter(c => c.t >= a && c.t <= a + ZW);
  const st = Y.ov.stance;
  const my = mine(), done = my.filter(ballChecked).length, o = Y.sc && Y.sc.overs.find(x => x.number === d.over);
  const why = ownPin(d) ? 'Pinned by you.' : tagged(d) ? 'Placed by your first/last shot tag.' : d.candidate == null ? 'No bat-hit sound found here: the time is estimated. Scrub to the contact and set it.' : d.conf === 'low' ? 'The bat-hit sound is faint here. Scrub to the contact and set it.' : d.conf === 'med' ? 'Bat hit likely: the sound is clear but close to another noise.' : 'Bat hit found at the contact.';
  box.innerHTML = `<div class="qbox fixbox" title="Keys: Enter confirm · P contact at the playhead · ↑/↓ ball · , and . one frame · Shift+←/→ ¼ s · N snap to hit">
    <button class="btn primary sm qhere" style="--c:var(--green)" data-act="pin" id="pinbtn" title="Set this ball's contact to the playhead and pin it (P)">${ic('flag', 'sm')}<span class="ql">Contact is at the playhead · <span class="mono" id="qhere-t">${mmss(Y.t, 2)}</span></span> <span class="kbd">P</span></button>
    <div class="qkeys">
      <button class="btn sm" data-act="bstep" data-d="-1">${ic('prev', 'sm')}<span class="ql">Ball earlier</span> <span class="kbd">↑</span></button>
      <button class="btn sm" data-act="bstep" data-d="1"><span class="ql">Ball later</span> <span class="kbd">↓</span>${ic('next', 'sm')}</button>
      <button class="btn primary sm" style="--c:var(--green)" data-act="bok" ${d.t == null ? 'disabled' : ''} title="Keep the contact where it is and pin it">${ic('check', 'sm')}<span class="ql">Confirm</span> <span class="kbd">Enter</span></button>
    </div>
    <div class="qh"><b>Check balls</b><div class="prog"><i style="width:${my.length ? done / my.length * 100 : 0}%"></i></div><span class="mono cap muted">${done}/${my.length}</span></div>
    <div class="qwho">
      <div class="l1"><span class="mono">${d.over}.${d.ball}</span>${esc(who(d))} · ${esc(d.label)}</div>
      <div class="l2">${o && o.bowler ? 'Bowler ' + esc(o.bowler) + ' · ' : ''}${d.facer !== 'me' ? pill('normal', 'Partner\'s ball') : ballChecked(d) ? pill('keep', ownPin(d) ? 'Pinned' : tagged(d) ? 'Tagged' : d.conf === 'high' ? 'High' : 'Medium') : pill('check', 'Check')} <span class="mono cap muted">${d.t != null ? mmss(d.t, 2) : '–'}</span></div>
      <div class="l2">${why}</div>
    </div>
    <div class="zoom" id="zoom" data-a="${a}" title="Click a hit sound, or anywhere, to move the playhead">
      ${hits.map(c => `<button class="zh" style="left:${zx(c.t)}%;height:${18 + c.s * 70}%" data-act="seekt" data-t="${c.t}" aria-label="Hit sound at ${mmss(c.t, 2)}"></button>`).join('')}
      ${st ? st.moments.filter(([x, y]) => y >= a && x <= a + ZW).map(([x, y]) => `<i class="zs" style="left:${zx(Math.max(x, a))}%;width:${((Math.min(y, a + ZW) - Math.max(x, a)) / ZW * 100).toFixed(2)}%" title="You at the crease"></i>`).join('') : ''}
      ${d.t != null ? `<i class="zb" style="left:${zx(d.t)}%"></i>` : ''}<i class="zp" id="zp"></i>
      <span class="zl">${mmss(a, 0)}</span><span class="zr">${mmss(a + ZW, 0)}</span>
    </div>
    <div class="nudges">${[[-1, '−1 s'], [-0.25, '−¼ s'], [-FRAME, '−1 f'], [FRAME, '+1 f'], [0.25, '+¼ s'], [1, '+1 s']].map(([v, l]) => `<button class="chip" data-act="nudge" data-d="${v}" aria-label="Move the playhead ${l}">${l}</button>`).join('')}</div>
    <div class="fx-pin"><span class="cap" id="fxoff"></span><span style="display:flex;gap:6px;flex-wrap:wrap">
      ${ownPin(d) ? `<button class="btn sm ghost" data-act="unpin" data-i="${d.index}">Unpin</button>` : ''}
      <button class="btn sm" data-act="snap" title="Jump to the nearest bat-hit sound (N)">${ic('audio', 'sm')}Snap to hit</button></span></div>
  </div>`;
  drawFixLive();
}
function drawFixLive() {
  const d = cur(), z = $('#zoom'); if (!d || !z) return;
  const a = +z.dataset.a, zp = $('#zp'), inWin = Y.t >= a && Y.t <= a + ZW;
  zp.hidden = !inWin; if (inWin) zp.style.left = ((Y.t - a) / ZW * 100).toFixed(2) + '%';
  const off = d.t == null ? null : Y.t - d.t, on = off != null && Math.abs(off) < 0.02;
  const o = $('#fxoff'); o.className = 'cap ' + (on ? 'muted' : '');
  o.textContent = off == null ? 'No time yet: move the playhead onto the hit' : on ? 'Playhead is on this ball' : `Playhead ${Math.abs(off).toFixed(2)} s ${off < 0 ? 'before' : 'after'} it`;
  $('#pinbtn').disabled = on;
}
/** Check balls: the next of your balls (d = ±1), or the next one still to check. */
function stepMine(k) {
  const my = mine().filter(d => d.t != null); if (!my.length) return;
  const i = my.findIndex(d => d.index === Y.sel);
  select(my[clamp((i < 0 ? 0 : i) + k, 0, my.length - 1)].index);
}
function nextToCheck(from) {
  const list = ballsToCheck(); if (!list.length) return toast('Every one of your balls is checked');
  const after = list.find(d => d.index > from);
  select((after || list[0]).index);
}
async function confirmBall(atPlayhead) {
  const d = cur(); if (!d) return;
  const t = atPlayhead ? Math.round(Y.t * 1000) / 1000 : d.t;
  if (t == null) return;
  const v = vid(); if (v) v.pause();
  await pinAt(d, t);
  if (Y.panel === 'fix') nextToCheck(d.index);
}
function snap() {
  const c = Y.ov.candidates.filter(c => Math.abs(c.t - Y.t) > 0.02);
  if (!c.length) return toast('No bat-hit sounds found');
  const n = c.reduce((b, x) => Math.abs(x.t - Y.t) < Math.abs(b.t - Y.t) ? x : b);
  seek(n.t); toast(`Snapped to the hit at ${mmss(n.t, 2)}`);
}
async function pinAt(d, t, quiet) {
  const prev = ownPin(d) ? d.pinned : null;
  Y.busyOver = d.over; drawOvers(); saving('saving');
  try {
    Y.ov = await api('POST', `/api/matches/${enc(Y.id)}/sync/pin`, { index: d.index, t });
    saving('saved');
  } catch (e) { saving('error'); Y.busyOver = null; drawOvers(); return toastErr(e); }
  Y.busyOver = null; refresh();
  if (quiet) return;
  const msg = t == null ? `Ball ${d.over}.${d.ball} unpinned · over ${d.over} re-synced` : `Ball ${d.over}.${d.ball} pinned at ${mmss(t, 2)} · over ${d.over} re-synced, other overs unchanged`;
  toast(msg, { undo: () => pinAt(d, prev ?? null, true).then(() => toast('Undone')) });
}

// ---------- tags (S2) and stance (S3) ----------
function drawTags() {
  if (!$('#tags')) return;
  const tags = Y.ov.anchors || {}, my = mine().filter(d => d.t != null), f = my[0], l = my[my.length - 1];
  const box = (k, label, d, t) => `<div class="tagbox"><span class="k" style="color:var(--teal)">${ic('flag', 'sm')}${label}${t != null ? ' · tagged' : ''}</span>
    <span class="v">${d ? `Over ${d.over} · Ball ${d.ball} · ${mmss(t ?? d.t)}` : '–'}</span>
    <span style="display:flex;gap:6px"><button class="btn sm" data-act="tag" data-w="${k}">Set to playhead</button>${t != null ? `<button class="btn sm ghost" data-act="untag" data-w="${k}">Clear</button>` : ''}</span></div>`;
  $('#tags').innerHTML = `<div class="card-head"><span class="ic">${ic('flag')}</span><h3>Your first and last shot</h3></div>
    <div class="tagrow">${box('first', 'First shot', f, tags.first)}${box('last', 'Last shot', l, tags.last)}</div>
    <p class="cap muted" style="margin-top:10px">${my.length > 2 ? `Your other ${my.length - 2} balls are placed between these two from the sheet order and the bat-hit sounds. ` : ''}Put the playhead on the contact of your first (or last) shot and set it; everything is re-synced in a few seconds.</p>`;
}
function drawStance() {
  if (!$('#stance')) return;
  const st = Y.ov.stance, ref = Y.match.stance_ref || {}, off = !!ref.off;
  let body;
  if (off) body = '<p class="cap muted">Off. The sync uses hit sounds and camera movement only.</p>';
  else if (!st) body = `<p class="small muted">Shows when you were at the crease facing up, from a still of your stance. Tag your first shot, or pause on a frame of you in your stance, to turn it on.</p><button class="btn sm" style="margin-top:8px" data-act="ref">Use frame at playhead</button>`;
  else {
    const before = t => st.moments.some(([, b]) => t - b >= -1 && t - b < 8);
    const my = mine().filter(d => d.t != null), part = dels().filter(d => d.facer !== 'me' && d.t != null);
    body = `<div class="filebox"><img src="/api/matches/${enc(Y.id)}/thumb/${Math.floor(st.ref)}" alt="Reference frame of you in your stance" onerror="this.style.visibility='hidden'"><div style="flex:1;min-width:0">
        <div class="small"><b>Reference ${mmss(st.ref)}</b> <span class="muted">· ${st.auto ? '1.5 s before your first shot' : 'chosen by you'}</span></div>
        <div class="chips" style="margin-top:6px">${st.moments.length ? `${pill('purple', `Before ${my.filter(d => before(d.t)).length} of your ${my.length} balls`)}${pill('normal', `${part.filter(d => before(d.t)).length} of ${esc(who({ facer: 'partner' }))}'s`, false)}` : pill('check', 'Not found yet: re-sync')}</div>
        <span style="display:flex;gap:6px;margin-top:8px;flex-wrap:wrap"><button class="btn sm" data-act="ref">Use frame at playhead</button>${!st.auto ? '<button class="btn sm ghost" data-act="refauto">Back to automatic</button>' : ''}</span></div></div>
      <p class="cap muted" style="margin-top:8px">Purple on the timeline = you at the crease facing up. Your balls should follow one. It matches your stance only, not the ball or bat.</p>`;
  }
  $('#stance').innerHTML = `<div class="card-head"><span class="ic">${ic('target')}</span><h3>You at the crease</h3><label class="switch" style="--accent:var(--purple);padding:0"><span class="sr">Use your stance to help the sync</span><input type="checkbox" data-act="stance" ${off ? '' : 'checked'}></label></div>${body}`;
}
async function setReference(body, msg) {
  try {
    await api('PUT', `/api/matches/${enc(Y.id)}/sync/reference`, body);
    Y.match.stance_ref = { t: body.t ?? null, off: !!body.off };
    toast(msg); startSync({ batting_start: res() ? res().batting_start : null });
  } catch (e) { toastErr(e); }
}

// ---------- overs (two per row) ----------
function drawOvers() {
  const box = $('#overs'); if (!box) return;
  const ds = dels(), slots = res().slots || [], byO = new Map();
  ds.forEach(d => { if (!byO.has(d.over)) byO.set(d.over, []); byO.get(d.over).push(d); });
  box.innerHTML = [...byO.entries()].map(([n, list], i) => {
    const o = Y.sc && Y.sc.overs.find(x => x.number === n), sl = slots.find(s => s.over === n), busy = Y.busyOver === n;
    const ts = list.filter(d => d.t != null);
    return `<section class="card a-teal over-card ${busy ? 'busy' : ''}" style="--i:${i + 4}" id="over${n}">
      <div class="card-head"><span class="ic mono" style="font-weight:700">${n}</span><div style="flex:1;min-width:0"><h3>Over ${n}${o && o.bowler ? ' · ' + esc(o.bowler) : ''}</h3>
        <p class="cap muted">${sl ? `slot <span class="slot">${mmss(sl.start, 0)}–${mmss(sl.end, 0)}</span> · ` : ''}found <span class="mono">${ts.length ? `${mmss(ts[0].t, 0)}–${mmss(ts[ts.length - 1].t, 0)}` : '–'}</span></p></div>
        <span class="meta mono">${o && o.total_sheet != null ? o.total_sheet + ' runs' : ''}</span></div>
      ${busy ? '<div class="busybar" role="status" aria-label="Re-syncing this over"></div>' : ''}
      <div class="rows">${list.map(d => {
        const me = d.facer === 'me';
        return `<div class="row-i ${me ? '' : 'partner'} ${Y.sel === d.index ? 'sel' : ''}" data-act="sel" data-i="${d.index}" role="button" tabindex="0" aria-label="Ball ${d.over}.${d.ball}, ${esc(who(d))}, ${esc(d.label)}, ${d.t != null ? mmss(d.t) : 'no time'}${ownPin(d) ? ', pinned' : tagged(d) ? ', tagged' : ''}${me && d.conf === 'low' ? ', needs a check' : ''}">
          <span class="bn">${d.over}.${d.ball}</span><span class="who">${esc(who(d))}</span>
          <span class="res">${me ? pill(d.conf === 'low' ? 'check' : kindClass(d.kind), esc(d.label)) : `<span class="cap">${esc(d.label)}</span>`}</span>
          <span class="t">${d.t != null ? mmss(d.t) : '–'}</span>
          ${ownPin(d) ? `<button class="btn icon sm pinned" data-act="unpin" data-i="${d.index}" aria-label="Unpin ball ${d.over}.${d.ball}" title="Pinned. Click to unpin.">${ic('pin', 'sm')}</button>` : tagged(d) ? `<span class="btn icon sm pinned" title="Placed by your ${d.index === (mine()[0] || {}).index ? 'first' : 'last'}-shot tag" aria-hidden="true">${ic('flag', 'sm')}</span>` : '<span></span>'}
        </div>`;
      }).join('')}</div>
    </section>`;
  }).join('');
  requestAnimationFrame(() => box.classList.add('drawn')); // later redraws (after a pin) don't replay the fade-in
}

function drawCounts() {
  const n = ballsToCheck().length;
  ['#nbchk', '#nbchk2'].forEach(k => { const el = $(k); if (el) el.textContent = n; });
  const b = $('[data-act="bcheck"]'); if (b) b.disabled = !n;
}
function refresh() { drawNotes(); drawHow(); drawFieldHow(); drawZoom(); drawTimeline(); drawOverview(); drawTags(); drawStance(); drawBatCard(); drawFix(); drawFieldOvers(); drawManual(); drawWkTable(); drawQueue(); drawAdd(); drawNow(); drawCounts(); }

function select(i, { seekTo = true } = {}) {
  Y.sel = i;
  $$('#overs .row-i').forEach(r => r.classList.toggle('sel', +r.dataset.i === i));
  const d = cur();
  drawFix(); drawTimeline();
  if (seekTo && d && d.t != null) seek(d.t);
  const row = $(`#overs .row-i[data-i="${i}"]`); if (row) row.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
}
function stepBall(k) {
  const ds = dels(); if (!ds.length) return;
  const j = clamp(ds.findIndex(d => d.index === Y.sel) + k, 0, ds.length - 1);
  select(ds[j].index);
}

// ---------- input ----------
function bind() {
  const main = Y.main;
  main.onclick = async e => {
    if (Date.now() - Y.dragEnd < 400 && e.target.closest('#tl')) return;   // the click after a drag
    const b = e.target.closest('[data-act]'); if (!b || b.disabled) return;
    const act = b.dataset.act, r = res();
    if (act === 'sel') { if (Y.panel !== 'fix' && $('#fix')) setPanel('fix'); select(+b.dataset.i); }
    else if (act === 'tview') { Y.view = b.dataset.k; Y.zr = null; redrawTimeline(); }
    else if (act === 'zoom') { const [a, z] = range(), span = z - a, c = Y.t >= a && Y.t <= z ? Y.t : (a + z) / 2, ns = clamp(span * +b.dataset.d, 8, dur()); setRange(c - ns / 2, c + ns / 2); redrawTimeline(); }
    else if (act === 'dockmin') { Y.dockMin = !Y.dockMin; $('#tldock').classList.toggle('min', Y.dockMin); b.innerHTML = ic(Y.dockMin ? 'up' : 'down', 'sm'); b.setAttribute('aria-label', `${Y.dockMin ? 'Show' : 'Hide'} the timeline`); }
    else if (act === 'key') { Y.keyOpen = !Y.keyOpen; $('#tllegend').hidden = !Y.keyOpen; b.setAttribute('aria-pressed', Y.keyOpen); }
    else if (act === 'fold') { const k = b.dataset.k; setFold(k, !Y.folds[k]); ({ split: drawFieldHow, overs: drawFieldOvers, wk: drawWkTable, bat: drawBatCard }[k] || drawManual)(); }
    else if (act === 'speed') { Y.speed = +b.dataset.v; const v = vid(); if (v) v.playbackRate = Y.speed; $$('[data-act="speed"]').forEach(x => x.setAttribute('aria-pressed', +x.dataset.v === Y.speed)); }
    else if (act === 'pnudge') nudgePlayhead(+b.dataset.d);
    else if (act === 'qhere') wicketHere();
    else if (act === 'ovseek') { const o = fld().overs[+b.dataset.n - 1]; const v = vid(); if (v) v.pause(); seek(o.s + 0.1); drawFieldOvers(); }
    else if (act === 'wopen') openW(b.dataset.id, { play: true });
    else if (act === 'openq') { const l = needCheck(); if (l.length) openW(l[0].id, { play: true }); }
    else if (act === 'bcheck') { setPanel('fix'); nextToCheck(-1); }
    else if (act === 'bstep') { if (Y.panel !== 'fix') setPanel('fix'); stepMine(+b.dataset.d); }
    else if (act === 'bok') confirmBall(false);
    else if (act === 'mseek') { if (e.target.closest('[data-act="mdel"]')) return; const m = (Y.ov.manual || []).find(x => x.id === b.dataset.id); if (m) { if (!inR(m.t)) { setRange(m.t - 15, m.t + 15); redrawTimeline(); } seek(m.t); } }
    else if (act === 'mdel') {
      e.stopPropagation(); const m = (Y.ov.manual || []).find(x => x.id === b.dataset.id);
      try { Y.ov = await api('DELETE', `/api/matches/${enc(Y.id)}/manual-clips/${enc(m.id)}`); refresh(); } catch (err) { return toastErr(err); }
      toast(`${esc(m.label || 'Clip')} removed`, { undo: async () => { try { Y.ov = await api('POST', `/api/matches/${enc(Y.id)}/manual-clips`, { t: m.t, role: m.role, label: m.label }); refresh(); toast('Undone'); } catch (err) { toastErr(err); } } });
    }
    else if (act === 'wstep') { const d = +b.dataset.d, ws = wkts(); const c = d > 0 ? ws.filter(w => w.t > Y.t + .5) : ws.filter(w => w.t < Y.t - .5).reverse(); if (c.length) openW(c[0].id, { play: true }); }
    else if (act === 'flag') flagHere();
    else if (act === 'unflag') { const n = +b.dataset.n, prev = ((Y.ov.field_user || {}).flags || {})[n]; setFlag(n, null, `Flag on over ${n} removed · overs re-spread`, prev); }
    else if (act === 'unbound') setBound(null, 'The split is back to the guess', (Y.ov.field_user || {}).bound);
    else if (act === 'ptab') setPanel(b.dataset.k);
    else if (act === 'akind') { Y.addRole = b.dataset.k; $$('#addp [data-act="akind"]').forEach(x => x.setAttribute('aria-pressed', x.dataset.k === Y.addRole)); }
    else if (act === 'alab') { Y.addLabel = b.dataset.l; const l = $('#alabel'); if (l) l.value = Y.addLabel; }
    else if (act === 'addclip') addClip();
    else if (act === 'qball') qball(+b.dataset.d);
    else if (act === 'qskip') { qnext(Y.qi); drawQueue(); redrawTimeline(); drawWkTable(); }
    else if (act === 'qok') qok();
    else if (act === 'qundo') setWicket(Y.qi, null, `Wicket ${Y.qi} is unconfirmed again`, (Y.ov.field_user.confirmed || {})[Y.qi]);
    else if (act === 'unpin') { e.stopPropagation(); const d = dels().find(x => x.index === +b.dataset.i); pinAt(d, null); }
    else if (act === 'pin') confirmBall(true);
    else if (act === 'snap') snap();
    else if (act === 'nudge') { const v = vid(); if (v) v.pause(); seek(Y.t + +b.dataset.d); }
    else if (act === 'seekt') seek(+b.dataset.t);
    else if (act === 'step') stepBall(+b.dataset.d);
    else if (act === 'play') togglePlay();
    else if (act === 'resync') startSync({ batting_start: r ? r.batting_start : null });
    else if (act === 'sensitive') startSync({ batting_start: r ? r.batting_start : null, sensitivity: 0.9 });
    else if (act === 'mark') { Y.marking = true; Y.dockMin = false; $('#tldock').classList.remove('min'); $('#tlhint').textContent = "Click where your pair's first ball was bowled"; $('#tlhint').style.color = 'var(--teal)'; }
    else if (act === 'even') {
      const start = r && r.batting_start != null ? r.batting_start : 0;
      if (await confirmSheet('Space the balls evenly?', `All ${dels().length} balls are spread evenly from ${mmss(start)} to the end of the video and marked as needing a check. Mark the batting start first for a better spread.`, 'Space evenly')) {
        try { Y.ov = { ...Y.ov, ...(await api('POST', `/api/matches/${enc(Y.id)}/sync/even`, { start, end: dur() })) }; refresh(); toast('Balls spaced evenly · check each one'); } catch (err) { toastErr(err); }
      }
    }
    else if (act === 'tag' || act === 'untag') {
      const tags = { ...(Y.ov.anchors || {}) };
      if (act === 'tag') tags[b.dataset.w] = Math.round(Y.t * 1000) / 1000; else delete tags[b.dataset.w];
      try {
        await api('PUT', `/api/matches/${enc(Y.id)}/sync/anchors`, tags);
        toast(act === 'tag' ? `${b.dataset.w === 'first' ? 'First' : 'Last'} shot tagged at ${mmss(Y.t, 2)} · re-syncing` : 'Tag cleared · re-syncing');
        startSync({ batting_start: r ? r.batting_start : null });
      } catch (err) { toastErr(err); }
    }
    else if (act === 'ref') setReference({ t: Math.round(Y.t * 100) / 100 }, `Reference set to ${mmss(Y.t)} · re-syncing`);
    else if (act === 'refauto') setReference({ t: null }, 'Reference back to automatic · re-syncing');
  };
  main.onchange = async e => {
    const t = e.target;
    if (t.dataset.act === 'hasbat') {
      try { Y.ov = await api('PUT', `/api/matches/${enc(Y.id)}/fielding/has-batting`, { on: t.checked }); Y.zr = null; Y.view = 'all'; refresh(); toast(t.checked ? 'Batting shown: drag the split to where it starts' : 'The whole recording is fielding'); } catch (err) { toastErr(err); }
      return;
    }
    if (t.dataset.act === 'stance') setReference(t.checked ? { t: null, off: false } : { off: true }, t.checked ? 'Stance matching on · re-syncing' : 'Stance matching off · re-syncing');
  };
  const tl = $('#tl'); if (!tl) return;
  const tAt = e => { const rc = tl.getBoundingClientRect(), [a, b] = range(); return clamp(a + (e.clientX - rc.left) / rc.width * (b - a), 0, dur()); };
  tl.onpointerdown = async e => {
    if (e.target.closest('button')) return;           // markers drag themselves (bindMarkers)
    const t = tAt(e);
    if (Y.marking) {
      Y.marking = false; $('#tlhint').textContent = 'Scroll to zoom · Shift+scroll to move · drag to scrub'; $('#tlhint').style.color = '';
      if (await confirmSheet('Re-sync from here?', `Your pair's batting is taken to start at ${mmss(t)}. Anything earlier is ignored.`, 'Re-sync')) startSync({ batting_start: t });
      return;
    }
    tl.setPointerCapture(e.pointerId); const v = vid(); if (v) v.pause(); seek(t);
    tl.onpointermove = ev => seek(tAt(ev));
    tl.onpointerup = () => { tl.onpointermove = null; };
  };
  tl.onmousemove = e => { const h = $('#tlhover'); if (!h) return; const rc = tl.getBoundingClientRect(); h.hidden = false; h.style.left = (e.clientX - rc.left) + 'px'; h.textContent = mmss(tAt(e), 1); };
  tl.onmouseleave = () => { const h = $('#tlhover'); if (h) h.hidden = true; };
  // scroll to zoom around the mouse; Shift+scroll (or a sideways swipe) moves along
  tl.onwheel = e => {
    e.preventDefault();
    const [a, b] = range(), rc = tl.getBoundingClientRect(), span = b - a;
    if (e.shiftKey || Math.abs(e.deltaX) > Math.abs(e.deltaY)) { const d = (e.shiftKey ? e.deltaY : e.deltaX) / rc.width * span; setRange(a + d, b + d); }
    else { const f = e.deltaY > 0 ? 1.25 : 0.8, at = a + clamp((e.clientX - rc.left) / rc.width, 0, 1) * span, ns = clamp(span * f, 8, dur()); setRange(at - (at - a) / span * ns, at - (at - a) / span * ns + ns); }
    redrawTimeline();
  };
  const ov = $('#tlov');
  if (ov) ov.onpointerdown = e => {
    const rc = ov.getBoundingClientRect(), [a, b] = range(), span = b - a, tAtO = x => (x - rc.left) / rc.width * dur();
    const off = e.target.id === 'ovwin' ? tAtO(e.clientX) - a : span / 2;
    const go = ev => { const s = tAtO(ev.clientX) - off; setRange(s, s + span); redrawTimeline(); };
    go(e);
    const mv = ev => go(ev), up = () => { window.removeEventListener('pointermove', mv); window.removeEventListener('pointerup', up); };
    window.addEventListener('pointermove', mv); window.addEventListener('pointerup', up);
  };
  const z = $('#fix');
  z.onpointerdown = e => {
    const zz = e.target.closest('#zoom'); if (!zz || e.target.closest('[data-act]')) return;
    const rc = zz.getBoundingClientRect(); const v = vid(); if (v) v.pause();
    seek(+zz.dataset.a + (e.clientX - rc.left) / rc.width * ZW);
  };
}

function onKey(e) {
  if (!res()) return;
  const tg = e.target instanceof Element ? e.target : document.body;
  if (tg.closest('input,textarea,select')) return;
  const v = vid(), k = e.key;
  if (fld()) {
    if (k === 'f' || k === 'F') { e.preventDefault(); return flagHere(); }
    if (k === 'w' || k === 'W') { e.preventDefault(); return wicketHere(); }
    if (Y.panel === 'check' && Y.qi && !e.shiftKey && (k === 'ArrowLeft' || k === 'ArrowRight') && !tg.closest('#bound')) { e.preventDefault(); return qball(k === 'ArrowLeft' ? -1 : 1); }
    if (Y.panel === 'check' && Y.qi && k === 'Enter' && !tg.closest('button,[role="button"],a')) { e.preventDefault(); return qok(); }
    if (Y.panel === 'check' && Y.qi && (k === 's' || k === 'S')) { e.preventDefault(); qnext(Y.qi); drawQueue(); drawTimeline(); drawWkTable(); return; }
  }
  if (Y.panel === 'fix' && k === 'Enter' && !tg.closest('button,[role="button"],a')) { e.preventDefault(); return confirmBall(false); }
  if (k === 'a' || k === 'A') { e.preventDefault(); setPanel('add'); const l = $('#alabel'); if (l) l.focus(); return; }
  if (k === '[' || k === ']') { e.preventDefault(); return nudgePlayhead(k === '[' ? -1 : 1); }
  if (k === '{' || k === '}') { e.preventDefault(); return nudgePlayhead(k === '{' ? -5 : 5); }
  if (e.key === 'ArrowDown' || e.key === 'ArrowUp') { e.preventDefault(); stepBall(e.key === 'ArrowDown' ? 1 : -1); }
  else if (e.key === ',' || e.key === '.') { e.preventDefault(); if (v) v.pause(); seek(Y.t + (e.key === ',' ? -FRAME : FRAME)); }
  else if (e.shiftKey && (e.key === 'ArrowLeft' || e.key === 'ArrowRight')) { e.preventDefault(); if (v) v.pause(); seek(Y.t + (e.key === 'ArrowLeft' ? -0.25 : 0.25)); }
  else if (e.key === 'p' || e.key === 'P') { e.preventDefault(); const b = $('#pinbtn'); if (b && !b.disabled) b.click(); }
  else if (e.key === 'n' || e.key === 'N') { e.preventDefault(); snap(); }
  else if (e.key === ' ') { e.preventDefault(); togglePlay(); }
}
