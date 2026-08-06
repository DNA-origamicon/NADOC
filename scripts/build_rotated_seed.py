#!/usr/bin/env python
"""Write an oxDNA seed with every helix rotated about its own axis by a fixed angle.

Why
───
On a standard 6hb, the two staple crossovers of a Holliday junction at bp i and i+1 are
NOT equally strained.  Measured on ``workspace/6hbx100_noT.nadoc`` as built: the early
crossover's oxDNA backbone-site separation is 0.739 units and the late one's is 1.103 —
and **exactly 30 of the 60 staple crossovers sit over the FENE cliff** (1.0064), which is
the "half of all crossovers" symptom.

Rotating every helix about its own axis by a small angle re-balances them.  At −4° on
that design the pair goes to 0.914 / 0.923 (imbalance 0.009) and **no crossover exceeds
even the 0.98 safe threshold**.  The optimum is DESIGN-SPECIFIC — ``6hb_validated`` wants
about −14° — so this is a per-design seed transform, not a constant to bake in.

What this is NOT
────────────────
It does not touch ``_lattice_phase_offset`` or ``BDNA_MINOR_GROOVE_ANGLE_DEG``.  Those are
locked, and they were validated against equilibrated-origami MD in
``scripts/measure_interhelix_phase.py`` (legacy crossover azimuth +3.3° vs MD +7.1°, well
inside the MD spread).  The build convention is right; this only changes the STARTING
CONFIGURATION handed to the simulator, which is a physical-layer artefact.

How the rotation is applied
───────────────────────────
A design's stored ``phase_offset`` is dead data for geometry: every representation goes
through ``deformation.effective_helix_for_geometry``, which for a lattice-bound helix
re-derives the phase from ``grid_pos``.  Overriding the stored value changes nothing
(verified: geometry delta 0.0).  So the rotation is injected at that single decision
point — the one that module names as shared by CG geometry, atomistic placement and
deformation frames — for the duration of the write only.

Scope: lattice helices carrying staple crossovers.  Overhang and ``__lnk__`` helices keep
their stored pose (``_helix_preserves_stored_pose``) and are therefore NOT rotated, so a
design that has them would mix two conventions; the script refuses those.

Usage
─────
    uv run python scripts/build_rotated_seed.py \
        --design workspace/6hbx100_noT.nadoc --deg -4 --out runs/seed_rot_m4
    uv run python scripts/build_rotated_seed.py \
        --design workspace/6hbx100_noT.nadoc --deg 0  --out runs/seed_rot_0     # control
"""
from __future__ import annotations

import argparse
import contextlib
import json
import math
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import backend.core.deformation as _defm                                   # noqa: E402
from backend.core.constants import NM_TO_OXDNA                             # noqa: E402
from backend.core.design_geometry import _geometry_for_design              # noqa: E402
from backend.core.models import Design                                     # noqa: E402
from backend.core.oxdna_health import (                                    # noqa: E402
    FENE_RMAX_UNITS, FENE_SAFE_MAX_UNITS,
)
from backend.physics.oxdna_interface import (                              # noqa: E402
    effective_a3, oxdna_backbone_site, write_configuration, write_topology,
)


@contextlib.contextmanager
def helix_rotation(delta_rad: float):
    """Rotate EVERY lattice helix about its own axis by *delta_rad* inside the block."""
    orig = _defm._normalize_helix_for_grid

    def patched(helix, lattice_type):
        h = orig(helix, lattice_type)
        return h.model_copy(update={"phase_offset": h.phase_offset + delta_rad})

    _defm._normalize_helix_for_grid = patched
    try:
        yield
    finally:
        _defm._normalize_helix_for_grid = orig


def _staple_owner(d: Design) -> dict:
    owner = {}
    for s in d.strands:
        for dom in s.domains:
            lo, hi = min(dom.start_bp, dom.end_bp), max(dom.start_bp, dom.end_bp)
            for bp in range(lo, hi + 1):
                owner[(dom.helix_id, bp, dom.direction)] = s.strand_type.value
    return owner


def crossover_report(d: Design) -> dict:
    """oxDNA backbone-site separation of every staple crossover, in oxDNA units."""
    nucs = _geometry_for_design(d, compact_skips=True)
    gm = {(n["helix_id"], n["bp_index"], str(n["direction"])): n for n in nucs}
    owner = _staple_owner(d)
    out = []
    for x in d.crossovers:
        a, b = x.half_a, x.half_b
        if owner.get((a.helix_id, a.index, a.strand)) != "staple":
            continue
        na = gm.get((a.helix_id, a.index, str(a.strand.value)))
        nb = gm.get((b.helix_id, b.index, str(b.strand.value)))
        if na is None or nb is None:
            continue
        sa = oxdna_backbone_site(np.asarray(na["backbone_position"], float),
                                 np.asarray(na["base_normal"], float), effective_a3(na))
        sb = oxdna_backbone_site(np.asarray(nb["backbone_position"], float),
                                 np.asarray(nb["base_normal"], float), effective_a3(nb))
        out.append(float(np.linalg.norm(sb - sa)) * NM_TO_OXDNA)
    v = np.asarray(out)
    return {
        "n_staple_crossovers": int(v.size),
        "mean_units": float(v.mean()) if v.size else None,
        "max_units": float(v.max()) if v.size else None,
        "n_over_cliff": int((v > FENE_RMAX_UNITS).sum()),
        "n_over_safe": int((v > FENE_SAFE_MAX_UNITS).sum()),
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--design", required=True)
    ap.add_argument("--deg", type=float, required=True,
                    help="rotation of every helix about its own axis, degrees")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()

    d = Design.model_validate_json(Path(a.design).read_text())

    # Refuse the mixed-convention cases rather than silently seeding a broken structure.
    bad = [h.id for h in d.helices if _defm._helix_preserves_stored_pose(h, d)]
    if bad and abs(a.deg) > 1e-9:
        raise SystemExit(
            f"{len(bad)} helices keep a stored pose and would NOT be rotated "
            f"({bad[:4]}...) — the seed would mix two phase conventions. "
            f"Out of scope: run this on plain lattice designs.")
    if any(x.extra_bases for x in d.crossovers):
        raise SystemExit("design has extra crossover bases — out of scope")
    if any(h.loop_skips for h in d.helices):
        raise SystemExit("design has loop/skip sites — out of scope")

    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    with helix_rotation(math.radians(a.deg)):
        rep = crossover_report(d)
        geom = _geometry_for_design(d, compact_skips=True)
        write_topology(d, out / "seed.top")
        write_configuration(d, geom, out / "seed.dat", oxdna_native_seed=True)

    rep.update({"design": a.design, "rotation_deg": a.deg,
                "fene_rmax_units": FENE_RMAX_UNITS,
                "fene_safe_max_units": FENE_SAFE_MAX_UNITS})
    (out / "seed_report.json").write_text(json.dumps(rep, indent=2))
    print(f"{Path(a.design).stem}  rotation {a.deg:+.1f} deg -> {out}")
    print(f"  staple crossovers {rep['n_staple_crossovers']}   "
          f"mean {rep['mean_units']:.3f}  max {rep['max_units']:.3f} units")
    print(f"  over FENE cliff ({FENE_RMAX_UNITS:.4f}): {rep['n_over_cliff']}   "
          f"over safe ({FENE_SAFE_MAX_UNITS}): {rep['n_over_safe']}")


if __name__ == "__main__":
    main()
