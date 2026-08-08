"""Ephemeral in-process oxpy LIVE field sessions — display-only, nothing persisted.

Where ``oxdna_runner`` manages persisted :class:`~backend.core.oxdna_job.OxdnaJob`
runs (a job dir on disk, stored frames, a resumable stage machine), a LIVE session
is the opposite: it opens a *persistent* oxpy engine
(:class:`~backend.physics.oxdna_live.LiveOxdnaSession`) over a **temp** run dir
seeded from a completed relaxed job, burst-steps it in a background thread, and
serves the *current* configuration for display while the uniform field is re-aimed
**live** between bursts.  Nothing is persisted — there is no ``OxdnaJob``, no stored
frames, only a temp rundir that is removed on stop.

**Three-Layer Law (load-bearing).** The field is a *Physical-layer* load; the
positions captured each burst are display artifacts — they are NEVER written into
``Design`` topology.

**Testability.** The worker loop is independent of oxpy: it drives an injected
``session`` (a :class:`LiveOxdnaSession`-like context manager exposing
``set_field`` / ``run``) and an injected ``frame_builder`` (``session → positions``),
so the burst / pending-field / latest-frame logic is unit-testable GPU-free with a
fake session + fake builder.  The route module (``routes_oxdna_live``) wires the
real oxpy ones.
"""

from __future__ import annotations

import threading
import uuid
from pathlib import Path
from shutil import rmtree


# ── In-memory session registry (single active session policy) ─────────────────
_SESSIONS: dict[str, "LiveSession"] = {}
_REG_LOCK = threading.Lock()


def new_session_id() -> str:
    return uuid.uuid4().hex[:12]


def register(session: "LiveSession") -> None:
    with _REG_LOCK:
        _SESSIONS[session.session_id] = session


def get_session(session_id: str) -> "LiveSession | None":
    with _REG_LOCK:
        return _SESSIONS.get(session_id)


def stop_session(session_id: str) -> bool:
    """Stop + remove ONE session (teardown its thread + temp rundir). Returns
    whether a session was found."""
    with _REG_LOCK:
        session = _SESSIONS.pop(session_id, None)
    if session is None:
        return False
    session.stop()
    return True


def stop_all() -> int:
    """Stop + remove EVERY registered session.  Called before starting a new one
    (a single in-process oxpy engine at a time) and on teardown.  Returns the count
    stopped."""
    with _REG_LOCK:
        items = list(_SESSIONS.values())
        _SESSIONS.clear()
    for s in items:
        s.stop()
    return len(items)


