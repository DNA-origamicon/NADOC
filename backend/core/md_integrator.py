"""md_integrator.py — the three integrator axes, resolved in ONE place.

A NAMD run's stability is set by three settings that used to be a single dial in this
codebase: the **timestep**, whether bonds to hydrogen are **constrained** (``rigidBonds``),
and whether the PSF carries **repartitioned hydrogen masses** (HMR).  Every emitter derived
the other two from the timestep — ``_segment_conf`` wrote ``"none" if spec.soft else "all"``
and picked the HMR PSF from ``fast``; ``build_production_conf`` branched on ``ts`` alone —
so the off-diagonal combinations were unreachable and had never been measured.

exp51 measured them (``experiments/exp51_integrator_factorial``, 2026-08-05, one solvated
2hb_1xT system, 12 cells differing only in these three settings, GPU-resident held off):

===========================  ===============================================================
4 fs, rigid, standard masses **RATTLE constraint failure at step 4,200** (16.8 ps).  HMR is
                             genuinely load-bearing at 4 fs.
4 fs, flexible               dies at step 0 on the velocity limit, with or without HMR.
2 fs, flexible               survives, but conserves energy ~5x worse than 2 fs rigid.
1 fs, rigid                  stable; drift indistinguishable from 1 fs flexible.  The
                             1 fs <-> flexible coupling the code enforced is a CONVENTION.
HMR below 4 fs               3.5x worse energy conservation at 2 fs rigid, 7x at 2 fs
                             flexible, 35x at 1 fs flexible — and the drift turns positive.
                             Repartitioning subtracts mass from the parent heavy atom, so
                             heavy-atom librations speed up while the X-H stretch that
                             ``rigidBonds all`` already froze gets slower.  Only the harm
                             remains.
===========================  ===============================================================

Which matches the literature the diagonals came from: Ryckaert/Ciccotti/Berendsen 1977 for
constrained-bond 2 fs, Feenstra 1999 and Hopkins/Le Grand/Walker/Roitberg 2015 for HMR 4 fs.

Nothing here BLOCKS a combination.  The warnings are stated and the run proceeds — the
audit that produced this module was only possible because someone could run the
combinations the code called impossible.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

#: Bonds to hydrogen are constrained ("all") or free ("none").  NAMD also accepts "water",
#: which nothing in this codebase emits.
RIGID_ALL = "all"
RIGID_NONE = "none"

#: Above this timestep, unconstrained X-H stretches are undersampled.
_RIGID_REQUIRED_ABOVE_FS = 1.0
#: At and above this timestep, HMR is required for the constrained system to be stable.
_HMR_REQUIRED_AT_FS = 4.0


@dataclass(frozen=True)
class IntegratorChoice:
    """The three axes, resolved, plus whether each was chosen or defaulted."""

    timestep_fs: float
    rigid_bonds: str
    hmr: bool
    rigid_explicit: bool
    hmr_explicit: bool

    @property
    def rigid(self) -> bool:
        return self.rigid_bonds == RIGID_ALL

    def as_dict(self) -> dict:
        return {"timestep_fs": self.timestep_fs, "rigid_bonds": self.rigid_bonds,
                "hmr": self.hmr, "rigid_explicit": self.rigid_explicit,
                "hmr_explicit": self.hmr_explicit}


def auto_rigid_bonds(timestep_fs: float) -> str:
    """The constraint setting a timestep implies when the user has not chosen one.

    1 fs keeps the historical conservative-reference default of flexible bonds (exp51 shows
    ``all`` is equally stable there, so this is a default, not a requirement); everything
    above needs the X-H stretch frozen.
    """
    return RIGID_NONE if float(timestep_fs) <= _RIGID_REQUIRED_ABOVE_FS else RIGID_ALL


def auto_hmr(timestep_fs: float) -> bool:
    """Whether to repartition hydrogen masses when the user has not chosen.

    On only at 4 fs, where exp51 measured it to be load-bearing.  Below that it is a
    measured LOSS in energy conservation, so it is never defaulted on.
    """
    return float(timestep_fs) >= _HMR_REQUIRED_AT_FS


def resolve_integrator(timestep_fs: float, rigid_bonds: Optional[str] = None,
                       hmr: Optional[bool] = None) -> IntegratorChoice:
    """Resolve the three axes, filling ``None`` from the timestep.

    ``rigid_bonds`` accepts "all"/"none" (case-insensitive) or None for auto; ``hmr``
    accepts a bool or None for auto.  An unrecognised ``rigid_bonds`` falls back to auto
    rather than raising: this runs inside conf emission, and a typo must not take a job
    down at write time when the request validator already rejects bad values.
    """
    dt = float(timestep_fs)
    want = str(rigid_bonds).strip().lower() if rigid_bonds is not None else None
    if want not in (RIGID_ALL, RIGID_NONE):
        want = None
    return IntegratorChoice(
        timestep_fs=dt,
        rigid_bonds=want if want is not None else auto_rigid_bonds(dt),
        hmr=bool(hmr) if hmr is not None else auto_hmr(dt),
        rigid_explicit=want is not None,
        hmr_explicit=hmr is not None,
    )


def integrator_warnings(choice: IntegratorChoice, *, scope: str = "relaxation") -> list[dict]:
    """Every measured objection to this combination, as plan-condition dicts.

    ``scope`` is "relaxation" or "production" and only shapes the wording — the physics is
    the same either way.  ``source`` names the request field the warning belongs to, which
    is what lets the wizard render it against that specific control instead of only in a
    list underneath.

    Deliberately WARNINGS, never blocking: see the module docstring.
    """
    dt = choice.timestep_fs
    where = "production run" if scope == "production" else "relaxation ladder"
    field = "production" if scope == "production" else "relax"
    out: list[dict] = []

    if dt >= _HMR_REQUIRED_AT_FS and not choice.hmr:
        out.append({
            "id": f"{field}_4fs_without_hmr", "kind": "warning",
            "title": f"{dt:g} fs without hydrogen-mass repartitioning",
            "detail": (
                f"The {where} is set to {dt:g} fs on standard masses. exp51 ran exactly "
                f"this combination on a solvated 2hb_1xT system and it failed RATTLE at "
                f"step 4,200 — 16.8 ps in, so a shorter probe would have called it stable. "
                f"A {dt:g} fs step needs the X-H stretch slowed by repartitioning, not just "
                f"the bond constrained. Turn HMR on, or drop to 2 fs."
            ),
            "applies_to": "all", "source": f"CreateJobRequest.{field}_hmr",
        })

    if dt > _RIGID_REQUIRED_ABOVE_FS and choice.rigid_bonds == RIGID_NONE:
        fatal = dt >= _HMR_REQUIRED_AT_FS
        out.append({
            "id": f"{field}_flexible_above_1fs", "kind": "warning",
            "title": f"{dt:g} fs with flexible bonds",
            "detail": (
                f"With rigidBonds none the X-H stretch (~11 fs period) is integrated "
                f"directly, and {dt:g} fs does not sample it. exp51 measured "
                + ("this exact combination dying at step 0 on the velocity limit, with and "
                   "without HMR." if fatal else
                   "5x worse energy conservation than the same run with rigidBonds all "
                   "(-8.8e-3 vs -1.7e-3 kcal/mol/ns/atom).")
                + " 1 fs is the supported timestep for flexible bonds."
            ),
            "applies_to": "all", "source": f"CreateJobRequest.{field}_rigid_bonds",
        })

    if dt < _HMR_REQUIRED_AT_FS and choice.hmr:
        out.append({
            "id": f"{field}_hmr_below_4fs", "kind": "warning",
            "title": f"Repartitioned masses at {dt:g} fs buy nothing",
            "detail": (
                f"HMR exists to make a 4 fs step stable; at {dt:g} fs it is a measured "
                f"LOSS. exp51: 3.5x worse energy conservation at 2 fs with rigid bonds, "
                f"7x at 2 fs flexible, 35x at 1 fs flexible — and the drift turns positive "
                f"(systematic energy gain). Repartitioning subtracts mass from the parent "
                f"heavy atom, so heavy-atom librations get faster while the X-H stretch "
                f"rigidBonds already froze gets slower. Leave it off below 4 fs unless you "
                f"are deliberately matching another run's mass set."
            ),
            "applies_to": "all", "source": f"CreateJobRequest.{field}_hmr",
        })

    return out


# ── GPU-resident ────────────────────────────────────────────────────────────────
# A THROUGHPUT axis, not a physics one: it changes WHERE integration runs, not what is
# computed.  It was nonetheless decided in two different places with two different rule
# sets, and in production it was keyed to the TIMESTEP — `gpu_line = "" if ts == 1.0` —
# which silently overrode the user's own choice.  exp52 measured the coupling; this is the
# one place that decides, and it always says why.

#: Reasons resident cannot run, whatever anyone asked for.  Each is a NAMD refusal, not a
#: preference: implicit solvent has no resident path; a vacuum run has no periodic cell for
#: resident's density bookkeeping; NAMD 3 refuses fixed atoms under resident; a sparsely
#: filled carved cell makes it under-count its GPU exclusion buffers and die at step 0.
HARD_BLOCKERS = ("implicit solvent (GBIS)", "vacuum (no periodic cell)",
                 "fixed atoms", "a sparsely filled carved cell")


@dataclass(frozen=True)
class ResidentDecision:
    """Whether GPUresident is emitted, and the reason a reader can check."""

    on: bool
    reason: str
    #: 'incompatible' | 'user' | 'size' — what settled it.  A UI can say "your choice was
    #: overridden" only because this distinguishes them.
    decided_by: str

    @property
    def overridden(self) -> bool:
        """True when the user asked for something the run could not honour."""
        return self.decided_by == "incompatible"


def resident_decision(*, n_atoms: Optional[int] = None,
                      force_resident: Optional[bool] = None,
                      min_atoms: int = 100_000,
                      gbis: bool = False, vacuum: bool = False,
                      fixed_atoms: bool = False,
                      carved_fill: Optional[float] = None,
                      min_fill: float = 0.90) -> ResidentDecision:
    """Resolve GPU-resident once, for both the ladder and production.

    Precedence: a hard incompatibility, then the user's explicit choice, then the measured
    size crossover.  Notably absent: the TIMESTEP.  exp52 measured resident against every
    sanctioned integrator setting on one system; the timestep does not decide this, and the
    rule that said it did was overriding an explicit user choice.
    """
    blockers = []
    if gbis:
        blockers.append("implicit solvent has no GPU-resident path in NAMD at all")
    if vacuum:
        blockers.append("a vacuum run has no periodic cell for resident's density "
                        "bookkeeping")
    if fixed_atoms:
        blockers.append("NAMD 3 refuses fixed atoms under GPU-resident")
    if carved_fill is not None and carved_fill < min_fill:
        blockers.append(f"this carved cell is only {carved_fill:.0%} full — below "
                        f"{min_fill:.0%} resident under-counts its GPU exclusion buffers "
                        f"and dies at step 0")
    if blockers:
        return ResidentDecision(False, "; ".join(blockers), "incompatible")

    if force_resident is not None:
        return ResidentDecision(
            bool(force_resident),
            "you chose this" if force_resident else "you turned it off",
            "user")

    if n_atoms is None:
        return ResidentDecision(True, "no solvated atom count yet — resident is the "
                                      "default until solvation says otherwise", "size")
    on = n_atoms >= min_atoms
    return ResidentDecision(
        on,
        (f"{n_atoms:,} atoms is at or above the ~{min_atoms:,}-atom crossover, where "
         f"resident starts winning" if on else
         f"{n_atoms:,} atoms is below the ~{min_atoms:,}-atom crossover, where resident is "
         f"a measured LOSS (both paths hit the same per-step floor and resident's setup is "
         f"pure overhead)"),
        "size")
