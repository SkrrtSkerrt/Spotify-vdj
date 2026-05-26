import unittest
from unittest.mock import MagicMock, patch

import spotify_client


class SpotifyClientRedirectUriTests(unittest.TestCase):
    def test_busy_redirect_port_raises_clear_error(self):
        fake_socket = MagicMock()

        with patch("spotify_client.socket.create_connection", return_value=fake_socket), \
             patch("spotify_client.SpotifyOAuth") as oauth_mock, \
             patch("spotify_client.spotipy.Spotify") as spotify_mock:
            with self.assertRaises(RuntimeError) as ctx:
                spotify_client.create_client(
                    "client-id",
                    "client-secret",
                    "http://127.0.0.1:8888/callback",
                )

        self.assertIn("8888", str(ctx.exception))
        oauth_mock.assert_not_called()
        spotify_mock.assert_not_called()
        fake_socket.close.assert_called_once()

    def test_free_redirect_port_creates_client(self):
        auth = MagicMock()
        sp_instance = MagicMock()

        with patch("spotify_client.socket.create_connection", side_effect=OSError), \
             patch("spotify_client.SpotifyOAuth", return_value=auth) as oauth_mock, \
             patch("spotify_client.spotipy.Spotify", return_value=sp_instance) as spotify_mock:
            result = spotify_client.create_client(
                "client-id",
                "client-secret",
                "http://127.0.0.1:9999/callback",
            )

        self.assertIs(result, sp_instance)
        oauth_mock.assert_called_once()
        spotify_mock.assert_called_once_with(auth_manager=auth)


