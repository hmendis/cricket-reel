// Step 1 · Import: the match video (desktop: used where it is; browser: uploaded), camera and lens (U2), and the
// score sheet from a Spawtz link (U1: readable paste, a tick when recognised, a preview of every ball) or a photo.
import { api, upload } from './core/api.js';
import { esc, mmss, money } from './core/util.js';
import { $, $$, confirmSheet, gb, head, ic, note, pill, toast, toastErr } from './ui.js';
import { saving, shell, stepLabel } from './shell.js';
import { redrawShell } from './main.js';

const URL_RE = /^https?:\/\/([a-z0-9-]+)\.spawtz\.com\/\S*scoresheet\S*[?&]fixtureid=(\d+)/i;
const desktopPicker = () => window.pywebview && window.pywebview.api && window.pywebview.api.pick_videos;
let N = null;

export async function prepare([id]) {
  let full = null;
  if (id) { full = await api('GET', `/api/matches/${encodeURIComponent(id)}`); shell.match = full.match; }
  shell.step = 'import';
  shell.title = id ? '' : 'New match';
  return { full };
}

export async function mount(main, { full }) {
  const st = shell.status.settings;
  let mode = 'url';
  try { mode = localStorage.getItem('cr.sheetMode') || 'url'; } catch (e) { /* storage blocked */ }
  const m = full && full.match;
  N = {
    main, full, uploads: [], sheetUp: null, busy: false, error: null, mode,
    url: (m && m.sheet && m.sheet.url) || '', batter: (m && m.batter) || st.batter_name || '', name: (m && !m.auto_name && m.name) || '',
    camera: (m && m.camera && m.camera.model) || st.camera, lens: (m && m.camera && m.camera.lens) || st.lens,
    highlights: (m && m.highlights) || 'allround',
  };
  if (m && m.sheet && !m.sheet.url) N.mode = 'file';
  main.style.setProperty('--accent', 'var(--blue)');
  render();
  bind();
  return { context: () => `${N.full ? N.full.match.videos.length + ' video file(s), sheet ' + (N.full.scorecard ? 'imported' : 'not yet') : 'new match'}` };
}

const match = () => N.full && N.full.match;
const synced = m => ['synced', 'review', 'arrange', 'look', 'exported', 'described'].includes(m.step);
const id = () => match() && match().id;

function videoBox(v, i, n) {
  const p = v.probe || {}, warn = [];
  if (!p.ok) warn.push(p.error || 'Not checked yet');
  else { if (!p.vertical) warn.push('Not vertical (expected 1080×1920)'); if (!p.has_audio) warn.push('No audio track: the sync needs the sound'); }
  const fps = p.ok ? (p.vfr ? 'variable frame rate' : `${Math.round(p.fps * 100) / 100} fps`) : '';
  return `<div class="filebox" data-file="${esc(v.file)}">
    <span class="ph">${ic('film')}</span>
    <div style="min-width:0;flex:1"><div class="nm">${i + 1}. ${esc(v.name)}</div>
      <div class="cap muted">${gb(v.size)}${p.ok ? ` · ${mmss(p.duration)} · ${p.width}×${p.height} ${esc((p.codec || '').toUpperCase())} · ${fps}` : ''}${v.linked ? ' · used where it is' : ''}</div>
      <div class="chips" style="margin-top:6px">${p.ok ? (p.vertical ? pill('keep', 'Vertical') : '') + (p.has_audio ? pill('keep', 'Audio found') : '') : ''}${warn.map(w => pill('wicket', esc(w))).join('')}${p.ok && (p.vfr || Math.abs(p.fps - 25) > 0.05) ? pill('check', 'A 25 fps working copy is made') : ''}</div></div>
    <span class="x" style="display:flex;gap:2px">${n > 1 ? `<button class="btn icon sm ghost" data-act="vup" ${i === 0 ? 'disabled' : ''} aria-label="Move ${esc(v.name)} up" title="Earlier in the match">${ic('back', 'sm')}</button><button class="btn icon sm ghost" data-act="vdown" ${i === n - 1 ? 'disabled' : ''} aria-label="Move ${esc(v.name)} down" title="Later in the match">${ic('chev', 'sm')}</button>` : ''}
      <button class="btn icon sm ghost" data-act="vdel" aria-label="Remove ${esc(v.name)}" title="Remove">${ic('x', 'sm')}</button></span>
  </div>`;
}

