"""Long tool calls run as jobs, so the server answers at once and keeps answering.

A tool that may take long (hashing a big folder, comparing two trees, waiting for the owner to run a change) starts a job on a thread and
waits for it a short while (``wait_seconds``). If the job is done by then, the call returns its result as usual. If not, the call returns
``status: running`` with a ``job_id``; the assistant asks again with ``get_job`` (which can also page through a long result) or stops it
with ``cancel_job``. Jobs live in the server's memory only: when the assistant's program closes the server, they are gone.
"""
from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Callable, Optional

from ..core.progress import Cancelled, CancelToken

KEEP = 20                                     # finished jobs kept for get_job
WAIT_DEFAULT, WAIT_MAX = 20, 60
RUNNING, DONE, FAILED, CANCELLED = "running", "done", "failed", "cancelled"


@dataclass
class Job:
    id: str
    tool: str
    started: float
    token: CancelToken = field(default_factory=CancelToken)
    status: str = RUNNING
    progress: dict = field(default_factory=dict)
    result: Optional[dict] = None
    error: str = ""
    finished: float = 0.0
    _done: threading.Event = field(default_factory=threading.Event)

    def wait(self, seconds: float) -> bool:
        return self._done.wait(max(0.0, seconds))

    def report(self, **progress) -> None:
        self.progress = dict(progress)

    def describe(self) -> dict:
        end = self.finished or time.time()
        out = {"job_id": self.id, "tool": self.tool, "status": self.status, "seconds": round(end - self.started, 1)}
        if self.progress:
            out["progress"] = self.progress
        if self.error:
            out["error"] = self.error
        return out


class Jobs:
    def __init__(self) -> None:
        self._jobs: dict = {}
        self._lock = threading.Lock()

    def start(self, tool: str, work: Callable[[Job], dict]) -> Job:
        """Run ``work(job)`` on a thread. It checks ``job.token`` and may call ``job.report(...)``; what it returns is the result."""
        job = Job(uuid.uuid4().hex[:10], tool, time.time())

        def run() -> None:
            try:
                job.result = work(job)
                job.status = DONE
            except Cancelled:
                job.status = CANCELLED
            except Exception as e:   # noqa: BLE001 -- a job's error is reported to the assistant, the server stays up
                job.status, job.error = FAILED, str(e) or type(e).__name__
            finally:
                job.finished = time.time()
                job._done.set()
        with self._lock:
            self._jobs[job.id] = job
            done = [j for j in self._jobs.values() if j.status != RUNNING]
            for old in sorted(done, key=lambda j: j.finished)[:-KEEP] if len(done) > KEEP else []:
                self._jobs.pop(old.id, None)
        threading.Thread(target=run, name=f"dossier-job-{tool}", daemon=True).start()
        return job

    def get(self, job_id: str) -> Optional[Job]:
        with self._lock:
            return self._jobs.get(job_id)

    def all(self) -> list:
        with self._lock:
            return sorted(self._jobs.values(), key=lambda j: j.started)
