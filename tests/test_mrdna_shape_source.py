"""Oracle for M5 — mrDNA contribution to the cross-engine comparison card (S5).

Property under test (the bright line — a *comparable prediction*, not "a wrapper exists"):
the mrDNA relaxed display frame becomes the shared ``{engine, descriptors, rmsf, shape_frame,
field}`` source bundle the comparison card consumes, so mrDNA's ABSOLUTE twist/bend appears as
a third live column cross-validated against oxDNA's shape reference, plus a per-nucleotide RMSF
from the CG trajectory ensemble.

The M5-specific engineering the fast tests pin is the **copy-key gap**: mrDNA's
``_display_positions`` emits crossover extra-base inserts as ``__xb__`` entries whose
``bp_index`` is a *string* crossover id (``{helix_id:"__xb__", bp_index:xo_id, direction:k}``).
Those crash the shared ``_dev_key`` (which does ``int(bp_index)``) that ``rmsf_from_ensemble`` /
``deviation_profile`` use — oxDNA never feeds them into its source (``configuration_full``
drops ``__xb__``).  The source builder must swallow them (they are ssDNA, never part of the
comparable dsDNA core) exactly the way ``_core_column_key`` already does.

Everything here is Physical-layer / display-only (Three-Layer Law): the tests read positions
off frames + (slow) run a real ARBD coarse relaxation — no ``Design`` is ever mutated.
"""

from __future__ import annotations

import numpy as np
import pytest

from backend.api.skip_twist_tuning import core_reference_geometry
from backend.core.mrdna_shape_source import build_mrdna_shape_source
from backend.core.shape_metrics import compute_shape_descriptors
from tests.conftest import make_6hb_design


# ── helpers ───────────────────────────────────────────────────────────────────


def _core_and_frame():
    """A realistic multi-helix core reference + a candidate display frame that equals
    it (so the whole frame survives the core mask and the descriptors are well-defined)."""
    d = make_6hb_design(length_bp=24)
    ref = core_reference_geometry(d)
    # The candidate frame carries the SAME keys/positions as the reference core.
    frame = [
        {
            "helix_id": p["helix_id"],
            "bp_index": p["bp_index"],
            "direction": p["direction"],
            "copy": p.get("copy", 0),
            "backbone_position": list(p["backbone_position"]),
        }
        for p in ref
    ]
    return d, ref, frame


def _xb_entry(xo_id, k):
    """A crossover extra-base insert entry exactly as ``_display_positions`` emits it:
    ``helix_id="__xb__"``, ``bp_index`` a STRING crossover id, ``direction`` the insert
    index.  This is the copy-key landmine the builder must not choke on."""
    return {
        "helix_id": "__xb__",
        "bp_index": xo_id,
        "direction": k,
        "backbone_position": [float(k), 0.0, 0.0],
    }


def test_shared_rmsf_keeps_manifest_addressed_crossover_inserts():
    """Synthetic render addresses are valid scalar-map identities, not parse errors."""
    from backend.core.shape_metrics import rmsf_from_ensemble

    first = [_xb_entry("xo-1", 0), _xb_entry("xo-1", 1)]
    second = [
        {**first[0], "backbone_position": [0.1, 0.0, 0.0]},
        {**first[1], "backbone_position": [1.0, 0.1, 0.0]},
    ]
    result = rmsf_from_ensemble([first, second], align=False)
    assert result["n"] == 2
    assert {p["bp_index"] for p in result["positions"]} == {"xo-1"}


# ── FAST: engine tag + descriptor self-consistency ────────────────────────────


def test_engine_tag_and_descriptors_are_absolute_on_the_core():
    _d, ref, frame = _core_and_frame()
    src = build_mrdna_shape_source(frame, ref)
    assert src["engine"] == "mrdna"
    # ABSOLUTE descriptors on the core — the SAME locked estimator, so self-consistent.
    assert src["descriptors"] == compute_shape_descriptors(frame)
    assert src["descriptors"] is not None
    assert src["descriptors"]["twist_total_deg"] is not None  # >= 2 helices → defined
    # shape_frame is the core-filtered frame (here the whole frame).
    assert len(src["shape_frame"]) == len(frame)


