import threading
from dataclasses import dataclass, field
from typing import Callable
import downloader


@dataclass
class DownloadJob:
    track: dict
    output_folder: str
    on_progress: Callable
    on_done: Callable
    handle: downloader.DownloadHandle | None = field(default=None, init=False)

    @property
    def track_id(self) -> str:
        return self.track["id"]


class DownloadManager:
    """Serialized download queue with a cap on concurrent downloads."""

    def __init__(self, max_concurrent: int = 2):
        self._max = max_concurrent
        self._pending: list[DownloadJob] = []
        self._active: dict[str, DownloadJob] = {}
        self._lock = threading.Lock()

    def enqueue(self, job: DownloadJob) -> None:
        with self._lock:
            self._pending.append(job)
        self._maybe_start_next()

    def prioritize(self, track_id: str) -> bool:
        """Move track to front of pending queue. Returns True if it was pending."""
        with self._lock:
            idx = next((i for i, j in enumerate(self._pending) if j.track_id == track_id), None)
            if idx is None or idx == 0:
                return False
            job = self._pending.pop(idx)
            self._pending.insert(0, job)
        return True

    def cancel(self, track_id: str) -> None:
        pending_done = None
        with self._lock:
            # If pending, remove it and notify the caller outside the lock.
            for idx, job in enumerate(self._pending):
                if job.track_id == track_id:
                    self._pending.pop(idx)
                    pending_done = job.on_done
                    break
            # If active, signal cancellation.
            job = self._active.get(track_id)

        if pending_done:
            pending_done(track_id, False, "Cancelled")
            self._maybe_start_next()
            return

        if job and job.handle:
            job.handle.cancel()

    def cancel_all(self) -> list[str]:
        """Cancel everything. Returns list of track_ids that were pending (not yet started)."""
        with self._lock:
            pending_jobs = list(self._pending)
            pending_ids = [j.track_id for j in pending_jobs]
            self._pending.clear()
            active_jobs = list(self._active.values())

        for job in pending_jobs:
            job.on_done(job.track_id, False, "Cancelled")

        for job in active_jobs:
            if job.handle:
                job.handle.cancel()

        return pending_ids

    def pending_ids(self) -> list[str]:
        with self._lock:
            return [j.track_id for j in self._pending]

    def _maybe_start_next(self) -> None:
        while True:
            with self._lock:
                if len(self._active) >= self._max or not self._pending:
                    return
                job = self._pending.pop(0)
                self._active[job.track_id] = job

            def _wrap_done(track_id, orig_done):
                def _done(tid: str, success: bool, msg: str):
                    with self._lock:
                        self._active.pop(track_id, None)
                    orig_done(tid, success, msg)
                    self._maybe_start_next()
                return _done

            job.handle = downloader.download_track(
                job.track,
                job.output_folder,
                on_progress=job.on_progress,
                on_done=_wrap_done(job.track_id, job.on_done),
            )
