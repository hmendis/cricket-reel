// Step 4 · Arrange: the reel order (biggest moments first; drag or Alt+←/→ to move, K1), transitions and effects,
// and the text on each clip (L3): drag it on the video, style it; it stops at the keep-away zones (L5).
// 2.2: one window, no page scroll - a Reel panel with folded settings, a two-column text panel, the reel order docked
// along the bottom and the video full height. No header cards, no music. A Bowling + Fielding reel is one sequence by
// ball (no sections); an All-round reel keeps its sections and their order.
import { api } from './core/api.js';
import { follow, isActive } from './core/jobs.js';
import { fitBox, isBowlField, reelLength, sectionOf } from './core/reel.js';
import { createAutosave, createHistory } from './core/state.js';
import { clamp, esc, mmss } from './core/util.js';
import { $, $$, ic, kindClass, pill, toast, toastErr } from './ui.js';
import { kickJobs, reached, saving, shell, stepLabel } from './shell.js';

const enc = encodeURIComponent;
const FONTS = ['Barlow Condensed', 'Bebas Neue', 'Oswald', 'Plus Jakarta Sans'];
const COLOURS = ['#FFFFFF', '#FFB547', '#4ADE80', '#FF5C8A', '#4F8CFF', '#07080B'];
const TRANS = [['cut', 'Cut'], ['fade', 'Crossfade'], ['slideleft', 'Swipe'], ['zoomin', 'Zoom']];
const STYLE_KEYS = ['font', 'size', 'bold', 'caps', 'shadow', 'outline', 'bg', 'bo', 'color'];
const FOLDS = { sec: true, txt: false, fx: true };   // folded by default: section order, transition & effects
let A = null;

// 2.1: three kinds of reel
const RTYPES = { batting: ['Batting', ['batting']], bowlfield: ['Bowling + Fielding', ['bowling', 'fielding']], allround: ['All-round', ['batting', 'bowling', 'fielding']] };
const SEC = { batting: ['Batting', 'bat'], bowling: ['Bowling', 'ball'], fielding: ['Fielding', 'hand'] };

export async function prepare([id]) {
  const d = await api('GET', `/api/matches/${enc(id)}/arrange`);
  shell.match = d.match; shell.step = 'arrange';
  return { d };
}

export async function mount(main, { d }) {
  A = { main, id: d.match.id, reel: d.reel, clips: d.clips, sel: null, selText: null, zones: true, mode: 'clip', raf: 0, stop: null,
    reels: d.reels || [], newOpen: false, poolOpen: false, folds: readFolds() };
  main.classList.add('wide', 'fit');
  normalize();
  if (A.reel.texts == null) A.reel.texts = d.texts; // old reels: start from what their hook/outro/labels drew
  A.sel = A.reel.entries.length ? A.reel.entries[0].uid : null;
  A.selText = (texts()[0] || {}).id || null;
  A.hist = createHistory(() => A.reel, x => { A.reel = x; });
  A.save = createAutosave({
    key: 'reel', url: () => `/api/matches/${enc(A.id)}/reel`, body: () => ({ reel: A.reel }),
    send: b => api('PUT', `/api/matches/${enc(A.id)}/reel`, b).then(r => { reached('arrange'); return r; }), onState: (s, e) => { saving(s); if (e) toastErr(e); },
  });
  main.style.setProperty('--accent', 'var(--amber)');
  render();
  bind();
  return {
    context: () => { const e = entry(); return e ? `${RTYPES[A.reel.rtype][0]} reel, clip ${A.reel.entries.indexOf(e) + 1} of ${A.reel.entries.length} selected, ${texts().length} text(s)` : 'empty reel'; },
    key: onKey,
    unmount: () => { A.save.flush(); if (A.stop) A.stop(); cancelAnimationFrame(A.raf); const v = vid(); if (v) { v.pause(); v.removeAttribute('src'); v.load(); } },
  };
}

const clipBy = i => A.clips.find(c => c.index === i);
const entry = () => A.reel.entries.find(e => e.uid === A.sel);
const curClip = () => { const e = entry(); return e && clipBy(e.index); };
const texts = () => { const c = curClip(); if (!c) return []; return A.reel.texts[String(c.index)] || (A.reel.texts[String(c.index)] = []); };
const selText = () => texts().find(t => t.id === A.selText);
const vid = () => $('#av');
const name = c => c.source === 'manual' ? (c.label ? c.label.charAt(0) + c.label.slice(1).toLowerCase() : 'Your clip') : `Over ${c.over} · Ball ${c.ball}`;
const ballTag = c => c.source === 'manual' ? mmss(c.t, 0) : `${c.over}.${c.ball}`;
const shortLabel = c => c.wid ? c.label.split('·').pop().trim() : (c.label || name(c));
const thumb = c => `/api/matches/${enc(A.id)}/thumb/${Math.max(0, Math.floor(c.t))}`;
const clipLen = c => c.before + c.after;
const kinds = () => RTYPES[A.reel.rtype || 'batting'][1];
const order = () => { const ks = kinds(), o = (A.reel.order || []).filter(s => ks.includes(s)); return o.concat(ks.filter(s => !o.includes(s))); };
/** Sections only on an All-round reel; Batting has one kind and Bowling + Fielding plays as one sequence by ball. */
const multi = () => kinds().length > 1 && !isBowlField(kinds());
const possible = () => Object.keys(RTYPES).filter(k => RTYPES[k][1].some(s => A.clips.some(c => sectionOf(c) === s)));
const pool = () => A.clips.filter(c => c.keep && kinds().includes(sectionOf(c)) && !A.reel.entries.some(e => e.index === c.index));
function readFolds() { try { return { ...FOLDS, ...JSON.parse(localStorage.getItem('cr.arrange.folds') || '{}') }; } catch (e) { return { ...FOLDS }; } }
function setFold(k) { A.folds[k] = !A.folds[k]; try { localStorage.setItem('cr.arrange.folds', JSON.stringify(A.folds)); } catch (e) { /* storage blocked */ } }
/** Keep the entries in this reel's kinds; on an All-round reel: hook + each section in order (a clip dropped in
 * another section goes back to its own). */
