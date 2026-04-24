"""
Workspace file-change event broadcaster.

A watchdog observer monitors _WORKSPACE_DIR for .nadoc/.nass file changes.
When a file is created, modified, or deleted the event is pushed to all
connected SSE clients via asyncio Queues.

Usage (in main.py lifespan):
    from backend.api import library_events
    library_events.start(_WORKSPACE_DIR, loop)
    yield
    library_events.stop()
"""

from __future__ import annotations

import asyncio
import json
import threading
from pathlib import Path

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

_subscribers: list[asyncio.Queue] = []
_lock = threading.Lock()
_observer: Observer | None = None
_workspace_dir: Path | None = None


def subscribe(q: asyncio.Queue) -> None:
    with _lock:
        _subscribers.append(q)


def unsubscribe(q: asyncio.Queue) -> None:
    with _lock:
        try:
            _subscribers.remove(q)
        except ValueError:
            pass


def _push(event_dict: dict) -> None:
    msg = json.dumps(event_dict)
    with _lock:
        targets = list(_subscribers)
    for q in targets:
        try:
            q.put_nowait(msg)
        except Exception:
            pass


class _WorkspaceHandler(FileSystemEventHandler):
    def __init__(self, workspace: Path) -> None:
        super().__init__()
        self._workspace = workspace

    def _handle(self, src_path: str, event_type: str) -> None:
        p = Path(src_path)
        if p.is_dir():
            return
        if p.suffix not in (".nadoc", ".nass"):
            return
        try:
            rel = str(p.relative_to(self._workspace))
        except ValueError:
            return
        _push({
            "type":      event_type,
            "path":      rel,
            "file_type": "assembly" if p.suffix == ".nass" else "part",
        })

    def on_created(self, event) -> None:
        self._handle(event.src_path, "file-changed")

    def on_modified(self, event) -> None:
        self._handle(event.src_path, "file-changed")

    def on_deleted(self, event) -> None:
        self._handle(event.src_path, "file-deleted")

    def on_moved(self, event) -> None:
        # Treat move-in as a create event for the destination
        self._handle(event.dest_path, "file-changed")


def start(workspace: Path) -> None:
    global _observer, _workspace_dir
    _workspace_dir = workspace
    workspace.mkdir(parents=True, exist_ok=True)
    obs = Observer()
    obs.schedule(_WorkspaceHandler(workspace), str(workspace), recursive=True)
    obs.start()
    _observer = obs


def stop() -> None:
    global _observer
    if _observer is not None:
        _observer.stop()
        _observer.join()
        _observer = None
