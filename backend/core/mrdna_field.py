"""mrDNA uniform E-field — a constant per-bead force in an ARBD CG run.

An *E-field* is a JOB-REQUEST annotation (never a ``Design`` edit — Three-Layer Law):
the user supplies the SHARED cross-engine field descriptor
``{"field_pN": <force per NUCLEOTIDE, pN>, "dir": [x, y, z]}`` — the very same
per-nucleotide load oxDNA puts on each bead (``OXDNA_FORCE_PN``), NAMD delivers via
``eField`` (``md_protocols.namd_efield_vector``) and CanDo adds as a nodal ``q·E`` load.
For mrDNA we turn it into a constant force on every DNA bead, applied through ARBD's
per-``ParticleType`` **grid potential** (``add_grid_potential`` / ``gridFile``): a linear
ramp potential ``U = -(F·r)`` whose negative gradient is the uniform force ``F`` (in
kcal/mol/Å) everywhere inside the grid.  This is mrDNA's own idiom for a constant force
(``arbdmodel.grid.constant_force``); the ``forceXGrid`` tabulated-force path expects a
different grid layout and is not used here.

Per-bead scaling (the cross-engine bright line):

  * The descriptor is force *per nucleotide*.  A coarse mrDNA bead carries several
    base pairs (~5 bp/bead; ~2.5 bp at helix ends) — its ARBD mass is proportional to
    that base content (measured: 1380 Da for a full 5-bp bead, 690 Da for a half bead,
    i.e. exactly ∝ nt count).  So a bead's force is ``field_pN × (nt in bead)`` and we
    recover ``nt in bead = bead_mass / (Da per nucleotide)`` with the Da-per-nucleotide
    calibrated from the model itself (total DNA-bead mass ÷ total nucleotides).  This
    makes the TOTAL applied force ``field_pN × n_nucleotides`` exactly — the same total
    the per-nucleotide engines apply — while the CG model spreads it across fewer beads.
  * mrDNA gives every bead of one base-content the same ``ParticleType`` (D000 = half
    beads, D001 = full beads), so a per-type force grid is EXACT per bead, no averaging.

A uniform field needs ≥1 anchor (:mod:`backend.core.mrdna_anchors`) or the whole
structure just streams down-field (COM drift) — the same rule as every engine.

mrDNA regenerates beads (``clear_beads()`` + ``generate_bead_model()``) between
resolution stages inside ``multiresolution_simulation`` — that also rebuilds the
``ParticleType`` objects, wiping the ``forceXGrid`` attributes.
:func:`install_field_force` wraps the model's ``generate_bead_model`` so the grids are
re-applied after every regeneration (same discipline as the anchor restraints).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Optional

import numpy as np

from backend.core.md_protocols import KCAL_MOL_A_IN_PN

if TYPE_CHECKING:  # pragma: no cover
    from backend.core.models import Design

logger = logging.getLogger(__name__)

#: pN → kcal·mol⁻¹·Å⁻¹ (ARBD's native force unit).  The inverse of the canonical
#: ``KCAL_MOL_A_IN_PN`` (≈69.477) shared by the NAMD E-field path — one physical
#: conversion, no per-engine fudge (mrDNA beads carry no explicit charge, so the force
#: is applied directly rather than as q·E).
PN_TO_KCAL_MOL_A: float = 1.0 / KCAL_MOL_A_IN_PN

#: Å of padding around the bead bounding box for the ramp potential grid.  ARBD zeroes a
#: grid potential outside its extent (Dirichlet) — a bead reaching the boundary would feel
#: a huge spurious edge force — so the grid must comfortably enclose the structure plus its
#: expected down-field drift for the whole run.
GRID_MARGIN_A: float = 500.0

#: Grid samples per axis.  ``U = -(F·r)`` is linear, so trilinear interpolation is exact
#: at any resolution; a few samples suffice.
GRID_SAMPLES: int = 4


def _model_beads(model) -> list:
    """Flat DNA-bead list (same order/scope :mod:`backend.core.mrdna_anchors` uses —
    orientation beads are already omitted by ``segment.beads``)."""
    return [b for s in model.segments for b in getattr(s, "beads", [])]


def _n_nucleotides(design: "Design") -> int:
    from backend.physics.oxdna_interface import _strand_nucleotide_order  # noqa: PLC0415

    return len(_strand_nucleotide_order(design))


def dalton_per_nucleotide(design: "Design", model) -> float:
    """Model-calibrated Da per nucleotide = total DNA-bead mass ÷ total nucleotides.

    Lets a bead's nucleotide content be recovered from its ARBD mass so the per-bead
    force scales with the base content the descriptor is defined per."""
    beads = _model_beads(model)
    total_mass = sum(float(b.type_.mass) for b in beads)
    n_nt = _n_nucleotides(design)
    if n_nt <= 0 or total_mass <= 0:
        return 0.0
    return total_mass / n_nt


def parse_field(field) -> Optional[tuple[float, np.ndarray]]:
    """``{"field_pN"|"force_pN", "dir"}`` → ``(magnitude_pN, unit_dir)`` or ``None``.

    ``None`` / empty / zero-magnitude / zero-direction all return ``None`` (a no-op
    field), mirroring ``md_protocols.namd_efield_vector``."""
    if not field:
        return None
    mag = float(field.get("field_pN", field.get("force_pN", 0.0)) or 0.0)
    d = np.asarray(field.get("dir", (0.0, 0.0, 0.0)), dtype=float)
    dnorm = float(np.linalg.norm(d))
    if mag == 0.0 or dnorm == 0.0:
        return None
    return mag, d / dnorm


def field_force_vector(field, bead_mass: float, dalton_per_nt: float) -> np.ndarray:
    """The constant force (kcal/mol/Å, 3-vector) on one bead of mass ``bead_mass``.

    ``field_pN × PN_TO_KCAL_MOL_A × (bead_mass / dalton_per_nt) × dir̂`` — the
    per-nucleotide descriptor scaled up by the bead's nucleotide content."""
    parsed = parse_field(field)
    if parsed is None or dalton_per_nt <= 0:
        return np.zeros(3)
    mag_pn, dhat = parsed
    n_nt = float(bead_mass) / dalton_per_nt
    return mag_pn * PN_TO_KCAL_MOL_A * n_nt * dhat


