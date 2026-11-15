// Score sheet check: the original (Spawtz page or photo) beside an editable grid. Totals are checked as you type;
// amber cells are ones Claude wasn't sure about (fix them, or press Enter to confirm). Ctrl+Z undoes.
import { api, clearPending, setPending } from './core/api.js';
import { createHistory } from './core/state.js';
import { esc } from './core/util.js';
import { $, $$, confirmSheet, head, ic, toast, toastErr } from './ui.js';
import { saving, shell, stepLabel } from './shell.js';

let S = null;
const intOrNull = v => { const n = parseInt(String(v).trim(), 10); return Number.isFinite(n) ? n : null; };
const enc = encodeURIComponent;

export async function prepare([id]) {
  const full = await api('GET', `/api/matches/${enc(id)}`);
  if (!full.scorecard) { location.replace('#import/' + enc(id)); return false; }
  shell.match = full.match; shell.step = 'import';
  return { full };
}

export async function mount(main, { full }) {
  S = { main, id: full.match.id, match: full.match, sc: full.scorecard, v: full.validation, timer: 0, seq: 0, burst: false, before: null,
    tab: 'fielding', catches: new Set(full.match.my_catches || []) };
  S.hist = createHistory(() => S.sc, x => { S.sc = x; });
  main.style.setProperty('--accent', 'var(--blue)');
  render();
  bind();
  api('GET', '/api/tokens').then(t => { const el = $('#codes'); if (el) el.textContent = `Codes: ${t.runs.min}–${t.runs.max} runs · ${Object.keys(t.dismissals).join(' ')} = out (−${Math.abs(t.wicket_penalty)}) · ${Object.keys(t.extras).join(', ')} = extras`; }).catch(() => {});
  return {
    context: () => `Score sheet · ${S.v && S.v.ok ? 'adds up' : (S.v && S.v.errors[0]) || ''}`,
    key: e => { if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'z') { e.preventDefault(); e.shiftKey ? redo() : undo(); } },
    unmount: () => { if (S.timer) { clearTimeout(S.timer); persist(); } },
  };
}

function undo() { if (!S.hist.undo()) return toast('Nothing to undo'); render(); persist(); toast('Undone'); }
function redo() { if (!S.hist.redo()) return toast('Nothing to redo'); render(); persist(); toast('Redone'); }

// One undo step per burst of typing; the save goes out 350 ms after the last key.
function snapshot() { if (!S.burst) S.before = JSON.stringify(S.sc); }
function changed() {
  if (!S.burst) { const cur = S.sc; S.sc = JSON.parse(S.before || JSON.stringify(cur)); S.hist.push(); S.sc = cur; S.burst = true; } // undo returns to before the burst
  clearTimeout(S.timer); saving('saving');
  setPending('sheet', 'PUT', `/api/matches/${enc(S.id)}/scorecard`, () => ({ scorecard: S.sc }));
  S.timer = setTimeout(() => { S.timer = 0; S.burst = false; persist(); }, 350);
}
async function persist(confirm = false) {
  clearPending('sheet');
  const seq = ++S.seq;
  try {
    const r = await api('PUT', `/api/matches/${enc(S.id)}/scorecard`, { scorecard: S.sc, confirm });
    if (seq !== S.seq && !confirm) return r;
    S.v = r.validation; status(); saving('saved');
    return r;
  } catch (e) { saving('error'); toastErr(e); throw e; }
}

