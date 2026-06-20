"""
Crash/restart recovery cache for all open documents (multi-document, Phase 2).

A background daemon thread writes each open document's design + assembly to disk
under ``<workspace>/.session/<doc_id>/`` a few seconds after its last change.  On
process startup, :func:`restore` reloads every cached document into its session,
so a backend restart silently brings back all in-progress work — single-document
(``__default__``) and multi-tab alike.

Design goals (unchanged from Phase 1)
-------------------------------------
* **Off the hot path.** Serialization + disk I/O run in the flush thread, never
  in a request handler and never while holding a state lock.  Snapshots are deep
  copies taken under the lock (``state.copy_doc_for_persist``), serialized after.
* **Cheap when idle.** Each session exposes a monotonic ``revision``; the thread
  only writes documents whose revision changed.
* **Debounced.** Writes happen ~``_FLUSH_DEBOUNCE_S`` after the last change in a
  burst across all documents.
* **Never crash startup.** A corrupt/partial cache is logged and skipped.
"""

from __future__ import annotations

import datetime as _dt
import json
import re
import shutil
import threading
import time
import traceback
from pathlib import Path

from backend.api import assembly_state, server_info
from backend.api import state as design_state
from backend.api.doc_context import DEFAULT_DOC_ID
from backend.core.models import Assembly, Design

# Write at most this long after the most recent change in a burst.
_FLUSH_DEBOUNCE_S = 3.0
# How often the flush thread wakes to check for new revisions.
_POLL_INTERVAL_S = 1.0

# Startup pruning bounds.  The session cache is crash-recovery scratch, not an
# archive: without a cap it accrued one ~2 MB sub-dir per document/tab/test ever
# opened (790+ → 180 MB → +6 s on every boot, growing forever, since restore()
# loads and validates each one).  Prune before restore so each boot only pays for
# recent work: drop anything untouched for _MAX_AGE_DAYS, then keep at most
# _MAX_DOCS of whatever survives (most-recently-modified wins).
_MAX_AGE_DAYS = 7
_MAX_DOCS = 50

_DESIGN_FILE = "active_design.nadoc"
_ASSEMBLY_FILE = "active_assembly.nass"
_REGISTRY_FILE = "registry.json"

_session_dir: Path | None = None
_thread: threading.Thread | None = None
_stop = threading.Event()

# Flush bookkeeping (touched only by the flush thread + stop()).
# Per-doc combined (design_rev, assembly_rev) tuples.
_last_flushed: dict[str, tuple[int, int]] = {}
_seen: dict[str, tuple[int, int]] = {}
_stable_since: float | None = None

_SAFE_DOC_RE = re.compile(r"[^A-Za-z0-9_.-]")


def _doc_dir(doc_id: str) -> Path:
    """Per-doc cache directory, with a filesystem-safe name.

    doc_ids are minted as uuid hex or the ``__default__`` sentinel (both safe),
    but the id ultimately comes from a client header, so sanitize defensively
    to keep writes inside the session dir.
    """
    safe = _SAFE_DOC_RE.sub("_", doc_id)[:80] or "_"
    return _session_dir / safe


# ── Public lifecycle ─────────────────────────────────────────────────────────

def start(workspace_dir: Path) -> None:
    """Restore any cached documents, then start the background flush thread.

    Called once from the FastAPI lifespan hook.  Never started during the test
    suite (tests do not enter the app lifespan), so it adds no test overhead.
    """
    global _session_dir, _thread, _last_flushed, _seen, _stable_since
    _session_dir = Path(workspace_dir) / ".session"
    try:
        _session_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        traceback.print_exc()
        return

    _prune()
    restore()

    # Baseline bookkeeping to the post-restore revisions so we don't immediately
    # re-write content we just loaded.
    _seen = _combined_revisions()
    _last_flushed = dict(_seen)
    _stable_since = time.monotonic()

    _stop.clear()
    _thread = threading.Thread(target=_run, name="nadoc-session-cache", daemon=True)
    _thread.start()


def stop() -> None:
    """Stop the flush thread and write one final snapshot."""
    global _thread
    _stop.set()
    if _thread is not None:
        _thread.join(timeout=5.0)
        _thread = None
    try:
        _flush(force=True)
    except Exception:
        traceback.print_exc()


# ── Prune (startup) ──────────────────────────────────────────────────────────

def _doc_mtime(sub: Path) -> float:
    """Freshness of a cached doc — newest mtime among its files (0.0 if empty)."""
    mtimes = [p.stat().st_mtime for p in sub.iterdir() if p.is_file()]
    return max(mtimes) if mtimes else 0.0


def _prune(now: float | None = None) -> int:
    """Delete stale/excess cached docs before restore.  Returns the count removed.

    Two bounds, applied in order to the per-doc sub-dirs:
      1. age — drop any doc untouched for more than ``_MAX_AGE_DAYS``;
      2. count — of whatever survives, keep only the ``_MAX_DOCS`` freshest.

    Best-effort: a sub-dir that won't stat/delete is logged and skipped, never
    fatal to startup.
    """
    if _session_dir is None or not _session_dir.is_dir():
        return 0
    if now is None:
        now = time.time()

    dated: list[tuple[float, Path]] = []
    for sub in _session_dir.iterdir():
        if sub.is_dir():
            try:
                dated.append((_doc_mtime(sub), sub))
            except OSError:
                traceback.print_exc()

    cutoff = now - _MAX_AGE_DAYS * 86400.0
    survivors = [(m, s) for (m, s) in dated if m >= cutoff]
    doomed = [s for (m, s) in dated if m < cutoff]

    # Count cap: keep the freshest _MAX_DOCS survivors, evict the rest.
    survivors.sort(key=lambda t: t[0], reverse=True)
    doomed += [s for (_m, s) in survivors[_MAX_DOCS:]]

    removed = 0
    for sub in doomed:
        try:
            shutil.rmtree(sub)
            removed += 1
        except OSError:
            traceback.print_exc()
    return removed