function normalize() {
  const es = A.reel.entries.filter(e => { const c = clipBy(e.index); return c && kinds().includes(sectionOf(c)); });
  if (!es.length || !multi()) { A.reel.entries = es; return; }
  A.reel.entries = [es[0], ...order().flatMap(s => es.slice(1).filter(e => sectionOf(clipBy(e.index)) === s))];
}
const totalLen = () => reelLength(A.reel, clipBy);
const defaultLabel = c => c.kind === 'manual' ? (c.label || 'MOMENT') : c.wid ? `Over ${c.over} · ${(c.label.split('·').pop() || '').trim()}` : c.kind === 'big' && c.label.includes('·') ? `Over ${c.over} · ${c.label.split('·').pop().trim()} RUNS` : c.kind === 'wicket' ? `Over ${c.over} · WICKET` : `Over ${c.over} · ${c.label === 'DOT' ? 'DOT BALL' : c.label}`;

function ring(v, lo, hi) {
  const r = 48, C = 2 * Math.PI * r, p = clamp(v / hi, 0, 1), ok = v >= lo && v <= hi;
  return `<div class="ring" style="--accent:${ok ? 'var(--amber)' : 'var(--pink)'}"><svg viewBox="0 0 112 112"><circle class="bgc" cx="56" cy="56" r="${r}" fill="none" stroke-width="10"/><circle class="fg" cx="56" cy="56" r="${r}" fill="none" stroke-width="10" stroke-dasharray="${C}" stroke-dashoffset="${C * (1 - p)}"/></svg><div class="c"><div><b>${v.toFixed(1)} s</b><small>of ${hi} s</small></div></div></div>`;
}

function render() {
  A.main.innerHTML = `<div class="studio fit"><div class="smain">
      <div class="fithead"><span class="eyebrow"><span class="dot"></span>${stepLabel('arrange')}</span><span class="sum" id="asum"></span><span class="acts" id="aacts"></span></div>
      <div id="newreel"></div>
      <div class="ar-grid">
        <section class="card a-amber ar-set" style="--i:0" id="settings" aria-label="Reel"></section>
        <section class="card a-amber ar-text" style="--i:1" id="tinsp" aria-label="Text on this clip"></section>
      </div>
      <section class="card a-amber ar-strip" style="--i:2" aria-label="Reel order"><div class="rsh" id="striphead"></div><div id="pool"></div><div class="reel" id="reel" role="list"></div></section>
    </div>
    <aside class="vcol" aria-label="Preview"><div class="vframe" id="aframe"></div></aside>
  </div>`;
  drawHead(); drawSettings(); drawFrame(); drawInspector(); drawStrip();
}