function overHtml(o, oi) {
  const sc = S.sc;
  const cells = f => o.balls.map((b, bi) => {
    const has = b.facer === f, u = has && b.unsure;
    return `<td class="${u ? 'unsure' : ''}" ${u ? `title="${esc(b.note || 'Claude was unsure about this cell')}. Fix it, or press Enter to confirm."` : ''}><input type="text" class="${has ? 'has' : ''}" value="${has ? esc(b.code) : ''}" data-o="${oi}" data-b="${bi}" data-f="${f}" maxlength="5" autocomplete="off" spellcheck="false" aria-label="Over ${o.number} ball ${bi + 1}, ${esc(f === 'me' ? sc.batter.name : sc.partner.name)}${u ? ', unsure' : ''}"></td>`;
  }).join('');
  return `<section class="card a-blue oblock" id="ob${oi}" style="--i:${oi + 2}">
    <div class="card-head"><span class="ic mono" style="font-weight:700">${o.number}</span>
      <label class="cap muted" style="display:flex;gap:6px;align-items:center">Over <input type="text" value="${o.number}" data-ofield="number" data-o="${oi}" style="width:52px" aria-label="Over number"></label>
      <label class="cap muted" style="display:flex;gap:6px;align-items:center">Bowler <input type="text" value="${esc(o.bowler || '')}" data-ofield="bowler" data-o="${oi}" style="width:150px" aria-label="Bowler"></label>
      <label class="cap muted" style="display:flex;gap:6px;align-items:center">Sheet total <input type="text" inputmode="numeric" value="${o.total_sheet ?? ''}" data-ofield="total_sheet" data-o="${oi}" style="width:56px" aria-label="Over total written on the sheet"></label>
      <span class="obsum" style="margin-left:auto"></span>
      <button class="btn icon sm ghost" data-act="delover" data-o="${oi}" title="Remove over" aria-label="Remove over ${o.number}">${ic('trash', 'sm')}</button></div>
    <div class="obwrap"><table class="ob"><thead><tr><th></th>${o.balls.map((_, bi) => `<th>${bi + 1}</th>`).join('')}<th></th></tr></thead>
      <tbody><tr><th class="me">${esc(sc.batter.name)} (you)</th>${cells('me')}<td rowspan="2"><button class="add" data-act="addball" data-o="${oi}" title="Add a delivery" aria-label="Add a delivery to over ${o.number}">${ic('plus', 'sm')}</button></td></tr>
      <tr><th>${esc(sc.partner.name)}</th>${cells('partner')}</tr></tbody></table></div>
  </section>`;
}