def test_core_mask_drops_ssdna_ends():
    _d, ref, frame = _core_and_frame()
    # Two extra columns absent from the core reference (floppy ssDNA ends).
    frame = frame + [
        {
            "helix_id": frame[0]["helix_id"],
            "bp_index": 9999,
            "direction": "FORWARD",
            "backbone_position": [0.0, 0.0, 0.0],
        },
        {
            "helix_id": "no_such_helix",
            "bp_index": 3,
            "direction": "REVERSE",
            "backbone_position": [1.0, 1.0, 1.0],
        },
    ]
    src = build_mrdna_shape_source(frame, ref)
    keys = {(p["helix_id"], p["bp_index"]) for p in src["shape_frame"]}
    assert (frame[0]["helix_id"], 9999) not in keys
    assert ("no_such_helix", 3) not in keys
    assert len(src["shape_frame"]) == len(ref)  # exactly the core survived


def test_copy_key_gap_xb_inserts_do_not_crash_and_drop_out():
    """THE M5 fix: a display frame carrying string-``bp_index`` ``__xb__`` inserts builds a
    valid bundle — the inserts drop out of the comparable core, the real nucleotides stay,
    and the descriptors are still finite (no ``int('xo_3')`` crash)."""
    _d, ref, frame = _core_and_frame()
    poisoned = frame + [
        _xb_entry("xo_3", 0),
        _xb_entry("xo_3", 1),
        _xb_entry("xo_7", 0),
    ]
    src = build_mrdna_shape_source(poisoned, ref)
    assert src["descriptors"] is not None
    assert all(p["helix_id"] != "__xb__" for p in src["shape_frame"])
    assert len(src["shape_frame"]) == len(ref)  # inserts gone, core intact
    # Same descriptors as the un-poisoned frame (inserts were never comparable).
    assert src["descriptors"] == build_mrdna_shape_source(frame, ref)["descriptors"]


# ── FAST: RMSF remap + robustness ─────────────────────────────────────────────


def test_rmsf_remap_preserves_copy_drops_none_and_xb():
    _d, ref, frame = _core_and_frame()
    h = frame[0]["helix_id"]
    rmsf = [
        {
            "helix_id": h,
            "bp_index": 3,
            "direction": "FORWARD",
            "copy": 0,
            "rmsf_nm": 0.4,
        },
        {
            "helix_id": h,
            "bp_index": 3,
            "direction": "REVERSE",
            "copy": 1,
            "rmsf_nm": 0.6,
        },
        {
            "helix_id": h,
            "bp_index": 4,
            "direction": "FORWARD",
            "rmsf_nm": None,
        },  # dropped
        {
            "helix_id": "__xb__",
            "bp_index": "xo_3",
            "direction": 0,
            "rmsf_nm": 0.9,
        },  # dropped
    ]
    src = build_mrdna_shape_source(frame, ref, rmsf=rmsf)
    got = src["rmsf"]
    assert len(got) == 2
    assert {r["rmsf_nm"] for r in got} == {0.4, 0.6}
    assert {r["copy"] for r in got} == {0, 1}  # copy preserved
    assert all(isinstance(r["bp_index"], int) for r in got)


def test_field_passthrough_and_none_defaults():
    _d, ref, frame = _core_and_frame()
    sentinel = {"passed": True, "rows": [1, 2, 3]}
    src = build_mrdna_shape_source(frame, ref, field=sentinel)
    assert src["field"] is sentinel
    assert build_mrdna_shape_source(frame, ref)["field"] is None
    assert build_mrdna_shape_source(frame, ref)["rmsf"] is None


