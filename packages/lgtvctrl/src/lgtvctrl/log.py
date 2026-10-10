import logging
import time
from logging.handlers import RotatingFileHandler

from lgtvctrl.config import CONFIG_DIR

LOG_FILE = CONFIG_DIR / "lgtvctrl.log"
APP_LOGGER = "lgtvctrl"


def _for_the_terminal(record: logging.LogRecord) -> bool:
    """A command's own results from INFO up; other libraries only from WARNING."""
    own = record.name == APP_LOGGER or record.name.startswith(f"{APP_LOGGER}.")
    return record.levelno >= (logging.INFO if own else logging.WARNING)


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
    stderr_handler.addFilter(_for_the_terminal)
    stderr_handler.setFormatter(logging.Formatter("%(message)s"))

    logging.basicConfig(
        level=logging.DEBUG,
        handlers=[stderr_handler, file_handler],
        force=True,
    )

    return str(LOG_FILE)
