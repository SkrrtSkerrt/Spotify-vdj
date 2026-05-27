import json
import os
import tempfile
import unittest
from typing import cast

import playlist_cache


class PlaylistCacheTests(unittest.TestCase):
    def test_save_and_load_round_trip_preserves_playlist_payload(self):
        playlists = [
            {
                "id": "abc",
                "name": "My Playlist",
                "total": 17,
                "image": "https://example.com/cover.jpg",
                "description": "A test playlist",
                "owner_name": "Operator",
                "public": True,
            }
        ]

        with tempfile.TemporaryDirectory() as tmpdir:
            cache_path = os.path.join(tmpdir, "playlists.json")
            playlist_cache.save(
                playlists,
                account_id="user-1",
                selected_playlist_id="abc",
                path=cache_path,
            )
            payload = playlist_cache.load(path=cache_path)

        self.assertIsInstance(payload, dict)
        self.assertEqual(payload["account_id"], "user-1")
        self.assertEqual(payload["selected_playlist_id"], "abc")
        self.assertEqual(payload["playlists"], playlists)
        self.assertIn("updated_at", payload)

    def test_load_returns_none_for_corrupt_json(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_path = os.path.join(tmpdir, "playlists.json")
            with open(cache_path, "w", encoding="utf-8") as f:
                f.write("{ not valid json")

            payload = playlist_cache.load(path=cache_path)

        self.assertIsNone(payload)

    def test_clear_removes_cache_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_path = os.path.join(tmpdir, "playlists.json")
            playlist_cache.save([], path=cache_path)
            self.assertTrue(os.path.exists(cache_path))

            playlist_cache.clear(path=cache_path)

            self.assertFalse(os.path.exists(cache_path))
            self.assertIsNone(playlist_cache.load(path=cache_path))

    def test_describe_age_reports_human_readable_age(self):
        payload = {"updated_at": "2026-05-27T12:00:00Z"}

        label = playlist_cache.describe_age(payload, now="2026-05-27T12:05:00Z")

        self.assertEqual(label, "cached 5m ago")

    def test_payload_age_seconds_and_staleness_helpers(self):
        payload = {"updated_at": "2026-05-27T12:00:00Z"}

        self.assertEqual(playlist_cache.payload_age_seconds(payload, now="2026-05-27T12:05:00Z"), 300)
        self.assertFalse(playlist_cache.is_stale(payload, max_age_seconds=600, now="2026-05-27T12:05:00Z"))
        self.assertTrue(playlist_cache.is_stale(payload, max_age_seconds=120, now="2026-05-27T12:05:00Z"))

    def test_cache_matches_account_only_when_ids_align(self):
        payload = {"account_id": "user-1"}

        self.assertTrue(playlist_cache.cache_matches_account(payload, "user-1"))
        self.assertFalse(playlist_cache.cache_matches_account(payload, "user-2"))
        self.assertTrue(playlist_cache.cache_matches_account({"account_id": None}, "user-2"))

    def test_load_sanitizes_malformed_playlist_entries(self):
        payload = {
            "updated_at": "2026-05-27T12:00:00Z",
            "account_id": "user-1",
            "selected_playlist_id": "missing",
            "playlists": [
                "not-a-dict",
                {"id": "abc", "name": "Good Playlist", "total": "5"},
                {"name": "Missing Id"},
            ],
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            cache_path = os.path.join(tmpdir, "playlists.json")
            with open(cache_path, "w", encoding="utf-8") as f:
                json.dump(payload, f)

            loaded = playlist_cache.load(path=cache_path)

        self.assertIsNotNone(loaded)
        loaded_payload = cast(dict, loaded)
        self.assertEqual(loaded_payload["playlists"], [{"id": "abc", "name": "Good Playlist", "total": 5}])
        self.assertIsNone(loaded_payload["selected_playlist_id"])