/** U1: the imported sheet as a grid, your balls highlighted. */
export function sheetPreview(sc) {
  const maxB = Math.max(1, ...sc.overs.map(o => o.balls.length));
  const isW = c => /^(r|b|c|s|w|st|lb|ro|ct)\b/i.test(String(c)) || /w$/i.test(String(c)) && !/^\d/.test(String(c));
  return `<div class="tablewrap"><table class="sheetgrid"><thead><tr><th>Over</th><th>Bowler</th>${Array.from({ length: maxB }, (_, i) => `<th>${i + 1}</th>`).join('')}<th>Total</th></tr></thead><tbody>
    ${sc.overs.map(o => `<tr><th class="mono">${o.number}</th><th>${esc(o.bowler || '')}</th>${Array.from({ length: maxB }, (_, i) => {
      const b = o.balls[i]; if (!b) return '<td class="tot"></td>';
      const me = b.facer === 'me';
      return `<td class="${me ? 'me' : 'pt'} ${me && isW(b.code) ? 'w' : ''}" title="${esc(me ? sc.batter.name : sc.partner.name)}">${esc(b.code)}</td>`;
    }).join('')}<td class="tot">${o.total_sheet ?? ''}</td></tr>`).join('')}
  </tbody></table></div>`;
}

function render() {
  const m = match(), vids = m ? m.videos : [], sheet = m && m.sheet, sc = N.full && N.full.scorecard, v = N.full && N.full.validation;
  const st = shell.status, isUrl = N.mode === 'url', um = URL_RE.exec(N.url.trim());
  const total = vids.reduce((s, x) => s + ((x.probe && x.probe.duration) || 0), 0);
  const canRead = !N.busy && N.batter.trim() && (isUrl ? !!N.url.trim() : !!(sheet && !sheet.url) && st.api_key);
  const canSync = sc && vids.length && v;
  let err = '';
  if (N.error) {
    const e = N.error;
    err = e.code === 'import' ? note('bad', 'alert', `<b>Couldn't import the score sheet.</b> ${esc(e.message)}`, `<button class="btn sm" data-act="read">Try again</button><button class="btn sm" data-act="mode" data-mode="file">Use a photo instead</button>`)
      : e.code === 'no_key' ? note('bad', 'alert', '<b>Claude API key missing.</b> Sheet photos are read by Claude. Paste the key in Settings, or use the Spawtz link, which needs no key.', '<a class="btn sm" href="#settings">Open Settings</a>')
      : ['unreadable', 'refusal'].includes(e.code) ? note('bad', 'alert', `<b>Couldn't read this score sheet.</b> ${esc(e.message)} Retake it flat and close up without flash, or enter the balls by hand.`, `<button class="btn sm" data-act="pickSheet">Upload a clearer photo</button><button class="btn sm" data-act="manual">Enter the balls by hand</button>`)
      : note('bad', 'alert', `<b>Reading the sheet failed.</b> ${esc(e.message)}`, '<button class="btn sm" data-act="read">Try again</button>');
  }
  N.main.innerHTML = `${head(stepLabel('import'), m ? 'Match files' : 'New match', 'Add the match video and the score sheet. Video never leaves this laptop; only a sheet photo is sent to Claude.',
    sc ? `<a class="btn" href="#sheet/${esc(id())}">${ic('table', 'sm')}Check the sheet</a>${synced(m)
      ? `<a class="btn primary" href="#sync/${esc(id())}">Open Sync ${ic('chev')}</a>`
      : `<button class="btn primary" data-act="sync" ${canSync ? '' : 'disabled'} title="${vids.length ? '' : 'Add the match video first'}">Sync the video ${ic('chev')}</button>`}` : '')}
    ${err}
    <div class="grid">
      <section class="card a-blue span-6" style="--i:0">
        <div class="card-head"><span class="ic">${ic('film')}</span><h3>Match video</h3><span class="meta">${vids.length} file${vids.length === 1 ? '' : 's'}${total ? ' · ' + mmss(total, 0) : ''}</span></div>
        <div class="dropzone" id="vdrop">
          ${vids.map((x, i) => videoBox(x, i, vids.length)).join('')}
          ${N.uploads.map((u, k) => `<div class="filebox" data-up="${k}"><span class="ph">${ic(u.err ? 'alert' : 'upload')}</span><div style="min-width:0;flex:1"><div class="nm">${esc(u.name)}</div>${u.err ? `<div class="cap" style="color:var(--pink)">${esc(u.err)}</div>` : `<div class="bar-up"><i style="width:${Math.round(u.prog * 100)}%"></i></div><div class="cap muted mono">${u.prog < 1 ? Math.round(u.prog * 100) + '%' : 'Checking the file…'}</div>`}</div></div>`).join('')}
          <button class="btn ${vids.length ? 'ghost sm' : 'primary'}" data-act="pickVideo">${ic('plus', 'sm')}${vids.length ? 'Add another file' : 'Add the match video'}</button>
          ${vids.length ? '' : `<p class="cap muted" style="text-align:center">${desktopPicker() ? 'The files are used where they are, nothing is copied.' : 'Or drop MP4 / MOV files here. They are copied into the match folder.'}</p>`}
          <input type="file" id="vfile" accept=".mp4,.mov,video/mp4,video/quicktime" multiple hidden>
        </div>
        <div class="camrow">
          <label class="field"><span>Camera</span><select id="cam">${st.cameras.map(c => `<option ${c === N.camera ? 'selected' : ''}>${esc(c)}</option>`).join('')}${st.cameras.includes(N.camera) ? '' : `<option selected>${esc(N.camera)}</option>`}</select></label>
          <div class="field"><span>Lens mode</span><div class="seg" role="group" aria-label="Lens mode">${Object.entries(st.lenses).map(([k, l]) => `<button data-act="lens" data-k="${k}" aria-pressed="${N.lens === k}">${esc(l)}</button>`).join('')}</div></div>
        </div>
        ${note('', 'info', '<b>Add every file from the match here, fielding and batting together,</b> even if the camera split them. It\'s one match: one sync, one set of clips. The reel you pick below decides what to find; you can add the other reels later in Arrange.')}
        <p class="cap muted" style="margin-top:8px">Several files play as one timeline, top to bottom. Size and frame rate come from the file; the lens mode isn't stored in it, so it's asked once and remembered.</p>
      </section>
      <section class="card a-blue span-6" style="--i:1">
        <div class="card-head"><span class="ic">${ic(isUrl ? 'link' : 'image')}</span><h3>Score sheet</h3>
          <div class="seg" role="group" aria-label="Score sheet source"><button data-act="mode" data-mode="url" aria-pressed="${isUrl}">Spawtz link</button><button data-act="mode" data-mode="file" aria-pressed="${!isUrl}">Photo or PDF</button></div></div>
        ${isUrl ? `
          <label class="field"><span>Paste the Scoresheet link from your venue's Spawtz site</span>
            <div class="input-wrap"><input id="sheeturl" type="url" value="${esc(N.url)}" autocomplete="off" spellcheck="false" placeholder="https://yourcentre.spawtz.com/…/Scoresheet?FixtureId=…">${um ? `<span class="tick" aria-label="Link recognised">${ic('check', 'sm')}</span>` : ''}</div></label>
          ${st.settings.standings_url ? `<div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin:-2px 0 10px"><a class="btn sm" href="${esc(st.settings.standings_url)}" target="_blank" rel="noopener">${ic('ext', 'sm')}Standings</a><span class="cap muted">Find the fixture there, open its <b>Scoresheet</b> and copy that link.</span></div>` : ''}
          <div id="urlstate">${urlState(um)}</div>`
        : `<div class="dropzone" id="sdrop" style="align-items:center;text-align:center;padding:18px">
            ${sheet && !sheet.url ? `<img src="/api/matches/${esc(id())}/sheet-image?t=${Date.now()}" alt="Score sheet photo" style="max-height:180px;width:auto;border-radius:10px"><div class="cap muted">${esc(sheet.name)} · ${gb(sheet.size)}</div><button class="btn sm" data-act="pickSheet">Replace</button>`
              : N.sheetUp ? `<div class="nm">${esc(N.sheetUp.name)}</div><div class="bar-up" style="width:200px"><i style="width:${Math.round(N.sheetUp.prog * 100)}%"></i></div>`
              : `${ic('image', 'lg')}<p class="small">Drop a photo, screenshot or PDF of the sheet</p><button class="btn sm" data-act="pickSheet">Choose a file</button>`}
            <input type="file" id="sfile" accept=".jpg,.jpeg,.png,.webp,.pdf,image/*,application/pdf" hidden></div>
          <p class="cap muted" style="margin-top:8px">Claude reads it in 20–60 s. The cost shows on the button before you click.</p>`}
        <label class="field" style="margin-top:6px"><span>Your name on the sheet · used as both batter and bowler</span><input type="text" id="batter" value="${esc(N.batter)}" autocomplete="off" placeholder="For example: Alex Carter"></label>
        <p class="cap muted" style="margin:-4px 0 10px">${(st.settings.other_names || []).length ? `Also tried: ${(st.settings.other_names || []).map(esc).join(', ')}. ` : ''}<a href="#settings">Other names in Settings</a></p>
        <label class="field"><span>Match name</span><input type="text" id="mname" value="${esc(N.name)}" placeholder="Filled in from the sheet (date and teams)"></label>
        <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap">
          <button class="btn ${sc ? '' : 'primary'}" data-act="read" ${canRead ? '' : 'disabled'}>${N.busy ? `<span class="spin"></span>${isUrl ? 'Importing…' : 'Reading…'}` : isUrl ? `${ic('download', 'sm')}${sc ? 'Import again' : 'Import the sheet'}` : `${sc ? 'Read again' : 'Read with Claude'} <span class="cost">≈ ${money(st.estimates.sheet)}</span>`}</button>
          ${!sc ? '<button class="btn ghost sm" data-act="manual">Enter the balls by hand</button>' : ''}
        </div>
      </section>
      ${reelCard()}
      ${sc ? previewCard(sc, v) : ''}
    </div>`;
}

