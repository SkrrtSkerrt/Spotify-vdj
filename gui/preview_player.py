import webbrowser
from PyQt5.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QLabel, QPushButton,
    QSlider, QSizePolicy
)
from PyQt5.QtMultimedia import QMediaPlayer, QMediaContent
from PyQt5.QtCore import Qt, QUrl, QTimer
from PyQt5.QtGui import QFont

import downloader


class PreviewPlayer(QWidget):
    """Compact audio preview bar shown at the bottom of the window."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._current_track: dict | None = None
        self._player = QMediaPlayer()
        self._player.stateChanged.connect(self._on_state_changed)
        self._player.positionChanged.connect(self._on_position_changed)
        self._player.durationChanged.connect(self._on_duration_changed)
        self._player.error.connect(self._on_error)

        self._timer = QTimer()
        self._timer.setInterval(500)
        self._timer.timeout.connect(self._update_slider)

        self._build()

    def _build(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(8)

        self._label = QLabel("No preview")
        self._label.setFont(QFont("", 9))
        self._label.setMinimumWidth(220)
        self._label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        layout.addWidget(self._label)

        self._play_btn = QPushButton("▶ Play")
        self._play_btn.setFixedWidth(72)
        self._play_btn.setEnabled(False)
        self._play_btn.clicked.connect(self._toggle_play)
        layout.addWidget(self._play_btn)

        self._stop_btn = QPushButton("■ Stop")
        self._stop_btn.setFixedWidth(64)
        self._stop_btn.setEnabled(False)
        self._stop_btn.clicked.connect(self._stop)
        layout.addWidget(self._stop_btn)

        self._slider = QSlider(Qt.Horizontal)
        self._slider.setRange(0, 1000)
        self._slider.setFixedWidth(160)
        self._slider.sliderMoved.connect(self._seek)
        layout.addWidget(self._slider)

        self._time_label = QLabel("0:00 / 0:30")
        self._time_label.setFont(QFont("", 9))
        self._time_label.setFixedWidth(80)
        layout.addWidget(self._time_label)

        self._yt_btn = QPushButton("Find on YouTube")
        self._yt_btn.setFixedWidth(120)
        self._yt_btn.setEnabled(False)
        self._yt_btn.clicked.connect(self._open_youtube)
        layout.addWidget(self._yt_btn)

        self._no_preview_label = QLabel("")
        self._no_preview_label.setFont(QFont("", 8))
        self._no_preview_label.setStyleSheet("color: #999;")
        layout.addWidget(self._no_preview_label)

    def load_track(self, track: dict):
        self._stop()
        self._current_track = track
        self._no_preview_label.setText("")
        self._yt_btn.setEnabled(True)

        preview_url = track.get("preview_url")
        if preview_url:
            self._label.setText(f"Preview: {track['artist']} — {track['name']}  (30s clip)")
            content = QMediaContent(QUrl(preview_url))
            self._player.setMedia(content)
            self._play_btn.setEnabled(True)
            self._stop_btn.setEnabled(True)
            self._play_btn.setText("▶ Play")
        else:
            self._label.setText(f"{track['artist']} — {track['name']}")
            self._play_btn.setEnabled(False)
            self._stop_btn.setEnabled(False)
            self._no_preview_label.setText("No 30s clip available — use 'Find on YouTube' to verify")

    def _toggle_play(self):
        if self._player.state() == QMediaPlayer.PlayingState:
            self._player.pause()
            self._play_btn.setText("▶ Play")
            self._timer.stop()
        else:
            self._player.play()
            self._play_btn.setText("⏸ Pause")
            self._timer.start()

    def _stop(self):
        self._player.stop()
        self._play_btn.setText("▶ Play")
        self._slider.setValue(0)
        self._time_label.setText("0:00 / 0:30")
        self._timer.stop()

    def _seek(self, value: int):
        duration = self._player.duration()
        if duration > 0:
            self._player.setPosition(int(value / 1000 * duration))

    def _update_slider(self):
        pos = self._player.position()
        duration = self._player.duration()
        if duration > 0:
            self._slider.setValue(int(pos / duration * 1000))
        self._time_label.setText(f"{_fmt_ms(pos)} / {_fmt_ms(duration)}")

    def _on_state_changed(self, state):
        if state == QMediaPlayer.StoppedState:
            self._play_btn.setText("▶ Play")
            self._timer.stop()

    def _on_position_changed(self, pos):
        duration = self._player.duration()
        if duration > 0:
            self._slider.setValue(int(pos / duration * 1000))
        self._time_label.setText(f"{_fmt_ms(pos)} / {_fmt_ms(duration)}")

    def _on_duration_changed(self, duration):
        self._time_label.setText(f"0:00 / {_fmt_ms(duration)}")

    def _on_error(self, error):
        if error != QMediaPlayer.NoError:
            self._label.setText(f"Playback error — use 'Find on YouTube' instead")
            self._play_btn.setEnabled(False)

    def _open_youtube(self):
        if self._current_track:
            webbrowser.open(downloader.youtube_search_url(self._current_track))


def _fmt_ms(ms: int) -> str:
    s = ms // 1000
    return f"{s // 60}:{s % 60:02d}"
