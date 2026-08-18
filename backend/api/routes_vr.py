"""Local native-OpenXR companion lifecycle for Linux VR.

Stock Linux browsers do not currently bridge WebXR to SteamVR. These endpoints
are therefore deliberately localhost-only: they snapshot the active NADOC part
into a compact read-only scene file and launch/stop the bundled native viewer.
No design data is mutated and no shell command is constructed from request data.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import signal
import subprocess
import tempfile
import threading
import time
from typing import Optional
from urllib.parse import urlparse

import numpy as np
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from backend.api import state as design_state
from backend.core.constants import STAPLE_PALETTE

router = APIRouter(tags=["vr"])

_REPO_ROOT = Path(__file__).resolve().parents[2]
_VIEWER_DIR = _REPO_ROOT / "native" / "vr_viewer"
_BUILD_DIR = _VIEWER_DIR / "build"
_VIEWER = _BUILD_DIR / "nadoc-vr-viewer"
_STATE_PATH = Path(tempfile.gettempdir()) / f"nadoc-vr-{os.getuid()}.json"
_LOG_PATH = Path(tempfile.gettempdir()) / f"nadoc-vr-{os.getuid()}.log"
_STATE_LOCK = threading.Lock()


class VRCamera(BaseModel):
    position: list[float] = Field(min_length=3, max_length=3)
    target: list[float] = Field(min_length=3, max_length=3)
    up: list[float] = Field(min_length=3, max_length=3)


class VRLaunchRequest(BaseModel):
    camera: Optional[VRCamera] = None
    measured_positioning: bool = False
    assembly_active: bool = False


def _require_local(request: Request) -> None:
    host = request.client.host if request.client else ""
    if host not in {"127.0.0.1", "::1", "localhost"}:
        raise HTTPException(403, detail="Native VR launch is available only from localhost.")
    # A local Vite reverse proxy makes every backend peer look loopback. Preserve
    # the workstation-only boundary by also checking the browser's Origin.
    origin = request.headers.get("origin")
    if origin and (urlparse(origin).hostname or "") not in {
        "127.0.0.1",
        "::1",
        "localhost",
    }:
        raise HTTPException(403, detail="Native VR launch is available only from localhost.")


def _rgb(hex_color: str) -> tuple[float, float, float]:
    value = int(hex_color.lstrip("#"), 16)
    return (
        ((value >> 16) & 0xFF) / 255.0,
        ((value >> 8) & 0xFF) / 255.0,
        (value & 0xFF) / 255.0,
    )


def _strand_colors(design) -> dict[str, tuple[float, float, float]]:
    colors: dict[str, tuple[float, float, float]] = {}
    staple_index = 0
    for strand in design.strands:
        if not strand.id:
            continue
        if strand.is_scaffold:
            colors[strand.id] = _rgb("#0070bb")
        elif strand.color:
            colors[strand.id] = _rgb(strand.color)
        else:
            colors[strand.id] = _rgb(
                STAPLE_PALETTE[staple_index % len(STAPLE_PALETTE)]
            )
            staple_index += 1
    return colors


def _view_rotation(camera: VRCamera | None) -> np.ndarray:
    """Rows map NADOC world coordinates into the desktop camera's view axes."""
    if camera is None:
        return np.identity(3, dtype=float)
    position = np.asarray(camera.position, dtype=float)
    target = np.asarray(camera.target, dtype=float)
    up_hint = np.asarray(camera.up, dtype=float)
    if not np.all(np.isfinite([position, target, up_hint])):
        return np.identity(3, dtype=float)
    forward = target - position
    forward_norm = float(np.linalg.norm(forward))
    up_norm = float(np.linalg.norm(up_hint))
    if forward_norm < 1e-9 or up_norm < 1e-9:
        return np.identity(3, dtype=float)
    forward /= forward_norm
    up_hint /= up_norm
    right = np.cross(forward, up_hint)
    right_norm = float(np.linalg.norm(right))
    if right_norm < 1e-9:
        return np.identity(3, dtype=float)
    right /= right_norm
    up = np.cross(right, forward)
    # OpenXR neutral view looks down -Z.
    return np.stack([right, up, -forward])


