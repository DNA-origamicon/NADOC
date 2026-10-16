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
import logging
import os
import shutil
import threading
import time
import traceback
from pathlib import Path

from backend.api import assembly_state, server_info
from backend.api import state as design_state
from backend.api.doc_context import DEFAULT_DOC_ID
from backend.api.document_identity import UnsafeDocumentIdentity, require_document_identity
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
_WORKSPACE_HEADS_FILE = "workspace_heads.json"
_REGISTRY_FILE = "registry.json"

_session_dir: Path | None = None
_thread: threading.Thread | None = None
_stop = threading.Event()

# Flush bookkeeping (touched only by the flush thread + stop()).
# Per-doc combined (design_rev, assembly_rev) tuples.
_last_flushed: dict[str, tuple[int, int]] = {}
_seen: dict[str, tuple[int, int]] = {}
_stable_since: float | None = None
_strict_persistence = None

_log = logging.getLogger(__name__)


def _doc_dir(doc_id: str) -> Path:
    """Per-document cache path without lossy identity rewriting."""
    return _session_dir / require_document_identity(doc_id)


def _autosave_identity_supported(doc_id: str) -> bool:
    try:
        require_document_identity(doc_id)
    except UnsafeDocumentIdentity as error:
        # Bound and escape the client-controlled diagnostic. Unsupported IDs
        # must not abort autosaving unrelated supported documents.
        hint = repr(doc_id[:80]) if type(doc_id) is str else type(doc_id).__name__
        _log.warning("Session autosave skipped %s: %s; %s", hint, error.code, error)
        return False
    return True


# ── Public lifecycle ─────────────────────────────────────────────────────────


def start(workspace_dir: Path) -> None:
    """Restore any cached documents, then start the background flush thread.

    Called once from the FastAPI lifespan hook.  Never started during the test
    suite (tests do not enter the app lifespan), so it adds no test overhead.

    Set ``NADOC_DISABLE_SESSION_CACHE`` to skip it entirely (no restore, no
    autosave) — used by the e2e backends, which are throwaway processes that
    would otherwise flush a ``.session/<doc>`` dir per test into the shared
    workspace.
    """
    if os.environ.get("NADOC_DISABLE_SESSION_CACHE"):
        return
    global _session_dir, _thread, _last_flushed, _seen, _stable_since, _strict_persistence
    _session_dir = Path(workspace_dir) / ".session"
    try:
        _session_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        traceback.print_exc()
        return

    from backend.api.part_immutable_persistence import StrictPersistence
    from backend.core.part_command_errors import CommandContractError
    _strict_persistence = StrictPersistence(workspace_dir)
    try:
        pending = _strict_persistence.discover()
        if pending.manifests or pending.issues:
            _log.warning("Strict part recovery pending: %s records, %s unsupported entries; files preserved",
                         len(pending.manifests), len(pending.issues))
    except CommandContractError as error:
        _log.warning("Strict part recovery unavailable: %s; files preserved", error.code)

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
    if _session_dir is None:
        return  # never started (test suite, or NADOC_DISABLE_SESSION_CACHE)
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


def _strict_shadowed(doc_id: str) -> bool:
    """Unknown typed storage never means permission to restore/delete old bytes."""
    if _strict_persistence is None:
        return False
    from backend.core.part_command_errors import CommandContractError
    try:
        return _strict_persistence.shadows_legacy(doc_id)
    except (CommandContractError, OSError) as error:
        _log.warning("Strict recovery status unavailable for %r: %s; legacy part preserved",
                     doc_id[:80], getattr(error, "code", type(error).__name__))
        return True


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
            if _strict_shadowed(sub.name):
                continue
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
        if d_path.is_file() and _strict_shadowed(doc_id):
            _log.warning("Legacy part %r is shadowed by pending strict recovery; both records preserved", doc_id[:80])
        elif d_path.is_file():
            try:
                design_state.restore_doc_design(
                    doc_id, Design.from_json(d_path.read_text(encoding="utf-8"))
                )
                heads_path = sub / _WORKSPACE_HEADS_FILE
                if heads_path.is_file():
                    design_state.restore_workspace_heads(
                        doc_id, json.loads(heads_path.read_text(encoding="utf-8"))
                    )
                restored += 1
            except Exception:
                traceback.print_exc()
        if a_path.is_file():
            try:
                assembly_state.restore_doc_assembly(
                    doc_id, Assembly.from_json(a_path.read_text(encoding="utf-8"))
                )
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
        if (
            _stable_since is None
            or (time.monotonic() - _stable_since) < _FLUSH_DEBOUNCE_S
        ):
            return  # still settling

    # Docs that vanished (closed) → remove their cache dirs.
    for doc_id in set(_last_flushed) - set(current):
        if _autosave_identity_supported(doc_id):
            _remove_doc_dir(doc_id)

    # Docs whose combined revision changed → rewrite.
    supported = {}
    completed = {doc: rev for doc, rev in _last_flushed.items() if doc in current}
    for doc_id, rev in current.items():
        if not _autosave_identity_supported(doc_id):
            completed[doc_id] = rev  # Preserve the existing one-warning-per-revision policy.
            continue
        supported[doc_id] = rev
        if _last_flushed.get(doc_id) == rev:
            continue
        written = _write_doc(doc_id)
        if written is not False:
            completed[doc_id] = rev if written is None else written

    _write_registry(supported)
    # A transient strict file refusal stays pending. Never mark sampled/newer
    # revisions as durable when the captured source or write did not succeed.
    _last_flushed = completed


