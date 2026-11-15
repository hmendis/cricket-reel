// Step 5 · Export: one top-quality file per item (E1), into the match's exports folder. Either the highlight reel
// only, or the reel plus the clips you pick. 2.2: the clip picker is the "Export as clip" flag from Review (the same
// flag: a tile changed here changes it there). Descriptions come next.
import { api } from './core/api.js';
import { exportOn, isHighlight, reelKinds, sectionOf } from './core/reel.js';
import { createAutosave } from './core/state.js';
import { follow, isActive, remaining } from './core/jobs.js';
import { debounce, esc, mmss } from './core/util.js';
import { $, $$, head, ic, note, pill, toast, toastErr } from './ui.js';
import { kickJobs, saving, shell, stepLabel } from './shell.js';
import { redrawShell } from './main.js';

const enc = encodeURIComponent;
let X = null;

export async function prepare([id]) {
  const d = await api('GET', `/api/matches/${enc(id)}/export`);
  shell.match = d.match; shell.step = 'export';
  return { d };
}

export async function mount(main, { d }) {
  let mode = 'reel';
  try { mode = localStorage.getItem('cr.exportMode') || 'reel'; } catch (e) { /* storage blocked */ }
  X = { main, id: d.match.id, d, mode, plan: null, job: d.job, stop: null, kinds: reelKinds(d.match),
    reels: new Set((d.reels || []).map(r => r.rtype)) };
  X.save = createAutosave({
    key: 'clips', url: () => `/api/matches/${enc(X.id)}/clips`, body: () => ({ clips: X.d.clips }),
    send: b => api('PUT', `/api/matches/${enc(X.id)}/clips`, b), onState: (st, e) => { saving(st); if (e) toastErr(e); },
  });
  main.style.setProperty('--accent', 'var(--blue)');
  X.replan = debounce(replan, 150);
  render();
  bind();
  await replan();
  if (X.job && isActive(X.job)) followJob(X.job);
  return { context: () => `${X.mode === 'reel' ? 'reel only' : `reel + ${picked().length} clips`}${X.job ? ', last export ' + X.job.status : ''}`, unmount: () => { X.save.flush(); if (X.stop) X.stop(); } };
}

/** Kept clips of the kinds this match's reels use. */
const clips = () => X.d.clips.filter(c => c.keep && X.kinds.includes(sectionOf(c)));
const picked = () => clips().filter(exportOn).map(c => c.index);
const what = () => ({ reels: [...X.reels], clips: X.mode === 'clips' ? picked().sort((a, b) => a - b) : [] });
const ROLES = { batting: ['Batting', 'bat'], bowling: ['Bowling', 'ball'], fielding: ['Fielding', 'hand'], other: ['Other', 'other'] };
const role = c => c.role || 'batting';
const BIGW = { 4: 'FOUR', 5: 'FIVE', 6: 'SIX', 7: 'SEVEN' };
const resShort = c => c.source === 'manual' ? (c.label || 'CLIP') : c.wid ? c.label.split('·').pop().trim() : BIGW[c.code] || (c.code === '0' ? 'DOT' : c.label.replace('BIG SHOT · ', '') || c.code);
const ballTag = c => c.source === 'manual' ? `${Math.floor(c.t / 60)}:${String(Math.floor(c.t % 60)).padStart(2, '0')}` : `Over ${c.over}.${c.ball}`;
const clipWhat = c => c.source === 'manual' ? `Your clip · ${c.label || ROLES[role(c)][0]} · ${ROLES[role(c)][0]}` : `${c.wid ? 'Their' : 'Our'} innings · Over ${c.over}, ball ${c.ball} · ${resShort(c).toLowerCase()} · ${ROLES[role(c)][0]}`;

async function replan() {
  try { X.plan = await api('POST', `/api/matches/${enc(X.id)}/export/plan`, what()); } catch (e) { toastErr(e); }
  drawFiles(); drawHead();
}