def _serialize_scene(design, nucleotides: list[dict], axes: list[dict], camera=None) -> str:
    """Create the deliberately trivial line-oriented format read by the C++ viewer."""
    rotation = _view_rotation(camera)
    colors = _strand_colors(design)
    default_color = (0.55, 0.62, 0.72)

    def point(value) -> np.ndarray | None:
        if not isinstance(value, (list, tuple)) or len(value) != 3:
            return None
        p = np.asarray(value, dtype=float)
        if not np.all(np.isfinite(p)):
            return None
        return rotation @ p

    def nums(*values: float) -> str:
        return " ".join(f"{float(value):.7g}" for value in values)

    lines = ["NADOCVR 1", "# Read-only NADOC display snapshot"]
    by_strand: dict[str, list[tuple[dict, np.ndarray]]] = {}
    for nucleotide in nucleotides:
        backbone = point(nucleotide.get("backbone_position"))
        base = point(nucleotide.get("base_position"))
        if backbone is None:
            continue
        strand_id = nucleotide.get("strand_id") or ""
        color = colors.get(strand_id, default_color)
        lines.append(f"P {nums(*backbone, *color, 9.0)}")
        if base is not None:
            base_color = tuple(min(1.0, channel * 0.75 + 0.25) for channel in color)
            lines.append(f"P {nums(*base, *base_color, 7.0)}")
            lines.append(f"L {nums(*backbone, *base, *color)}")
        if strand_id:
            by_strand.setdefault(strand_id, []).append((nucleotide, backbone))

    # Join sequential backbone beads. Long jumps are omitted so malformed or
    # sparse strand metadata cannot draw a line across an entire structure.
    for strand_nucleotides in by_strand.values():
        strand_nucleotides.sort(
            key=lambda item: (
                int(item[0].get("domain_index") or 0),
                int(item[0].get("bp_index") or 0)
                if item[0].get("direction") == "FORWARD"
                else -int(item[0].get("bp_index") or 0),
                int(item[0].get("copy_k") or item[0].get("ext_k") or 0),
            )
        )
        for (_, first), (_, second) in zip(
            strand_nucleotides, strand_nucleotides[1:]
        ):
            if float(np.linalg.norm(second - first)) <= 5.0:
                lines.append(f"L {nums(*first, *second, 0.72, 0.76, 0.84)}")

    for axis in axes:
        start = point(axis.get("start"))
        end = point(axis.get("end"))
        if start is not None and end is not None:
            lines.append(f"L {nums(*start, *end, 0.30, 0.34, 0.42)}")

    if len(lines) == 2:
        raise HTTPException(409, detail="The active design contains no display geometry.")
    return "\n".join(lines) + "\n"


def _snapshot(body: VRLaunchRequest) -> str:
    from backend.core.deformation import (
        _apply_ovhg_rotations_to_axes,
        deformed_helix_axes,
    )
    from backend.core.design_geometry import _geometry_for_design

    design = design_state.get_or_404()
    nucleotides = _geometry_for_design(
        design,
        measured_positioning=body.measured_positioning,
        junction_balance=True,
    )
    axes = deformed_helix_axes(design)
    _apply_ovhg_rotations_to_axes(design, axes, nucleotides)
    return _serialize_scene(design, nucleotides, axes, body.camera)


def _build_environment() -> dict[str, str]:
    env = dict(os.environ)
    for key in (
        "CFLAGS",
        "CXXFLAGS",
        "CPPFLAGS",
        "LDFLAGS",
        "CPATH",
        "CPLUS_INCLUDE_PATH",
        "CMAKE_PREFIX_PATH",
        "LIBRARY_PATH",
        "LD_LIBRARY_PATH",
        "CONDA_PREFIX",
    ):
        env.pop(key, None)
    env["PATH"] = "/usr/local/bin:/usr/bin:/bin"
    runtime = (
        Path.home()
        / ".local/share/Steam/steamapps/common/SteamVR/steamxr_linux64.json"
    )
    if runtime.is_file():
        env["XR_RUNTIME_JSON"] = str(runtime)
    return env