class SpotifyClientPlaylistTests(unittest.TestCase):
    def test_get_playlists_prefers_list_response_total(self):
        sp = MagicMock()
        sp.current_user_playlists.return_value = {
            "items": [
                {
                    "id": "abc",
                    "name": "My Playlist",
                    "images": [{"url": "https://example.com/cover.jpg"}],
                    "items": {"href": "https://api.spotify.com/v1/playlists/abc/items", "total": 17},
                }
            ],
            "next": None,
        }

        playlists = spotify_client.get_playlists(sp)

        self.assertEqual(playlists, [
            {
                "id": "abc",
                "name": "My Playlist",
                "total": 17,
                "image": "https://example.com/cover.jpg",
            }
        ])
        sp.playlist.assert_not_called()

    def test_get_playlists_uses_playlist_total_fallback(self):
        sp = MagicMock()
        sp.current_user_playlists.return_value = {
            "items": [
                {
                    "id": "abc",
                    "name": "My Playlist",
                    "images": [{"url": "https://example.com/cover.jpg"}],
                }
            ],
            "next": None,
        }
        sp.playlist.return_value = {"tracks": {"total": 17}}

        playlists = spotify_client.get_playlists(sp)

        self.assertEqual(playlists, [
            {
                "id": "abc",
                "name": "My Playlist",
                "total": 17,
                "image": "https://example.com/cover.jpg",
            }
        ])
        sp.playlist.assert_called_once_with("abc", fields="tracks.total")

    def test_get_playlists_network_errors_are_user_friendly(self):
        sp = MagicMock()
        sp.current_user_playlists.side_effect = TimeoutError("request timed out")

        with self.assertRaises(RuntimeError) as ctx:
            spotify_client.get_playlists(sp)

        self.assertIn("timed out", str(ctx.exception).lower())
        self.assertIn("network", str(ctx.exception).lower())

    def test_get_tracks_keeps_local_playlist_items(self):
        sp = MagicMock()
        sp.playlist_tracks.return_value = {
            "items": [
                {
                    "track": {
                        "id": None,
                        "uri": "spotify:local:123",
                        "is_local": True,
                        "name": "My Local Track",
                        "artists": [{"name": "Local Artist"}],
                        "album": {"name": "Local Album", "images": []},
                        "duration_ms": 123000,
                        "preview_url": None,
                    }
                }
            ],
            "next": None,
        }

        tracks = spotify_client.get_tracks(sp, "playlist-1")

        self.assertEqual(len(tracks), 1)
        self.assertEqual(tracks[0]["id"], "spotify:local:123")
        self.assertTrue(tracks[0]["is_local"])
        self.assertEqual(tracks[0]["name"], "My Local Track")
        self.assertEqual(tracks[0]["artist"], "Local Artist")

    def test_get_tracks_handles_missing_album_and_artist_metadata(self):
        sp = MagicMock()
        sp.playlist_tracks.return_value = {
            "items": [
                {
                    "track": {
                        "id": "abc",
                        "uri": "spotify:track:abc",
                        "name": "Mystery Track",
                        "artists": None,
                        "album": None,
                        "duration_ms": 90000,
                        "preview_url": None,
                    }
                }
            ],
            "next": None,
        }

        tracks = spotify_client.get_tracks(sp, "playlist-2")

        self.assertEqual(tracks[0]["id"], "abc")
        self.assertEqual(tracks[0]["artist"], "")
        self.assertEqual(tracks[0]["album"], "")

    def test_get_tracks_recovers_tracks_around_local_file_boundaries(self):
        sp = MagicMock()

        def playlist_tracks(playlist_id, limit=50, offset=0):
            del playlist_id
            start = offset
            end = offset + limit
            local_index = 3
            total = 6

            if start <= local_index < end:
                return {"items": [], "next": None}

            items = []
            for index in range(start, min(end, total)):
                items.append(
                    {
                        "track": {
                            "id": f"track-{index}",
                            "uri": f"spotify:track:{index}",
                            "name": f"Track {index}",
                            "artists": [{"name": "Artist"}],
                            "album": {"name": "Album", "images": []},
                            "duration_ms": 180000,
                            "preview_url": None,
                        }
                    }
                )
            return {"items": items, "next": None if end >= total else "next"}

        sp.playlist_tracks.side_effect = playlist_tracks

        tracks = spotify_client.get_tracks(sp, "playlist-1")

        self.assertEqual([t["id"] for t in tracks], ["track-0", "track-1", "track-2", "track-4", "track-5"])
        self.assertTrue(any(call.kwargs.get("limit") < 100 for call in sp.playlist_tracks.mock_calls))
        self.assertTrue(any(call.kwargs.get("offset") == 3 for call in sp.playlist_tracks.mock_calls))

    def test_get_tracks_recovers_when_page_has_only_null_track_items(self):
        sp = MagicMock()

        def playlist_tracks(playlist_id, limit=50, offset=0):
            del playlist_id
            total = 6
            if offset == 0:
                return {
                    "items": [
                        {"track": None},
                        {"track": None},
                        {"track": None},
                    ],
                    "next": None,
                }
            items = []
            for index in range(offset, min(offset + limit, total)):
                items.append(
                    {
                        "track": {
                            "id": f"track-{index}",
                            "uri": f"spotify:track:{index}",
                            "name": f"Track {index}",
                            "artists": [{"name": "Artist"}],
                            "album": {"name": "Album", "images": []},
                            "duration_ms": 180000,
                            "preview_url": None,
                        }
                    }
                )
            return {"items": items, "next": None if offset + limit >= total else "next"}

        sp.playlist_tracks.side_effect = playlist_tracks

        tracks = spotify_client.get_tracks(sp, "playlist-1")

        self.assertEqual([t["id"] for t in tracks], ["track-1", "track-2", "track-3", "track-4", "track-5"])
        self.assertGreater(len(sp.playlist_tracks.mock_calls), 1)

    def test_get_tracks_reports_forbidden_playlists_cleanly(self):
        sp = MagicMock()
        sp.playlist_tracks.side_effect = Exception("HTTP status 403, code 1")

        with self.assertRaises(RuntimeError) as ctx:
            spotify_client.get_tracks(sp, "playlist-403")

        self.assertIn("403", str(ctx.exception))
        self.assertIn("removed", str(ctx.exception).lower())

    def test_get_tracks_falls_back_to_playlist_endpoint_item_rows(self):
        sp = MagicMock()
        sp.playlist_tracks.return_value = {"items": [], "next": None}
        sp.me.return_value = {"country": "US"}
        sp.playlist.return_value = {
            "tracks": {
                "items": [
                    {
                        "item": {
                            "type": "track",
                            "id": "abc",
                            "uri": "spotify:track:abc",
                            "name": "Fallback Track",
                            "artists": [{"name": "Artist"}],
                            "album": {"name": "Album", "images": []},
                            "duration_ms": 210000,
                            "preview_url": None,
                        }
                    }
                ],
                "next": None,
            }
        }

        tracks = spotify_client.get_tracks(sp, "playlist-1")

        self.assertEqual([t["id"] for t in tracks], ["abc"])
        sp.playlist.assert_called_once_with(
            "playlist-1",
            additional_types=("track",),
            market="US",
        )


if __name__ == "__main__":
    unittest.main()