def _write_doc(doc_id: str) -> tuple[int, int] | bool:
    d = _doc_dir(doc_id)
    owner = _strict_persistence
    from backend.core.part_command_errors import CommandContractError
    if owner is not None:
        try:
            revision = owner.write_if_immutable(doc_id)
        except CommandContractError as error:
            _log.warning("Strict part autosave pending for %r: %s; durable records preserved", doc_id[:80], error.code)
            _write_assembly_cache(doc_id, d)
            return False
        if revision is not None:
            return revision, _write_assembly_cache(doc_id, d)
    try:
        if owner is None:
            return _write_legacy_doc(doc_id, d)
        # Keep the typed absence decision through the snapshot and file write.
        # First strict creation cannot overtake an admitted compatibility save.
        with owner.legacy_write(doc_id):
            return _write_legacy_doc(doc_id, d)
    except CommandContractError as error:
        explanation = ("strict recovery must finish before legacy part writes"
                       if error.code == "strict_cache_pending" else str(error))
        _log.warning("Part autosave pending for %r: %s; %s; legacy bytes preserved",
                     doc_id[:80], error.code, explanation)
        _write_assembly_cache(doc_id, d)
        return False


def _write_legacy_doc(doc_id: str, d: Path) -> tuple[int, int]:
    """Caller holds the typed owner's legacy lease when one is configured."""
    design, design_revision = design_state.copy_doc_for_persist(doc_id)
    assembly, assembly_revision = assembly_state.copy_doc_for_persist(doc_id)
    if design is None and assembly is None:
        _remove_known_files(d, (_DESIGN_FILE, _ASSEMBLY_FILE, _WORKSPACE_HEADS_FILE))
        return design_revision, assembly_revision
    d.mkdir(parents=True, exist_ok=True)
    _write_or_unlink(d / _DESIGN_FILE, design.to_json() if design is not None else None)
    _write_or_unlink(
        d / _WORKSPACE_HEADS_FILE,
        json.dumps(design_state.workspace_heads_for_doc(doc_id)) if design is not None else None,
    )
    _write_or_unlink(
        d / _ASSEMBLY_FILE, assembly.to_json() if assembly is not None else None
    )
    return design_revision, assembly_revision


def _write_assembly_cache(doc_id: str, directory: Path) -> int:
    """Preserve assembly autosave independently of a refused part write."""
    assembly, revision = assembly_state.copy_doc_for_persist(doc_id)
    if assembly is not None:
        directory.mkdir(parents=True, exist_ok=True)
    _write_or_unlink(directory / _ASSEMBLY_FILE, assembly.to_json() if assembly is not None else None)
    return revision


def _remove_doc_dir(doc_id: str) -> None:
    d = _doc_dir(doc_id)
    owner = _strict_persistence
    if owner is None:
        _remove_known_files(d, (_DESIGN_FILE, _ASSEMBLY_FILE, _WORKSPACE_HEADS_FILE))
        return
    from backend.core.part_command_errors import CommandContractError
    try:
        with owner.legacy_write(doc_id):
            _remove_known_files(d, (_DESIGN_FILE, _ASSEMBLY_FILE, _WORKSPACE_HEADS_FILE))
    except CommandContractError as error:
        _log.warning("Part close cleanup refused for %r: %s; legacy bytes preserved", doc_id[:80], error.code)
        _remove_known_files(d, (_ASSEMBLY_FILE,))


def _remove_known_files(d: Path, names: tuple[str, ...]) -> None:
    """Unlink only the caller's already admitted legacy names; no nested lease."""
    for name in names:
        (d / name).unlink(missing_ok=True)
    try:
        if d.is_dir() and not any(d.iterdir()):
            d.rmdir()
    except OSError:
        pass


def _write_registry(current: dict[str, tuple[int, int]]) -> None:
    docs = []
    for doc_id in sorted(current):
        design = design_state.design_metadata_for_doc(doc_id)
        assembly = assembly_state.peek_assembly(doc_id)
        if design is None and assembly is None:
            continue
        docs.append(
            {
                "doc_id": doc_id,
                "is_default": doc_id == DEFAULT_DOC_ID,
                "design": design,
                "assembly": _meta(assembly),
            }
        )
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
    name = (
        getattr(meta, "name", None) if meta is not None else getattr(doc, "name", None)
    )
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
