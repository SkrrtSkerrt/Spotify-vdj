import sys
from PyQt5.QtWidgets import QApplication, QMessageBox
from PyQt5.QtGui import QIcon

import config
import spotify_client as sc
from downloader import ensure_ffmpeg_available
from gui.setup_dialog import SetupDialog
from gui.main_window import MainWindow
from resource_utils import resource_path


FFMPEG_DOWNLOAD_URL = "https://www.gyan.dev/ffmpeg/builds/"


def show_ffmpeg_missing_dialog() -> None:
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


def main():
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
    except Exception as e:
        QMessageBox.critical(None, "Spotify Auth Failed", str(e))
        sys.exit(1)

    window = MainWindow(sp, cfg)
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
