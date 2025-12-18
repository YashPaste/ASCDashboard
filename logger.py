import logging
import logging.config
from pathlib import Path
import os

LOG_DIR = Path("logs")
LOG_DIR.mkdir(exist_ok=True)
LOG_FILE = LOG_DIR / "app.log"


def setup_logging(level: str | None = None):
    if getattr(setup_logging, "configured", False):
        return

    lvl = level or os.environ.get("LOG_LEVEL", "INFO")

    config = {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "standard": {
                "format": "%(asctime)s %(levelname)s %(name)s: %(message)s"
            }
        },
        "handlers": {
            "console": {
                "class": "logging.StreamHandler",
                "level": lvl,
                "formatter": "standard",
                "stream": "ext://sys.stderr",
            },
            "file": {
                "class": "logging.handlers.RotatingFileHandler",
                "level": "DEBUG",
                "formatter": "standard",
                "filename": str(LOG_FILE),
                "maxBytes": 5 * 1024 * 1024,
                "backupCount": 3,
                "encoding": "utf8",
            },
        },
        "root": {"level": lvl, "handlers": ["console", "file"]},
    }

    logging.config.dictConfig(config)
    setup_logging.configured = True


def get_logger(name: str | None = None):
    setup_logging()
    return logging.getLogger(name)
