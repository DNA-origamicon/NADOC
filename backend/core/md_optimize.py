"""Recommend NAMD execution settings without changing the physical system."""

from __future__ import annotations

from backend.core.md_protocols import (
    AKSIMENTIEV_STEPS_PER_CYCLE,
    _RESIDENT_MIN_ATOMS,
    _round_up_to_cycle,
)
from backend.core.md_vram import (
    detect_host_ram_mb,
    detect_vram_mb,
    estimate_profile_from_design,
    max_atoms_for_host_ram,
    max_atoms_for_vram,
)

# ── Measured throughput model ────────────────────────────────────────────────
# Wall-clock on a single GPU is dominated by atom count, and to a good first
# approximation throughput ~ K / N_atoms with a per-path constant K.  Both anchors
# below are real benchmarks of the SAME design (6hbx100_90deg) on an RTX 2080 Super,
# NAMD 3.0.2, HMR + rigidBonds all + 4 fs + stepspercycle 20:
#
#   GPU-resident, full solvation : 12.8 ns/day @ 747,262 atoms
#   CUDA-offload, 12 A carve     : 18.8 ns/day @ 196,606 atoms
#
# K is machine-specific (a 3080 is ~3x these); these anchors only rank execution paths.
K_GPU_RESIDENT = 12.8 * 747_262  # ~9.6e6 atom·ns/day
K_OFFLOAD = 18.8 * 196_606  # ~3.7e6 atom·ns/day
K_CPU = K_OFFLOAD / 12.0  # crude: the CPU build is ~an order slower

# GPU-resident's advantage is NOT scale-free — the 2.6x-per-atom ratio above only holds
# for large systems.  Below ~100k atoms both paths hit the same fixed per-step
# kernel-launch floor and resident's extra setup makes it a net LOSS.  Measured on an
# RTX 3080 Ti (+p16, startup excluded), offload -> resident ms/step:
#
#     32.5k relax      0.840 -> 0.862   0.97x    32.5k k=0 prod  1.116 -> 1.266  0.88x
#      111k            1.749 -> 1.544   1.13x     181k           3.338 -> 2.507  1.33x
#      770k           32.10  -> 16.16   1.99x    3.14M         125.6  -> 39.0    3.22x
#
# So the model must not promise a speed-up it cannot deliver: below the threshold the
# resident path is predicted at the OFFLOAD rate times the measured small-system penalty.
# Threshold shared with the conf writer (md_protocols._RESIDENT_MIN_ATOMS) so the
# optimiser's advice and the emitted confs can never disagree.
_SMALL_SYSTEM_RESIDENT_PENALTY = 0.89  # 1.116 -> 1.266 ms/step at 32.5k atoms


def predict_ns_per_day(n_atoms: int, *, gpu_resident: bool, gpu: bool = True) -> float:
    """Rough throughput ESTIMATE for *n_atoms* on the given path (ns/day, 4 fs).

    An extrapolation from two benchmarks of one design on one card — not a measurement of
    the caller's machine, and known to be wrong by ~2x on at least one box (exp52).  Every
    caller must label its output as an estimate, and prefer ``md_bench_probe`` when a real
    measurement for this machine exists.
    """
    if n_atoms <= 0:
        return 0.0
    if not gpu:
        return K_CPU / n_atoms
    if not gpu_resident:
        return K_OFFLOAD / n_atoms
    if n_atoms < _RESIDENT_MIN_ATOMS:
        # Small system: resident does not beat offload, it loses to it.
        return (K_OFFLOAD / n_atoms) * _SMALL_SYSTEM_RESIDENT_PENALTY
    return K_GPU_RESIDENT / n_atoms


def gpu_resident_pays(n_atoms: int, *, workspace=None, machine=None) -> bool:
    """Is GPU-resident worth using at this system size?

    A MEASUREMENT on this machine wins if one exists (md_bench_probe's cache); the
    ``_RESIDENT_MIN_ATOMS`` crossover is only the fallback for a machine nobody has probed.
    That order matters: the crossover was taken on an RTX 3080 Ti at +p16 and exp52
    measured the opposite answer on this box at 32.7k atoms — a 2x error in the direction
    that costs wall clock on every run.
    """
    m = measured_resident(n_atoms, workspace=workspace, machine=machine)
    if m and m.get("faster"):
        return m["faster"] == "on"
    return n_atoms >= _RESIDENT_MIN_ATOMS


def measured_resident(n_atoms: int, *, workspace=None, machine=None) -> dict | None:
    """This machine's own GPU-resident measurement at a comparable size, if any."""
    if workspace is None or machine is None:
        return None
    from backend.core.md_bench_probe import (  # noqa: PLC0415
        load_measurement,
        resident_verdict,
    )

    entry = load_measurement(workspace, machine, n_atoms)
    return resident_verdict(entry) if entry else None


