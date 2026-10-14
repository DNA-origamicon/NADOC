"""Workstation-local final-output recorder setup for ordinary VR launches.

No configuration means the portable application-eye recorder remains available.
A configured workstation always selects final output, including when its current
SteamVR process lacks the layer: readiness then reports an explicit error. Only a
fully stopped runtime may be bootstrapped; this module never stops a process or
changes installed SteamVR binaries, capabilities, or Vulkan configuration.
"""
from __future__ import annotations

from dataclasses import dataclass
import fcntl
import hashlib
import json
import os
from pathlib import Path
import tempfile
import time

_UNIX_SOCKET_PATH_BYTES = 108


class CaptureSetupError(RuntimeError):
    pass


@dataclass(frozen=True)
class CaptureConfig:
    archive_mount: Path
    storage_root: Path
    socket_root: Path
    layer_directory: Path
    layer_library_sha256: str
    active_capture_directory: Path | None
    viewer_build_directory: Path | None = None
    restore_presentation_file: Path | None = None


def _private_directory(path: Path) -> Path:
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    info = path.stat()
    if not path.is_dir() or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise CaptureSetupError(f"VR capture directory must be private and owned by this user: {path}")
    return path


def _archive_path(value: str, mount: Path, *, private: bool = False) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute() or path.resolve() != path:
        raise CaptureSetupError("VR capture paths must be absolute and must not contain symlinks")
    try:
        path.relative_to(mount)
    except ValueError as exc:
        raise CaptureSetupError(f"VR capture path is outside mounted Archive storage: {path}") from exc
    ancestor = path
    while not ancestor.exists():
        ancestor = ancestor.parent
    if ancestor.stat().st_dev != mount.stat().st_dev:
        raise CaptureSetupError("VR capture path is on a different filesystem from Archive")
    if path.exists() and (not path.is_dir() or path.stat().st_uid != os.getuid()):
        raise CaptureSetupError(f"VR capture directory must belong to this user: {path}")
    return _private_directory(path) if private else path


def _presentation_file(value: str, mount: Path) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute() or path.resolve() != path or not path.is_relative_to(mount):
        raise CaptureSetupError("VR presentation restore must be an absolute Archive file without symlinks")
    info = path.stat()
    if (not path.is_file() or info.st_uid != os.getuid() or info.st_mode & 0o022
            or info.st_size > 16384 or info.st_dev != mount.stat().st_dev):
        raise CaptureSetupError("VR presentation restore must be an owner-controlled regular file of at most 16 KiB")
    return path


