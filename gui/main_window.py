import csv
import json
import logging
import os
import platform
import subprocess
import sys
import webbrowser
import zipfile
from datetime import datetime, timedelta, timezone
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QHBoxLayout, QVBoxLayout,
    QListWidget, QListWidgetItem, QTableWidget, QTableWidgetItem,
    QPushButton, QLabel, QHeaderView, QSplitter,
    QStatusBar, QAction, QAbstractItemView, QMessageBox,
    QDockWidget, QFileDialog
)
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QObject, QTimer
from PyQt5.QtGui import QFont, QColor, QBrush, QIcon
import spotipy

import config
import spotify_client as sc
import downloader
import playlist_cache
import track_cache
import ui_state
from download_manager import DownloadManager, DownloadJob
from logging_utils import LOG_FILE
from gui.queue_panel import QueuePanel, QueueEntry
from resource_utils import resource_path
from version import __version__

logger = logging.getLogger(__name__)

PLAYLIST_CACHE_MAX_AGE_SECONDS = 6 * 60 * 60
TRACK_CACHE_MAX_AGE_SECONDS = 60 * 60

def _fmt_duration(ms: int) -> str:
    s = ms // 1000
    return f"{s // 60}:{s % 60:02d}"


def _capture_track_view_state(track_table, tracks: list[dict]) -> dict | None:
    selected_rows = sorted(set(item.row() for item in track_table.selectedItems()))
    selected_track_id = None
    for row in selected_rows:
        if 0 <= row < len(tracks):
            selected_track_id = tracks[row].get("id")
            if selected_track_id:
                break

    scroll_value = None
    scrollbar = getattr(track_table, "verticalScrollBar", None)
    if callable(scrollbar):
        scrollbar = scrollbar()
    if scrollbar is not None:
        try:
            value_fn = getattr(scrollbar, "value", None)
            scroll_value = value_fn() if callable(value_fn) else None
        except Exception:
            scroll_value = None

    if selected_track_id is None and scroll_value is None:
        return None
    return {"selected_track_id": selected_track_id, "scroll_value": scroll_value}


def _apply_track_view_state(track_table, tracks: list[dict], state: dict | None) -> None:
    if not state:
        return

    selected_track_id = state.get("selected_track_id")
    if selected_track_id:
        for row, track in enumerate(tracks):
            if track.get("id") == selected_track_id:
                select_row = getattr(track_table, "selectRow", None)
                if callable(select_row):
                    select_row(row)
                else:
                    set_current_cell = getattr(track_table, "setCurrentCell", None)
                    if callable(set_current_cell):
                        set_current_cell(row, 0)
                break

    scroll_value = state.get("scroll_value")
    if scroll_value is not None:
        scrollbar = getattr(track_table, "verticalScrollBar", None)
        if callable(scrollbar):
            scrollbar = scrollbar()
        if scrollbar is not None:
            set_value = getattr(scrollbar, "setValue", None)
            if callable(set_value):
                set_value(scroll_value)


def _resolve_playlist_selection(playlists: list[dict], selected_playlist_id: str | None) -> str | None:
    playlist_ids = [pl.get("id") for pl in playlists if isinstance(pl, dict) and pl.get("id")]
    if selected_playlist_id and selected_playlist_id in playlist_ids:
        return selected_playlist_id
    return playlist_ids[0] if playlist_ids else None


class TrackState:
    PENDING = "pending"
    DOWNLOADING = "downloading"
    DONE = "done"
    ERROR = "error"
    EXISTS = "exists"
    CANCELLED = "cancelled"
    LOCAL = "local"
    UNSUPPORTED = "unsupported"


class PlaylistsLoader(QObject):
    finished = pyqtSignal(list)
    error = pyqtSignal(str)

    def __init__(self, sp):
        super().__init__()
        self.sp = sp

    def run(self):
        try:
            playlists = sc.get_playlists(self.sp)
            self.finished.emit(playlists)
        except Exception as e:
            self.error.emit(str(e))


class PlaylistLoader(QObject):
    finished = pyqtSignal(list)
    error = pyqtSignal(str)

    def __init__(self, sp, playlist_id):
        super().__init__()
        self.sp = sp
        self.playlist_id = playlist_id

    def run(self):
        try:
            if self.playlist_id == "__liked__":
                tracks = sc.get_liked_tracks(self.sp)
            else:
                tracks = sc.get_tracks(self.sp, self.playlist_id)
            self.finished.emit(tracks)
        except Exception as e:
            self.error.emit(str(e))


