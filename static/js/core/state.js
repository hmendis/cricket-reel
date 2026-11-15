// Undo/redo history and debounced autosave, shared by every editing screen (was written three times).
import { clearPending, setPending } from './api.js';

/** Snapshot history. get() returns the current state, set(state) restores one. */
export function createHistory(get, set, limit = 200) {
  const undo = [], redo = [];
  const snap = () => JSON.stringify(get());
  return {
    /** Call BEFORE a change. */
    push() { undo.push(snap()); if (undo.length > limit) undo.shift(); redo.length = 0; },
    undo() { if (!undo.length) return false; redo.push(snap()); set(JSON.parse(undo.pop())); return true; },
    redo() { if (!redo.length) return false; undo.push(snap()); set(JSON.parse(redo.pop())); return true; },
    get canUndo() { return undo.length > 0; },
    get canRedo() { return redo.length > 0; },
  };
}

/**
 * Debounced save. queue() after each change; the PUT goes out `delay` ms after the last one. Until then the save
 * is registered as pending, so closing the window sends it anyway. onState('saving'|'saved'|'error', error).
 */
export function createAutosave({ key, method = 'PUT', url, body, send, delay = 400, onState = () => {} }) {
  let t = 0;
  async function run() {
    clearPending(key);
    try { await send(body()); onState('saved'); } catch (e) { onState('error', e); }
  }
  return {
    queue() { onState('saving'); clearTimeout(t); setPending(key, method, url(), body); t = setTimeout(run, delay); },
    async flush() { if (!t) return; clearTimeout(t); t = 0; await run(); },
    cancel() { clearTimeout(t); t = 0; clearPending(key); },
  };
}
