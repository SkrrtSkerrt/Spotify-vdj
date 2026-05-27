import json
import os
import tempfile
from datetime import datetime, timezone

STATE_FILE = os.path.join(os.path.expanduser("~"), ".spotify_vdj_ui_state.json")


def _cache_path(path: str | None = None) -> str:
    return path or STATE_FILE


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def cache_matches_account(payload: dict | None, account_id: str | None) -> bool:
    if not payload:
        return True
    cached_account = payload.get("account_id")
    if not cached_account or not account_id:
        return True
    return cached_account == account_id


def _sanitize_queue_entry(entry) -> dict | None:
    if not isinstance(entry, dict):
        return None
    track = entry.get("track")
    if not isinstance(track, dict):
        return None
    track_id = entry.get("track_id")
    if not track_id:
        return None
    track_id = str(track_id)
    track_copy = dict(track)
    if not track_copy.get("id"):
        track_copy["id"] = track_id
    if not track_copy.get("name"):
        return None
    sanitized = {
        "playlist_id": entry.get("playlist_id"),
        "track_id": track_id,
        "track": track_copy,
        "status": entry.get("status") or "Queued",
        "progress": entry.get("progress", 0),
    }
    source_url = entry.get("source_url")
    if source_url:
        sanitized["source_url"] = source_url
    return sanitized


def _sanitize_payload(payload: dict) -> dict:
    sanitized = dict(payload)
    if sanitized.get("account_id") is not None:
        sanitized["account_id"] = str(sanitized["account_id"])
    if sanitized.get("last_playlist_id") is not None:
        sanitized["last_playlist_id"] = str(sanitized["last_playlist_id"])
    if sanitized.get("playlist_refresh_cooldown_until") is not None:
        sanitized["playlist_refresh_cooldown_until"] = str(sanitized["playlist_refresh_cooldown_until"])
    queue_entries = sanitized.get("queue_entries") or []
    sanitized["queue_entries"] = [entry for entry in (_sanitize_queue_entry(entry) for entry in queue_entries) if entry]
    return sanitized


def load(account_id: str | None = None, path: str | None = None) -> dict | None:
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
    payload = _sanitize_payload(payload)
    if not cache_matches_account(payload, account_id):
        return None
    return payload


def save(payload: dict, path: str | None = None) -> dict:
    cache_path = _cache_path(path)
    dir_name = os.path.dirname(cache_path)
    if dir_name:
        os.makedirs(dir_name, exist_ok=True)

    sanitized = _sanitize_payload(payload)
    sanitized.setdefault("updated_at", _now_iso())
    fd, tmp_path = tempfile.mkstemp(prefix=".spotify_vdj_state.", suffix=".tmp", dir=dir_name or None)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(sanitized, f, indent=2, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, cache_path)
    finally:
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except OSError:
            pass
    return sanitized


def clear(path: str | None = None) -> None:
    cache_path = _cache_path(path)
    try:
        os.remove(cache_path)
    except FileNotFoundError:
        return
    except OSError:
        pass
