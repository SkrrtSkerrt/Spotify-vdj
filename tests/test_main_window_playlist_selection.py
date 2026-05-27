import unittest

from gui.main_window import _resolve_playlist_selection


class PlaylistSelectionTests(unittest.TestCase):
    def test_resolve_playlist_selection_uses_existing_match_or_first_playlist(self):
        playlists = [
            {"id": "a", "name": "A"},
            {"id": "b", "name": "B"},
        ]

        self.assertEqual(_resolve_playlist_selection(playlists, "b"), "b")
        self.assertEqual(_resolve_playlist_selection(playlists, "missing"), "a")
        self.assertIsNone(_resolve_playlist_selection([], "missing"))


if __name__ == "__main__":
    unittest.main()
