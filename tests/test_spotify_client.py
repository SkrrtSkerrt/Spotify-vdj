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


if __name__ == "__main__":
    unittest.main()
