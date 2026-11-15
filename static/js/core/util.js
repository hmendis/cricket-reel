// Small pure helpers shared by every screen. No DOM access here, so they can be unit-tested (tests/js).

export const clamp = (v, a, b) => Math.max(a, Math.min(b, v));

export function esc(s) {
  return String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

/** m:ss.d (e.g. 3:55.9); d = decimals of the seconds. */
export function mmss(t, d = 1) {
  if (t == null || !isFinite(t)) return '–';
  const neg = t < 0, a = Math.abs(t), m = Math.floor(a / 60);
  let s = (a - m * 60).toFixed(d);
  if (parseFloat(s) >= 60) return `${neg ? '-' : ''}${m + 1}:${(0).toFixed(d).padStart(d ? d + 3 : 2, '0')}`;
  if (parseFloat(s) < 10) s = '0' + s;
  return `${neg ? '-' : ''}${m}:${s}`;
}

/** hh:mm:ss:ff at 25 fps, for the timeline. */
export function timecode(t, fps = 25) {
  const f = Math.max(0, Math.round(t * fps)), ff = f % fps, s = Math.floor(f / fps);
  const p = n => String(n).padStart(2, '0');
  return `${p(Math.floor(s / 3600))}:${p(Math.floor(s / 60) % 60)}:${p(s % 60)}:${p(ff)}`;
}

/** $0.02 - Claude bills in US dollars. */
export const money = v => '$' + (Math.round((v || 0) * 100) / 100).toFixed(2);

/** DD/MM/YYYY from an ISO date or Date. */
export function auDate(d) {
  const x = typeof d === 'string' ? new Date(d.length === 10 ? d + 'T00:00:00' : d) : d;
  if (!x || isNaN(x)) return '';
  return `${String(x.getDate()).padStart(2, '0')}/${String(x.getMonth() + 1).padStart(2, '0')}/${x.getFullYear()}`;
}

export function debounce(fn, ms) {
  let t = 0;
  const d = (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); };
  d.cancel = () => clearTimeout(t);
  return d;
}
