"""N4 oracle — the NAMD source bundle for the cross-engine comparison card (S5).

NAMD is the GOLD-OVERRIDE engine: once a NAMD run for a design exists, its descriptors
become the reference for EVERY observable (shape, RMSF, field), overriding the oxDNA-shape /
CanDo-RMSF policy (:func:`shape_metrics.reference_for`).  This module verifies:

* the source builder emits the shared ``{engine:"namd", descriptors, rmsf, shape_frame,
  field}`` bundle with NAMD's ABSOLUTE shape descriptors on the rigid dsDNA core (SOURCE-BUNDLE
  CONTRACT, twin of O1/C5/M5), remapping the ``md_rmsf`` ``rmsf`` key → ``rmsf_nm``;
* the CORE-FILTER drops ssDNA ends before the twist/bend descriptors run;
* the HEADLINE N4 property — when the NAMD bundle joins the report, NAMD is the reference for
  shape AND rmsf, overriding the oxDNA / CanDo policy engines (gold override).

FAST tests are pure over Physical-layer dicts.  The SLOW test drives ``md_rmsf`` over a real
NAMD DCD (fixture-gated like ``test_md_trajectory.py``) → a ready NAMD source.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from backend.core.namd_shape_source import build_namd_shape_source
from backend.core.shape_compare import build_comparison_report
from backend.core.shape_metrics import compute_shape_descriptors


# ── synthetic frame helpers ─────────────────────────────────────────────────────────
def _core_frame(rmsf_val=0.3, *, with_rmsf=True):
    """A small two-helix dsDNA-core frame (10 bp × 2 strands each) with a straight axis,
    the ``md_rmsf`` positions shape: {helix_id, bp_index, direction, backbone_position, rmsf}.
    Both helices are parallel rods offset in x so the bundle has a defined twist/bend core."""
    frame = []
    for hid, x0 in ((0, 0.0), (1, 2.0)):
        for bp in range(10):
            for direction, dy in (("FORWARD", 0.0), ("REVERSE", 1.0)):
                entry = {
                    "helix_id": hid,
                    "bp_index": bp,
                    "direction": direction,
                    "backbone_position": [x0, dy, bp * 0.34],
                }
                if with_rmsf:
                    entry["rmsf"] = rmsf_val
                frame.append(entry)
    return frame


def _core_reference(frame):
    """A core-reference geometry that admits every (helix,bp,direction) column in ``frame``
    (so ``_filter_to_reference_core`` keeps them all).  Shape mirrors what
    ``core_reference_geometry`` returns: {helix_id, bp_index, direction, backbone_position}."""
    return [{k: e[k] for k in ("helix_id", "bp_index", "direction", "backbone_position")}
            for e in frame]


# ── FAST: pure source-bundle assembly ───────────────────────────────────────────────
def test_engine_tag_and_descriptor_self_consistency():
    frame = _core_frame()
    ref = _core_reference(frame)
    bundle = build_namd_shape_source(frame, ref, rmsf_positions=frame)
    assert bundle["engine"] == "namd"
    # Descriptors are the SAME locked estimator on the core-filtered frame.
    assert bundle["descriptors"] == compute_shape_descriptors(bundle["shape_frame"])
    assert bundle["descriptors"] is not None
    assert bundle["descriptors"]["n_nucleotides"] == len(frame)


def test_rmsf_remap_key_and_drops_none():
    frame = _core_frame(rmsf_val=0.42)
    ref = _core_reference(frame)
    # inject one entry with no rmsf sample — it must drop out of the profile.
    frame[0] = {k: v for k, v in frame[0].items() if k != "rmsf"}
    bundle = build_namd_shape_source(frame, ref, rmsf_positions=frame)
    prof = bundle["rmsf"]
    assert prof is not None
    assert len(prof) == len(frame) - 1                     # the rmsf-less entry dropped
    p0 = prof[0]
    assert set(p0) >= {"helix_id", "bp_index", "direction", "copy", "rmsf_nm"}
    assert p0["rmsf_nm"] == pytest.approx(0.42)            # rmsf -> rmsf_nm
    assert all(isinstance(p["bp_index"], int) for p in prof)


def test_core_filter_drops_ssdna_ends():
    """A frame carrying extra columns NOT in the core reference (ssDNA ends) — they drop
    before descriptors run, so descriptors match the core-only build."""
    frame = _core_frame()
    ref = _core_reference(frame)                            # reference = core only
    # append two ssDNA-end nts on a helix the reference doesn't cover.
    frame = frame + [
        {"helix_id": 9, "bp_index": 99, "direction": "FORWARD",
         "backbone_position": [50.0, 0.0, 0.0], "rmsf": 5.0},
        {"helix_id": 9, "bp_index": 100, "direction": "FORWARD",
         "backbone_position": [51.0, 0.0, 0.0], "rmsf": 5.0},
    ]
    bundle = build_namd_shape_source(frame, ref, rmsf_positions=frame)
    assert bundle["descriptors"]["n_nucleotides"] == len(ref)   # ss ends excluded
    # every column in the emitted shape_frame is in the core reference
    core_keys = {(e["helix_id"], e["bp_index"], e["direction"]) for e in ref}
    assert all((e["helix_id"], e["bp_index"], e["direction"]) in core_keys
               for e in bundle["shape_frame"])


def test_field_passthrough():
    frame = _core_frame()
    ref = _core_reference(frame)
    sentinel = {"passed": True, "free_proj_along_field_nm": 1.5}
    bundle = build_namd_shape_source(frame, ref, rmsf_positions=frame, field=sentinel)
    assert bundle["field"] is sentinel


def test_empty_core_yields_none_descriptors():
    """RED guard: a reference that shares NO column with the frame → empty core → None."""
    frame = _core_frame()
    bundle = build_namd_shape_source(frame, [], rmsf_positions=frame)
    assert bundle["descriptors"] is None
    assert bundle["shape_frame"] is None


# ── FAST: THE HEADLINE N4 PROPERTY — gold override ──────────────────────────────────
def test_namd_overrides_shape_and_rmsf_reference():
    """When the NAMD bundle joins oxDNA (shape ref) + CanDo (rmsf ref), NAMD becomes the
    reference for BOTH observables — the gold override that makes N4 the last live column."""
    frame = _core_frame()
    ref = _core_reference(frame)

    # A shifted copy so agreement math has something non-trivial to score.
    shifted = [dict(e, backbone_position=[e["backbone_position"][0] + 5.0,
                                          *e["backbone_position"][1:]]) for e in frame]

    namd = build_namd_shape_source(frame, ref, rmsf_positions=frame)
    # oxDNA + CanDo built via their own twins (same contract, different engine tag).
    from backend.core.cando_shape_source import build_cando_shape_source
    from backend.core.oxdna_shape_source import build_oxdna_shape_source
    oxdna = build_oxdna_shape_source(shifted, ref, rmsf_positions=shifted)
    cando_rmsf = [{"helix_id": e["helix_id"], "bp_index": e["bp_index"],
                   "rmsf_nm": 0.2} for e in ref]
    cando = build_cando_shape_source(shifted, ref, rmsf=cando_rmsf)

    report = build_comparison_report([oxdna, cando, namd])
    assert report["ready"]
    assert report["references"]["shape"] == "namd"   # overrides oxDNA policy
    assert report["references"]["rmsf"] == "namd"     # overrides CanDo policy
    assert "namd" in report["engines"]


def test_namd_reference_without_gold_falls_back_to_policy():
    """Sanity: absent NAMD, the policy engines remain the references (no accidental
    global override) — proves the previous test's flip is caused by NAMD, not the harness."""
    frame = _core_frame()
    ref = _core_reference(frame)
    from backend.core.cando_shape_source import build_cando_shape_source
    from backend.core.oxdna_shape_source import build_oxdna_shape_source
    oxdna = build_oxdna_shape_source(frame, ref, rmsf_positions=frame)
    cando = build_cando_shape_source(frame, ref, rmsf=[
        {"helix_id": e["helix_id"], "bp_index": e["bp_index"], "rmsf_nm": 0.2} for e in ref])
    report = build_comparison_report([oxdna, cando])
    assert report["references"]["shape"] == "oxdna"
    assert report["references"]["rmsf"] == "cando"