def physical_cores() -> int:
    """Physical (not logical) cores — NAMD gains nothing from hyperthreads."""
    import os  # noqa: PLC0415

    return max(1, (os.cpu_count() or 2) // 2)


def probe_hardware(devices: str = "0") -> dict:
    """GPU / RAM / core facts for this host.  Fast (~0.5 s: one nvidia-smi call).

    Split out from :func:`recommend_advanced` so the panel can show a REAL first
    progress stage.  The expensive part of an optimize run is not this — it is
    building the design's heavy-atom model (~26 s on a 6-helix bundle), which is why
    the two are separate calls rather than a fabricated progress animation.
    """
    from backend.core.md_vram import detect_gpu_activity  # noqa: PLC0415

    cpu_only = (devices or "").strip().lower() in ("cpu", "none")
    vram_mb = None if cpu_only else detect_vram_mb(devices)
    host_mb = detect_host_ram_mb()

    name = None
    if not cpu_only:
        try:
            act = detect_gpu_activity(devices)
            name = (act or {}).get("name")
        except Exception:  # noqa: BLE001
            name = None

    vram_cap = max_atoms_for_vram(vram_mb) if vram_mb else None
    host_cap = max_atoms_for_host_ram(host_mb) if host_mb else None
    caps = [c for c in (vram_cap, host_cap) if c is not None]

    cores = physical_cores()
    bits = []
    if name:
        bits.append(name)
    if vram_mb:
        bits.append(f"{round(vram_mb / 1024)} GB VRAM")
    if host_mb:
        bits.append(f"{round(host_mb / 1024)} GB RAM")
    bits.append(f"{cores} cores")

    return {
        "gpu_name": name,
        "vram_mb": vram_mb,
        "host_ram_mb": host_mb,
        "physical_cores": cores,
        "atom_cap": min(caps) if caps else None,
        "summary": " · ".join(bits),
    }


def recommend_advanced(
    design,
    *,
    devices: str = "0",
    padding_nm: float = 1.2,
    minimize_steps: int = 10_000,
    atomistic_model=None,
) -> dict:
    """Recommend Advanced-card settings for *design* on THIS machine.

    Never raises: on any failure it returns the caller's inputs unchanged with an
    explanatory warning, so the button can't wedge the panel.
    """
    warnings: list[str] = []
    rationale: list[str] = []

    cpu_only = (devices or "").strip().lower() in ("cpu", "none")
    vram_mb = None if cpu_only else detect_vram_mb(devices)
    gpu = not cpu_only and vram_mb is not None
    host_mb = detect_host_ram_mb()

    threads = physical_cores()
    rationale.append(
        f"Threads → {threads}: one NAMD thread per physical core "
        f"(hyperthreads do not speed up MD)."
    )

    if cpu_only:
        rationale.append("Compute → CPU: kept, as requested.")
    elif vram_mb is None:
        warnings.append(
            "No CUDA GPU detected (nvidia-smi unavailable) — recommending the CPU build. "
            "If you do have a GPU, leave Compute on GPU and ignore this."
        )
        rationale.append("Compute → CPU: no GPU detected.")
    else:
        rationale.append(
            f"Compute → GPU: {round(vram_mb / 1024)} GB CUDA device detected."
        )

    # Memory ceiling: the run must fit BOTH the card and host RAM.
    vram_cap = max_atoms_for_vram(vram_mb) if vram_mb else None
    host_cap = max_atoms_for_host_ram(host_mb) if host_mb else None
    caps = [c for c in (vram_cap, host_cap) if c is not None]
    atom_cap = min(caps) if caps else None

    profile = None
    try:
        profile = estimate_profile_from_design(
            design, padding_nm=padding_nm, atomistic_model=atomistic_model
        )
    except Exception as exc:  # noqa: BLE001
        warnings.append(f"Could not size the fully solvated system ({exc}).")

    rec: dict = {
        "threads": threads,
        "compute": "cpu" if (cpu_only or vram_mb is None) else "gpu",
        "fast": True,
        "padding_nm": padding_nm,
        "minimize_steps": _round_up_to_cycle(
            max(AKSIMENTIEV_STEPS_PER_CYCLE, minimize_steps)
        ),
    }
    facts: dict = {
        "vram_mb": vram_mb,
        "host_ram_mb": host_mb,
        "atom_cap": atom_cap,
        "cpu_logical": (physical_cores() * 2),
    }

    if profile is None:
        rec["gpu_resident"] = None
        return {
            "recommended": rec,
            "rationale": rationale,
            "warnings": warnings,
            "facts": facts,
        }

    full_atoms = profile["dna_atoms"] + profile["full_water"] * 3 + profile["ion_atoms"]
    chosen_atoms = full_atoms
    gpu_resident = bool(gpu and gpu_resident_pays(full_atoms))
    rec["gpu_resident"] = bool(gpu_resident)
    rationale.append("The complete periodic water box is retained.")

    est = predict_ns_per_day(chosen_atoms, gpu_resident=gpu_resident, gpu=gpu)
    facts.update(
        {
            "full_atoms": full_atoms,
            "chosen_atoms": chosen_atoms,
            "est_ns_per_day": round(est, 1),
            "gpu_resident": bool(gpu_resident),
        }
    )
    rationale.append(
        f"Estimated throughput ≈ {est:.0f} ns/day at ~{chosen_atoms:,} atoms "
        f"({'GPU-resident' if gpu_resident else 'CUDA offload'}, 4 fs)."
    )

    if atom_cap is not None and chosen_atoms > atom_cap:
        warnings.append(
            f"Even the recommended system (~{chosen_atoms:,} atoms) may exceed this machine's "
            f"~{atom_cap:,}-atom memory ceiling. It may still run — but expect an out-of-memory "
            "abort. Consider a smaller design or the CPU build."
        )

    return {
        "recommended": rec,
        "rationale": rationale,
        "warnings": warnings,
        "facts": facts,
    }