def load_config() -> CaptureConfig | None:
    """Read only an owner-controlled local config; malformed setup never falls back."""
    path = Path(os.environ.get("NADOC_VR_CAPTURE_CONFIG", str(Path.home()/".config/nadoc/vr-capture.json"))).expanduser()
    if not path.exists() and not path.is_symlink():
        return None
    try:
        info = path.lstat()
        if path.is_symlink() or not path.is_file() or info.st_uid != os.getuid() or info.st_mode & 0o022:
            raise CaptureSetupError("VR capture configuration must be an owner-controlled regular file")
        if info.st_size > 16384:
            raise CaptureSetupError("VR capture configuration is too large")
        data = json.loads(path.read_text())
        if not isinstance(data, dict) or data.get("schema") != 1:
            raise CaptureSetupError("Unsupported VR capture configuration schema")
        mount = Path(data["archive_mount"]).expanduser()
        if not mount.is_absolute() or mount.resolve() != mount or not os.path.ismount(mount):
            raise CaptureSetupError("VR capture Archive storage is not mounted")
        storage = _archive_path(data["storage_root"], mount, private=True)
        sockets = _archive_path(data["socket_root"], mount, private=True)
        # Linux sockaddr_un has 108 bytes including its terminator. mkdtemp below
        # appends 10 bytes, then /viewer.sock. Reserve extra room rather than fail
        # after the runtime and scene have already started.
        if len(os.fsencode(sockets)) + 24 >= _UNIX_SOCKET_PATH_BYTES:
            raise CaptureSetupError("VR capture socket_root is too long for a private Unix socket")
        layer = _archive_path(data["layer_directory"], mount)
        expected = data["layer_library_sha256"]
        if not isinstance(expected, str) or len(expected) != 64 or any(c not in "0123456789abcdef" for c in expected):
            raise CaptureSetupError("VR capture layer requires a pinned SHA256")
        manifest = json.loads((layer/"VkLayer_NADOC_present_capture.json").read_text())
        if manifest["layer"]["name"] != "VK_LAYER_NADOC_present_capture":
            raise CaptureSetupError("Unexpected VR capture Vulkan layer name")
        library = Path(manifest["layer"]["library_path"])
        library = (library if library.is_absolute() else layer/library).resolve(strict=True)
        if not library.is_relative_to(layer) or not library.is_file() or library.stat().st_uid != os.getuid():
            raise CaptureSetupError("VR capture library must be inside the configured layer directory")
        with library.open("rb") as stream:
            actual = hashlib.file_digest(stream, "sha256").hexdigest()
        if actual != expected:
            raise CaptureSetupError("VR capture layer differs from its installed SHA256")
        active = data.get("active_capture_directory")
        active = _archive_path(active, mount) if active else None
        build = data.get("viewer_build_directory")
        build = _archive_path(build, mount) if build else None
        restore = data.get("restore_presentation_file")
        restore = _presentation_file(restore, mount) if restore else None
        return CaptureConfig(mount, storage, sockets, layer, expected, active, build, restore)
    except CaptureSetupError:
        raise
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise CaptureSetupError(f"Invalid VR capture configuration {path}: {exc}") from exc


def select_build_directory(default: Path, config: CaptureConfig | None) -> Path:
    """Keep the existing explicit environment override ahead of local setup."""
    override = os.environ.get("NADOC_VR_BUILD_DIR")
    if override:
        return Path(override).expanduser().resolve()
    return config.viewer_build_directory if config and config.viewer_build_directory else default


def backend_temporary_directory(config: CaptureConfig | None) -> Path | None:
    """Explicit per-file storage keeps concurrent backend workers off global TMPDIR."""
    return _private_directory(config.storage_root/"backend-tmp") if config else None


def cmake_generator(build_directory: Path) -> str:
    """Respect an existing native build without changing its generator in place."""
    cache = build_directory/"CMakeCache.txt"
    try:
        lines = cache.read_text().splitlines()
    except FileNotFoundError:
        return "Ninja"
    except OSError as exc:
        raise CaptureSetupError(f"Cannot read VR viewer CMake cache: {exc}") from exc
    generators = [line.partition("=")[2] for line in lines if line.startswith("CMAKE_GENERATOR:INTERNAL=")]
    if len(generators) != 1 or generators[0] not in {"Ninja", "Unix Makefiles"}:
        raise CaptureSetupError("Existing VR viewer build must use Ninja or Unix Makefiles")
    return generators[0]


def capture_directory(config: CaptureConfig) -> Path:
    state = config.storage_root/"active-runtime.json"
    if state.exists():
        try:
            if state.is_symlink() or state.stat().st_uid != os.getuid() or state.stat().st_mode & 0o022:
                raise CaptureSetupError("VR capture runtime pointer is not owner-controlled")
            data = json.loads(state.read_text())
            return _archive_path(data["capture_directory"], config.archive_mount)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise CaptureSetupError(f"Invalid VR capture runtime pointer: {exc}") from exc
    if config.active_capture_directory:
        return config.active_capture_directory
    # An uninjected existing runtime still gets a real final-recorder directory.
    # The helper will report unavailable rather than invoke the old eye recorder.
    return _private_directory(config.storage_root/"unavailable")


