// The library: every match, newest first, with its next step. Tap a match to carry on where you left off.
import { api } from './core/api.js';
import { auDate, esc, money } from './core/util.js';
import { $, $$, confirmSheet, countUp, head, ic, note, pill, toast, toastErr } from './ui.js';
import { shell } from './shell.js';

const NEXT = {
  import: ['Next: add the files', 'check', id => `#import/${id}`],
  sheet: ['Next: check the score sheet', 'check', id => `#sheet/${id}`],
  sync: ['Next: sync the video', 'teal', id => `#sync/${id}`],
  synced: ['Synced · next: review', 'teal', id => `#review/${id}`],
  review: ['Reviewing clips', 'keep', id => `#review/${id}`],
  arrange: ['Arranging the reel', 'big', id => `#arrange/${id}`],
  look: ['Arranged · next: export', 'big', id => `#export/${id}`],  // 2.2: the old Look step counts as arranged
  exported: ['Exported · next: descriptions', 'keep', id => `#describe/${id}`],
  described: ['Exported · descriptions written', 'purple', id => `#describe/${id}`],
};
const ACCENTS = ['a-blue', 'a-teal', 'a-green', 'a-amber', 'a-purple', 'a-pink'];

export async function prepare() {
  shell.title = '';
  const [list, usage] = await Promise.all([api('GET', '/api/matches'), api('GET', '/api/usage').catch(() => null)]);
  return { list, usage };
}

// 2.1: a badge for each kind of clip the match has (a kind it doesn't have is a faded, dashed badge)
const KB = [['batting', 'Bat', 'bat'], ['bowling', 'Bowl', 'ball'], ['fielding', 'Field', 'hand'], ['other', 'Other', 'other']];
function kindRow(m) {
  const k = m.kinds || {};
  if (!m.clips) return '';
  const wants = { batting: ['batting'], bowlfield: ['bowling', 'fielding'], allround: ['batting', 'bowling', 'fielding'] }[m.highlights] || ['batting'];
  return `<div class="kindrow">${KB.filter(([r]) => k[r] || wants.includes(r)).map(([r, l, i]) => `<span class="pill kind ${k[r] ? '' : 'none'}">${ic(i)}${l}${k[r] ? ` <b>${k[r]}</b>` : ''}</span>`).join('')}</div>`;
}

function card(m, i) {
  if (m.damaged) {
    return `<article class="card a-pink span-6" style="--i:${i}"><div class="card-head"><span class="ic">${ic('alert')}</span><h3>${esc(m.name)}</h3></div>
      <p class="small muted">This match's file couldn't be read: ${esc(m.error || '')}. Its folder is untouched; the other matches are fine.</p></article>`;
  }
  const [label, cls, href] = NEXT[m.step] || NEXT.import, s = m.summary;
  const date = (m.name.match(/^\d{4}-\d{2}-\d{2}/) || [m.created.slice(0, 10)])[0];
  const title = m.name.replace(/^\d{4}-\d{2}-\d{2}\s*/, '') || m.name;
  return `<article class="card tap ${ACCENTS[i % ACCENTS.length]} span-6" style="--i:${i}" data-href="${href(m.id)}" data-id="${esc(m.id)}" data-name="${esc(m.name.toLowerCase())}" tabindex="0" role="link" aria-label="Open ${esc(m.name)}">
    <div class="match-hero">${m.poster != null ? `<img src="/api/matches/${encodeURIComponent(m.id)}/thumb/${m.poster}" alt="" loading="lazy" onerror="this.style.visibility='hidden'">` : `<span class="ph">${ic('film', 'lg')}</span>`}
      <div style="min-width:0;display:flex;flex-direction:column;gap:10px">
        <div><div class="eyebrow" style="margin:0"><span class="dot"></span>${esc(auDate(date))}</div>
          <h2 style="margin-top:4px">${esc(title)}</h2>${s && s.result ? `<p class="muted small">${esc(s.result)}</p>` : ''}</div>
        <div class="chips">${pill(cls, label)}${s && !s.ok ? pill('wicket', 'Sheet doesn\'t add up') : ''}</div>
        ${kindRow(m)}
        <dl class="kv" style="max-width:300px">${s ? `<dt>Your innings</dt><dd>${s.runs} off ${s.balls}</dd>` : ''}<dt>Video files</dt><dd>${m.videos}</dd>${m.clips ? `<dt>Clips</dt><dd>${m.clips}</dd>` : ''}${m.exports ? `<dt>Exported files</dt><dd>${m.exports}</dd>` : ''}</dl>
      </div>
      <button class="btn icon sm ghost" data-del="${esc(m.id)}" aria-label="Delete ${esc(m.name)}" title="Delete match" style="position:absolute;right:0;top:0">${ic('trash', 'sm')}</button>
    </div>
  </article>`;
}