// ---------- the one-line header: counts, reel tabs, new reel, delete, preview mode, Export ----------
function drawHead() {
  const r = A.reel, have = new Set(A.reels.map(x => x.rtype)), missing = possible().filter(k => !have.has(k));
  $('#asum').innerHTML = `<b>${r.entries.length}</b> clips · <b>${totalLen().toFixed(1)} s</b> of ${r.target_max} s · each reel exports as its own file`;
  $('#aacts').innerHTML = `${A.reels.length > 1 ? `<div class="seg" role="tablist" aria-label="Reels">${A.reels.map(x => `<button role="tab" data-act="rpick" data-k="${x.rtype}" aria-pressed="${x.rtype === r.rtype}" aria-selected="${x.rtype === r.rtype}">${RTYPES[x.rtype][1].map(s => ic(SEC[s][1], 'sm')).join('')}${RTYPES[x.rtype][0]} <span class="mono cap">${x.rtype === r.rtype ? r.entries.length : x.count} · ${(x.rtype === r.rtype ? totalLen() : x.total).toFixed(0)}s</span></button>`).join('')}</div>` : ''}
    ${missing.length ? `<button class="btn sm ghost" data-act="newreel" aria-expanded="${A.newOpen}">${ic('plus', 'sm')}New reel</button>` : ''}
    ${A.reels.length > 1 ? `<button class="btn icon sm ghost" data-act="delreel" aria-label="Delete this reel" title="Delete this reel">${ic('trash', 'sm')}</button>` : ''}
    <div class="seg" role="group" aria-label="Preview"><button data-act="mode" data-k="clip" aria-pressed="${A.mode === 'clip'}" title="Play the selected clip">This clip</button><button data-act="mode" data-k="reel" aria-pressed="${A.mode === 'reel'}" title="The whole reel, rendered at 540×960">Whole reel</button></div>
    <a class="btn sm primary" href="#export/${enc(A.id)}">Export ${ic('chev', 'sm')}</a>`;
  $('#newreel').innerHTML = A.newOpen && missing.length ? `<div class="newreel"><span class="small">Add a</span>${missing.map(k => `<button class="btn sm" data-act="mkreel" data-k="${k}">${RTYPES[k][1].map(s => ic(SEC[s][1], 'sm')).join('')}${RTYPES[k][0]} reel</button>`).join('')}<button class="btn sm ghost" data-act="newreel">Cancel</button></div>` : '';
}
async function openReel(rtype, create) {
  try {
    await A.save.flush();
    const d = create ? await api('POST', `/api/matches/${enc(A.id)}/reels`, { rtype }) : await api('GET', `/api/matches/${enc(A.id)}/arrange?rtype=${enc(rtype)}`);
    A.reel = d.reel; A.clips = d.clips; A.reels = d.reels || A.reels; A.newOpen = false; A.poolOpen = false;
    if (A.reel.texts == null) A.reel.texts = d.texts;
    normalize(); A.sel = A.reel.entries.length ? A.reel.entries[0].uid : null; A.selText = (texts()[0] || {}).id || null;
    A.hist = createHistory(() => A.reel, x => { A.reel = x; });
    render();
    if (create) toast(`${RTYPES[rtype][0]} reel made · ${A.reel.entries.length} clips, about ${totalLen().toFixed(0)} s`);
  } catch (e) { toastErr(e); }
}
function newText(c, k, prev) {
  const t = { id: Math.random().toString(16).slice(2, 10), text: k === 0 && A.reel.hook_text ? A.reel.hook_text : defaultLabel(c), x: 50, y: k === 0 ? 30 : 72, font: 'Barlow Condensed', size: k === 0 ? 8 : 5, bold: true, caps: true, shadow: false, outline: false, bg: 'box', bo: 0.55, color: '#FFFFFF', show: 'clip' };
  if (prev) STYLE_KEYS.forEach(s => { if (s !== 'size') t[s] = prev[s]; });
  return t;
}
function textAll(on) {
  A.hist.push();
  const prev = selText() || Object.values(A.reel.texts).flat()[0];
  A.reel.entries.forEach((e, k) => {
    const key = String(e.index);
    if (!on) { A.reel.texts[key] = []; return; }
    if ((A.reel.texts[key] || []).length) return;
    A.reel.texts[key] = [newText(clipBy(e.index), k, prev)];
  });
  A.selText = (texts()[0] || {}).id || null;
  const redraw = () => { A.save.queue(); drawSettings(); drawStrip(); refreshStage(); drawInspector(); };
  redraw();
  toast(on ? 'Text on every clip in this reel' : 'Text removed from every clip in this reel', { undo: () => { A.hist.undo(); redraw(); } });
}

// ---------- the Reel panel: length, target, auto-fill and the folded settings ----------
const fold = (k, title, sum, body) => `<div class="fold"><button class="fold-h" data-act="fold" data-k="${k}" aria-expanded="${!A.folds[k]}"><span>${title}</span><small>${sum}</small>${ic(A.folds[k] ? 'down' : 'up', 'sm')}</button>${A.folds[k] ? '' : `<div class="fold-b">${body}</div>`}</div>`;
function drawSettings() {
  const r = A.reel, len = totalLen(), nTxt = r.entries.filter(e => (r.texts[String(e.index)] || []).length).length;
  $('#settings').innerHTML = `<div class="rs1">${ring(len, r.target_min, r.target_max)}<dl class="kv" style="flex:1"><dt>Clips</dt><dd>${r.entries.length}</dd>${multi() ? `<dt>Sections</dt><dd>${order().length}</dd>` : ''}<dt>Kept, not in reel</dt><dd>${pool().length}</dd></dl></div>
    <div class="label">Target length</div>
    <div class="chips">${[30, 45, 60, 90].map(v => `<button class="chip" data-act="target" data-v="${v}" aria-pressed="${r.target_max === v}">${v} s</button>`).join('')}
      <button class="btn sm primary" data-act="autopick" title="${multi() ? 'The sections take turns adding their best clip (stars, then wickets and your clips, then the biggest shots) until the target is full' : isBowlField(kinds()) ? 'The best clips until the target is full, in ball order' : 'The best clips (stars, then the biggest shots) until the target is full'}">${ic('refresh', 'sm')}Auto-fill</button></div>
    ${multi() ? fold('sec', 'Section order', order().map(s => SEC[s][0]).join(' → '), order().map((s, k) => `<div class="secrow"><span class="grip">${k + 1}</span><span><b>${ic(SEC[s][1])}${SEC[s][0]}</b><small>${r.entries.slice(1).filter(e => sectionOf(clipBy(e.index)) === s).length} clips</small></span><span class="mv"><button class="btn icon sm ghost" data-act="secmv" data-s="${s}" data-d="-1" aria-label="Move ${SEC[s][0]} up" ${k === 0 ? 'disabled' : ''}>${ic('up', 'sm')}</button><button class="btn icon sm ghost" data-act="secmv" data-s="${s}" data-d="1" aria-label="Move ${SEC[s][0]} down" ${k === order().length - 1 ? 'disabled' : ''}>${ic('down', 'sm')}</button></span></div>`).join('')) : ''}
    ${fold('txt', 'Text on all clips', `${nTxt} of ${r.entries.length} show text`, `<div class="chips"><button class="chip" data-act="textall" data-v="1" aria-pressed="${!!r.entries.length && nTxt === r.entries.length}">${ic('type', 'sm')}Text on all</button><button class="chip" data-act="textall" data-v="0" aria-pressed="${nTxt === 0}">${ic('x', 'sm')}Remove from all</button></div>`)}
    ${fold('fx', 'Transition & effects', (TRANS.find(([k]) => k === r.trans) || [, 'Cut'])[1], `<div class="chips">${TRANS.map(([k, l]) => `<button class="chip" data-act="trans" data-k="${k}" aria-pressed="${r.trans === k}">${l}</button>`).join('')}</div>
      <label class="switch"><span class="t">Punch-in at contact<small>${Math.round(r.punch_zoom * 100)}% for a moment on the hit</small></span><input type="checkbox" data-set="punch" ${r.punch ? 'checked' : ''}></label>
      <label class="switch"><span class="t">Freeze the hook<small>${r.freeze_dur} s on the first contact</small></span><input type="checkbox" data-set="freeze" ${r.freeze ? 'checked' : ''}></label>
      <label class="switch" style="--accent:var(--pink)"><span class="t">Keep-away zones<small>Where TikTok, Reels and Shorts put their buttons</small></span><input type="checkbox" data-act="zones" ${A.zones ? 'checked' : ''}></label>`)}`;
}