// 2.1: which reel to start with. Only the clips that reel needs are found; the others can be added later.
const RTYPES = [['batting', 'Batting', ['bat'], 'Your balls faced'], ['bowlfield', 'Bowling + Fielding', ['ball', 'hand'], 'Wickets in your overs, then every other wicket your team took'],
  ['allround', 'All-round', ['bat', 'ball', 'hand'], 'Batting, bowling and fielding in one reel']];
function reelCard() {
  return `<section class="card a-blue span-12" style="--i:2">
    <div class="card-head"><span class="ic">${ic('layers')}</span><h3>Highlight reel</h3><span class="meta">Pick one to start</span></div>
    <div class="rpick grid3" role="radiogroup" aria-label="Which reel">${RTYPES.map(([k, l, icons, sub]) => `<button class="pick" role="radio" data-act="hl" data-k="${k}" aria-pressed="${N.highlights === k}" aria-checked="${N.highlights === k}"><span class="ic">${icons.map(i => ic(i, 'sm')).join('')}</span><span><b>${l} reel</b><small>${sub}</small></span></button>`).join('')}</div>
    <p class="cap muted" style="margin-top:6px">Bowling and fielding need the other team's innings, which the Spawtz link gives. You can add the other reels later, in Arrange.</p>
  </section>`;
}