function render() {
  const r = X.d.reel;
  X.main.innerHTML = `<div id="xhead"></div>
    ${!X.d.has_media ? note('bad', 'alert', '<b>The working copy of the video is missing.</b> Re-run the sync first.', `<a class="btn sm" href="#sync/${enc(X.id)}">Open Sync</a>`) : ''}
    <div class="grid">
      <section class="card a-blue span-7" style="--i:0">
        <div class="card-head"><span class="ic">${ic('film')}</span><h3>What to export</h3></div>
        <div class="seg" role="group" aria-label="What to export" style="margin-bottom:12px"><button data-act="mode" data-k="reel" aria-pressed="${X.mode === 'reel'}">Reels only</button><button data-act="mode" data-k="clips" aria-pressed="${X.mode === 'clips'}">Reels + clips</button></div>
        <div class="label" style="margin-top:0">Reels · one file each</div>
        <div id="reelbox"></div>
        <a class="btn sm ghost" href="#arrange/${enc(X.id)}" style="margin:2px 0 6px">${ic('plus', 'sm')}Make another reel in Arrange</a>
        <div id="clipbox"></div>
      </section>
      <div class="span-5" style="display:flex;flex-direction:column;gap:var(--gap);min-width:0">
        <section class="card a-blue" style="--i:1">
          <div class="card-head"><span class="ic">${ic('download')}</span><h3>Output</h3></div>
          <dl class="kv"><dt>Size</dt><dd>1080×1920 · 25 fps</dd><dt>Video</dt><dd>H.264 High · ${X.d.mbps} Mbps</dd><dt>Colour</dt><dd>BT.709 · TV range</dd><dt>Audio</dt><dd>AAC 48 kHz · −14 LUFS</dd><dt>Encoder</dt><dd>${X.d.encoder === 'h264_qsv' ? 'Intel Quick Sync' : 'Software (x264)'}</dd><dt>Folder</dt><dd>exports\\</dd></dl>
          <div class="chips" style="margin-top:12px" id="fits"></div>
        </section>
        <section class="card a-blue" style="--i:2" id="files"></section>
      </div>
    </div>`;
  drawReels(); drawClips();
}
function drawReels() {
  $('#reelbox').innerHTML = (X.d.reels || []).map(r => `<button class="pick" data-act="xreel" data-k="${r.rtype}" aria-pressed="${X.reels.has(r.rtype)}"><span class="ic" style="color:${X.reels.has(r.rtype) ? 'var(--blue)' : 'var(--faint)'}">${ic(X.reels.has(r.rtype) ? 'check' : 'x', 'sm')}</span><span><b>${esc(r.name)} reel</b><small>${r.total.toFixed(1)} s · ${r.count} clips${r.sections.length > 1 ? ' · ' + r.sections.map(s => ROLES[s][0]).join(' → ') : ''}${r.hook ? ` · starts with ${esc(ballTag(r.hook))} ${esc(resShort(r.hook).toLowerCase())}` : ''}${r.music ? ' · with music' : ''}</small></span></button>`).join('') || '<p class="small muted">No reels yet. Make one in Arrange.</p>';
}

function drawHead() {
  const n = X.plan ? X.plan.files.length : 0, j = X.job, running = isActive(j), done = j && j.status === 'done';
  $('#xhead').innerHTML = head(stepLabel('export'), 'Export', 'One top-quality file per item. Upload the same file to TikTok, Reels and Shorts. Descriptions come next.',
    `${done ? `<button class="btn" data-act="open">${ic('folder', 'sm')}Open folder</button>` : ''}<button class="btn ${done ? '' : 'primary'}" data-act="export" ${running || !n ? 'disabled' : ''}>${ic('download', 'sm')}${done ? 'Export again' : `Export ${n} file${n === 1 ? '' : 's'}`}</button>${done ? `<a class="btn primary" style="--c:var(--purple)" href="#describe/${enc(X.id)}">Write descriptions ${ic('chev')}</a>` : ''}`);
}

function drawClips() {
  const box = $('#clipbox');
  if (X.mode !== 'clips') { box.innerHTML = ''; return; }
  const cs = clips(), kinds = Object.keys(ROLES).filter(k => cs.some(c => role(c) === k));
  box.innerHTML = `<div class="label">Clips · <span id="nsel">${picked().length}</span> picked · one file each</div>
    <div class="chips"><button class="chip" data-act="q" data-k="none">None</button><button class="chip" data-act="q" data-k="hl">${ic('star', 'sm')}Highlights</button><button class="chip" data-act="q" data-k="all">All kept</button></div>
    <p class="cap muted" style="margin:6px 0 2px">Starts with the clips you flagged <b>Export as clip</b> in Review. Tap a tile to change it.</p>
    ${kinds.map(k => { const xs = cs.filter(c => role(c) === k); return `<div class="xgroup"><div class="label">${ic(ROLES[k][1], 'sm')}${ROLES[k][0]} · <span data-n="${k}">${xs.filter(exportOn).length}</span>/${xs.length}</div>
      <div class="thumbgrid xl">${xs.map(c => `<button data-act="clip" data-i="${c.index}" aria-pressed="${exportOn(c)}" aria-label="${esc(clipWhat(c))}" title="${esc(clipWhat(c))}"><img src="/api/matches/${enc(X.id)}/thumb/${Math.floor(c.t)}" alt="" loading="lazy"><span><b>${esc(ballTag(c))}</b><em class="${c.wid ? 'w' : c.kind === 'big' ? 'big' : ''}">${esc(resShort(c))}</em></span></button>`).join('')}</div></div>`; }).join('')}`;
}