function render() {
  const sc = S.sc, m = sc.match || {}, url = S.match.sheet && S.match.sheet.url;
  const field = (k, label, cls = '') => `<label class="field ${cls}"><span>${label}</span><input type="text" ${k.startsWith('total') ? 'inputmode="numeric"' : ''} data-mfield="${k}" value="${esc(m[k] ?? '')}"></label>`;
  S.main.innerHTML = `${head(stepLabel('import', 'Score sheet'), 'Check the score sheet', url
      ? 'Imported from Spawtz: every ball was copied exactly. Check your balls are in your row; totals update as you type.'
      : `Fix any cell Claude got wrong; totals update as you type. Amber cells are ones it wasn't sure about: fix them or press Enter to confirm. Read by <span class="mono">${esc(sc.model || 'hand entry')}</span>.`,
    `<a class="btn sm" href="#import/${enc(S.id)}">${ic('film', 'sm')}Videos (${S.match.videos.length})</a><button class="btn sm" data-act="swap" title="Use if your balls ended up in your partner's row">${ic('swap', 'sm')}Swap me and partner</button><button class="btn sm" data-act="reread">${ic('refresh', 'sm')}${url ? 'Import again' : 'Read again'}</button>`)}
    <div class="sheet-layout">
      <section class="card a-blue sheet-orig" style="--i:0">
        <div class="card-head"><span class="ic">${ic(url ? 'link' : 'image')}</span><h3>Original sheet</h3>${url ? `<a class="btn sm ghost" href="${esc(url)}" target="_blank" rel="noopener noreferrer">Open on Spawtz ${ic('ext', 'sm')}</a>` : '<span class="meta">Click to zoom</span>'}</div>
        ${url ? '<div class="frame" id="sheetframe"><iframe sandbox title="Original score sheet"></iframe></div>' : `<div class="photo" id="sheetimg"><img src="/api/matches/${enc(S.id)}/sheet-image" alt="Score sheet photo"></div>`}
      </section>
      <div style="display:flex;flex-direction:column;gap:var(--gap);min-width:0">
        ${sc.notes ? `<div class="note">${ic('info', 'sm')}<span><b>${url ? 'Source' : "Claude's notes"}:</b> ${esc(sc.notes)}</span></div>` : ''}
        <section class="card a-purple" style="--i:1"><div class="card-head"><span class="ic">${ic('info')}</span><h3>Match details</h3></div>
          <div class="mgrid">${field('team_us', 'Our team')}${field('total_us', 'Total')}${field('team_them', 'Opponent')}${field('total_them', 'Total')}
            ${field('result', 'Result', 'wide')}${field('player_of_match', 'Player of the match')}${field('date', 'Date (YYYY-MM-DD)')}</div></section>
        ${(sc.innings || []).length ? `<section class="card a-blue" style="--i:2" id="innings"></section>
        <div class="grid"><section class="card a-blue span-6" style="--i:3" id="inchecks"></section><section class="card a-pink span-6" style="--i:4" id="figs"></section></div>
        <section class="card a-pink" style="--i:5" id="wlist"></section>
        <div class="label" style="margin-top:4px">Your pair's overs (batting clips)</div>` : ''}
        <p class="cap muted mono" id="codes"></p>
        <div id="overs" style="display:flex;flex-direction:column;gap:var(--gap)">${sc.overs.map(overHtml).join('')}</div>
        <div><button class="btn sm" data-act="addover">${ic('plus', 'sm')}Add over</button></div>
        <section class="card a-green" style="--i:9" id="battot"></section>
      </div>
    </div>
    <div class="actionbar"><span class="msg" id="sheetmsg"></span><button class="btn" id="contanyway" data-act="confirmAnyway" hidden>Continue anyway</button><button class="btn primary" id="sheetok" data-act="confirm">${['synced', 'review', 'arrange', 'look', 'exported', 'described'].includes(S.match.step) ? 'Save and re-sync' : 'Looks right · sync'} ${ic('chev')}</button></div>`;
  const sf = $('#sheetframe');
  if (sf) {
    // The Spawtz page is about 1000 px wide: zoom it to the panel. Sandboxed with no permissions, so it can't run scripts.
    const fit = () => { const f = sf.firstElementChild, s = sf.clientWidth / 1060; f.style.zoom = s; f.style.height = (sf.clientHeight / s) + 'px'; }; // zoom, not transform: a scaled iframe inside a card paints blank
    fit(); new ResizeObserver(fit).observe(sf);
    fetch(`/api/matches/${enc(S.id)}/sheet-html`).then(r => r.ok ? r.text() : '').then(h => { sf.firstElementChild.srcdoc = h; }).catch(() => {});
  }
  status();
}

// ---------- 2.1: both innings ----------
const sameName = (a, b) => (a || '').toLowerCase().replace(/[^a-z ]/g, '').trim() === (b || '').toLowerCase().replace(/[^a-z ]/g, '').trim();
const isWkt = c => /^(c|b|r|s|st)$/i.test(String(c || '').trim());
function inningsCard() {
  const box = $('#innings'); if (!box) return;
  const inns = S.sc.innings, ii = Math.max(0, inns.findIndex(i => i.side === S.tab)), inn = inns[ii], vi = S.v.innings && S.v.innings.innings[ii];
  const maxB = Math.max(6, ...inn.overs.map(o => o.balls.length)), me = S.sc.batter.name;
  box.innerHTML = `<div class="card-head" style="flex-wrap:wrap"><div class="seg" role="tablist" aria-label="Innings">${inns.map(i => `<button role="tab" data-act="itab" data-k="${i.side}" aria-pressed="${i.side === inn.side}" aria-selected="${i.side === inn.side}">${ic(i.side === 'batting' ? 'bat' : 'ball', 'sm')}${i.side === 'batting' ? 'Our innings' : 'Their innings'} · <span class="mono">${i.total ?? '–'}</span></button>`).join('')}</div>
      <span class="meta" style="margin-left:auto">Batting: ${esc(inn.team)}${inn.side === 'fielding' ? ' · you fielded' : ''}${inn.batted_first ? ' · batted first' : ''}</span></div>
    <div class="tablewrap"><table class="sheetgrid"><thead><tr><th>Over</th><th>Bowler</th>${Array.from({ length: maxB }, (_, i) => `<th>${i + 1}</th>`).join('')}<th>W/R</th></tr></thead><tbody>
    ${inn.overs.map((o, k) => { const mine = inn.side === 'fielding' && sameName(o.bowler, me), vo = vi && vi.overs[k];
      return `<tr class="${mine ? 'mine' : ''}"><th class="mono">${o.number}</th><th><span class="bw">${esc(o.bowler)}${mine ? '<span class="youtag">You</span>' : ''}</span></th>
        ${Array.from({ length: maxB }, (_, bi) => { const b = o.balls[bi]; if (!b) return '<td class="empty"></td>';
          const w = isWkt(b.code), meBat = inn.side === 'batting' && sameName(b.batter, me);
          return `<td class="cell ${w ? 'wk' : ''} ${w && mine ? 'myw' : ''} ${inn.side === 'batting' ? (meBat ? 'me' : 'pt') : ''}"><input type="text" value="${esc(b.code)}" data-ii="${ii}" data-io="${k}" data-ib="${bi}" maxlength="4" autocomplete="off" spellcheck="false" title="${esc(b.batter)}" aria-label="${inn.side === 'batting' ? 'Our' : 'Their'} innings over ${o.number} ball ${bi + 1}, ${esc(b.batter)}"></td>`; }).join('')}
        <td class="foot ${vo && !vo.ok ? 'bad' : ''}" id="foot${ii}_${k}" title="${vo && !vo.ok ? `The codes show ${vo.wkts_codes} wicket(s); the footer says ${o.wkts}` : 'Wickets / runs in the footer'}">${o.wkts ?? '–'}/${o.runs ?? '–'}</td></tr>`; }).join('')}
    </tbody></table></div>
    <div class="sheetkey"><span><i style="background:color-mix(in srgb,var(--wicket) 30%,var(--raised))"></i>Wicket</span>${inn.side === 'fielding' ? '<span><i style="box-shadow:inset 3px 0 0 var(--blue);background:var(--raised)"></i>Your over</span><span><i style="background:color-mix(in srgb,var(--wicket) 30%,var(--raised));box-shadow:inset 0 0 0 1px var(--wicket)"></i>Wicket in your over = bowling clip</span>' : '<span><i style="background:color-mix(in srgb,var(--blue) 25%,var(--raised))"></i>Your ball</span>'}<span class="mono">W/R = wickets / runs in the footer</span></div>`;
}
function inningsSide() {
  const v = S.v.innings; if (!v) return;
  const vrow = (ok, txt, val) => `<div class="vrow ${ok ? '' : 'bad'}"><span class="vi">${ic(ok ? 'check' : 'alert', 'sm')}</span><span>${txt}</span><span class="vv">${val}</span></div>`;
  const b = v.bowling, tb = b.table;
  $('#inchecks').innerHTML = `<div class="card-head"><span class="ic">${ic('shield')}</span><h3>Checks</h3>${v.ok ? pillOk('All pass') : pillBad('Needs a look')}</div>
    ${v.innings.map(i => `<div class="label" style="margin-top:6px">${i.side === 'batting' ? 'Our innings' : 'Their innings'}</div><div class="vlist">
      ${vrow(i.overs_ok === i.overs.length, 'Wicket codes match every footer', `${i.overs_ok}/${i.overs.length}`)}
      ${vrow(i.sum_ok, 'Footers add up to the total', `${i.footer_sum} / ${i.total ?? '–'}`)}</div>`).join('')}
    ${vrow(b.ok, 'Your figures match the bowling table', `${b.wkts}/${b.runs}${tb ? ` · ${tb.wkts}/${tb.runs}` : ' · no table'}`)}`;
  const mineW = v.wickets.filter(w => w.role === 'bowling');
  $('#figs').innerHTML = `<div class="card-head"><span class="ic">${ic('user')}</span><h3>Your figures</h3>${b.ok ? pillOk('Match the table') : pillBad("Don't match")}</div>
    <div class="figs"><div class="howstep"><div class="k">Overs</div><div class="v">${b.overs.length}</div><div class="s">${b.overs.join(' and ') || '–'}</div></div>
      <div class="howstep"><div class="k">Runs</div><div class="v">${b.runs}</div><div class="s">conceded</div></div>
      <div class="howstep"><div class="k">Wickets</div><div class="v">${b.wkts}</div><div class="s">${mineW.map(w => esc(w.how)).join(', ') || '–'}</div></div>
      <div class="howstep"><div class="k">Econ</div><div class="v">${b.overs.length ? (b.runs / b.overs.length).toFixed(1) : '–'}</div><div class="s">${tb ? 'Table ' + tb.runs + ' off ' + tb.overs : ''}</div></div></div>
    <div class="label">Catches you took · <span class="mono">${S.catches.size}</span></div>
    <div class="chips">${v.wickets.filter(w => w.how === 'caught').map(w => `<button class="chip" data-act="mycatch" data-id="${w.id}" aria-pressed="${S.catches.has(w.id)}">${S.catches.has(w.id) ? ic('check', 'sm') : ''}${w.id} ${esc(w.batter.split(' ')[0])}</button>`).join('') || '<span class="cap muted">No catches on the sheet.</span>'}</div>
    <p class="cap muted" style="margin-top:6px">The sheet doesn't say who caught. Tick yours; you can change them in Review too. They go into the fielding header card and the descriptions.</p>`;
  $('#wlist').innerHTML = `<div class="card-head"><span class="ic">${ic('ball')}</span><h3>Wickets your team took</h3><span class="meta mono">${v.wickets.length} · ${mineW.length} bowling · ${v.wickets.length - mineW.length} fielding</span></div>
    <div class="wlist"><div class="wrow head"><span>Ball</span><span>Out</span><span class="how">How</span><span class="bw">Bowler</span><span class="kc">Clip</span></div>
    ${v.wickets.map(w => `<div class="wrow ${w.role === 'bowling' ? 'mine' : ''}"><span class="bn">${w.id}</span><span class="nm">${esc(w.batter)}${S.catches.has(w.id) ? ' · <b>your catch</b>' : ''}</span><span class="how">${esc(w.how)}</span><span class="bw">${esc(w.bowler)}${w.role === 'bowling' ? ' (you)' : ''}</span><span class="kc"><span class="pill kind">${ic(w.role === 'bowling' ? 'ball' : 'hand')}${w.role === 'bowling' ? 'Bowling' : 'Fielding'}</span></span></div>`).join('')}</div>
    <p class="cap muted" style="margin-top:10px">A wicket is <b>Bowling</b> when you bowled the over and <b>Fielding</b> for every other wicket, bowled ones included. You can change the kind of any clip in Review.</p>`;
}
const pillOk = t => `<span class="pill keep"><span class="d"></span>${t}</span>`;
const pillBad = t => `<span class="pill check"><span class="d"></span>${t}</span>`;
async function saveCatches() {
  try { const r = await api('PUT', `/api/matches/${enc(S.id)}/catches`, { ids: [...S.catches] }); S.catches = new Set(r.my_catches); } catch (e) { toastErr(e); }
}

