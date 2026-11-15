// Settings: saved on this laptop, applied straight away. Claude API key and model, quick links (E4), keep rules (K2),
// the keep-away zones (L5), batting and camera defaults, export encoder, storage, feedback and privacy, about.
import { api } from './core/api.js';
import { esc } from './core/util.js';
import { $, $$, confirmSheet, head, ic, pill, sheet, toast, toastErr } from './ui.js';
import { openFeedback, shell } from './shell.js';

const DEFAULT_LINKS = [
  { name: 'Facebook / Meta', url: 'https://business.facebook.com/latest/home' },
  { name: 'YouTube', url: 'https://studio.youtube.com' },
  { name: 'TikTok', url: 'https://www.tiktok.com/tiktokstudio/upload' },
];
const COLOURS = ['--blue', '--pink', '--teal', '--amber', '--purple', '--green'];
const SHORTCUTS = [
  ['Sync', [[', / .', 'Playhead one frame'], ['Shift+← / →', 'Playhead ¼ s'], ['↑ / ↓', 'Previous / next ball'], ['N', 'Snap to the nearest hit'], ['P', 'Pin the ball at the playhead'], ['Space', 'Play / pause']]],
  ['Review', [['↑ / ↓', 'Previous / next clip'], ['Shift+← / →', 'Move the contact ¼ s'], ['Alt+, / Alt+.', 'Move the contact one frame'], ['C', 'Contact at the playhead'], ['N', 'Snap to the nearest hit'], ['X', 'Keep / not keep'], ['S', 'Star'], ['Enter', "It's right, next to check"]]],
  ['Arrange', [['← / →', 'Select the previous / next clip'], ['Alt+← / →', 'Move the selected clip'], ['Delete', 'Take the clip out of the reel']]],
  ['Everywhere', [['Ctrl+Z / Ctrl+Shift+Z', 'Undo / redo'], ['Esc', 'Close a dialog']]],
];
let S = null;

export async function prepare() { shell.title = 'Settings'; return {}; }

export async function mount(main) {
  S = { main, links: (shell.status.settings.quick_links || []).map(x => ({ ...x })) };
  main.style.setProperty('--accent', 'var(--blue)');
  render();
  bind();
  return { context: () => 'Settings' };
}

async function save(patch, msg) {
  try { shell.status.settings = await api('PUT', '/api/settings', patch); if (msg) toast(msg); return true; } catch (e) { toastErr(e); return false; }
}

// 2.1: the description prompt, in the parts it's made of, editable. Empty or unchanged = the default.
const PARTS = [['shared', 'Shared rules', 'audience, search, style, rules'], ['meta', 'Meta · Instagram + Facebook Reels', 'caption'], ['tiktok', 'TikTok', 'caption'],
  ['yt_title', 'YouTube Shorts', 'title'], ['yt_desc', 'YouTube Shorts', 'description'], ['user', 'Message for each file', '{facts} and {prompt} are filled in']];
function promptsCard() {
  const st = shell.status, mine = st.settings.describe_prompts || {}, def = st.describe_defaults || {};
  const n = Object.keys(mine).length;
  return `<section class="card a-purple span-12" style="--i:11">
    <div class="card-head"><span class="ic">${ic('message')}</span><h3>Description prompts</h3>${n ? pill('check', `${n} changed`) : pill('keep', 'Defaults')}<button class="btn sm ghost" data-act="promptreset" style="margin-left:auto">${ic('refresh', 'sm')}Reset to defaults</button></div>
    <p class="small muted" style="margin-bottom:12px">Exactly what's sent to Claude for each exported file on Describe: one call per file. The system prompt is the shared rules and the four platform parts; the message is the facts and your words. {venue} is replaced by the venue below.</p>
    <label class="field"><span>Venue</span><input id="venue" value="${esc(st.settings.venue || '')}" maxlength="80"></label>
    ${PARTS.map(([k, l, sub], i) => `${i === 1 ? '<div class="pgrid">' : ''}<label class="field"><span>${l} <small class="muted" style="text-transform:none;letter-spacing:0;font-weight:500">· ${sub}</small></span><textarea class="prompt-ta ${k === 'shared' ? '' : 'sm'}" data-pk="${k}" spellcheck="false">${esc(mine[k] || def[k] || '')}</textarea></label>${i === 4 ? '</div>' : ''}`).join('')}
  </section>`;
}

