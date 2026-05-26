import os
import re
import shutil
import sys
import tempfile
import threading
from typing import Callable

import yt_dlp

AUDIO_EXTENSIONS = {".mp3", ".m4a", ".aac", ".wav", ".flac", ".ogg", ".opus", ".m4b"}


def _sanitize(name: str) -> str:
    return re.sub(r'[\\/*?:"<>|]', "_", name)


def _normalize_text(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", text.lower()))


def _track_signature(track: dict) -> tuple[set[str], set[str]]:
    return _normalize_text(track["artist"]), _normalize_text(track["name"])


def _file_signature(path: str) -> set[str]:
    stem = os.path.splitext(os.path.basename(path))[0]
    return _normalize_text(stem)


def _expected_filename(track: dict, output_folder: str) -> str:
    safe_artist = _sanitize(track["artist"])
    safe_name = _sanitize(track["name"])
    return os.path.join(output_folder, f"{safe_artist} - {safe_name}.mp3")


def build_download_index(output_folder: str) -> list[str]:
    if not output_folder or not os.path.isdir(output_folder):
        return []

    paths: list[str] = []
    for root, _, files in os.walk(output_folder):
        for filename in files:
            ext = os.path.splitext(filename)[1].lower()
            if ext not in AUDIO_EXTENSIONS:
                continue
            paths.append(os.path.join(root, filename))
    return paths


def find_existing_download_path(
    track: dict,
    output_folder: str,
    known_paths: list[str] | None = None,
) -> str | None:
    expected = _expected_filename(track, output_folder)
    if os.path.exists(expected):
        return expected

    paths = known_paths if known_paths is not None else build_download_index(output_folder)
    if not paths:
        return None

    artist_tokens, name_tokens = _track_signature(track)
    for path in paths:
        tokens = _file_signature(path)
        if artist_tokens and name_tokens and artist_tokens.issubset(tokens) and name_tokens.issubset(tokens):
            return path
    return None


def already_downloaded(track: dict, output_folder: str, known_paths: list[str] | None = None) -> bool:
    return find_existing_download_path(track, output_folder, known_paths) is not None


def _search_queries(track: dict) -> list[str]:
    artist = track["artist"].strip()
    name = track["name"].strip()
    return [
        f"{artist} - {name} official audio",
        f"{artist} - {name}",
        f"{artist} {name} official audio",
    ]


def _search_query(track: dict) -> str:
    return _search_queries(track)[0]


def youtube_search_url(track: dict):
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


def _is_retryable_source_error(message: str) -> bool:
    lowered = message.lower()
    return any(
        needle in lowered
        for needle in (
            "this video is not available",
            "video is unavailable",
            "private video",
            "members-only",
            "sign in to confirm",
            "unable to extract",
            "no video formats found",
            "postprocessing audio conversion failed",
        )
    )


def format_download_error(error: Exception | str, track: dict, source_url: str | None = None) -> str:
    title = f"{track['artist']} - {track['name']}"
    details = str(error).strip() or error.__class__.__name__
    lowered = details.lower()
    lines = [f"{title}: download failed."]

    if "winerror 32" in lowered or "winerror 5" in lowered or "access denied" in lowered:
        lines[0] = f"{title}: Windows could not write the file because it is locked or access was denied."
        lines.append("Close anything using the output file, confirm the folder is writable, then retry.")
    elif "postprocessing audio conversion failed" in lowered or "ffmpeg" in lowered:
        lines[0] = f"{title}: FFmpeg failed while converting the download to MP3."
        lines.append("Check that FFmpeg is installed and that the output file is not open in another app.")
    elif "this video is not available" in lowered or "video is unavailable" in lowered or "private video" in lowered:
        lines[0] = f"{title}: YouTube returned an unavailable result while searching for a match."
        lines.append("The app will try other search results, but you may need a different version of the track.")
    elif "no video formats found" in lowered or "unable to extract" in lowered:
        lines[0] = f"{title}: YouTube did not expose a usable audio stream for this candidate."
        lines.append("The app will try another search result or a different query.")
    else:
        lines.append("Try a different result or search manually if this keeps happening.")

    manual_search = youtube_search_url(track)
    lines.append(f"Manual search: {manual_search}")
    lines.append("If you find a usable copy, download it or add it into the configured output folder, then refresh the library.")

    if source_url:
        lines.append(f"Source: {source_url}")
    lines.append(f"Details: {details}")
    return "\n".join(lines)


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


def _search_candidates_for_query(query: str, limit: int = 10) -> list[dict]:
    search_url = f"ytsearch{limit}:{query}"
    with yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True}) as ydl:
        info = ydl.extract_info(search_url, download=False)
    entries = info.get("entries") or []
    return [e for e in entries if e and e.get("webpage_url")]


def _search_candidates(track: dict, limit: int = 10) -> list[dict]:
    return _search_candidates_for_query(_search_query(track), limit)


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
    source_url: str | None = None,
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
            last_error: Exception | None = None
            last_url: str | None = None
            url_candidates = [source_url] if source_url else []
            if not url_candidates:
                for query in _search_queries(track):
                    candidates = _candidate_urls(track, _search_candidates_for_query(query))
                    if candidates:
                        url_candidates.extend(candidates)

            for url in url_candidates:
                last_url = url
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
                    msg = str(e)
                    last_error = e
                    if source_url:
                        if on_done:
                            on_done(track["id"], False, format_download_error(e, track, source_url=url))
                        return
                    if _is_retryable_source_error(msg):
                        continue
                    if on_done:
                        on_done(track["id"], False, format_download_error(e, track, source_url=url))
                    return

            if on_done:
                if last_error is None:
                    last_error = RuntimeError(f"No YouTube matches found for {track['artist']} - {track['name']}")
                on_done(track["id"], False, format_download_error(last_error, track, source_url=last_url))
        except yt_dlp.utils.DownloadCancelled:
            if on_done:
                on_done(track["id"], False, "Cancelled")
        except Exception as e:
            if on_done:
                on_done(track["id"], False, format_download_error(e, track))
        finally:
            _cleanup_temp_dir(temp_dir)

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    return handle
