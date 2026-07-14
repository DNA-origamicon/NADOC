"""Tests for the folder-navigator backend (backend/core/fs_browse.py)."""

from __future__ import annotations

import os
import time

import backend.core.fs_browse as fb


def test_list_dir_sorts_dirs_then_recent_files(tmp_path):
    (tmp_path / "zeta").mkdir()
    (tmp_path / "alpha").mkdir()
    old = tmp_path / "old.txt"; old.write_text("x")
    new = tmp_path / "new.txt"; new.write_text("y")
    # make new.txt genuinely newer
    os.utime(old, (time.time() - 1000, time.time() - 1000))
    os.utime(new, None)

    res = fb.list_dir(str(tmp_path))
    names = [e["name"] for e in res["entries"]]
    # directories first (alpha order), then files newest-first
    assert names[:2] == ["alpha", "zeta"]
    assert names.index("new.txt") < names.index("old.txt")
    assert res["cwd"] == str(tmp_path)
    assert res["parent"] == os.path.dirname(str(tmp_path))


def test_list_dir_flags_matches(tmp_path):
    (tmp_path / "arbd-may24-beta.tar.gz").write_text("x")
    (tmp_path / "notes.txt").write_text("y")
    res = fb.list_dir(str(tmp_path), name_glob="arbd*.tar.*")
    by = {e["name"]: e for e in res["entries"]}
    assert by["arbd-may24-beta.tar.gz"]["matches"] is True
    assert by["notes.txt"]["matches"] is False


def test_list_dir_hides_dotfiles(tmp_path):
    (tmp_path / ".secret").write_text("x")
    (tmp_path / "visible.txt").write_text("y")
    names = [e["name"] for e in fb.list_dir(str(tmp_path))["entries"]]
    assert ".secret" not in names and "visible.txt" in names


def test_list_dir_missing_path_falls_back_to_downloads(tmp_path, monkeypatch):
    # Redirect the default away from the *real* Downloads: on WSL that resolves to
    # /mnt/c/Users/<you>/Downloads, and scandir+stat'ing its 2000+ entries over the
    # drvfs mount takes seconds.  The fallback behaviour under test is unchanged.
    monkeypatch.setattr(fb, "default_downloads_dir", lambda: str(tmp_path))
    res = fb.list_dir("/no/such/dir/xyz-does-not-exist")
    # falls back to a real, listable directory (the Downloads default)
    assert os.path.isdir(res["cwd"])
    assert res["cwd"] == fb.default_downloads_dir()


def test_root_has_no_parent():
    res = fb.list_dir("/")
    assert res["cwd"] == "/"
    assert res["parent"] is None


def test_default_downloads_dir_is_a_directory():
    d = fb.default_downloads_dir()
    assert isinstance(d, str) and os.path.isdir(d)