function render() {
  const st = shell.status, s = st.settings, ad = s.auto_drop || {};
  S.main.innerHTML = `${head('App', 'Settings', 'Saved on this laptop. Changes apply straight away.')}
    <div class="grid">
      <section class="card a-purple span-6" style="--i:0">
        <div class="card-head"><span class="ic">${ic('key')}</span><h3>Claude API</h3>${st.api_key ? pill('keep', 'Key saved') : pill('check', 'No key yet')}</div>
        <p class="small muted">${st.api_key ? (st.api_key_source === 'env' ? 'The key comes from the .env file (development).' : 'Encrypted for your Windows user, on this laptop only.') : 'Only needed for score sheet photos and descriptions. Spawtz links work without one.'}</p>
        ${st.api_key_source !== 'env' ? `<div style="display:flex;gap:8px;margin-top:10px;flex-wrap:wrap"><input type="password" class="search" id="apikey" placeholder="${st.api_key ? 'Paste a new key to replace it' : 'sk-ant-…'}" autocomplete="off" aria-label="Claude API key" style="flex:1;min-width:200px"><button class="btn sm" data-act="savekey">Save key</button>${st.api_key ? '<button class="btn sm ghost" data-act="delkey">Remove</button>' : ''}</div>` : ''}
        <label class="field" style="margin-top:12px"><span>Model for score sheets and descriptions</span><select id="model">${Object.entries(st.models).map(([k, l]) => `<option value="${k}" ${k === s.model ? 'selected' : ''}>${esc(l)}</option>`).join('')}</select></label>
        <button class="btn sm" data-act="test" ${st.api_key ? '' : 'disabled'}>Test the connection</button>
        <p class="cap muted" style="margin-top:8px">Only a score sheet photo and the text prompts are sent. Video never leaves this laptop. Cost shows on each step and in the top bar.</p>
      </section>
      <section class="card a-blue span-6" style="--i:1">
        <div class="card-head"><span class="ic">${ic('link')}</span><h3>Quick links</h3><span class="meta">Shown after the descriptions</span></div>
        <div id="qedit"></div>
        <div style="display:flex;gap:8px;margin-top:6px"><button class="btn sm" data-act="qadd" ${S.links.length >= 12 ? 'disabled' : ''}>${ic('plus', 'sm')}Add link</button><button class="btn sm ghost" data-act="qreset">Reset to defaults</button></div>
      </section>
      <section class="card a-green span-4" style="--i:2">
        <div class="card-head"><span class="ic">${ic('scissors')}</span><h3>Keep rules</h3></div>
        ${[['dot', 'Dot balls start as not kept'], ['ls', 'Leg-side wides start as not kept'], ['nb', 'No-balls start as not kept']].map(([k, l]) => `<label class="switch"><span class="t">${l}</span><input type="checkbox" data-drop="${k}" ${ad[k] ? 'checked' : ''}></label>`).join('')}
        <p class="cap muted">Everything else is kept. Applies to new clips; you can always change a single clip in Review.</p>
      </section>
      <section class="card a-pink span-4" style="--i:3">
        <div class="card-head"><span class="ic">${ic('phone')}</span><h3>Keep-away zones</h3></div>
        <dl class="kv"><dt>Top (status bar)</dt><dd>9%</dd><dt>Bottom (caption, buttons)</dt><dd>20%</dd><dt>Right (like, share)</dt><dd>15%, 45–80% down</dd></dl>
        <p class="cap muted" style="margin-top:8px">Text on the reel always stays out of these areas, where TikTok, Reels and Shorts draw their own buttons and captions.</p>
      </section>
      <section class="card a-teal span-4" style="--i:4">
        <div class="card-head"><span class="ic">${ic('user')}</span><h3>You</h3></div>
        <label class="field"><span>Your name on the sheet · batter and bowler</span><input id="batter" value="${esc(s.batter_name)}"></label>
        ${[0, 1].map(k => `<label class="field"><span>Also written as${k ? ' (another)' : ''}</span><input id="alias${k}" value="${esc((s.other_names || [])[k] || '')}" placeholder="${k ? 'e.g. Al C' : 'e.g. A Carter'}"></label>`).join('')}
        <p class="cap muted" style="margin:-4px 0 10px">Sheets don't always spell you the same way. Each name is tried; the closest match on the sheet wins.</p>
        <label class="field"><span>Standings page (shown on New match)</span><input id="standings" type="url" value="${esc(s.standings_url || '')}" placeholder="https://…spawtz.com/Leagues/Standings?…"></label>
        <div style="display:flex;gap:10px"><label class="field" style="flex:1"><span>Seconds before contact</span><input id="cb" type="number" inputmode="decimal" step="0.25" min="0.25" max="8" value="${s.clip_before}"></label><label class="field" style="flex:1"><span>Seconds after</span><input id="ca" type="number" inputmode="decimal" step="0.25" min="0.25" max="8" value="${s.clip_after}"></label></div>
      </section>
      <section class="card a-blue span-4" style="--i:5">
        <div class="card-head"><span class="ic">${ic('film')}</span><h3>Camera</h3></div>
        <label class="field"><span>Camera</span><select id="camera">${st.cameras.map(c => `<option ${c === s.camera ? 'selected' : ''}>${esc(c)}</option>`).join('')}${st.cameras.includes(s.camera) ? '' : `<option selected>${esc(s.camera)}</option>`}</select></label>
        <div class="field"><span>Lens mode</span><div class="seg" role="group" aria-label="Lens mode">${Object.entries(st.lenses).map(([k, l]) => `<button data-act="lens" data-k="${k}" aria-pressed="${s.lens === k}">${esc(l)}</button>`).join('')}</div></div>
        <p class="cap muted">The default for new matches. Each match keeps its own.</p>
      </section>
      <section class="card a-amber span-4" style="--i:6">
        <div class="card-head"><span class="ic">${ic('download')}</span><h3>Export</h3></div>
        <label class="field"><span>Video encoder</span><select id="encoder"><option value="auto" ${s.encoder !== 'x264' ? 'selected' : ''}>Automatic: Intel Quick Sync, else software</option><option value="x264" ${s.encoder === 'x264' ? 'selected' : ''}>Always software (x264)</option></select></label>
        <p class="cap muted">Every file is one top-quality 40 Mbps H.264 that fits TikTok, Reels and Shorts.</p>
      </section>
      <section class="card a-blue span-4" style="--i:7">
        <div class="card-head"><span class="ic">${ic('folder')}</span><h3>Storage</h3></div>
        <div class="field"><span>Matches folder</span><div class="mono cap" style="overflow-wrap:anywhere">${esc(st.matches_dir)}</div></div>
        <div style="display:flex;gap:8px;flex-wrap:wrap"><button class="btn sm" data-act="dir">Change…</button>${s.matches_dir ? '<button class="btn sm ghost" data-act="dirreset">Use the default</button>' : ''}</div>
        <p class="cap muted" style="margin-top:8px">Existing matches stay where they are. Settings and scoring rules: <span class="mono">${esc(st.config_dir)}</span></p>
      </section>
      <section class="card a-purple span-4" style="--i:8">
        <div class="card-head"><span class="ic">${ic('shield')}</span><h3>Feedback and privacy</h3></div>
        <p class="small muted">"Provide feedback" saves a zip in the app's feedback folder. The API key, passwords, tokens and folder paths outside the app are removed first. Nothing is sent anywhere.</p>
        <button class="btn sm" style="margin-top:10px" data-act="feedback">${ic('message', 'sm')}Provide feedback</button>
      </section>
      <section class="card a-teal span-8" style="--i:9">
        <div class="card-head"><span class="ic">${ic('keyboard')}</span><h3>Keyboard shortcuts</h3></div>
        <div class="grid" style="grid-template-columns:repeat(auto-fit,minmax(220px,1fr))">${SHORTCUTS.map(([g, list]) => `<div><div class="label" style="margin-top:0">${g}</div><dl class="kv">${list.map(([k, d]) => `<dt>${esc(d)}</dt><dd>${esc(k)}</dd>`).join('')}</dl></div>`).join('')}</div>
      </section>
      <section class="card a-blue span-4" style="--i:10">
        <div class="card-head"><span class="ic">${ic('info')}</span><h3>About</h3>${pill('normal mono', 'v' + esc(st.version), false)}</div>
        <p class="small muted">Cricket Reel ${esc(st.version)} · ${st.desktop ? 'desktop app' : 'browser'} · FFmpeg ${st.ffprobe ? 'found' : 'not found (winget install -e --id Gyan.FFmpeg)'}</p>
      </section>
      ${promptsCard()}
    </div>`;
  drawLinks();
}

