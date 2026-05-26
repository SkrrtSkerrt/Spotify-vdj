import faulthandler
import logging
import os
import sys
from logging.handlers import RotatingFileHandler

LOG_FILE = os.path.join(os.path.expanduser("~"), ".spotify_vdj_debug.log")
_FAULTHANDLER_FILE = None


def setup_logging() -> str:
    global _FAULTHANDLER_FILE
    os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)

    root = logging.getLogger()
    root.setLevel(logging.DEBUG)

    for handler in list(root.handlers):
        root.removeHandler(handler)

    formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    file_handler = RotatingFileHandler(LOG_FILE, maxBytes=2_000_000, backupCount=3, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)

    console_handler = logging.StreamHandler(sys.stderr)
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)
    root.addHandler(console_handler)

    _FAULTHANDLER_FILE = open(LOG_FILE, "a", encoding="utf-8")
    faulthandler.enable(_FAULTHANDLER_FILE)
    logging.captureWarnings(True)
    return LOG_FILE


def install_exception_hook(logger: logging.Logger | None = None) -> None:
    log = logger or logging.getLogger("spotify_vdj")
    previous_hook = sys.excepthook

    def _hook(exc_type, exc_value, exc_traceback):
        log.critical("Uncaught exception", exc_info=(exc_type, exc_value, exc_traceback))
        try:
            if previous_hook and previous_hook is not _hook:
                previous_hook(exc_type, exc_value, exc_traceback)
        except Exception:
            pass

    sys.excepthook = _hook
