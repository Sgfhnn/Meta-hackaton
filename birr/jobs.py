"""In-memory scan jobs: POST /scan starts one, GET /scan/{id} polls it.

Jobs live in the process, so run the backend as ONE uvicorn worker (or pin a client to one
worker). Finished jobs are dropped after JOB_TTL_S.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable
from dataclasses import dataclass, field


@dataclass
class Job:
    job_id: str
    lang: str
    created: float = field(default_factory=time.monotonic)
    status: str = "pending"  # pending | done | error
    http_status: int | None = None
    body: dict | None = None
    task: asyncio.Task | None = None

    @property
    def elapsed_ms(self) -> int:
        return int((time.monotonic() - self.created) * 1000)


class JobStore:
    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}

    def start(
        self, job_id: str, lang: str, work: Awaitable[tuple[int, dict]], fail: dict, ttl_s: float
    ) -> Job:
        """Run `work` in the background. `fail` is the body used if the work itself crashes."""
        self.prune(ttl_s)
        job = Job(job_id=job_id, lang=lang)
        self._jobs[job_id] = job

        async def run():
            try:
                status, body = await work
            except Exception:  # noqa: BLE001 - a crashed job must still answer the poll
                status, body = 502, fail
            job.http_status, job.body = status, body
            job.status = "done" if status == 200 else "error"

        job.task = asyncio.create_task(run())
        return job

    def get(self, job_id: str) -> Job | None:
        return self._jobs.get(job_id)

    def prune(self, ttl_s: float) -> None:
        now = time.monotonic()
        for job_id in [k for k, j in self._jobs.items() if j.status != "pending"]:
            if now - self._jobs[job_id].created > ttl_s:
                del self._jobs[job_id]

    async def close(self) -> None:
        tasks = [j.task for j in self._jobs.values() if j.task and not j.task.done()]
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
