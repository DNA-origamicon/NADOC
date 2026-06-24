"""Persistent in-process oxDNA engine via oxpy — the LIVE (interactive) physical
layer (AF-21, Tier 6).

Where :mod:`backend.api.headless_oxdna_build` drives the standalone oxDNA CLI
binary one shot per stage (spawn → poll → read files), this opens oxDNA's Python
binding **oxpy** as a *persistent* manager: load topology + conf **once**, step in
bursts (``run(M)`` in a loop), mutate the uniform field's magnitude + direction
**live between bursts**, and read positions back without re-initialising the engine
(no CUDA re-init, no per-burst file round-trip for the dynamics).  It is the
substrate for real-time field steering (AF-22) and the interactive analog of the
batch field path.

**Live field control (the load-bearing mechanism).** oxDNA's MD backend fires no
per-step Python event, so the field cannot be driven from a ``subscribe`` callback;
and stock oxpy did not expose a uniform ``string``/``ConstantRateForce`` field's
magnitude or direction.  NADOC patches the oxpy bindings to expose
``BaseForce.F0`` / ``BaseForce.dir`` read-write (see
``~/oxDNA/src/oxpy/bindings_includes/Forces/BaseForce.h``); this module re-aims the
field by mutating those attributes on the field force handle **between** ``run(M)``
bursts — the engine picks up the new force on the next step with no re-init.

**Three-Layer Law.** The field is a *Physical-layer* load.  Positions read back are
display / measurement artifacts — they are NEVER written into ``Design`` topology.

**Testability.** ``import oxpy`` is LAZY (importing this module never requires the
engine), so non-oxpy environments load fine; gate real-engine tests with
``pytest.importorskip("oxpy")``.  The *stepper* is an injectable seam
(:class:`LiveOxdnaSession` takes one), so the burst / observable logic is testable
GPU-free with an in-process mock that mirrors the ``_FIELD_MOCK_OXDNA`` deflection
model (free beads shift ∝ F0 along the field; anchors held).
"""

from __future__ import annotations

import contextlib
from pathlib import Path

import numpy as np

from backend.core.models import Design
from backend.core.oxdna_health import field_equilibrium_observables


def _unit(vec) -> np.ndarray:
    v = np.asarray(vec, dtype=float)
    n = float(np.linalg.norm(v))
    if n <= 1e-9:
        raise ValueError("oxdna_live: field direction is ~zero")
    return v / n