export async function mount(main, { list, usage }) {
  const ok = list.filter(m => !m.damaged && m.summary);
  const runs = ok.reduce((a, m) => a + m.summary.runs, 0), balls = ok.reduce((a, m) => a + m.summary.balls, 0);
  const st = shell.status;
  main.style.setProperty('--accent', 'var(--blue)');
  main.innerHTML = `${head('Library', 'Matches', 'Each match keeps its video, score sheet, clips and exports in one folder.',
    `${list.length > 3 ? '<input type="search" class="search" id="search" placeholder="Search matches" aria-label="Search matches">' : ''}<a class="btn primary" href="#import">${ic('plus')}New match</a>`)}
    ${!st.api_key ? note('warn', 'alert', '<b>No Claude API key yet.</b> Spawtz score sheets import without one; photos of a sheet need it.', '<a class="btn sm" href="#settings">Open Settings</a>') : ''}
    ${!st.ffprobe ? note('bad', 'alert', '<b>FFmpeg not found.</b> Videos can be added but not checked or synced. Install it with <span class="mono">winget install -e --id Gyan.FFmpeg</span>, then restart the app.') : ''}
    <div class="grid" style="margin-top:12px">
      <article class="card a-green span-4" style="--i:0"><div class="stat"><span class="k">Runs in these matches</span><span class="v"><span data-count="${runs}">0</span><small>off ${balls}</small></span><span class="k">Strike rate <span class="mono">${balls ? (runs / balls * 100).toFixed(1) : '–'}</span></span></div></article>
      <article class="card a-amber span-4" style="--i:1"><div class="stat"><span class="k">Matches</span><span class="v"><span data-count="${list.length}">0</span></span><span class="k">${list.filter(m => ['exported', 'described'].includes(m.step)).length} exported</span></div></article>
      <article class="card a-purple span-4" style="--i:2"><div class="stat"><span class="k">Claude since the app opened</span><span class="v">$<span data-count="${usage ? usage.session.usd : 0}" data-dec="2">0</span></span><span class="k">${usage ? usage.session.calls : 0} calls · Spawtz score sheets are free</span></div></article>
      ${list.map((m, i) => card(m, i + 3)).join('')}
    </div>
    <p class="cap muted" style="margin-top:16px">Matches are saved in <span class="mono">${esc(st.matches_dir)}</span>. Model for score sheet photos: ${esc(st.models[st.model] || st.model)}.</p>`;
  countUp(main);
  main.addEventListener('click', async e => {
    const del = e.target.closest('[data-del]');
    if (del) {
      e.stopPropagation();
      const m = list.find(x => x.id === del.dataset.del);
      if (await confirmSheet('Delete this match?', `“${esc(m.name)}” and the files copied into its folder are removed. This can't be undone. Original video files elsewhere on the laptop are not touched.`, 'Delete match', { danger: true })) {
        try { await api('DELETE', `/api/matches/${encodeURIComponent(m.id)}`); toast('Match deleted'); location.reload(); } catch (err) { toastErr(err); }
      }
      return;
    }
    const c = e.target.closest('[data-href]'); if (c) location.href = c.dataset.href;
  });
  const s = $('#search', main);
  if (s) s.oninput = () => $$('[data-name]', main).forEach(el => { el.hidden = !el.dataset.name.includes(s.value.toLowerCase()); });
  return { context: () => `${list.length} matches` };
}