function battot() {
  const sc = S.sc, v = S.v;
  const row = (k, label) => {
    const b = v[k], info = sc[k];
    return `<div class="btotal"><input class="nm" type="text" data-bfield="${k}.name" value="${esc(info.name)}" aria-label="${label} name">${k === 'batter' ? '<span class="cap muted">(you)</span>' : ''}
      <span class="calc ${b.ok ? 'good' : 'bad'}" data-calc="${k}">${ic(b.ok ? 'check' : 'alert', 'sm')}<span>${b.calc_runs} (${b.calc_balls})</span></span>
      <span class="cap muted" style="margin-left:auto">Sheet says</span><input type="text" inputmode="numeric" data-bfield="${k}.runs_sheet" value="${info.runs_sheet ?? ''}" aria-label="${label} runs on the sheet"><span class="muted">(</span><input type="text" inputmode="numeric" data-bfield="${k}.balls_sheet" value="${info.balls_sheet ?? ''}" style="width:52px" aria-label="${label} balls on the sheet"><span class="muted">)</span></div>`;
  };
  return `<div class="card-head"><span class="ic">${ic('user')}</span><h3>Batter totals</h3></div>${row('batter', 'Your')}${row('partner', 'Partner')}<p class="cap muted" style="margin-top:6px">Balls faced leave out no-balls and wides.</p>`;
}

