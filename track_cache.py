import json
import os
import re
from datetime import datetime, timezone

CACHE_DIR = os.path.join(os.path.expanduser("~"), ".spotify_vdj_tracks_cache")


def _safe_component(value: str | None, fallback: str) -> str:
    text = str(value or "").strip()
    if not text:
        return fallback
    text = re.sub(r"[^A-Za-z0-9_.-]+", "_", text)
    text = text.strip("._-")
    return text or fallback


def _default_cache_path(playlist_id: str, account_id: str | None = None) -> str:
    account_part = _safe_component(account_id, "shared")
    playlist_part = _safe_component(playlist_id, "playlist")
    return os.path.join(CACHE_DIR, account_part, f"{playlist_part}.json")


def _cache_path(playlist_id: str, account_id: str | None = None, path: str | None = None) -> str:
    return path or _default_cache_path(playlist_id, account_id)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_iso_timestamp(value: str | None) -> datetime | None:
    if not value or not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _sanitize_track_entry(entry: dict) -> dict | None:
    if not isinstance(entry, dict):
        return None

    track_id = entry.get("id")
    if not track_id:
        return None

    sanitized = dict(entry)
    sanitized["id"] = str(track_id)
    sanitized["name"] = str(entry.get("name", ""))

    playlist_position = entry.get("playlist_position")
    if playlist_position is not None:
        if isinstance(playlist_position, bool):
            playlist_position = None
        elif not isinstance(playlist_position, int):
            try:
                playlist_position = int(str(playlist_position))
            except (TypeError, ValueError):
                playlist_position = None
        if playlist_position is not None:
            sanitized["playlist_position"] = playlist_position

    if "duration_ms" in sanitized:
        duration_value = entry.get("duration_ms")
        if isinstance(duration_value, bool):
            duration_value = None
        elif duration_value is not None and not isinstance(duration_value, int):
            try:
                duration_value = int(str(duration_value))
            except (TypeError, ValueError):
                duration_value = None
        if duration_value is None:
            sanitized.pop("duration_ms", None)
        else:
            sanitized["duration_ms"] = duration_value

    return sanitized


def payload_age_seconds(payload: dict | None, now: str | datetime | None = None) -> int | None:
    if not isinstance(payload, dict):
        return None
    updated_at = _parse_iso_timestamp(payload.get("updated_at"))
    if updated_at is None:
        return None

    if isinstance(now, datetime):
        current = now
    elif isinstance(now, str):
        current = _parse_iso_timestamp(now)
    else:
        current = datetime.now(timezone.utc)

    if current is None:
        current = datetime.now(timezone.utc)
    if updated_at.tzinfo is None:
        updated_at = updated_at.replace(tzinfo=timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)

    delta = current - updated_at
    return max(0, int(delta.total_seconds()))


def describe_age(payload: dict | None, now: str | datetime | None = None) -> str | None:
    seconds = payload_age_seconds(payload, now=now)
    if seconds is None:
        return None
    if seconds < 60:
        return "cached just now"
    minutes = seconds // 60
    if minutes < 60:
        return f"cached {minutes}m ago"
    hours = minutes // 60
    if hours < 24:
        return f"cached {hours}h ago"
    days = hours // 24
    return f"cached {days}d ago"


def is_stale(payload: dict | None, max_age_seconds: int, now: str | datetime | None = None) -> bool:
    seconds = payload_age_seconds(payload, now=now)
    if seconds is None:
        return True
    return seconds > max_age_seconds


def cache_matches_account(payload: dict | None, account_id: str | None) -> bool:
    if not isinstance(payload, dict):
        return False
    cached_account = payload.get("account_id")
    if not cached_account or not account_id:
        return True
    return cached_account == account_id


def load(playlist_id: str, account_id: str | None = None, path: str | None = None) -> dict | None:
    cache_path = _cache_path(playlist_id, account_id, path)
    try:
        if not os.path.exists(cache_path):
            return None
        with open(cache_path, "r", encoding="utf-8") as f:
            payload = json.load(f)
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return None

    if not isinstance(payload, dict):
        return None
    if payload.get("playlist_id") != playlist_id:
        return None
    if not cache_matches_account(payload, account_id):
        return None

    tracks = payload.get("tracks")
    if not isinstance(tracks, list):
        return None

    sanitized_tracks = []
    for entry in tracks:
        sanitized = _sanitize_track_entry(entry)
        if sanitized is not None:
            sanitized_tracks.append(sanitized)

    payload = dict(payload)
    payload["tracks"] = sanitized_tracks
    if payload.get("playlist_total") is not None:
        try:
            payload["playlist_total"] = int(str(payload.get("playlist_total")))
        except (TypeError, ValueError):
            payload["playlist_total"] = None
    return payload


def save(
    playlist_id: str,
    tracks: list[dict],
    account_id: str | None = None,
    playlist_name: str | None = None,
    playlist_total: int | None = None,
    path: str | None = None,
) -> dict:
    cache_path = _cache_path(playlist_id, account_id, path)
    dir_name = os.path.dirname(cache_path)
    if dir_name:
        os.makedirs(dir_name, exist_ok=True)

    payload = {
        "updated_at": _now_iso(),
        "account_id": account_id,
        "playlist_id": playlist_id,
        "playlist_name": playlist_name,
        "playlist_total": playlist_total,
        "tracks": tracks,
    }

    temp_path = f"{cache_path}.tmp"
    with open(temp_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
    os.replace(temp_path, cache_path)
    return payload


def clear(playlist_id: str, account_id: str | None = None, path: str | None = None) -> None:
    cache_path = _cache_path(playlist_id, account_id, path)
    try:
        os.remove(cache_path)
    except FileNotFoundError:
        pass
