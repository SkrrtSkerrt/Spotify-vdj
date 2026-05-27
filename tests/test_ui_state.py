import os
import tempfile
import unittest
from typing import cast

import ui_state


class UIStateTests(unittest.TestCase):
    def test_save_and_load_round_trip_preserves_runtime_state(self):
        payload = {
            "account_id": "user-1",
            "last_playlist_id": "playlist-1",
            "playlist_refresh_cooldown_until": "2026-05-27T12:10:00Z",
            "queue_entries": [
                {
                    "playlist_id": "playlist-1",
                    "track_id": "track-1",
                    "track": {"id": "track-1", "name": "Song", "artist": "Artist"},
                    "source_url": "https://youtu.be/example",
                    "status": "Queued",
                    "progress": 0,
                }
            ],
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            cache_path = os.path.join(tmpdir, "state.json")
            ui_state.save(payload, path=cache_path)
            loaded = ui_state.load(path=cache_path)

        self.assertIsNotNone(loaded)
        loaded_payload = cast(dict, loaded)
        self.assertEqual(loaded_payload["account_id"], "user-1")
        self.assertEqual(loaded_payload["last_playlist_id"], "playlist-1")
        self.assertEqual(loaded_payload["playlist_refresh_cooldown_until"], "2026-05-27T12:10:00Z")
        self.assertEqual(loaded_payload["queue_entries"], payload["queue_entries"])
        self.assertIn("updated_at", loaded_payload)

    def test_load_returns_none_for_mismatched_account(self):
        payload = {
            "account_id": "user-1",
            "last_playlist_id": "playlist-1",
            "queue_entries": [],
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            cache_path = os.path.join(tmpdir, "state.json")
            with open(cache_path, "w", encoding="utf-8") as f:
                import json
                json.dump(payload, f)

            loaded = ui_state.load(account_id="user-2", path=cache_path)

        self.assertIsNone(loaded)

    def test_load_sanitizes_invalid_queue_entries(self):
        payload = {
            "updated_at": "2026-05-27T12:00:00Z",
            "account_id": "user-1",
            "last_playlist_id": "playlist-1",
            "queue_entries": [
                "not-a-dict",
                {"playlist_id": "playlist-1", "track_id": "track-1", "track": {"id": "track-1", "name": "Song"}, "status": "Queued"},
                {"playlist_id": "playlist-1", "track_id": "", "track": {"id": "track-2", "name": "Song 2"}},
            ],
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            cache_path = os.path.join(tmpdir, "state.json")
            with open(cache_path, "w", encoding="utf-8") as f:
                import json
                json.dump(payload, f)
            loaded = ui_state.load(path=cache_path)

        self.assertIsNotNone(loaded)
        loaded_payload = cast(dict, loaded)
        self.assertEqual(len(loaded_payload["queue_entries"]), 1)
        self.assertEqual(loaded_payload["queue_entries"][0]["track_id"], "track-1")

    def test_clear_removes_state_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_path = os.path.join(tmpdir, "state.json")
            ui_state.save({"last_playlist_id": "playlist-1"}, path=cache_path)
            self.assertTrue(os.path.exists(cache_path))

            ui_state.clear(path=cache_path)

            self.assertFalse(os.path.exists(cache_path))
            self.assertIsNone(ui_state.load(path=cache_path))


if __name__ == "__main__":
    unittest.main()
