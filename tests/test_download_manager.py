import unittest

from download_manager import DownloadJob, DownloadManager


class DownloadManagerCancelTests(unittest.TestCase):
    def test_cancel_pending_job_notifies_done(self):
        calls = []

        def on_progress(status, pct):
            calls.append(("progress", status, pct))

        def on_done(track_id, success, message):
            calls.append((track_id, success, message))

        manager = DownloadManager(max_concurrent=0)
        job = DownloadJob(
            track={"id": "track-1", "name": "Song", "artist": "Artist", "duration_ms": 180000},
            output_folder="/tmp",
            on_progress=on_progress,
            on_done=on_done,
        )

        manager.enqueue(job)
        manager.cancel("track-1")

        self.assertEqual(calls, [("track-1", False, "Cancelled")])
        self.assertEqual(manager.pending_ids(), [])

    def test_cancel_all_notifies_each_pending_job(self):
        calls = []

        def on_done(track_id, success, message):
            calls.append((track_id, success, message))

        manager = DownloadManager(max_concurrent=0)
        for track_id in ("track-1", "track-2"):
            manager.enqueue(
                DownloadJob(
                    track={"id": track_id, "name": "Song", "artist": "Artist", "duration_ms": 180000},
                    output_folder="/tmp",
                    on_progress=lambda status, pct: None,
                    on_done=on_done,
                )
            )

        pending = manager.cancel_all()

        self.assertEqual(pending, ["track-1", "track-2"])
        self.assertEqual(calls, [("track-1", False, "Cancelled"), ("track-2", False, "Cancelled")])
        self.assertEqual(manager.pending_ids(), [])


    def test_set_max_concurrent_releases_pending_jobs(self):
        started = []

        def make_job(track_id):
            return DownloadJob(
                track={"id": track_id, "name": "Song", "artist": "Artist", "duration_ms": 180000},
                output_folder="/tmp",
                on_progress=lambda status, pct: None,
                on_done=lambda *args: started.append(args),
            )

        manager = DownloadManager(max_concurrent=0)
        manager.enqueue(make_job("track-1"))
        manager.enqueue(make_job("track-2"))
        self.assertEqual(manager.pending_ids(), ["track-1", "track-2"])

        manager.set_max_concurrent(1)

        self.assertEqual(manager.pending_ids(), ["track-2"])

