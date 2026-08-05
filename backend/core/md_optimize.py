"""Recommend NAMD "Advanced" settings for the current design + this machine.

Backs the Advanced card's ⚡ Optimize button.  Pure policy: it reads the design's
solvation profile and the host's GPU/CPU, then picks the settings that should give
the highest throughput WITHOUT changing the science (force field, salt, protocol
shape and stage lengths are never touched).

The one genuinely non-obvious rule it encodes — measured 2026-07-12 on an RTX 2080
Super, NAMD 3.0.2, HMR + rigidBonds all + 4 fs (see [[water-shell-carve]]):

  * A **water-shell carve and NAMD's GPU-resident mode are mutually exclusive.**  A
    carve leaves vacuum in the periodic cell and NAMD's GPU-resident tile-list build
    then under-counts exclusions and aborts at step 0 ("Low global CUDA exclusion
    count!").  Carved packages therefore run the standard CUDA-offload path
    (nonbonded + PME still on the GPU, integrator + bonded on the CPU).
  * So a carve is a **trade**, not a free win: it buys fewer atoms but costs the
    GPU-resident integrator.  Throughput goes roughly as 1/N_atoms on each path, and
    GPU-resident is ~2.6x faster PER ATOM, so a carve only pays for itself when it
    removes more than ~2.6x the atoms.  For a concave design (a bent bundle, a plate
    with a hole) it easily does; for a straight bundle — whose DNA already fills its
    own bounding box — a carve removes almost nothing and is a pure loss.

That is exactly the decision this module automates, because getting it wrong costs
either ~35 % of throughput or a crash 40 minutes into a run.
"""

from __future__ import annotations

from typing import Optional