// ---------- the video with its text ----------
function textStyle(t) {
  return `left:${t.x}%;top:${t.y}%;font-family:'${t.font}',var(--font);font-size:${t.size}cqw;font-weight:${t.bold ? 700 : 500};text-transform:${t.caps ? 'uppercase' : 'none'};color:${t.color};--bo:${t.bo}`;
}
function stageHtml() {
  return `<div class="stage" id="stage">
    ${A.zones ? '<div class="zone top" data-z="top"><span>Status bar</span></div><div class="island"></div><div class="zone right" data-z="right"><span>Like · share</span></div><div class="zone bottom" data-z="bottom"><span>Caption · buttons</span></div>' : ''}
    ${texts().map(t => `<div class="otext bg-${t.bg} ${t.shadow ? 'shadow' : ''} ${t.outline ? 'outline' : ''} ${t.id === A.selText ? 'sel' : ''}" data-tid="${t.id}" style="${textStyle(t)}" tabindex="0" role="button" aria-label="Text: ${esc(t.text)}. Drag to move.">${esc(t.text)}</div>`).join('')}
  </div>`;
}
function drawFrame() {
  const fr = $('#aframe'), c = curClip();
  cancelAnimationFrame(A.raf);
  if (A.mode === 'reel') {
    fr.innerHTML = `<video id="av" src="/api/matches/${enc(A.id)}/reel-preview?t=${Date.now()}" playsinline controls></video><div class="empty" id="noprev" hidden>No rendered preview yet.</div>
      <div class="vcap"><span class="tc" id="acap"></span><button class="btn sm" data-act="render">${ic('refresh', 'sm')}Render the preview</button></div>`;
    const v = vid();
    v.onerror = () => { $('#noprev').hidden = false; v.hidden = true; };
    $('#acap').textContent = '540×960, with transitions and text';
    return;
  }
  if (!c) { fr.innerHTML = '<div class="empty">The reel is empty. Auto-fill, or add a kept clip from the reel order.</div>'; return; }
  const k = A.reel.entries.findIndex(e => e.uid === A.sel);
  fr.innerHTML = `<video id="av" src="/api/matches/${enc(A.id)}/proxy" preload="auto" playsinline muted></video>${stageHtml()}
    <div class="vcap"><span class="tc" id="acap">${k === 0 ? 'Hook · ' : ''}${esc(name(c))} · ${clipLen(c).toFixed(1)} s</span></div>`;
  const v = vid();
  v.addEventListener('loadedmetadata', () => { v.currentTime = Math.max(0, c.t - c.before); v.play().catch(() => {}); loop(); }, { once: true });
  requestAnimationFrame(() => texts().forEach(fitText));
}
function loop() {
  const v = vid(), c = curClip();
  if (v && c && A.mode === 'clip' && v.currentTime >= c.t + c.after) v.currentTime = Math.max(0, c.t - c.before);
  A.raf = requestAnimationFrame(loop);
}
function refreshStage() {
  const st = $('#stage'); if (!st) return;
  const t = document.createElement('div'); t.innerHTML = stageHtml(); st.replaceWith(t.firstElementChild);
  requestAnimationFrame(() => texts().forEach(fitText));
}

/** L5: keep a text box inside the frame and out of the zones (same rule as the render). Returns the zone that stopped it. */
function fitText(t) {
  const fr = $('#aframe'), el = fr && $(`.otext[data-tid="${t.id}"]`, fr); if (!el) return null;
  const R = fr.getBoundingClientRect(), r = el.getBoundingClientRect();
  const f = fitBox(t.x, t.y, r.width / R.width * 100, r.height / R.height * 100);
  t.x = f.x; t.y = f.y; el.style.left = t.x + '%'; el.style.top = t.y + '%';
  return f.hit;
}