def test_empty_core_yields_none():
    """RED guard: a reference mask that shares no key with the frame → no comparable
    frame, so descriptors + shape_frame are None (not a crash, not a bogus number)."""
    _d, _ref, frame = _core_and_frame()
    disjoint_ref = [
        {
            "helix_id": "ghost",
            "bp_index": 1,
            "direction": "FORWARD",
            "copy": 0,
            "backbone_position": [0, 0, 0],
        }
    ]
    src = build_mrdna_shape_source(frame, disjoint_ref)
    assert src["descriptors"] is None
    assert src["shape_frame"] is None


# ── FAST: the real trajectory-RMSF path (monkeypatched reconstruction) ────────


def test_trajectory_rmsf_subsamples_guards_and_feeds_ensemble(monkeypatch, tmp_path):
    """Drive ``mrdna_trajectory_rmsf`` itself (the path the slow ARBD test also covers) with
    a stubbed per-frame reconstruction + fake trajectory length: it caps the frame count,
    keys each frame the way ``_dev_key`` expects (int bp, string direction), and returns a
    finite per-nucleotide RMSF — and short/absent trajectories yield None."""
    from backend.core import mrdna_bridge, mrdna_decoder, mrdna_runner
    from backend.core.mrdna_manifest import MrdnaNucleotideManifest

    psf, dcd = tmp_path / "s.psf", tmp_path / "s.dcd"
    psf.write_text("")
    dcd.write_text("")
    monkeypatch.setattr(mrdna_runner, "_sim_paths", lambda jd: (psf, dcd))
    monkeypatch.setattr(mrdna_bridge, "_ensure_mrdna", lambda: None)
    MrdnaNucleotideManifest(design_fingerprint="test", records=[]).write(tmp_path)

    n_frames_box = {"n": 100}

    class _FakeU:
        def __init__(self, *_a, **_k):
            self.trajectory = list(range(n_frames_box["n"]))

    monkeypatch.setattr("MDAnalysis.Universe", _FakeU)

    # 8 real dsDNA keys (int bp, string direction) with a small frame-dependent, NON-rigid
    # wobble so the aligned ensemble has genuine site fluctuation (not a pure pose change).
    def _fake_decode(job_dir, p, dd, *, design=None, frame=-1):
        out = []
        for bp in range(4):
            for k, d in enumerate(("FORWARD", "REVERSE")):
                jitter = 0.01 * frame * (bp + 1) if (bp + k) % 2 == 0 else 0.0
                out.append(
                    {
                        "identity": f"n:{bp}:{d}",
                        "helix_id": "h",
                        "bp_index": bp,
                        "direction": d,
                        "copy": 0,
                        "backbone_position": [float(bp), float(k), jitter],
                        "simulation_mode": "direct",
                        "classification": "duplex",
                    }
                )
        return {"positions": out, "quality": {"usable": True}}

    monkeypatch.setattr(mrdna_decoder, "decode_mrdna_frame", _fake_decode)

    from backend.core.mrdna_runner import mrdna_trajectory_rmsf

    d = make_6hb_design(length_bp=12)
    out = mrdna_trajectory_rmsf(d, tmp_path, max_frames=10)
    assert out is not None
    assert 2 <= out["n_frames"] <= 10  # 100 frames subsampled to <= max_frames
    assert out["n"] == 8  # all keys shared across every frame
    assert all(
        np.isfinite(p["rmsf_nm"]) and p["rmsf_nm"] >= 0.0 for p in out["positions"]
    )
    assert all(isinstance(p["bp_index"], int) for p in out["positions"])

    # A single-frame trajectory has no ensemble → None (not a crash).
    n_frames_box["n"] = 1
    assert mrdna_trajectory_rmsf(d, tmp_path) is None


# ── FAST: cross-engine integration (the actual cross-validation) ──────────────


