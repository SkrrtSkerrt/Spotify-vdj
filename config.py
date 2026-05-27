import json
import os
import tempfile

CONFIG_FILE = os.path.join(os.path.expanduser("~"), ".spotify_vdj_config.json")

DEFAULTS = {
    "client_id": "",
    "client_secret": "",
    "redirect_uri": "http://127.0.0.1:8888/callback",
    "output_folder": os.path.join(os.path.expanduser("~"), "Music", "SpotifyVDJ"),
    "audio_format": "mp3",
    "audio_quality": "320",
    "max_concurrent_downloads": 2,
    "watch_output_folder": True,
    "watch_interval_seconds": 30,
}


def load() -> dict:
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            return dict(DEFAULTS)
        if not isinstance(data, dict):
            return dict(DEFAULTS)
        return {**DEFAULTS, **data}
    return dict(DEFAULTS)


def save(cfg: dict) -> None:
    dir_name = os.path.dirname(CONFIG_FILE)
    if dir_name:
        os.makedirs(dir_name, exist_ok=True)

    fd, tmp_path = tempfile.mkstemp(prefix=".spotify_vdj_config.", suffix=".tmp", dir=dir_name or None)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, CONFIG_FILE)
    finally:
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except OSError:
            pass


def is_configured(cfg: dict) -> bool:
    return bool(cfg.get("client_id") and cfg.get("client_secret"))
