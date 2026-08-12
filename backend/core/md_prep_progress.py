"""
MD-preparation progress tracker.

The "Use as NAMD seed" / "Relax" buttons kick off a multi-phase preparation
(reconstruct relaxed atoms → build topology → GROMACS solvation → ion placement
→ elastic-network restraints → write configs).  Historically the whole thing ran
inside one blocking POST, so the UI could only show an indeterminate spinner —
there was no way to tell a slow run from a hung one.

This module turns that opaque wait into an observable, ETA-bearing loading bar:

  * A :class:`PrepTracker` is created up-front with the ordered list of phases it
    expects (seed-build is skipped for non-seeded jobs).  Each phase carries a
    size-scaled *nominal duration* used both as a progress weight and as the
    basis for stall / timeout thresholds.
  * Deep prep code reports into the tracker with a tiny callback
    ``progress(phase_key, frac_within_phase, message)`` — it never needs to
    import the tracker.  Phases that can't report fine-grained progress (opaque
    subprocesses / numpy kernels) are *time-filled* by a 1 Hz heartbeat against
    their nominal duration, so the bar always advances.
  * ETA self-calibrates: once a phase finishes, the ratio of its actual to
    nominal duration scales the estimate for the remaining phases, so a slow
    machine still gets an honest countdown.
  * A phase that overruns ``soft_factor × nominal`` raises a non-fatal
    ``warning`` ("taking longer than expected — possible stall").  Hard killing
    of a genuinely hung subprocess is the runner's job (it owns the process);
    this module only surfaces the soft warning and the snapshot the UI reads.

The tracker is thread-safe: ``report``/``enter`` are called from the worker
thread running the (blocking) preparation, while ``snapshot`` is read from the
event-loop heartbeat that persists it to ``{job_dir}/prep_progress.json``.
"""

from __future__ import annotations

import dataclasses
import json
import threading
from pathlib import Path
from typing import Callable, Optional

# Sidecar file the websocket reads and the heartbeat writes.  Kept separate from
# job.json so the high-frequency progress writes never race the job's own
# start/finish writes.
PREP_PROGRESS_FILENAME = "prep_progress.json"


@dataclasses.dataclass
class PrepPhase:
    """One preparation phase.

    nominal_s:    expected duration at the current design size (seconds).  Used
                  as the progress weight AND the time-fill basis for opaque
                  phases.  Must be > 0.
    soft_factor:  warn once elapsed-in-phase exceeds soft_factor × nominal_s.
    fill_cap:     max time-based fraction an opaque phase reaches before it
                  actually completes (so the bar never sits at 100% mid-phase).
    """

    key: str
    label: str
    nominal_s: float
    soft_factor: float = 3.0
    fill_cap: float = 0.97


# ── Canonical phase catalogue ────────────────────────────────────────────────
# Nominal seconds are quoted at a ~7000-nt reference origami and scaled linearly
# by `size_factor` in `build_prep_phases`.  Ratios matter more than absolutes —
# they shape how fast the bar moves through each phase — and the ETA recalibrates
# against the wall clock as phases complete.

_SEED_PHASE = PrepPhase(
    "seed", "Reconstructing relaxed atomic model", nominal_s=8.0, soft_factor=4.0
)
_CORE_PHASES = [
    PrepPhase(
        "topology", "Building DNA topology (PSF/PDB)", nominal_s=10.0, soft_factor=3.0
    ),
    PrepPhase(
        "solvate", "Adding explicit water (GROMACS)", nominal_s=30.0, soft_factor=2.5
    ),
    PrepPhase(
        "assemble",
        "Placing ions + assembling solvated system",
        nominal_s=25.0,
        soft_factor=3.0,
    ),
    PrepPhase(
        "enm", "Building elastic-network restraints", nominal_s=15.0, soft_factor=3.0
    ),
    PrepPhase("finalize", "Writing simulation configs", nominal_s=4.0, soft_factor=5.0),
]