function urlState(um) {
  if (um) return `<p class="ok-row field" style="flex-direction:row">${ic('check', 'sm')}Link recognised · ${esc(um[1][0].toUpperCase() + um[1].slice(1))} · fixture ${um[2]} · imported exactly, no API cost</p>`;
  if (N.url.trim()) return note('warn', 'alert', "This isn't a Spawtz <b>Scoresheet</b> link yet. Open the match on the venue site, click <b>Scoresheet</b> and copy that address.");
  return '';
}

function previewCard(sc, v) {
  const mm = sc.match || {}, mine = v.batter, part = v.partner;
  const n = sc.overs.reduce((a, o) => a + o.balls.length, 0), my = sc.overs.reduce((a, o) => a + o.balls.filter(b => b.facer === 'me').length, 0);
  return `<section class="card ${v.ok ? 'a-green' : 'a-pink'} span-12" style="--i:2">
    <div class="card-head"><span class="ic">${ic(v.ok ? 'check' : 'alert')}</span><h3>Sheet preview</h3><span class="meta">${esc([mm.team_us, mm.team_them].filter(Boolean).join(' v '))}${mm.result ? ' · ' + esc(mm.result) : ''}</span></div>
    <div class="chips" style="margin-bottom:12px">${v.ok ? pill('keep', 'Totals add up') : pill('wicket', esc(v.errors[0] || "Totals don't add up"))}${v.unsure ? pill('check', `${v.unsure} cell${v.unsure === 1 ? '' : 's'} to check`) : ''}
      ${pill('normal', `${esc(mine.name)} <span class="mono">${mine.calc_runs} (${mine.calc_balls})</span>`, false)}${pill('normal', `${esc(part.name)} <span class="mono">${part.calc_runs} (${part.calc_balls})</span>`, false)}${pill('normal', `${sc.overs.length} overs · ${n} balls · ${my} yours`, false)}</div>
    ${sheetPreview(sc)}
    <p class="cap muted" style="margin-top:8px">Your balls are highlighted. If anything is wrong, <a href="#sheet/${esc(id())}">check the sheet</a> and fix the cell.</p>
  </section>`;
}