// ---------- the text panel: two columns ----------
function drawInspector() {
  const box = $('#tinsp'), c = curClip(), t = selText(), ts = texts();
  if (!c) { box.innerHTML = '<p class="small muted">This reel has no clips yet. Auto-fill, or keep more in Review.</p>'; return; }
  const isHook = A.reel.entries[0] && A.reel.entries[0].uid === A.sel;
  const cells = [[25, 22], [50, 22], [75, 22], [25, 45], [50, 45], [70, 45], [25, 68], [50, 68], [70, 68]];
  const head = `<div class="card-head"><span class="ic">${ic('type')}</span><h3>Text on ${isHook ? 'the hook · ' : ''}${esc(name(c))}</h3>${c.source === 'manual' ? '' : pill(c.wid ? 'wicket' : kindClass(c.kind), esc(shortLabel(c)))}<span class="pill normal mono">${clipLen(c).toFixed(1)} s</span>
      <button class="tgl" data-act="tshowtext" style="margin-left:auto;--accent:var(--amber)" aria-pressed="${ts.length > 0}" title="${ts.length ? 'Take the text off this clip' : 'Put text on this clip'}">${ic(ts.length ? 'check' : 'x', 'sm')}Shows text</button></div>`;
  const foot = `<div class="foot">${t ? '<button class="btn sm" data-act="tall">Use this style on every clip</button>' : ''}${isHook ? '' : `<button class="btn sm" data-act="mkhook">${ic('star', 'sm')}Make this the hook</button>`}<button class="btn sm ghost" data-act="remove">${ic('x', 'sm')}Take out of the reel</button><span class="cap muted" style="margin-left:auto;display:inline-flex;gap:4px;align-items:center">${ic('shield', 'sm')}Text stops at the red zones</span></div>`;
  if (!t) { box.innerHTML = `${head}<p class="small muted">No text on this clip. Switch <b>Shows text</b> on to add some; each clip has its own.</p>${foot}`; return; }
  box.innerHTML = `${head}
    ${ts.length > 1 ? `<div class="chips tight" style="margin-bottom:8px">${ts.map(x => `<button class="chip" data-act="seltext" data-tid="${x.id}" aria-pressed="${x.id === A.selText}">${esc((x.text.split('\n')[0] || 'Text').slice(0, 14))}${x.text.length > 14 ? '…' : ''}</button>`).join('')}<button class="btn icon sm ghost" data-act="rmtext" aria-label="Remove this text" title="Remove this text">${ic('trash', 'sm')}</button></div>` : ''}
    <div class="cols">
      <div class="col">
        <div class="field"><span style="display:flex;justify-content:space-between;align-items:center"><label for="ttext">${isHook ? 'Hook text' : 'Text'}</label><button class="btn sm ghost" style="min-height:22px;padding:0 6px" data-act="addtext" title="Add another text to this clip">${ic('plus', 'sm')}Another</button></span><textarea id="ttext" rows="2" maxlength="200">${esc(t.text)}</textarea></div>
        <label class="field"><span>Font</span><select id="tfont">${FONTS.map(f => `<option ${f === t.font ? 'selected' : ''}>${f}</option>`).join('')}</select></label>
        <div class="chips">${[['bold', 'Bold'], ['caps', 'Capitals'], ['shadow', 'Shadow'], ['outline', 'Outline']].map(([k, l]) => `<button class="chip" data-act="tstyle" data-k="${k}" aria-pressed="${!!t[k]}">${l}</button>`).join('')}</div>
        <div class="slider s" style="--accent:var(--amber)"><label for="tsize">Size</label><input id="tsize" type="range" min="3" max="16" step="0.5" value="${t.size}" style="--p:${(t.size - 3) / 13 * 100}%"><output>${t.size}</output></div>
      </div>
      <div class="col">
        <div class="label" style="margin-top:0">Colour</div>
        <div class="swatches">${COLOURS.map(col => `<button data-act="tcolor" data-c="${col}" style="background:${col}" aria-label="Colour ${col}" aria-pressed="${t.color.toUpperCase() === col}"></button>`).join('')}</div>
        <div class="label">Background</div>
        <div class="seg" role="group" aria-label="Text background">${[['none', 'None'], ['box', 'Box'], ['pill', 'Pill']].map(([k, l]) => `<button data-act="tbg" data-k="${k}" aria-pressed="${t.bg === k}">${l}</button>`).join('')}</div>
        ${t.bg !== 'none' ? `<div class="slider s" style="--accent:var(--amber)"><label for="tbo">Opacity</label><input id="tbo" type="range" min="0.1" max="1" step="0.05" value="${t.bo}" style="--p:${(t.bo - .1) / .9 * 100}%"><output>${Math.round(t.bo * 100)}%</output></div>` : ''}
        <div class="label">Shows</div>
        <div class="seg" role="group" aria-label="When the text shows">${[['clip', 'Whole clip'], ['first3', 'First 3 s']].map(([k, l]) => `<button data-act="tshow" data-k="${k}" aria-pressed="${t.show === k}">${l}</button>`).join('')}</div>
        <div class="label">Position · or drag it on the video <span class="mono" id="tdown" style="letter-spacing:0;text-transform:none">${Math.round(t.y)}% down</span></div>
        <div class="posgrid" role="group" aria-label="Quick position">${cells.map(([x, y]) => `<button data-act="tpos" data-x="${x}" data-y="${y}" aria-pressed="${Math.abs(t.x - x) < 4 && Math.abs(t.y - y) < 4}" aria-label="Position ${x}% across, ${y}% down"><i></i></button>`).join('')}</div>
      </div>
    </div>
    ${foot}`;
}

