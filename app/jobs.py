"""Background jobs, run one at a time by a single worker, with progress the UI follows over server-sent events.

One worker because the laptop's CPU, Quick Sync and disk are the bottleneck: a sync, a preview render and an
export running together would each be slower, and a render could read proxy.mp4 while a sync replaces it.
A job queued behind another shows as "waiting".
"""
from __future__ import annotations

import logging
import queue
import threading
import time
import uuid

log = logging.getLogger(__name__)

_JOBS: dict[str, "Job"] = {}
_LOCK = threading.Lock()
_QUEUE: "queue.Queue[Job]" = queue.Queue()
_worker: threading.Thread | None = None
ACTIVE = ("waiting", "running")
NAMES = {"sync": "the sync", "render": "the preview render", "export": "the export"}


class Job:
    def __init__(self, kind: str, match_id: str, steps: list[str], fn):
        self.id = uuid.uuid4().hex[:12]
        self.kind, self.match_id, self.steps, self.fn = kind, match_id, steps, fn
        self.status = "waiting"            # waiting | running | done | failed | cancelled
        self.progress = 0.0
        self.step = 0
        self.detail = ""
        self.error = None
        self.result = None
        self.queued = time.time()
        self.started = None
        self.finished = None
        self.cancel = threading.Event()

    def update(self, progress: float | None = None, step: int | None = None, detail: str | None = None):
        if progress is not None:
            self.progress = max(self.progress, min(1.0, progress))
        if step is not None:
            self.step = step
        if detail is not None:
            self.detail = detail

    def to_dict(self) -> dict:
        now = self.finished or time.time()
        elapsed = now - self.started if self.started else 0.0
        remaining = None
        if self.status == "running" and self.progress > 0.03:
            remaining = elapsed * (1 - self.progress) / self.progress
        detail = self.detail
        if self.status == "waiting":
            ahead = [j for j in active() if j.status == "running"]
            detail = f"Waiting for {NAMES.get(ahead[0].kind, 'another job')} to finish…" if ahead else "Starting…"
        return {"id": self.id, "kind": self.kind, "match_id": self.match_id, "status": self.status, "steps": self.steps,
                "step": self.step, "progress": round(self.progress, 4), "detail": detail, "error": self.error,
                "elapsed": round(elapsed, 1), "remaining": round(remaining, 1) if remaining is not None else None,
                "result": self.result}


def start(kind: str, match_id: str, steps: list[str], fn) -> Job:
    """Queue fn(job), unless the same kind of job is already waiting or running for this match (that one is returned)."""
    global _worker
    with _LOCK:
        for j in _JOBS.values():
            if j.match_id == match_id and j.kind == kind and j.status in ACTIVE:
                return j
        job = Job(kind, match_id, steps, fn)
        _JOBS[job.id] = job
        if _worker is None or not _worker.is_alive():
            _worker = threading.Thread(target=_work, daemon=True, name="job-worker")
            _worker.start()
    _QUEUE.put(job)
    return job


def _work():
    while True:
        job = _QUEUE.get()
        if job.cancel.is_set():
            job.status, job.finished = "cancelled", time.time()
            continue
        job.status, job.started = "running", time.time()
        try:
            job.result = job.fn(job)
            job.status = "cancelled" if job.cancel.is_set() else "done"
            job.progress = 1.0 if job.status == "done" else job.progress
        except Exception as e:  # noqa: BLE001 - every failure must reach the UI
            if job.cancel.is_set():
                job.status = "cancelled"
            else:
                job.status = "failed"
                job.error = getattr(e, "message", None) or str(e) or e.__class__.__name__
                log.exception("%s job for %s failed", job.kind, job.match_id)
        finally:
            job.finished = time.time()


def cancel(job: Job) -> None:
    job.cancel.set()
    if job.status == "waiting":  # never started: done at once
        job.status, job.finished = "cancelled", time.time()


def get(job_id: str) -> Job | None:
    with _LOCK:
        return _JOBS.get(job_id)


def latest_for(match_id: str, kind: str | None = None) -> Job | None:
    with _LOCK:
        js = [j for j in _JOBS.values() if j.match_id == match_id and (kind is None or j.kind == kind)]
    return max(js, key=lambda j: j.queued) if js else None


def active() -> list[Job]:
    """Jobs waiting or running, oldest first."""
    with _LOCK:
        return sorted((j for j in _JOBS.values() if j.status in ACTIVE), key=lambda j: j.queued)


def running() -> list[Job]:
    return active()


def cancel_all(wait: float = 5.0) -> None:
    """Stop every job (their FFmpeg processes are killed) - used when the app closes."""
    js = active()
    for j in js:
        cancel(j)
    deadline = time.time() + wait
    while time.time() < deadline and any(j.status == "running" for j in js):
        time.sleep(0.1)
