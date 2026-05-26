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


def _search_candidates(track: dict, limit: int = 10) -> list[dict]:
    query = _search_query(track)
    search_url = f"ytsearch{limit}:{query}"
    with yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True}) as ydl:
        info = ydl.extract_info(search_url, download=False)
    entries = info.get("entries") or []
    return [e for e in entries if e and e.get("webpage_url")]


def _candidate_sort_key(entry: dict, desired_duration: int) -> tuple[int, int, int]:
    duration = entry.get("duration") or 0
    duration_diff = abs(duration - desired_duration) if duration else 999999
    availability = entry.get("availability")
    availability_score = 0 if availability in (None, "public", "unlisted") else 1
    return (availability_score, duration_diff, 0)


def _candidate_urls(track: dict, entries: list[dict]) -> list[str]:
    desired_duration = max(0, track["duration_ms"] // 1000)
    ranked = sorted(entries, key=lambda entry: _candidate_sort_key(entry, desired_duration))
    urls: list[str] = []
    for entry in ranked:
        url = entry.get("webpage_url")
        if url and url not in urls:
            urls.append(url)
    return urls


def _cleanup_temp_dir(path: str) -> None:
    try:
        shutil.rmtree(path)
    except OSError:
        pass


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
        temp_dir = os.path.join(output_folder, ".spotifyvdj_tmp", track["id"])
        os.makedirs(temp_dir, exist_ok=True)

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
            "paths": {"temp": temp_dir},
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
            "overwrites": True,
            "progress_hooks": [progress_hook],
            "quiet": True,
            "no_warnings": True,
        }

        try:
            candidates = _candidate_urls(track, _search_candidates(track))
            if not candidates:
                raise RuntimeError(f"No YouTube matches found for {track['artist']} - {track['name']}")

            last_error: Exception | None = None
            for url in candidates:
                try:
                    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                        ydl.download([url])
                    out_path = _expected_filename(track, output_folder)
                    if on_done:
                        on_done(track["id"], True, out_path)
                    return
                except yt_dlp.utils.DownloadCancelled:
                    if on_done:
                        on_done(track["id"], False, "Cancelled")
                    return
                except Exception as e:
                    msg = str(e).lower()
                    last_error = e
                    if any(
                        needle in msg
                        for needle in (
                            "this video is not available",
                            "video is unavailable",
                            "private video",
                            "members-only",
                            "sign in to confirm",
                        )
                    ):
                        continue
                    raise

            if on_done:
                on_done(track["id"], False, str(last_error or RuntimeError("No playable YouTube candidate found.")))
        except yt_dlp.utils.DownloadCancelled:
            if on_done:
                on_done(track["id"], False, "Cancelled")
        except Exception as e:
            if on_done:
                on_done(track["id"], False, str(e))
        finally:
            _cleanup_temp_dir(temp_dir)

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    return handle
