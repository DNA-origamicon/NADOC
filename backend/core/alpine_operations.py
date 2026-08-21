"""Persistent structured audit log for every Alpine transport operation.

The ordinary application logger is useful for exceptions, but it does not preserve a
complete start/finish timeline across dev-server reloads.  This module writes one JSON
object per line so a later investigation can correlate overlapping SSH commands and
SFTP transfers by ``operation_id`` without ever recording credentials.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
import uuid
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

_LOGGER = logging.getLogger("nadoc.alpine.operations")
_LOGGER.setLevel(logging.INFO)
_LOGGER.propagate = False
_LOCK = threading.Lock()
_PATH: Path | None = None


def configure(workspace_dir: Path) -> Path:
    """Configure the durable Alpine log and return its path (idempotent)."""
    global _PATH
    path = Path(workspace_dir) / "logs" / "alpine_operations.jsonl"
    with _LOCK:
        if _PATH == path and _LOGGER.handlers:
            return path
        path.parent.mkdir(parents=True, exist_ok=True)
        for handler in tuple(_LOGGER.handlers):
            handler.close()
            _LOGGER.removeHandler(handler)
        handler = RotatingFileHandler(
            path, maxBytes=25 * 1024 * 1024, backupCount=10, encoding="utf-8"
        )
        handler.setFormatter(logging.Formatter("%(message)s"))
        _LOGGER.addHandler(handler)
        _PATH = path
    event("logger_ready", path=str(path))
    return path


def log_path() -> Path | None:
    return _PATH


def new_operation_id() -> str:
    return uuid.uuid4().hex[:12]


def event(event_name: str, **fields: Any) -> None:
    """Append one timestamped event. A logging failure must never break Alpine I/O."""
    if not _LOGGER.handlers:
        return
    record = {
        "timestamp": datetime.now(timezone.utc).astimezone().isoformat(timespec="milliseconds"),
        "epoch": round(time.time(), 6),
        "event": event_name,
        "pid": os.getpid(),
        **{key: value for key, value in fields.items() if value is not None},
    }
    try:
        _LOGGER.info(json.dumps(record, ensure_ascii=False, default=str))
    except Exception:  # noqa: BLE001 - diagnostics must not affect production I/O
        pass


def finish(
    operation: str,
    operation_id: str,
    started: float,
    *,
    outcome: str,
    **fields: Any,
) -> None:
    event(
        f"{operation}_finish",
        operation_id=operation_id,
        outcome=outcome,
        duration_ms=round((time.monotonic() - started) * 1000, 3),
        **fields,
    )
