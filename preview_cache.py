import hashlib
import json
import os
import re
import tempfile
from urllib.request import urlopen


def _safe_name(text: str) -> str:
    return re.sub(r'[^A-Za-z0-9._-]+', '_', text).strip('_') or 'preview'


def _metadata_path(path: str) -> str:
    return f"{path}.json"


def _sha256_file(path: str) -> str:
    hasher = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def _load_cached_preview(path: str, preview_url: str) -> bool:
    meta_path = _metadata_path(path)
    if not (os.path.exists(path) and os.path.getsize(path) > 0 and os.path.exists(meta_path)):
        return False

    try:
        with open(meta_path, "r", encoding="utf-8") as f:
            metadata = json.load(f)
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return False

    if not isinstance(metadata, dict):
        return False
    if metadata.get("preview_url") != preview_url:
        return False

    expected_hash = metadata.get("sha256")
    if not expected_hash:
        return False

    try:
        return _sha256_file(path) == expected_hash
    except OSError:
        return False


def _remove_cached_preview(path: str) -> None:
    for candidate in (path, _metadata_path(path)):
        try:
            os.remove(candidate)
        except FileNotFoundError:
            pass
        except OSError:
            pass


def download_preview_clip(preview_url: str, cache_key: str, cache_dir: str | None = None) -> str:
    cache_dir = cache_dir or os.path.join(tempfile.gettempdir(), 'spotify-vdj-previews')
    os.makedirs(cache_dir, exist_ok=True)

    digest = hashlib.sha1(preview_url.encode('utf-8')).hexdigest()[:12]
    filename = f"{_safe_name(cache_key)}-{digest}.mp3"
    path = os.path.join(cache_dir, filename)

    if _load_cached_preview(path, preview_url):
        return path

    _remove_cached_preview(path)

    with urlopen(preview_url, timeout=20) as response:
        data = response.read()

    fd, tmp_path = tempfile.mkstemp(dir=cache_dir, prefix=f".{_safe_name(cache_key)}-", suffix=".tmp")
    try:
        with os.fdopen(fd, 'wb') as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())

        os.replace(tmp_path, path)
        metadata = {
            "preview_url": preview_url,
            "sha256": hashlib.sha256(data).hexdigest(),
            "size": len(data),
        }
        with open(_metadata_path(path), 'w', encoding='utf-8') as f:
            json.dump(metadata, f, indent=2, ensure_ascii=False)
    finally:
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except OSError:
            pass

    return path
