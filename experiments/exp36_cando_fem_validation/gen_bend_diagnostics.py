"""Generate the CanDo BEND-GAP diagnostic battery (HANDOFF §4).

Purpose: designs that isolate WHY the native FEM converts only ~68% of the
programmed bend while CanDo converts ~95%.  Five families:

  B1  crossover-density sweep   6HB, 90deg bend, staple-xover density {full, 1/2, 1/4, min}
  B2  bend-angle series         6HB, 210bp, programmed 30/45/60/90/135 deg
  B3  length series             6HB, 90deg-equivalent curvature at 105/210/420 bp
  B4  minimal cross-sections    2HB + 4HB, 90deg bend
  B5  square-lattice bend        SQ 6HB, 90deg bend (lattice-artifact control)

Each design: reuse the proven route (create_bundle -> auto_scaffold(seamed/seamless)
-> auto_crossover -> auto_break), optionally thin staple crossovers, realize the
bend gradient, RELOCATE any loop/skip that lands on a crossover or a strand end
(feedback_loopskip_no_crossover_ends), assign M13 + WC staples, then export
.nadoc + .cadnano.json + _sequences.csv into 'workspace/cando validation/'.

Run: uv run python experiments/exp36_cando_fem_validation/gen_bend_diagnostics.py
"""
import json
import sys
import traceback
from pathlib import Path

REPO = Path("/home/joshua/NADOC")
sys.path.insert(0, str(REPO))

from backend.api import headless_build as hb
from backend.api import state as design_state
from backend.api.routes_sequences import export_sequence_csv
from backend.core.models import LatticeType, StrandType
from backend.core.cadnano import export_cadnano, check_cadnano_compatibility
from backend.core import loop_skip_calculator as lsc

OUT = Path("/home/joshua/NADOC/workspace/cando validation")
OUT.mkdir(parents=True, exist_ok=True)

HC = LatticeType.HONEYCOMB
SQ = LatticeType.SQUARE

# Canonical cross-sections (conftest 6HB; 2/4HB are contiguous sub-columns).
CELLS_6HB = [(0, 1), (1, 1), (1, 2), (1, 3), (0, 3), (0, 2)]
CELLS_2HB = [(0, 1), (1, 1)]
CELLS_4HB = [(0, 1), (1, 1), (1, 2), (0, 2)]
# Square lattice: a 2x3 block of adjacent cells.
CELLS_6SQ = [(0, 0), (0, 1), (0, 2), (1, 0), (1, 1), (1, 2)]

END_MARGIN = 6  # bp kept clear of each helix's duplex ends


# ── Routing ──────────────────────────────────────────────────────────────────

def _route(cells, length, lattice=HC, seamless=False):
    """create -> auto_scaffold -> auto_crossover -> auto_break (single scaffold)."""
    hb.create_bundle(cells, length, lattice=lattice, name="diag")
    hb.auto_scaffold(seamless=seamless)
    hb.auto_crossover()
    hb.auto_break()


# ── Staple-crossover thinning (density sweep) ──────────────────────────────────

def thin_staple_crossovers(keep_every: int):
    """Delete a fraction of the ``auto_crossover`` (staple) crossovers in place.

    Scaffold crossovers (auto_scaffold seam + create_*_ends) are NEVER touched, so
    the single snaking scaffold is preserved.  Deleting a staple crossover desplices
    the staple into shorter fragments (extra nicks) — topologically valid; it just
    reduces the inter-helix HJ coupling density, which is the whole point of the sweep.

    keep_every=1 keeps all; 2 keeps every other; 4 keeps every fourth; a large value
    (e.g. 999) keeps ~1 (minimal).  Returns (n_before, n_after) staple-crossover counts.
    """
    d = design_state.get_or_404()
    staple_xo = [x for x in d.crossovers if x.process_id == "auto_crossover"]
    n_before = len(staple_xo)
    if keep_every <= 1:
        return n_before, n_before
    # Stable order for reproducibility: sort by (helix_a, index).
    staple_xo.sort(key=lambda x: (x.half_a.helix_id, x.half_a.index, x.id))
    deleted = 0
    for i, xo in enumerate(staple_xo):
        if i % keep_every == 0:
            continue  # keep
        try:
            hb.delete_crossover(xo.id)
            deleted += 1
        except Exception:
            pass  # crossover already gone / not deletable — skip
    d = design_state.get_or_404()
    n_after = sum(1 for x in d.crossovers if x.process_id == "auto_crossover")
    return n_before, n_after