async function ensureMatch() {
  if (id()) return;
  if (!N.batter.trim()) { $('#batter').focus(); throw new Error('Enter your name as it is written on the score sheet first.'); }
  const m = await api('POST', '/api/matches', { name: N.name, batter: N.batter, remember: true });
  const full = await api('PATCH', `/api/matches/${encodeURIComponent(m.id)}`, { camera: N.camera, lens: N.lens, highlights: N.highlights });
  N.full = full; shell.match = full.match;
  history.replaceState(null, '', '#import/' + encodeURIComponent(m.id));
  redrawShell();
}

async function saveFields() {
  const m = match(), patch = {};
  if (N.batter.trim() && N.batter.trim() !== m.batter) patch.batter = N.batter.trim();
  if (N.name.trim() && N.name.trim() !== m.name) patch.name = N.name.trim();
  if (!Object.keys(patch).length) return;
  N.full = await api('PATCH', `/api/matches/${encodeURIComponent(m.id)}`, patch);
  shell.match = N.full.match;
  history.replaceState(null, '', '#import/' + encodeURIComponent(N.full.match.id));
  redrawShell();
}

async function addVideos(files) {
  try { await ensureMatch(); } catch (e) { return toastErr(e); }
  for (const f of files) {
    const u = { name: f.name, prog: 0, err: null };
    N.uploads.push(u); render();
    let t = 0;
    try {
      // Progress updates the bar in place: re-rendering the page 4 times a second made it flash (2.1 fix).
      const m = await upload(`/api/matches/${encodeURIComponent(id())}/videos/raw`, f, p => { u.prog = p; const now = Date.now(); if (now - t > 250) { t = now; drawUpload(u); } }, true);
      N.full.match = m; shell.match = m; N.uploads.splice(N.uploads.indexOf(u), 1);
    } catch (e) { u.err = e.message; }
    render();
  }
}