def test_mrdna_pairs_with_oxdna_in_the_comparison_report():
    """oxDNA (shape reference) + mrDNA source → a ready comparison report: oxDNA is the
    shape reference, mrDNA appears as an engine, and a rigid shift of the same frame gives
    a ~0 shape-RMSD (Kabsch strips the pose), i.e. mrDNA's shape genuinely compares."""
    from backend.core.oxdna_shape_source import build_oxdna_shape_source
    from backend.core.shape_compare import build_comparison_report

    _d, ref, frame = _core_and_frame()
    oxdna = build_oxdna_shape_source(frame, ref)
    # mrDNA "predicts" the same shape rigidly translated (a pure pose change).
    shifted = [
        {
            **p,
            "backbone_position": [
                p["backbone_position"][0] + 5.0,
                p["backbone_position"][1],
                p["backbone_position"][2],
            ],
        }
        for p in frame
    ]
    mrdna = build_mrdna_shape_source(shifted, ref)
    report = build_comparison_report([oxdna, mrdna])
    assert report["ready"]
    assert "mrdna" in report["engines"]
    assert report["references"]["shape"] == "oxdna"
    agr = {a["engine"]: a for a in report["agreement"]}
    assert "mrdna" in agr
    assert agr["mrdna"]["shape_rmsd_nm"] is not None
    assert agr["mrdna"]["shape_rmsd_nm"] < 1e-6  # rigid shift → Kabsch-zeroed


# ── SLOW: a real ARBD coarse relaxation → trajectory RMSF + a ready source ────


@pytest.mark.slow
def test_real_mrdna_trajectory_rmsf_and_source_ready(tmp_path):
    """A real short ARBD coarse run: reconstruct the relaxed display frame + a per-nt RMSF
    from the CG trajectory ensemble, and assemble a READY mrDNA source bundle whose
    descriptors + RMSF are finite — a comparable mrDNA prediction, not a smoke run."""
    from backend.core.mrdna_bridge import find_arbd

    if not find_arbd():
        pytest.skip("arbd binary not installed")

    from backend.core.mrdna_runner import (
        _SIM_STEM,
        _display_positions,
        mrdna_trajectory_rmsf,
    )

    d = make_6hb_design(length_bp=42)
    job_dir = tmp_path / "job"
    (job_dir / "output").mkdir(parents=True)
    from backend.core.mrdna_manifest import (
        bind_manifest_to_mrdna_particles,
        build_mrdna_nucleotide_manifest,
    )
    from backend.parameterization.mrdna_inject import (
        CrossoverPotentialOverride,
        mrdna_model_from_nadoc_parameterized,
    )

    m = mrdna_model_from_nadoc_parameterized(
        d, CrossoverPotentialOverride.from_database("T0")
    )
    manifest = build_mrdna_nucleotide_manifest(d, design_fingerprint="test")
    bind_manifest_to_mrdna_particles(manifest, m).write(job_dir)
    # A handful of trajectory frames (output_period ≪ num_steps) so RMSF has an ensemble.
    m.simulate(
        output_name=_SIM_STEM,
        directory=str(job_dir),
        num_steps=4000.0,
        timestep=200e-6,
        output_period=800.0,
        gpu=0,
    )

    frame, _n = _display_positions(d, job_dir)
    rmsf = mrdna_trajectory_rmsf(d, job_dir)
    assert rmsf is not None and rmsf["n_frames"] >= 2
    assert rmsf["positions"] and all(p["rmsf_nm"] >= 0.0 for p in rmsf["positions"])

    ref = core_reference_geometry(d)
    src = build_mrdna_shape_source(frame, ref, rmsf=rmsf["positions"])
    assert src["engine"] == "mrdna"
    assert src["descriptors"] is not None
    assert src["descriptors"]["twist_total_deg"] is not None
    assert src["rmsf"] and all(np.isfinite(r["rmsf_nm"]) for r in src["rmsf"])
