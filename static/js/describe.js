// Step 6 · Describe: social media text for each exported file (E2), each with its own prompt, written to your
// indoor-cricket-socials rules. The cost shows before you click and for the step (E3). Quick links to upload (E4).
import { api } from './core/api.js';
import { follow, isActive } from './core/jobs.js';
import { esc, money } from './core/util.js';
import { $, $$, head, ic, note, pill, toast, toastErr } from './ui.js';
import { kickJobs, refreshCost, shell, stepLabel } from './shell.js';
import { redrawShell } from './main.js';

const enc = encodeURIComponent;
const PLAT = [['meta', 'Instagram + Facebook', '--blue', 'words'], ['tiktok', 'TikTok', '--teal', 'words'], ['youtube_title', 'YouTube Shorts title', '--pink', 'chars'], ['youtube_description', 'YouTube Shorts description', '--pink', 'words']];
const LINK_COLOURS = ['--blue', '--pink', '--teal', '--amber', '--purple', '--green'];
let G = null;

export async function prepare([id]) {
  const [d, full] = await Promise.all([api('GET', `/api/matches/${enc(id)}/describe`), api('GET', `/api/matches/${enc(id)}`)]);
  shell.match = full.match; shell.step = 'describe';
  return { d };
}

export async function mount(main, { d }) {
  G = { main, id: shell.match.id, d, busy: null, stop: null };
  main.style.setProperty('--accent', 'var(--purple)');
  render();
  bind();
  const j = await api('GET', '/api/jobs').catch(() => []);
  const run = (j || []).find(x => x.kind === 'describe' && x.match_id === G.id && isActive(x));
  if (run) followJob(run, 'all');
  return { context: () => `${G.d.files.length} exported files, ${G.d.files.filter(f => f.saved).length} described`, unmount: () => { if (G.stop) G.stop(); } };
}

const key = f => `cr.prompt.${G.id}.${f.name}`;
function prompt(f) {
  try { const v = localStorage.getItem(key(f)); if (v != null) return v; } catch (e) { /* */ }
  return (f.saved && f.saved.prompt) || f.draft || '';
}
const RNAMES = { batting: 'Batting reel', bowlfield: 'Bowling + Fielding reel', allround: 'All-round reel' };
const what = f => f.kind === 'reel' ? (RNAMES[f.rtype] || 'Highlight reel') : (f.facts.find(x => x.startsWith('This clip')) || 'Clip').replace('This clip: ', '').replace(/^./, m => m.toUpperCase());
const edited = f => { try { const v = localStorage.getItem(key(f)); return v != null && v !== f.draft; } catch (e) { return false; } };
const thumbT = f => { const c = (shell.match.clips || []).find(x => x.index === f.index); return c ? c.t : ((shell.match.clips || [])[0] || {}).t || 0; };

function render() {
  const d = G.d, step = (d.usage.match.steps || []).find(s => s.step === 'describe'), n = d.files.length;
  if (!n) {
    G.main.innerHTML = `${head(stepLabel('describe'), 'Descriptions', 'Export the reel or a clip first; each exported file gets its own text.')}
      ${note('', 'info', 'Nothing exported yet.', `<a class="btn sm" href="#export/${enc(G.id)}">Open Export</a>`)}${linksCard()}`;
    return;
  }
  G.main.innerHTML = `${head(stepLabel('describe'), 'Descriptions', 'Each exported file gets its own prompt and its own text, written to your indoor-cricket-socials rules: no hashtags, no calls to action, "indoor cricket" in the first 125 characters.',
    `<span class="stepcost">${ic('coins', 'sm')}This step ${money(step ? step.usd : 0)} · ${step ? step.calls : 0} call${step && step.calls === 1 ? '' : 's'}</span><button class="btn" data-act="genall" ${G.busy != null || !shell.status.api_key ? 'disabled' : ''}>${ic('refresh', 'sm')}Generate all <span class="cost">≈ ${money(d.estimate_each * n)}</span></button>`)}
    ${!shell.status.api_key ? note('warn', 'alert', '<b>No Claude API key yet.</b> Descriptions are written by Claude.', '<a class="btn sm" href="#settings">Open Settings</a>') : ''}
    <div class="grid">
      ${d.files.map((f, k) => fileCard(f, k)).join('')}
      <section class="card a-green span-4" style="--i:${n}">
        <div class="card-head"><span class="ic">${ic('folder')}</span><h3>Saved with the videos</h3></div>
        ${d.text_file ? `<div class="fn mono cap" style="overflow-wrap:anywhere">exports\\${esc(d.text_file)}</div>${pill('keep', 'Rewritten on every Generate')}` : '<p class="cap muted">Written to the exports folder once you generate.</p>'}
        <button class="btn sm" style="margin-top:10px;display:flex" data-act="open">${ic('folder', 'sm')}Open folder</button>
      </section>
      ${linksCard(n + 1)}
    </div>`;
}

