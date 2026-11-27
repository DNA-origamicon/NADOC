"""Bounded, cancellable optional OptiX preview/export sessions. No design/session state."""
import asyncio
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import uuid

from .optix_progress import render_progress


def blender_executable():
    configured = os.environ.get("NADOC_BLENDER")
    config = Path.home() / ".local/share/nadoc/renderers/optix.json"
    if configured is None and config.is_file():
        configured = json.loads(config.read_text()).get("blender")
    if configured:
        path = shutil.which(configured)
        if path:
            return path
        raise RuntimeError("NADOC_BLENDER is unavailable; no fallback.")
    path = shutil.which("blender")
    bundled = Path.home() / ".local/share/nadoc/renderers/blender-4.5.9-linux-x64/blender"
    if path or bundled.is_file():
        return path or str(bundled)
    raise RuntimeError("OptiX runtime is not installed. Run python scripts/setup_optix_renderer.py or set NADOC_BLENDER.")


class OptixSession:
    def __init__(self):
        self.id = uuid.uuid4().hex
        parent = os.environ.get("NADOC_RENDER_SCRATCH_ROOT", os.environ.get("NADOC_TEST_SCRATCH_ROOT"))
        if parent is not None:
            parent = Path(parent).expanduser().resolve(strict=True)
        self.work = tempfile.TemporaryDirectory(prefix="nadoc-optix-", dir=parent)
        self.root = Path(self.work.name)
        self.process = None
        self.lock = asyncio.Lock()
        self.upload_lock = asyncio.Lock()
        self.touched = time.monotonic()
        self.claimed = False
        self.device = None
        self.closed = False
        self._close_task = None
        self.windows_pid = None
        self.windows = False
        self.progress = {"stage": "prepare", "label": "Starting OptiX", "fraction": None, "request_id": None}

    def _path(self, path):
        if self.windows and os.name != "nt":
            return subprocess.check_output(["wslpath", "-w", str(path)], text=True).strip()
        return str(path)

    async def start(self):
        try:
            executable = blender_executable()
            self.windows = executable.lower().endswith(".exe")
            self.process = await asyncio.create_subprocess_exec(
                executable, "--background", "--factory-startup", "--threads", "2",
                "--python", self._path(Path(__file__).with_name("optix_worker.py")), "--", self._path(self.root),
                stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                env={**os.environ, "OMP_NUM_THREADS": "2", "TMPDIR": str(self.root),
                     "BLENDER_USER_CONFIG": self._path(self.root / "config")},
                cwd=self.root, limit=1024 * 1024,
            )
            ready = await asyncio.wait_for(self._message("NADOC_READY"), 90)
            self.device = json.loads(ready)["device"]
            return self
        except BaseException:
            await self.close()
            raise

    async def _message(self, prefix):
        tail = []
        while True:
            line = await self.process.stdout.readline()
            if not line:
                raise RuntimeError("OptiX worker exited: " + " ".join(tail)[-1500:])
            text = line.decode(errors="replace").strip()
            if text.startswith("NADOC_PID "):
                self.windows_pid = int(text.removeprefix("NADOC_PID "))
            progress = render_progress(text)
            if progress:
                self.progress = {**progress, "request_id": self.progress.get("request_id")}
            tail.append(text)
            tail = tail[-8:]
            if text.startswith("NADOC_ERROR "):
                raise RuntimeError(text.removeprefix("NADOC_ERROR "))
            if text.startswith(prefix):
                return text[len(prefix):].strip()

    async def render(self, data, *, source=None):
        if self.closed or self.lock.locked():
            raise RuntimeError("OptiX session is closed or already rendering.")
        async with self.lock:
            started = time.monotonic()
            self.touched = time.monotonic()
            uploaded = source is not None
            source, target = source or self.root / "frame.json", self.root / "frame.rgba"
            try:
                if not uploaded:
                    await asyncio.to_thread(lambda: source.write_text(json.dumps(data)))
                self.process.stdin.write((json.dumps({"input": self._path(source), "output": self._path(target)}) + "\n").encode())
                await self.process.stdin.drain()
                stats = await asyncio.wait_for(self._message("NADOC_DONE"), 1800)
                self.stats = json.loads(stats) if stats else {}
                result = await asyncio.to_thread(target.read_bytes)
                self.stats["service_ms"] = (time.monotonic() - started) * 1000
                if len(result) != data["width"] * data["height"] * 16:
                    raise RuntimeError("Incomplete OptiX frame")
                self.progress = {"stage": "complete", "label": "OptiX image ready", "fraction": 1, "request_id": self.progress.get("request_id")}
                return result
            finally:
                source.unlink(missing_ok=True)
                target.unlink(missing_ok=True)
                self.touched = time.monotonic()

    async def close(self):
        if self._close_task is None:
            self._close_task = asyncio.create_task(self._close())
        await asyncio.shield(self._close_task)

    async def _close(self):
        self.closed = True
        if self.process and self.process.returncode is None:
            if self.windows and os.name != "nt" and self.windows_pid:
                # Only the exact PID announced by our owned background worker.
                killer = await asyncio.create_subprocess_exec(
                    "/mnt/c/Windows/System32/taskkill.exe", "/PID", str(self.windows_pid), "/T", "/F",
                    stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
                await killer.wait()
            else:
                self.process.terminate()
            try:
                await asyncio.wait_for(self.process.wait(), 5)
            except asyncio.TimeoutError:
                self.process.kill()
                await self.process.wait()
        self.work.cleanup()
