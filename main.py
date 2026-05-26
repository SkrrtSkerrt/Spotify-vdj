import sys
import logging
import subprocess
from PyQt5.QtWidgets import QApplication, QMessageBox
from PyQt5.QtGui import QIcon

import config
import spotify_client as sc
from downloader import ensure_ffmpeg_available
from logging_utils import LOG_FILE, install_exception_hook, setup_logging
from gui.setup_dialog import SetupDialog
from gui.main_window import MainWindow
from resource_utils import resource_path


FFMPEG_DOWNLOAD_URL = "https://www.gyan.dev/ffmpeg/builds/"


def show_ffmpeg_missing_dialog() -> None:
    logging.getLogger("spotify_vdj").error("FFmpeg not found")
    msg = QMessageBox()
    msg.setIcon(QMessageBox.Critical)
    msg.setWindowTitle("FFmpeg Not Found")
    msg.setText("Spotify VDJ needs FFmpeg to convert downloads into MP3 files.")
    msg.setInformativeText(
        "FFmpeg was not detected on this system. You can install it now, then restart Spotify VDJ."
    )
    msg.setDetailedText(
        "Portable install options:\n\n"
        "1) Download an FFmpeg Windows build (the 'Essentials' zip is fine):\n"
        f"   {FFMPEG_DOWNLOAD_URL}\n\n"
        "2) Extract the zip.\n"
        "3) Either:\n"
        "   - add the extracted \"bin\" folder to PATH, or\n"
        "   - copy ffmpeg.exe and ffprobe.exe next to SpotifyVDJ.exe\n"
        "4) Restart Spotify VDJ.\n\n"
        "Quick install (if winget is available):\n"
        "   winget install Gyan.FFmpeg\n"
    )
    msg.exec_()


def open_debug_log() -> None:
    try:
        if sys.platform == "win32":
            subprocess.Popen(["notepad.exe", LOG_FILE])
        elif sys.platform == "darwin":
            subprocess.Popen(["open", LOG_FILE])
        else:
            subprocess.Popen(["xdg-open", LOG_FILE])
    except Exception:
        pass


def main():
    log_path = setup_logging()
    install_exception_hook(logging.getLogger("spotify_vdj"))
    logging.getLogger("spotify_vdj").info("Starting Spotify VDJ (debug log: %s)", log_path)

    app = QApplication(sys.argv)
    app.setApplicationName("Spotify VDJ")
    app.setStyle("Fusion")
    app.setWindowIcon(QIcon(resource_path("icon.ico")))

    try:
        ensure_ffmpeg_available()
    except Exception:
        show_ffmpeg_missing_dialog()
        sys.exit(1)

    cfg = config.load()

    # First run or missing credentials — show setup
    if not config.is_configured(cfg):
        dlg = SetupDialog(cfg)
        if dlg.exec_() != dlg.Accepted:
            sys.exit(0)
        cfg = dlg.get_config()

    # Authenticate with Spotify
    try:
        sp = sc.create_client(cfg["client_id"], cfg["client_secret"], cfg["redirect_uri"])
        # Trigger auth immediately so browser opens now
        sp.current_user()
    except Exception as exc:
        logging.getLogger("spotify_vdj").exception("Spotify authentication failed")
        QMessageBox.critical(None, "Spotify Auth Failed", str(exc))
        sys.exit(1)

    window = MainWindow(sp, cfg)
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
