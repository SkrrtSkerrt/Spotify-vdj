import os
import re
import shutil
import threading
import sys
from typing import Callable
import yt_dlp


def _sanitize(name: str) -> str:
    return re.sub(r'[\\/*?:"<>|]', "_", name)


def _search_query(track: dict) -> str:
    return f"{track['artist']} - {track['name']} official audio"


def _expected_filename(track: dict, output_folder: str) -> str:
    safe_artist = _sanitize(track["artist"])
    safe_name = _sanitize(track["name"])
    return os.path.join(output_folder, f"{safe_artist} - {safe_name}.mp3")


def already_downloaded(track: dict, output_folder: str) -> bool:
    return os.path.exists(_expected_filename(track, output_folder))


def youtube_search_url(track: dict) -> str:
    import urllib.parse
    q = urllib.parse.quote_plus(_search_query(track))
    return f"https://www.youtube.com/results?search_query={q}"


def find_ffmpeg_location() -> str | None:
    exe_name = "ffmpeg.exe" if os.name == "nt" else "ffmpeg"

    which_path = shutil.which("ffmpeg")
    if which_path:
        return os.path.dirname(which_path)

    for base in (
        os.getcwd(),
        os.path.dirname(os.path.abspath(__file__)),
        os.path.dirname(sys.executable),
    ):
        candidate = os.path.join(base, exe_name)
        if os.path.exists(candidate):
            return base

    return None


def ensure_ffmpeg_available() -> str:
    location = find_ffmpeg_location()
    if not location:
        raise RuntimeError(
            "FFmpeg was not found. Install FFmpeg, add it to PATH, or place ffmpeg.exe next to SpotifyVDJ.exe."
        )
    return location


class DownloadHandle:
    """Returned by download_track — call cancel() to abort."""

    def __init__(self):
        self._cancel = threading.Event()

    def cancel(self):
        self._cancel.set()

    @property
    def cancelled(self) -> bool:
        return self._cancel.is_set()


def download_track(
    track: dict,
    output_folder: str,
    on_progress: Callable[[str, float], None] | None = None,
    on_done: Callable[[str, bool, str], None] | None = None,
) -> DownloadHandle:
    """Start download in a background thread. Returns a DownloadHandle for cancellation."""

    handle = DownloadHandle()

    def _run():
        os.makedirs(output_folder, exist_ok=True)
        ffmpeg_location = ensure_ffmpeg_available()
        safe_artist = _sanitize(track["artist"])
        safe_name = _sanitize(track["name"])
        output_template = os.path.join(output_folder, f"{safe_artist} - {safe_name}.%(ext)s")
        duration_s = track["duration_ms"] // 1000

        def progress_hook(d):
            if handle.cancelled:
                raise yt_dlp.utils.DownloadCancelled()
            if on_progress is None:
                return
            if d["status"] == "downloading":
                total = d.get("total_bytes") or d.get("total_bytes_estimate", 0)
                downloaded = d.get("downloaded_bytes", 0)
                pct = (downloaded / total * 100) if total else 0
                on_progress(f"Downloading… {pct:.0f}%", pct)
            elif d["status"] == "finished":
                on_progress("Converting…", 99)

        ydl_opts = {
            "format": "bestaudio/best",
            "outtmpl": output_template,
            "ffmpeg_location": ffmpeg_location,
            "postprocessors": [
                {
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": "320",
                },
                {"key": "FFmpegMetadata"},
                {"key": "EmbedThumbnail"},
            ],
            "writethumbnail": True,
            "progress_hooks": [progress_hook],
            "quiet": True,
            "no_warnings": True,
            "match_filter": yt_dlp.utils.match_filter_func(
                f"duration >= {max(0, duration_s - 15)} & duration <= {duration_s + 15}"
            ),
        }

        query = _search_query(track)
        search_url = f"ytsearch5:{query}"

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([search_url])
            out_path = _expected_filename(track, output_folder)
            if on_done:
                on_done(track["id"], True, out_path)
        except yt_dlp.utils.DownloadCancelled:
            if on_done:
                on_done(track["id"], False, "Cancelled")
        except Exception as e:
            if on_done:
                on_done(track["id"], False, str(e))

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    return handle
