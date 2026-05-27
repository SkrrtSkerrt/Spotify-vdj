from dataclasses import dataclass, field
from typing import Callable
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QLineEdit,
    QScrollArea, QProgressBar, QFrame
)
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QFont


@dataclass
class QueueEntry:
    track_id: str
    name: str
    artist: str
    album: str = ""
    playlist_id: str | None = None
    track: dict | None = None
    source_url: str | None = None
    status: str = "Queued"
    progress: float = 0.0
    cancel_fn: Callable | None = None


class QueueRow(QFrame):
    cancelled = pyqtSignal(str)    # track_id
    prioritized = pyqtSignal(str)  # track_id
    retry_requested = pyqtSignal(str)  # track_id
    manual_url_requested = pyqtSignal(str, str)  # track_id, url

    def __init__(self, entry: QueueEntry, parent=None):
        super().__init__(parent)
        self.track_id = entry.track_id
        self.setFrameShape(QFrame.StyledPanel)
        self.setMaximumHeight(128)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 4, 6, 4)
        layout.setSpacing(8)

        # Priority badge — visible only when queued
        self._next_badge = QLabel("NEXT")
        self._next_badge.setStyleSheet(
            "background:#1565c0; color:white; border-radius:3px; padding:1px 4px; font-size:8pt; font-weight:bold;"
        )
        self._next_badge.setFixedWidth(40)
        self._next_badge.hide()
        layout.addWidget(self._next_badge)

        info = QVBoxLayout()
        info.setSpacing(1)
        self._title = QLabel(f"<b>{entry.name}</b>")
        self._title.setFont(QFont("", 9))
        self._subtitle = QLabel(entry.artist)
        self._subtitle.setFont(QFont("", 8))
        self._subtitle.setStyleSheet("color: #666;")
        info.addWidget(self._title)
        info.addWidget(self._subtitle)
        layout.addLayout(info, stretch=2)

        self._bar = QProgressBar()
        self._bar.setRange(0, 100)
        self._bar.setValue(0)
        self._bar.setMaximumHeight(14)
        self._bar.setMinimumWidth(100)
        layout.addWidget(self._bar, stretch=1)

        self._priority_btn = QPushButton("⬆ Next")
        self._priority_btn.setFixedSize(56, 24)
        self._priority_btn.setToolTip("Jump to front of queue")
        self._priority_btn.clicked.connect(lambda: self.prioritized.emit(self.track_id))
        layout.addWidget(self._priority_btn)

        self._retry_btn = QPushButton("↻ Retry")
        self._retry_btn.setFixedSize(72, 24)
        self._retry_btn.setToolTip("Retry download")
        self._retry_btn.clicked.connect(lambda: self.retry_requested.emit(self.track_id))
        layout.addWidget(self._retry_btn)

        self._manual_box = QWidget()
        manual_layout = QVBoxLayout(self._manual_box)
        manual_layout.setContentsMargins(0, 0, 0, 0)
        manual_layout.setSpacing(2)
        manual_label = QLabel("Manual YouTube URL")
        manual_label.setStyleSheet("font-size: 8pt; color: #555;")
        self._manual_hint = QLabel("Paste the URL of the YouTube video you found for this track.")
        self._manual_hint.setStyleSheet("font-size: 7pt; color: #777;")
        self._manual_hint.setWordWrap(True)
        manual_layout.addWidget(manual_label)
        manual_layout.addWidget(self._manual_hint)

        input_row = QHBoxLayout()
        input_row.setContentsMargins(0, 0, 0, 0)
        input_row.setSpacing(4)
        self._url_edit = QLineEdit()
        self._url_edit.setPlaceholderText("Paste the YouTube URL here")
        self._url_edit.setClearButtonEnabled(True)
        self._url_edit.setVisible(False)
        self._url_edit.setMinimumWidth(260)
        input_row.addWidget(self._url_edit, stretch=1)

        self._use_url_btn = QPushButton("Use URL")
        self._use_url_btn.setFixedSize(72, 24)
        self._use_url_btn.setToolTip("Download from the pasted YouTube link")
        self._use_url_btn.clicked.connect(self._emit_manual_url)
        self._use_url_btn.setVisible(False)
        input_row.addWidget(self._use_url_btn)
        manual_layout.addLayout(input_row)
        self._manual_box.setVisible(False)
        layout.addWidget(self._manual_box, stretch=2)

        self._cancel_btn = QPushButton("✕")
        self._cancel_btn.setFixedSize(24, 24)
        self._cancel_btn.setToolTip("Cancel download")
        self._cancel_btn.clicked.connect(lambda: self.cancelled.emit(self.track_id))
        layout.addWidget(self._cancel_btn)

        self._apply_status(entry.status, entry.progress)

    def update(self, status: str, progress: float):
        self._apply_status(status, progress)

    def mark_next(self, is_next: bool):
        self._next_badge.setVisible(is_next)

    def _emit_manual_url(self):
        url = self._url_edit.text().strip()
        if url:
            self.manual_url_requested.emit(self.track_id, url)

    def _apply_status(self, status: str, progress: float):
        display = status.splitlines()[0]
        self._subtitle.setText(display)
        self.setToolTip(status)
        self._bar.setValue(int(progress))

        queued = status == "Queued"
        done = status == "Downloaded"
        failed = status.startswith("Error") or status == "Cancelled"

        self._priority_btn.setVisible(queued)
        self._retry_btn.setVisible(failed)
        self._manual_box.setVisible(failed)
        self._url_edit.setVisible(failed)
        self._use_url_btn.setVisible(failed)
        if failed:
            self._url_edit.setFocus(Qt.OtherFocusReason)
        self._cancel_btn.setEnabled(not done and not failed)
        self._cancel_btn.setText("✓" if done else "✕")

        if done:
            self._bar.setValue(100)
            self._subtitle.setStyleSheet("color: #2e7d32; font-size: 8pt;")
        elif failed:
            self._subtitle.setStyleSheet("color: #c62828; font-size: 8pt;")
        else:
            self._subtitle.setStyleSheet("color: #666; font-size: 8pt;")


