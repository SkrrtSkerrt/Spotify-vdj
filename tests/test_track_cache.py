import os
import tempfile
import unittest
from typing import cast

import track_cache


class TrackCacheTests(unittest.TestCase):
    def test_save_and_load_round_trip_for_playlist(self):
        tracks = [
            {
                "id": "track-1",
                "name": "Test Song",
                "artist": "Test Artist",
                "album": "Test Album",
                "playlist_position": 1,
                "downloadable": True,
            }
        ]

        with tempfile.TemporaryDirectory() as tmpdir:
            cache_path = os.path.join(tmpdir, "tracks.json")
            track_cache.save(
                "playlist-1",
                tracks,
                account_id="user-1",
                playlist_name="Playlist 1",
                playlist_total=42,
                path=cache_path,
            )

            loaded = track_cache.load("playlist-1", account_id="user-1", path=cache_path)

        self.assertIsNotNone(loaded)
        loaded_payload = cast(dict, loaded)
        self.assertEqual(loaded_payload["playlist_id"], "playlist-1")
        self.assertEqual(loaded_payload["playlist_name"], "Playlist 1")
        self.assertEqual(loaded_payload["playlist_total"], 42)
        self.assertEqual(loaded_payload["tracks"], tracks)
        self.assertIn("updated_at", loaded_payload)

    def test_load_returns_none_for_mismatched_account(self):
        tracks = [{"id": "track-1", "name": "Test Song"}]

        with tempfile.TemporaryDirectory() as tmpdir:
            cache_path = os.path.join(tmpdir, "tracks.json")
            track_cache.save("playlist-1", tracks, account_id="user-1", path=cache_path)

            loaded = track_cache.load("playlist-1", account_id="user-2", path=cache_path)

        self.assertIsNone(loaded)

    def test_load_sanitizes_malformed_track_entries(self):
        payload = {
            "updated_at": "2026-05-27T12:00:00Z",
            "account_id": "user-1",
            "playlist_id": "playlist-1",
            "playlist_name": "Playlist 1",
            "playlist_total": 3,
            "tracks": [
                "not-a-dict",
                {"id": "track-1", "name": "Good Track", "downloadable": True},
                {"name": "Missing Id"},
            ],
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            cache_path = os.path.join(tmpdir, "tracks.json")
            with open(cache_path, "w", encoding="utf-8") as f:
                import json
                json.dump(payload, f)

            loaded = track_cache.load("playlist-1", account_id="user-1", path=cache_path)

        self.assertIsNotNone(loaded)
        loaded_payload = cast(dict, loaded)
        self.assertEqual(loaded_payload["tracks"], [{"id": "track-1", "name": "Good Track", "downloadable": True}])
        self.assertEqual(loaded_payload["playlist_id"], "playlist-1")

    def test_describe_age_and_staleness_helpers(self):
        payload = {"updated_at": "2026-05-27T12:00:00Z"}

        self.assertEqual(track_cache.describe_age(payload, now="2026-05-27T12:05:00Z"), "cached 5m ago")
        self.assertEqual(track_cache.payload_age_seconds(payload, now="2026-05-27T12:05:00Z"), 300)
        self.assertFalse(track_cache.is_stale(payload, max_age_seconds=600, now="2026-05-27T12:05:00Z"))
        self.assertTrue(track_cache.is_stale(payload, max_age_seconds=120, now="2026-05-27T12:05:00Z"))
