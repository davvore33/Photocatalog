import logging
import sys
from logging.handlers import RotatingFileHandler

from . import config

_LOG_FORMAT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

_configured = False


def setup_logging(level: int = logging.INFO) -> logging.Logger:
    """Configure the root logger to write to both the terminal and a rotating log file.

    Safe to call multiple times (e.g. once per CLI invocation, once in create_app) -
    only configures handlers on the first call.
    """
    global _configured
    root = logging.getLogger()
    if _configured:
        return root

    formatter = logging.Formatter(_LOG_FORMAT, datefmt=_DATE_FORMAT)

    console_handler = logging.StreamHandler(sys.stderr)
    console_handler.setFormatter(formatter)

    config.LOG_DIR.mkdir(parents=True, exist_ok=True)
    file_handler = RotatingFileHandler(
        config.LOG_FILE,
        maxBytes=config.LOG_MAX_BYTES,
        backupCount=config.LOG_BACKUP_COUNT,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)

    root.setLevel(level)
    root.addHandler(console_handler)
    root.addHandler(file_handler)

    _configured = True
    return root