// ---------- reel order, docked along the bottom (K1: drag with pointer events, or Alt+←/→) ----------
function drawStrip() {
  const r = A.reel, pl = pool();
  $('#striphead').innerHTML = `<span class="ic">${ic('grip')}</span><h3>Reel order · ${RTYPES[r.rtype][0]}</h3><span class="meta mono">${r.entries.length} clips · ${totalLen().toFixed(1)} s</span>
    <span class="meta hide-sm">${multi() ? 'Drag within a section' : 'Drag to reorder'} · the first slot is the hook · Alt+←/→ moves the selected clip · T = shows text</span>
    ${pl.length ? `<button class="btn sm" style="margin-left:auto" data-act="pooltoggle" aria-expanded="${A.poolOpen}">${ic('plus', 'sm')}${pl.length} kept, not in the reel</button>` : ''}`;
  $('#pool').innerHTML = A.poolOpen && pl.length ? `<div class="chips pool">${pl.map(c => `<button class="chip" data-act="add" data-i="${c.index}">${ic('plus', 'sm')}${c.source === 'manual' ? esc(name(c)) : `${c.over}.${c.ball} ${esc(shortLabel(c))}`}</button>`).join('')}</div>` : '';
  let prevSec = null;
  $('#reel').innerHTML = r.entries.map((e, k) => {
    const c = clipBy(e.index); if (!c) return '';
    let pre = '';
    if (multi() && k > 0 && sectionOf(c) !== prevSec) {
      const s = sectionOf(c);
      pre = `<div class="seclbl2">${ic(SEC[s][1], 'sm')}${SEC[s][0]}<small>${r.entries.slice(1).filter(x => sectionOf(clipBy(x.index)) === s).length}</small></div>`;
      prevSec = s;
    }
    const tx = (r.texts[String(e.index)] || []).length;
    return `${pre}<div class="rcard ${k === 0 ? 'hook' : ''} ${e.uid === A.sel ? 'sel' : ''}" data-uid="${e.uid}" tabindex="0" role="listitem" aria-label="${k === 0 ? 'Hook, first 3 seconds. ' : ''}Clip ${k + 1}: ${name(c)}, ${esc(c.label)}. Drag or press Alt+arrow to move.">
      <img src="${thumb(c)}" alt="" draggable="false"><span class="n">${k === 0 ? 'H' : k}</span><span class="tb ${tx ? '' : 'off'}" title="${tx ? 'Shows text' : 'No text'}">T</span><div class="l">${esc(shortLabel(c))}</div><div class="len">${ballTag(c)} · ${clipLen(c).toFixed(1)}s</div></div>`;
  }).join('') || '<p class="muted small" style="padding:8px">No clips in the reel yet. Auto-fill, or add a kept clip.</p>';
}
function afterOrder(msg) { normalize(); A.save.queue(); drawStrip(); drawSettings(); drawHead(); if (msg) toast(msg); }
function moveEntry(uid, to) {
  const es = A.reel.entries, i = es.findIndex(e => e.uid === uid);
  to = clamp(to, 0, es.length - 1);
  if (i < 0 || i === to) return;
  A.hist.push();
  const [e] = es.splice(i, 1); es.splice(to, 0, e);
  afterOrder(); drawFrame(); drawInspector();
  const el = $(`.rcard[data-uid="${uid}"]`); if (el) el.focus();
}
function bindDrag() {
  const strip = $('#reel');
  strip.onpointerdown = e => {
    const card = e.target.closest('.rcard'); if (!card || e.button !== 0) return;
    const uid = card.dataset.uid, x0 = e.clientX;
    let drag = false, mark = null, to = -1;
    const move = ev => {
      if (!drag && Math.abs(ev.clientX - x0) < 6) return;
      if (!drag) { drag = true; card.classList.add('dragging'); strip.setPointerCapture(ev.pointerId); }
      card.style.translate = `${ev.clientX - x0}px 0`;
      const cards = $$('.rcard', strip).filter(c => c !== card);
      to = cards.findIndex(c => { const r = c.getBoundingClientRect(); return ev.clientX < r.left + r.width / 2; });
      if (to < 0) to = cards.length;
      if (!mark) { mark = document.createElement('i'); mark.className = 'dropmark'; }
      if (to < cards.length) cards[to].before(mark); else cards[cards.length - 1].after(mark);
      const r = strip.getBoundingClientRect();
      if (ev.clientX > r.right - 40) strip.scrollLeft += 12; else if (ev.clientX < r.left + 40) strip.scrollLeft -= 12;
    };
    const up = () => {
      strip.removeEventListener('pointermove', move); strip.removeEventListener('pointerup', up); strip.removeEventListener('pointercancel', up);
      if (mark) mark.remove();
      card.classList.remove('dragging'); card.style.translate = '';
      if (drag && to >= 0) { moveEntry(uid, to); toast('Reel order saved'); }
      else select(uid);
    };
    strip.addEventListener('pointermove', move); strip.addEventListener('pointerup', up); strip.addEventListener('pointercancel', up);
  };
}

function select(uid) {
  A.sel = uid; A.selText = (texts()[0] || {}).id || null;
  $$('.rcard').forEach(c => c.classList.toggle('sel', c.dataset.uid === uid));
  if (A.mode !== 'clip') setMode('clip'); else drawFrame();
  drawInspector();
}
function setMode(m) {
  A.mode = m;
  $$('[data-act="mode"]').forEach(b => b.setAttribute('aria-pressed', b.dataset.k === m));
  drawFrame();
}

// ---------- text drag ----------
function bindStage() {
  A.main.addEventListener('pointerdown', e => {
    const el = e.target.closest('.otext'); if (!el) return;
    e.preventDefault();
    const fr = $('#aframe'), R = fr.getBoundingClientRect(), t = texts().find(x => x.id === el.dataset.tid);
    if (A.selText !== t.id) { A.selText = t.id; $$('.otext', fr).forEach(x => x.classList.toggle('sel', x === el)); drawInspector(); }
    A.hist.push();
    const dx = e.clientX - (R.left + t.x / 100 * R.width), dy = e.clientY - (R.top + t.y / 100 * R.height);
    el.setPointerCapture(e.pointerId);
    let hitZone = null;
    el.onpointermove = ev => {
      t.x = clamp((ev.clientX - dx - R.left) / R.width * 100, 0, 100); t.y = clamp((ev.clientY - dy - R.top) / R.height * 100, 0, 100);
      hitZone = fitText(t);
      $$('.zone', fr).forEach(z => z.classList.toggle('hit', z.dataset.z === hitZone));
      el.classList.toggle('bad', !!hitZone && hitZone !== 'edge');
      const d = $('#tdown'); if (d) d.textContent = `${Math.round(t.y)}% down`;
    };
    el.onpointerup = () => {
      el.onpointermove = el.onpointerup = null;
      $$('.zone', fr).forEach(z => z.classList.remove('hit')); el.classList.remove('bad');
      A.save.queue(); drawInspector();
      if (hitZone && hitZone !== 'edge') toast('Stopped at the edge of the keep-away zone');
    };
  });
}