function fileCard(f, k) {
  const s = f.saved, busy = G.busy === k || G.busy === 'all';
  return `<section class="card a-purple span-12" style="--i:${k}" id="f${k}">
    <div class="card-head"><img src="/api/matches/${enc(G.id)}/thumb/${Math.floor(thumbT(f))}" alt="" style="width:32px;height:57px;object-fit:cover;border-radius:8px" onerror="this.style.visibility='hidden'"><div style="flex:1;min-width:0"><h3>${esc(what(f))}</h3><div class="mono cap muted" style="overflow-wrap:anywhere">${esc(f.name)}</div></div>${s ? `<button class="btn sm" data-act="copyall" data-k="${k}">${ic('copy', 'sm')}Copy all</button>` : ''}</div>
    <div class="dgrid">
      <div>
        <label class="field"><span>What do you want to say about this ${f.kind === 'reel' ? 'reel' : 'clip'}?</span><textarea data-k="${k}" maxlength="1000" placeholder="For example: big night of hard-run twos, run out late, but we won by 27">${esc(prompt(f))}</textarea></label>
        <div class="draftnote">${f.saved && f.saved.prompt ? `${ic('check', 'sm')}Your words from last time` : edited(f) ? `${ic('type', 'sm')}Edited by you <button class="btn sm ghost" data-act="redraft" data-k="${k}" style="min-height:24px;padding:0 6px">Use the draft again</button>` : f.draft ? `${ic('check', 'sm')}Drafted from the match. Edit it or leave it.` : ''}</div>
        <div class="label">Added from the match</div>
        <div class="chips">${f.facts.map(x => pill('normal wrap', esc(x), false)).join('')}</div>
        <button class="btn sm" style="margin-top:12px" data-act="gen" data-k="${k}" ${G.busy != null || !shell.status.api_key ? 'disabled' : ''}>${busy ? '<span class="spin"></span>Writing…' : `${ic('refresh', 'sm')}${s ? 'Write again' : 'Generate'} for this ${f.kind === 'reel' ? 'reel' : 'clip'} <span class="cost">≈ ${money(G.d.estimate_each)}</span>`}</button>
      </div>
      <div>
        ${busy ? '<div class="busybar" style="height:3px;border-radius:3px;background:linear-gradient(90deg,transparent,var(--purple),transparent);background-size:50% 100%;background-repeat:no-repeat;animation:shimmer 1s linear infinite;margin-bottom:8px"></div>' : ''}
        ${s ? PLAT.map(([p, l, c, unit], j) => {
          const ch = s.checks || {}, n = (ch.lengths || {})[p];
          return `<div class="desc" style="--pc:var(${c})"><div class="h"><span class="plat"><i></i>${l}</span><span class="cnt">${n != null ? `${n}${unit === 'chars' ? ' / 50 characters' : ' words'}` : ''}</span><button class="btn icon sm ghost" data-act="copy" data-k="${k}" data-j="${j}" aria-label="Copy ${l}">${ic('copy', 'sm')}</button></div><div class="txt">${esc(s.text[p])}</div>
            ${j === 0 ? `<div class="checks">${[['keyword', '"indoor cricket" early'], ['no_hashtags', 'No hashtags'], ['no_call_to_action', 'No call to action'], ['title_length', 'Title ≤ 50 characters']].map(([ck, lab]) => `<span style="${ch[ck] ? '' : 'color:var(--pink)'}">${ic(ch[ck] ? 'check' : 'alert', 'sm')}${lab}</span>`).join('')}</div>` : ''}</div>`;
        }).join('') : '<p class="small muted" style="padding:12px 0">Write what you want to say (or leave it empty to use only the match facts), then Generate.</p>'}
      </div>
    </div>
  </section>`;
}

