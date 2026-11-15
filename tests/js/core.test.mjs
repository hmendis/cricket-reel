// Unit tests for the pure frontend helpers (R44). Run with Node 18+:  node --test tests/js
import assert from 'node:assert/strict';
import { test } from 'node:test';

import { auDate, clamp, esc, mmss, money, timecode } from '../../static/js/core/util.js';
import { bigScore, biggestFirst, exportOn, fitBox, isBowlField, reelKinds, reelLength, sectionOf, ZONES } from '../../static/js/core/reel.js';
import { createHistory } from '../../static/js/core/state.js';
import { isActive, remaining } from '../../static/js/core/jobs.js';

test('formatting', () => {
  assert.equal(mmss(235.89), '3:55.9');
  assert.equal(mmss(5), '0:05.0');
  assert.equal(mmss(59.96), '1:00.0');
  assert.equal(mmss(627.81, 2), '10:27.81');
  assert.equal(timecode(3725.5), '01:02:05:13');
  assert.equal(money(0.0213), '$0.02');
  assert.equal(auDate('2026-11-04'), '04/11/2026');
  assert.equal(esc('<b>"x"</b>'), '&lt;b&gt;&quot;x&quot;&lt;/b&gt;');
  assert.equal(clamp(5, 0, 3), 3);
});

test('biggest moments first, like the backend', () => {
  const clips = { 0: { code: '2', kind: 'runs' }, 1: { code: '6', kind: 'big' }, 2: { code: 'r', kind: 'wicket' },
                  3: { code: '1', kind: 'runs' }, 4: { code: '5', kind: 'big' }, 5: { code: '2', kind: 'runs' } };
  assert.deepEqual(biggestFirst([0, 1, 2, 3, 4, 5], i => clips[i]), [1, 4, 2, 0, 5, 3]);
  assert.ok(bigScore({ code: '1', kind: 'runs', star: true }) > bigScore({ code: '7', kind: 'big' }));
});

test('text stays out of the keep-away zones', () => {
  for (const [x, y] of [[50, 1], [50, 99], [99, 60], [2, 50], [99, 5]]) {
    const w = 40, h = 8, r = fitBox(x, y, w, h);
    const l = r.x - w / 2, t = r.y - h / 2, rr = r.x + w / 2, b = r.y + h / 2;
    assert.ok(l >= 0 && rr <= 100 && t >= ZONES.top[3] && b <= ZONES.bottom[1], `${x},${y}`);
    const [zx, zy1, , zy2] = ZONES.right;
    assert.ok(!(b > zy1 && t < zy2 && rr > zx), `${x},${y} in the right zone`);
  }
  assert.equal(fitBox(50, 1, 40, 8).hit, 'top');
  assert.equal(fitBox(50, 50, 40, 8).hit, null);
});

test('reel length counts transitions and the freeze', () => {
  const clips = { 0: { before: 1, after: 2 }, 1: { before: 1, after: 3.58 } };
  const reel = { entries: [{ index: 0 }, { index: 1 }], trans: 'zoomin', trans_dur: 0.25, freeze: true, freeze_dur: 0.4 };
  assert.equal(reelLength(reel, i => clips[i]), 3 + 4.58 - 0.25 + 0.4);
});

test('undo and redo', () => {
  let s = { n: 1 };
  const h = createHistory(() => s, v => { s = v; });
  h.push(); s = { n: 2 };
  h.push(); s = { n: 3 };
  assert.ok(h.undo()); assert.equal(s.n, 2);
  assert.ok(h.undo()); assert.equal(s.n, 1);
  assert.ok(!h.undo());
  assert.ok(h.redo()); assert.equal(s.n, 2);
  h.push(); s = { n: 9 };
  assert.ok(!h.redo());
});

test('jobs', () => {
  assert.ok(isActive({ status: 'waiting' }) && isActive({ status: 'running' }) && !isActive({ status: 'done' }));
  assert.equal(remaining({ remaining: 65.2 }), '1:05 left');
  assert.equal(remaining({ remaining: 12 }), '12 s left');
});

test('the reel type decides which kinds of clip show', () => {
  assert.deepEqual(reelKinds({ highlights: 'batting' }), ['batting']);
  assert.deepEqual(reelKinds({ highlights: 'bowlfield' }), ['bowling', 'fielding']);
  assert.deepEqual(reelKinds({ highlights: 'batting', reels: { batting: {}, allround: {} } }), ['batting', 'bowling', 'fielding']);
  assert.deepEqual(reelKinds({}), ['batting']);
  assert.ok(isBowlField(['bowling', 'fielding']) && !isBowlField(['batting', 'bowling', 'fielding']) && !isBowlField(['batting']));
  assert.equal(sectionOf({ role: 'other', phase: 'fielding' }), 'fielding');
  assert.equal(sectionOf({ role: 'other' }), 'batting');
  assert.equal(sectionOf({}), 'batting');
});

test('export as clip starts on for kept highlights only', () => {
  assert.ok(exportOn({ keep: true, wid: '12.1', code: 'c' }));
  assert.ok(exportOn({ keep: true, code: '4', kind: 'big' }) && !exportOn({ keep: true, code: '2' }));
  assert.ok(exportOn({ keep: true, code: '1', star: true }));
  assert.ok(!exportOn({ keep: false, code: '6' }) && !exportOn({ keep: false, code: '1', export_clip: true }));
  assert.ok(!exportOn({ keep: true, code: '6', export_clip: false }) && exportOn({ keep: true, code: '0', export_clip: true }));
  assert.ok(!exportOn({ keep: true, code: '', source: 'manual', label: 'CATCH' }));
});
