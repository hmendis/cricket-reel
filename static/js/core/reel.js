// Reel rules shared by Review, Arrange, Sync and Export: which kinds of clip the match's reels use, biggest-moments-
// first order and the keep-away zones for text.

/** Same order as the backend (reel.highlight_score): star, big shots by runs, wickets, then runs; extras last. */
export function bigScore(c) {
  const runs = /^\d+$/.test(String(c.code).trim()) ? parseInt(c.code, 10) : 0;
  const base = c.kind === 'big' ? 100 + runs : c.kind === 'wicket' ? 90 : c.kind === 'manual' ? 80 : c.kind === 'extra' ? 0 : runs * 10;
  return (c.star ? 1000 : 0) + base;
}

/** Clip indexes sorted biggest first; ties keep match order. clipBy(index) → clip. */
export const biggestFirst = (order, clipBy) =>
  order.slice().sort((a, b) => bigScore(clipBy(b)) - bigScore(clipBy(a)) || a - b);

// Keep-away zones in % of the frame (left, top, right, bottom), as in app/render.py. L5.
export const ZONES = { top: [0, 0, 100, 9], bottom: [0, 80, 100, 100], right: [85, 45, 100, 80] };

/**
 * Where a text box may sit: centre (x, y) in %, box size (w, h) in % of the frame. Returns the centre moved into
 * the frame and out of the zones, and which zone (or 'edge') stopped it. Same rule as render.fit_in_safe_area.
 */
export function fitBox(x, y, w, h) {
  let hit = null;
  let nx = Math.min(Math.max(x, w / 2 + 2), 100 - w / 2 - 2), ny = y;
  const minY = ZONES.top[3] + h / 2 + 1, maxY = ZONES.bottom[1] - h / 2 - 1;
  if (ny < minY) { ny = minY; hit = 'top'; }
  if (ny > maxY) { ny = maxY; hit = 'bottom'; }
  const [rx1, ry1, , ry2] = ZONES.right;
  if (ny + h / 2 > ry1 && ny - h / 2 < ry2 && nx + w / 2 > rx1) { nx = rx1 - w / 2 - 1; hit = hit || 'right'; }
  if (!hit && Math.abs(nx - x) > 0.5) hit = 'edge';
  return { x: Math.round(nx * 10) / 10, y: Math.round(ny * 10) / 10, hit };
}

/** Reel length: clips minus transition overlaps, plus the hook freeze. */
export function reelLength(reel, clipBy) {
  let t = 0;
  reel.entries.forEach((e, i) => {
    const c = clipBy(e.index);
    if (!c) return;
    t += c.before + c.after + (i === 0 && reel.freeze ? reel.freeze_dur : 0);
    if (i > 0 && (e.trans || reel.trans) !== 'cut') t -= reel.trans_dur;
  });
  return Math.round(t * 100) / 100;
}

// 2.2: the reel type decides what shows. Same table as app/matches.py REEL_TYPES.
export const REEL_TYPES = { batting: ['batting'], bowlfield: ['bowling', 'fielding'], allround: ['batting', 'bowling', 'fielding'] };
const KIND_ORDER = ['batting', 'bowling', 'fielding'];

/** The kinds of clip this match's reels use: the reel picked in New match plus any reel made since, in play order. */
export function reelKinds(match) {
  const types = [match && match.highlights || 'batting', ...Object.keys((match && match.reels) || {})];
  const ks = new Set(types.flatMap(t => REEL_TYPES[t] || []));
  return KIND_ORDER.filter(k => ks.has(k));
}

/** The section a clip plays in: its kind, and an 'other' clip goes with the phase it was recorded in (as reel.section_of). */
export const sectionOf = c => { const r = (c && c.role) || 'batting'; return r === 'other' ? (c.phase === 'fielding' ? 'fielding' : 'batting') : r; };

/** Bowling + Fielding only: one sequence by ball, no sections. */
export const isBowlField = kinds => kinds.length === 2 && kinds.includes('bowling') && kinds.includes('fielding');

/** 2.2: a highlight is a wicket in the field, a big shot (4+ runs) or a starred clip. Same rule as app/review.py. */
export function isHighlight(c) {
  const code = String(c.code ?? '').trim();
  return !!c.wid || (c.source !== 'manual' && !c.wid && /^\d+$/.test(code) && +code >= 4) || !!c.star;
}
/** Does the clip export on its own? Only kept clips: the owner's choice once set, else on for highlights. */
export const exportOn = c => !!c.keep && (c.export_clip != null ? !!c.export_clip : isHighlight(c));