function status() {
  const v = S.v; if (!v) return;
  v.overs.forEach((o, oi) => {
    const blk = $('#ob' + oi); if (!blk) return;
    blk.classList.toggle('bad', !o.ok);
    const t = $('.obsum', blk);
    t.className = 'obsum ' + (o.ok ? (o.sheet == null ? '' : 'good') : 'bad');
    t.innerHTML = `${o.ok ? (o.sheet == null ? '' : ic('check', 'sm')) : ic('alert', 'sm')}Adds to <b class="mono">${o.calc}</b>${o.sheet == null ? ' · no total on the sheet' : ` · sheet <b class="mono">${o.sheet}</b>`}${o.legal_balls < 6 ? ` · only ${o.legal_balls} legal balls` : ''}`;
  });
  $$('#overs td').forEach(td => { td.classList.remove('invalid'); });
  v.cells.forEach(c => { const inp = $(`#overs input[data-o="${c.over}"][data-b="${c.ball}"].has`) || $(`#overs input[data-o="${c.over}"][data-b="${c.ball}"][data-f="me"]`); if (inp) { inp.parentElement.classList.add('invalid'); inp.parentElement.title = c.error; } });
  const bt = $('#battot');
  if (!bt.dataset.built) { bt.innerHTML = battot(); bt.dataset.built = '1'; }
  else ['batter', 'partner'].forEach(k => { const b = v[k], el = $(`[data-calc="${k}"]`, bt); el.className = 'calc ' + (b.ok ? 'good' : 'bad'); el.innerHTML = `${ic(b.ok ? 'check' : 'alert', 'sm')}<span>${b.calc_runs} (${b.calc_balls})</span>`; });
  if ($('#innings')) {
    if (!$('#innings').dataset.built) { inningsCard(); $('#innings').dataset.built = '1'; }
    else if (v.innings) {    // update the footers in place, so typing in a cell keeps its focus
      const ii = S.sc.innings.findIndex(i => i.side === S.tab), vi = v.innings.innings[ii];
      vi.overs.forEach((o, k) => { const f = $(`#foot${ii}_${k}`); if (f) f.classList.toggle('bad', !o.ok); });
      $$('#innings td.cell input').forEach(inp => { inp.parentElement.classList.toggle('wk', isWkt(inp.value)); });
    }
    inningsSide();
  }
  const msg = $('#sheetmsg');
  msg.className = 'msg ' + (v.ok ? 'good' : 'bad');
  msg.innerHTML = v.ok ? `${ic('check', 'sm')}<span>Everything adds up${v.unsure ? ` · ${v.unsure} unsure cell${v.unsure > 1 ? 's' : ''} left (totals not affected)` : ''}</span>`
    : `${ic('alert', 'sm')}<span>${esc(v.errors[0] || "Something doesn't add up")}${v.errors.length > 1 ? ` · ${v.errors.length - 1} more` : ''}</span>`;
  $('#sheetok').disabled = !v.ok;
  $('#contanyway').hidden = v.ok;
}

