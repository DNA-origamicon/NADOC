"""Generate the CanDo first-wave validation battery (6 designs @ 210 bp, 6HB honeycomb).

Each design: create_bundle -> full_autostaple -> (loop/skip program via deformation
realization) -> export .nadoc + caDNAno json into 'workspace/cando validation/'.

Run: uv run python gen_cando_battery.py
"""
import json
import sys
import traceback
from pathlib import Path

REPO = Path("/home/joshua/NADOC")
sys.path.insert(0, str(REPO))

from backend.api import headless_build as hb
from backend.api import state as design_state
from backend.core.models import LatticeType
from backend.core.cadnano import export_cadnano, check_cadnano_compatibility
from backend.core import loop_skip_calculator as lsc

SIX_HB_CELLS = [(0, 1), (1, 1), (1, 2), (1, 3), (0, 3), (0, 2)]  # conftest canonical 6HB
LEN = 210
OUT = Path("/home/joshua/NADOC/workspace/cando validation")
OUT.mkdir(parents=True, exist_ok=True)

HC = LatticeType.HONEYCOMB


def _route_6hb():
    """Fully route into ONE scaffold: create -> auto_scaffold (seam+end xovers, single
    Hamiltonian scaffold) -> auto_crossover (staple xovers) -> auto_break (nick/grow).
    Mirrors make_18hb_routed_design. Loop/skips are realized AFTER this so autostaple
    only ever sees uniform 7-bp cells."""
    hb.create_bundle(SIX_HB_CELLS, LEN, lattice=HC, name="6hb")
    hb.auto_scaffold(seamless=False)
    hb.auto_crossover()
    hb.auto_break()


def _mark_summary(design):
    loops = skips = 0
    per_helix = {}
    for h in design.helices:
        nl = sum(1 for ls in h.loop_skips if ls.delta > 0)
        ns = sum(1 for ls in h.loop_skips if ls.delta < 0)
        loops += nl
        skips += ns
        per_helix[h.id] = {"loops": nl, "skips": ns}
    return {"total_loops": loops, "total_skips": skips, "per_helix": per_helix}


def _analytic(design):
    """NADOC closed-form predictions on the realized marks."""
    mods = {h.id: list(h.loop_skips) for h in design.helices if h.loop_skips}
    out = {}
    try:
        out["global_twist_deg"] = round(lsc.predict_global_twist_deg(mods), 2)
    except Exception as e:
        out["global_twist_deg_error"] = str(e)
    try:
        r = lsc.predict_radius_nm(list(design.helices), mods, 0, LEN, direction_deg=0.0)
        out["radius_nm"] = None if r == float("inf") else round(r, 2)
    except Exception as e:
        out["radius_nm_error"] = str(e)
    return out


def build(spec):
    """spec: dict(key, kind, angle). Returns (design_or_None, meta)."""
    meta = {k: spec[k] for k in ("key", "kind", "desc")}
    meta["length_bp"] = LEN
    meta["helices"] = len(SIX_HB_CELLS)
    try:
        with hb.scratch_session(HC):
            _route_6hb()
            if spec["kind"] == "control":
                pass
            elif spec["kind"] == "twist":
                hb.add_twist(0, LEN, total_degrees=spec["angle"])
                hb.apply_loop_skip_deformations()
            elif spec["kind"] == "bend":
                hb.add_bend(0, LEN, curvature_deg_per_bp=spec["angle"] / LEN)
                hb.apply_loop_skip_deformations()
            design = design_state.get_or_404().model_copy(deep=True)
        meta["target_angle_deg"] = spec.get("angle")
        meta["marks"] = _mark_summary(design)
        meta["nadoc_analytic"] = _analytic(design)
        meta["cadnano_compat"] = check_cadnano_compatibility(design)
        meta["n_crossovers"] = len(design.crossovers)
        meta["n_strands"] = len(design.strands)
        from backend.core.models import StrandType
        meta["n_scaffold_strands"] = sum(
            1 for s in design.strands if s.strand_type == StrandType.SCAFFOLD)
        return design, meta
    except Exception as e:
        meta["FAILED"] = f"{type(e).__name__}: {e}"
        meta["traceback"] = traceback.format_exc()
        return None, meta


SPECS = [
    {"key": "01_control_straight",
     "kind": "control", "angle": None,
     "desc": "6HB, no ins/del. Control: straight; lattice baseline only."},
    {"key": "02_twist_half_turn",
     "kind": "twist", "angle": 171.0,
     "desc": "Uniform twist ~171 deg (~1/2 turn global twist)."},
    {"key": "03_twist_full_turn",
     "kind": "twist", "angle": 343.0,
     "desc": "Uniform twist ~343 deg (~1 turn, Dietz dense regime)."},
    {"key": "04_twist_opposite",
     "kind": "twist", "angle": -171.0,
     "desc": "Uniform twist opposite sign ~171 deg (loops vs skips -> opposite handedness)."},
    {"key": "05_bend_90",
     "kind": "bend", "angle": 90.0,
     "desc": "Gradient ins/del, 90 deg end-to-end bend (R~45 nm, gentle)."},
    {"key": "06_bend_180",
     "kind": "bend", "angle": 180.0,
     "desc": "Gradient ins/del, 180 deg hairpin (R~23 nm, high-strain nonlinear stressor)."},
]


def main():
    manifest = {"length_bp": LEN, "cells": SIX_HB_CELLS, "lattice": "honeycomb",
                "designs": []}
    for spec in SPECS:
        design, meta = build(spec)
        if design is not None:
            stem = spec["key"]
            (OUT / f"{stem}.nadoc").write_text(design.model_dump_json(indent=2))
            cad = export_cadnano(design)
            (OUT / f"{stem}.cadnano.json").write_text(json.dumps(cad, indent=2))
            meta["files"] = [f"{stem}.nadoc", f"{stem}.cadnano.json"]
            print(f"OK  {stem}: xovers={meta['n_crossovers']} "
                  f"marks(L/S)={meta['marks']['total_loops']}/{meta['marks']['total_skips']} "
                  f"analytic={meta['nadoc_analytic']}")
        else:
            print(f"FAIL {spec['key']}: {meta['FAILED']}")
        manifest["designs"].append(meta)
    (OUT / "_manifest.json").write_text(json.dumps(manifest, indent=2))
    print(f"\nWrote manifest -> {OUT/'_manifest.json'}")


if __name__ == "__main__":
    main()
