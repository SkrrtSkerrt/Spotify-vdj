import socket
from urllib.parse import urlparse

import spotipy
from spotipy.oauth2 import SpotifyOAuth

SCOPES = "playlist-read-private playlist-read-collaborative user-library-read"


def ensure_redirect_uri_port_available(redirect_uri: str) -> None:
    parsed = urlparse(redirect_uri)
    host = parsed.hostname
    port = parsed.port
    if not host or not port:
        raise ValueError(f"Invalid redirect URI: {redirect_uri}")

    try:
        sock = socket.create_connection((host, port), timeout=0.25)
    except OSError:
        return
    else:
        sock.close()
        raise RuntimeError(
            f"Callback port {port} on {host} is already in use. "
            "Choose a different Redirect URI in Settings and in your Spotify app."
        )


def create_client(client_id: str, client_secret: str, redirect_uri: str) -> spotipy.Spotify:
    ensure_redirect_uri_port_available(redirect_uri)
    auth = SpotifyOAuth(
        client_id=client_id,
        client_secret=client_secret,
        redirect_uri=redirect_uri,
        scope=SCOPES,
        open_browser=True,
        cache_path=".spotify_token_cache",
    )
    return spotipy.Spotify(auth_manager=auth)


def _playlist_total(sp: spotipy.Spotify, playlist_id: str, item: dict) -> int:
    tracks = item.get("tracks") or {}
    total = tracks.get("total")
    if isinstance(total, int) and total > 0:
        return total

    try:
        full = sp.playlist(playlist_id, fields="tracks.total")
        return full.get("tracks", {}).get("total", total or 0)
    except Exception:
        return total or 0


def get_playlists(sp: spotipy.Spotify) -> list[dict]:
    playlists = []
    result = sp.current_user_playlists(limit=50)
    while result:
        for item in result["items"]:
            if item:
                playlists.append({
                    "id": item["id"],
                    "name": item["name"],
                    "total": _playlist_total(sp, item["id"], item),
                    "image": item["images"][0]["url"] if item.get("images") else None,
                })
        result = sp.next(result) if result.get("next") else None
    return playlists


def get_tracks(sp: spotipy.Spotify, playlist_id: str) -> list[dict]:
    tracks = []
    result = sp.playlist_tracks(playlist_id, limit=100)
    while result:
        for item in result["items"]:
            if not item or not item.get("track"):
                continue
            track = item["track"]
            if track.get("is_local"):
                continue
            artists = ", ".join(a["name"] for a in track.get("artists", []))
            album = track.get("album", {})
            image = album.get("images", [{}])[0].get("url") if album.get("images") else None
            tracks.append({
                "id": track["id"],
                "name": track["name"],
                "artist": artists,
                "album": album.get("name", ""),
                "duration_ms": track.get("duration_ms", 0),
                "image": image,
                "preview_url": track.get("preview_url"),
            })
        result = sp.next(result) if result.get("next") else None
    return tracks


def get_liked_tracks(sp: spotipy.Spotify) -> list[dict]:
    tracks = []
    result = sp.current_user_saved_tracks(limit=50)
    while result:
        for item in result["items"]:
            if not item or not item.get("track"):
                continue
            track = item["track"]
            artists = ", ".join(a["name"] for a in track.get("artists", []))
            album = track.get("album", {})
            image = album.get("images", [{}])[0].get("url") if album.get("images") else None
            tracks.append({
                "id": track["id"],
                "name": track["name"],
                "artist": artists,
                "album": album.get("name", ""),
                "duration_ms": track.get("duration_ms", 0),
                "image": image,
                "preview_url": track.get("preview_url"),
            })
        result = sp.next(result) if result.get("next") else None
    return tracks
