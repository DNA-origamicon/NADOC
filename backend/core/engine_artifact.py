"""Downloaded-artifact install — verify a user-downloaded package, then finish.

Some engines can't be auto-downloaded (NAMD is license-gated: the user must
register + accept the license on the NAMD site and download the tarball by hand).
This module closes the rest of the gap: given the file the user downloaded, it

  1. **checks it's the right package** — filename shape + a peek inside the tarball
     for the `namd3` binary (`validate_namd_archive`), GPU-aware (warns if a CPU
     build was grabbed on a GPU machine), and
  2. **finishes the install** — extracts it to the conventional `~/Applications`
     location and confirms `find_namd()` / `find_psfgen()` now resolve
     (`install_namd_archive`, streamed like the source builds).

`scan_namd_downloads` finds likely candidates in `~/Downloads` etc. so the UI can
offer "check download & install" without the user pasting a path.

Pure helpers (`parse_namd_filename`, `pick_best_candidate`) are unit-tested; the
FS scan + extraction are the only impurities.
"""

from __future__ import annotations

import os
import re
import tarfile
from pathlib import Path

from backend.core.engines import gpu_info
from backend.core.namd_runner import find_namd
from backend.core.namd_topology import find_psfgen

# NAMD release tarballs look like:
#   NAMD_3.0.2_Linux-x86_64-multicore-CUDA.tar.gz
#   NAMD_3.0.2_Linux-x86_64-multicore.tar.gz
_NAMD_RE = re.compile(r"^NAMD_.*Linux-x86_64.*\.tar\.gz$", re.IGNORECASE)

_DEFAULT_SEARCH_DIRS = ["~/Downloads", "~", "~/Desktop"]


class ArtifactError(RuntimeError):
    """The downloaded file is missing, the wrong package, or unreadable."""


# ── pure filename logic ───────────────────────────────────────────────────────

def parse_namd_filename(name: str) -> dict | None:
    """PURE: a NAMD tarball filename → ``{filename, is_cuda, multicore}`` or None.

    None means the name doesn't look like a NAMD Linux-x86_64 tarball at all.
    """
    base = os.path.basename(name)
    if not _NAMD_RE.match(base):
        return None
    low = base.lower()
    return {"filename": base, "is_cuda": "cuda" in low, "multicore": "multicore" in low}


def pick_best_candidate(candidates: list[dict], gpu: dict) -> dict | None:
    """PURE: choose the best NAMD candidate — on a GPU box prefer the CUDA build.

    ``candidates`` are the dicts produced by ``scan_namd_downloads``.  Returns the
    preferred one (CUDA-first when a GPU is present, then newest filename), or None.
    """
    valid = [c for c in candidates if c.get("matches_name")]
    if not valid:
        return None
    want_cuda = bool(gpu.get("present"))
    valid.sort(key=lambda c: (
        0 if c["is_cuda"] == want_cuda else 1,   # matching build type first
        c["filename"],
    ), reverse=False)
    # newest filename within the preferred group: filenames sort ascending, so
    # take the max within the first group.
    group = [c for c in valid if c["is_cuda"] == want_cuda] or valid
    return max(group, key=lambda c: c["filename"])


def _build_warning(parsed: dict, gpu: dict) -> str:
    if gpu.get("present") and not parsed["is_cuda"]:
        names = ", ".join(gpu.get("names") or []) or "a CUDA GPU"
        return (f"This is the CPU build, but {names} was detected — the "
                "multicore-CUDA build is much faster. You can install this anyway.")
    if not gpu.get("present") and parsed["is_cuda"]:
        return "This is the CUDA (GPU) build but no GPU was detected — it will run on CPU."
    return ""


# ── FS scan ───────────────────────────────────────────────────────────────────