function editText(fn, redraw = true) {
  const t = selText(); if (!t) return;
  A.hist.push(); fn(t); A.save.queue();
  refreshStage(); if (redraw) drawInspector();
}
function addText() {
  const c = curClip(), r = A.reel, prev = selText() || (Object.values(r.texts).flat()[0]);
  const k = r.entries.findIndex(e => e.uid === A.sel), more = texts().length > 0;
  const t = newText(c, k, prev);
  if (more) { t.text = c.label; t.y = 66; }
  A.hist.push(); texts().push(t); A.selText = t.id; A.save.queue(); refreshStage(); drawInspector(); drawStrip(); drawSettings();
  const ta = $('#ttext'); if (ta) { ta.focus(); ta.select(); }
}

// ---------- input ----------
function bind() {
  const main = A.main;
  bindDrag(); bindStage();
  main.addEventListener('click', async e => {
    const b = e.target.closest('[data-act]'); if (!b || b.disabled || b.tagName === 'INPUT') return;
    const act = b.dataset.act, r = A.reel;
    if (act === 'mode') setMode(b.dataset.k);
    else if (act === 'fold') { setFold(b.dataset.k); drawSettings(); }
    else if (act === 'rpick') { if (b.dataset.k !== r.rtype) openReel(b.dataset.k, false); }
    else if (act === 'newreel') { A.newOpen = !A.newOpen; drawHead(); }
    else if (act === 'mkreel') openReel(b.dataset.k, true);
    else if (act === 'delreel') {
      const gone = r.rtype;
      try { await A.save.flush(); const res = await api('DELETE', `/api/matches/${enc(A.id)}/reels/${gone}`); A.reels = A.reels.filter(x => x.rtype !== gone); openReel(res.active, false); toast(`${RTYPES[gone][0]} reel deleted`); } catch (err) { toastErr(err); }
    }
    else if (act === 'pooltoggle') { A.poolOpen = !A.poolOpen; drawStrip(); }
    else if (act === 'secmv') { A.hist.push(); const o = order(), s = b.dataset.s, k = o.indexOf(s), to = k + +b.dataset.d; o.splice(k, 1); o.splice(to, 0, s); r.order = o; afterOrder(`${SEC[s][0]} moved to section ${to + 1}`); }
    else if (act === 'mkhook') {
      const i = r.entries.findIndex(x => x.uid === A.sel); if (i <= 0) return;
      A.hist.push(); const [e2] = r.entries.splice(i, 1); r.entries.unshift(e2);
      afterOrder(`New hook: ${name(clipBy(e2.index))}${multi() ? ` from ${SEC[sectionOf(clipBy(e2.index))][0].toLowerCase()}` : ''}`); select(e2.uid);
    }
    else if (act === 'textall') textAll(b.dataset.v === '1');
    else if (act === 'target') { A.hist.push(); r.target_max = +b.dataset.v; r.target_min = Math.max(5, r.target_max - 15); autoFill(`Auto-filled to about ${r.target_max} s${multi() ? ', shared across the sections' : ''}`); }
    else if (act === 'autopick') { A.hist.push(); autoFill(isBowlField(kinds()) ? 'Clips picked again, in ball order' : 'Clips picked again, biggest first'); }
    else if (act === 'trans') { A.hist.push(); r.trans = b.dataset.k; A.save.queue(); drawSettings(); drawHead(); drawStrip(); toast('Transition set for the whole reel'); }
    else if (act === 'add') { A.hist.push(); const en = { uid: Math.random().toString(16).slice(2, 10), index: +b.dataset.i, trans: null }; r.entries.push(en); afterOrder('Added to the end of the reel'); select(en.uid); }
    else if (act === 'remove') {
      const i = r.entries.findIndex(x => x.uid === A.sel); if (i < 0) return;
      A.hist.push(); const [gone] = r.entries.splice(i, 1);
      afterOrder(); select((r.entries[Math.min(i, r.entries.length - 1)] || {}).uid);
      toast(`${name(clipBy(gone.index))} taken out`, { undo: () => { r.entries.splice(i, 0, gone); afterOrder(); select(gone.uid); } });
    }
    else if (act === 'render') renderPreview();
    else if (act === 'seltext') { A.selText = b.dataset.tid; refreshStage(); drawInspector(); }
    else if (act === 'addtext') addText();
    else if (act === 'tshowtext') {
      const ts = texts();
      if (!ts.length) { addText(); return; }
      const key = String(curClip().index), was = ts.slice();
      A.hist.push(); r.texts[key] = []; A.selText = null; A.save.queue(); refreshStage(); drawInspector(); drawStrip(); drawSettings();
      toast('Text taken off this clip', { undo: () => { r.texts[key] = was; A.selText = was[0].id; A.save.queue(); refreshStage(); drawInspector(); drawStrip(); drawSettings(); } });
    }
    else if (act === 'rmtext') {
      const ts = texts(), k = ts.findIndex(t => t.id === A.selText); if (k < 0) return;
      A.hist.push(); const [gone] = ts.splice(k, 1); A.selText = (ts[0] || {}).id || null; A.save.queue(); refreshStage(); drawInspector(); drawStrip();
      toast('Text removed', { undo: () => { ts.splice(k, 0, gone); A.selText = gone.id; A.save.queue(); refreshStage(); drawInspector(); drawStrip(); } });
    }
    else if (act === 'tstyle') editText(t => { t[b.dataset.k] = !t[b.dataset.k]; });
    else if (act === 'tcolor') editText(t => { t.color = b.dataset.c; });
    else if (act === 'tbg') editText(t => { t.bg = b.dataset.k; });
    else if (act === 'tshow') editText(t => { t.show = b.dataset.k; });
    else if (act === 'tpos') editText(t => { t.x = +b.dataset.x; t.y = +b.dataset.y; });
    else if (act === 'tall') {
      const s = selText(); A.hist.push();
      Object.values(r.texts).flat().forEach(t => { if (t !== s) STYLE_KEYS.forEach(k => { t[k] = s[k]; }); });
      A.save.queue(); toast('Font, size, colour and background copied to every clip. Positions stay per clip.');
    }
  });
  main.addEventListener('input', e => {
    const t = e.target;
    if (t.id === 'ttext') { const s = selText(); s.text = t.value; const el = $(`.otext[data-tid="${s.id}"]`); if (el) { el.textContent = t.value; fitText(s); } A.save.queue(); const chip = $(`[data-act="seltext"][data-tid="${s.id}"]`); if (chip) chip.textContent = (t.value.split('\n')[0] || 'Text').slice(0, 14); }
    else if (t.id === 'tsize') { t.style.setProperty('--p', (t.value - 3) / 13 * 100 + '%'); t.nextElementSibling.textContent = t.value; const s = selText(); s.size = +t.value; refreshStage(); A.save.queue(); }
    else if (t.id === 'tbo') { t.style.setProperty('--p', (t.value - .1) / .9 * 100 + '%'); t.nextElementSibling.textContent = Math.round(t.value * 100) + '%'; const s = selText(); s.bo = +t.value; refreshStage(); A.save.queue(); }
  });
  main.addEventListener('focusin', e => { if (['ttext', 'tsize', 'tbo'].includes(e.target.id)) A.hist.push(); });
  main.addEventListener('change', e => {
    const t = e.target, r = A.reel;
    if (t.id === 'tfont') editText(s => { s.font = t.value; }, false);
    else if (t.dataset.set) { A.hist.push(); r[t.dataset.set] = t.checked; A.save.queue(); drawSettings(); drawHead(); drawStrip(); }
    else if (t.dataset.act === 'zones') { A.zones = t.checked; refreshStage(); }
  });
}