# ── Off-crossover / off-end mark relocation ───────────────────────────────────

def _forbidden_bps(design):
    """Per helix: crossover bps + domain endpoints + duplex-end margin (bps a mark
    must NOT land on)."""
    forb = {h.id: set() for h in design.helices}
    interior = {}  # hid -> (lo, hi) duplex-covered bp range
    for xo in design.crossovers:
        for half in (xo.half_a, xo.half_b):
            if half.helix_id in forb:
                forb[half.helix_id].add(half.index)
    cov = {h.id: set() for h in design.helices}
    for s in design.strands:
        if s.is_reference:
            continue
        for dm in s.domains:
            if dm.helix_id not in forb:
                continue
            forb[dm.helix_id].add(dm.start_bp)
            forb[dm.helix_id].add(dm.end_bp)
            cov[dm.helix_id].update(range(min(dm.start_bp, dm.end_bp),
                                          max(dm.start_bp, dm.end_bp) + 1))
    for hid, bps in cov.items():
        if bps:
            lo, hi = min(bps), max(bps)
            interior[hid] = (lo + END_MARGIN, hi - END_MARGIN)
            for b in range(lo, lo + END_MARGIN):
                forb[hid].add(b)
            for b in range(hi - END_MARGIN + 1, hi + 1):
                forb[hid].add(b)
        else:
            interior[hid] = (0, -1)
    return forb, interior


def relocate_marks_off_forbidden(design):
    """Move every loop/skip that sits on a crossover / strand end / margin to the
    nearest free interior bp on the SAME helix, preserving delta (and thus each
    helix's net insertion/deletion count -> the programmed twist/bend magnitude).

    Mutates ``design.helices[*].loop_skips`` in place.  Returns (n_moved, n_stuck).
    """
    forb, interior = _forbidden_bps(design)
    moved = stuck = 0
    for h in design.helices:
        if not h.loop_skips:
            continue
        occupied = {ls.bp_index for ls in h.loop_skips}
        lo, hi = interior.get(h.id, (0, -1))
        bad = forb[h.id]
        for ls in h.loop_skips:
            if ls.bp_index not in bad:
                continue
            occupied.discard(ls.bp_index)
            # search outward for the nearest free, non-forbidden interior bp
            target = None
            for r in range(1, (hi - lo) + 2):
                for cand in (ls.bp_index + r, ls.bp_index - r):
                    if lo <= cand <= hi and cand not in bad and cand not in occupied:
                        target = cand
                        break
                if target is not None:
                    break
            if target is None:
                stuck += 1
                occupied.add(ls.bp_index)
                continue
            ls.bp_index = target
            occupied.add(target)
            moved += 1
    return moved, stuck


# ── Verification (caDNAno-level) ───────────────────────────────────────────────

def verify_clean(design):
    """Return a dict of invariant checks: 0 marks on crossovers/ends, single scaffold."""
    forb, _ = _forbidden_bps(design)
    on_forbidden = 0
    for h in design.helices:
        for ls in h.loop_skips:
            if ls.bp_index in forb[h.id]:
                on_forbidden += 1
    n_scaf = sum(1 for s in design.strands if s.strand_type == StrandType.SCAFFOLD)
    return {"marks_on_forbidden": on_forbidden, "n_scaffold_strands": n_scaf}


def _mark_counts(design):
    loops = sum(1 for h in design.helices for ls in h.loop_skips if ls.delta > 0)
    skips = sum(1 for h in design.helices for ls in h.loop_skips if ls.delta < 0)
    return loops, skips