class MainWindow(QMainWindow):
    _progress_signal = pyqtSignal(str, str, float)   # track_id, status, pct
    _done_signal = pyqtSignal(str, bool, str)          # track_id, success, path_or_error

    def __init__(self, sp: spotipy.Spotify, cfg: dict):
        super().__init__()
        self.sp = sp
        self.cfg = cfg
        self.playlists: list[dict] = []
        self.tracks: list[dict] = []
        self.track_states: dict[str, str] = {}
        self._track_errors: dict[str, str] = {}
        self._track_paths: dict[str, str] = {}
        self._dl_manager = DownloadManager(max_concurrent=int(cfg.get("max_concurrent_downloads", 2)))
        self._downloaded_paths: list[str] = downloader.build_download_index(cfg.get("output_folder", ""))
        self._watch_timer = QTimer(self)
        self._watch_timer.timeout.connect(self._rescan_output_folder)
        self._configure_folder_watch_timer()
        self._playlist_loader_thread = None
        self._playlist_loader = None
        self._active_threads = set()
        self._track_load_token = 0
        self._current_playlist_total = None
        self._playlist_refresh_in_progress = False
        self._cached_playlist_payload = None
        self._playlist_refresh_mode = "startup"
        self._spotify_account_id = None
        self._playlist_refresh_cooldown_until = None
        self._playlist_refresh_cooldown_timer = QTimer(self)
        self._playlist_refresh_cooldown_timer.setInterval(1000)
        self._playlist_refresh_cooldown_timer.timeout.connect(self._refresh_playlist_refresh_cooldown)
        self._track_view_state_by_playlist: dict[str, dict] = {}
        self._current_playlist_id = None
        self._runtime_state: dict = {}
        self._restored_queue_playlists: set[str] = set()
        self._refresh_after_cooldown_pending = False
        self._progress_signal.connect(self._on_progress)
        self._done_signal.connect(self._on_done)

        self.setWindowTitle(f"Spotify VDJ v{__version__}")
        self.setWindowIcon(QIcon(resource_path("icon.ico")))
        self.setMinimumSize(1000, 650)
        self._build_menu()
        self._build_ui()
        self._build_docks()
        self._runtime_state = ui_state.load(account_id=self._current_account_id()) or {}
        self._apply_saved_refresh_cooldown()
        self._load_playlists()

    def _build_menu(self):
        menubar = self.menuBar()
        file_menu = menubar.addMenu("File")

        settings_action = QAction("Settings…", self)
        settings_action.triggered.connect(self._open_settings)
        file_menu.addAction(settings_action)

        open_folder_action = QAction("Open Output Folder", self)
        open_folder_action.triggered.connect(self._open_output_folder)
        file_menu.addAction(open_folder_action)

        rescan_action = QAction("Rescan Library", self)
        rescan_action.triggered.connect(self._rescan_output_folder)
        file_menu.addAction(rescan_action)

        open_log_action = QAction("Open Debug Log", self)
        open_log_action.triggered.connect(self._open_debug_log)
        file_menu.addAction(open_log_action)

        copy_log_path_action = QAction("Copy Debug Log Path", self)
        copy_log_path_action.triggered.connect(self._copy_debug_log_path)
        file_menu.addAction(copy_log_path_action)

        export_debug_bundle_action = QAction("Export Debug Bundle…", self)
        export_debug_bundle_action.triggered.connect(self._export_debug_bundle)
        file_menu.addAction(export_debug_bundle_action)

        export_failed_action = QAction("Export Failed Tracks…", self)
        export_failed_action.triggered.connect(self._export_failed_tracks)
        file_menu.addAction(export_failed_action)

        view_menu = menubar.addMenu("View")
        self._toggle_queue_action = QAction("Show Queue", self, checkable=True, checked=True)
        self._toggle_queue_action.triggered.connect(self._toggle_queue_dock)
        view_menu.addAction(self._toggle_queue_action)

        track_menu = menubar.addMenu("Track")
        self._find_manual_action = QAction("Find Manually", self)
        self._find_manual_action.triggered.connect(self._find_selected_manually)
        track_menu.addAction(self._find_manual_action)

        self._retry_failed_action = QAction("Retry Failed", self)
        self._retry_failed_action.triggered.connect(self._retry_failed_tracks)
        track_menu.addAction(self._retry_failed_action)

        self._open_file_action = QAction("Open File Location", self)
        self._open_file_action.triggered.connect(self._open_selected_file_location)
        track_menu.addAction(self._open_file_action)

    # ── Main UI ───────────────────────────────────────────────────────────────

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root_layout = QVBoxLayout(central)
        root_layout.setContentsMargins(8, 8, 8, 4)

        splitter = QSplitter(Qt.Horizontal)
        root_layout.addWidget(splitter)

        # Left: playlist list
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        lbl = QLabel("Playlists")
        lbl.setFont(QFont("", 11, QFont.Bold))
        left_layout.addWidget(lbl)

        self.playlist_list = QListWidget()
        self.playlist_list.currentRowChanged.connect(self._on_playlist_selected)
        self.playlist_list.itemClicked.connect(lambda item: self._on_playlist_selected(self.playlist_list.row(item)))
        left_layout.addWidget(self.playlist_list)
        splitter.addWidget(left)

        # Right: track table
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)

        top_bar = QHBoxLayout()
        title_stack = QVBoxLayout()
        self.playlist_title = QLabel("Select a playlist")
        self.playlist_title.setFont(QFont("", 11, QFont.Bold))
        self.playlist_cache_label = QLabel("")
        self.playlist_cache_label.setStyleSheet("color: #666; font-size: 10px;")
        self.track_cache_label = QLabel("")
        self.track_cache_label.setStyleSheet("color: #666; font-size: 10px;")
        title_stack.addWidget(self.playlist_title)
        title_stack.addWidget(self.playlist_cache_label)
        title_stack.addWidget(self.track_cache_label)
        top_bar.addLayout(title_stack)
        top_bar.addStretch()

        self.refresh_playlists_btn = QPushButton("Refresh Playlists")
        self.refresh_playlists_btn.clicked.connect(self._refresh_playlists)
        top_bar.addWidget(self.refresh_playlists_btn)

        self.download_selected_btn = QPushButton("Download Selected")
        self.download_selected_btn.clicked.connect(self._download_selected)
        self.download_selected_btn.setEnabled(False)

        self.download_all_btn = QPushButton("Download All")
        self.download_all_btn.clicked.connect(self._download_all)
        self.download_all_btn.setEnabled(False)

        self.retry_failed_btn = QPushButton("Retry Failed")
        self.retry_failed_btn.clicked.connect(self._retry_failed_tracks)
        self.retry_failed_btn.setEnabled(False)

        self.find_manual_btn = QPushButton("Find Manually")
        self.find_manual_btn.clicked.connect(self._find_selected_manually)
        self.find_manual_btn.setEnabled(False)

        self.open_file_btn = QPushButton("Open File Location")
        self.open_file_btn.clicked.connect(self._open_selected_file_location)
        self.open_file_btn.setEnabled(False)

        self.rescan_btn = QPushButton("Rescan Library")
        self.rescan_btn.clicked.connect(self._rescan_output_folder)

        self.export_failed_btn = QPushButton("Export Failed")
        self.export_failed_btn.clicked.connect(self._export_failed_tracks)

        top_bar.addWidget(self.download_selected_btn)
        top_bar.addWidget(self.download_all_btn)
        right_layout.addLayout(top_bar)

        action_bar = QHBoxLayout()
        action_bar.addWidget(self.retry_failed_btn)
        action_bar.addWidget(self.find_manual_btn)
        action_bar.addWidget(self.open_file_btn)
        action_bar.addWidget(self.rescan_btn)
        action_bar.addWidget(self.export_failed_btn)
        action_bar.addStretch()
        right_layout.addLayout(action_bar)

        # Track table
        self.track_table = QTableWidget(0, 6)
        self.track_table.setHorizontalHeaderLabels(["#", "Title", "Artist", "Album", "Duration", "Status"])
        self.track_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.track_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.track_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.track_table.setColumnWidth(0, 36)
        self.track_table.setColumnWidth(4, 66)
        self.track_table.setColumnWidth(5, 180)
        self.track_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.track_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.track_table.setAlternatingRowColors(True)
        self.track_table.verticalHeader().setDefaultSectionSize(28)
        self.track_table.itemSelectionChanged.connect(self._update_download_btn)
        self.track_table.itemSelectionChanged.connect(self._persist_current_track_view_state)
        track_scroll_bar = self.track_table.verticalScrollBar()
        if track_scroll_bar is not None:
            track_scroll_bar.valueChanged.connect(lambda *_: self._persist_current_track_view_state())
        right_layout.addWidget(self.track_table)

        splitter.addWidget(right)
        splitter.setSizes([210, 790])

        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("Ready")

    # ── Dock widgets ──────────────────────────────────────────────────────────

    def _build_docks(self):
        # Queue dock (bottom)
        self._queue_dock = QDockWidget("Download Queue", self)
        self._queue_dock.setAllowedAreas(Qt.BottomDockWidgetArea)
        self._queue_dock.setFeatures(
            QDockWidget.DockWidgetClosable | QDockWidget.DockWidgetMovable
        )
        self.queue_panel = QueuePanel()
        self.queue_panel.setMinimumHeight(120)
        self.queue_panel.priority_requested.connect(self._on_priority_requested)
        self.queue_panel.retry_requested.connect(self._retry_track)
        self.queue_panel.manual_url_requested.connect(self._apply_manual_url)
        self._queue_dock.setWidget(self.queue_panel)
        self.addDockWidget(Qt.BottomDockWidgetArea, self._queue_dock)
        self._queue_dock.visibilityChanged.connect(
            lambda v: self._toggle_queue_action.setChecked(v)
        )

    def _toggle_queue_dock(self, checked: bool):
        self._queue_dock.setVisible(checked)

    def _retain_thread(self, thread: QThread):
        self._active_threads.add(thread)
        thread.finished.connect(lambda t=thread: self._active_threads.discard(t))
        thread.finished.connect(thread.deleteLater)

    # ── Playlists ─────────────────────────────────────────────────────────────

    def _current_playlist_item_id(self):
        row = self.playlist_list.currentRow()
        if row < 0:
            return None
        item = self.playlist_list.item(row)
        if not item:
            return None
        return item.data(Qt.UserRole)

    def _set_playlist_refresh_state(self, in_progress: bool):
        self._playlist_refresh_in_progress = in_progress
        self.refresh_playlists_btn.setEnabled(not in_progress)
        if not in_progress and self._playlist_refresh_cooldown_until is None:
            self.refresh_playlists_btn.setText("Refresh Playlists")
            if self._refresh_after_cooldown_pending:
                self._refresh_after_cooldown_pending = False
                QTimer.singleShot(0, self._auto_refresh_playlists_after_cooldown)

    def _persist_current_track_view_state(self):
        playlist_id = self._current_playlist_id
        if not playlist_id:
            return
        state = _capture_track_view_state(self.track_table, self.tracks)
        if state:
            self._track_view_state_by_playlist[playlist_id] = state

    def _restore_track_view_state(self, playlist_id: str | None):
        if not playlist_id:
            return
        state = self._track_view_state_by_playlist.get(playlist_id)
        if state:
            _apply_track_view_state(self.track_table, self.tracks, state)

    def _current_account_id(self) -> str | None:
        if self._spotify_account_id is not None:
            return self._spotify_account_id
        try:
            profile = self.sp.me()
            if isinstance(profile, dict):
                self._spotify_account_id = profile.get("id")
        except Exception:
            self._spotify_account_id = None
        return self._spotify_account_id

    def _parse_iso_datetime(self, value: str | None) -> datetime | None:
        if not value:
            return None
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None

    def _save_runtime_state(self):
        payload = {
            "account_id": self._current_account_id(),
            "last_playlist_id": self._current_playlist_id or self._runtime_state.get("last_playlist_id"),
            "playlist_refresh_cooldown_until": (
                self._playlist_refresh_cooldown_until.isoformat().replace("+00:00", "Z")
                if self._playlist_refresh_cooldown_until is not None else None
            ),
            "queue_entries": self.queue_panel.snapshot_entries() if hasattr(self, "queue_panel") else [],
        }
        try:
            self._runtime_state = ui_state.save(payload)
        except Exception as e:
            logger.warning("Could not save runtime state: %s", e)
            self._runtime_state = payload

    def _apply_saved_refresh_cooldown(self):
        cooldown_until = self._parse_iso_datetime(self._runtime_state.get("playlist_refresh_cooldown_until"))
        if not cooldown_until:
            self._set_playlist_refresh_cooldown(None)
            return
        remaining = int((cooldown_until - datetime.now(timezone.utc)).total_seconds())
        if remaining > 0:
            self._set_playlist_refresh_cooldown(remaining)
            self.status_bar.showMessage(f"Playlist refresh cooldown restored ({remaining}s remaining)")
        else:
            self._set_playlist_refresh_cooldown(None)

    def _saved_queue_entries_for_playlist(self, playlist_id: str | None) -> list[dict]:
        if not playlist_id:
            return []
        entries = self._runtime_state.get("queue_entries") or []
        return [entry for entry in entries if isinstance(entry, dict) and entry.get("playlist_id") == playlist_id]

    def _restore_saved_queue_for_playlist(self, playlist_id: str | None):
        if not playlist_id or playlist_id in self._restored_queue_playlists:
            return
        saved_entries = self._saved_queue_entries_for_playlist(playlist_id)
        if not saved_entries:
            return
        tracks = [entry.get("track") for entry in saved_entries if isinstance(entry.get("track"), dict)]
        tracks = [track for track in tracks if track and track.get("id")]
        if not tracks:
            return
        self._restored_queue_playlists.add(playlist_id)
        self.status_bar.showMessage(f"Restoring {len(tracks)} queued track(s) from the last session…")
        for entry in saved_entries:
            track = entry.get("track")
            if not isinstance(track, dict) or not track.get("id"):
                continue
            self._start_downloads([track], source_url=entry.get("source_url"))
        self._save_runtime_state()

    def _set_playlist_cache_badge(self, payload: dict | None):
        if not payload:
            self.playlist_cache_label.setText("")
            return
        age = playlist_cache.describe_age(payload)
        if not age:
            self.playlist_cache_label.setText("")
            return
        pieces = [age]
        if playlist_cache.is_stale(payload, PLAYLIST_CACHE_MAX_AGE_SECONDS):
            pieces.append("stale")
        selected = payload.get("selected_playlist_id")
        if selected:
            pieces.append("last selection saved")
        if not playlist_cache.cache_matches_account(payload, self._current_account_id()):
            pieces.append("different account")
        self.playlist_cache_label.setText(" · ".join(pieces))

    def _set_track_cache_badge(self, payload: dict | None):
        if not payload:
            self.track_cache_label.setText("")
            return
        age = track_cache.describe_age(payload)
        if not age:
            self.track_cache_label.setText("")
            return
        pieces = [age]
        if track_cache.is_stale(payload, TRACK_CACHE_MAX_AGE_SECONDS):
            pieces.append("stale")
        if payload.get("playlist_name"):
            pieces.append(str(payload["playlist_name"]))
        self.track_cache_label.setText(" · ".join(pieces))

    def _set_playlist_refresh_cooldown(self, seconds: int | None):
        if seconds and seconds > 0:
            self._playlist_refresh_cooldown_until = datetime.now(timezone.utc) + timedelta(seconds=seconds)
            self._playlist_refresh_cooldown_timer.start()
        else:
            self._playlist_refresh_cooldown_until = None
            self._playlist_refresh_cooldown_timer.stop()
        self._refresh_playlist_refresh_cooldown()
        self._save_runtime_state()

    def _refresh_playlist_refresh_cooldown(self):
        until = self._playlist_refresh_cooldown_until
        if until is None:
            self.refresh_playlists_btn.setEnabled(not self._playlist_refresh_in_progress)
            return

        remaining = int((until - datetime.now(timezone.utc)).total_seconds())
        if remaining <= 0:
            self._playlist_refresh_cooldown_until = None
            self._playlist_refresh_cooldown_timer.stop()
            self.refresh_playlists_btn.setEnabled(not self._playlist_refresh_in_progress)
            self.refresh_playlists_btn.setText("Refresh Playlists")
            if self._cached_playlist_payload:
                self._set_playlist_cache_badge(self._cached_playlist_payload)
            self._save_runtime_state()
            if self._refresh_after_cooldown_pending:
                return
            if not self._playlist_refresh_in_progress:
                self._refresh_after_cooldown_pending = True
                QTimer.singleShot(0, self._auto_refresh_playlists_after_cooldown)
            return

        self.refresh_playlists_btn.setEnabled(False)
        self.refresh_playlists_btn.setText(f"Refresh Playlists ({remaining}s)")

    def _auto_refresh_playlists_after_cooldown(self):
        if self._playlist_refresh_in_progress:
            self._refresh_after_cooldown_pending = True
            return
        self._refresh_after_cooldown_pending = False
        if self.playlists:
            self.status_bar.showMessage("Refresh cooldown expired; checking Spotify again…")
            self._load_playlists(preserve_visible=True)

    def _show_playlist_loading_placeholder(self):
        self.playlist_list.setEnabled(False)
        self.playlist_list.clear()
        loading_item = QListWidgetItem("Loading playlists…")
        loading_item.setFlags(Qt.ItemIsEnabled)
        self.playlist_list.addItem(loading_item)
        self.playlist_title.setText("Loading playlists…")
        self.track_table.setRowCount(0)
        self.tracks = []
        self.track_states = {}
        self._track_errors = {}
        self._track_paths = {}
        self.download_all_btn.setEnabled(False)
        self.download_selected_btn.setEnabled(False)
        self.retry_failed_btn.setEnabled(False)
        self.find_manual_btn.setEnabled(False)
        self.open_file_btn.setEnabled(False)
        self.export_failed_btn.setEnabled(False)
        self.status_bar.showMessage("Loading playlists…")

    def _render_playlist_list(self, playlists: list[dict], selected_playlist_id: str | None = None):
        self.playlists = playlists
        self.playlist_list.clear()

        liked_item = QListWidgetItem("♥ Liked Songs")
        liked_item.setData(Qt.UserRole, "__liked__")
        liked_item.setData(Qt.UserRole + 1, None)
        self.playlist_list.addItem(liked_item)

        selected_row = None
        for pl in self.playlists:
            row_index = self.playlist_list.count()
            item = QListWidgetItem(f"{pl['name']}  ({pl['total']})")
            item.setData(Qt.UserRole, pl["id"])
            item.setData(Qt.UserRole + 1, pl.get("total"))
            tooltip_bits = [pl.get("name", "")]
            if pl.get("owner_name"):
                tooltip_bits.append(f"Owner: {pl['owner_name']}")
            if pl.get("description"):
                tooltip_bits.append(pl["description"])
            if pl.get("public") is not None:
                tooltip_bits.append(f"Public: {pl['public']}")
            item.setToolTip("\n".join(bit for bit in tooltip_bits if bit))
            self.playlist_list.addItem(item)
            if selected_playlist_id is not None and pl.get("id") == selected_playlist_id:
                selected_row = row_index

        if selected_row is not None:
            self.playlist_list.setCurrentRow(selected_row)
        elif self.playlist_list.count() > 0 and self.playlist_list.currentRow() < 0:
            self.playlist_list.setCurrentRow(0)

    def _load_playlists(self, preserve_visible: bool = False):
        if self._playlist_refresh_in_progress:
            self.status_bar.showMessage("Playlist refresh already in progress…")
            return

        self._set_playlist_refresh_state(True)
        self._playlist_refresh_mode = "manual" if preserve_visible else "startup"
        account_id = self._current_account_id()
        cached_payload = playlist_cache.load()
        if cached_payload and not playlist_cache.cache_matches_account(cached_payload, account_id):
            logger.info("Ignoring playlist cache from a different Spotify account")
            cached_payload = None
        self._cached_playlist_payload = cached_payload
        has_cached_playlists = bool(cached_payload and cached_payload.get("playlists"))
        cached_is_fresh = bool(cached_payload) and not playlist_cache.is_stale(cached_payload, PLAYLIST_CACHE_MAX_AGE_SECONDS)

        if has_cached_playlists:
            persisted_playlist_id = self._runtime_state.get("last_playlist_id")
            cached_selection = cached_payload.get("selected_playlist_id") if cached_payload else None
            selected_playlist_id = self._current_playlist_item_id() if preserve_visible else (persisted_playlist_id or cached_selection)
            self.playlist_list.setEnabled(True)
            self._render_playlist_list(cached_payload["playlists"], selected_playlist_id=selected_playlist_id)
            self._set_playlist_cache_badge(cached_payload)
            if cached_is_fresh and not preserve_visible:
                self._set_playlist_refresh_state(False)
                self.status_bar.showMessage("Loaded cached playlists")
                return
            self.status_bar.showMessage("Showing cached playlists while Spotify refreshes in the background…")
        elif not preserve_visible:
            self._show_playlist_loading_placeholder()
        else:
            self.status_bar.showMessage("Refreshing playlists…")

        if not preserve_visible or not has_cached_playlists:
            self.track_table.setRowCount(0)
            self.tracks = []
            self.track_states = {}
            self._track_errors = {}
            self._track_paths = {}
            self.download_all_btn.setEnabled(False)
            self.download_selected_btn.setEnabled(False)
            self.retry_failed_btn.setEnabled(False)
            self.find_manual_btn.setEnabled(False)
            self.open_file_btn.setEnabled(False)
            self.export_failed_btn.setEnabled(False)

        self._playlist_loader_thread = QThread(self)
        self._playlist_loader = PlaylistsLoader(self.sp)
        self._playlist_loader.moveToThread(self._playlist_loader_thread)
        self._playlist_loader_thread.started.connect(self._playlist_loader.run)
        self._playlist_loader.finished.connect(self._on_playlists_loaded)
        self._playlist_loader.error.connect(self._on_playlists_load_error)
        self._playlist_loader.finished.connect(self._playlist_loader_thread.quit)
        self._playlist_loader.error.connect(self._playlist_loader_thread.quit)
        self._retain_thread(self._playlist_loader_thread)
        self._playlist_loader_thread.start()

    def _refresh_playlists(self):
        if self._playlist_refresh_in_progress:
            self.status_bar.showMessage("Playlist refresh already in progress…")
            return
        if self._playlist_refresh_cooldown_until is not None:
            remaining = int((self._playlist_refresh_cooldown_until - datetime.now(timezone.utc)).total_seconds())
            if remaining > 0:
                self.status_bar.showMessage(f"Playlist refresh is cooling down for another {remaining}s")
                return
        self._load_playlists(preserve_visible=True)

    def _on_playlists_loaded(self, playlists: list[dict]):
        selected_playlist_id = _resolve_playlist_selection(playlists, self._current_playlist_item_id())
        self.playlists = playlists
        try:
            saved_payload = playlist_cache.save(
                playlists,
                account_id=self._current_account_id(),
                selected_playlist_id=selected_playlist_id,
            )
        except Exception as e:
            logger.warning("Could not save playlist cache: %s", e)
            saved_payload = {
                "updated_at": None,
                "account_id": self._current_account_id(),
                "selected_playlist_id": selected_playlist_id,
                "playlists": playlists,
            }
        self.playlist_list.setEnabled(True)
        self._render_playlist_list(playlists, selected_playlist_id=selected_playlist_id)
        selected_playlist_id = _resolve_playlist_selection(playlists, self._current_playlist_item_id())
        if saved_payload.get("selected_playlist_id") != selected_playlist_id:
            saved_payload["selected_playlist_id"] = selected_playlist_id
        self._cached_playlist_payload = saved_payload
        self._set_playlist_cache_badge(self._cached_playlist_payload)
        self._set_playlist_refresh_cooldown(None)
        self.status_bar.showMessage(f"Loaded {len(self.playlists)} playlists")
        if self.playlist_list.count() > 0 and self.playlist_list.currentRow() < 0:
            self.playlist_list.setCurrentRow(0)
        self._set_playlist_refresh_state(False)
        self._save_runtime_state()

    def _on_playlists_load_error(self, error: str):
        logger.error("Playlist list load failed: %s", error)
        self._set_playlist_refresh_state(False)
        retry_after = sc.extract_retry_after_seconds(error)
        if retry_after:
            self._set_playlist_refresh_cooldown(retry_after)
        if self.playlists:
            self.playlist_list.setEnabled(True)
            self._set_playlist_cache_badge(self._cached_playlist_payload)
            cooldown_note = f" Refresh cooling down for about {retry_after}s." if retry_after else ""
            self.status_bar.showMessage(
                f"Playlist refresh failed; keeping the current playlist list. Reason: {error}.{cooldown_note}"
            )
            return

        self.playlists = []
        self.playlist_list.setEnabled(True)
        self.playlist_list.clear()
        error_item = QListWidgetItem("Failed to load playlists")
        error_item.setFlags(Qt.ItemIsEnabled)
        error_item.setToolTip(error)
        self.playlist_list.addItem(error_item)
        self.playlist_title.setText("Playlists unavailable")
        self.status_bar.showMessage(f"Playlist load failed: {error}")
        QMessageBox.warning(
            self,
            "Playlist load failed",
            "We couldn't load your Spotify playlists.\n\n"
            f"Reason: {error}\n\n"
            "Check that Spotify is signed in, the network is available, and the app has permission to read playlists.",
        )

    def _on_playlist_selected(self, row: int):
        if row < 0:
            return
        item = self.playlist_list.item(row)
        playlist_id = item.data(Qt.UserRole)
        if not playlist_id:
            return
        if self._current_playlist_id and self._current_playlist_id != playlist_id:
            self._persist_current_track_view_state()
        self._current_playlist_id = playlist_id
        self._current_playlist_total = item.data(Qt.UserRole + 1)
        logger.info("Loading playlist tracks: %s (%s)", item.text(), playlist_id)
        self.playlist_title.setText(item.text())
        self.track_cache_label.setText("Loading tracks…")
        self._track_load_token += 1
        self._save_runtime_state()

        cached_tracks_payload = track_cache.load(playlist_id, account_id=self._current_account_id())
        cached_tracks_fresh = bool(cached_tracks_payload) and not track_cache.is_stale(cached_tracks_payload, TRACK_CACHE_MAX_AGE_SECONDS)

        if cached_tracks_payload:
            cached_tracks = cached_tracks_payload.get("tracks") or []
            if isinstance(cached_tracks_payload.get("playlist_total"), int):
                self._current_playlist_total = cached_tracks_payload.get("playlist_total")
            self._render_tracks(cached_tracks, source="cache")
            cache_age = track_cache.describe_age(cached_tracks_payload)
            self._set_track_cache_badge(cached_tracks_payload)
            if cached_tracks_fresh:
                self.status_bar.showMessage(f"Loaded cached tracks{f' ({cache_age})' if cache_age else ''}")
                return
            self.status_bar.showMessage(f"Showing cached tracks while refreshing in the background{f' ({cache_age})' if cache_age else ''}…")
        else:
            self.track_table.setRowCount(0)
            self.tracks = []
            self.track_states = {}
            self._track_errors = {}
            self._track_paths = {}
            self.download_all_btn.setEnabled(False)
            self.download_selected_btn.setEnabled(False)
            self._refresh_action_buttons()
            self.status_bar.showMessage("Loading tracks…")

        token = self._track_load_token
        self._loader_thread = QThread(self)
        self._loader = PlaylistLoader(self.sp, playlist_id)
        self._loader.moveToThread(self._loader_thread)
        self._loader_thread.started.connect(self._loader.run)
        self._loader.finished.connect(lambda tracks, t=token: self._on_tracks_loaded(t, tracks))
        self._loader.error.connect(lambda error, t=token: self._on_tracks_load_error(t, error))
        self._loader.finished.connect(self._loader_thread.quit)
        self._loader.error.connect(self._loader_thread.quit)
        self._retain_thread(self._loader_thread)
        self._loader_thread.start()

    def _render_tracks(self, tracks: list[dict], source: str = "network"):
        self.tracks = tracks
        self.track_table.setRowCount(len(tracks))
        output_folder = self.cfg.get("output_folder", "")

        unsupported_count = 0
        for i, track in enumerate(tracks):
            downloadable = bool(track.get("downloadable", not track.get("is_local")))
            media_type = track.get("media_type", "track")
            track_name = track.get("name", "")
            track_artist = track.get("artist", "")
            track_album = track.get("album", "")
            position = track.get("playlist_position", i + 1)
            self.track_table.setItem(i, 0, QTableWidgetItem(str(position)))
            self.track_table.setItem(i, 1, QTableWidgetItem(track_name))
            self.track_table.setItem(i, 2, QTableWidgetItem(track_artist))
            self.track_table.setItem(i, 3, QTableWidgetItem(track_album))
            self.track_table.setItem(i, 4, QTableWidgetItem(_fmt_duration(track.get("duration_ms", 0))))

            if track.get("is_local"):
                state = TrackState.LOCAL
                status_text = "Local Spotify file"
                status_color = "#8d6e63"
                status_tip = "Stored locally in Spotify; it cannot be downloaded from Spotify."
            elif not downloadable:
                state = TrackState.UNSUPPORTED
                status_text = "Unsupported item"
                if media_type == "episode":
                    status_text = "Podcast episode"
                status_color = "#757575"
                status_tip = track.get("unsupported_reason") or "Spotify did not return a downloadable track for this row."
                unsupported_count += 1
            else:
                exists = downloader.already_downloaded(track, output_folder, self._downloaded_paths)
                state = TrackState.EXISTS if exists else TrackState.PENDING
                status_text = "Downloaded" if exists else ""
                status_color = "#2e7d32"
                status_tip = None

            self.track_states[track["id"]] = state

            status_item = QTableWidgetItem(status_text)
            if state == TrackState.EXISTS:
                status_item.setForeground(QBrush(QColor(status_color)))
                existing_path = downloader.find_existing_download_path(track, output_folder, self._downloaded_paths)
                if existing_path:
                    status_item.setToolTip(f"Already in folder: {existing_path}")
            elif state in (TrackState.LOCAL, TrackState.UNSUPPORTED):
                status_item.setForeground(QBrush(QColor(status_color)))
                status_item.setToolTip(status_tip)
            self.track_table.setItem(i, 5, status_item)

        pending = sum(1 for s in self.track_states.values() if s == TrackState.PENDING)
        self.download_all_btn.setEnabled(pending > 0)
        total_hint = self._current_playlist_total
        visible_count = len(tracks)
        if source == "network" and self._current_playlist_id:
            try:
                saved_tracks_payload = track_cache.save(
                    self._current_playlist_id,
                    tracks,
                    account_id=self._current_account_id(),
                    playlist_name=self.playlist_title.text(),
                    playlist_total=total_hint,
                )
                self._set_track_cache_badge(saved_tracks_payload)
            except Exception as e:
                logger.warning("Could not save track cache: %s", e)
        if isinstance(total_hint, int) and total_hint > 0 and visible_count < total_hint:
            msg = (
                f"Spotify returned {visible_count} of {total_hint} items for this playlist. "
                "That usually means the playlist includes local files, episodes, or other rows Spotify does not fully expose."
            )
            logger.warning(msg)
            self.status_bar.showMessage(msg)
            QMessageBox.warning(self, "Partial playlist load", msg)
        elif unsupported_count:
            self.status_bar.showMessage(f"{visible_count} items loaded  ·  {pending} downloadable  ·  {unsupported_count} unsupported")
        else:
            self.status_bar.showMessage(f"{visible_count} tracks  ·  {pending} not yet downloaded")
        self._restore_track_view_state(self._current_playlist_id)
        self._refresh_action_buttons()
        self._restore_saved_queue_for_playlist(self._current_playlist_id)
        self._save_runtime_state()

    def _on_tracks_loaded(self, token: int, tracks: list[dict]):
        if token != self._track_load_token:
            return
        self._render_tracks(tracks, source="network")

    def _on_tracks_load_error(self, token: int, error: str):
        if token != self._track_load_token:
            return
        logger.error("Playlist track load failed: %s", error)
        if self.tracks:
            self.status_bar.showMessage(f"Track refresh failed; keeping cached tracks. Reason: {error}")
            return
        self.status_bar.showMessage(f"Error: {error}")
        QMessageBox.warning(self, "Playlist load failed", f"Could not load tracks for this playlist:\n\n{error}")

    # ── Downloads ─────────────────────────────────────────────────────────────

    def _update_download_btn(self):
        self._refresh_action_buttons()

    def _refresh_action_buttons(self):
        rows = sorted(set(item.row() for item in self.track_table.selectedItems()))
        selected_tracks = [self.tracks[r] for r in rows if r < len(self.tracks)]
        selected_states = [self.track_states.get(track["id"]) for track in selected_tracks]

        has_selected_downloadable = any(track.get("downloadable", not track.get("is_local")) for track in selected_tracks)
        has_downloadable = any(
            track.get("downloadable", not track.get("is_local")) and state in (TrackState.PENDING, TrackState.ERROR, TrackState.CANCELLED)
            for track, state in zip(selected_tracks, selected_states)
        )
        has_failed = any(state in (TrackState.ERROR, TrackState.CANCELLED) for state in selected_states)
        has_existing = any(state in (TrackState.DONE, TrackState.EXISTS) for state in selected_states)
        any_failed_in_library = any(
            state in (TrackState.ERROR, TrackState.CANCELLED) for state in self.track_states.values()
        )

        self.download_selected_btn.setEnabled(has_downloadable)
        self.retry_failed_btn.setEnabled(any_failed_in_library)
        self.find_manual_btn.setEnabled(has_selected_downloadable)
        self.open_file_btn.setEnabled(has_existing)
        self.export_failed_btn.setEnabled(any_failed_in_library)

    def _download_selected(self):
        rows = set(item.row() for item in self.track_table.selectedItems())
        tracks = [self.tracks[r] for r in rows if r < len(self.tracks) and self.tracks[r].get("downloadable", not self.tracks[r].get("is_local"))]
        if rows and not tracks:
            QMessageBox.information(
                self,
                "Unsupported items",
                "The selected items are local files, podcasts, or other Spotify rows that cannot be downloaded.",
            )
            return
        self._start_downloads(tracks)

    def _download_all(self):
        pending = [t for t in self.tracks if self.track_states.get(t["id"]) == TrackState.PENDING]
        if not pending:
            QMessageBox.information(self, "All Done", "All tracks are already downloaded.")
            return
        self._start_downloads(pending)

    def _retry_failed_tracks(self, *_):
        failed = [
            track for track in self.tracks
            if self.track_states.get(track["id"]) in (TrackState.ERROR, TrackState.CANCELLED)
        ]
        if not failed:
            QMessageBox.information(self, "Nothing to retry", "There are no failed tracks to retry.")
            return
        self._start_downloads(failed)

    def _retry_track(self, track_id: str):
        for track in self.tracks:
            if track["id"] == track_id:
                if self.track_states.get(track_id) in (TrackState.ERROR, TrackState.CANCELLED):
                    self._start_downloads([track])
                return

    def _apply_manual_url(self, track_id: str, url: str):
        url = (url or "").strip()
        if not url:
            QMessageBox.information(self, "Missing URL", "Paste a YouTube URL first.")
            return
        for track in self.tracks:
            if track["id"] == track_id:
                if track.get("is_local"):
                    QMessageBox.information(self, "Local track", "Spotify local files cannot be downloaded from a pasted YouTube URL.")
                    return
                if self.track_states.get(track_id) not in (TrackState.ERROR, TrackState.CANCELLED):
                    QMessageBox.information(self, "Not a failed track", "Use the manual URL option on a failed track.")
                    return
                self._start_downloads([track], source_url=url)
                return

    def _find_selected_manually(self, *_):
        track = self._selected_track(lambda t: t.get("downloadable", not t.get("is_local")))
        if not track:
            QMessageBox.information(self, "No track selected", "Select a track first.")
            return
        if track.get("is_local"):
            QMessageBox.information(self, "Local track", "Spotify local files cannot be searched or downloaded through the web search flow.")
            return
        webbrowser.open(downloader.youtube_search_url(track))

    def _open_selected_file_location(self, *_):
        track = self._selected_track(lambda t: self.track_states.get(t["id"]) in (TrackState.DONE, TrackState.EXISTS))
        if not track:
            QMessageBox.information(self, "No track selected", "Select a downloaded track first.")
            return
        path = downloader.find_existing_download_path(track, self.cfg.get("output_folder", ""), self._downloaded_paths)
        if not path:
            QMessageBox.information(self, "Not found", "That track is not currently in the output folder.")
            return
        self._open_path_in_file_manager(path)

    def _open_output_folder(self):
        path = self.cfg.get("output_folder", "")
        if not path:
            QMessageBox.information(self, "No folder set", "Set an output folder in Settings first.")
            return
        self._open_path_in_file_manager(path)

    def _open_debug_log(self):
        self._open_path_in_file_manager(LOG_FILE)

    def _copy_debug_log_path(self):
        QApplication.clipboard().setText(LOG_FILE)
        self.status_bar.showMessage(f"Copied debug log path: {LOG_FILE}", 5000)

    def _export_debug_bundle(self):
        default_name = os.path.join(
            self.cfg.get("output_folder", "") or os.path.expanduser("~"),
            "spotifyvdj-debug-bundle.zip",
        )
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Export Debug Bundle",
            default_name,
            "ZIP Archives (*.zip);;All Files (*)",
        )
        if not path:
            return
        if not path.lower().endswith(".zip"):
            path += ".zip"

        bundle_dir = os.path.dirname(path) or os.path.expanduser("~")
        os.makedirs(bundle_dir, exist_ok=True)

        redacted_cfg = dict(self.cfg)
        if redacted_cfg.get("client_secret"):
            redacted_cfg["client_secret"] = "[REDACTED]"
        if redacted_cfg.get("client_id"):
            redacted_cfg["client_id"] = redacted_cfg["client_id"][:4] + "…[REDACTED]"

        system_info = {
            "app": "Spotify VDJ",
            "python": sys.version.replace("\n", " "),
            "platform": platform.platform(),
            "machine": platform.machine(),
            "processor": platform.processor(),
            "log_file": LOG_FILE,
            "config_file": config.CONFIG_FILE,
        }

        diagnostics = {
            "current_account_id": self._current_account_id(),
            "current_playlist_id": self._current_playlist_id,
            "playlist_refresh_cooldown_until": self._playlist_refresh_cooldown_until.isoformat().replace("+00:00", "Z") if self._playlist_refresh_cooldown_until else None,
            "playlist_cache": self._cached_playlist_payload,
            "runtime_state": self._runtime_state,
            "queue_entries": self.queue_panel.snapshot_entries() if hasattr(self, "queue_panel") else [],
        }
        track_cache_payload = None
        if self._current_playlist_id:
            track_cache_payload = track_cache.load(self._current_playlist_id, account_id=self._current_account_id())
        
        files_written = []
        with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            if os.path.exists(LOG_FILE):
                zf.write(LOG_FILE, arcname="debug.log")
                files_written.append("debug.log")
            zf.writestr("config.redacted.json", json.dumps(redacted_cfg, indent=2, ensure_ascii=False))
            files_written.append("config.redacted.json")
            zf.writestr("system-info.json", json.dumps(system_info, indent=2, ensure_ascii=False))
            files_written.append("system-info.json")
            zf.writestr("diagnostics.json", json.dumps(diagnostics, indent=2, ensure_ascii=False))
            files_written.append("diagnostics.json")
            if self._cached_playlist_payload:
                zf.writestr("playlist-cache.json", json.dumps(self._cached_playlist_payload, indent=2, ensure_ascii=False))
                files_written.append("playlist-cache.json")
            if track_cache_payload:
                zf.writestr("track-cache.json", json.dumps(track_cache_payload, indent=2, ensure_ascii=False))
                files_written.append("track-cache.json")

        self.status_bar.showMessage(f"Exported debug bundle: {path}", 5000)
        QMessageBox.information(
            self,
            "Debug bundle exported",
            "Saved a support bundle containing:\n- " + "\n- ".join(files_written) + f"\n\n{path}",
        )

    def _export_failed_tracks(self, *_):
        failed_tracks = [
            track for track in self.tracks
            if self.track_states.get(track["id"]) in (TrackState.ERROR, TrackState.CANCELLED)
        ]
        if not failed_tracks:
            QMessageBox.information(self, "Nothing to export", "There are no failed tracks to export.")
            return

        path, _ = QFileDialog.getSaveFileName(
            self,
            "Export failed tracks",
            os.path.join(self.cfg.get("output_folder", "") or os.path.expanduser("~"), "spotifyvdj-failed-tracks.csv"),
            "CSV Files (*.csv);;All Files (*)",
        )
        if not path:
            return
        if not path.lower().endswith(".csv"):
            path += ".csv"

        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["Title", "Artist", "Album", "Status", "Error", "Manual Search", "Output Path"])
            for track in failed_tracks:
                track_id = track["id"]
                error = self._track_errors.get(track_id, self._status_tooltip_for_track(track_id))
                writer.writerow([
                    track.get("name", ""),
                    track.get("artist", ""),
                    track.get("album", ""),
                    self.track_states.get(track_id, ""),
                    error or "",
                    downloader.youtube_search_url(track),
                    self._track_paths.get(track_id, ""),
                ])
        QMessageBox.information(self, "Export complete", f"Saved failed tracks to:\n{path}")


    def _selected_track(self, predicate=None) -> dict | None:
        rows = sorted(set(item.row() for item in self.track_table.selectedItems()))
        for row in rows:
            if 0 <= row < len(self.tracks):
                track = self.tracks[row]
                if predicate is None or predicate(track):
                    return track
        return None

    def _open_path_in_file_manager(self, path: str):
        if sys.platform == "win32":
            subprocess.Popen(["explorer", "/select,", path])
            return
        if sys.platform == "darwin":
            subprocess.Popen(["open", "-R", path])
            return
        subprocess.Popen(["xdg-open", os.path.dirname(path) or path])

    def _status_tooltip_for_track(self, track_id: str) -> str:
        for row, track in enumerate(self.tracks):
            if track["id"] == track_id:
                item = self.track_table.item(row, 5)
                return item.toolTip() if item else ""
        return ""

    def _configure_folder_watch_timer(self):
        watch_enabled = bool(self.cfg.get("watch_output_folder", True))
        interval = max(5, int(self.cfg.get("watch_interval_seconds", 30)))
        self._watch_timer.setInterval(interval * 1000)
        if watch_enabled:
            self._watch_timer.start()
        else:
            self._watch_timer.stop()

    def _rescan_output_folder(self, *_):
        output_folder = self.cfg.get("output_folder", "")
        self._downloaded_paths = downloader.build_download_index(output_folder)
        if not self.tracks:
            self.status_bar.showMessage("Output folder rescanned")
            return

        for track in self.tracks:
            if track.get("is_local"):
                continue
            track_id = track["id"]
            current_state = self.track_states.get(track_id)
            if current_state == TrackState.DOWNLOADING:
                continue

            existing_path = downloader.find_existing_download_path(track, output_folder, self._downloaded_paths)
            if existing_path:
                self.track_states[track_id] = TrackState.EXISTS
                self._track_paths[track_id] = existing_path
                self._track_errors.pop(track_id, None)
                self._set_track_status(track_id, "Downloaded", "#2e7d32", tooltip=f"Already in folder: {existing_path}")
                self.queue_panel.update_progress(track_id, "Downloaded", 100)
            elif current_state in (TrackState.EXISTS, TrackState.DONE):
                self.track_states[track_id] = TrackState.PENDING
                self._track_paths.pop(track_id, None)
                self._set_track_status(track_id, "", "#000000")
            elif current_state == TrackState.ERROR and self._track_errors.get(track_id):
                self._set_track_status(track_id, "Error", "#c62828", tooltip=self._track_errors.get(track_id))

        self._refresh_action_buttons()
        pending = sum(1 for s in self.track_states.values() if s == TrackState.PENDING)
        available = sum(1 for s in self.track_states.values() if s in (TrackState.DONE, TrackState.EXISTS))
        self.status_bar.showMessage(f"Rescanned output folder: {available}/{len(self.tracks)} available, {pending} pending")


    def _start_downloads(self, tracks: list[dict], source_url: str | None = None):
        output_folder = self.cfg.get("output_folder", "")
        if not output_folder:
            QMessageBox.warning(self, "No Folder", "Please set an output folder in Settings.")
            return

        queued = 0
        for track in tracks:
            if track.get("is_local"):
                continue
            state = self.track_states.get(track["id"])
            if state in (TrackState.DOWNLOADING, TrackState.DONE, TrackState.EXISTS):
                continue

            existing_path = downloader.find_existing_download_path(track, output_folder, self._downloaded_paths)
            if existing_path:
                self.track_states[track["id"]] = TrackState.EXISTS
                self._track_paths[track["id"]] = existing_path
                self._track_errors.pop(track["id"], None)
                self._set_track_status(track["id"], "Downloaded", "#2e7d32", tooltip=f"Already in folder: {existing_path}")
                continue

            self.track_states[track["id"]] = TrackState.DOWNLOADING
            self._track_errors.pop(track["id"], None)
            self._track_paths.pop(track["id"], None)
            self._set_track_status(track["id"], "Queued…", "#1565c0")
            queued += 1

            entry = QueueEntry(
                track_id=track["id"],
                name=track["name"],
                artist=track["artist"],
                album=track.get("album", ""),
                playlist_id=self._current_playlist_id,
                track=track,
                source_url=source_url,
                status="Queued",
            )
            self.queue_panel.add(entry)

            job = DownloadJob(
                track=track,
                output_folder=output_folder,
                on_progress=self._make_progress_cb(track["id"]),
                on_done=self._make_done_cb(track["id"]),
                source_url=source_url if len(tracks) == 1 else None,
            )
            self._dl_manager.enqueue(job)
            # cancel_fn wired after enqueue so handle exists
            self.queue_panel.set_cancel_fn(track["id"], lambda tid=track["id"]: self._dl_manager.cancel(tid))

        self._refresh_action_buttons()
        self._save_runtime_state()
        if queued:
            self._queue_dock.raise_()
            self.status_bar.showMessage(f"Queued {queued} track(s) for download…")

    def _make_progress_cb(self, track_id: str):
        def cb(status: str, pct: float):
            self._progress_signal.emit(track_id, status, pct)
        return cb

    def _make_done_cb(self, track_id: str):
        def cb(tid: str, success: bool, path_or_error: str):
            self._done_signal.emit(tid, success, path_or_error)
        return cb

    def _on_progress(self, track_id: str, status: str, pct: float):
        self._set_track_status(track_id, status, "#1565c0")
        self.queue_panel.update_progress(track_id, status, pct)

    def _on_priority_requested(self, track_id: str):
        moved = self._dl_manager.prioritize(track_id)
        if moved:
            self.status_bar.showMessage(f"Track moved to front of queue")

    def _on_done(self, track_id: str, success: bool, path_or_error: str):
        if success:
            self.track_states[track_id] = TrackState.DONE
            self._track_errors.pop(track_id, None)
            self._track_paths[track_id] = path_or_error
            self._set_track_status(track_id, "Downloaded", "#2e7d32", tooltip=path_or_error)
            self.queue_panel.update_progress(track_id, "Downloaded", 100)
            if path_or_error and path_or_error not in self._downloaded_paths:
                self._downloaded_paths.append(path_or_error)
        elif path_or_error == "Cancelled":
            self.track_states[track_id] = TrackState.CANCELLED
            self._track_paths.pop(track_id, None)
            self._set_track_status(track_id, "Cancelled", "#888", tooltip="Download cancelled")
            self.queue_panel.update_progress(track_id, "Cancelled", 0)
        else:
            self.track_states[track_id] = TrackState.ERROR
            self._track_paths.pop(track_id, None)
            self._track_errors[track_id] = path_or_error
            self._set_track_status(track_id, "Error", "#c62828", tooltip=path_or_error)
            self.queue_panel.update_progress(track_id, f"Error: {path_or_error.splitlines()[0][:120]}", 0)

        active = sum(1 for s in self.track_states.values() if s == TrackState.DOWNLOADING)
        done = sum(1 for s in self.track_states.values() if s in (TrackState.DONE, TrackState.EXISTS))
        self._refresh_action_buttons()
        self._save_runtime_state()
        if active == 0:
            self.status_bar.showMessage(f"{done}/{len(self.tracks)} tracks available in VDJ folder")

    def _set_track_status(self, track_id: str, text: str, color: str = "#000000", tooltip: str | None = None):
        for i, track in enumerate(self.tracks):
            if track["id"] == track_id:
                item = QTableWidgetItem(text)
                item.setForeground(QBrush(QColor(color)))
                if tooltip:
                    item.setToolTip(tooltip)
                self.track_table.setItem(i, 5, item)
                return

    def closeEvent(self, a0):
        self._save_runtime_state()
        super().closeEvent(a0)

    # ── Settings / helpers ────────────────────────────────────────────────────

    def _open_settings(self):
        from gui.setup_dialog import SetupDialog
        dlg = SetupDialog(self.cfg, self)
        if dlg.exec_():
            self.cfg = dlg.get_config()
            try:
                self.sp = sc.create_client(
                    self.cfg["client_id"],
                    self.cfg["client_secret"],
                    self.cfg["redirect_uri"],
                )
                self._spotify_account_id = None
                self._runtime_state = ui_state.load(account_id=self._current_account_id()) or {}
                self._apply_saved_refresh_cooldown()
                self._dl_manager.set_max_concurrent(int(self.cfg.get("max_concurrent_downloads", 2)))
                self._downloaded_paths = downloader.build_download_index(self.cfg.get("output_folder", ""))
                self._configure_folder_watch_timer()
                self._rescan_output_folder()
                self._load_playlists()
            except Exception as e:
                QMessageBox.critical(self, "Auth Error", str(e))

    def _open_output_folder(self):
        folder = self.cfg.get("output_folder", "")
        if folder and os.path.exists(folder):
            import subprocess, sys
            if sys.platform == "win32":
                os.startfile(folder)
            else:
                subprocess.Popen(["xdg-open", folder])
        else:
            QMessageBox.information(self, "No Folder", "Output folder not set or doesn't exist yet.")