class QueuePanel(QWidget):
    """Scrollable download queue with priority jumping."""

    priority_requested = pyqtSignal(str)  # track_id — connect to DownloadManager.prioritize
    retry_requested = pyqtSignal(str)     # track_id — connect to MainWindow._retry_track
    manual_url_requested = pyqtSignal(str, str)  # track_id, url

    def __init__(self, parent=None):
        super().__init__(parent)
        self._rows: dict[str, QueueRow] = {}
        self._entries: dict[str, QueueEntry] = {}
        self._cancel_fns: dict[str, Callable] = {}
        self._row_order: list[str] = []  # insertion order for badge refresh
        self._build()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(4, 4, 4, 4)
        root.setSpacing(4)

        header = QHBoxLayout()
        title = QLabel("Download Queue")
        title.setFont(QFont("", 10, QFont.Bold))
        header.addWidget(title)
        header.addStretch()

        self._count_label = QLabel("")
        self._count_label.setFont(QFont("", 9))
        self._count_label.setStyleSheet("color: #555;")
        header.addWidget(self._count_label)

        clear_btn = QPushButton("Clear Completed")
        clear_btn.setFixedHeight(24)
        clear_btn.clicked.connect(self.clear_completed)
        header.addWidget(clear_btn)

        cancel_all_btn = QPushButton("Cancel All")
        cancel_all_btn.setFixedHeight(24)
        cancel_all_btn.clicked.connect(self.cancel_all)
        header.addWidget(cancel_all_btn)

        root.addLayout(header)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        self._container = QWidget()
        self._container_layout = QVBoxLayout(self._container)
        self._container_layout.setContentsMargins(0, 0, 0, 0)
        self._container_layout.setSpacing(3)

        self._empty_label = QLabel("No downloads yet")
        self._empty_label.setAlignment(Qt.AlignCenter)
        self._empty_label.setStyleSheet("color: #999;")
        self._container_layout.addWidget(self._empty_label)
        self._container_layout.addStretch()

        scroll.setWidget(self._container)
        root.addWidget(scroll)

    # ── Public API ────────────────────────────────────────────────────────────

    def add(self, entry: QueueEntry):
        if entry.track_id in self._rows:
            self._entries[entry.track_id] = entry
            self._rows[entry.track_id].update(entry.status, entry.progress)
            self._rows[entry.track_id].mark_next(False)
            self._refresh_counts()
            return
        self._entries[entry.track_id] = entry
        self._empty_label.hide()

        row = QueueRow(entry)
        row.cancelled.connect(self._on_cancel)
        row.prioritized.connect(self._on_prioritize)
        row.retry_requested.connect(self._on_retry)
        row.manual_url_requested.connect(self.manual_url_requested.emit)
        self._rows[entry.track_id] = row
        self._row_order.append(entry.track_id)
        # Insert before trailing stretch
        self._container_layout.insertWidget(self._container_layout.count() - 1, row)
        self._refresh_counts()

    def snapshot_entries(self) -> list[dict]:
        return [
            {
                "track_id": entry.track_id,
                "playlist_id": entry.playlist_id,
                "track": entry.track,
                "source_url": entry.source_url,
                "name": entry.name,
                "artist": entry.artist,
                "album": entry.album,
                "status": entry.status,
                "progress": entry.progress,
            }
            for entry in self._entries.values()
        ]

    def update_progress(self, track_id: str, status: str, progress: float):
        row = self._rows.get(track_id)
        if row:
            row.update(status, progress)
        entry = self._entries.get(track_id)
        if entry:
            entry.status = status
            entry.progress = progress
        self._refresh_counts()

    def set_cancel_fn(self, track_id: str, fn: Callable):
        self._cancel_fns[track_id] = fn

    def move_to_top(self, track_id: str):
        """Visually move a row to the top of the list and mark it NEXT."""
        row = self._rows.get(track_id)
        if not row:
            return
        # Reorder in layout: remove then re-insert at position 0 (after empty label)
        self._container_layout.removeWidget(row)
        self._container_layout.insertWidget(0, row)
        # Reorder tracking list
        if track_id in self._row_order:
            self._row_order.remove(track_id)
            self._row_order.insert(0, track_id)
        self._refresh_next_badges()

    def clear_completed(self):
        terminal = {"Downloaded", "Cancelled"}
        to_remove = [
            tid for tid, e in self._entries.items()
            if e.status in terminal or e.status.startswith("Error")
        ]
        for tid in to_remove:
            self._remove_row(tid)
        if not self._rows:
            self._empty_label.show()
        self._refresh_counts()

    def cancel_all(self):
        for tid, fn in list(self._cancel_fns.items()):
            entry = self._entries.get(tid)
            if entry and entry.status not in ("Downloaded", "Cancelled") and not entry.status.startswith("Error"):
                fn()

    # ── Internal ──────────────────────────────────────────────────────────────

    def _on_cancel(self, track_id: str):
        fn = self._cancel_fns.get(track_id)
        if fn:
            fn()

    def _on_prioritize(self, track_id: str):
        self.move_to_top(track_id)
        self.priority_requested.emit(track_id)

    def _on_retry(self, track_id: str):
        self.retry_requested.emit(track_id)

    def _remove_row(self, track_id: str):
        row = self._rows.pop(track_id, None)
        if row:
            self._container_layout.removeWidget(row)
            row.deleteLater()
        self._entries.pop(track_id, None)
        self._cancel_fns.pop(track_id, None)
        if track_id in self._row_order:
            self._row_order.remove(track_id)

    def _refresh_next_badges(self):
        """Show NEXT badge on the first queued row."""
        found_next = False
        for tid in self._row_order:
            row = self._rows.get(tid)
            entry = self._entries.get(tid)
            if row and entry:
                is_next = not found_next and entry.status == "Queued"
                row.mark_next(is_next)
                if is_next:
                    found_next = True

    def _refresh_counts(self):
        active = sum(
            1 for e in self._entries.values()
            if e.status not in ("Downloaded", "Cancelled") and not e.status.startswith("Error")
        )
        total = len(self._entries)
        if total == 0:
            self._count_label.setText("")
        else:
            done = total - active
            self._count_label.setText(f"{done}/{total} done  ·  {active} active")
        self._refresh_next_badges()
