// Talking to the local backend: JSON calls, uploads, and saves that must not be lost when the window closes.

export class ApiError extends Error {
  constructor(message, status, code) { super(message); this.status = status; this.code = code; }
}

export async function api(method, url, body) {
  let r;
  try {
    r = await fetch(url, { method, headers: body ? { 'Content-Type': 'application/json' } : {}, body: body ? JSON.stringify(body) : undefined });
  } catch (e) {
    throw new ApiError("Can't reach the app's backend. Is it still running?", 0, 'offline');
  }
  let data = null;
  try { data = await r.json(); } catch (e) { /* empty body */ }
  if (!r.ok) {
    const msg = (data && (data.error || (typeof data.detail === 'string' ? data.detail : null))) || `Request failed (${r.status})`;
    throw new ApiError(msg, r.status, data && data.code);
  }
  return data;
}

/** Upload with progress. raw = the file is the request body (videos), else multipart form field "file". */
export function upload(url, file, onProgress, raw = false) {
  return new Promise((resolve, reject) => {
    const x = new XMLHttpRequest();
    x.open('POST', raw ? `${url}?name=${encodeURIComponent(file.name)}` : url);
    x.upload.onprogress = e => e.lengthComputable && onProgress && onProgress(e.loaded / e.total);
    x.onload = () => {
      let d = null;
      try { d = JSON.parse(x.responseText); } catch (e) { /* not JSON */ }
      x.status < 300 ? resolve(d) : reject(new ApiError((d && (d.error || d.detail)) || 'Upload failed', x.status));
    };
    x.onerror = () => reject(new ApiError('Upload failed. Is the app still running?', 0, 'offline'));
    if (raw) { x.setRequestHeader('Content-Type', 'application/octet-stream'); x.send(file); return; }
    const fd = new FormData();
    fd.append('file', file);
    x.send(fd);
  });
}

// Saves that are queued but not sent yet. When the window closes they're sent with keepalive (R29).
const PENDING = new Map();

export function setPending(key, method, url, bodyFn) { PENDING.set(key, { method, url, bodyFn }); }
export function clearPending(key) { PENDING.delete(key); }
export function pendingCount() { return PENDING.size; }

export function flushPending() {
  for (const p of PENDING.values()) {
    try {
      fetch(p.url, { method: p.method, keepalive: true, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(p.bodyFn()) });
    } catch (e) { /* the window is closing */ }
  }
  PENDING.clear();
}

if (typeof addEventListener === 'function') addEventListener('pagehide', flushPending);