# ── Restore (startup) ────────────────────────────────────────────────────────

def restore() -> int:
    """Load every cached document into its session.  Returns the count restored.

    Failures per file are logged and swallowed — a bad cache must never block
    startup.  Each ``.session/<doc_id>/`` subdirectory maps to one document.
    """
    if _session_dir is None or not _session_dir.is_dir():
        return 0
    restored = 0
    for sub in _session_dir.iterdir():
        if not sub.is_dir():
            continue
        doc_id = sub.name
        d_path = sub / _DESIGN_FILE
        a_path = sub / _ASSEMBLY_FILE
        if d_path.is_file():
            try:
                design_state.restore_doc_design(
                    doc_id, Design.from_json(d_path.read_text(encoding="utf-8")))
                restored += 1
            except Exception:
                traceback.print_exc()
        if a_path.is_file():
            try:
                assembly_state.restore_doc_assembly(
                    doc_id, Assembly.from_json(a_path.read_text(encoding="utf-8")))
                restored += 1
            except Exception:
                traceback.print_exc()
    return restored


# ── Flush (background) ─────────────────────────────────────────────────────────

def _combined_revisions() -> dict[str, tuple[int, int]]:
    """``{doc_id: (design_rev, assembly_rev)}`` across both registries."""
    d_map = design_state.revision_map()
    a_map = assembly_state.revision_map()
    docs = set(d_map) | set(a_map)
    return {doc: (d_map.get(doc, 0), a_map.get(doc, 0)) for doc in docs}


def _run() -> None:
    while not _stop.wait(_POLL_INTERVAL_S):
        try:
            _flush(force=False)
        except Exception:
            traceback.print_exc()


def _flush(force: bool) -> None:
    """Write documents whose revision changed, once the change has been stable
    for the debounce window (or ``force`` on shutdown)."""
    global _last_flushed, _seen, _stable_since
    if _session_dir is None:
        return

    current = _combined_revisions()

    if current != _seen:
        # Something changed since the last look → restart the debounce timer.
        _seen = current
        _stable_since = time.monotonic()

    if current == _last_flushed:
        return  # nothing pending
    if not force:
        if _stable_since is None or (time.monotonic() - _stable_since) < _FLUSH_DEBOUNCE_S:
            return  # still settling

    # Docs that vanished (closed) → remove their cache dirs.
    for doc_id in set(_last_flushed) - set(current):
        _remove_doc_dir(doc_id)

    # Docs whose combined revision changed → rewrite.
    for doc_id, rev in current.items():
        if _last_flushed.get(doc_id) == rev:
            continue
        _write_doc(doc_id)

    _write_registry(current)
    _last_flushed = current


def _write_doc(doc_id: str) -> None:
    design, _ = design_state.copy_doc_for_persist(doc_id)
    assembly, _ = assembly_state.copy_doc_for_persist(doc_id)
    if design is None and assembly is None:
        _remove_doc_dir(doc_id)
        return
    d = _doc_dir(doc_id)
    d.mkdir(parents=True, exist_ok=True)
    _write_or_unlink(d / _DESIGN_FILE, design.to_json() if design is not None else None)
    _write_or_unlink(d / _ASSEMBLY_FILE, assembly.to_json() if assembly is not None else None)


def _remove_doc_dir(doc_id: str) -> None:
    d = _doc_dir(doc_id)
    for name in (_DESIGN_FILE, _ASSEMBLY_FILE):
        (d / name).unlink(missing_ok=True)
    try:
        if d.is_dir() and not any(d.iterdir()):
            d.rmdir()
    except OSError:
        pass


def _write_registry(current: dict[str, tuple[int, int]]) -> None:
    docs = []
    for doc_id in sorted(current):
        design = design_state.peek_design(doc_id)
        assembly = assembly_state.peek_assembly(doc_id)
        if design is None and assembly is None:
            continue
        docs.append({
            "doc_id": doc_id,
            "is_default": doc_id == DEFAULT_DOC_ID,
            "design": _meta(design),
            "assembly": _meta(assembly),
        })
    payload = {
        "server_instance_id": server_info.SERVER_INSTANCE_ID,
        "saved_at": _dt.datetime.now(_dt.timezone.utc).isoformat(),
        "documents": docs,
    }
    _write_or_unlink(_session_dir / _REGISTRY_FILE, json.dumps(payload, indent=2))


def _meta(doc) -> dict | None:
    if doc is None:
        return None
    meta = getattr(doc, "metadata", None)
    name = getattr(meta, "name", None) if meta is not None else getattr(doc, "name", None)
    return {"id": getattr(doc, "id", None), "name": name}


def _write_or_unlink(path: Path, text: str | None) -> None:
    if text is None:
        path.unlink(missing_ok=True)
        return
    # Write to a temp file then rename, so a crash mid-write can't corrupt the
    # cache (a partial temp file is just ignored on restore).
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)