function linksCard(i = 0) {
  const links = shell.status.settings.quick_links || [];
  return `<section class="card a-blue span-8" style="--i:${i}">
    <div class="card-head"><span class="ic">${ic('ext')}</span><h3>Upload</h3><a class="meta" href="#settings" style="color:var(--muted)">Edit links in Settings</a></div>
    <div class="qlinks">${links.map((q, k) => `<a class="qlink" style="--pc:var(${LINK_COLOURS[k % LINK_COLOURS.length]})" href="${esc(q.url)}" target="_blank" rel="noopener noreferrer"><span class="dot"></span><span style="min-width:0"><b>${esc(q.name)}</b><small>${esc(q.url.replace(/^https:\/\//, '').split('/')[0])}</small></span>${ic('ext', 'sm')}</a>`).join('') || '<p class="cap muted">No links yet.</p>'}</div>
  </section>`;
}

async function generate(ks) {
  const files = ks.map(k => { const f = G.d.files[k]; return { name: f.name, kind: f.kind, index: f.index, rtype: f.rtype || null, prompt: prompt(f) }; });
  try {
    const j = await api('POST', `/api/matches/${enc(G.id)}/describe`, { files });
    kickJobs(); followJob(j, ks.length > 1 ? 'all' : ks[0]);
  } catch (e) { toastErr(e); }
}
function followJob(j, busy) {
  G.busy = busy; render();
  if (G.stop) G.stop();
  G.stop = follow(j.id, async x => {
    if (isActive(x)) return;
    G.stop = null; G.busy = null; kickJobs();
    try { G.d = await api('GET', `/api/matches/${enc(G.id)}/describe`); } catch (e) { /* keep the old */ }
    render(); refreshCost();
    if (x.status === 'done') {
      toast('Descriptions written and saved with the videos');
      api('GET', `/api/matches/${enc(G.id)}`).then(full => { shell.match = full.match; redrawShell(); }).catch(() => {});
    } else if (x.status === 'failed') toastErr(new Error(x.error || 'Writing the descriptions failed.'));
  });
}

function copy(text, msg) {
  const fail = () => toast('Copy was blocked here. Select the text instead.', { error: true });
  try { navigator.clipboard.writeText(text).then(() => toast(msg), fail); } catch (e) { fail(); }
}

function bind() {
  G.main.addEventListener('input', e => {
    const t = e.target; if (t.dataset.k == null || t.tagName !== 'TEXTAREA') return;
    try { localStorage.setItem(key(G.d.files[+t.dataset.k]), t.value); } catch (er) { /* the prompt is still sent */ }
  });
  G.main.addEventListener('click', async e => {
    const b = e.target.closest('[data-act]'); if (!b || b.disabled) return;
    const act = b.dataset.act, k = +b.dataset.k;
    if (act === 'gen') generate([k]);
    else if (act === 'redraft') { try { localStorage.removeItem(key(G.d.files[k])); } catch (er) { /* */ } render(); toast('Draft from the match put back'); }
    else if (act === 'genall') generate(G.d.files.map((_, i) => i));
    else if (act === 'copy') { const [p, l] = PLAT[+b.dataset.j]; copy(G.d.files[k].saved.text[p], `${l} copied`); }
    else if (act === 'copyall') { const s = G.d.files[k].saved.text; copy(PLAT.map(([p, l]) => `${l}\n${s[p]}`).join('\n\n'), 'All four copied'); }
    else if (act === 'open') { try { const r = await api('POST', `/api/matches/${enc(G.id)}/open-folder`); if (!shell.status.desktop) toast('Exports folder: ' + r.path, { ms: 8000 }); } catch (err) { toastErr(err); } }
  });
}