function drawUpload(u) {
  const box = $(`[data-up="${N.uploads.indexOf(u)}"]`, N.main); if (!box) return;
  const bar = $('.bar-up i', box), txt = $('.cap.mono', box);
  if (bar) bar.style.width = Math.round(u.prog * 100) + '%';
  if (txt) txt.textContent = u.prog < 1 ? Math.round(u.prog * 100) + '%' : 'Checking the file…';
}

async function setSheetFile(f) {
  try { await ensureMatch(); } catch (e) { return toastErr(e); }
  N.sheetUp = { name: f.name, prog: 0 }; N.error = null; render();
  try { N.full.match = await upload(`/api/matches/${encodeURIComponent(id())}/sheet`, f, p => { N.sheetUp.prog = p; }); toast('Score sheet added'); } catch (e) { toastErr(e); }
  N.sheetUp = null; render();
}

async function readSheet() {
  if (!N.batter.trim()) return toastErr(new Error('Enter your name as it is written on the sheet.'));
  try { await ensureMatch(); await saveFields(); } catch (e) { return toastErr(e); }
  N.busy = true; N.error = null; render();
  try {
    const full = N.mode === 'url'
      ? await api('POST', `/api/matches/${encodeURIComponent(id())}/import-url`, { url: N.url.trim() })
      : await api('POST', `/api/matches/${encodeURIComponent(id())}/read-sheet`);
    N.full = full; shell.match = full.match; N.name = full.match.auto_name ? '' : full.match.name;
    history.replaceState(null, '', '#import/' + encodeURIComponent(full.match.id));
    redrawShell();
    toast(N.mode === 'url' ? 'Score sheet imported' : 'Score sheet read');
  } catch (e) { N.error = { code: e.code || 'api', message: e.message }; }
  N.busy = false; render();
  const pv = $('.sheetgrid', N.main); if (pv) pv.closest('.card').scrollIntoView({ behavior: 'smooth', block: 'nearest' });
}

async function manualEntry() {
  try { await ensureMatch(); await saveFields(); } catch (e) { return toastErr(e); }
  const sc = { match: { team_us: '', team_them: '', total_us: null, total_them: null, result: '', player_of_match: '', date: '' },
    batter: { name: N.batter.trim(), runs_sheet: null, balls_sheet: null }, partner: { name: 'Partner', runs_sheet: null, balls_sheet: null },
    overs: [{ number: 1, bowler: '', total_sheet: null, balls: [] }], notes: '' };
  try { await api('PUT', `/api/matches/${encodeURIComponent(id())}/scorecard`, { scorecard: sc }); location.hash = '#sheet/' + encodeURIComponent(id()); } catch (e) { toastErr(e); }
}

async function startSync() {
  try {
    await saveFields();
    await api('PUT', `/api/matches/${encodeURIComponent(id())}/scorecard`, { scorecard: N.full.scorecard, confirm: true });
    await api('POST', `/api/matches/${encodeURIComponent(id())}/sync`, {});
    location.hash = '#sync/' + encodeURIComponent(id());
  } catch (e) { toastErr(e); }
}

