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
    candidates = []

    for key in ("tracks", "items"):
        container = item.get(key) or {}
        total = container.get("total")
        if isinstance(total, int):
            candidates.append(total)
            if total > 0:
                return total

    try:
        full = sp.playlist(playlist_id, fields="tracks.total")
        total = (full.get("tracks") or {}).get("total")
        if isinstance(total, int):
            candidates.append(total)
            if total > 0:
                return total
    except Exception:
        pass

    return next((total for total in candidates if isinstance(total, int)), 0)


def _playlist_list_error(error: Exception) -> RuntimeError:
    details = str(error).strip() or error.__class__.__name__
    lowered = details.lower()
    if "401" in lowered or "unauthorized" in lowered or "invalid token" in lowered:
        return RuntimeError(
            "Spotify authentication failed while loading playlists. "
            "Please re-check your Client ID, Client Secret, and redirect URI, then sign in again."
        )
    if "403" in lowered or "forbidden" in lowered:
        return RuntimeError(
            "Spotify refused access while loading playlists (HTTP 403). "
            "The account may not have permission to read one or more playlists, or Spotify may be rate-limiting the request."
        )
    if "timeout" in lowered or "timed out" in lowered or "connection" in lowered or "network" in lowered:
        return RuntimeError(
            "Spotify playlists could not be loaded because the network request failed or timed out. "
            "Check your internet connection and try again."
        )
    return RuntimeError(details)


def _build_track_entry(track: dict, playlist_id: str, index: int) -> dict:
    artists = ", ".join(
        a.get("name", "") for a in (track.get("artists") or [])
        if isinstance(a, dict) and a.get("name")
    )
    album = track.get("album") or {}
    if not isinstance(album, dict):
        album = {}
    images = album.get("images") or []
    image = images[0].get("url") if images and isinstance(images[0], dict) else None
    track_id = track.get("id") or track.get("uri") or f"{playlist_id}:{index}"
    return {
        "id": track_id,
        "name": track.get("name", ""),
        "artist": artists,
        "album": album.get("name", ""),
        "duration_ms": track.get("duration_ms", 0),
        "image": image,
        "preview_url": track.get("preview_url"),
        "is_local": bool(track.get("is_local")),
    }


def _fetch_playlist_tracks_range(
    sp: spotipy.Spotify,
    playlist_id: str,
    offset: int,
    limit: int,
    seen: set[str] | None = None,
) -> list[dict]:
    if seen is None:
        seen = set()
    if limit <= 0:
        return []

    result = sp.playlist_tracks(playlist_id, limit=limit, offset=offset)
    items = result.get("items") or []

    if items:
        tracks = []
        index = offset
        for item in items:
            if not item or not item.get("track"):
                index += 1
                continue
            entry = _build_track_entry(item["track"], playlist_id, index)
            if entry["id"] not in seen:
                tracks.append(entry)
                seen.add(entry["id"])
            index += 1

        if result.get("next"):
            tracks.extend(_fetch_playlist_tracks_range(sp, playlist_id, offset + limit, limit, seen))
        return tracks

    if limit == 1:
        return []

    left = limit // 2
    right = limit - left
    return _fetch_playlist_tracks_range(sp, playlist_id, offset, left, seen) + _fetch_playlist_tracks_range(sp, playlist_id, offset + left, right, seen)


def _playlist_access_error(error: Exception, playlist_id: str) -> RuntimeError:
    details = str(error).strip() or error.__class__.__name__
    lowered = details.lower()
    if "403" in lowered or "code 1" in lowered or "forbidden" in lowered:
        return RuntimeError(
            f"Spotify refused access to playlist {playlist_id} (HTTP 403, code 1). "
            "The playlist may have been removed, made unavailable, or your account may not have access to its tracks."
        )
    return RuntimeError(details)


def get_playlists(sp: spotipy.Spotify) -> list[dict]:
    playlists = []
    try:
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
    except Exception as e:
        raise _playlist_list_error(e) from e
    return playlists


def get_tracks(sp: spotipy.Spotify, playlist_id: str) -> list[dict]:
    try:
        return _fetch_playlist_tracks_range(sp, playlist_id, 0, 100)
    except Exception as e:
        raise _playlist_access_error(e, playlist_id) from e


def get_liked_tracks(sp: spotipy.Spotify) -> list[dict]:
    tracks = []
    result = sp.current_user_saved_tracks(limit=50)
    while result:
        for index, item in enumerate(result["items"], start=len(tracks)):
            if not item or not item.get("track"):
                continue
            track = item["track"]
            tracks.append(_build_track_entry(track, "liked", index))
        result = sp.next(result) if result.get("next") else None
    return tracks