def _ensure_viewer_built() -> None:
    newest_source = max(
        (_VIEWER_DIR / "CMakeLists.txt").stat().st_mtime,
        *[path.stat().st_mtime for path in (_VIEWER_DIR / "src").glob("*.cpp")],
    )
    if _VIEWER.is_file() and _VIEWER.stat().st_mtime >= newest_source:
        return

    env = _build_environment()
    env.update({"CC": "/usr/bin/gcc", "CXX": "/usr/bin/g++"})
    configure = subprocess.run(
        [
            "/usr/bin/cmake",
            "-S",
            str(_VIEWER_DIR),
            "-B",
            str(_BUILD_DIR),
            "-G",
            "Ninja",
            "-DCMAKE_BUILD_TYPE=Release",
        ],
        env=env,
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    if configure.returncode != 0:
        raise HTTPException(503, detail=f"VR viewer configure failed: {configure.stderr[-1200:]}")
    build = subprocess.run(
        ["/usr/bin/cmake", "--build", str(_BUILD_DIR)],
        env=env,
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    if build.returncode != 0 or not _VIEWER.is_file():
        raise HTTPException(503, detail=f"VR viewer build failed: {build.stderr[-1200:]}")


def _read_state() -> dict | None:
    try:
        state = json.loads(_STATE_PATH.read_text())
        pid = int(state["pid"])
        expected = _VIEWER.resolve()
        actual = Path(f"/proc/{pid}/exe").resolve()
        if actual != expected:
            raise ValueError("PID no longer belongs to NADOC VR")
        return state
    except (FileNotFoundError, KeyError, ValueError, OSError, json.JSONDecodeError):
        _STATE_PATH.unlink(missing_ok=True)
        return None


def _write_state(state: dict) -> None:
    _STATE_PATH.write_text(json.dumps(state))
    _STATE_PATH.chmod(0o600)


def _cleanup_after_process(process: subprocess.Popen, scene_path: Path) -> None:
    process.wait()
    scene_path.unlink(missing_ok=True)
    with _STATE_LOCK:
        state = _read_state()
        if state and int(state["pid"]) == process.pid:
            _STATE_PATH.unlink(missing_ok=True)


def _status_payload() -> dict:
    state = _read_state()
    if not state:
        return {
            "running": False,
            "available": _VIEWER.is_file() or (_VIEWER_DIR / "CMakeLists.txt").is_file(),
            "log_path": str(_LOG_PATH),
        }
    return {
        "running": True,
        "available": True,
        "pid": int(state["pid"]),
        "started_at": state.get("started_at"),
        "log_path": str(_LOG_PATH),
    }


@router.get("/vr/status")
def vr_status(request: Request) -> dict:
    _require_local(request)
    return _status_payload()


@router.post("/vr/launch")
def launch_vr(body: VRLaunchRequest, request: Request) -> dict:
    _require_local(request)
    if body.assembly_active:
        raise HTTPException(
            409,
            detail="The first native VR viewer supports Part view; exit Assembly mode first.",
        )

    with _STATE_LOCK:
        running = _read_state()
        if running:
            return _status_payload()
        _ensure_viewer_built()
        scene_text = _snapshot(body)
        with tempfile.NamedTemporaryFile(
            mode="w",
            prefix="nadoc-vr-",
            suffix=".nadocvr",
            delete=False,
        ) as scene_file:
            scene_file.write(scene_text)
            scene_path = Path(scene_file.name)
        scene_path.chmod(0o600)

        log = _LOG_PATH.open("ab")
        try:
            process = subprocess.Popen(
                [str(_VIEWER), str(scene_path)],
                cwd=_REPO_ROOT,
                env=_build_environment(),
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=subprocess.STDOUT,
                start_new_session=True,
                close_fds=True,
            )
        except OSError as exc:
            scene_path.unlink(missing_ok=True)
            raise HTTPException(503, detail=f"Could not launch VR viewer: {exc}") from exc
        finally:
            log.close()

        # Catch immediate loader/display errors and return their last log line.
        time.sleep(0.15)
        if process.poll() is not None:
            scene_path.unlink(missing_ok=True)
            detail = "Native VR viewer exited during startup."
            try:
                tail = _LOG_PATH.read_text(errors="replace").splitlines()[-1]
                if tail:
                    detail = tail
            except (OSError, IndexError):
                pass
            raise HTTPException(503, detail=detail)

        state = {
            "pid": process.pid,
            "scene_path": str(scene_path),
            "started_at": time.time(),
        }
        _write_state(state)
        threading.Thread(
            target=_cleanup_after_process,
            args=(process, scene_path),
            daemon=True,
            name="nadoc-vr-cleanup",
        ).start()
        return _status_payload()


@router.post("/vr/stop")
def stop_vr(request: Request) -> dict:
    _require_local(request)
    with _STATE_LOCK:
        state = _read_state()
        if not state:
            return _status_payload()
        try:
            os.killpg(int(state["pid"]), signal.SIGTERM)
        except ProcessLookupError:
            _STATE_PATH.unlink(missing_ok=True)
        return {**_status_payload(), "stopping": True}
