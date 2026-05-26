import json
import os

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
        with open(CONFIG_FILE, "r") as f:
            data = json.load(f)
        return {**DEFAULTS, **data}
    return dict(DEFAULTS)


def save(cfg: dict) -> None:
    with open(CONFIG_FILE, "w") as f:
        json.dump(cfg, f, indent=2)


def is_configured(cfg: dict) -> bool:
    return bool(cfg.get("client_id") and cfg.get("client_secret"))
