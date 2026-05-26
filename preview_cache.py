import hashlib
import os
import re
import tempfile
from urllib.request import urlopen


def _safe_name(text: str) -> str:
    return re.sub(r'[^A-Za-z0-9._-]+', '_', text).strip('_') or 'preview'


def download_preview_clip(preview_url: str, cache_key: str, cache_dir: str | None = None) -> str:
    cache_dir = cache_dir or os.path.join(tempfile.gettempdir(), 'spotify-vdj-previews')
    os.makedirs(cache_dir, exist_ok=True)

    digest = hashlib.sha1(preview_url.encode('utf-8')).hexdigest()[:12]
    filename = f"{_safe_name(cache_key)}-{digest}.mp3"
    path = os.path.join(cache_dir, filename)

    if os.path.exists(path) and os.path.getsize(path) > 0:
        return path

    with urlopen(preview_url, timeout=20) as response:
        data = response.read()

    with open(path, 'wb') as f:
        f.write(data)

    return path