function drawFiles() {
  const p = X.plan; if (!p) return;
  const j = X.job, running = isActive(j), res = j && j.result && j.result.files;
  const status = name => res && (res.find(f => f.name === name) || {}).status;
  const mb = p.files.reduce((s, f) => s + f.duration * p.mbps / 8, 0);
  const fitsAll = ['TikTok', 'Reels', 'Shorts'].map(n => p.files.every(f => f.fits.includes(n)) ? pill('keep', 'Fits ' + n) : pill('wicket', 'Too long for ' + n)).join('');
  $('#fits').innerHTML = fitsAll;
  $('#files').innerHTML = `<div class="card-head"><span class="ic">${ic('folder')}</span><h3>${j && j.status === 'done' ? 'Exported' : 'Files'}</h3><span class="meta mono">≈ ${Math.round(mb)} MB</span></div>
    ${running ? `<div class="prog big"><i style="width:${(j.progress || 0) * 100}%"></i></div><p class="cap muted mono" style="margin:6px 0">${esc(j.detail || '')}${remaining(j) ? ' · about ' + remaining(j) : ''}</p>` : ''}
    ${p.files.map(f => { const s = status(f.name); return `<div class="file-row"><span class="ic">${s === 'done' ? ic('check', 'sm') : s === 'failed' ? ic('alert', 'sm') : ic('film', 'sm')}</span>
      <div style="min-width:0"><div class="fn">${esc(f.name)}</div><div class="cap muted">${f.kind === 'reel' ? `${esc((X.d.reels.find(r => r.rtype === f.rtype) || {}).name || 'Highlight')} reel` : esc(clipWhat(X.d.clips.find(c => c.index === f.index) || {}))} · ${f.duration.toFixed(1)} s${f.warning ? ` · <span style="color:var(--amber)">${esc(f.warning)}</span>` : ''}</div></div>
      <span class="mono cap muted">${s && s !== 'waiting' ? esc(s) : Math.round(f.duration * p.mbps / 8) + ' MB'}</span></div>`; }).join('')}
    ${running ? '<button class="btn sm" style="margin-top:10px" data-act="cancel">Cancel</button>' : ''}
    ${j && j.status === 'failed' ? note('bad', 'alert', `<b>The export stopped.</b> ${esc(j.error || '')}`, '<button class="btn sm" data-act="x264">Try again with the software encoder</button>') : ''}`;
}

async function start(encoder) {
  try {
    const j = await api('POST', `/api/matches/${enc(X.id)}/export`, { ...what(), encoder: encoder || null });
    kickJobs(); followJob(j);
  } catch (e) { toastErr(e); }
}
function followJob(j) {
  X.job = j; drawFiles(); drawHead();
  if (X.stop) X.stop();
  X.stop = follow(j.id, x => {
    X.job = x; drawFiles(); drawHead();
    if (isActive(x)) return;
    X.stop = null; kickJobs();
    if (x.status === 'done') {
      const n = ((x.result && x.result.files) || []).filter(f => f.status === 'done').length;
      toast(`${n} file${n === 1 ? '' : 's'} exported to the exports folder`);
      api('GET', `/api/matches/${enc(X.id)}`).then(full => { shell.match = full.match; redrawShell(); }).catch(() => {});
    } else if (x.status === 'cancelled') toast('Export cancelled · unfinished files removed');
  });
}

function bind() {
  X.main.addEventListener('click', async e => {
    const b = e.target.closest('[data-act]'); if (!b || b.disabled) return;
    const act = b.dataset.act;
    if (act === 'mode') { X.mode = b.dataset.k; try { localStorage.setItem('cr.exportMode', X.mode); } catch (er) { /* */ } $$('[data-act="mode"]').forEach(x => x.setAttribute('aria-pressed', x.dataset.k === X.mode)); drawClips(); X.replan(); }
    else if (act === 'clip') {
      const c = X.d.clips.find(x => x.index === +b.dataset.i);
      c.export_clip = !exportOn(c); X.save.queue();
      b.setAttribute('aria-pressed', exportOn(c)); $('#nsel').textContent = picked().length;
      const n = $(`[data-n="${role(c)}"]`); if (n) n.textContent = clips().filter(x => role(x) === role(c) && exportOn(x)).length;
      X.replan();
    }
    else if (act === 'q') { const k = b.dataset.k; clips().forEach(c => { c.export_clip = k === 'all' || (k === 'hl' && isHighlight(c)); }); X.save.queue(); drawClips(); X.replan(); }
    else if (act === 'xreel') { const k = b.dataset.k; if (X.reels.has(k)) X.reels.delete(k); else X.reels.add(k); drawReels(); X.replan(); }
    else if (act === 'export') start();
    else if (act === 'x264') start('libx264');
    else if (act === 'cancel') { try { await api('POST', `/api/jobs/${X.job.id}/cancel`); } catch (err) { toastErr(err); } }
    else if (act === 'open') { try { const r = await api('POST', `/api/matches/${enc(X.id)}/open-folder`); if (!shell.status.desktop) toast('Exports folder: ' + r.path, { ms: 8000 }); } catch (err) { toastErr(err); } }
  });
}