# ── SLOW: real NAMD DCD → md_rmsf → ready NAMD source ───────────────────────────────
_WS = Path(__file__).resolve().parent.parent / "workspace"
_JOB = _WS / "md_jobs" / "5c6a87247a60" / "package" / "2hb_namd_solvated"
_PSF = _JOB / "2hb.psf"
_REF = _JOB / "2hb.pdb"
_DESIGN = _WS / "2hb.nadoc"
_HAVE_FIXTURE = _PSF.exists() and _REF.exists() and _DESIGN.exists() and any(
    (_JOB / "output").glob("*.dcd")) if _JOB.exists() else False


@pytest.mark.skipif(not _HAVE_FIXTURE, reason="real 2hb NAMD job fixture not present")
def test_real_namd_trajectory_builds_ready_source():
    pytest.importorskip("MDAnalysis")
    from backend.api.skip_twist_tuning import core_reference_geometry
    from backend.core.md_trajectory import md_rmsf
    from backend.core.models import Design

    raw = _DESIGN.read_text()
    try:
        design = Design.model_validate_json(raw)
    except Exception:
        obj = json.loads(raw)
        design = Design.model_validate(obj.get("design", obj))

    dcds = sorted((_JOB / "output").glob("*.dcd"))
    segments = [(d.stem, "md", d) for d in dcds]
    r = md_rmsf(_PSF, segments, _REF, design, max_frames=20)
    assert r["ready"] is True and r["n_frames"] > 0

    # Regression: md_rmsf recovers each strand's 5'-terminal nucleotide (no P atom —
    # pdb2gmx strips the 5' phosphate) via its O5', so EVERY design nucleotide carries a
    # position + RMSF.  The P-only path silently dropped one nucleotide per strand, which
    # then rendered un-moved/un-coloured in the flexibility map.
    from backend.physics.oxdna_interface import _XB_SENTINEL, _strand_nucleotide_order
    design_nt = {(k[0], int(k[1]), getattr(k[2], "value", k[2]))
                 for k in _strand_nucleotide_order(design) if k[0] != _XB_SENTINEL}
    rmsf_nt = {(p["helix_id"], int(p["bp_index"]), str(p["direction"]).upper())
               for p in r["positions"] if p["helix_id"] != _XB_SENTINEL}
    assert design_nt <= rmsf_nt, f"design nucleotides missing from RMSF map: {sorted(design_nt - rmsf_nt)[:5]}"

    reference = core_reference_geometry(design)
    bundle = build_namd_shape_source(r["positions"], reference, rmsf_positions=r["positions"])
    assert bundle["engine"] == "namd"
    assert bundle["descriptors"] is not None
    assert bundle["shape_frame"]
    assert bundle["rmsf"] and all(np.isfinite(p["rmsf_nm"]) for p in bundle["rmsf"])
    # gold override holds on real data too.
    report = build_comparison_report([bundle])
    assert report["ready"]
    assert report["references"]["shape"] == "namd"
