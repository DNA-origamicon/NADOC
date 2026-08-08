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

The user selects the downloaded file with the folder navigator (see
`backend/core/fs_browse.py`), which hands its path here.

Pure helpers (`parse_namd_filename`, `parse_arbd_filename`) are unit-tested; the
tar peek + extraction/build are the only impurities.
"""

from __future__ import annotations

import asyncio
import os
import re
import shutil
import tarfile

from backend.core.engines import gpu_info
from backend.core.namd_runner import find_namd
from backend.core.namd_topology import find_psfgen

# NAMD release tarballs look like:
#   NAMD_3.0.2_Linux-x86_64-multicore-CUDA.tar.gz
#   NAMD_3.0.2_Linux-x86_64-multicore.tar.gz
_NAMD_RE = re.compile(r"^NAMD_.*Linux-x86_64.*\.tar\.gz$", re.IGNORECASE)

# ARBD source tarballs look like: arbd-may24-beta.tar.gz  (from the KS/UIUC portal).
_ARBD_RE = re.compile(r"^arbd.*\.tar\.(gz|xz|bz2)$", re.IGNORECASE)


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


def _build_warning(parsed: dict, gpu: dict) -> str:
    if gpu.get("present") and not parsed["is_cuda"]:
        names = ", ".join(gpu.get("names") or []) or "a CUDA GPU"
        return (
            f"This is the CPU build, but {names} was detected — the "
            "multicore-CUDA build is much faster. You can install this anyway."
        )
    if not gpu.get("present") and parsed["is_cuda"]:
        return (
            "This is the CUDA (GPU) build but no GPU was detected — it will run on CPU."
        )
    return ""


# ── deep validation + install ─────────────────────────────────────────────────


def validate_namd_archive(path: str, gpu: dict) -> dict:
    """Rigorously check a specific file: exists, named right, and CONTAINS namd3.

    Returns ``{path, valid, filename, is_cuda, build, contains_namd3, warning,
    error}``.  ``valid`` is True only when the filename matches AND the tarball
    actually carries a ``namd3`` executable.
    """
    res = {
        "path": path,
        "valid": False,
        "contains_namd3": False,
        "is_cuda": False,
        "build": None,
        "filename": None,
        "warning": "",
        "error": "",
    }
    if not path or not os.path.isfile(os.path.expanduser(path)):
        res["error"] = "File not found."
        return res
    real = os.path.expanduser(path)
    parsed = parse_namd_filename(real)
    if not parsed:
        res["error"] = (
            "This doesn't look like a NAMD Linux-x86_64 tarball (NAMD_*_Linux-x86_64*.tar.gz)."
        )
        return res
    res.update(
        filename=parsed["filename"],
        is_cuda=parsed["is_cuda"],
        build="CUDA" if parsed["is_cuda"] else "CPU",
        warning=_build_warning(parsed, gpu),
    )
    try:
        with tarfile.open(real) as tar:
            for m in tar:  # streams; namd3 sits near the top
                if m.isfile() and os.path.basename(m.name) == "namd3":
                    res["contains_namd3"] = True
                    break
    except (tarfile.TarError, OSError) as exc:
        res["error"] = f"Could not read the archive: {exc}"
        return res
    if not res["contains_namd3"]:
        res["error"] = (
            "The archive doesn't contain a namd3 binary — wrong or corrupt download."
        )
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

    await send(
        {
            "type": "log",
            "line": f"Verified {v['filename']} ({v['build']} build) — contains namd3 ✓",
        }
    )
    dest = os.path.expanduser("~/Applications")
    os.makedirs(dest, exist_ok=True)
    await send({"type": "progress", "stage": "Extracting NAMD…", "pct": 5})

    count = 0
    with tarfile.open(real) as tar:
        for m in tar:
            tar.extract(m, dest, filter="data")  # 3.12 safe-extraction filter
            count += 1
            if count % 200 == 0:
                await send(
                    {
                        "type": "progress",
                        "stage": f"Extracting NAMD… ({count} files)",
                        "pct": min(90, 5 + count // 60),
                    }
                )

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


# ── ARBD: downloaded source tarball → build (sudo install stays manual) ───────
#
# ARBD isn't a public one-click download; the user gets the source tarball from
# the TBGL lab, drops it in ~/Downloads, and NADOC verifies + builds it.  Unlike
# NAMD (a prebuilt binary we just extract), ARBD must be *compiled* (cmake+make)
# and then installed to /usr/local/bin/arbd with `sudo make install` — which needs
# the admin password, so that final line stays manual (streamed as a `manual_step`
# rather than a `complete`).


def parse_arbd_filename(name: str) -> dict | None:
    """PURE: an ARBD source-tarball filename → ``{filename}`` or None.

    None means it doesn't look like an ``arbd*.tar.(gz|xz|bz2)`` archive.
    """
    base = os.path.basename(name)
    if not _ARBD_RE.match(base):
        return None
    return {"filename": base}


def validate_arbd_archive(path: str, gpu: dict) -> dict:
    """Check a specific file: exists, named right, and looks like ARBD *source*.

    Returns ``{path, valid, filename, is_source, warning, error}``.  ``valid`` is
    True only when the filename matches AND the tarball carries a build entry point
    (a ``CMakeLists.txt`` or a ``src/`` directory).
    """
    res = {
        "path": path,
        "valid": False,
        "is_source": False,
        "filename": None,
        "warning": "",
        "error": "",
    }
    if not path or not os.path.isfile(os.path.expanduser(path)):
        res["error"] = "File not found."
        return res
    real = os.path.expanduser(path)
    parsed = parse_arbd_filename(real)
    if not parsed:
        res["error"] = "This doesn't look like an ARBD source tarball (arbd*.tar.gz)."
        return res
    res["filename"] = parsed["filename"]
    if not gpu.get("present"):
        res["warning"] = (
            "No CUDA GPU detected — ARBD builds but can't run simulations without a GPU."
        )
    try:
        with tarfile.open(real) as tar:
            for m in tar:
                b = os.path.basename(m.name.rstrip("/"))
                if b == "CMakeLists.txt" or (m.isdir() and b == "src"):
                    res["is_source"] = True
                    break
    except (tarfile.TarError, OSError) as exc:
        res["error"] = f"Could not read the archive: {exc}"
        return res
    if not res["is_source"]:
        res["error"] = (
            "The archive doesn't look like ARBD source (no CMakeLists.txt / src/) — wrong or corrupt download."
        )
        return res
    res["valid"] = True
    return res


async def install_arbd_archive(path: str, send) -> None:
    """Verify → extract → cmake → make an ARBD source tarball, streamed.

    Stops one step short of a full install: the binary lands in /usr/local/bin only
    after ``sudo make install`` (admin password), which a background stream can't
    do.  So on a successful build this emits a ``manual_step`` message with the one
    line to paste, instead of ``complete``.  Raises `ArtifactError` on a bad archive
    or a failed configure/compile.
    """
    real = os.path.expanduser(path)
    v = validate_arbd_archive(real, gpu_info())
    if not v["valid"]:
        raise ArtifactError(v.get("error") or "Not a valid ARBD source archive.")

    await send({"type": "log", "line": f"Verified {v['filename']} — ARBD source ✓"})
    src = os.path.expanduser("~/arbd-src")
    build = os.path.join(src, "build")
    os.makedirs(src, exist_ok=True)

    await send({"type": "progress", "stage": "Unpacking ARBD…", "pct": 5})
    count = 0
    with tarfile.open(real) as tar:
        members = tar.getmembers()
        strip = _common_prefix_len(members)
        for m in members:
            stripped = _strip_prefix(m.name, strip)
            if not stripped:
                continue
            m.name = stripped
            tar.extract(m, src, filter="data")
            count += 1
            if count % 200 == 0:
                await send(
                    {
                        "type": "progress",
                        "stage": f"Unpacking ARBD… ({count} files)",
                        "pct": min(20, 5 + count // 100),
                    }
                )

    os.makedirs(build, exist_ok=True)
    await send({"type": "progress", "stage": "Configuring (cmake)…", "pct": 25})
    rc = await _stream_build(
        ["cmake", "..", "-DCMAKE_INSTALL_PREFIX=/usr/local"], build, send
    )
    if rc != 0:
        raise ArtifactError(
            "cmake failed — usually the CUDA toolkit (nvcc) is missing or CUDA "
            "headers aren't found. Install the CUDA toolkit, then try again."
        )

    await send(
        {
            "type": "progress",
            "stage": "Compiling (make) — this can take several minutes…",
            "pct": 45,
        }
    )
    rc = await _stream_build(["make", f"-j{os.cpu_count() or 2}"], build, send)
    if rc != 0:
        raise ArtifactError("make failed — see the log above for the compiler error.")

    await send({"type": "progress", "stage": "Built — one step left", "pct": 95})
    await send(
        {
            "type": "manual_step",
            "engine": "arbd",
            "command": f"cd {build} && sudo make install",
            "cwd": build,
            "can_finish_built": True,  # a no-password finish is available (copy onto PATH)
            "note": (
                "ARBD built successfully (the Linux binary). To finish, either click "
                "**Finish install (no password)** to copy it onto your PATH, or — for a "
                "system-wide install — paste this one line in a terminal (needs your "
                f"password):\n\n    cd {build} && sudo make install\n\nThen click Re-check."
            ),
        }
    )


async def install_arbd_binary(send) -> str:
    """No-password finish: copy an already-built ARBD Linux binary onto PATH.

    Resolves the common WSL snag where ARBD built fine on the Linux side
    (``~/arbd-src/build/arbd``) but ``sudo make install`` was never completed, so
    NADOC can't find it.  Copies the built binary to ``~/.local/bin/arbd`` (no
    sudo), makes it executable, and confirms `find_arbd()` now resolves it.  Warns
    if ``~/.local/bin`` isn't on PATH (mrdna needs to spawn ``arbd``).  Raises
    `ArtifactError` if no built binary is found.
    """
    from backend.core.mrdna_bridge import find_arbd, find_arbd_build

    built = find_arbd_build()
    if not built:
        raise ArtifactError(
            "No built ARBD binary found (looked in ~/arbd-src/build). Build ARBD first "
            "with the download-and-build step above."
        )
    await send({"type": "log", "line": f"Found built binary: {built}"})
    dest_dir = os.path.expanduser("~/.local/bin")
    os.makedirs(dest_dir, exist_ok=True)
    dest = os.path.join(dest_dir, "arbd")
    await send({"type": "progress", "stage": "Installing arbd onto PATH…", "pct": 40})
    shutil.copy2(built, dest)
    os.chmod(dest, 0o755)
    await send({"type": "log", "line": f"Installed → {dest}"})

    resolved = find_arbd()
    if not resolved:
        raise ArtifactError(f"Copied to {dest} but NADOC still can't resolve it.")
    path_dirs = os.environ.get("PATH", "").split(os.pathsep)
    if dest_dir not in path_dirs:
        await send(
            {
                "type": "log",
                "line": (
                    f"Note: {dest_dir} isn't on this server's PATH. arbd is installed, but if a "
                    "simulation can't launch it, add ~/.local/bin to PATH (or use sudo make "
                    "install for /usr/local/bin) and restart NADOC."
                ),
            }
        )
    await send({"type": "progress", "stage": "Done", "pct": 100})
    await send({"type": "complete", "engine": "arbd", "path": resolved})
    return resolved


async def install_arbd_sudo(password: str, send) -> str:
    """Run ``sudo make install`` for the user (system-wide /usr/local install).

    For users who'd rather not open a terminal: NADOC runs the one privileged step
    itself, feeding the password to ``sudo -S`` on stdin.  The password is used
    once, never logged, and never streamed back.  Requires ARBD to be built already
    (``~/arbd-src/build``).  Raises `ArtifactError` on a wrong password or a failed
    install (the two are hard to tell apart, so the message covers both).

    Security note: this is a localhost-only personal tool; the password travels the
    local WebSocket to the local backend and straight into ``sudo``.
    """
    from backend.core.mrdna_bridge import find_arbd, find_arbd_build

    build = find_arbd_build()
    build_dir = (
        os.path.dirname(build) if build else os.path.expanduser("~/arbd-src/build")
    )
    if not os.path.isdir(build_dir):
        raise ArtifactError(
            "ARBD isn't built yet — build it first (the download step above)."
        )
    if not password:
        raise ArtifactError("No password was entered.")

    await send(
        {"type": "progress", "stage": "Installing ARBD (sudo make install)…", "pct": 30}
    )
    # -S: read password from stdin;  -k: force re-auth so a wrong password really fails
    proc = await asyncio.create_subprocess_exec(
        "sudo",
        "-S",
        "-k",
        "-p",
        "",
        "make",
        "install",
        cwd=build_dir,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    assert proc.stdin is not None and proc.stdout is not None
    proc.stdin.write((password + "\n").encode())
    try:
        await proc.stdin.drain()
    except (BrokenPipeError, ConnectionResetError):
        pass
    proc.stdin.close()

    async for raw in proc.stdout:
        line = raw.decode("utf-8", "replace").rstrip()
        # never echo the password; sudo's own prompt is suppressed via -p ""
        if line and password not in line:
            await send({"type": "log", "line": line})
    rc = await proc.wait()
    if rc != 0:
        raise ArtifactError(
            "Couldn't finish the install. The password may be incorrect, or `make "
            "install` failed — check the log. You can also use the no-password option."
        )

    resolved = find_arbd()
    if not resolved:
        raise ArtifactError(
            "Ran the install but arbd still isn't where NADOC looks (/usr/local/bin)."
        )
    await send({"type": "progress", "stage": "Done", "pct": 100})
    await send({"type": "complete", "engine": "arbd", "path": resolved})
    return resolved


def _common_prefix_len(members: list) -> str | None:
    """The single top-level dir shared by every member (e.g. ``arbd-may24/``), else None."""
    tops = {
        m.name.split("/", 1)[0]
        for m in members
        if m.name and not m.name.startswith("/")
    }
    return tops.pop() if len(tops) == 1 else None


def _strip_prefix(name: str, prefix: str | None) -> str:
    if not prefix:
        return name
    if name == prefix:
        return ""
    if name.startswith(prefix + "/"):
        return name[len(prefix) + 1 :]
    return name


async def _stream_build(argv: list[str], cwd: str, send) -> int:
    """Run ``argv`` in ``cwd``, forwarding each output line to ``send`` as a log."""
    os.makedirs(cwd, exist_ok=True)
    proc = await asyncio.create_subprocess_exec(
        *argv,
        cwd=cwd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    assert proc.stdout is not None
    async for raw in proc.stdout:
        line = raw.decode("utf-8", "replace").rstrip()
        if line:
            await send({"type": "log", "line": line})
    return await proc.wait()


def _safe(fn):
    try:
        return fn()
    except Exception:
        return None
