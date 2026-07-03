"""Server-side directory browsing for the "pick a downloaded file" UI.

The MD-Engines install flow needs the *filesystem path* of a file the user
downloaded (to extract NAMD / build ARBD).  A browser `<input type=file>` can't
give us that path (browsers hide it), so the frontend drives a small folder
navigator backed by these helpers instead: list a directory, step up/down, pick a
file — starting at the user's Downloads folder.

WSL note: the user's *real* Downloads is usually the Windows one
(`/mnt/c/Users/<name>/Downloads`), not the Linux `~/Downloads`.
`default_downloads_dir()` prefers the Windows folder when it exists so the picker
opens where the file actually is.

Read-only; the only impurity is the filesystem scan.
"""

from __future__ import annotations

import glob
import os
from pathlib import Path

_WIN_SKIP = {"Default", "Default User", "Public", "All Users"}


def _safe_mtime(path: str) -> float:
    try:
        return os.path.getmtime(path)
    except OSError:
        return 0.0


def _windows_downloads() -> list[str]:
    """Every real per-user Windows Downloads visible under /mnt/*/Users/*/Downloads."""
    out: list[str] = []
    for d in glob.glob("/mnt/*/Users/*/Downloads"):
        user = os.path.basename(os.path.dirname(d))
        if user in _WIN_SKIP:
            continue
        if os.path.isdir(d):
            out.append(d)
    return out


def default_downloads_dir() -> str:
    """Best guess at the folder the picker should open in.

    Prefers the Windows Downloads (most-recently-touched) on WSL, since that's
    where a browser download actually lands; falls back to ``~/Downloads`` then
    ``~``.
    """
    wins = _windows_downloads()
    if wins:
        return max(wins, key=_safe_mtime)
    home_dl = os.path.expanduser("~/Downloads")
    if os.path.isdir(home_dl):
        return home_dl
    return os.path.expanduser("~")


def list_dir(path: str | None, *, name_glob: str | None = None) -> dict:
    """List a directory for the folder navigator.

    Returns ``{cwd, parent, error, entries}`` where each entry is
    ``{name, path, is_dir, size, mtime, matches}``.  Directories come first
    (alphabetical); files follow sorted by mtime **descending** ("recents"),
    so the just-downloaded file is at the top.  ``matches`` flags files that fit
    ``name_glob`` (e.g. ``"arbd*.tar.*"``) so the UI can highlight likely picks
    (navigation is never restricted — the user can still open anything).
    ``path=None`` (or a missing/unreadable dir) falls back to the Downloads dir.
    """
    cwd = os.path.expanduser(path) if path else default_downloads_dir()
    cwd = os.path.abspath(cwd)
    if not os.path.isdir(cwd):
        cwd = default_downloads_dir()

    parent = os.path.dirname(cwd.rstrip("/")) or "/"
    if parent == cwd:
        parent = None  # at filesystem root

    dirs: list[dict] = []
    files: list[dict] = []
    error = ""
    try:
        with os.scandir(cwd) as it:
            for e in it:
                if e.name.startswith("."):
                    continue
                try:
                    is_dir = e.is_dir()
                    st = e.stat()
                except OSError:
                    continue
                row = {
                    "name": e.name,
                    "path": os.path.join(cwd, e.name),
                    "is_dir": is_dir,
                    "size": 0 if is_dir else st.st_size,
                    "mtime": st.st_mtime,
                    "matches": (not is_dir and _matches(e.name, name_glob)),
                }
                (dirs if is_dir else files).append(row)
    except OSError as exc:
        error = f"Can't open this folder: {exc}"

    dirs.sort(key=lambda r: r["name"].lower())
    files.sort(key=lambda r: r["mtime"], reverse=True)
    return {"cwd": cwd, "parent": parent, "error": error, "entries": dirs + files}


def _matches(name: str, name_glob: str | None) -> bool:
    if not name_glob:
        return False
    return Path(name.lower()).match(name_glob.lower())
