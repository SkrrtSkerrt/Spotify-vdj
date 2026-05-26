from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QFileDialog, QMessageBox, QGroupBox, QApplication, QSpinBox
)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont, QIcon
import webbrowser
import config
from resource_utils import resource_path

DEFAULT_REDIRECT_URI = "http://127.0.0.1:8888/callback"


class SetupDialog(QDialog):
    def __init__(self, cfg: dict, parent=None):
        super().__init__(parent)
        self.cfg = dict(cfg)
        self.setWindowTitle("Spotify VDJ — Setup")
        self.setWindowIcon(QIcon(resource_path("icon.ico")))
        self.setMinimumWidth(540)
        self._build()

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        header = QLabel("Connect to Spotify")
        header.setFont(QFont("", 14, QFont.Bold))
        layout.addWidget(header)

        instructions = QLabel(
            "You need a free Spotify Developer app to use this tool.\n"
            "Click the button below to open the Spotify Developer Dashboard,\n"
            "create an app, then paste your credentials here."
        )
        instructions.setWordWrap(True)
        layout.addWidget(instructions)

        open_btn = QPushButton("Open Spotify Developer Dashboard")
        open_btn.clicked.connect(lambda: webbrowser.open("https://developer.spotify.com/dashboard"))
        layout.addWidget(open_btn)

        # Redirect URI box — prominent, copyable
        uri_group = QGroupBox("Step 1 — Add this Redirect URI to your Spotify app settings")
        uri_layout = QHBoxLayout(uri_group)

        self.redirect_uri_input = QLineEdit(self.cfg.get("redirect_uri", DEFAULT_REDIRECT_URI))
        self.redirect_uri_input.setReadOnly(False)
        self.redirect_uri_input.setStyleSheet("font-family: monospace; font-size: 10pt;")
        uri_layout.addWidget(self.redirect_uri_input)

        copy_btn = QPushButton("Copy")
        copy_btn.setFixedWidth(56)
        copy_btn.clicked.connect(self._copy_redirect_uri)
        uri_layout.addWidget(copy_btn)

        layout.addWidget(uri_group)

        uri_note = QLabel(
            "In your Spotify app → Edit Settings → Redirect URIs, paste the URI above exactly as shown.\n"
            "The URI in this box and in Spotify's dashboard must match character-for-character."
        )
        uri_note.setWordWrap(True)
        uri_note.setStyleSheet("color: #555; font-size: 8pt;")
        layout.addWidget(uri_note)

        # Credentials
        cred_group = QGroupBox("Step 2 — Paste your app credentials")
        cred_layout = QVBoxLayout(cred_group)

        cred_layout.addWidget(QLabel("Client ID:"))
        self.client_id_input = QLineEdit(self.cfg.get("client_id", ""))
        self.client_id_input.setPlaceholderText("e.g. 4b3a2c1d...")
        cred_layout.addWidget(self.client_id_input)

        cred_layout.addWidget(QLabel("Client Secret:"))
        self.client_secret_input = QLineEdit(self.cfg.get("client_secret", ""))
        self.client_secret_input.setPlaceholderText("e.g. 9f8e7d6c...")
        self.client_secret_input.setEchoMode(QLineEdit.Password)
        cred_layout.addWidget(self.client_secret_input)

        layout.addWidget(cred_group)

        # Output folder
        folder_group = QGroupBox("Step 3 — Choose your VDJ output folder")
        folder_layout = QHBoxLayout(folder_group)
        self.folder_input = QLineEdit(self.cfg.get("output_folder", ""))
        browse_btn = QPushButton("Browse...")
        browse_btn.clicked.connect(self._browse_folder)
        folder_layout.addWidget(self.folder_input)
        folder_layout.addWidget(browse_btn)
        layout.addWidget(folder_group)

        folder_note = QLabel("Add this folder to VDJ's Library settings — downloaded tracks appear there automatically.")
        folder_note.setWordWrap(True)
        folder_note.setStyleSheet("color: #555; font-size: 8pt;")
        layout.addWidget(folder_note)

        # Queue size
        queue_group = QGroupBox("Step 4 — Set download queue size")
        queue_layout = QHBoxLayout(queue_group)
        queue_layout.addWidget(QLabel("Max concurrent downloads:"))
        self.max_concurrent_input = QSpinBox()
        self.max_concurrent_input.setRange(1, 8)
        self.max_concurrent_input.setValue(int(self.cfg.get("max_concurrent_downloads", 2)))
        queue_layout.addWidget(self.max_concurrent_input)
        queue_layout.addStretch()
        layout.addWidget(queue_group)

        queue_note = QLabel("Higher values start more downloads at once. Lower values are steadier on slower machines.")
        queue_note.setWordWrap(True)
        queue_note.setStyleSheet("color: #555; font-size: 8pt;")
        layout.addWidget(queue_note)

        # Buttons
        btn_layout = QHBoxLayout()
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        save_btn = QPushButton("Save & Connect")
        save_btn.setDefault(True)
        save_btn.clicked.connect(self._save)
        btn_layout.addStretch()
        btn_layout.addWidget(cancel_btn)
        btn_layout.addWidget(save_btn)
        layout.addLayout(btn_layout)

    def _copy_redirect_uri(self):
        QApplication.clipboard().setText(self.redirect_uri_input.text().strip())
        # Brief visual feedback
        sender = self.sender()
        sender.setText("Copied!")
        from PyQt5.QtCore import QTimer
        QTimer.singleShot(1500, lambda: sender.setText("Copy"))

    def _browse_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Select VDJ Output Folder")
        if folder:
            self.folder_input.setText(folder)

    def _save(self):
        client_id = self.client_id_input.text().strip()
        client_secret = self.client_secret_input.text().strip()
        folder = self.folder_input.text().strip()
        redirect_uri = self.redirect_uri_input.text().strip()

        if not client_id or not client_secret:
            QMessageBox.warning(self, "Missing Credentials", "Please enter both Client ID and Client Secret.")
            return
        if not folder:
            QMessageBox.warning(self, "No Folder", "Please select an output folder.")
            return
        if not redirect_uri:
            redirect_uri = DEFAULT_REDIRECT_URI

        self.cfg["client_id"] = client_id
        self.cfg["client_secret"] = client_secret
        self.cfg["output_folder"] = folder
        self.cfg["redirect_uri"] = redirect_uri
        self.cfg["max_concurrent_downloads"] = int(self.max_concurrent_input.value())
        config.save(self.cfg)
        self.accept()

    def get_config(self) -> dict:
        return self.cfg