/** Auto-fill (and the target chips): the backend picks; a Bowling + Fielding reel comes back in ball order. */
async function autoFill(msg) {
  try {
    await A.save.flush();
    const res = await api('POST', `/api/matches/${enc(A.id)}/reel/auto?rtype=${enc(A.reel.rtype)}`);
    A.reel.entries = res.reel.entries;
    A.sel = A.reel.entries[0] && A.reel.entries[0].uid;
    afterOrder(msg); select(A.sel);
  } catch (err) { toastErr(err); }
}

async function renderPreview() {
  try {
    await A.save.flush();
    const j = await api('POST', `/api/matches/${enc(A.id)}/render-preview`);
    kickJobs();
    const draw = x => { const cap = $('#acap'); if (A.mode === 'reel' && cap) cap.innerHTML = isActive(x) ? `<span class="spin"></span> Rendering ${Math.floor((x.progress || 0) * 100)}%` : x.status === 'done' ? `${ic('check', 'sm')} Rendered` : esc(x.error || 'Render stopped'); };
    draw(j);
    if (A.stop) A.stop();
    A.stop = follow(j.id, x => { draw(x); if (!isActive(x)) { A.stop = null; kickJobs(); if (x.status === 'done') { toast('Reel preview rendered'); if (A.mode === 'reel') drawFrame(); } else if (x.status === 'failed') toastErr(new Error(x.error || 'The preview render failed.')); } });
  } catch (err) { toastErr(err); }
}

function onKey(e) {
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'z') {
    e.preventDefault();
    if (!(e.shiftKey ? A.hist.redo() : A.hist.undo())) return toast(e.shiftKey ? 'Nothing to redo' : 'Nothing to undo');
    if (!A.reel.entries.some(x => x.uid === A.sel)) A.sel = (A.reel.entries[0] || {}).uid;
    if (!selText()) A.selText = (texts()[0] || {}).id || null;
    A.save.queue(); drawHead(); drawSettings(); drawStrip(); drawFrame(); drawInspector(); return;
  }
  const es = A.reel.entries, i = es.findIndex(x => x.uid === A.sel);
  if (e.altKey && (e.key === 'ArrowLeft' || e.key === 'ArrowRight')) { e.preventDefault(); moveEntry(A.sel, i + (e.key === 'ArrowLeft' ? -1 : 1)); }
  else if (!e.altKey && (e.key === 'ArrowLeft' || e.key === 'ArrowRight') && es.length) { e.preventDefault(); select(es[clamp(i + (e.key === 'ArrowLeft' ? -1 : 1), 0, es.length - 1)].uid); }
  else if (e.key === 'Delete' && A.sel) { e.preventDefault(); $('[data-act="remove"]', A.main).click(); }
}