function drawLinks() {
  $('#qedit').innerHTML = S.links.map((q, k) => `<div class="linkedit" style="--pc:var(${COLOURS[k % COLOURS.length]})"><span class="dot"></span><input aria-label="Link name" data-q="${k}" data-f="name" value="${esc(q.name)}" maxlength="40"><input class="url" aria-label="Link address" data-q="${k}" data-f="url" value="${esc(q.url)}" inputmode="url"><button class="btn icon sm ghost" data-act="qdel" data-k="${k}" aria-label="Remove ${esc(q.name)}">${ic('x', 'sm')}</button></div>`).join('') || '<p class="cap muted">No links.</p>';
}
async function saveLinks(msg) {
  const bad = S.links.find(q => !q.name.trim() || !q.url.startsWith('https://'));
  if (bad) return toastErr(new Error('Each link needs a name and an address starting with https://'));
  await save({ quick_links: S.links }, msg);
}

async function setDir(dir) {
  if (await save({ matches_dir: dir }, 'Matches folder updated')) { shell.status = await api('GET', '/api/status'); render(); }
}

function bind() {
  const main = S.main;
  main.addEventListener('change', async e => {
    const t = e.target;
    if (t.id === 'model') save({ model: t.value }, 'Model updated');
    else if (t.id === 'encoder') save({ encoder: t.value }, 'Encoder updated');
    else if (t.id === 'batter') save({ batter_name: t.value.trim() }, 'Your name saved');
    else if (t.id === 'alias0' || t.id === 'alias1') save({ other_names: [$('#alias0').value.trim(), $('#alias1').value.trim()].filter(Boolean) }, 'Names saved');
    else if (t.id === 'standings') save({ standings_url: t.value.trim() }, 'Standings link saved');
    else if (t.id === 'venue') save({ venue: t.value.trim() }, 'Venue saved');
    else if (t.dataset.pk) { if (await save({ describe_prompts: { ...(shell.status.settings.describe_prompts || {}), [t.dataset.pk]: t.value } }, 'Prompt saved')) render(); }
    else if (t.id === 'cb' || t.id === 'ca') { const v = Math.min(8, Math.max(0.25, +t.value || 1)); t.value = v; save({ [t.id === 'cb' ? 'clip_before' : 'clip_after']: v }, 'Default clip window saved'); }
    else if (t.id === 'camera') save({ camera: t.value }, 'Camera saved');
    else if (t.dataset.drop) save({ auto_drop: { ...shell.status.settings.auto_drop, [t.dataset.drop]: t.checked } }, 'Keep rule saved');
    else if (t.dataset.q != null) { S.links[+t.dataset.q][t.dataset.f] = t.value.trim(); saveLinks('Quick links saved'); }
  });
  main.addEventListener('click', async e => {
    const b = e.target.closest('[data-act]'); if (!b || b.disabled) return;
    const act = b.dataset.act;
    if (act === 'lens') { if (await save({ lens: b.dataset.k }, 'Lens mode saved')) $$('[data-act="lens"]', main).forEach(x => x.setAttribute('aria-pressed', x === b)); }
    else if (act === 'promptreset') { if (await confirmSheet('Reset the description prompts?', 'Every part goes back to the default. The venue stays.', 'Reset') && await save({ describe_prompts: {} }, 'Prompts reset to the defaults')) render(); }
    else if (act === 'savekey') {
      const v = $('#apikey').value.trim(); if (!v) return;
      try { await api('PUT', '/api/settings/api-key', { key: v }); shell.status = await api('GET', '/api/status'); toast('API key saved'); render(); } catch (err) { toastErr(err); }
    }
    else if (act === 'delkey') {
      if (await confirmSheet('Remove the API key?', "Score sheet photos and descriptions can't be written until you add a key again. Spawtz links still work.", 'Remove key', { danger: true })) {
        try { await api('DELETE', '/api/settings/api-key'); shell.status = await api('GET', '/api/status'); toast('API key removed'); render(); } catch (err) { toastErr(err); }
      }
    }
    else if (act === 'test') { b.innerHTML = '<span class="spin"></span>Testing…'; try { await api('POST', '/api/test-key'); toast('Connected to the Claude API'); } catch (err) { toastErr(err); } b.textContent = 'Test the connection'; }
    else if (act === 'qadd') { S.links.push({ name: 'New link', url: 'https://' }); drawLinks(); const i = $$('#qedit .url'); i[i.length - 1].focus(); }
    else if (act === 'qdel') { const k = +b.dataset.k, [gone] = S.links.splice(k, 1); drawLinks(); await saveLinks(); toast(`${gone.name} removed`, { undo: () => { S.links.splice(k, 0, gone); drawLinks(); saveLinks(); } }); }
    else if (act === 'qreset') { S.links = DEFAULT_LINKS.map(x => ({ ...x })); drawLinks(); saveLinks('Quick links reset'); }
    else if (act === 'feedback') openFeedback();
    else if (act === 'dirreset') setDir('');
    else if (act === 'dir') {
      if (window.pywebview && window.pywebview.api && window.pywebview.api.pick_folder) { const d = await window.pywebview.api.pick_folder(); if (d) setDir(d); return; }
      const s = sheet(`<h2>Matches folder</h2><label class="field" style="margin-top:12px"><span>Full path of the folder to keep matches in</span><input type="text" id="dirin" value="${esc(shell.status.matches_dir)}"></label>
        <div style="display:flex;gap:8px;justify-content:flex-end"><button class="btn ghost" data-close>Cancel</button><button class="btn primary" data-ok>Use this folder</button></div>`, { label: 'Matches folder' });
      s.el.querySelector('[data-ok]').onclick = () => { const v = s.el.querySelector('#dirin').value.trim(); s.close(); if (v) setDir(v); };
    }
  });
}
