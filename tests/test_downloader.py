import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch

import downloader


class ImmediateThread:
    def __init__(self, *args, **kwargs):
        self.target = kwargs.get("target")
        if self.target is None and args:
            self.target = args[0]

    def start(self):
        self.target()


class DownloaderTests(unittest.TestCase):
    def test_candidate_urls_prioritize_public_matching_result(self):
        track = {"id": "trk1", "artist": "Artist", "name": "Song", "duration_ms": 180000}
        entries = [
            {
                "webpage_url": "https://www.youtube.com/watch?v=bad",
                "duration": 180,
                "availability": "private",
            },
            {
                "webpage_url": "https://www.youtube.com/watch?v=good",
                "duration": 181,
                "availability": "public",
            },
        ]

        urls = downloader._candidate_urls(track, entries)

        self.assertEqual(urls, [
            "https://www.youtube.com/watch?v=good",
            "https://www.youtube.com/watch?v=bad",
        ])

    def test_download_track_uses_single_selected_candidate(self):
        track = {"id": "trk1", "artist": "Artist", "name": "Song", "duration_ms": 180000}
        done = []
        progress = []

        search_ydl = MagicMock()
        search_ydl.extract_info.return_value = {
            "entries": [
                {
                    "webpage_url": "https://www.youtube.com/watch?v=bad",
                    "duration": 180,
                    "availability": "private",
                },
                {
                    "webpage_url": "https://www.youtube.com/watch?v=good",
                    "duration": 181,
                    "availability": "public",
                },
            ]
        }
        search_ctx = MagicMock()
        search_ctx.__enter__.return_value = search_ydl
        search_ctx.__exit__.return_value = False

        download_ydl = MagicMock()
        download_ctx = MagicMock()
        download_ctx.__enter__.return_value = download_ydl
        download_ctx.__exit__.return_value = False

        with tempfile.TemporaryDirectory() as outdir, \
                patch("downloader.ensure_ffmpeg_available", return_value="/ffmpeg"), \
                patch("downloader.threading.Thread", ImmediateThread), \
                patch("downloader.yt_dlp.YoutubeDL", side_effect=[search_ctx, download_ctx]):
            handle = downloader.download_track(
                track,
                outdir,
                on_progress=lambda status, pct: progress.append((status, pct)),
                on_done=lambda *args: done.append(args),
            )

            self.assertFalse(handle.cancelled)

            search_ydl.extract_info.assert_called_once_with(
                "ytsearch10:Artist - Song official audio",
                download=False,
            )
            download_ydl.download.assert_called_once_with(["https://www.youtube.com/watch?v=good"])
            self.assertEqual(done, [
                ("trk1", True, os.path.join(outdir, "Artist - Song.mp3"))
            ])
            self.assertFalse(os.path.exists(os.path.join(outdir, ".spotifyvdj_tmp", "trk1")))


if __name__ == "__main__":
    unittest.main()