function rerenderOver(oi) {
  const blk = $('#ob' + oi), tmp = document.createElement('div');
  tmp.innerHTML = overHtml(S.sc.overs[oi], oi);
  tmp.firstElementChild.style.animation = 'none';
  blk.replaceWith(tmp.firstElementChild);
  status();
}

function bind() {
  const main = S.main;
  main.addEventListener('focusin', snapshot);
  main.addEventListener('input', e => {
    const t = e.target, sc = S.sc;
    if (t.dataset.mfield) { const k = t.dataset.mfield; sc.match[k] = k.startsWith('total') ? intOrNull(t.value) : t.value; }
    else if (t.dataset.bfield) { const [k, f] = t.dataset.bfield.split('.'); sc[k][f] = f === 'name' ? t.value : intOrNull(t.value); }
    else if (t.dataset.ofield) { const o = sc.overs[+t.dataset.o], f = t.dataset.ofield; o[f] = f === 'bowler' ? t.value : intOrNull(t.value); if (f === 'number' && o.number == null) o.number = +t.dataset.o + 1; }
    else if (t.dataset.ii != null) { const b = sc.innings[+t.dataset.ii].overs[+t.dataset.io].balls[+t.dataset.ib]; b.code = t.value.trim(); }
    else if (t.dataset.b != null) {
      const b = sc.overs[+t.dataset.o].balls[+t.dataset.b], val = t.value.trim();
      if (val) {
        b.code = val; b.facer = t.dataset.f; b.unsure = false; b.note = '';
        const other = $(`#overs input[data-o="${t.dataset.o}"][data-b="${t.dataset.b}"]:not([data-f="${t.dataset.f}"])`);
        if (other) { other.value = ''; other.classList.remove('has'); other.parentElement.classList.remove('unsure'); }
        t.classList.add('has'); t.parentElement.classList.remove('unsure'); t.parentElement.removeAttribute('title');
      } else if (b.facer === t.dataset.f) b.code = '';
    } else return;
    changed();
  });
  main.addEventListener('focusout', e => {
    const t = e.target; if (t.dataset.b == null) return;
    const o = S.sc.overs[+t.dataset.o], b = o && o.balls[+t.dataset.b];
    if (b && !b.code.trim()) setTimeout(() => { // both cells empty → the delivery goes
      const a = document.activeElement, same = a && a.dataset && a.dataset.o === t.dataset.o && a.dataset.b === t.dataset.b;
      if (o.balls[+t.dataset.b] === b && !b.code.trim() && !same) { snapshot(); o.balls.splice(+t.dataset.b, 1); rerenderOver(+t.dataset.o); changed(); }
    }, 0);
  });
  main.addEventListener('keydown', e => {
    const t = e.target;
    if (e.key === 'Enter' && t.dataset.b != null) {
      e.preventDefault();
      const b = S.sc.overs[+t.dataset.o].balls[+t.dataset.b];
      if (b && b.unsure && b.facer === t.dataset.f) { snapshot(); b.unsure = false; b.note = ''; t.parentElement.classList.remove('unsure'); t.parentElement.removeAttribute('title'); changed(); toast('Cell confirmed'); }
    }
  });
  main.addEventListener('click', async e => {
    const si = e.target.closest('#sheetimg'); if (si) { si.classList.toggle('zoom'); return; }
    const b = e.target.closest('[data-act]'); if (!b || b.disabled) return;
    const act = b.dataset.act, sc = S.sc;
    if (act === 'itab') { S.tab = b.dataset.k; inningsCard(); return; }
    if (act === 'mycatch') { const id = b.dataset.id; if (S.catches.has(id)) S.catches.delete(id); else S.catches.add(id); inningsSide(); saveCatches(); toast(S.catches.has(id) ? `${id} marked as your catch · ${S.catches.size} in all` : `${id} isn't your catch now`); return; }
    if (act === 'addball') {
      snapshot(); const oi = +b.dataset.o;
      sc.overs[oi].balls.push({ facer: 'me', code: '', unsure: false, note: '' });
      rerenderOver(oi); $(`#overs input[data-o="${oi}"][data-b="${sc.overs[oi].balls.length - 1}"][data-f="me"]`).focus(); changed();
    } else if (act === 'addover') {
      snapshot(); const last = sc.overs[sc.overs.length - 1];
      sc.overs.push({ number: last ? last.number + 1 : 1, bowler: '', total_sheet: null, balls: [] }); render(); changed();
    } else if (act === 'delover') {
      const oi = +b.dataset.o; snapshot(); const before = S.before;
      const [gone] = sc.overs.splice(oi, 1); render(); changed();
      toast(`Over ${gone.number} removed`, { undo: () => { S.before = before; sc.overs.splice(oi, 0, gone); render(); changed(); } });
    } else if (act === 'swap') {
      snapshot(); [sc.batter, sc.partner] = [sc.partner, sc.batter];
      sc.overs.forEach(o => o.balls.forEach(x => { x.facer = x.facer === 'me' ? 'partner' : 'me'; }));
      render(); changed(); toast(`You are now ${sc.batter.name}`);
    } else if (act === 'reread') {
      const u = S.match.sheet && S.match.sheet.url;
      if (await confirmSheet(u ? 'Import the sheet again?' : 'Read the sheet again?', `${u ? 'The page is downloaded again from Spawtz' : 'Claude reads the photo from scratch'} and your edits here are replaced. Ctrl+Z brings them back.`, u ? 'Import again' : 'Read again')) reread();
    } else if (act === 'confirm' || act === 'confirmAnyway') {
      clearTimeout(S.timer); S.timer = 0; S.burst = false; b.disabled = true;
      try {
        await persist(true);
        if (!S.match.videos.length) { toast('Score sheet saved. Add the match video to sync it.'); location.hash = '#import/' + enc(S.id); return; }
        await api('POST', `/api/matches/${enc(S.id)}/sync`, {});
        location.hash = '#sync/' + enc(S.id);
      } catch (err) { b.disabled = false; toastErr(err); }
    }
  });
}

async function reread() {
  const u = S.match.sheet && S.match.sheet.url, msg = $('#sheetmsg');
  msg.className = 'msg'; msg.innerHTML = `<span class="spin"></span><span>${u ? 'Importing the score sheet again…' : 'Reading the score sheet again (20–60 s)…'}</span>`;
  try {
    const full = u ? await api('POST', `/api/matches/${enc(S.id)}/import-url`, { url: u }) : await api('POST', `/api/matches/${enc(S.id)}/read-sheet`);
    S.hist.push(); S.sc = full.scorecard; S.v = full.validation; S.match = full.match; shell.match = full.match;
    if (full.match.id !== S.id) { S.id = full.match.id; history.replaceState(null, '', '#sheet/' + enc(S.id)); }
    const ib = $('#innings'); if (ib) delete ib.dataset.built;
    render(); toast(u ? 'Imported again' : 'Read again');
  } catch (e) { status(); toastErr(e); }
}