class _OxpyStepper:
    """Drive a real :class:`oxpy.OxpyManager` over a prepared field run dir.

    The run dir must already hold ``input`` + ``topology.top`` + ``conf.dat`` +
    ``field_forces.txt`` (the uniform ``string`` field + anchor ``trap``s, written
    by :func:`backend.physics.oxdna_interface.write_field_forces`).  Used as a
    context manager so the ``oxpy.Context()`` stays open across bursts:

        with _OxpyStepper(rundir) as st:
            st.set_field(F0, [0, 0, 1]); st.run(1000)
            fmap = st.configuration(design)
    """

    def __init__(self, rundir, *, input_name: str = "input", backend: str = "CPU",
                 fallback_input: str = "input_cpu", _open_fn=None):
        self.rundir = Path(rundir)
        self.input_name = input_name
        # ``backend`` is the backend the primary ``input`` was staged with. When it
        # is "CUDA" and the open fails (no GPU init / out of memory), we retry on the
        # pre-staged CPU input (``fallback_input``) and flag it for the UI.
        self.backend = backend
        self.fallback_input = fallback_input
        self.active_backend = backend
        self.fell_back = False
        self.fallback_reason: str | None = None
        self._open_fn = _open_fn or self._oxpy_open
        self._stack: contextlib.ExitStack | None = None
        self._mgr = None
        self._field = None

    def _oxpy_open(self, input_name: str):
        """Open a real oxpy engine over ``rundir/input_name`` → ``(stack, mgr, field)``.

        On any failure the half-opened oxpy ``Context`` is torn down before
        re-raising, so a CUDA out-of-memory leaves no dangling GPU context for the
        CPU retry."""
        import oxpy  # lazy — only a real session needs the engine

        stack = contextlib.ExitStack()
        try:
            stack.enter_context(oxpy.Context())
            inp = oxpy.InputFile()
            inp.init_from_filename(str(self.rundir / input_name))
            # Absolute file paths so the run does not depend on the process cwd.
            for key, fname in (
                ("topology", "topology.top"),
                ("conf_file", "conf.dat"),
                ("external_forces_file", "field_forces.txt"),
                ("lastconf_file", "last_conf.dat"),
                ("trajectory_file", "trajectory.dat"),
                ("energy_file", "energy.dat"),
            ):
                if key in inp:
                    inp[key] = str(self.rundir / fname)
            mgr = oxpy.OxpyManager(inp)
            ci = mgr.config_info()
            # The uniform field is the single "string" force; anchors are "trap"s. A
            # run may carry NO field (anchors / hard surface / pure free dynamics
            # only), in which case there is nothing to steer — set_field then no-ops.
            strings = [f for f in ci.forces if f.type == "string"]
            field = strings[0] if strings else None
            return stack, mgr, field
        except Exception:
            stack.close()
            raise

    def __enter__(self) -> "_OxpyStepper":
        self.fell_back = False
        self.fallback_reason = None
        self.active_backend = self.backend
        try:
            self._stack, self._mgr, self._field = self._open_fn(self.input_name)
        except Exception as exc:  # noqa: BLE001 — retry CUDA→CPU, else re-raise
            cpu_input = self.rundir / self.fallback_input
            if self.backend != "CUDA" or not cpu_input.exists():
                raise
            # GPU init / out-of-memory: fall back to the pre-staged CPU input and
            # flag it so the live runner can alert the user (popup).
            self.fell_back = True
            self.fallback_reason = f"{type(exc).__name__}: {exc}"
            self.active_backend = "CPU"
            self._stack, self._mgr, self._field = self._open_fn(self.fallback_input)
        return self

    def __exit__(self, *exc) -> bool:
        self._mgr = None
        self._field = None
        if self._stack is not None:
            self._stack.close()
            self._stack = None
        return False

    def set_field(self, F0: float, direction) -> None:
        if self._field is None:
            return   # no uniform field in this run → nothing to steer
        v = _unit(direction)
        self._field.F0 = float(F0)
        self._field.dir = [float(v[0]), float(v[1]), float(v[2])]

    def run(self, steps: int) -> None:
        self._mgr.run(int(steps), print_output=False)

    def configuration(self, design: Design) -> dict:
        """Flush the current in-engine state and read it back exactly as the batch
        path does — :func:`read_configuration_full` (nm, ``(helix,bp,dir)`` keys),
        so the live and batch readout paths are byte-for-byte the same code."""
        from backend.physics.oxdna_interface import read_configuration_full

        self._mgr.print_configuration()
        return read_configuration_full(self.rundir / "last_conf.dat", design)

    def configuration_map(self, design: Design) -> dict:
        """Live-display readout WITHOUT the file round-trip: build the same
        ``(helix,bp,dir) -> {backbone_position(nm), a1, a3}`` map :meth:`configuration`
        returns, but straight from the in-engine oxpy particles
        (:func:`configuration_full_from_particles`) — no ``print_configuration`` write
        + re-parse every frame.  Verified byte-identical through the display unwrap."""
        from backend.physics.oxdna_interface import configuration_full_from_particles

        particles = self._mgr.config_info().particles()
        return configuration_full_from_particles(particles, design)

    def box_nm(self) -> np.ndarray:
        """Current simulation-box edge lengths in nm (oxDNA ``box_sides`` × length
        unit) — the per-frame minimum-image basis the display unwrap needs."""
        from backend.physics.oxdna_interface import OXDNA_LENGTH_UNIT

        return np.asarray(self._mgr.config_info().box_sides, dtype=float) * OXDNA_LENGTH_UNIT

    def snapshot_seed(self) -> Path:
        """Dump the current engine configuration to ``reconfig_seed.dat`` so a live
        recomposition can continue from the PRESENT pose (not the relaxed seed).
        Returns the seed path."""
        import shutil

        self._mgr.print_configuration()   # writes rundir/last_conf.dat
        seed = self.rundir / "reconfig_seed.dat"
        shutil.copy(self.rundir / "last_conf.dat", seed)
        return seed


class LiveOxdnaSession:
    """A persistent live field session: a field-off reference, burst-stepping, live
    field re-aiming, and equilibrium-observable readout — over an injectable
    ``stepper`` (a real :class:`_OxpyStepper`, or a GPU-free in-process mock).

    Used as a context manager.  On ``__enter__`` it opens the stepper and captures
    the field-off configuration as the reference (alignment is measured against it).
    """

    def __init__(self, design: Design, anchor_keys, *, stepper,
                 field_dir, field_oxdna: float):
        self.design = design
        self.anchor_keys = list(anchor_keys)
        self.stepper = stepper
        self.field_dir = list(field_dir)
        self.field_oxdna = float(field_oxdna)
        self._ref_map: dict | None = None

    def __enter__(self) -> "LiveOxdnaSession":
        self.stepper.__enter__()
        # Field-off reference (seed conf, before any field burst).
        self._ref_map = self.stepper.configuration(self.design)
        return self

    def __exit__(self, *exc) -> bool:
        return self.stepper.__exit__(*exc)

    def set_field(self, *, field_oxdna: float | None = None, field_dir=None) -> None:
        """Re-aim / rescale the field for subsequent bursts (the live mutation)."""
        if field_oxdna is not None:
            self.field_oxdna = float(field_oxdna)
        if field_dir is not None:
            self.field_dir = list(field_dir)
        self.stepper.set_field(self.field_oxdna, self.field_dir)

    def run(self, steps: int) -> None:
        self.stepper.run(steps)

    def snapshot_seed(self):
        """Dump the current pose for a live reconfigure (see
        :meth:`_OxpyStepper.snapshot_seed`)."""
        return self.stepper.snapshot_seed()

    def equilibrium_observables(self, *, field_dir=None) -> dict:
        """Current equilibrium observables vs the field-off reference
        (:func:`field_equilibrium_observables`).  ``field_dir`` overrides the
        projection axis (e.g. to measure deflection along a *re-aimed* field)."""
        fmap = self.stepper.configuration(self.design)
        return field_equilibrium_observables(
            fmap, self._ref_map, field_dir or self.field_dir,
            self.anchor_keys, design=self.design)
