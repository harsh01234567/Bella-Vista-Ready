"""
Central logging setup for the Bella Vista backend.

Logs go to both the console and a rotating file under backend/logs/app.log,
so a deployed instance retains recent history without growing unbounded.

Configurable via:
  BELLA_VISTA_LOG_LEVEL - e.g. DEBUG, INFO (default), WARNING.
  BELLA_VISTA_LOG_FILE  - path to the log file (default backend/logs/app.log).
"""

from __future__ import annotations

import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path

LOG_LEVEL = os.getenv("BELLA_VISTA_LOG_LEVEL", "INFO").strip().upper()
LOG_FILE = Path(os.getenv("BELLA_VISTA_LOG_FILE", "").strip() or Path(__file__).with_name("logs") / "app.log")
LOG_FILE.parent.mkdir(parents=True, exist_ok=True)

_FORMAT = "%(asctime)s %(levelname)s [%(name)s] %(message)s"
_formatter = logging.Formatter(_FORMAT)

logger = logging.getLogger("bella_vista")
logger.setLevel(LOG_LEVEL)

if not logger.handlers:  # avoid duplicate handlers on --reload re-imports
    file_handler = RotatingFileHandler(LOG_FILE, maxBytes=5 * 1024 * 1024, backupCount=5, encoding="utf-8")
    file_handler.setFormatter(_formatter)
    logger.addHandler(file_handler)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(_formatter)
    logger.addHandler(console_handler)

    logger.propagate = False