from backend.core.md_protocols import (
    AKSIMENTIEV_STEPS_PER_CYCLE,
    _RESIDENT_MIN_ATOMS,
    _round_up_to_cycle,
)
from backend.core.md_vram import (
    CANDIDATE_SHELLS_NM,
    detect_host_ram_mb,
    detect_vram_mb,
    estimate_profile_from_design,
    estimate_total_atoms,
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
# K is machine-specific (a 3080 is ~3x these), but the RATIO — which is all the
# carve/no-carve decision depends on — is a property of NAMD, not of the card.
K_GPU_RESIDENT = 12.8 * 747_262   # ~9.6e6 atom·ns/day
K_OFFLOAD      = 18.8 * 196_606   # ~3.7e6 atom·ns/day
K_CPU          = K_OFFLOAD / 12.0  # crude: the CPU build is ~an order slower

#: A carve must remove more than this factor of atoms to beat GPU-resident (~2.6x).
CARVE_BREAKEVEN = K_GPU_RESIDENT / K_OFFLOAD
# When the full box would run OFFLOAD anyway (a system below the resident crossover), a
# carve costs no code path — but it still forces NVT and leaves vacuum in the cell, so it
# has to buy a REAL atom reduction rather than a rounding error.
CARVE_MIN_PAYOFF_NO_RESIDENT = 1.5

# Shell thickness is a PHYSICS choice, not a speed knob.  Throughput rises
# monotonically as the shell thins, so an optimiser told to maximise ns/day will
# happily shave the hydration layer down to nothing.  It must not: the shell has to
# be thick enough to (a) hydrate the duplex properly and (b) keep the minimum-image
# convention valid (2 x shell >= cutoff).  So we FIX the shell at a validated
# thickness and only ever go thinner when memory forces it — never for speed.
DEFAULT_SHELL_NM = 1.2   # 12 A — the thickness validated on 6hbx100_90deg
MIN_SHELL_NM     = 0.8   # hard floor; below this the hydration layer is not credible


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
_SMALL_SYSTEM_RESIDENT_PENALTY = 0.89   # 1.116 -> 1.266 ms/step at 32.5k atoms


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
        except Exception:                                   # noqa: BLE001
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


def choose_water_shell(
    *,
    full_atoms: int,
    shell_atoms: dict[float, int],
    atom_cap: Optional[int],
    gpu: bool,
) -> tuple[float, bool, str]:
    """Pick the water shell (nm; 0 = full box) that maximises predicted throughput.

    ``shell_atoms`` maps a candidate shell (nm) → estimated total atom count.
    ``atom_cap`` is the hard VRAM/host-RAM ceiling (None = unknown, don't bind).

    Returns ``(shell_nm, gpu_resident, reason)``.  A carve always implies
    ``gpu_resident=False`` — that incompatibility is the whole point of this module.

    The shell is NEVER thinned for throughput (see DEFAULT_SHELL_NM): the only choice
    made on speed grounds is the binary carve-vs-full-box one.
    """
    def fits(n: int) -> bool:
        return atom_cap is None or n <= atom_cap

    # The carve candidate: the validated thickness, thinned ONLY if memory forces it.
    carve_shell = 0.0
    for s in sorted((s for s in shell_atoms if s >= MIN_SHELL_NM), reverse=True):
        if s > DEFAULT_SHELL_NM:
            continue                       # never thicker than the default — no benefit
        carve_shell = s                    # the thickest shell <= default...
        if fits(shell_atoms[s]):
            break                          # ...that also fits memory
    carve_atoms = shell_atoms.get(carve_shell, full_atoms) if carve_shell else full_atoms

    full_ok = fits(full_atoms)
    # Predict the full box on the path it would ACTUALLY take: resident only where that
    # pays (below the crossover it is slower than offload, see predict_ns_per_day).
    full_resident = gpu and gpu_resident_pays(full_atoms)
    full_rate = (predict_ns_per_day(full_atoms, gpu_resident=full_resident, gpu=gpu)
                 if full_ok else -1.0)
    carve_rate = (predict_ns_per_day(carve_atoms, gpu_resident=False, gpu=gpu)
                  if carve_shell else -1.0)
    # How much a carve must buy to be worth taking.  This used to be implicit in the rate
    # comparison: with the full box on resident, `carve_rate <= full_rate` is exactly
    # `payoff <= K_GPU_RESIDENT/K_OFFLOAD`.  That equivalence BREAKS once a small full box
    # is (correctly) predicted on offload — the threshold silently collapses to 1.0x and
    # any carve, however tiny, "wins".  So state it explicitly for both regimes.
    carve_payoff = full_atoms / max(1, carve_atoms) if carve_shell else 0.0
    payoff_needed = CARVE_BREAKEVEN if full_resident else CARVE_MIN_PAYOFF_NO_RESIDENT

    if not full_ok and not fits(carve_atoms):
        return (carve_shell, False,
                f"nothing fits this machine's ~{atom_cap:,}-atom ceiling; using the "
                f"thinnest credible shell ({round(carve_shell * 10)} Å)")

    if not full_ok:
        return (carve_shell, False,
                f"the full box (~{full_atoms:,} atoms) exceeds this machine's memory, so a "
                f"{round(carve_shell * 10)} Å shell (~{carve_atoms:,} atoms) is required")

    if carve_payoff < payoff_needed or carve_rate <= full_rate:
        # Full box wins — but that does NOT automatically mean run it GPU-resident.
        if gpu and not full_resident:
            return (0.0, False,
                    f"the full box fits and a {round(carve_shell * 10)} Å carve would only "
                    f"remove {carve_payoff:.1f}x the atoms (needs >{payoff_needed:.1f}x to be "
                    f"worth forcing NVT); at ~{full_atoms:,} atoms GPU-resident is SLOWER than "
                    f"CUDA offload — below ~{_RESIDENT_MIN_ATOMS:,} both paths hit the same "
                    f"per-step floor and resident's setup is pure overhead — so the run stays "
                    f"on offload")
        return (0.0, full_resident,
                f"a {round(carve_shell * 10)} Å carve would only remove {carve_payoff:.1f}x the "
                f"atoms, which does not pay for losing GPU-resident mode "
                f"(needs >{payoff_needed:.1f}x) — this design largely fills its own bounding box")

    return (carve_shell, False,
            f"a {round(carve_shell * 10)} Å shell cuts {full_atoms:,} → {carve_atoms:,} atoms "
            f"({carve_payoff:.1f}x), which beats the full box "
            f"(needs >{payoff_needed:.1f}x)")


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
        rationale.append(f"Compute → GPU: {round(vram_mb / 1024)} GB CUDA device detected.")

    # Memory ceiling: the run must fit BOTH the card and host RAM.
    vram_cap = max_atoms_for_vram(vram_mb) if vram_mb else None
    host_cap = max_atoms_for_host_ram(host_mb) if host_mb else None
    caps = [c for c in (vram_cap, host_cap) if c is not None]
    atom_cap = min(caps) if caps else None

    profile = None
    try:
        profile = estimate_profile_from_design(
            design, padding_nm=padding_nm, atomistic_model=atomistic_model)
    except Exception as exc:                                   # noqa: BLE001
        warnings.append(f"Could not size the solvated system ({exc}) — left the water shell alone.")

    rec: dict = {
        "threads": threads,
        "compute": "cpu" if (cpu_only or vram_mb is None) else "gpu",
        "fast": True,
        "padding_nm": padding_nm,
        "minimize_steps": _round_up_to_cycle(max(AKSIMENTIEV_STEPS_PER_CYCLE, minimize_steps)),
    }
    facts: dict = {"vram_mb": vram_mb, "host_ram_mb": host_mb, "atom_cap": atom_cap,
                   "cpu_logical": (physical_cores() * 2)}

    if profile is None:
        rec["water_shell_a"] = None      # leave the user's value alone
        rec["gpu_resident"] = None
        return {"recommended": rec, "rationale": rationale, "warnings": warnings, "facts": facts}

    full_atoms = profile["dna_atoms"] + profile["full_water"] * 3 + profile["ion_atoms"]
    shell_atoms = {
        s: estimate_total_atoms(
            dna_xyz_nm=profile["dna_xyz_nm"], box_nm=profile["box_nm"],
            full_water=profile["full_water"], dna_atoms=profile["dna_atoms"],
            ion_atoms=profile["ion_atoms"], shell_nm=s,
        )
        for s in CANDIDATE_SHELLS_NM
    }

    shell_nm, gpu_resident, why = choose_water_shell(
        full_atoms=full_atoms, shell_atoms=shell_atoms, atom_cap=atom_cap, gpu=gpu)

    chosen_atoms = full_atoms if shell_nm == 0 else shell_atoms.get(shell_nm, full_atoms)
    rec["water_shell_a"] = round(shell_nm * 10, 1)
    rec["gpu_resident"] = bool(gpu_resident)

    if shell_nm == 0:
        rationale.append(f"Water shell → 0 (full box): {why}.")
    else:
        rationale.append(f"Water shell → {round(shell_nm * 10)} Å: {why}.")
        warnings.append(
            f"A {round(shell_nm * 10)} Å water shell DISABLES NAMD's GPU-resident mode — a carved "
            "cell has vacuum in it, which NAMD's GPU-resident tile-list build cannot handle "
            "(it aborts at step 0). The run stays fully CUDA-accelerated on the offload path "
            "(nonbonded + PME on the GPU) and is still the faster option here, but the barostat "
            "is off (NVT) because a piston would collapse the vacuum."
        )

    est = predict_ns_per_day(chosen_atoms, gpu_resident=gpu_resident, gpu=gpu)
    facts.update({
        "full_atoms": full_atoms,
        "chosen_atoms": chosen_atoms,
        "shell_atoms": {str(k): v for k, v in shell_atoms.items()},
        "est_ns_per_day": round(est, 1),
        "gpu_resident": bool(gpu_resident),
    })
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

    return {"recommended": rec, "rationale": rationale, "warnings": warnings, "facts": facts}