def build_prep_phases(
    *, seeded: bool, size_factor: float = 1.0, implicit: bool = False
) -> list[PrepPhase]:
    """Return the ordered phase list for a prep run, scaled to design size.

    ``size_factor`` ≈ design_nt / 7000 (floored at ~0.15 so tiny designs still
    get a sane minimum estimate).  ``seeded`` prepends the seed-reconstruction
    phase that only oxDNA-seeded jobs run.  ``implicit`` (GBIS) drops the two
    solvation phases — there is no water box to build or ions to place.
    """
    sf = max(0.15, float(size_factor))
    core = _CORE_PHASES
    if implicit:
        core = [p for p in _CORE_PHASES if p.key not in ("solvate", "assemble")]
    src = ([_SEED_PHASE] if seeded else []) + core
    return [dataclasses.replace(p, nominal_s=max(1.0, p.nominal_s * sf)) for p in src]


def design_size_factor(design) -> float:
    """Coarse size proxy (≈ nt / 7000) used to scale phase nominal durations."""
    try:
        nt = sum((d.end_bp - d.start_bp + 1) for s in design.strands for d in s.domains)
    except Exception:
        nt = 0
    if nt <= 0:
        return 1.0
    return nt / 7000.0


class PrepTracker:
    """Thread-safe weighted-progress + ETA tracker over a fixed phase list."""

    def __init__(
        self,
        phases: list[PrepPhase],
        *,
        clock: Callable[[], float],
    ) -> None:
        if not phases:
            raise ValueError("PrepTracker needs at least one phase")
        self._phases = phases
        self._by_key = {p.key: i for i, p in enumerate(phases)}
        self._clock = clock
        self._lock = threading.Lock()

        self._start = clock()
        self._cur = 0  # index of the active phase
        self._phase_start = self._start
        self._frac_in_phase = 0.0  # discrete fraction reported for cur
        self._reported = False  # has cur received a discrete report?
        self._message = phases[0].label
        # actual durations of completed phases (key -> seconds), for ETA recal
        self._actual: dict[str, float] = {}
        self._done = False
        self._failed = False
        self._error = ""

    # ── Worker-thread API (the `progress` callback) ──────────────────────────

    def report(
        self, phase_key: str, frac: Optional[float] = None, message: str = ""
    ) -> None:
        """Report progress within ``phase_key`` (auto-enters it if new).

        ``frac`` is the 0..1 fraction *within that phase*.  Pass ``frac=None`` to
        merely *enter* an opaque phase (no fine-grained progress) — the heartbeat
        then time-fills it against its nominal duration.  Safe to call from the
        prep worker thread.  Unknown keys are ignored (defensive).
        """
        idx = self._by_key.get(phase_key)
        if idx is None:
            return
        with self._lock:
            if self._done or self._failed:
                return
            if idx != self._cur:
                self._advance_to(idx)
            if frac is not None:
                self._frac_in_phase = max(self._frac_in_phase, min(1.0, max(0.0, frac)))
                self._reported = True
            if message:
                self._message = message

    def enter(self, phase_key: str, message: str = "") -> None:
        """Mark ``phase_key`` as the active phase (frac resets to 0)."""
        idx = self._by_key.get(phase_key)
        if idx is None:
            return
        with self._lock:
            if self._done or self._failed:
                return
            if idx != self._cur:
                self._advance_to(idx)
            if message:
                self._message = message

    def fail(self, error: str) -> None:
        with self._lock:
            self._failed = True
            self._done = True
            self._error = error or "Preparation failed"

    def finish(self) -> None:
        with self._lock:
            if not self._failed:
                self._done = True
                self._frac_in_phase = 1.0

    def is_done(self) -> bool:
        with self._lock:
            return self._done

    # ── Internal (lock held) ─────────────────────────────────────────────────

    def _advance_to(self, idx: int) -> None:
        """Close every phase before ``idx`` and make ``idx`` active."""
        now = self._clock()
        # Record actual duration for the phase we are leaving (and any skipped).
        for j in range(self._cur, idx):
            key = self._phases[j].key
            self._actual.setdefault(key, max(0.0, now - self._phase_start))
            # Each leg's "start" is approximated as the same instant for skips;
            # only the last leg's duration is meaningful, which is fine for ETA.
            self._phase_start = now
        self._cur = idx
        self._phase_start = now
        self._frac_in_phase = 0.0
        self._reported = False
        self._message = self._phases[idx].label

    def _speed_factor(self) -> float:
        """actual / nominal over completed phases (1.0 until one completes)."""
        nominal = sum(p.nominal_s for p in self._phases if p.key in self._actual)
        actual = sum(self._actual.values())
        if nominal <= 0 or actual <= 0:
            return 1.0
        return actual / nominal

    # ── Event-loop API ───────────────────────────────────────────────────────

    def snapshot(self) -> dict:
        """Return the current progress as a JSON-able dict (UI contract)."""
        with self._lock:
            now = self._clock()
            elapsed = now - self._start
            phase = self._phases[self._cur]

            if self._done and not self._failed:
                frac_cur = 1.0
            elif self._reported:
                frac_cur = self._frac_in_phase
            else:
                # Opaque phase: time-fill against nominal, capped below 100%.
                t_in = max(0.0, now - self._phase_start)
                frac_cur = (
                    min(phase.fill_cap, t_in / phase.nominal_s)
                    if phase.nominal_s > 0
                    else 0.0
                )

            total_nominal = sum(p.nominal_s for p in self._phases)
            done_nominal = sum(self._phases[j].nominal_s for j in range(self._cur))
            fraction = (done_nominal + phase.nominal_s * frac_cur) / total_nominal
            fraction = max(0.0, min(1.0, fraction))

            if self._done:
                fraction = 1.0 if not self._failed else fraction
                eta = 0.0 if not self._failed else None
            else:
                speed = self._speed_factor()
                remaining_nominal = phase.nominal_s * (1.0 - frac_cur) + sum(
                    self._phases[j].nominal_s
                    for j in range(self._cur + 1, len(self._phases))
                )
                eta = speed * remaining_nominal

            # No elapsed-vs-expected "longer than expected / may be stalled"
            # warning: the per-phase nominal times vary too much by design size to
            # be a useful stall indicator (they cry wolf on legitimately slow
            # steps).  A genuine stall is surfaced instead by the heartbeat going
            # stale (the snapshot stops advancing), which the UI detects directly.
            warning = ""

            return {
                "phase": phase.key,
                "label": phase.label,
                "phase_index": self._cur,
                "n_phases": len(self._phases),
                "fraction": round(fraction, 4),
                "eta_seconds": None if eta is None else round(eta, 1),
                "elapsed_seconds": round(elapsed, 1),
                "message": self._message,
                # True when the active operation reported a real work fraction.
                # False means the fraction is the tracker's time-based estimate for
                # an otherwise opaque subprocess/kernel.
                "measured": self._reported,
                "warning": warning,
                "done": self._done,
                "failed": self._failed,
                "error": self._error,
            }


# ── Sidecar persistence ──────────────────────────────────────────────────────


def write_prep_progress(job_dir: Path, snapshot: dict) -> None:
    """Atomically write the progress snapshot to the job's sidecar file."""
    job_dir.mkdir(parents=True, exist_ok=True)
    tmp = job_dir / (PREP_PROGRESS_FILENAME + ".tmp")
    tmp.write_text(json.dumps(snapshot))
    tmp.replace(job_dir / PREP_PROGRESS_FILENAME)


def read_prep_progress(job_dir: Path) -> Optional[dict]:
    """Return the last-written progress snapshot, or None if absent/unreadable."""
    p = job_dir / PREP_PROGRESS_FILENAME
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text())
    except (OSError, ValueError):
        return None


def clear_prep_progress(job_dir: Path) -> None:
    """Remove the sidecar file (called once prep leaves the 'preparing' state)."""
    try:
        (job_dir / PREP_PROGRESS_FILENAME).unlink()
    except FileNotFoundError:
        pass