def _analytic(design, length):
    mods = {h.id: list(h.loop_skips) for h in design.helices if h.loop_skips}
    out = {}
    try:
        out["global_twist_deg"] = round(lsc.predict_global_twist_deg(mods), 2)
    except Exception as e:
        out["global_twist_deg_error"] = str(e)
    # Probe the bend plane: report the smallest finite radius over candidate directions
    # (the true bend plane is design-dependent; a 2HB stack bends only in its pair plane).
    try:
        best = None
        for dd in (0.0, 90.0, 180.0, 270.0):
            r = lsc.predict_radius_nm(list(design.helices), mods, 0, length, direction_deg=dd)
            if r != float("inf") and (best is None or r < best[0]):
                best = (round(r, 2), dd)
        out["radius_nm"] = None if best is None else best[0]
        out["radius_dir_deg"] = None if best is None else best[1]
    except Exception as e:
        out["radius_nm_error"] = str(e)
    return out


def _sequences_csv() -> str:
    resp = export_sequence_csv()
    body = resp.body
    return body.decode("utf-8") if isinstance(body, (bytes, bytearray)) else str(body)


# ── Build one design ───────────────────────────────────────────────────────────

def build(spec):
    meta = {k: spec[k] for k in ("key", "desc")}
    meta.update({"cells": len(spec["cells"]), "length_bp": spec["length"],
                 "lattice": spec["lattice"].value, "target_bend_deg": spec.get("bend_deg"),
                 "direction_deg": spec.get("direction_deg", 0.0)})
    if spec.get("confounded"):
        meta["confounded"] = spec["confounded"]
    try:
        with hb.scratch_session(spec["lattice"]):
            _route(spec["cells"], spec["length"], lattice=spec["lattice"],
                   seamless=spec.get("seamless", False))
            if spec.get("keep_every", 1) > 1:
                nb, na = thin_staple_crossovers(spec["keep_every"])
                meta["staple_xovers_before_after"] = [nb, na]
            # realize the bend gradient
            length = spec["length"]
            hb.add_bend(0, length,
                        curvature_deg_per_bp=spec["bend_deg"] / length,
                        direction_deg=spec.get("direction_deg", 0.0))
            hb.apply_loop_skip_deformations()
            # clean marks in place, then push back to state so exports see it
            d = design_state.get_or_404()
            moved, stuck = relocate_marks_off_forbidden(d)
            design_state.set_design(d)
            meta["marks_relocated"] = moved
            meta["marks_stuck"] = stuck
            # sequences (for CanDo atomic model + clean CSV)
            hb.assign_scaffold_sequence("M13mp18")
            hb.assign_staple_sequences()
            design = design_state.get_or_404().model_copy(deep=True)
            csv_text = _sequences_csv()

        loops, skips = _mark_counts(design)
        meta["marks_loops_skips"] = [loops, skips]
        meta["n_crossovers"] = len(design.crossovers)
        meta["n_staple_crossovers"] = sum(
            1 for x in design.crossovers if x.process_id == "auto_crossover")
        meta["n_strands"] = len(design.strands)
        meta["nadoc_analytic"] = _analytic(design, spec["length"])
        meta["verify"] = verify_clean(design)
        meta["cadnano_compat"] = check_cadnano_compatibility(design)
        meta["csv_has_q"] = "?" in csv_text
        return design, csv_text, meta
    except Exception as e:
        meta["FAILED"] = f"{type(e).__name__}: {e}"
        meta["traceback"] = traceback.format_exc()
        return None, None, meta


# ── Specs ──────────────────────────────────────────────────────────────────────