def _write_ramp_grid(path: Path, fvec: np.ndarray, lo: np.ndarray, hi: np.ndarray) -> None:
    """A linear ramp potential ``U = -(F·r)`` over the ``lo``→``hi`` box, so ``-∇U = F``
    (constant force) everywhere inside — ARBD's ``gridFile`` idiom for a uniform force."""
    from mrdna.arbdmodel.grid import writeDx  # noqa: PLC0415

    n = GRID_SAMPLES
    axes = [np.linspace(lo[i], hi[i], n) for i in range(3)]
    X, Y, Z = np.meshgrid(axes[0], axes[1], axes[2], indexing="ij")
    U = -(fvec[0] * X + fvec[1] * Y + fvec[2] * Z)
    delta = [float((hi[i] - lo[i]) / (n - 1)) for i in range(3)]
    writeDx(str(path), U, [float(lo[0]), float(lo[1]), float(lo[2])], delta)


def apply_field_force(design: "Design", model, field, *, out_dir: Path) -> list[str]:
    """Attach a uniform-force grid potential to each DNA bead type on the current cloud.

    Writes a ramp-potential ``field_<type>.dx`` into ``out_dir`` and registers it on the
    type via ``add_grid_potential`` (so ARBD's ``gridFile`` applies its constant gradient
    force).  Returns the type names given a force ([] for a no-op field or empty model)."""
    parsed = parse_field(field)
    beads = _model_beads(model)
    if parsed is None or not beads:
        return []
    dpn = dalton_per_nucleotide(design, model)
    if dpn <= 0:
        return []

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    pos = np.array([b.get_collapsed_position() for b in beads], dtype=float)
    lo = pos.min(axis=0) - GRID_MARGIN_A
    hi = pos.max(axis=0) + GRID_MARGIN_A

    types: dict[int, object] = {}
    for b in beads:
        types.setdefault(id(b.type_), b.type_)

    applied: list[str] = []
    for t in types.values():
        fvec = field_force_vector(field, float(t.mass), dpn)
        g = out_dir / f"field_{t.name}.dx"
        _write_ramp_grid(g, fvec, lo, hi)
        # Overwrite rather than append so re-application (after bead regen) stays
        # idempotent; DNA bead types carry no other grid potential by default.
        t.grid_potentials = [(str(g), 1, "dirichlet")]
        applied.append(t.name)
    return applied


def install_field_force(design: "Design", model, field, *, out_dir: Path) -> int:
    """Wire a uniform E-field into a model so its force grids survive bead regeneration.

    ``multiresolution_simulation`` rebuilds beads (and their ``ParticleType`` objects)
    between stages; we wrap ``generate_bead_model`` so the grids are re-attached to the
    fresh types after every regeneration.  The single coarse pass (no regeneration) is
    covered by the immediate application below.  Returns the number of bead types given a
    force on the current bead cloud."""
    if parse_field(field) is None:
        return 0

    orig = model.generate_bead_model

    def _wrapped(*args, **kwargs):
        orig(*args, **kwargs)
        names = apply_field_force(design, model, field, out_dir=out_dir)
        logger.info("mrdna field: re-applied force grids to %d bead type(s) after regen",
                    len(names))

    model.generate_bead_model = _wrapped

    names = apply_field_force(design, model, field, out_dir=out_dir)
    logger.info("mrdna field: applied force grids to %d bead type(s) (%s)",
                len(names), ", ".join(names) or "none")
    return len(names)
