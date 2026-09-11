"""Small in-process worker backed by the durable jobs repository."""

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from contextlib import suppress
from datetime import UTC, datetime, timedelta

from soulmate_core.domain import JobRepository

JobHandler = Callable[[dict[str, object]], Awaitable[None]]


class DurableJobWorker:
    def __init__(
        self,
        repository: JobRepository,
        handlers: Mapping[str, JobHandler],
        *,
        poll_interval: float = 0.25,
        lease_timeout: timedelta = timedelta(minutes=5),
    ) -> None:
        self._repository = repository
        self._handlers = dict(handlers)
        self._poll_interval = poll_interval
        self._lease_timeout = lease_timeout

    async def process_once(self) -> bool:
        """Run one available supported job, including a stale interrupted job."""
        now = datetime.now(UTC)
        job = self._repository.claim_next(now, now - self._lease_timeout, self._handlers.keys())
        if job is None:
            return False
        handler = self._handlers[job.job_type]
        try:
            await handler(job.payload)
        except Exception as exc:
            error = f"Handler failed with {type(exc).__name__}"
            self._repository.mark_failed(job.id, error, datetime.now(UTC))
        else:
            self._repository.mark_succeeded(job.id, datetime.now(UTC))
        return True

    async def run(self, stop: asyncio.Event) -> None:
        while not stop.is_set():
            processed = await self.process_once()
            if processed:
                continue
            with suppress(TimeoutError):
                await asyncio.wait_for(stop.wait(), timeout=self._poll_interval)
