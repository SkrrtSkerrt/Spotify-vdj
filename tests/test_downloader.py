import os
import tempfile
import unittest
from unittest.mock import MagicMock, call, patch

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

    def test_search_queries_include_fallbacks(self):
        track = {"id": "trk1", "artist": "Artist", "name": "Song", "duration_ms": 180000}

        queries = downloader._search_queries(track)

        self.assertEqual(queries, [
            "Artist - Song official audio",
            "Artist - Song",
            "Artist Song official audio",
        ])

    def test_find_existing_download_path_matches_variant_filename(self):
        track = {"id": "trk1", "artist": "Artist", "name": "Song", "duration_ms": 180000}
        with tempfile.TemporaryDirectory() as outdir:
            expected = os.path.join(outdir, "Artist - Song (Official Audio).mp3")
            with open(expected, "wb") as f:
                f.write(b"x")

            found = downloader.find_existing_download_path(track, outdir)

            self.assertEqual(found, expected)
            self.assertTrue(downloader.already_downloaded(track, outdir))

    def test_format_download_error_is_more_helpful(self):
        track = {"id": "trk1", "artist": "Artist", "name": "Song", "duration_ms": 180000}
        msg = downloader.format_download_error(RuntimeError("Postprocessing audio conversion failed"), track)

        self.assertIn("FFmpeg", msg)
        self.assertIn("Artist - Song", msg)
        self.assertIn("conversion", msg.lower())
        self.assertIn("Manual search", msg)
        self.assertIn("youtube.com/results", msg)

    def test_download_track_falls_back_to_second_query_after_unavailable_candidate(self):
        track = {"id": "trk1", "artist": "Artist", "name": "Song", "duration_ms": 180000}
        done = []

        search1_ydl = MagicMock()
        search1_ydl.extract_info.return_value = {
            "entries": [
                {
                    "webpage_url": "https://www.youtube.com/watch?v=bad1",
                    "duration": 180,
                    "availability": "public",
                }
            ]
        }
        search1_ctx = MagicMock()
        search1_ctx.__enter__.return_value = search1_ydl
        search1_ctx.__exit__.return_value = False

        download1_ydl = MagicMock()
        download1_ydl.download.side_effect = RuntimeError("This video is not available")
        download1_ctx = MagicMock()
        download1_ctx.__enter__.return_value = download1_ydl
        download1_ctx.__exit__.return_value = False

        search2_ydl = MagicMock()
        search2_ydl.extract_info.return_value = {
            "entries": [
                {
                    "webpage_url": "https://www.youtube.com/watch?v=good",
                    "duration": 181,
                    "availability": "public",
                }
            ]
        }
        search2_ctx = MagicMock()
        search2_ctx.__enter__.return_value = search2_ydl
        search2_ctx.__exit__.return_value = False

        download2_ydl = MagicMock()
        download2_ctx = MagicMock()
        download2_ctx.__enter__.return_value = download2_ydl
        download2_ctx.__exit__.return_value = False

        search3_ydl = MagicMock()
        search3_ydl.extract_info.return_value = {
            "entries": [
                {
                    "webpage_url": "https://www.youtube.com/watch?v=good3",
                    "duration": 182,
                    "availability": "public",
                }
            ]
        }
        search3_ctx = MagicMock()
        search3_ctx.__enter__.return_value = search3_ydl
        search3_ctx.__exit__.return_value = False

        download3_ydl = MagicMock()
        download3_ctx = MagicMock()
        download3_ctx.__enter__.return_value = download3_ydl
        download3_ctx.__exit__.return_value = False

        search_ctxs = [search1_ctx, search2_ctx, search3_ctx]
        download_ctxs = [download1_ctx, download2_ctx, download3_ctx]

        def yt_factory(*args, **kwargs):
            opts = args[0] if args else kwargs
            if isinstance(opts, dict) and opts.get("format"):
                return download_ctxs.pop(0) if len(download_ctxs) > 1 else download_ctxs[0]
            return search_ctxs.pop(0) if len(search_ctxs) > 1 else search_ctxs[0]

        with tempfile.TemporaryDirectory() as outdir, \
                patch("downloader.ensure_ffmpeg_available", return_value="/ffmpeg"), \
                patch("downloader.threading.Thread", ImmediateThread), \
                patch("downloader.yt_dlp.YoutubeDL", side_effect=yt_factory):
            downloader.download_track(
                track,
                outdir,
                on_progress=lambda status, pct: None,
                on_done=lambda *args: done.append(args),
            )

        self.assertTrue(
            any(
                [
                    call(["https://www.youtube.com/watch?v=good"]) in download1_ydl.download.call_args_list,
                    call(["https://www.youtube.com/watch?v=good"]) in download2_ydl.download.call_args_list,
                    call(["https://www.youtube.com/watch?v=good"]) in download3_ydl.download.call_args_list,
                ]
            )
        )
        self.assertEqual(done, [("trk1", True, os.path.join(outdir, "Artist - Song.mp3"))])

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

        def yt_factory(*args, **kwargs):
            opts = args[0] if args else kwargs
            return download_ctx if isinstance(opts, dict) and opts.get("format") else search_ctx

        with tempfile.TemporaryDirectory() as outdir, \
                patch("downloader.ensure_ffmpeg_available", return_value="/ffmpeg"), \
                patch("downloader.threading.Thread", ImmediateThread), \
                patch("downloader.yt_dlp.YoutubeDL", side_effect=yt_factory):
            handle = downloader.download_track(
                track,
                outdir,
                on_progress=lambda status, pct: progress.append((status, pct)),
                on_done=lambda *args: done.append(args),
            )

            self.assertFalse(handle.cancelled)

            search_ydl.extract_info.assert_has_calls(
                [
                    call("ytsearch10:Artist - Song official audio", download=False),
                    call("ytsearch10:Artist - Song", download=False),
                    call("ytsearch10:Artist Song official audio", download=False),
                ],
                any_order=False,
            )
            download_ydl.download.assert_called_once_with(["https://www.youtube.com/watch?v=good"])
            self.assertEqual(done, [
                ("trk1", True, os.path.join(outdir, "Artist - Song.mp3"))
            ])
            self.assertFalse(os.path.exists(os.path.join(outdir, ".spotifyvdj_tmp", "trk1")))


    def test_download_track_uses_manual_source_url_when_provided(self):
        track = {"id": "trk1", "artist": "Artist", "name": "Song", "duration_ms": 180000}
        done = []

        download_ydl = MagicMock()
        download_ctx = MagicMock()
        download_ctx.__enter__.return_value = download_ydl
        download_ctx.__exit__.return_value = False

        with tempfile.TemporaryDirectory() as outdir, \
                patch("downloader.ensure_ffmpeg_available", return_value="/ffmpeg"), \
                patch("downloader.threading.Thread", ImmediateThread), \
                patch("downloader.yt_dlp.YoutubeDL", return_value=download_ctx):
            downloader.download_track(
                track,
                outdir,
                source_url="https://www.youtube.com/watch?v=manual",
                on_progress=lambda status, pct: None,
                on_done=lambda *args: done.append(args),
            )

        download_ydl.download.assert_called_once_with(["https://www.youtube.com/watch?v=manual"])
        self.assertEqual(done, [("trk1", True, os.path.join(outdir, "Artist - Song.mp3"))])

    def test_download_track_continues_after_search_error(self):
        track = {"id": "trk1", "artist": "Artist", "name": "Song", "duration_ms": 180000}
        done = []

        search1_ctx = MagicMock()
        search1_ydl = MagicMock()
        search1_ydl.extract_info.side_effect = RuntimeError("timeout")
        search1_ctx.__enter__.return_value = search1_ydl
        search1_ctx.__exit__.return_value = False

        search2_ctx = MagicMock()
        search2_ydl = MagicMock()
        search2_ydl.extract_info.return_value = {
            "entries": [
                {
                    "webpage_url": "https://www.youtube.com/watch?v=good",
                    "duration": 180,
                    "availability": "public",
                }
            ]
        }
        search2_ctx.__enter__.return_value = search2_ydl
        search2_ctx.__exit__.return_value = False

        download_ctx = MagicMock()
        download_ydl = MagicMock()
        download_ctx.__enter__.return_value = download_ydl
        download_ctx.__exit__.return_value = False

        search_ctxs = [search1_ctx, search2_ctx]
        download_ctxs = [download_ctx]

        def yt_factory(*args, **kwargs):
            opts = args[0] if args else kwargs
            if isinstance(opts, dict) and opts.get("format"):
                return download_ctxs.pop(0) if len(download_ctxs) > 1 else download_ctxs[0]
            return search_ctxs.pop(0) if len(search_ctxs) > 1 else search_ctxs[0]

        with tempfile.TemporaryDirectory() as outdir, \
                patch("downloader.ensure_ffmpeg_available", return_value="/ffmpeg"), \
                patch("downloader.threading.Thread", ImmediateThread), \
                patch("downloader.yt_dlp.YoutubeDL", side_effect=yt_factory):
            downloader.download_track(
                track,
                outdir,
                on_progress=lambda status, pct: None,
                on_done=lambda *args: done.append(args),
            )

        self.assertEqual(search1_ydl.extract_info.call_count, 1)
        self.assertGreaterEqual(search2_ydl.extract_info.call_count, 1)
        download_ydl.download.assert_called_once_with(["https://www.youtube.com/watch?v=good"])
        self.assertEqual(done, [("trk1", True, os.path.join(outdir, "Artist - Song.mp3"))])

    def test_find_existing_download_path_ignores_missing_known_paths(self):
        track = {"id": "trk1", "artist": "Artist", "name": "Song", "duration_ms": 180000}
        with tempfile.TemporaryDirectory() as outdir:
            missing = os.path.join(outdir, "Artist - Song.mp3")
            found = downloader.find_existing_download_path(track, outdir, known_paths=[missing])

        self.assertIsNone(found)

    def test_build_download_index_ignores_temporary_download_artifacts(self):
        with tempfile.TemporaryDirectory() as outdir:
            temp_dir = os.path.join(outdir, ".spotifyvdj_tmp", "trk1")
            os.makedirs(temp_dir, exist_ok=True)
            temp_file = os.path.join(temp_dir, "Artist - Song.mp3")
            with open(temp_file, "wb") as f:
                f.write(b"x")

            index = downloader.build_download_index(outdir)

        self.assertEqual(index, [])


if __name__ == "__main__":
    unittest.main()

