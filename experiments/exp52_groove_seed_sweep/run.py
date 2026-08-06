#!/usr/bin/env python3
"""exp52 — does the P–P groove separation converge, or does MD keep its seed?

The question
------------
NADOC's coarse-grained layer draws the two backbones of a base pair 150° apart on
FORWARD-cell helices and 210° apart on REVERSE-cell ones (mirror images — only one
can be right for a chiral molecule).  ``atomistic.py`` corrects both to a single
208.2° taken from the 1ZEW crystal, but applies the correction to the template frame
ORIGIN; the template's phosphorus sits 0.1887 nm off that origin, and because the two
strands' frames are z-mirrored the offset rotates the two P atoms in OPPOSITE
directions.  Realised separation: 183.84°, verified at every bp in both cell types.

So every structure this repo has ever simulated started at ~184°.  A free 20 bp duplex
(job dbd8ad3b7d4f) drifts 186.6 → 179.7° and plateaus — away from 208.5°, not toward
it — while its C1'–C1' does relax correctly (0.967 → 1.074 nm).  That is not enough to
tell "≈184° is the CHARMM36 solution equilibrium" from "the groove is a soft, slowly
reorganising DOF still sitting on its seed", because there is no arm that started
anywhere else.

The design
----------
One sequence, one box, one protocol; four seeds differing ONLY in baked-in P–P azimuth.
``_ATOMISTIC_PP_SEP_RAD`` is the frame-origin separation, so each arm sets it to its
target plus the 24.364° template collapse.  Verified before any GPU time was spent:

    origin sep set   realised P–P   C1'–C1'   WC N1–N3
        174.36°         152.31°      0.869      0.357
        208.36°         184.82°      0.967      0.309   ← control (today's build)
        232.36°         207.72°      0.985      0.277   ← crystal value
        256.36°         230.77°      0.961      0.253

If the arms converge on a common separation, that value is the equilibrium and the
answer.  If each stays near its seed over the free stage, the groove is kinetically
frozen on this timescale and the display value has to come from the crystal instead —
which is itself a publishable-grade negative result about every NADOC MD seed.

Read the arms with ``scripts/measure_cg_registration.py`` — free stages ONLY
(``MGHH_only`` / ``_k0``).  An ``ENM`` stage is restrained to the built geometry and
will hand each arm its own seed straight back, faking perfect non-convergence.

Usage
-----
    uv run python experiments/exp52_groove_seed_sweep/run.py build
    uv run python experiments/exp52_groove_seed_sweep/run.py prepare
    uv run python experiments/exp52_groove_seed_sweep/run.py launch --confirm-start
    uv run python experiments/exp52_groove_seed_sweep/run.py measure

``prepare`` never starts NAMD; ``launch`` refuses without ``--confirm-start``.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

HERE = Path(__file__).resolve().parent
WORKSPACE = REPO / "workspace"

# 20 nt, the same length as the propagator_20bp_long reference duplex.  Mixed
# sequence with G/C-rich ends so the termini fray less than the interior we measure.
SEQUENCE = "GCGCATCGATTAGCATAGCG"[:20]

# The template collapse measured in measured_positioning.template_p_azimuth_offset_rad:
# realised P–P separation = frame-origin separation − 2 × 12.182°.
TEMPLATE_COLLAPSE_DEG = 24.364

ARMS = {
    "sep150": 150.0,   # what the CG layer draws on a FORWARD-cell helix
    "sep184": 184.0,   # control — what every existing NADOC seed actually is
    "sep208": 208.0,   # the 1ZEW crystal value atomistic.py intends
    "sep232": 232.0,   # bracket from above, so convergence is not just "drifts down"
}


def _duplex_design():
    from backend.ml.propagator.systems import canonical_duplex

    return canonical_duplex(SEQUENCE).design


def _seed_model(design, target_sep_deg: float):
    """Build the atomistic model with a deliberately shifted P–P azimuth."""
    from backend.core import atomistic as at

    origin_sep = math.radians(target_sep_deg + TEMPLATE_COLLAPSE_DEG)
    with patch.object(at, "_ATOMISTIC_PP_SEP_RAD", origin_sep):
        # frame_sink={} forces the slow path; the cached fast path would bypass the
        # patched constant and silently hand every arm the same coordinates.
        return at.build_atomistic_model(design, frame_sink={})


def cmd_build(_args) -> int:
    """Build each seed and record what separation it actually realises."""
    import numpy as np

    sys.path.insert(0, str(REPO / "scripts"))
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "mcr", REPO / "scripts" / "measure_cg_registration.py")
    mcr = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mcr)

    design = _duplex_design()
    out = {}
    for name, target in ARMS.items():
        model = _seed_model(design, target)
        realised = _measure_model(mcr, np, design, model)
        out[name] = {"target_deg": target,
                     "origin_sep_deg": target + TEMPLATE_COLLAPSE_DEG,
                     **realised}
        print(f"  {name}: target {target:6.1f}  realised {realised['pp_sep_deg']:7.2f}  "
              f"C1'-C1' {realised['c1c1_nm']:.3f}  WC {realised['wc_nm']:.3f}")
    (HERE / "seeds.json").write_text(json.dumps(out, indent=2))
    print(f"\nwrote {HERE / 'seeds.json'}")
    return 0


def _measure_model(mcr, np, design, model) -> dict:
    from collections import defaultdict

    helix = design.helices[0]
    byres, resn = defaultdict(dict), {}
    for a in model.atoms:
        if a.crossover_id is not None or a.extension_id is not None:
            continue
        if a.helix_id != helix.id:
            continue
        byres[(a.bp_index, a.direction)][a.name] = np.array([a.x, a.y, a.z])
        resn[(a.bp_index, a.direction)] = a.residue
    ok = [bp for bp in sorted({k[0] for k in byres})
          if (bp, "FORWARD") in byres and (bp, "REVERSE") in byres]

    def mk(k):
        names = list(byres[k].keys())
        return mcr.ResidueView(resn[k], names, np.array([byres[k][n] for n in names]))

    recs = mcr.measure_frame([mk((bp, "FORWARD")) for bp in ok],
                             [mk((bp, "REVERSE")) for bp in ok], 9, 3, "phosphate")
    return {
        "pp_sep_deg": mcr._wrap360(mcr._circmean_deg(np.array([r["dphi_PP"] for r in recs]))[0]),
        "c1c1_nm": float(np.mean([r["c1c1_nm"] for r in recs])),
        "wc_nm": float(np.mean([r["wc_nm"] for r in recs])),
        "r_P_nm": float(np.mean([r["r_P_fwd"] for r in recs])),
    }


def cmd_prepare(args) -> int:
    """Solvate one NAMD package per arm.  Does NOT start NAMD."""
    from backend.core.md_protocols import prepare_propagator_reference
    from backend.ml.propagator.local_run import attach_and_queue, new_local_job

    design = _duplex_design()
    registry = {}
    for name, target in ARMS.items():
        print(f"── {name} (target {target}°) ──")
        model = _seed_model(design, target)
        job = new_local_job(f"exp52_{name}")
        job.save(WORKSPACE)
        subdir, stem, segments = prepare_propagator_reference(
            design, job.job_dir(WORKSPACE),
            atomistic_model=model,
            seed_lattice_nm=None,        # explicit: never let a lattice scale replace our model
            ion_conc_mM=150.0, mg_conc_mM=0.0, salt_mode="custom",
            minimize_steps=24_000,
        )
        attach_and_queue(job, WORKSPACE, subdir, stem, segments)
        registry[name] = {"job_id": job.job_id, "target_deg": target,
                          "package_subdir": subdir, "name_stem": stem}
        print(f"   job {job.job_id} queued")
    (HERE / "runs.json").write_text(json.dumps(registry, indent=2))
    print(f"\nwrote {HERE / 'runs.json'} — nothing started yet")
    return 0


def cmd_launch(args) -> int:
    if not args.confirm_start:
        print("refusing to start NAMD without --confirm-start", file=sys.stderr)
        return 2
    from backend.ml.propagator.local_run import run_prepared_job

    registry = json.loads((HERE / "runs.json").read_text())
    for name, info in registry.items():
        print(f"── running {name} ({info['job_id']}) ──", flush=True)
        job = run_prepared_job(info["job_id"], WORKSPACE)
        print(f"   {name} finished: {job.status}")
    return 0


def cmd_measure(_args) -> int:
    """Report the realised P–P separation per arm from its FREE stage only."""
    registry = json.loads((HERE / "runs.json").read_text())
    print("Run scripts/measure_cg_registration.py on each arm's free stage:\n")
    for name, info in registry.items():
        pkg = WORKSPACE / "md_jobs" / info["job_id"] / info["package_subdir"]
        stem = info["name_stem"]
        print(f"  # {name} (seeded {info['target_deg']}°)")
        print(f"  uv run python scripts/measure_cg_registration.py \\\n"
              f"      --psf {pkg}/{stem}.psf \\\n"
              f"      --dcd {pkg}/output/{stem}_04_300K_NPT_MGHH_only_p100.dcd \\\n"
              f"      --label {name}\n")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("build").set_defaults(fn=cmd_build)
    sub.add_parser("prepare").set_defaults(fn=cmd_prepare)
    p = sub.add_parser("launch")
    p.add_argument("--confirm-start", action="store_true")
    p.set_defaults(fn=cmd_launch)
    sub.add_parser("measure").set_defaults(fn=cmd_measure)
    args = ap.parse_args()
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
