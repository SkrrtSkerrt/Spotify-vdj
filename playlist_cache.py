import json
import os
from datetime import datetime, timezone

CACHE_FILE = os.path.join(os.path.expanduser("~"), ".spotify_vdj_playlists_cache.json")


def _cache_path(path: str | None = None) -> str:
    return path or CACHE_FILE


def _sanitize_playlist_entry(entry: dict) -> dict | None:
    if not isinstance(entry, dict):
        return None

    playlist_id = entry.get("id")
    name = entry.get("name")
    if not playlist_id or not name:
        return None

    sanitized = dict(entry)
    sanitized["id"] = str(playlist_id)
    sanitized["name"] = str(name)

    total_value = entry.get("total")
    total = 0
    if isinstance(total_value, bool):
        total = 0
    elif isinstance(total_value, int):
        total = total_value
    else:
        try:
            total = int(str(total_value))
        except (TypeError, ValueError):
            total = 0
    sanitized["total"] = total
    return sanitized


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_iso_timestamp(value: str | None) -> datetime | None:
    if not value or not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


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


def load(path: str | None = None) -> dict | None:
    cache_path = _cache_path(path)
    try:
        if not os.path.exists(cache_path):
            return None
        with open(cache_path, "r", encoding="utf-8") as f:
            payload = json.load(f)
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return None

    if not isinstance(payload, dict):
        return None

    playlists = payload.get("playlists")
    if not isinstance(playlists, list):
        return None

    sanitized_playlists = []
    for entry in playlists:
        sanitized = _sanitize_playlist_entry(entry)
        if sanitized is not None:
            sanitized_playlists.append(sanitized)
    payload = dict(payload)
    payload["playlists"] = sanitized_playlists

    selected_playlist_id = payload.get("selected_playlist_id")
    if selected_playlist_id and not any(pl.get("id") == selected_playlist_id for pl in sanitized_playlists):
        payload["selected_playlist_id"] = None

    return payload


def save(
    playlists: list[dict],
    account_id: str | None = None,
    selected_playlist_id: str | None = None,
    path: str | None = None,
) -> dict:
    cache_path = _cache_path(path)
    dir_name = os.path.dirname(cache_path)
    if dir_name:
        os.makedirs(dir_name, exist_ok=True)
    payload = {
        "updated_at": _now_iso(),
        "account_id": account_id,
        "selected_playlist_id": selected_playlist_id,
        "playlists": playlists,
    }
    temp_path = f"{cache_path}.tmp"
    with open(temp_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
    os.replace(temp_path, cache_path)
    return payload


def clear(path: str | None = None) -> None:
    cache_path = _cache_path(path)
    try:
        os.remove(cache_path)
    except FileNotFoundError:
        pass
