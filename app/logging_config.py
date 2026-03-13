"""
Structured logging for the Aegis Archive module.

- Console and optional file handlers
- Request ID in log format (set by middleware)
- Enhanced format: timestamp | level | request_id | message (no logger/file names)
- Messages use key=value style for easy scanning
"""

import logging
import sys
from contextvars import ContextVar
from pathlib import Path
from typing import Optional

# Request-scoped ID for correlating all logs of a single HTTP request
request_id_ctx: ContextVar[Optional[str]] = ContextVar("request_id", default=None)


class RequestIdFilter(logging.Filter):
    """Add request_id to every log record (from context or '-' when not in a request)."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            record.request_id = request_id_ctx.get() or "-"
        except LookupError:
            record.request_id = "-"
        return True


def get_request_id() -> Optional[str]:
    return request_id_ctx.get()


def set_request_id(rid: str) -> None:
    request_id_ctx.set(rid)


def setup_logging(
    level: str = "INFO",
    log_file: Optional[str] = None,
    log_file_level: Optional[str] = None,
    include_location: bool = False,
) -> None:
    """
    Configure root logger and app loggers.
    Call once at application startup (e.g. in main.py lifespan).
    """
    log_level = getattr(logging, level.upper(), logging.INFO)
    file_level = getattr(logging, (log_file_level or level).upper(), log_level)

    # Enhanced format: no logger/file names — timestamp | level | request_id | message
    date_fmt = "%Y-%m-%d %H:%M:%S"
    log_format = "%(asctime)s | %(levelname)-5s | %(request_id)s | %(message)s"
    if include_location:
        log_format = "%(asctime)s | %(levelname)-5s | %(request_id)s | %(module)s:%(funcName)s:%(lineno)d | %(message)s"

    formatter = logging.Formatter(log_format, datefmt=date_fmt)

    root = logging.getLogger()
    root.setLevel(log_level)

    # Remove existing handlers to avoid duplicates on reload
    for h in root.handlers[:]:
        root.removeHandler(h)

    # Console handler
    console = logging.StreamHandler(sys.stdout)
    console.setLevel(log_level)
    console.setFormatter(formatter)
    console.addFilter(RequestIdFilter())
    root.addHandler(console)

    # Optional file handler (default logs/aegis.log when LOG_FILE is set)
    if log_file:
        path = Path(log_file)
        path.parent.mkdir(parents=True, exist_ok=True)
        fh = logging.FileHandler(path, encoding="utf-8")
        fh.setLevel(file_level)
        fh.setFormatter(formatter)
        fh.addFilter(RequestIdFilter())
        root.addHandler(fh)

    # Reduce noise from third-party libs
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.error").setLevel(logging.INFO)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)

    # App loggers: ensure our namespaces get the configured level
    logging.getLogger("app").setLevel(log_level)
    logging.getLogger("app.db").setLevel(log_level)
    logging.getLogger("app.routes").setLevel(log_level)
    logging.getLogger("app.services").setLevel(log_level)
