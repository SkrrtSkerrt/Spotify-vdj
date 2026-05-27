import re
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
    return spotipy.Spotify(
        auth_manager=auth,
        requests_timeout=10,
        retries=2,
        status_retries=0,
        backoff_factor=0.2,
    )


def extract_retry_after_seconds(details: str) -> int | None:
    return _retry_after_hint(details)


def _retry_after_hint(details: str) -> int | None:
    patterns = [
        r"retry[- ]?after[^0-9]*(\d+)",
        r"retry[- ]?after\s*[:=]\s*(\d+)",
        r"\b(\d+)\s*s\b",
    ]
    for pattern in patterns:
        match = re.search(pattern, details, flags=re.IGNORECASE)
        if match:
            try:
                value = int(match.group(1))
            except ValueError:
                continue
            if value > 0:
                return value
    return None


def _best_image_url(images: list[dict] | None) -> str | None:
    if not images:
        return None

    best_url = None
    best_area = -1
    for image in images:
        if not isinstance(image, dict):
            continue
        url = image.get("url")
        if not url:
            continue
        width = image.get("width")
        height = image.get("height")
        if isinstance(width, int) and isinstance(height, int):
            area = width * height
        else:
            area = 0
        if area > best_area:
            best_area = area
            best_url = url

    return best_url


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
    if "429" in lowered or "too many requests" in lowered or "rate limit" in lowered:
        retry_after = _retry_after_hint(details)
        retry_text = f" Retry-After: {retry_after}s." if retry_after else ""
        return RuntimeError(
            "Spotify is rate-limiting playlist loading (HTTP 429)."
            f"{retry_text} Please wait a few minutes and try again, or reopen the app later."
        )
    if "403" in lowered or "forbidden" in lowered:
        return RuntimeError(
            "Spotify refused access while loading playlists (HTTP 403). "
            "The account may not have permission to read one or more playlists."
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
    image = _best_image_url(images)
    track_id = track.get("id") or track.get("uri") or f"{playlist_id}:{index}"
    media_type = track.get("type") or "track"
    is_local = bool(track.get("is_local"))
    downloadable = media_type == "track" and not is_local and track.get("duration_ms", 0) > 0
    entry = {
        "id": track_id,
        "name": track.get("name", ""),
        "artist": artists,
        "album": album.get("name", ""),
        "duration_ms": track.get("duration_ms", 0),
        "image": image,
        "preview_url": track.get("preview_url"),
        "is_local": is_local,
        "downloadable": downloadable,
        "media_type": media_type,
        "playlist_position": index + 1,
        "track_number": track.get("track_number"),
        "disc_number": track.get("disc_number"),
    }
    if media_type != "track" or is_local:
        entry["unsupported_reason"] = (
            "Spotify local files cannot be downloaded." if is_local else f"Spotify {media_type} items are not downloadable."
        )
    return entry


def _build_playlist_entry(row: dict, playlist_id: str, index: int) -> dict | None:
    if not isinstance(row, dict):
        return None

    track = row.get("track")
    if isinstance(track, dict):
        entry = _build_track_entry(track, playlist_id, index)
        if not entry.get("downloadable", False):
            entry.setdefault("unsupported_reason", "Spotify track items are not downloadable.")
        return entry

    item = row.get("item")
    if isinstance(item, dict):
        if item.get("type") == "track":
            entry = _build_track_entry(item, playlist_id, index)
            if not entry.get("downloadable", False):
                entry.setdefault("unsupported_reason", "Spotify track items are not downloadable.")
            return entry

        show = item.get("show") if isinstance(item.get("show"), dict) else None
        entry = {
            "id": item.get("id") or item.get("uri") or f"{playlist_id}:{index}",
            "name": item.get("name", "Unavailable Spotify item"),
            "artist": (show.get("name") or show.get("publisher") or "") if show else "",
            "album": show.get("name", "") if show else "",
            "duration_ms": item.get("duration_ms", 0),
            "image": _best_image_url(show.get("images") if show else None),
            "preview_url": item.get("preview_url"),
            "is_local": bool(item.get("is_local")),
            "downloadable": False,
            "media_type": item.get("type") or "unknown",
            "playlist_position": index + 1,
            "unsupported_reason": f"Spotify {item.get('type', 'item')} items are not downloadable.",
        }
        return entry

    return None


def _fetch_playlist_tracks_page(
    sp: spotipy.Spotify,
    playlist_id: str,
    seen: set[str],
    page: dict | None = None,
) -> list[dict]:
    if page is None:
        market = None
        try:
            profile = sp.me()
            if isinstance(profile, dict):
                market = profile.get("country")
        except Exception:
            pass

        playlist = sp.playlist(
            playlist_id,
            additional_types=("track",),
            market=market,
        )
        page = playlist.get("tracks") or playlist.get("items") or {}

    if not isinstance(page, dict):
        return []

    tracks = []
    index = 0
    while page:
        items = page.get("items") or []
        for row in items:
            entry = _build_playlist_entry(row, playlist_id, index)
            if entry is None:
                index += 1
                continue
            if entry["id"] not in seen:
                tracks.append(entry)
                seen.add(entry["id"])
            index += 1

        if not page.get("next"):
            break

        page = sp.next(page)
        if page is None:
            break

    return tracks


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
            entry = _build_playlist_entry(item, playlist_id, index)
            if entry is None:
                index += 1
                continue
            if entry["id"] not in seen:
                tracks.append(entry)
                seen.add(entry["id"])
            index += 1

        if tracks:
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
                        "image": _best_image_url(item.get("images")),
                        "description": item.get("description", ""),
                        "owner_name": (item.get("owner") or {}).get("display_name", ""),
                        "public": item.get("public"),
                    })
            result = sp.next(result) if result.get("next") else None
    except Exception as e:
        raise _playlist_list_error(e) from e
    return playlists


def get_tracks(sp: spotipy.Spotify, playlist_id: str) -> list[dict]:
    try:
        tracks = _fetch_playlist_tracks_range(sp, playlist_id, 0, 100)
        if tracks:
            return tracks

        fallback_tracks = _fetch_playlist_tracks_page(sp, playlist_id, set())
        if fallback_tracks:
            return fallback_tracks

        return tracks
    except Exception as e:
        try:
            fallback_tracks = _fetch_playlist_tracks_page(sp, playlist_id, set())
            if fallback_tracks:
                return fallback_tracks
        except Exception:
            pass
        raise _playlist_access_error(e, playlist_id) from e


def get_liked_tracks(sp: spotipy.Spotify) -> list[dict]:
    tracks = []
    result = sp.current_user_saved_tracks(limit=50)
    while result:
        row_index = len(tracks)
        for item in result["items"]:
            if not item or not item.get("track"):
                row_index += 1
                continue
            track = item["track"]
            tracks.append(_build_track_entry(track, "liked", row_index))
            row_index += 1
        result = sp.next(result) if result.get("next") else None
    return tracks