def scan_namd_downloads(gpu: dict, search_dirs: list[str] | None = None) -> list[dict]:
    """Find candidate NAMD tarballs in the user's download folders.

    Filename-level check only (fast, no tar peek) so the UI can list candidates
    immediately; the deep validation happens in `install_namd_archive`.  Each
    candidate: ``{path, filename, is_cuda, multicore, matches_name, build, warning}``.
    """
    dirs = search_dirs or _DEFAULT_SEARCH_DIRS
    seen: set[str] = set()
    out: list[dict] = []
    for d in dirs:
        base = Path(os.path.expanduser(d))
        if not base.is_dir():
            continue
        try:
            entries = list(base.glob("NAMD_*Linux-x86_64*.tar.gz"))
        except OSError:
            continue
        for p in entries:
            rp = str(p.resolve())
            if rp in seen:
                continue
            seen.add(rp)
            parsed = parse_namd_filename(p.name)
            if not parsed:
                continue
            out.append({
                "path": rp,
                "filename": parsed["filename"],
                "is_cuda": parsed["is_cuda"],
                "multicore": parsed["multicore"],
                "matches_name": True,
                "build": "CUDA" if parsed["is_cuda"] else "CPU",
                "warning": _build_warning(parsed, gpu),
            })
    return out


# ── deep validation + install ─────────────────────────────────────────────────

def validate_namd_archive(path: str, gpu: dict) -> dict:
    """Rigorously check a specific file: exists, named right, and CONTAINS namd3.

    Returns ``{path, valid, filename, is_cuda, build, contains_namd3, warning,
    error}``.  ``valid`` is True only when the filename matches AND the tarball
    actually carries a ``namd3`` executable.
    """
    res = {"path": path, "valid": False, "contains_namd3": False,
           "is_cuda": False, "build": None, "filename": None, "warning": "", "error": ""}
    if not path or not os.path.isfile(os.path.expanduser(path)):
        res["error"] = "File not found."
        return res
    real = os.path.expanduser(path)
    parsed = parse_namd_filename(real)
    if not parsed:
        res["error"] = "This doesn't look like a NAMD Linux-x86_64 tarball (NAMD_*_Linux-x86_64*.tar.gz)."
        return res
    res.update(filename=parsed["filename"], is_cuda=parsed["is_cuda"],
               build="CUDA" if parsed["is_cuda"] else "CPU",
               warning=_build_warning(parsed, gpu))
    try:
        with tarfile.open(real) as tar:
            for m in tar:                       # streams; namd3 sits near the top
                if m.isfile() and os.path.basename(m.name) == "namd3":
                    res["contains_namd3"] = True
                    break
    except (tarfile.TarError, OSError) as exc:
        res["error"] = f"Could not read the archive: {exc}"
        return res
    if not res["contains_namd3"]:
        res["error"] = "The archive doesn't contain a namd3 binary — wrong or corrupt download."
        return res
    res["valid"] = True
    return res


async def install_namd_archive(path: str, send) -> str:
    """Validate then extract a NAMD tarball to ``~/Applications``, streamed.

    ``send`` is the WebSocket callback (same protocol as engine_install).  Raises
    `ArtifactError` if the file is the wrong package or if ``namd3`` isn't detected
    after extraction (the UI surfaces the reason).
    """
    real = os.path.expanduser(path)
    v = validate_namd_archive(real, gpu_info())
    if not v["valid"]:
        raise ArtifactError(v.get("error") or "Not a valid NAMD archive.")

    await send({"type": "log", "line": f"Verified {v['filename']} ({v['build']} build) — contains namd3 ✓"})
    dest = os.path.expanduser("~/Applications")
    os.makedirs(dest, exist_ok=True)
    await send({"type": "progress", "stage": "Extracting NAMD…", "pct": 5})

    count = 0
    with tarfile.open(real) as tar:
        for m in tar:
            tar.extract(m, dest, filter="data")   # 3.12 safe-extraction filter
            count += 1
            if count % 200 == 0:
                await send({"type": "progress", "stage": f"Extracting NAMD… ({count} files)",
                            "pct": min(90, 5 + count // 60)})

    namd = _safe(find_namd)
    psfgen = _safe(find_psfgen)
    if not namd:
        raise ArtifactError(
            "Extracted, but namd3 wasn't found where NADOC looks. The tarball may "
            "have an unexpected layout — see docs/namd_setup.md."
        )
    await send({"type": "log", "line": f"namd3 → {namd}"})
    if psfgen:
        await send({"type": "log", "line": f"psfgen → {psfgen}"})
    await send({"type": "progress", "stage": "Done", "pct": 100})
    await send({"type": "complete", "engine": "namd", "path": namd})
    return namd


def _safe(fn):
    try:
        return fn()
    except Exception:
        return None