def _specs():
    specs = []
    # B1 crossover-density sweep (6HB, 90deg bend)
    for keep, tag in [(1, "full"), (2, "half"), (4, "quarter"), (999, "minimal")]:
        specs.append({
            "key": f"B1_density_{tag}", "cells": CELLS_6HB, "length": 210,
            "lattice": HC, "bend_deg": 90.0, "keep_every": keep,
            "desc": f"6HB 90deg bend, staple-crossover density={tag} (keep_every={keep}). "
                    f"THE bend-vs-coupling diagnostic: does CanDo bend stay ~87deg as "
                    f"crossovers thin?"})
    # B2 bend-angle series (6HB, 210bp)
    for ang in (30, 45, 60, 90, 135):
        specs.append({
            "key": f"B2_bend_{ang:03d}", "cells": CELLS_6HB, "length": 210,
            "lattice": HC, "bend_deg": float(ang),
            "desc": f"6HB 210bp, programmed {ang}deg bend. Is conversion ratio constant "
                    f"(linear partition) or angle-dependent (large-deflection)?"})
    # B3 length series at fixed curvature (radius ~= 105bp-90deg equivalent)
    #   Keep curvature (deg/bp) constant so R is fixed; vary length -> shear-lag length test.
    curv = 90.0 / 210.0  # deg/bp -> fixed R~45.5nm; series = 45/90/180deg (no self-contact)
    for length in (105, 210, 420):
        specs.append({
            "key": f"B3_len_{length}", "cells": CELLS_6HB, "length": length,
            "lattice": HC, "bend_deg": curv * length,
            "desc": f"6HB {length}bp at fixed curvature {curv:.4f} deg/bp (R fixed). "
                    f"Shear-lag has a length scale: does conversion efficiency rise with length?"})
    # B4 minimal cross-sections (90deg bend)
    specs.append({
        "key": "B4_2hb_bend", "cells": CELLS_2HB, "length": 210, "lattice": HC,
        "bend_deg": 90.0, "seamless": True, "direction_deg": 90.0,
        "desc": "2HB 90deg bend (seamless single scaffold; bend plane = the 2-helix stack, "
                "direction_deg=90). Few crossover pairs -> shear-lag extreme; isolates "
                "per-crossover shear coupling."})
    specs.append({
        "key": "B4_4hb_bend", "cells": CELLS_4HB, "length": 210, "lattice": HC,
        "bend_deg": 90.0,
        "desc": "4HB 90deg bend. Intermediate cross-section for the shear-coupling scaling."})
    # B5 square-lattice bend (multiple of 32 bp)
    #   CAVEAT: the SQ lattice carries an intrinsic ~150deg twist from its 10.67->10.5
    #   periodic-skip correction (baseline -27 skips, before any bend). The bend here is
    #   therefore CONFOUNDED with a large global twist -> lowest priority; run only if the
    #   HC bend series leaves the honeycomb-artifact question open.
    specs.append({
        "key": "B5_sq_6hb_bend", "cells": CELLS_6SQ, "length": 224, "lattice": SQ,
        "bend_deg": 90.0, "confounded": "carries ~150deg intrinsic SQ-correction twist",
        "desc": "Square-lattice 6HB 90deg bend (224bp = 7x32). Confirms conversion isn't a "
                "honeycomb-geometry artifact. CONFOUND: ~150deg intrinsic twist from SQ "
                "periodic skips -> bend must be disentangled from twist. OPTIONAL/last."})
    return specs


def main():
    manifest = {"purpose": "CanDo bend-gap diagnostic battery (HANDOFF section 4)",
                "designs": []}
    for spec in _specs():
        design, csv_text, meta = build(spec)
        stem = spec["key"]
        if design is not None:
            (OUT / f"{stem}.nadoc").write_text(design.model_dump_json(indent=2))
            (OUT / f"{stem}.cadnano.json").write_text(
                json.dumps(export_cadnano(design), indent=2))
            (OUT / f"{stem}_sequences.csv").write_text(csv_text)
            v = meta["verify"]
            flag = "" if (v["marks_on_forbidden"] == 0 and v["n_scaffold_strands"] == 1
                          and not meta["csv_has_q"]) else "  <-- CHECK"
            print(f"OK  {stem}: xo={meta['n_crossovers']} "
                  f"(staple {meta['n_staple_crossovers']}) "
                  f"L/S={meta['marks_loops_skips']} "
                  f"reloc={meta['marks_relocated']}/stuck={meta['marks_stuck']} "
                  f"onForbidden={v['marks_on_forbidden']} scaf={v['n_scaffold_strands']} "
                  f"q={meta['csv_has_q']} "
                  f"analytic={meta['nadoc_analytic']}{flag}")
        else:
            print(f"FAIL {stem}: {meta['FAILED']}")
        manifest["designs"].append(meta)
    (OUT / "_bend_diagnostics_manifest.json").write_text(json.dumps(manifest, indent=2))
    print(f"\nWrote manifest -> {OUT/'_bend_diagnostics_manifest.json'}")


if __name__ == "__main__":
    main()
