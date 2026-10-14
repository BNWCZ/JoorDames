"""Structured logging for JoorDames.

Every run appends to a single rotating file (``logs/joordames.log``) and mirrors
the same lines to stdout, so the host ``cron.log`` keeps docker-level output
while the structured log stays greppable on the server:

    2026-09-10 08:00:11 INFO  [book] target 2026-10-21

``LOG_LEVEL=DEBUG`` in .env turns on selector-level detail for diagnosing a
broken SPA selector without a separate debug run.
"""

import logging
import os
import sys
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path

import pytz

# The Playwright image ships no zoneinfo database, so the TZ=Europe/Paris set in
# docker-compose.yml is a no-op and naive datetimes come out as UTC. Timestamps
# are therefore built from pytz explicitly, to match the operator's wall clock.
PARIS_TZ = pytz.timezone("Europe/Paris")


def _paris_time(secs=None):
    return datetime.fromtimestamp(secs, PARIS_TZ).timetuple()

LOG_DIR = Path(os.getenv("LOG_DIR", "logs"))
LOG_FILE = LOG_DIR / "joordames.log"
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
MAX_BYTES = 5 * 1024 * 1024
BACKUP_COUNT = 5

DEBUG_DIR = Path(os.getenv("DEBUG_DIR", "debug_out"))

_ROOT = "joordames"


class _WorldWritableRotatingFileHandler(RotatingFileHandler):
    """RotatingFileHandler that keeps the log file writable by the host user.

    The container runs as root, so a default-mode log file (root:root 0644)
    could not be truncated from the host. ``_open`` also runs on every
    rotation, so backups stay writable too.
    """

    def _open(self):
        stream = super()._open()
        try:
            os.chmod(self.baseFilename, 0o666)
        except OSError:
            pass
        return stream

_mode = "-"
_configured = False


class _ModeFilter(logging.Filter):
    """Stamp every record with the run mode (book / checkin / sync / …)."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.mode = _mode
        return True


def setup(mode: str = "-") -> None:
    """Configure handlers once per process; safe to call again to set the mode."""
    global _mode, _configured
    _mode = mode
    if _configured:
        return

    level = getattr(logging, LOG_LEVEL, logging.INFO)
    if level <= logging.DEBUG:
        fmt = "%(asctime)s %(levelname)-5s [%(mode)s] %(name)s: %(message)s"
    else:
        fmt = "%(asctime)s %(levelname)-5s [%(mode)s] %(message)s"
    formatter = logging.Formatter(fmt, datefmt="%Y-%m-%d %H:%M:%S")
    formatter.converter = _paris_time

    root = logging.getLogger(_ROOT)
    root.setLevel(level)
    root.propagate = False

    # The filter goes on the handlers, not the logger: a logger's filters only
    # run for records logged directly to it, not for ones propagated up from
    # child loggers (joordames.book, joordames.auth, …).
    mode_filter = _ModeFilter()

    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(formatter)
    console.addFilter(mode_filter)
    root.addHandler(console)

    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        file_handler = _WorldWritableRotatingFileHandler(
            LOG_FILE, maxBytes=MAX_BYTES, backupCount=BACKUP_COUNT, encoding="utf-8",
        )
        file_handler.setFormatter(formatter)
        file_handler.addFilter(mode_filter)
        root.addHandler(file_handler)
    except Exception as exc:  # read-only mount, permissions… — never kill the run
        print(f"[logger] file logging disabled ({LOG_FILE}): {exc}", file=sys.stderr)

    _configured = True


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(f"{_ROOT}.{name}")


def log_run_start(mode: str) -> None:
    get_logger("run").info("─── run start (mode=%s, pid=%s) ───", mode, os.getpid())


def log_run_end(mode: str, ok: bool) -> None:
    get_logger("run").info("─── run end (mode=%s, %s) ───", mode, "ok" if ok else "FAILED")


def dump_page_state(page, label: str) -> str:
    """Save a screenshot + HTML dump of the current page to DEBUG_DIR.

    Returns the file prefix (without extension) so the caller can log it. Never
    raises: a failed dump must not mask the error that triggered it.
    """
    log = get_logger("debug")
    prefix = f"{datetime.now(PARIS_TZ).strftime('%Y%m%d_%H%M%S')}_{label}"
    try:
        DEBUG_DIR.mkdir(parents=True, exist_ok=True)
    except Exception as exc:
        log.warning("cannot create %s: %s", DEBUG_DIR, exc)
        return prefix

    try:
        page.screenshot(path=str(DEBUG_DIR / f"{prefix}.png"), full_page=True, timeout=10_000)
    except Exception as exc:
        log.warning("screenshot failed for %s: %s", prefix, exc)
    try:
        with open(DEBUG_DIR / f"{prefix}.html", "w") as f:
            f.write(page.content())
    except Exception as exc:
        log.warning("html dump failed for %s: %s", prefix, exc)

    try:
        url = page.url
    except Exception:
        url = "?"
    log.info("page state saved: %s/%s.{png,html}  url=%s", DEBUG_DIR, prefix, url)
    return prefix
