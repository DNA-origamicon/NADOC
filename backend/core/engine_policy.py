"""Automatic simulation-engine selection policy (pure decision logic).

Given what's in the design (proteins?) and the machine's live resources (GPU busy?
free CPU cores?), decide which engine a novice should run — so pressing one button
gives near-optimal speed with zero understanding.  The governing facts (benchmarked
2026-07-10, see ``project_lammps_oxdna``):

* **oxDNA-CUDA is far faster than LAMMPS-CPU whenever the GPU is free** — 13× on a
  small design (1328 nt), 47× on a large one (14172 nt); the gap grows with size.
  So oxDNA-GPU is the default, and LAMMPS-CPU is a *fallback*, not a co-equal.
* **LAMMPS can't simulate proteins** (no DNANM/ANM) → any design with a visible
  protein must run on oxDNA.
* LAMMPS-CPU is worth choosing only when the GPU is *busy* (mostly for small designs
  / long GPU queues) or a design is too big for VRAM.

This module is PURE (no I/O, no nvidia-smi) so it is trivially unit-tested; the route
(:mod:`backend.api.routes_simulate`) gathers the live sensor values and calls in.
"""

from __future__ import annotations

# Benchmarked oxDNA-GPU ÷ LAMMPS-CPU-16 wall-time ratios at matched dt=0.005 (GPU idle).
# Re-benchmark → edit these two anchors only.
_SMALL_NT, _SMALL_FACTOR = 1328, 13.0
_LARGE_NT, _LARGE_FACTOR = 14172, 47.0


def cpu_slowdown_factor(n_nucleotides: int) -> float:
    """How many times slower LAMMPS-CPU is than oxDNA-GPU for a design of this size.

    Linearly interpolates the two benchmark anchors and clamps outside them (tiny
    designs stay at ~13×, huge ones at ~47×).  Used to tell the user "~N× slower on
    CPU" before they commit to a GPU-busy fallback run.
    """
    n = max(0, int(n_nucleotides))
    if n <= _SMALL_NT:
        return _SMALL_FACTOR
    if n >= _LARGE_NT:
        return _LARGE_FACTOR
    frac = (n - _SMALL_NT) / (_LARGE_NT - _SMALL_NT)
    return _SMALL_FACTOR + frac * (_LARGE_FACTOR - _SMALL_FACTOR)


def recommend_engine(
    *,
    has_proteins: bool,
    gpu_busy: bool,
    gpu_hog_name: str | None = None,
    gpu_eta_seconds: float | None = None,
    n_nucleotides: int = 0,
    free_cores: int = 1,
) -> dict:
    """Pick the engine + backend a novice should run, with a one-line ``reason``.

    Returns ``{engine, backend, reason, cpu_slowdown_factor, needs_dialog}``:
    ``engine`` is ``"oxdna"`` or ``"lammps"``; ``backend`` is ``"CUDA"`` or ``"CPU"``;
    ``needs_dialog`` flags that a GPU-busy confirmation should be shown before launch.

    Policy:
    * proteins → oxDNA/CUDA (LAMMPS can't do proteins); dialog only if the GPU is busy.
    * no proteins, GPU free → oxDNA/CUDA (fastest).
    * no proteins, GPU busy → LAMMPS/CPU (parallel), with the ~N× slowdown surfaced.
    """
    factor = cpu_slowdown_factor(n_nucleotides)
    hog = gpu_hog_name or "another job"

    if has_proteins:
        reason = "Proteins present — only oxDNA supports protein (ANM) hybrids."
        if gpu_busy:
            reason = (f"Proteins present — must use oxDNA (LAMMPS can't do proteins) — "
                      f"but the GPU is busy with {hog}.")
        return {"engine": "oxdna", "backend": "CUDA", "reason": reason,
                "cpu_slowdown_factor": factor, "needs_dialog": gpu_busy}

    if not gpu_busy:
        return {"engine": "oxdna", "backend": "CUDA",
                "reason": "GPU free — oxDNA on GPU is fastest here.",
                "cpu_slowdown_factor": factor, "needs_dialog": False}

    return {"engine": "lammps", "backend": "CPU",
            "reason": (f"GPU busy with {hog} — running on CPU (LAMMPS, {free_cores} cores) "
                       f"is ~{factor:.0f}× slower but doesn't wait for the GPU."),
            "cpu_slowdown_factor": factor, "needs_dialog": True}
