"""Startup pruning of the crash-recovery session cache.

The cache is scratch, not an archive: ``_prune`` bounds it by age then count so a
restart never has to load+validate hundreds of stale docs (the cause of the
multi-second boot regression).
"""

import os

from backend.api import session_cache


def _make_doc(session_dir, name: str, mtime: float) -> None:
    """Create ``<session_dir>/<name>/active_design.nadoc`` stamped at ``mtime``."""
    sub = session_dir / name
    sub.mkdir(parents=True)
    f = sub / session_cache._DESIGN_FILE
    f.write_text("{}", encoding="utf-8")
    os.utime(f, (mtime, mtime))


def _prune_in(tmp_path, monkeypatch, **kw):
    monkeypatch.setattr(session_cache, "_session_dir", tmp_path)
    for k, v in kw.items():
        monkeypatch.setattr(session_cache, k, v)
    return tmp_path


def test_drops_docs_older_than_max_age(tmp_path, monkeypatch):
    _prune_in(tmp_path, monkeypatch, _MAX_AGE_DAYS=7, _MAX_DOCS=1000)
    now = 1_000_000.0
    _make_doc(tmp_path, "fresh", now - 1 * 86400)      # 1 day old — keep
    _make_doc(tmp_path, "stale", now - 30 * 86400)     # 30 days old — drop

    removed = session_cache._prune(now=now)

    assert removed == 1
    assert (tmp_path / "fresh").is_dir()
    assert not (tmp_path / "stale").exists()


def test_count_cap_keeps_freshest(tmp_path, monkeypatch):
    _prune_in(tmp_path, monkeypatch, _MAX_AGE_DAYS=3650, _MAX_DOCS=2)
    now = 1_000_000.0
    # All within the age window; only the 2 freshest survive the count cap.
    _make_doc(tmp_path, "newest", now - 1 * 3600)
    _make_doc(tmp_path, "middle", now - 2 * 3600)
    _make_doc(tmp_path, "oldest", now - 3 * 3600)

    removed = session_cache._prune(now=now)

    assert removed == 1
    assert (tmp_path / "newest").is_dir()
    assert (tmp_path / "middle").is_dir()
    assert not (tmp_path / "oldest").exists()


def test_age_and_count_compose(tmp_path, monkeypatch):
    _prune_in(tmp_path, monkeypatch, _MAX_AGE_DAYS=7, _MAX_DOCS=1)
    now = 1_000_000.0
    _make_doc(tmp_path, "a", now - 1 * 3600)    # fresh, freshest
    _make_doc(tmp_path, "b", now - 2 * 3600)    # fresh, but over count cap
    _make_doc(tmp_path, "c", now - 99 * 86400)  # stale → age-dropped first

    removed = session_cache._prune(now=now)

    assert removed == 2
    assert (tmp_path / "a").is_dir()
    assert not (tmp_path / "b").exists()
    assert not (tmp_path / "c").exists()


def test_noop_when_under_bounds(tmp_path, monkeypatch):
    _prune_in(tmp_path, monkeypatch, _MAX_AGE_DAYS=7, _MAX_DOCS=50)
    now = 1_000_000.0
    _make_doc(tmp_path, "only", now - 60)

    assert session_cache._prune(now=now) == 0
    assert (tmp_path / "only").is_dir()


def test_missing_dir_is_safe(tmp_path, monkeypatch):
    monkeypatch.setattr(session_cache, "_session_dir", tmp_path / "nope")
    assert session_cache._prune(now=1.0) == 0


def test_disable_env_skips_start_and_stop(tmp_path, monkeypatch):
    """NADOC_DISABLE_SESSION_CACHE (used by the throwaway e2e backends) makes start()
    a no-op: no .session dir, no autosave thread, and stop() stays a safe no-op — so
    an e2e run never flushes session docs into the shared workspace."""
    monkeypatch.setenv("NADOC_DISABLE_SESSION_CACHE", "1")
    monkeypatch.setattr(session_cache, "_session_dir", None)
    monkeypatch.setattr(session_cache, "_thread", None)

    session_cache.start(tmp_path)

    assert session_cache._session_dir is None      # never bound → nothing persists
    assert session_cache._thread is None           # no flush thread spawned
    assert not (tmp_path / ".session").exists()
    session_cache.stop()                            # must not raise (guards on None dir)