def directory_readiness(directory: Path) -> dict:
    status = {"configured": True, "available": False,
              "source": "final_swapchain_before_queue_present", "directory": str(directory),
              "checked_unix_ns": time.time_ns()}
    try:
        from tools.vr_capture.viewer_record import locate_layer
        path, header = locate_layer(directory)
        status.update(available=True, compositor_pid=header["pid"], event_log=str(path), reason=None)
    except (OSError, ValueError, RuntimeError) as exc:
        status["reason"] = ("Final-output recorder unavailable: " + str(exc) +
                            ". Close SteamVR normally, then launch VR from NADOC to prepare recording.")
    return status


def readiness(config: CaptureConfig) -> dict:
    return directory_readiness(capture_directory(config))


def start_runtime_if_stopped(config: CaptureConfig) -> bool:
    """Return whether the configured capture stack was started, without replacing one."""
    from tools.vr_capture import launch_compositor
    lock_path = config.storage_root/"runtime-launch.lock"
    with lock_path.open("a") as lock:
        os.chmod(lock_path, 0o600)
        fcntl.flock(lock, fcntl.LOCK_EX)
        if any(launch_compositor.process_ids(name) for name in ("vrserver", "vrcompositor", "vrmonitor")):
            return False
        output = config.storage_root/("runtime-" + str(time.time_ns()))
        # The shared launcher creates output itself and rejects any live runtime.
        launch_compositor.launch_stack(output, config.layer_directory, mode="pixels")
        state = {"schema": 1, "capture_directory": str(output/"compositor"),
                 "layer_library_sha256": config.layer_library_sha256,
                 "started_unix_ns": time.time_ns()}
        fd, name = tempfile.mkstemp(prefix=".active-runtime-", dir=config.storage_root)
        temporary = Path(name)
        try:
            with os.fdopen(fd, "w") as stream:
                json.dump(state, stream)
                stream.write("\n")
            os.replace(temporary, config.storage_root/"active-runtime.json")
        finally:
            temporary.unlink(missing_ok=True)
        return True


def ensure_runtime(config: CaptureConfig, status: dict, *, runtime_payload, assert_display) -> dict:
    """Reuse a running stack; wait for a fresh configured stack's recorder."""
    if status["steamvr_running"]:
        return status
    assert_display()
    if not start_runtime_if_stopped(config):
        # A different API worker may have bootstrapped while this one waited.
        status = runtime_payload()
        if status["steamvr_running"]:
            return status
        raise CaptureSetupError(
            "SteamVR is partially running. Close SteamVR normally, then "
            "launch VR from NADOC to prepare final-output recording."
        )
    deadline = time.monotonic() + 60.0
    while time.monotonic() < deadline:
        status = runtime_payload()
        if status["steamvr_running"] and readiness(config)["available"]:
            return status
        time.sleep(0.25)
    raise CaptureSetupError(
        "SteamVR started without a ready final-output recorder. "
        f"See {config.storage_root}."
    )


@dataclass(frozen=True)
class ViewerCapture:
    socket: Path
    journal_directory: Path
    temporary_directory: Path
    directory: Path
    status: dict
    restore_presentation_file: Path | None = None

    def environment(self, base: dict[str, str]) -> dict[str, str]:
        return {**base, "NADOC_VR_COMPOSITOR_CAPTURE_DIR": str(self.directory),
                "TMPDIR": str(self.temporary_directory)}

    def arguments(self) -> list[str]:
        args = ["--pose-journal", str(self.journal_directory), "--submitted-frame-marker", "recording"]
        if self.restore_presentation_file:
            args += ["--presentation-state", str(self.restore_presentation_file)]
        return args


def prepare_viewer(config: CaptureConfig) -> ViewerCapture:
    """All large diagnostic files start on Archive, including ScryWrite captures."""
    session = Path(tempfile.mkdtemp(prefix="viewer-", dir=config.storage_root))
    sockets = Path(tempfile.mkdtemp(prefix="v-", dir=config.socket_root))
    journal = _private_directory(session/"journals")
    temporary = _private_directory(session/"tmp")
    return ViewerCapture(sockets/"viewer.sock", journal, temporary,
                         capture_directory(config), readiness(config), config.restore_presentation_file)
