// Background jobs (sync, preview render, export): one runs at a time, others wait in the queue.

export const isActive = j => !!j && (j.status === 'running' || j.status === 'waiting');

/** Follow a job's progress stream. onUpdate(job) on every message; returns a function that stops following. */
export function follow(jobId, onUpdate) {
  const es = new EventSource(`/api/jobs/${jobId}/events`);
  es.onmessage = e => {
    let j = null;
    try { j = JSON.parse(e.data); } catch (err) { return; }
    onUpdate(j);
    if (!isActive(j)) es.close();
  };
  es.onerror = () => { /* the browser retries; the server ends the stream when the job ends */ };
  return () => es.close();
}

/** "1:05 left", "12 s left", or '' while unknown. */
export function remaining(j) {
  if (!j || j.remaining == null) return '';
  const s = Math.round(j.remaining);
  return s >= 60 ? `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')} left` : `${s} s left`;
}