function bind() {
  const main = N.main;
  main.addEventListener('input', e => {
    const t = e.target;
    if (t.id === 'batter') { N.batter = t.value; const b = $('[data-act="read"]', main); if (b) b.disabled = !N.batter.trim() || N.busy; }
    else if (t.id === 'mname') N.name = t.value;
    else if (t.id === 'sheeturl') {
      N.url = t.value;
      const um = URL_RE.exec(N.url.trim()), wrap = t.parentElement, tick = $('.tick', wrap);
      if (um && !tick) wrap.insertAdjacentHTML('beforeend', `<span class="tick" aria-label="Link recognised">${ic('check', 'sm')}</span>`);
      if (!um && tick) tick.remove();
      $('#urlstate', main).innerHTML = urlState(um);
      const b = $('[data-act="read"]', main); if (b) b.disabled = !N.url.trim() || !N.batter.trim() || N.busy;
    }
  });
  main.addEventListener('keydown', e => { if (e.target.id === 'sheeturl' && e.key === 'Enter' && N.url.trim()) readSheet(); });
  main.addEventListener('change', async e => {
    const t = e.target;
    if (t.id === 'vfile') { addVideos([...t.files]); t.value = ''; }
    else if (t.id === 'sfile') { if (t.files[0]) setSheetFile(t.files[0]); t.value = ''; }
    else if (t.id === 'cam') { N.camera = t.value; await saveCamera(); }
  });
  ['dragover', 'dragleave', 'drop'].forEach(ev => main.addEventListener(ev, e => {
    const z = e.target.closest('#vdrop, #sdrop'); if (!z) return;
    e.preventDefault();
    z.classList.toggle('drop-on', ev === 'dragover');
    if (ev === 'drop') { const fs = [...e.dataTransfer.files]; if (z.id === 'vdrop') addVideos(fs); else if (fs[0]) setSheetFile(fs[0]); }
  }));
  main.addEventListener('click', async e => {
    const b = e.target.closest('[data-act]'); if (!b || b.disabled) return;
    e.preventDefault();
    const act = b.dataset.act, file = b.closest('[data-file]') && b.closest('[data-file]').dataset.file;
    try {
      if (act === 'hl') {
        N.highlights = b.dataset.k;
        if (id()) { try { N.full = await api('PATCH', `/api/matches/${encodeURIComponent(id())}`, { highlights: N.highlights }); shell.match = N.full.match; } catch (er) { toastErr(er); } }
        render(); return;
      }
      if (act === 'mode') { N.mode = b.dataset.mode; N.error = null; try { localStorage.setItem('cr.sheetMode', N.mode); } catch (er) { /* */ } render(); const u = $('#sheeturl'); if (u) u.focus(); }
      else if (act === 'lens') { N.lens = b.dataset.k; $$('[data-act="lens"]', main).forEach(x => x.setAttribute('aria-pressed', x.dataset.k === N.lens)); await saveCamera(); toast(`Lens set to ${shell.status.lenses[N.lens]} · remembered for next time`); }
      else if (act === 'pickVideo') {
        if (desktopPicker()) {
          const paths = await window.pywebview.api.pick_videos();
          if (paths && paths.length) { await ensureMatch(); N.full.match = await api('POST', `/api/matches/${encodeURIComponent(id())}/videos/link`, { paths }); shell.match = N.full.match; render(); }
        } else $('#vfile').click();
      }
      else if (act === 'pickSheet') $('#sfile').click();
      else if (act === 'read') await readSheet();
      else if (act === 'manual') await manualEntry();
      else if (act === 'sync') await startSync();
      else if (act === 'vdel') {
        const v = match().videos.find(x => x.file === file);
        if (await confirmSheet('Remove this video?', v.linked ? 'The match stops using it. Your original file is not touched.' : 'The copy in the match folder is deleted. Your original file is not touched.', 'Remove', { danger: true })) {
          N.full.match = await api('DELETE', `/api/matches/${encodeURIComponent(id())}/videos?file=${encodeURIComponent(file)}`); shell.match = N.full.match; render();
        }
      }
      else if (act === 'vup' || act === 'vdown') {
        const files = match().videos.map(v => v.file), i = files.indexOf(file), j = i + (act === 'vup' ? -1 : 1);
        [files[i], files[j]] = [files[j], files[i]];
        N.full.match = await api('PUT', `/api/matches/${encodeURIComponent(id())}/videos/order`, { files }); render();
      }
    } catch (err) { toastErr(err); }
  });
}

async function saveCamera() {
  if (!id()) { await api('PUT', '/api/settings', { camera: N.camera, lens: N.lens }).catch(() => {}); return; }
  saving('saving');
  try { N.full = await api('PATCH', `/api/matches/${encodeURIComponent(id())}`, { camera: N.camera, lens: N.lens }); shell.match = N.full.match; saving('saved'); }
  catch (e) { saving('error'); toastErr(e); }
}
