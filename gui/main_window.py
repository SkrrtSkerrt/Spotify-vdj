import os
from PyQt5.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QVBoxLayout,
    QListWidget, QListWidgetItem, QTableWidget, QTableWidgetItem,
    QPushButton, QLabel, QHeaderView, QSplitter,
    QStatusBar, QAction, QAbstractItemView, QMessageBox,
    QDockWidget
)
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QObject
from PyQt5.QtGui import QFont, QColor, QBrush, QIcon
import spotipy

import config
import spotify_client as sc
import downloader
from download_manager import DownloadManager, DownloadJob
from gui.queue_panel import QueuePanel, QueueEntry
from gui.preview_player import PreviewPlayer
from resource_utils import resource_path


def _fmt_duration(ms: int) -> str:
    s = ms // 1000
    return f"{s // 60}:{s % 60:02d}"


class TrackState:
    PENDING = "pending"
    DOWNLOADING = "downloading"
    DONE = "done"
    ERROR = "error"
    EXISTS = "exists"
    CANCELLED = "cancelled"


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
        self._dl_manager = DownloadManager(max_concurrent=int(cfg.get("max_concurrent_downloads", 2)))
        self._downloaded_paths: list[str] = downloader.build_download_index(cfg.get("output_folder", ""))

        self._progress_signal.connect(self._on_progress)
        self._done_signal.connect(self._on_done)

        self.setWindowTitle("Spotify VDJ")
        self.setWindowIcon(QIcon(resource_path("icon.ico")))
        self.setMinimumSize(1000, 650)
        self._build_menu()
        self._build_ui()
        self._build_docks()
        self._load_playlists()

    # ── Menu ─────────────────────────────────────────────────────────────────

    def _build_menu(self):
        menubar = self.menuBar()
        file_menu = menubar.addMenu("File")

        settings_action = QAction("Settings…", self)
        settings_action.triggered.connect(self._open_settings)
        file_menu.addAction(settings_action)

        open_folder_action = QAction("Open Output Folder", self)
        open_folder_action.triggered.connect(self._open_output_folder)
        file_menu.addAction(open_folder_action)

        view_menu = menubar.addMenu("View")
        self._toggle_queue_action = QAction("Show Queue", self, checkable=True, checked=True)
        self._toggle_queue_action.triggered.connect(self._toggle_queue_dock)
        view_menu.addAction(self._toggle_queue_action)

        self._toggle_preview_action = QAction("Show Preview Player", self, checkable=True, checked=True)
        self._toggle_preview_action.triggered.connect(self._toggle_preview_dock)
        view_menu.addAction(self._toggle_preview_action)

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
        left_layout.addWidget(self.playlist_list)
        splitter.addWidget(left)

        # Right: track table
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)

        top_bar = QHBoxLayout()
        self.playlist_title = QLabel("Select a playlist")
        self.playlist_title.setFont(QFont("", 11, QFont.Bold))
        top_bar.addWidget(self.playlist_title)
        top_bar.addStretch()

        self.download_selected_btn = QPushButton("Download Selected")
        self.download_selected_btn.clicked.connect(self._download_selected)
        self.download_selected_btn.setEnabled(False)

        self.download_all_btn = QPushButton("Download All")
        self.download_all_btn.clicked.connect(self._download_all)
        self.download_all_btn.setEnabled(False)

        top_bar.addWidget(self.download_selected_btn)
        top_bar.addWidget(self.download_all_btn)
        right_layout.addLayout(top_bar)

        # Track table — extra "Preview" column
        self.track_table = QTableWidget(0, 6)
        self.track_table.setHorizontalHeaderLabels(["#", "Title", "Artist", "Duration", "Status", "Preview"])
        self.track_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.track_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.track_table.setColumnWidth(0, 36)
        self.track_table.setColumnWidth(3, 66)
        self.track_table.setColumnWidth(4, 110)
        self.track_table.setColumnWidth(5, 80)
        self.track_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.track_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.track_table.setAlternatingRowColors(True)
        self.track_table.verticalHeader().setDefaultSectionSize(28)
        self.track_table.itemSelectionChanged.connect(self._update_download_btn)
        right_layout.addWidget(self.track_table)

        splitter.addWidget(right)
        splitter.setSizes([210, 790])

        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("Ready")

    # ── Dock widgets ──────────────────────────────────────────────────────────

    def _build_docks(self):
        # Preview player dock (bottom)
        self._preview_dock = QDockWidget("Preview Player", self)
        self._preview_dock.setAllowedAreas(Qt.BottomDockWidgetArea)
        self._preview_dock.setFeatures(
            QDockWidget.DockWidgetClosable | QDockWidget.DockWidgetMovable
        )
        self.preview_player = PreviewPlayer()
        self.preview_player.setFixedHeight(46)
        self._preview_dock.setWidget(self.preview_player)
        self._preview_dock.setMaximumHeight(80)
        self.addDockWidget(Qt.BottomDockWidgetArea, self._preview_dock)
        self._preview_dock.visibilityChanged.connect(
            lambda v: self._toggle_preview_action.setChecked(v)
        )

        # Queue dock (bottom, tabified with preview)
        self._queue_dock = QDockWidget("Download Queue", self)
        self._queue_dock.setAllowedAreas(Qt.BottomDockWidgetArea)
        self._queue_dock.setFeatures(
            QDockWidget.DockWidgetClosable | QDockWidget.DockWidgetMovable
        )
        self.queue_panel = QueuePanel()
        self.queue_panel.setMinimumHeight(120)
        self.queue_panel.priority_requested.connect(self._on_priority_requested)
        self._queue_dock.setWidget(self.queue_panel)
        self.addDockWidget(Qt.BottomDockWidgetArea, self._queue_dock)
        self.tabifyDockWidget(self._preview_dock, self._queue_dock)
        self._queue_dock.visibilityChanged.connect(
            lambda v: self._toggle_queue_action.setChecked(v)
        )

        # Show preview tab by default
        self._preview_dock.raise_()

    def _toggle_queue_dock(self, checked: bool):
        self._queue_dock.setVisible(checked)

    def _toggle_preview_dock(self, checked: bool):
        self._preview_dock.setVisible(checked)

    # ── Playlists ─────────────────────────────────────────────────────────────

    def _load_playlists(self):
        self.playlist_list.clear()
        self.status_bar.showMessage("Loading playlists…")
        try:
            self.playlists = sc.get_playlists(self.sp)
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to load playlists: {e}")
            return

        liked_item = QListWidgetItem("♥ Liked Songs")
        liked_item.setData(Qt.UserRole, "__liked__")
        self.playlist_list.addItem(liked_item)

        for pl in self.playlists:
            item = QListWidgetItem(f"{pl['name']}  ({pl['total']})")
            item.setData(Qt.UserRole, pl["id"])
            self.playlist_list.addItem(item)

        self.status_bar.showMessage(f"Loaded {len(self.playlists)} playlists")

    def _on_playlist_selected(self, row: int):
        if row < 0:
            return
        item = self.playlist_list.item(row)
        playlist_id = item.data(Qt.UserRole)
        self.playlist_title.setText(item.text())
        self.track_table.setRowCount(0)
        self.tracks = []
        self.track_states = {}
        self.download_all_btn.setEnabled(False)
        self.download_selected_btn.setEnabled(False)
        self.status_bar.showMessage("Loading tracks…")

        self._loader_thread = QThread()
        self._loader = PlaylistLoader(self.sp, playlist_id)
        self._loader.moveToThread(self._loader_thread)
        self._loader_thread.started.connect(self._loader.run)
        self._loader.finished.connect(self._on_tracks_loaded)
        self._loader.error.connect(lambda e: self.status_bar.showMessage(f"Error: {e}"))
        self._loader.finished.connect(self._loader_thread.quit)
        self._loader.error.connect(self._loader_thread.quit)
        self._loader_thread.start()

    def _on_tracks_loaded(self, tracks: list[dict]):
        self.tracks = tracks
        self.track_table.setRowCount(len(tracks))
        output_folder = self.cfg.get("output_folder", "")

        for i, track in enumerate(tracks):
            exists = downloader.already_downloaded(track, output_folder, self._downloaded_paths)
            state = TrackState.EXISTS if exists else TrackState.PENDING
            self.track_states[track["id"]] = state

            self.track_table.setItem(i, 0, QTableWidgetItem(str(i + 1)))
            self.track_table.setItem(i, 1, QTableWidgetItem(track["name"]))
            self.track_table.setItem(i, 2, QTableWidgetItem(track["artist"]))
            self.track_table.setItem(i, 3, QTableWidgetItem(_fmt_duration(track["duration_ms"])))

            status_item = QTableWidgetItem("Downloaded" if exists else "")
            if exists:
                status_item.setForeground(QBrush(QColor("#2e7d32")))
                existing_path = downloader.find_existing_download_path(track, output_folder, self._downloaded_paths)
                if existing_path:
                    status_item.setToolTip(f"Already in folder: {existing_path}")
            self.track_table.setItem(i, 4, status_item)

            # Preview button — greyed out if Spotify has no clip
            preview_btn = QPushButton("▶ Preview" if track.get("preview_url") else "No clip")
            preview_btn.setEnabled(bool(track.get("preview_url")))
            preview_btn.setFixedHeight(22)
            preview_btn.clicked.connect(self._make_preview_handler(track))
            self.track_table.setCellWidget(i, 5, preview_btn)

        self.download_all_btn.setEnabled(True)
        pending = sum(1 for s in self.track_states.values() if s == TrackState.PENDING)
        self.status_bar.showMessage(f"{len(tracks)} tracks  ·  {pending} not yet downloaded")

    def _make_preview_handler(self, track: dict):
        def _handler():
            self.preview_player.load_track(track)
            self._preview_dock.raise_()
        return _handler

    # ── Downloads ─────────────────────────────────────────────────────────────

    def _update_download_btn(self):
        rows = set(item.row() for item in self.track_table.selectedItems())
        self.download_selected_btn.setEnabled(len(rows) > 0)

    def _download_selected(self):
        rows = set(item.row() for item in self.track_table.selectedItems())
        tracks = [self.tracks[r] for r in rows if r < len(self.tracks)]
        self._start_downloads(tracks)

    def _download_all(self):
        pending = [t for t in self.tracks if self.track_states.get(t["id"]) == TrackState.PENDING]
        if not pending:
            QMessageBox.information(self, "All Done", "All tracks are already downloaded.")
            return
        self._start_downloads(pending)

    def _start_downloads(self, tracks: list[dict]):
        output_folder = self.cfg.get("output_folder", "")
        if not output_folder:
            QMessageBox.warning(self, "No Folder", "Please set an output folder in Settings.")
            return

        queued = 0
        for track in tracks:
            state = self.track_states.get(track["id"])
            if state in (TrackState.DOWNLOADING, TrackState.DONE, TrackState.EXISTS):
                continue

            existing_path = downloader.find_existing_download_path(track, output_folder, self._downloaded_paths)
            if existing_path:
                self.track_states[track["id"]] = TrackState.EXISTS
                self._set_track_status(track["id"], "Downloaded", "#2e7d32", tooltip=f"Already in folder: {existing_path}")
                continue

            self.track_states[track["id"]] = TrackState.DOWNLOADING
            self._set_track_status(track["id"], "Queued…", "#1565c0")
            queued += 1

            entry = QueueEntry(
                track_id=track["id"],
                name=track["name"],
                artist=track["artist"],
                status="Queued",
            )
            self.queue_panel.add(entry)

            job = DownloadJob(
                track=track,
                output_folder=output_folder,
                on_progress=self._make_progress_cb(track["id"]),
                on_done=self._make_done_cb(track["id"]),
            )
            self._dl_manager.enqueue(job)
            # cancel_fn wired after enqueue so handle exists
            self.queue_panel.set_cancel_fn(track["id"], lambda tid=track["id"]: self._dl_manager.cancel(tid))

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
            self._set_track_status(track_id, "Downloaded", "#2e7d32")
            self.queue_panel.update_progress(track_id, "Downloaded", 100)
            if path_or_error and path_or_error not in self._downloaded_paths:
                self._downloaded_paths.append(path_or_error)
        elif path_or_error == "Cancelled":
            self.track_states[track_id] = TrackState.CANCELLED
            self._set_track_status(track_id, "Cancelled", "#888")
            self.queue_panel.update_progress(track_id, "Cancelled", 0)
        else:
            self.track_states[track_id] = TrackState.ERROR
            self._set_track_status(track_id, f"Error", "#c62828", tooltip=path_or_error)
            self.queue_panel.update_progress(track_id, f"Error: {path_or_error.splitlines()[0][:120]}", 0)

        active = sum(1 for s in self.track_states.values() if s == TrackState.DOWNLOADING)
        done = sum(1 for s in self.track_states.values() if s in (TrackState.DONE, TrackState.EXISTS))
        if active == 0:
            self.status_bar.showMessage(f"{done}/{len(self.tracks)} tracks available in VDJ folder")

    def _set_track_status(self, track_id: str, text: str, color: str = "#000000", tooltip: str | None = None):
        for i, track in enumerate(self.tracks):
            if track["id"] == track_id:
                item = QTableWidgetItem(text)
                item.setForeground(QBrush(QColor(color)))
                if tooltip:
                    item.setToolTip(tooltip)
                self.track_table.setItem(i, 4, item)
                return

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
                self._dl_manager.set_max_concurrent(int(self.cfg.get("max_concurrent_downloads", 2)))
                self._downloaded_paths = downloader.build_download_index(self.cfg.get("output_folder", ""))
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
