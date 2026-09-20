import logging
import time
from logging.handlers import RotatingFileHandler

from lgtvctrl.config import CONFIG_DIR

LOG_FILE = CONFIG_DIR / "lgtvctrl.log"


def setup_logging() -> str:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)

    formatter = logging.Formatter(
        "[%(asctime)s.%(msecs)03dZ] [%(levelname)s] %(name)s: %(message)s",
        "%Y-%m-%dT%H:%M:%S",
    )
    formatter.converter = time.gmtime

    file_handler = RotatingFileHandler(
        LOG_FILE,
        maxBytes=2_000_000,
        backupCount=3,
        encoding="utf-8",
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)

    stderr_handler = logging.StreamHandler()
    stderr_handler.setLevel(logging.DEBUG)
    stderr_handler.setFormatter(formatter)

    logging.basicConfig(
        level=logging.DEBUG,
        handlers=[stderr_handler, file_handler],
        force=True,
    )

    return str(LOG_FILE)