class LiveSession:
    """A live, re-aimable oxpy field run on a background thread.

    Drives an injected ``session`` (a :class:`~backend.physics.oxdna_live.LiveOxdnaSession`-
    like context manager) in bursts of ``burst_steps``, capturing the current
    configuration after each burst via ``frame_builder(session) -> list[positions]``.
    The uniform field can be re-aimed at any time with :meth:`set_field`; the new
    magnitude / direction is applied at the start of the next burst (the live
    steering).  Read the latest captured frame with :meth:`frame`.
    """

    def __init__(
        self,
        session_id: str,
        session,
        *,
        frame_builder,
        field_oxdna: float,
        field_dir,
        burst_steps: int = 500,
        rundir: Path | None = None,
        design=None,
        design_ref=None,
    ):
        self.session_id = session_id
        self._session = session
        self._frame_builder = frame_builder
        self._burst = max(1, int(burst_steps))
        self._rundir = Path(rundir) if rundir is not None else None
        # Domain handles a live RECONFIGURE needs (re-stage the rundir for a new
        # element composition); the route sets them at start.  Left None for the
        # GPU-free fake-engine tests, which inject their own rebuild callable.
        self.design = design
        self.design_ref = Path(design_ref) if design_ref is not None else None

        self._lock = threading.Lock()
        self._pending: tuple | None = None  # (field_oxdna|None, dir|None)
        self._pending_reconfig: tuple | None = None  # (rebuild_fn, field_oxdna, dir)
        self._latest: list | None = None  # last captured positions payload
        self._field_oxdna = float(field_oxdna)
        self._field_dir = list(field_dir)
        self._n_bursts = 0
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.status = "starting"
        self.error: str | None = None

    # ── Lifecycle ─────────────────────────────────────────────────────────────
    def start(self) -> None:
        self._thread = threading.Thread(
            target=self._run, name=f"oxdna-live-{self.session_id}", daemon=True
        )
        self._thread.start()

    def _run(self) -> None:
        # Manual enter/exit (not `with self._session:`) so a live RECONFIGURE can swap
        # self._session mid-loop and the finally still tears down whatever engine is
        # current — `with` would bind the ORIGINAL session and double-exit it.
        try:
            self._session.__enter__()
            try:
                # Field on at the requested magnitude + direction, then a first
                # capture so the display has a frame before the first burst lands.
                self._session.set_field(
                    field_oxdna=self._field_oxdna, field_dir=self._field_dir
                )
                self.status = "running"
                self._capture_frame()
                while not self._stop.is_set():
                    self._apply_pending_reconfig()
                    self._apply_pending_field()
                    self._session.run(self._burst)
                    self._n_bursts += 1
                    self._capture_frame()
            finally:
                self._session.__exit__(None, None, None)
        except Exception as exc:  # noqa: BLE001 — surfaced via /frame, not swallowed
            self.error = f"{type(exc).__name__}: {exc}"
            self.status = "error"
        finally:
            if self.status != "error":
                self.status = "stopped"

    def _apply_pending_reconfig(self) -> None:
        """Apply a queued live recomposition (floor / E-field / anchors toggled
        mid-run).  Dumps the CURRENT engine state as the new seed, tears down the old
        engine, and rebuilds it over that seed with the new forces — so the structure
        continues SEAMLESSLY from where it is rather than resetting to the relaxed
        pose.  ``rebuild_fn() -> (new_session, new_frame_builder)`` is supplied by the
        route (it re-stages the rundir + constructs the fresh engine)."""
        with self._lock:
            rc = self._pending_reconfig
            self._pending_reconfig = None
        if rc is None:
            return
        rebuild_fn, f_oxdna, f_dir = rc
        # Snapshot the present pose while the old engine is still open, then close it,
        # build the new engine over that seed, and continue.
        self._session.snapshot_seed()
        self._session.__exit__(None, None, None)
        new_session, new_builder = rebuild_fn()
        self._session = new_session
        self._frame_builder = new_builder
        self._session.__enter__()
        self._session.set_field(field_oxdna=f_oxdna, field_dir=f_dir)
        with self._lock:
            self._field_oxdna = float(f_oxdna)
            self._field_dir = list(f_dir)
        self._capture_frame()

    def _apply_pending_field(self) -> None:
        with self._lock:
            pend = self._pending
            self._pending = None
        if pend is None:
            return
        f_oxdna, f_dir = pend
        kw = {}
        if f_oxdna is not None:
            kw["field_oxdna"] = f_oxdna
        if f_dir is not None:
            kw["field_dir"] = f_dir
        if kw:
            self._session.set_field(**kw)
            with self._lock:
                if f_oxdna is not None:
                    self._field_oxdna = f_oxdna
                if f_dir is not None:
                    self._field_dir = list(f_dir)

    def _capture_frame(self) -> None:
        try:
            positions = self._frame_builder(self._session)
        except Exception as exc:  # noqa: BLE001 — a bad read shouldn't kill the loop
            self.error = f"frame: {type(exc).__name__}: {exc}"
            return
        with self._lock:
            self._latest = positions

    # ── Control / readout ─────────────────────────────────────────────────────
    def set_field(self, *, field_oxdna: float | None = None, field_dir=None) -> None:
        """Queue a live field re-aim / rescale; applied before the next burst."""
        with self._lock:
            self._pending = (
                None if field_oxdna is None else float(field_oxdna),
                None if field_dir is None else list(field_dir),
            )

    def _backend_info(self) -> dict:
        """Active backend + GPU→CPU fallback flags, read from the session's stepper
        (a real :class:`~backend.physics.oxdna_live._OxpyStepper`).  Absent for the
        GPU-free fake sessions used in unit tests → empty dict."""
        stepper = getattr(self._session, "stepper", None)
        if stepper is None:
            return {}
        return {
            "backend": getattr(stepper, "active_backend", None),
            "backend_fell_back": bool(getattr(stepper, "fell_back", False)),
            "backend_reason": getattr(stepper, "fallback_reason", None),
        }

    def reconfigure(
        self, rebuild_fn, *, field_oxdna: float = 0.0, field_dir=None
    ) -> None:
        """Queue a live recomposition (the element set changed — floor/field/anchors
        toggled).  ``rebuild_fn()`` (built by the route) returns the
        ``(new_session, new_frame_builder)`` for the new composition, seeded from the
        pose the worker snapshots; applied before the next burst."""
        with self._lock:
            self._pending_reconfig = (
                rebuild_fn,
                float(field_oxdna),
                list(field_dir) if field_dir is not None else list(self._field_dir),
            )

    @property
    def rundir(self) -> "Path | None":
        return self._rundir

    @property
    def burst_steps(self) -> int:
        return self._burst

    def frame(self) -> dict:
        """The latest captured configuration as a display payload (or not-ready)."""
        with self._lock:
            latest = self._latest
            return {
                "ready": latest is not None,
                "positions": latest or [],
                "n_positions": len(latest) if latest else 0,
                "n_bursts": self._n_bursts,
                "status": self.status,
                "error": self.error,
                **self._backend_info(),
            }

    def stop(self) -> None:
        """Signal the loop to stop, join the thread, and remove the temp rundir."""
        self._stop.set()
        t = self._thread
        if t is not None:
            t.join(timeout=10.0)
        if self._rundir is not None:
            rmtree(self._rundir, ignore_errors=True)
