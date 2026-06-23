"""AF-13 Phase 1 — headless oxDNA relaxation wrapper + physical-layer oracle.

Drives the REAL oxDNA job routes (``create_oxdna_job`` → ``start_oxdna_job`` →
poll → ``get_oxdna_display``) from a scratch session, against the MOCK oxDNA binary
(``$OXDNA_BIN``), and proves the foundational Tier-5 property: a headless relaxation
reaches ``completed`` and its relaxed last frame reads back into a full
per-nucleotide position map (``assert_relaxed_geometry_recovered``).

The mock copies the input conf → ``last_conf`` (it does not actually relax), so
``min_bp_retained=0.0`` disables the base-pair-retention gate — this pins the
ORCHESTRATION + geometry recovery, not relaxation quality (covered separately in
``test_oxdna_relaxation.py``).  Real-binary paths stay gated by ``find_oxdna()``.
"""

from __future__ import annotations

import dataclasses
import stat

import pytest

from backend.api import headless_oxdna_build as hox
from backend.core.oxdna_job import OxdnaStatus
from tests.automation_harness import (
    assert_equilibration_timeline,
    assert_field_ready_specimen,
    assert_field_sweep_map,
    assert_fully_sequenced,
    assert_relaxed_geometry_recovered,
    assert_relaxed_measurement,
    oxdna_coverage_report,
)
from tests.conftest import make_6hb_design

# Reuse the mock-binary source + the M13+WC sequencing helper from the oxDNA runner
# tests (a local fixture wraps the mock so pytest discovers it without a
# cross-module fixture import).
from tests.test_oxdna_relaxation import _MOCK_OXDNA, _sequence_for_oxdna


@pytest.fixture
def mock_oxdna(tmp_path, monkeypatch):
    """A fake oxDNA binary (copies the input conf → last_conf, writes energy) bound
    via ``$OXDNA_BIN`` — drives the whole job lifecycle deterministically, no GPU."""
    p = tmp_path / "mock_oxdna.py"
    p.write_text(_MOCK_OXDNA)
    p.chmod(p.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    monkeypatch.setenv("OXDNA_BIN", str(p))
    return p


@pytest.fixture
def sequenced_6hb():
    """A fully-sequenced 6hb (M13 scaffold + WC-complement staples) — oxDNA rejects
    any undefined base, so the design must carry a definite A/C/G/T everywhere."""
    return _sequence_for_oxdna(make_6hb_design())


# ── The wrapper drives a real relaxation + the oracle recovers the geometry ────

def test_run_relaxation_completes_and_recovers_geometry(sequenced_6hb, tmp_path, mock_oxdna):
    job = hox.run_relaxation(sequenced_6hb, tmp_path, min_bp_retained=0.0)
    assert job.status is OxdnaStatus.completed, job.error
    # All three relaxation stages ran.
    assert all(s.status == "done" for s in job.stages)

    display = assert_relaxed_geometry_recovered(job, sequenced_6hb, tmp_path)
    # The recovered map is the full design (the geometry kernel's nucleotide count).
    from backend.core.design_geometry import _geometry_for_design
    assert display["n_positions"] == len(_geometry_for_design(sequenced_6hb))


def test_create_then_start_two_step(sequenced_6hb, tmp_path, mock_oxdna):
    """The lower-level wrappers compose: create (queued, no autostart) → start →
    poll to completed."""
    info = hox.create_job(sequenced_6hb, tmp_path, autostart=False, min_bp_retained=0.0)
    assert info["status"] == "queued"
    hox.start_relaxation(info["job_id"], tmp_path)
    job = hox.wait_for_terminal(info["job_id"], tmp_path)
    assert job.status is OxdnaStatus.completed, job.error
    assert_relaxed_geometry_recovered(job, sequenced_6hb, tmp_path)


def test_append_production_after_completion(sequenced_6hb, tmp_path, mock_oxdna):
    """A completed relaxation can be extended with an unbiased production stage —
    it reaches completed again and the relaxed geometry still reads back."""
    job = hox.run_relaxation(sequenced_6hb, tmp_path, min_bp_retained=0.0)
    assert job.status is OxdnaStatus.completed

    n_stages_before = len(job.stages)
    hox.append_production(job.job_id, tmp_path, steps=1000)
    job = hox.wait_for_terminal(job.job_id, tmp_path)
    assert job.status is OxdnaStatus.completed, job.error
    assert len(job.stages) == n_stages_before + 1
    assert any(s.kind == "production" for s in job.stages)
    assert_relaxed_geometry_recovered(job, sequenced_6hb, tmp_path)


def test_run_field_spawns_child_field_job(sequenced_6hb, tmp_path, mock_oxdna):
    """A field run is a CHILD job branched from the relaxed parent: it links back
    via parent_job_id, runs a single field stage from the relaxed structure, and
    writes a field/anchor forces file (uniform string force + ≥1 trap)."""
    d = sequenced_6hb
    parent = hox.run_relaxation(d, tmp_path, min_bp_retained=0.0)
    assert parent.status is OxdnaStatus.completed
    anchor = {"kind": "domain", "strand_id": d.strands[0].id, "domain_index": 0}
    child_info = hox.append_field(parent.job_id, tmp_path, field_pN=2.0, dir=[1, 0, 0],
                                  anchors=[anchor])
    assert child_info["parent_job_id"] == parent.job_id
    assert child_info["efield"]["force_pN"] == 2.0
    child = hox.wait_for_terminal(child_info["job_id"], tmp_path)
    assert child.status is OxdnaStatus.completed, child.error
    assert [s.kind for s in child.stages] == ["field"]
    text = (child.job_dir(tmp_path) / "field_forces.txt").read_text()
    assert "type = string" in text and "particle = -1" in text   # uniform field
    assert "type = trap" in text                                  # anchor pin


def test_multiple_field_children_from_one_parent(sequenced_6hb, tmp_path, mock_oxdna):
    """The same relaxed parent fans out into several independent field children."""
    d = sequenced_6hb
    parent = hox.run_relaxation(d, tmp_path, min_bp_retained=0.0)
    anchor = {"kind": "domain", "strand_id": d.strands[0].id, "domain_index": 0}
    ids = []
    for pN in (1.0, 4.0):
        info = hox.append_field(parent.job_id, tmp_path, field_pN=pN, dir=[0, 0, 1],
                                anchors=[anchor])
        ids.append(info["job_id"])
        hox.wait_for_terminal(info["job_id"], tmp_path)
    assert len(set(ids)) == 2                       # two distinct child jobs
    from backend.core.oxdna_job import OxdnaJob
    children = [OxdnaJob.load(i, tmp_path) for i in ids]
    assert all(c.parent_job_id == parent.job_id for c in children)
    # A field run CAN now be chained off a completed field child — it seeds from
    # that child's end state, giving a relax → field1 → field2 lineage.
    grandchild = hox.append_field(ids[0], tmp_path, field_pN=2.0, dir=[0, 0, 1], anchors=[anchor])
    hox.wait_for_terminal(grandchild["job_id"], tmp_path)
    assert OxdnaJob.load(grandchild["job_id"], tmp_path).parent_job_id == ids[0]


def test_run_config_persisted_for_panel_cards(sequenced_6hb, tmp_path, mock_oxdna):
    """Both the relaxation parent and an E-field child store run_config so the
    panel can repopulate its cards when the job is selected."""
    from backend.core.oxdna_job import OxdnaJob
    d = sequenced_6hb
    parent = hox.run_relaxation(d, tmp_path, min_bp_retained=0.0)
    prc = OxdnaJob.load(parent.job_id, tmp_path).run_config
    assert prc and prc["kind"] == "relax"
    assert prc["mc_steps"] and prc["md_relax_steps"] and prc["equil_steps"]
    assert prc["min_bp_retained"] == 0.0

    anchor = {"kind": "domain", "strand_id": d.strands[0].id, "domain_index": 0}
    info = hox.append_field(parent.job_id, tmp_path, field_pN=3.0, dir=[1, 0, 0],
                            anchors=[anchor])
    crc = OxdnaJob.load(info["job_id"], tmp_path).run_config
    assert crc and crc["kind"] == "field"
    assert crc["field"]["field_pN"] == 3.0 and crc["field"]["dir"] == [1, 0, 0]
    # Anchor descriptors stored camelCase so the Anchors card re-renders chips.
    assert crc["anchors"] == [{"kind": "domain", "strandId": d.strands[0].id, "domainIndex": 0}]


def test_run_field_rejects_no_anchor(sequenced_6hb, tmp_path, mock_oxdna):
    """An electric-field stage with no anchor is refused (HTTP 400) — without an
    anchor the field just drifts the whole structure."""
    from fastapi import HTTPException
    job = hox.run_relaxation(sequenced_6hb, tmp_path, min_bp_retained=0.0)
    assert job.status is OxdnaStatus.completed
    with pytest.raises(HTTPException) as exc:
        hox.append_field(job.job_id, tmp_path, field_pN=2.0, dir=[1, 0, 0], anchors=[])
    assert exc.value.status_code == 400


# ── E-field VALIDATION (deflecting mock → oracle) ─────────────────────────────
# A field-aware mock oxDNA binary: for a stage whose forces file carries the
# uniform `string` field block, it shifts every NON-anchored particle along the
# field direction (∝ F0) and leaves the trapped (anchored) particles fixed —
# simulating the field-driven deflection a real GPU run produces, so the whole
# validation pipeline (relax → field → oracle) is automatable without a GPU.
_FIELD_MOCK_OXDNA = '''#!/usr/bin/env python3
import sys, re, shutil
from pathlib import Path
inp = Path(sys.argv[1]); text = inp.read_text()
def val(k):
    m = re.search(r"^" + k + r"\\s*=\\s*(.+)$", text, re.M)
    return m.group(1).strip() if m else None
conf = Path(val("conf_file"))
lastconf = val("lastconf_file") or "last_conf.dat"
energy = val("energy_file") or "energy.dat"
steps = int(val("steps") or "100")
cwd = Path.cwd()
ff = val("external_forces_file")
ftxt = Path(ff).read_text() if ff and Path(ff).exists() else ""
trapped = set(int(m) for m in re.findall(r"type = trap\\nparticle = (\\d+)", ftxt))
sm = re.search(r"type = string\\nparticle = -1\\nF0 = ([-\\d.eE]+)\\nrate = [-\\d.eE]+\\ndir = ([-\\d.eE,]+)", ftxt)
lines = conf.read_text().splitlines()
out = []; idx = 0
if sm:
    F0 = float(sm.group(1))
    dx, dy, dz = (float(x) for x in sm.group(2).split(","))
    sc = 200.0
    sh = (sc * F0 * dx, sc * F0 * dy, sc * F0 * dz)
    for ln in lines:
        if ln.startswith(("t ", "b ", "E ")) or not ln.strip():
            out.append(ln); continue
        p = ln.split()
        if idx not in trapped:
            p[0] = repr(float(p[0]) + sh[0])
            p[1] = repr(float(p[1]) + sh[1])
            p[2] = repr(float(p[2]) + sh[2])
        out.append(" ".join(p)); idx += 1
    (cwd / lastconf).write_text("\\n".join(out) + "\\n")
else:
    shutil.copy(conf, cwd / lastconf)
n = max(1, steps // 100)
with open(cwd / energy, "w") as f:
    for i in range(n):
        f.write(f"{i} {-1.5 - 0.001 * i} 0.5 -1.0\\n")
'''


@pytest.fixture
def mock_oxdna_field(tmp_path, monkeypatch):
    p = tmp_path / "mock_oxdna_field.py"
    p.write_text(_FIELD_MOCK_OXDNA)
    p.chmod(p.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    monkeypatch.setenv("OXDNA_BIN", str(p))
    return p


def _design_with_overhang_anchor(overhang_id="ov_anchor"):
    """A sequenced design with one staple domain tagged as a ssDNA overhang anchor.

    The eventual physics validation is a single duplex with a ssDNA overhang end
    pinned as the anchor; here we tag a known-correct 6hb staple domain rather than
    hand-building duplex topology (CLAUDE.md 'DNA Topology — Ask First').  The
    anchor-resolution + oracle exercised are identical for the real fixture."""
    d = _sequence_for_oxdna(make_6hb_design())
    for s in d.strands:
        if not s.id.startswith("scaf"):
            s.domains[0].overhang_id = overhang_id
            return d, s.domains[0]
    raise AssertionError("no staple strand to tag as an overhang anchor")


def test_field_validation_oracle_passes_with_deflecting_mock(tmp_path, mock_oxdna_field):
    """End-to-end automatable validation: relax → field (overhang anchored) →
    the oracle confirms the anchor held and the rest deflected ALONG the field."""
    d, dom = _design_with_overhang_anchor()
    n_anchor = abs(dom.end_bp - dom.start_bp) + 1
    out = hox.run_field_validation(
        d, tmp_path, field_pN=2.0, dir=[0, 0, 1],
        anchors=[{"kind": "overhang", "id": "ov_anchor"}], min_bp_retained=0.0)
    assert out["job"].status is OxdnaStatus.completed, out["job"].error
    r = out["response"]
    assert r is not None and r["n_anchored"] == n_anchor
    assert r["passed"] is True, r["reason"]
    assert r["anchored_max_drift_nm"] < 0.01          # overhang held by its traps
    assert r["free_proj_along_field_nm"] > 1.0        # rest deflected along +z


def test_field_validation_deflection_scales_with_field(tmp_path, mock_oxdna_field):
    """Stronger field → larger deflection in the same step budget — the automatable
    proxy for 'aligns faster at higher field magnitude' (the real time-vs-magnitude
    relationship needs a GPU run; the monotonic direction is pinned here)."""
    anchors = [{"kind": "overhang", "id": "ov_anchor"}]
    weak = hox.run_field_validation(_design_with_overhang_anchor()[0], tmp_path,
                                    field_pN=2.0, dir=[0, 0, 1], anchors=anchors,
                                    min_bp_retained=0.0)["response"]
    strong = hox.run_field_validation(_design_with_overhang_anchor()[0], tmp_path,
                                      field_pN=8.0, dir=[0, 0, 1], anchors=anchors,
                                      min_bp_retained=0.0)["response"]
    assert strong["free_proj_along_field_nm"] > weak["free_proj_along_field_nm"]


# ── AF-18 (Tier 6): full-pipeline anchored field-specimen builder ─────────────

def test_build_field_specimen_is_field_ready(tmp_path, mock_oxdna_field):
    """The composite builder takes a (sequenced) design → relaxed, anchored specimen,
    and the composite oracle confirms all three field-ready clauses end-to-end:
    fully sequenced + relaxed geometry recovered + a probe field holds the anchor
    while the rest deflects."""
    d, _dom = _design_with_overhang_anchor()
    anchor = {"kind": "overhang", "id": "ov_anchor"}
    result = hox.build_field_specimen(
        d, tmp_path, anchor=anchor, sequence=False, min_bp_retained=0.0)
    assert result["job"].status is OxdnaStatus.completed, result["job"].error
    assert result["anchor"] == anchor and result["anchor_keys"]

    out = assert_field_ready_specimen(result, result["design"], tmp_path)
    assert out["n_anchored"] == len(result["anchor_keys"])
    assert out["field_response"]["passed"] is True


def test_build_field_specimen_sequences_an_unsequenced_design(tmp_path, mock_oxdna_field):
    """The ``sequence=True`` branch genuinely sequences: a ROUTED-but-UNSEQUENCED 6hb
    (single scaffold, sequences stripped) comes out fully sequenced + relaxed +
    anchorable — proving the full_sequence step in the chain ran, not a passthrough."""
    from backend.api import headless_spec_build as hs
    from backend.physics.oxdna_interface import count_undefined_bases

    cells = [[0, 1], [1, 1], [1, 2], [1, 3], [0, 3], [0, 2]]   # SIX_HB_CELLS
    spec = {"lattice": "honeycomb", "ops": [
        {"op": "bundle", "cells": cells, "length_bp": 42},
        {"op": "auto_scaffold"}, {"op": "full_autostaple"}]}
    routed = hs.build_design(spec)
    # Strip every assigned sequence → routed (single scaffold) but unsequenced; tag a
    # known staple domain as the anchor (which nucleotides anchor is declared, never
    # inferred), and it survives full_sequence (a sequence-only step).
    stripped = routed.model_copy(update={"strands": [
        s.model_copy(update={"sequence": None}) for s in routed.strands]})
    # A domain anchor (which staple domain anchors is declared, never inferred) — no
    # overhang tag, so full_sequence WC-completes every staple position.
    anchor_strand = next(s for s in stripped.strands if not s.id.startswith("scaf"))
    anchor = {"kind": "domain", "strand_id": anchor_strand.id, "domain_index": 0}
    undefined_before, total = count_undefined_bases(stripped, exclude_reference=True)
    assert undefined_before > 0 and total > 0   # genuinely unsequenced going in

    result = hox.build_field_specimen(
        stripped, tmp_path, anchor=anchor, sequence=True, min_bp_retained=0.0)
    assert result["job"].status is OxdnaStatus.completed, result["job"].error
    # The output is fully sequenced (the chain's full_sequence step did the work —
    # it went in with 630 undefined bases and came out export/oxDNA-ready), and the
    # anchor resolved on the final design.  (The full composite oracle's strict
    # geometry-key-equality clause is exact only for densely-populated bundles like
    # the test_a fixture — a routed scaffold leaves lattice slots strand-less — so
    # this branch test proves the sequence step, not that clause.)
    assert_fully_sequenced(result["design"])
    assert result["anchor_keys"]


def test_build_field_specimen_from_build_spec(tmp_path, mock_oxdna_field):
    """The build-spec branch: a declarative design spec is lowered via
    ``headless_spec_build.build_design`` then sequenced/relaxed/anchored — proving
    ``build_field_specimen`` accepts the text-to-design grammar's output, not only a
    pre-built Design."""
    cells = [[0, 1], [1, 1], [1, 2], [1, 3], [0, 3], [0, 2]]   # SIX_HB_CELLS
    spec = {
        "lattice": "honeycomb",
        "ops": [
            {"op": "bundle", "cells": cells, "length_bp": 42},
            {"op": "auto_scaffold"},
            {"op": "full_autostaple"},
        ],
    }
    # Discover a staple to anchor (build is deterministic, so the same id reappears).
    from backend.api import headless_spec_build as hs
    built = hs.build_design(spec)
    staple = next(s for s in built.strands if not s.id.startswith("scaf"))
    anchor = {"kind": "domain", "strand_id": staple.id, "domain_index": 0}

    result = hox.build_field_specimen(
        spec, tmp_path, anchor=anchor, sequence=True, min_bp_retained=0.0)
    assert result["job"].status is OxdnaStatus.completed, result["job"].error
    assert result["anchor_keys"], "build-spec specimen resolved no anchor"
    # The dict was lowered through headless_spec_build.build_design → identical
    # topology to a direct build of the same spec (the build-spec branch dispatched).
    from tests.automation_harness import canonical_topology
    assert canonical_topology(result["design"]) == canonical_topology(built)


def test_build_field_specimen_rejects_unresolvable_anchor(tmp_path, mock_oxdna):
    """An anchor descriptor that resolves to no nucleotides is refused up front —
    an un-anchorable specimen is not field-ready (the COM-drift gotcha)."""
    d, _dom = _design_with_overhang_anchor()
    with pytest.raises(ValueError, match="resolved to no nucleotides"):
        hox.build_field_specimen(
            d, tmp_path, anchor={"kind": "overhang", "id": "does_not_exist"},
            sequence=False, min_bp_retained=0.0)


# ── Red-tests: the oracle CAN go red ──────────────────────────────────────────

def test_oracle_fires_on_non_completed_job(sequenced_6hb, tmp_path, mock_oxdna):
    """A job that did not reach completed raises the status guard."""
    job = hox.run_relaxation(sequenced_6hb, tmp_path, min_bp_retained=0.0)
    not_done = dataclasses.replace(job, status=OxdnaStatus.failed, error="boom")
    with pytest.raises(AssertionError, match="did not reach completed"):
        assert_relaxed_geometry_recovered(not_done, sequenced_6hb, tmp_path)


def test_oracle_fires_on_wrong_count(sequenced_6hb, tmp_path, mock_oxdna):
    """If fewer/more positions come back than design nucleotides, the count check
    raises (a truncated / dropped conf would trip this)."""
    job = hox.run_relaxation(sequenced_6hb, tmp_path, min_bp_retained=0.0)
    from backend.core.design_geometry import _geometry_for_design
    inflated = len(_geometry_for_design(sequenced_6hb)) + 5
    with pytest.raises(AssertionError, match="expected"):
        assert_relaxed_geometry_recovered(job, sequenced_6hb, tmp_path,
                                          expected_count=inflated)


def test_field_ready_oracle_fires_on_unsequenced_specimen(tmp_path, mock_oxdna_field):
    """The composite oracle's clause 1 goes red on an unsequenced design (oxDNA
    refuses to relax undefined bases, so the only way to exercise clause 1 is to hand
    the oracle a raw, unsequenced design — the fully-sequenced gate fires first)."""
    d, _dom = _design_with_overhang_anchor()
    result = hox.build_field_specimen(
        d, tmp_path, anchor={"kind": "overhang", "id": "ov_anchor"},
        sequence=False, min_bp_retained=0.0)
    with pytest.raises(AssertionError, match="undefined"):
        assert_field_ready_specimen(result, make_6hb_design(), tmp_path)


def test_field_ready_oracle_fires_on_empty_anchor(tmp_path, mock_oxdna_field):
    """Clause 3 goes red: a specimen with no resolved anchor is not field-ready
    (a uniform field would stream the whole structure)."""
    d, _dom = _design_with_overhang_anchor()
    result = hox.build_field_specimen(
        d, tmp_path, anchor={"kind": "overhang", "id": "ov_anchor"},
        sequence=False, min_bp_retained=0.0)
    result["anchor_keys"] = []          # simulate an un-anchorable specimen
    with pytest.raises(AssertionError, match="no anchor"):
        assert_field_ready_specimen(result, result["design"], tmp_path)


# ── AF-19 (Tier 6): field equilibration-timeline τ + non-melt oracle ───────────

def _resolve_anchor_keys(design, anchor):
    from backend.physics.oxdna_interface import resolve_anchor_particles
    _parts, keys = resolve_anchor_particles(design, [anchor])
    return keys


def test_equilibration_timeline_extracts_finite_tau(tmp_path, mock_oxdna_field_traj):
    """End-to-end: relax → field (overhang anchored) → the time-resolved oracle
    finds a finite positive τ, a monotone approach to a stable plateau, and no melt
    across the whole field trajectory."""
    d, _dom = _design_with_overhang_anchor()
    anchor = {"kind": "overhang", "id": "ov_anchor"}
    keys = _resolve_anchor_keys(d, anchor)
    job = hox.run_field(d, tmp_path, field_pN=4.0, dir=[0, 0, 1], anchors=[anchor],
                        field_steps=2000, min_bp_retained=0.0)
    assert job.status is OxdnaStatus.completed, job.error

    out = assert_equilibration_timeline(
        job, tmp_path, [0, 0, 1], keys, design=d, melt_floor=0.5)
    assert out["converged"] is True
    assert out["tau_steps"] is not None and out["tau_steps"] > 0
    assert out["melted"] is False
    assert out["bp_min"] >= 0.5
    # The free body actually rose and saturated (the timeline isn't a flat line).
    assert out["aligned_final"] > out["alignment_timecourse"][0] + 0.5


def test_equilibration_timeline_inconclusive_on_short_run(tmp_path, mock_oxdna_field_traj):
    """The confidence gate fires: too few field frames → INCONCLUSIVE-raise."""
    d, _dom = _design_with_overhang_anchor()
    anchor = {"kind": "overhang", "id": "ov_anchor"}
    keys = _resolve_anchor_keys(d, anchor)
    # field_steps=1000 → 10 trajectory frames (the 1000-step FieldRequest minimum);
    # a min_confidence of 15 is unreachable → the gate fires.
    job = hox.run_field(d, tmp_path, field_pN=4.0, dir=[0, 0, 1], anchors=[anchor],
                        field_steps=1000, min_bp_retained=0.0)
    assert job.status is OxdnaStatus.completed, job.error
    with pytest.raises(AssertionError, match="INCONCLUSIVE"):
        assert_equilibration_timeline(
            job, tmp_path, [0, 0, 1], keys, design=d, melt_floor=0.5,
            min_confidence=15)


# Pure-measure unit tests — hand-built frames pin the τ / plateau / monotone /
# melt logic independent of the mock binary (the measure is the load-bearing core).

def _frame_from(positions_by_key, a1=(1.0, 0.0, 0.0)):
    """Build a read_trajectory_frames_full-shaped frame map from {key: xyz_nm}."""
    import numpy as np
    return {k: {"backbone_position": np.asarray(v, dtype=float),
                "a1": np.asarray(a1, dtype=float),
                "a3": np.asarray((0.0, 0.0, 1.0), dtype=float)}
            for k, v in positions_by_key.items()}


def _ramp_frames(n, plateau_nm, k, *, free_key, anchor_key, bp_floor_at=None):
    """n saturating frames: the free bead ramps along +z, the anchor bead is held.
    If ``bp_floor_at`` is set, the free bead's WC partner is yanked away at that
    frame (a transient melt) by separating their base sites."""
    import math as _m
    frames = []
    for i in range(n):
        factor = 1.0 - _m.exp(-i / k)
        z = plateau_nm * factor
        pos = {anchor_key: (0.0, 0.0, 0.0),
               free_key: (0.0, 0.0, z),
               # free_key's WC partner sits at the same site (paired) unless melted.
               (free_key[0], free_key[1], "REVERSE"): (0.0, 0.0, z)}
        if bp_floor_at is not None and i >= bp_floor_at:
            pos[(free_key[0], free_key[1], "REVERSE")] = (0.0, 5.0, z)  # ripped apart
        frames.append(_frame_from(pos))
    return frames


def test_measure_field_equilibration_pure_converges():
    """A saturating ramp → converged, finite τ near the time constant, full bp."""
    from backend.core.oxdna_health import measure_field_equilibration
    free = ("h0", 0, "FORWARD")
    anch = ("h0", 99, "FORWARD")
    frames = _ramp_frames(20, plateau_nm=4.0, k=5.0, free_key=free, anchor_key=anch)
    # design only used for base_pair_retention; the frames carry the pairing.
    d = make_6hb_design()
    out = measure_field_equilibration(
        frames, [0, 0, 1], [anch], design=d, steps_per_frame=100.0, melt_floor=0.5)
    assert out["converged"] is True
    assert out["tau_frames"] is not None
    assert 3.0 <= out["tau_frames"] <= 7.0            # 1−1/e crossing ≈ k=5
    assert out["tau_steps"] == out["tau_frames"] * 100.0
    assert out["melted"] is False


def test_measure_field_equilibration_pure_non_converging():
    """A LINEAR (never-plateau) ramp → no finite τ (can-go-red clause)."""
    from backend.core.oxdna_health import measure_field_equilibration
    free = ("h0", 0, "FORWARD")
    anch = ("h0", 99, "FORWARD")
    frames = []
    for i in range(20):
        pos = {anch: (0.0, 0.0, 0.0), free: (0.0, 0.0, 0.5 * i),
               ("h0", 0, "REVERSE"): (0.0, 0.0, 0.5 * i)}
        frames.append(_frame_from(pos))
    out = measure_field_equilibration(
        frames, [0, 0, 1], [anch], design=make_6hb_design(), melt_floor=0.5)
    assert out["converged"] is False
    assert out["tau_steps"] is None
    assert "plateau" in out["reason"]


def test_measure_field_equilibration_pure_detects_melt():
    """bp retention dips below the floor mid-swing → melted=True (the transient-melt
    watch measure_field_response is blind to)."""
    from backend.core.oxdna_health import measure_field_equilibration
    free = ("h0", 0, "FORWARD")
    anch = ("h0", 99, "FORWARD")
    frames = _ramp_frames(20, plateau_nm=4.0, k=5.0, free_key=free, anchor_key=anch,
                          bp_floor_at=8)
    out = measure_field_equilibration(
        frames, [0, 0, 1], [anch], design=make_6hb_design(), melt_floor=0.5)
    # The single designed pair breaks at frame 8 → retention 1.0 → 0.0 < floor.
    assert out["melted"] is True
    assert out["bp_min"] < 0.5


def test_measure_field_equilibration_requires_two_frames():
    from backend.core.oxdna_health import measure_field_equilibration
    one = _ramp_frames(1, 4.0, 5.0, free_key=("h0", 0, "FORWARD"),
                       anchor_key=("h0", 99, "FORWARD"))
    with pytest.raises(ValueError, match="two trajectory frames"):
        measure_field_equilibration(one, [0, 0, 1], [], design=make_6hb_design())


# ── Function-identity coverage: the wrappers drive the real route handlers ─────

def test_oxdna_coverage_report_marks_af13_routes_covered():
    """The wrappers register their /oxdna routes as covered (function-identity)."""
    report = oxdna_coverage_report()
    assert report["total"] == report["covered"] + report["uncovered"]
    covered = {r["endpoint"] for r in report["covered_routes"]}
    # The three /oxdna MUTATION routes the wrappers drive (get_oxdna_display is a
    # read-only GET, excluded from a mutation audit — pinned by the import test).
    assert {"create_oxdna_job", "start_oxdna_job",
            "append_oxdna_production", "append_oxdna_field"} <= covered


def test_wrappers_import_exact_route_handlers():
    """Anti-passthrough: the wrappers reference the actual route handler objects,
    not re-implementations."""
    from backend.api import routes_oxdna

    assert hox._route_create_oxdna_job is routes_oxdna.create_oxdna_job
    assert hox._route_start_job is routes_oxdna.start_oxdna_job
    assert hox._route_append_production is routes_oxdna.append_oxdna_production
    assert hox._route_append_field is routes_oxdna.append_oxdna_field
    assert hox._route_get_display is routes_oxdna.get_oxdna_display
    assert hox._route_get_rmsf is routes_oxdna.get_oxdna_rmsf


# ── AF-13 Phase 2: the relaxed-geometry MEASUREMENT oracle ─────────────────────
# A purpose-built mock that, unlike _MOCK_OXDNA, ALSO writes a multi-frame
# trajectory.dat (the input conf repeated `max(1, steps//100)` times) so the
# production rmsf route has frames to pool into a mean structure + confidence.
# The "relaxation" is still identity (last_conf == input conf), so the relaxed
# mean structure equals the design geometry — letting the test assert the
# measured end-to-end distance against the design's own end-to-end (the mock
# can't move anything, so the physical-layer measurement pipeline must preserve
# it).  A real GPU run would move atoms; here we pin the measurement machinery.
_MOCK_OXDNA_TRAJ = '''#!/usr/bin/env python3
import sys, re, shutil
from pathlib import Path
inp = Path(sys.argv[1]); text = inp.read_text()
def val(key):
    m = re.search(r"^" + key + r"\\s*=\\s*(.+)$", text, re.M)
    return m.group(1).strip() if m else None
conf = val("conf_file")
lastconf = val("lastconf_file") or "last_conf.dat"
energy = val("energy_file") or "energy.dat"
traj = val("trajectory_file") or "trajectory.dat"
steps = int(val("steps") or "100")
cwd = Path.cwd()
shutil.copy(conf, cwd / lastconf)             # identity "relaxation"
lines = Path(conf).read_text().splitlines()
hdr = lines[:3]; data = [l for l in lines[3:] if l.strip()]
n_frames = max(1, steps // 100)               # control pooled frames via `steps`
with open(cwd / traj, "w") as f:
    for _ in range(n_frames):
        f.write("\\n".join(hdr + data) + "\\n")
with open(cwd / energy, "w") as f:
    for i in range(n_frames):
        f.write(f"{i} {-1.5 - 0.001*i} 0.5 -1.0\\n")
'''


@pytest.fixture
def mock_oxdna_traj(tmp_path, monkeypatch):
    """A fake oxDNA binary that also emits a multi-frame trajectory.dat (frames =
    ``max(1, steps//100)``), so the production rmsf/mean-structure route works."""
    p = tmp_path / "mock_oxdna_traj.py"
    p.write_text(_MOCK_OXDNA_TRAJ)
    p.chmod(p.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    monkeypatch.setenv("OXDNA_BIN", str(p))
    return p


# ── AF-19 (Tier 6): a field mock that emits a TIME-RESOLVED trajectory ─────────
# Unlike _FIELD_MOCK_OXDNA (single shifted last_conf) this writes a multi-frame
# trajectory.dat where the free (non-trapped) beads ramp along the field with a
# SATURATING profile (shift_i = plateau·(1−exp(−i/k))) — a synthetic monotone
# approach to equilibrium with a finite τ.  The plateau ∝ F0, so a stronger field
# saturates further (reused by the AF-20 sweep).  Base pairs translate together,
# so retention stays high (no melt) — the can-go-red melt/non-converge cases are
# exercised on hand-built frames against the pure measure.
_FIELD_TRAJ_MOCK_OXDNA = '''#!/usr/bin/env python3
import sys, re, math
from pathlib import Path
inp = Path(sys.argv[1]); text = inp.read_text()
def val(k):
    m = re.search(r"^" + k + r"\\s*=\\s*(.+)$", text, re.M)
    return m.group(1).strip() if m else None
conf = Path(val("conf_file"))
lastconf = val("lastconf_file") or "last_conf.dat"
energy = val("energy_file") or "energy.dat"
traj = val("trajectory_file") or "trajectory.dat"
steps = int(val("steps") or "100")
cwd = Path.cwd()
ff = val("external_forces_file")
ftxt = Path(ff).read_text() if ff and Path(ff).exists() else ""
trapped = set(int(m) for m in re.findall(r"type = trap\\nparticle = (\\d+)", ftxt))
sm = re.search(r"type = string\\nparticle = -1\\nF0 = ([-\\d.eE]+)\\nrate = [-\\d.eE]+\\ndir = ([-\\d.eE,]+)", ftxt)
lines = conf.read_text().splitlines()
hdr = lines[:3]
data = [l for l in lines[3:] if l.strip()]
n_frames = max(2, steps // 100)
if sm:
    F0 = float(sm.group(1))
    dx, dy, dz = (float(x) for x in sm.group(2).split(","))
    sc = 100.0
    pk = (sc * F0 * dx, sc * F0 * dy, sc * F0 * dz)
else:
    pk = (0.0, 0.0, 0.0)
k = max(1.0, n_frames / 4.0)
frames_txt = []
for fi in range(n_frames):
    factor = 1.0 - math.exp(-fi / k)
    sh = (pk[0] * factor, pk[1] * factor, pk[2] * factor)
    out = ["t = " + str(fi), hdr[1], hdr[2]]
    idx = 0
    for ln in data:
        p = ln.split()
        if idx not in trapped:
            p[0] = repr(float(p[0]) + sh[0])
            p[1] = repr(float(p[1]) + sh[1])
            p[2] = repr(float(p[2]) + sh[2])
        out.append(" ".join(p)); idx += 1
    frames_txt.append("\\n".join(out))
(cwd / traj).write_text("\\n".join(frames_txt) + "\\n")
(cwd / lastconf).write_text("\\n".join(frames_txt[-1].splitlines()) + "\\n")
with open(cwd / energy, "w") as f:
    for i in range(n_frames):
        f.write(f"{i} {-1.5 - 0.001 * i} 0.5 -1.0\\n")
'''


@pytest.fixture
def mock_oxdna_field_traj(tmp_path, monkeypatch):
    """A fake oxDNA binary whose field stage emits a multi-frame trajectory.dat
    with a saturating monotone alignment ramp (AF-19 equilibration timeline)."""
    p = tmp_path / "mock_oxdna_field_traj.py"
    p.write_text(_FIELD_TRAJ_MOCK_OXDNA)
    p.chmod(p.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    monkeypatch.setenv("OXDNA_BIN", str(p))
    return p


# ── AF-20 (Tier 6): a field mock whose τ AND melt depend on |E| ────────────────
# Richer than _FIELD_TRAJ_MOCK_OXDNA (whose time constant k is field-independent):
# here the saturating ramp's time constant k DECREASES with F0 (a stronger field
# equilibrates faster → smaller τ), and above a destructive F0 threshold the free
# (non-trapped) cloud is dilated about its own centroid by a factor (1+s) that ramps
# in with the swing — every free base-pair separation scales by (1+s), so above the
# threshold the structure melts (base-pair retention → 0) mid-swing.  The dilation
# is about the free centroid, so it cancels in the MEAN along-field projection
# (mean(orig−C)=0) → alignment still saturates ∝F0 and still plateaus; only the
# per-pair distances (hence bp retention) change.  This gives the AF-20 sweep a
# substrate where BOTH τ↔|E| (decreasing) and the destructive window vary with |E|.
_FIELD_SWEEP_MOCK_OXDNA = '''#!/usr/bin/env python3
import sys, re, math
from pathlib import Path
inp = Path(sys.argv[1]); text = inp.read_text()
def val(k):
    m = re.search(r"^" + k + r"\\s*=\\s*(.+)$", text, re.M)
    return m.group(1).strip() if m else None
conf = Path(val("conf_file"))
lastconf = val("lastconf_file") or "last_conf.dat"
energy = val("energy_file") or "energy.dat"
traj = val("trajectory_file") or "trajectory.dat"
steps = int(val("steps") or "100")
cwd = Path.cwd()
ff = val("external_forces_file")
ftxt = Path(ff).read_text() if ff and Path(ff).exists() else ""
trapped = set(int(m) for m in re.findall(r"type = trap\\nparticle = (\\d+)", ftxt))
sm = re.search(r"type = string\\nparticle = -1\\nF0 = ([-\\d.eE]+)\\nrate = [-\\d.eE]+\\ndir = ([-\\d.eE,]+)", ftxt)
lines = conf.read_text().splitlines()
hdr = lines[:3]
data = [l for l in lines[3:] if l.strip()]
n_frames = max(2, steps // 100)
if sm:
    F0 = float(sm.group(1))
    dx, dy, dz = (float(x) for x in sm.group(2).split(","))
    sc = 100.0
    pk = (sc * F0 * dx, sc * F0 * dy, sc * F0 * dz)
    k = max(1.3, 4.5 - 12.0 * F0)            # stronger field -> smaller k -> smaller tau
    s_max = 2.0 if F0 >= 0.4 else 0.0        # above threshold: dilate -> melt
else:
    F0 = 0.0; pk = (0.0, 0.0, 0.0); k = max(1.0, n_frames / 4.0); s_max = 0.0
# centroid of the free (non-trapped) beads' original positions
free_xyz = [[float(x) for x in l.split()[:3]]
            for i, l in enumerate(data) if i not in trapped]
if free_xyz:
    cx = sum(p[0] for p in free_xyz) / len(free_xyz)
    cy = sum(p[1] for p in free_xyz) / len(free_xyz)
    cz = sum(p[2] for p in free_xyz) / len(free_xyz)
else:
    cx = cy = cz = 0.0
frames_txt = []
for fi in range(n_frames):
    factor = 1.0 - math.exp(-fi / k)
    sh = (pk[0] * factor, pk[1] * factor, pk[2] * factor)
    s = s_max * factor
    out = ["t = " + str(fi), hdr[1], hdr[2]]
    idx = 0
    for ln in data:
        p = ln.split()
        if idx not in trapped:
            ox, oy, oz = float(p[0]), float(p[1]), float(p[2])
            p[0] = repr(cx + (ox - cx) * (1.0 + s) + sh[0])
            p[1] = repr(cy + (oy - cy) * (1.0 + s) + sh[1])
            p[2] = repr(cz + (oz - cz) * (1.0 + s) + sh[2])
        out.append(" ".join(p)); idx += 1
    frames_txt.append("\\n".join(out))
(cwd / traj).write_text("\\n".join(frames_txt) + "\\n")
(cwd / lastconf).write_text("\\n".join(frames_txt[-1].splitlines()) + "\\n")
with open(cwd / energy, "w") as f:
    for i in range(n_frames):
        f.write(f"{i} {-1.5 - 0.001 * i} 0.5 -1.0\\n")
'''


@pytest.fixture
def mock_oxdna_field_sweep(tmp_path, monkeypatch):
    """A fake oxDNA binary whose field stage gives a τ that DECREASES with |E| and a
    melt (base-pair break) above a destructive threshold (AF-20 sweep substrate)."""
    p = tmp_path / "mock_oxdna_field_sweep.py"
    p.write_text(_FIELD_SWEEP_MOCK_OXDNA)
    p.chmod(p.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    monkeypatch.setenv("OXDNA_BIN", str(p))
    return p


def _sweep_specimen(tmp_path):
    """Build a relaxed specimen anchored on a REAL extruded ssDNA overhang (12 nt),
    given a structure-safe random sequence so no base is undefined.

    This is the correct field experimental setup: the anchor is a genuine
    single-stranded overhang tip (the whole overhang domain is pinned), NOT a regular
    duplex domain buried in the bundle.  ``extrude_valid_overhang`` delegates to the
    geometry oracle (``overhang_candidate_error``) so the overhang lands exactly where
    the UI overhang tool would offer it (CLAUDE.md 'DNA Topology — Ask First': the
    site is chosen by the validated oracle, not reasoned about here).

    ``make_6hb_design`` is multi-scaffold, so it is sequenced with ``_sequence_for_oxdna``
    (which WC-complements staples per (helix, bp) across all scaffolds); the extruded
    overhang's ssDNA has no WC partner, so it is given a fixed random sequence so no
    base is undefined (the simulation guard requires a definite base on every
    nucleotide)."""
    from tests.conftest import extrude_valid_overhang

    base = _sequence_for_oxdna(make_6hb_design())
    d, ovhg_id = extrude_valid_overhang(base, length_bp=12)
    d = _define_overhang_bases(d, ovhg_id, seed=20240623)
    anchor = {"kind": "overhang", "id": ovhg_id}
    result = hox.build_field_specimen(
        d, tmp_path, anchor=anchor, sequence=False, min_bp_retained=0.0)
    assert result["job"].status is OxdnaStatus.completed, result["job"].error
    return result


def _define_overhang_bases(design, overhang_id, *, seed):
    """Fill the overhang domain's slice of its parent strand's (domain-order) sequence
    with fixed random A/C/G/T, leaving every other base unchanged → no undefined base.
    Pure index arithmetic on the documented 5′→3′ domain-order layout (no geometry)."""
    import random
    rng = random.Random(seed)
    new_strands = []
    for s in design.strands:
        oh_idx = next((i for i, dm in enumerate(s.domains)
                       if dm.overhang_id == overhang_id), None)
        if oh_idx is None or not s.sequence:
            new_strands.append(s)
            continue
        offset = sum(abs(dm.end_bp - dm.start_bp) + 1 for dm in s.domains[:oh_idx])
        dm = s.domains[oh_idx]
        length = abs(dm.end_bp - dm.start_bp) + 1
        chars = list(s.sequence)
        for j in range(offset, offset + length):
            chars[j] = rng.choice("ACGT")
        new_strands.append(s.model_copy(update={"sequence": "".join(chars)}))
    return design.model_copy(update={"strands": new_strands})


def test_field_sweep_maps_response_surface(tmp_path, mock_oxdna_field_sweep):
    """The full AF-20 path: sweep |E| × direction off one relaxed specimen → a
    complete map with a non-destructive operating window, a destructive upper bound,
    and a τ that decreases with |E| (the field↔equilibration correlation)."""
    specimen = _sweep_specimen(tmp_path)
    sweep = hox.sweep_field_response(
        specimen, [2.0, 4.0, 8.0, 16.0, 32.0], [(0, 0, 1), (0, 1, 0)], tmp_path,
        field_steps=2000, melt_floor=0.5, min_confidence=10)

    assert not sweep["skipped"]
    assert len(sweep["map"]) == 5 * 2
    summary = assert_field_sweep_map(
        sweep, benign_range=(0.0, 20.0), destructive_range=(24.0, 1e9),
        melt_floor=0.5)
    assert summary["n_directions_checked"] == 2
    assert summary["n_benign_safe"] >= 1
    # The 32 pN cells melted (destructive upper bound); the 2 pN cells held.
    assert sweep["map"][(32.0, (0.0, 0.0, 1.0))]["destructive"] is True
    assert sweep["map"][(2.0, (0.0, 0.0, 1.0))]["destructive"] is False
    # τ fell monotonically across the responsive band (per direction).
    band = sorted((pN, c["tau_steps"]) for (pN, d), c in sweep["map"].items()
                  if d == (0.0, 0.0, 1.0) and not c["destructive"])
    taus = [t for _pN, t in band]
    assert taus == sorted(taus, reverse=True) and taus[0] > taus[-1]


def _sweep_cell(*, tau, destructive=False, aligned=True, bp_min=1.0):
    return {"tau_steps": tau, "tau_frames": (tau / 100.0 if tau else None),
            "converged": aligned, "aligned": aligned, "bp_min": bp_min,
            "bp_final": bp_min, "n_frames": 20, "melted": bp_min < 0.5,
            "confident": True, "destructive": destructive}


def test_field_sweep_oracle_fires_on_flat_tau():
    """Can-go-red (clause 4): a field-INDEPENDENT τ (flat across |E|) → the field↔τ
    correlation clause fires.  Hand-built so clauses 1-3 pass (a real safe window +
    a melted upper bound) and ONLY the flat-τ clause can fire — the AF-19 mock can't
    be reused here (it never melts → no destructive cell to satisfy clause 3)."""
    d = (0.0, 0.0, 1.0)
    sweep = {
        "map": {(2.0, d): _sweep_cell(tau=300.0),
                (4.0, d): _sweep_cell(tau=300.0),       # flat — same τ as 2 pN
                (8.0, d): _sweep_cell(tau=300.0),
                (32.0, d): _sweep_cell(tau=300.0, destructive=True, bp_min=0.0)},
        "skipped": [], "intensities_pN": [2.0, 4.0, 8.0, 32.0],
        "directions": [d], "melt_floor": 0.5}
    with pytest.raises(AssertionError, match="flat across"):
        assert_field_sweep_map(sweep, benign_range=(0.0, 20.0),
                               destructive_range=(24.0, 1e9), melt_floor=0.5)


def test_field_sweep_oracle_fires_on_unbounded_window(tmp_path, mock_oxdna_field_sweep):
    """Can-go-red (clause 3): calling the oracle with a destructive range over cells
    that did NOT melt (all ≤ the threshold) → the 'window not bounded above' fires."""
    specimen = _sweep_specimen(tmp_path)
    sweep = hox.sweep_field_response(
        specimen, [2.0, 4.0, 8.0, 16.0], [(0, 0, 1)], tmp_path,
        field_steps=2000, melt_floor=0.5, min_confidence=10)
    with pytest.raises(AssertionError, match="did\\s+NOT melt|not bounded above"):
        assert_field_sweep_map(sweep, benign_range=(0.0, 4.0),
                               destructive_range=(8.0, 20.0), melt_floor=0.5)


def test_field_sweep_oracle_fires_on_gap(tmp_path, mock_oxdna_field_sweep):
    """Can-go-red (clause 1): a missing grid cell → the no-gaps clause fires."""
    specimen = _sweep_specimen(tmp_path)
    sweep = hox.sweep_field_response(
        specimen, [2.0, 4.0, 32.0], [(0, 0, 1)], tmp_path,
        field_steps=2000, melt_floor=0.5, min_confidence=10)
    sweep["map"].pop((4.0, (0.0, 0.0, 1.0)))   # drop a verdict
    with pytest.raises(AssertionError, match="no verdict for cell|gap in the map"):
        assert_field_sweep_map(sweep, benign_range=(0.0, 20.0),
                               destructive_range=(24.0, 1e9), melt_floor=0.5)


def _landmarks(design):
    """Two well-separated landmark nucleotide keys present in the design geometry."""
    from backend.core.design_geometry import _geometry_for_design
    geom = _geometry_for_design(design)
    a, b = geom[0], geom[-1]
    return ((a["helix_id"], a["bp_index"], a["direction"]),
            (b["helix_id"], b["bp_index"], b["direction"]))


def _design_end_to_end(design, a, b):
    """Expected end-to-end: the design's OWN backbone geometry distance (the mock
    relaxation is identity, so the relaxed mean must reproduce this)."""
    from backend.core.design_geometry import _geometry_for_design
    from backend.core.oxdna_health import measure_end_to_end
    return measure_end_to_end(_geometry_for_design(design), a, b)


def _design_radius_of_gyration(design):
    """Expected R_g: the design's OWN whole-structure radius of gyration (identity
    mock relaxation → the relaxed mean reproduces the design geometry)."""
    from backend.core.design_geometry import _geometry_for_design
    from backend.core.oxdna_health import measure_radius_of_gyration
    return measure_radius_of_gyration(_geometry_for_design(design))


def _angle_landmarks(design):
    """Three landmark keys along ONE helix strand (same direction, spread bp) so a
    straight duplex reads ~180° and a bend at the middle drops below it.  Returns
    (a, b, c) with b the angle vertex."""
    from backend.core.design_geometry import _geometry_for_design
    geom = _geometry_for_design(design)
    # Group by (helix_id, direction); pick the first group with >= 3 nucleotides.
    groups = {}
    for p in geom:
        groups.setdefault((p["helix_id"], p["direction"]), []).append(p)
    strand = next(g for g in groups.values() if len(g) >= 3)
    strand.sort(key=lambda p: p["bp_index"])
    a, b, c = strand[0], strand[len(strand) // 2], strand[-1]
    return tuple((p["helix_id"], p["bp_index"], p["direction"]) for p in (a, b, c))


def _design_segment_angle(design, a, b, c):
    """Expected segment angle: the design's OWN three-landmark bend angle (identity
    mock relaxation → the relaxed mean reproduces the design geometry)."""
    from backend.core.design_geometry import _geometry_for_design
    from backend.core.oxdna_health import measure_segment_angle
    return measure_segment_angle(_geometry_for_design(design), a, b, c)


def _relaxed_with_production(design, workspace, *, steps):
    """Relax → append a production run of `steps` → return the terminal job."""
    job = hox.run_relaxation(design, workspace, min_bp_retained=0.0)
    assert job.status is OxdnaStatus.completed, job.error
    hox.append_production(job.job_id, workspace, steps=steps)
    return hox.wait_for_terminal(job.job_id, workspace)


def test_read_flexibility_map_returns_mean_and_confidence(sequenced_6hb, tmp_path,
                                                          mock_oxdna_traj):
    """The mean-structure wrapper pools production frames and reports confidence."""
    job = _relaxed_with_production(sequenced_6hb, tmp_path, steps=6000)
    assert job.status is OxdnaStatus.completed, job.error
    rmsf = hox.read_flexibility_map(job.job_id, tmp_path)
    assert rmsf["ready"] is True
    assert rmsf["confidence"]["n_frames"] == 60        # 6000 // 100
    assert rmsf["confidence"]["preliminary"] is False  # >= RMSF_PRELIM_FRAMES (50)
    assert len(rmsf["positions"]) > 0


def test_assert_relaxed_measurement_end_to_end(sequenced_6hb, tmp_path, mock_oxdna_traj):
    """The relaxed mean structure preserves the design's end-to-end distance, and
    the oracle certifies it within tolerance with sufficient confidence."""
    a, b = _landmarks(sequenced_6hb)
    target = _design_end_to_end(sequenced_6hb, a, b)
    assert target > 1.0                                # non-degenerate landmarks
    job = _relaxed_with_production(sequenced_6hb, tmp_path, steps=6000)
    result = assert_relaxed_measurement(
        job, {"measure": "end_to_end", "landmarks": [a, b]},
        target, 0.1, workspace=tmp_path, min_confidence=50)
    assert result["n_frames"] == 60
    assert abs(result["measured_nm"] - target) < 0.1     # observed gap ~0.002 nm


def test_assert_relaxed_measurement_radius_of_gyration(sequenced_6hb, tmp_path,
                                                       mock_oxdna_traj):
    """The whole-structure radius_of_gyration measure flows through the SAME
    oracle (no landmarks), certified against the design's own R_g."""
    target = _design_radius_of_gyration(sequenced_6hb)
    assert target > 1.0                                  # non-degenerate structure
    job = _relaxed_with_production(sequenced_6hb, tmp_path, steps=6000)
    result = assert_relaxed_measurement(
        job, {"measure": "radius_of_gyration"},
        target, 0.1, workspace=tmp_path, min_confidence=50)
    assert result["n_frames"] == 60
    assert abs(result["measured_nm"] - target) < 0.1     # identity mock → ~0 gap


def test_relaxed_measurement_radius_of_gyration_fires_on_wrong_target(
        sequenced_6hb, tmp_path, mock_oxdna_traj):
    """An R_g target the relaxed structure doesn't match raises the tolerance check."""
    target = _design_radius_of_gyration(sequenced_6hb)
    job = _relaxed_with_production(sequenced_6hb, tmp_path, steps=6000)
    with pytest.raises(AssertionError, match="not within"):
        assert_relaxed_measurement(
            job, {"measure": "radius_of_gyration"},
            target + 20.0, 0.5, workspace=tmp_path, min_confidence=50)


def test_assert_relaxed_measurement_segment_angle(sequenced_6hb, tmp_path, mock_oxdna_traj):
    """The three-landmark segment_angle measure (degrees) flows through the SAME
    oracle, certified against the straight bundle's own ~180° bend angle (identity
    mock → the relaxed mean reproduces the design geometry)."""
    a, b, c = _angle_landmarks(sequenced_6hb)
    target = _design_segment_angle(sequenced_6hb, a, b, c)
    assert target > 160.0                                 # a straight duplex is ~175°
    job = _relaxed_with_production(sequenced_6hb, tmp_path, steps=6000)
    # tol in DEGREES; a few degrees absorbs the oxDNA backbone-site convention vs the
    # design-geometry one (an angle near 180° is sensitive to sub-Å offsets).
    result = assert_relaxed_measurement(
        job, {"measure": "segment_angle", "landmarks": [a, b, c]},
        target, 3.0, workspace=tmp_path, min_confidence=50)
    assert result["n_frames"] == 60
    assert abs(result["measured_nm"] - target) < 3.0


def test_relaxed_measurement_segment_angle_fires_on_wrong_target(
        sequenced_6hb, tmp_path, mock_oxdna_traj):
    """A segment-angle target the relaxed structure doesn't match raises the
    tolerance check (the message reports degrees, not nm)."""
    a, b, c = _angle_landmarks(sequenced_6hb)
    target = _design_segment_angle(sequenced_6hb, a, b, c)
    job = _relaxed_with_production(sequenced_6hb, tmp_path, steps=6000)
    with pytest.raises(AssertionError, match="not within"):
        assert_relaxed_measurement(
            job, {"measure": "segment_angle", "landmarks": [a, b, c]},
            target - 60.0, 1.0, workspace=tmp_path, min_confidence=50)


# ── Red-tests: the measurement oracle CAN go red ───────────────────────────────

def test_relaxed_measurement_fires_on_wrong_target(sequenced_6hb, tmp_path, mock_oxdna_traj):
    """A target the relaxed structure doesn't match raises the tolerance check."""
    a, b = _landmarks(sequenced_6hb)
    target = _design_end_to_end(sequenced_6hb, a, b)
    job = _relaxed_with_production(sequenced_6hb, tmp_path, steps=6000)
    with pytest.raises(AssertionError, match="not within"):
        assert_relaxed_measurement(
            job, {"measure": "end_to_end", "landmarks": [a, b]},
            target + 20.0, 0.5, workspace=tmp_path, min_confidence=50)


def test_relaxed_measurement_fires_on_low_confidence(sequenced_6hb, tmp_path, mock_oxdna_traj):
    """Too few pooled frames → INCONCLUSIVE (the load-bearing confidence gate),
    even when the measured value is within tolerance."""
    a, b = _landmarks(sequenced_6hb)
    target = _design_end_to_end(sequenced_6hb, a, b)
    # steps has a 1000 minimum; 1000 // 100 = 10 frames, below RMSF_PRELIM_FRAMES.
    job = _relaxed_with_production(sequenced_6hb, tmp_path, steps=1000)   # 10 frames
    with pytest.raises(AssertionError, match="INCONCLUSIVE"):
        assert_relaxed_measurement(
            job, {"measure": "end_to_end", "landmarks": [a, b]},
            target, 0.5, workspace=tmp_path, min_confidence=50)


def test_relaxed_measurement_fires_without_production(sequenced_6hb, tmp_path, mock_oxdna_traj):
    """No production run → no mean structure → the oracle raises (not a silent 0)."""
    a, b = _landmarks(sequenced_6hb)
    target = _design_end_to_end(sequenced_6hb, a, b)
    job = hox.run_relaxation(sequenced_6hb, tmp_path, min_bp_retained=0.0)
    with pytest.raises(AssertionError, match="no production mean structure"):
        assert_relaxed_measurement(
            job, {"measure": "end_to_end", "landmarks": [a, b]},
            target, 0.5, workspace=tmp_path, min_confidence=50)


# ── AF-13 Phase 3: the declarative constraint checker on a REAL relaxed output ─
# Proves check_relaxed_constraint consumes the actual read_flexibility_map dict
# shape (positions + confidence) and that its confidence gate fires on a genuine
# under-sampled production run — not just on synthetic maps.

def test_check_relaxed_constraint_met_on_real_run(sequenced_6hb, tmp_path, mock_oxdna_traj):
    """A within-tolerance target on a well-sampled run → met."""
    from backend.core.oxdna_health import check_relaxed_constraint
    a, b = _landmarks(sequenced_6hb)
    target = _design_end_to_end(sequenced_6hb, a, b)
    job = _relaxed_with_production(sequenced_6hb, tmp_path, steps=6000)   # 60 frames
    rmsf = hox.read_flexibility_map(job.job_id, tmp_path)
    r = check_relaxed_constraint(
        {"measure": "end_to_end", "landmarks": [a, b], "target_nm": target,
         "tol_nm": 0.1, "min_confidence": 50}, rmsf)
    assert r["status"] == "met" and r["met"] is True
    assert r["n_frames"] == 60
    assert abs(r["measured_nm"] - target) < 0.1


def test_check_relaxed_constraint_inconclusive_on_low_frames(sequenced_6hb, tmp_path,
                                                             mock_oxdna_traj):
    """A real under-sampled run reports inconclusive (never met), even though the
    measured value is within tolerance — the confidence gate end-to-end."""
    from backend.core.oxdna_health import check_relaxed_constraint
    a, b = _landmarks(sequenced_6hb)
    target = _design_end_to_end(sequenced_6hb, a, b)
    job = _relaxed_with_production(sequenced_6hb, tmp_path, steps=1000)   # 10 frames
    rmsf = hox.read_flexibility_map(job.job_id, tmp_path)
    r = check_relaxed_constraint(
        {"measure": "end_to_end", "landmarks": [a, b], "target_nm": target,
         "tol_nm": 0.5, "min_confidence": 50}, rmsf)
    assert r["status"] == "inconclusive" and r["met"] is False
    assert r["n_frames"] == 10
    assert abs(r["measured_nm"] - target) < 0.5      # within tol, yet NOT met


# ── Benchmark access for feature automation (the relaxation auto-tune bridge) ──
# Makes the simulation Benchmark headlessly runnable + its result consumable by a
# relaxation, so AF-13 P4's iterate-until-met loop relaxes on the fastest discovered
# backend instead of a hard-coded CPU default.

from backend.core import benchmark as _bench
from tests.automation_harness import assert_relax_honors_hardware_default


def test_resolve_oxdna_relax_config_reads_default():
    """The pure bridge maps a stored HardwareBenchmark → {backend, device}, with a
    CPU/0 fallback when nothing was benchmarked on this machine."""
    from backend.core.models import HardwareBenchmark, OxdnaHardwareDefault

    assert _bench.resolve_oxdna_relax_config(None) == {"backend": "CPU", "device": "0"}
    assert _bench.resolve_oxdna_relax_config(HardwareBenchmark()) == {
        "backend": "CPU", "device": "0"}                    # NAMD-only slot still falls back
    hw = HardwareBenchmark(oxdna=OxdnaHardwareDefault(backend="CUDA", device="1"))
    assert _bench.resolve_oxdna_relax_config(hw) == {"backend": "CUDA", "device": "1"}


def test_run_oxdna_benchmark_produces_recommendation(tmp_path, mock_oxdna):
    """Headless sweep end-to-end against the mock binary: builds a size-matched proxy,
    runs every config in this machine's real grid, and returns a well-formed
    recommendation (CPU on a no-GPU box, CUDA where a device exists). The benchmark
    builds its own sequenced proxy, so the input design need not be sequenced."""
    result = hox.run_oxdna_benchmark(make_6hb_design(), tmp_path, steps=200)
    assert result["state"] == "completed", result["error"]
    rec = result["recommendation"]
    assert rec is not None and rec["backend"] in {"CPU", "CUDA"}
    assert rec["steps_per_s"] and rec["steps_per_s"] > 0
    assert result["proxy_nucleotides"] and result["proxy_nucleotides"] > 0
    assert result["note"]                                   # the no-silent-caps note
    # The sweep cleans up its own workdir (rmtree in the runner's finally).
    assert not (tmp_path / "benchmark_runs").exists() or \
        not any((tmp_path / "benchmark_runs").iterdir())


def test_run_oxdna_benchmark_picks_winner_from_injected_grid(tmp_path, mock_oxdna):
    """With an injected runner + a two-config grid (CPU + a synthetic CUDA device),
    the sweep runs BOTH trials through the REAL orchestration + pick-best path — the
    GPU-free way to exercise the CUDA branch on a no-GPU box. run_oxdna_trials labels
    each trial ``bench-<id>-<i>`` (i = config index), so slowing trial 0 (CPU) makes
    CUDA win on measured steps/s. (find_oxdna still resolves via $OXDNA_BIN, hence
    mock_oxdna, even though the stub launches nothing.)"""
    import asyncio

    async def _stub(_bin, _input, stage_dir, _log, label):
        (stage_dir / "last_conf.dat").write_text("t = 0\nb = 1 1 1\nE = 0 0 0\n")
        if label.endswith("-0"):
            await asyncio.sleep(0.05)
        return 0, ""

    grid = [
        _bench.OxdnaTrialConfig(label="CPU", backend="CPU", device="0"),
        _bench.OxdnaTrialConfig(label="CUDA:0", backend="CUDA", device="0"),
    ]
    result = hox.run_oxdna_benchmark(make_6hb_design(), tmp_path, steps=200,
                                     configs=grid, runner=_stub)
    assert result["state"] == "completed", result["error"]
    assert len(result["results"]) == 2
    assert result["recommendation"]["backend"] == "CUDA"


def test_relax_honors_benchmarked_backend(sequenced_6hb, tmp_path, mock_oxdna):
    """THE BRIDGE: a benchmarked default flows benchmark→metadata→relaxation. A
    design tuned to CUDA:1 relaxes on CUDA:1; an un-tuned design falls back to CPU.
    The mock binary ignores the declared backend, so this is GPU-free."""
    job = assert_relax_honors_hardware_default(
        sequenced_6hb, tmp_path, backend="CUDA", device="1", min_bp_retained=0.0)
    assert job.backend == "CUDA" and job.device == "1"


def test_run_oxdna_benchmark_then_apply_then_relax(sequenced_6hb, tmp_path, mock_oxdna):
    """The full producer→consumer chain: run a real (mock-binary) sweep, apply its
    recommendation to the design, and relax_tuned honours it — the exact pipeline the
    iterate-until-met loop uses to auto-tune its relaxations."""
    result = hox.run_oxdna_benchmark(sequenced_6hb, tmp_path, steps=200)
    rec = result["recommendation"]
    tuned = hox.apply_oxdna_benchmark(sequenced_6hb, rec)
    job = hox.run_relaxation_tuned(tuned, tmp_path, min_bp_retained=0.0)
    assert job.status is OxdnaStatus.completed, job.error
    assert (job.backend, job.device) == (rec["backend"], rec["device"])


def test_bridge_oracle_fires_when_default_ignored(sequenced_6hb, tmp_path, mock_oxdna,
                                                  monkeypatch):
    """Red-test: a bridge that ignores the stored default (hard-codes CPU) makes the
    oracle raise — proving the green can go red."""
    real = hox.run_relaxation_tuned

    def _broken(design, workspace, **params):
        params.pop("hostname", None)
        params["backend"] = "CPU"          # ignore the benchmarked default
        params["device"] = "0"
        return real(design, workspace, **params)

    monkeypatch.setattr(hox, "run_relaxation_tuned", _broken)
    with pytest.raises(AssertionError, match="did not honour the benchmarked default"):
        assert_relax_honors_hardware_default(
            sequenced_6hb, tmp_path, backend="CUDA", device="1", min_bp_retained=0.0)


def test_bridge_oracle_rejects_vacuous_cpu_request(sequenced_6hb, tmp_path):
    """The non-vacuity guard: requesting the CPU/0 fallback config is rejected (a
    bridge that ignored the default would pass it)."""
    with pytest.raises(AssertionError, match="vacuous"):
        assert_relax_honors_hardware_default(
            sequenced_6hb, tmp_path, backend="CPU", device="0", min_bp_retained=0.0)


# ── AF-13 Phase 4: the iterate-until-met loop (the capstone) ───────────────────
# Composes build (a bend-curvature TOPOLOGY knob) → relax → production → measure →
# adjust into a CLOSED loop that converges the knob to a relaxed-structure
# end-to-end target.  The identity mock can't move atoms, so the relaxed mean
# reproduces the DESIGN geometry — meaning the bend (a real topology edit) is what
# moves the measured end-to-end, exactly as a real GPU run's physics would.  Probed
# monotone profile: kappa 0 -> 13.74 nm, 2.0 -> 12.64, 2.5 -> 12.04, 3.0 -> 11.33.

from backend.api import headless_build as hb
from backend.api import state as design_state
from backend.core.models import LatticeType
from tests.automation_harness import assert_converges_to_constraint

_BEND_CELLS = [[0, 0], [0, 1]]
_BEND_LENGTH = 42
_BEND_LANDMARKS = (("h_XY_0_0", 0, "FORWARD"), ("h_XY_0_1", 41, "REVERSE"))


def _build_bent_bundle(knob):
    """build_fn: a fully-sequenced 2-helix bundle bent by ``knob['kappa']`` deg/bp.
    The bend curves the bundle so its fixed-index end-to-end shrinks with curvature;
    the landmark keys are stable across all curvatures (topology is unchanged)."""
    with hb.scratch_session(LatticeType.HONEYCOMB):
        hb.create_bundle(_BEND_CELLS, _BEND_LENGTH, lattice=LatticeType.HONEYCOMB)
        if knob["kappa"] > 1e-9:
            hb.add_bend(2, _BEND_LENGTH - 3, curvature_deg_per_bp=knob["kappa"])
        return _sequence_for_oxdna(design_state.get_or_404())


def _bisect_kappa(target):
    """adjust_fn: bisection on curvature.  end-to-end DECREASES monotonically with
    kappa, so a measurement above target needs MORE bend (raise lo), below needs
    LESS (lower hi).  Only ever called on an ``unmet`` verdict."""
    def adjust(knob, verdict):
        lo, hi, k = knob["lo"], knob["hi"], knob["kappa"]
        if verdict["measured_nm"] > target:    # too straight → bend more
            lo = k
        else:                                  # too bent → bend less
            hi = k
        return {"kappa": (lo + hi) / 2, "lo": lo, "hi": hi}
    return adjust


def _e2e_constraint(target, *, tol=0.5, min_confidence=50):
    a, b = _BEND_LANDMARKS
    return {"measure": "end_to_end", "landmarks": [list(a), list(b)],
            "target_nm": target, "tol_nm": tol, "min_confidence": min_confidence}


def test_segment_angle_captures_bend():
    """THE LOAD-BEARING AUGMENT: segment_angle actually measures curvature — three
    collinear landmarks along a STRAIGHT bundle read ~180°, and the SAME landmarks
    on a bundle bent at the middle read strictly (and substantially) less.  Pure
    geometry (no oxDNA): proves the measure reflects real bending, not a constant.
    Direction-agnostic (an arccos magnitude) — no frame/sign reasoning."""
    straight = _build_bent_bundle({"kappa": 0.0})
    bent = _build_bent_bundle({"kappa": 3.0})
    a, b, c = _angle_landmarks(straight)
    straight_angle = _design_segment_angle(straight, a, b, c)
    bent_angle = _design_segment_angle(bent, a, b, c)
    # ~175°, not exactly 180: backbone sites spiral around the helix axis, so three
    # backbone landmarks are on a helical path, not a straight line.
    assert straight_angle > 170.0
    assert bent_angle < straight_angle - 40.0          # the bend folds the segment
    assert 0.0 < bent_angle < 180.0                    # a real interior angle


def test_iterate_converges_to_constraint(tmp_path, mock_oxdna_traj):
    """THE CAPSTONE: the closed loop bisects the bend curvature until the relaxed
    end-to-end lands within tolerance of the target — every verdict confidence-gated
    via check_relaxed_constraint."""
    target = 12.0
    result = hox.iterate_to_constraint(
        _build_bent_bundle, _bisect_kappa(target), _e2e_constraint(target),
        tmp_path, initial_knob={"kappa": 2.0, "lo": 0.0, "hi": 4.0},
        max_iterations=8, production_steps=6000, min_bp_retained=0.0)
    assert_converges_to_constraint(result, target_nm=target, tol_nm=0.5,
                                   min_confidence=50)
    assert result["status"] == "met"
    assert 2.0 < result["knob"]["kappa"] < 3.0    # converged between the two brackets
    assert len(result["iterations"]) <= 5         # a few bisection steps
    # every iteration was conclusive in one well-sampled production round
    assert all(it["production_rounds"] == 1 for it in result["iterations"])


def test_iterate_grows_production_on_inconclusive(tmp_path, mock_oxdna_traj):
    """The 'inconclusive → run a longer production' branch: a run that starts
    under-sampled pools MORE production (not a knob change) until the confidence gate
    clears.  The knob starts on-target, so once confident it is immediately met and
    the adjust_fn is never called."""
    target = 12.037                               # kappa=2.5 lands here

    def _no_adjust(knob, verdict):
        raise AssertionError("adjust_fn must not be called on an inconclusive/met loop")

    result = hox.iterate_to_constraint(
        _build_bent_bundle, _no_adjust,
        _e2e_constraint(target, tol=0.5, min_confidence=25), tmp_path,
        initial_knob={"kappa": 2.5, "lo": 0.0, "hi": 4.0}, max_iterations=3,
        production_steps=1000,        # 10 frames/round → needs ≥3 rounds for 25
        max_production_rounds=8, min_bp_retained=0.0)
    assert result["status"] == "met"
    assert result["iterations"][0]["production_rounds"] >= 3   # pooled multiple runs
    assert result["verdict"]["n_frames"] >= 25


# ── Red-tests: the convergence oracle CAN go red ───────────────────────────────

def test_iterate_oracle_fires_on_exhaustion(tmp_path, mock_oxdna_traj):
    """A target no curvature can reach (> the straight ~13.74 nm end-to-end) → the
    loop exhausts its budget without ever meeting it, and the oracle raises."""
    target = 20.0
    result = hox.iterate_to_constraint(
        _build_bent_bundle, _bisect_kappa(target),
        _e2e_constraint(target, tol=0.3), tmp_path,
        initial_knob={"kappa": 2.0, "lo": 0.0, "hi": 4.0}, max_iterations=4,
        production_steps=6000, min_bp_retained=0.0)
    assert result["status"] == "exhausted"
    with pytest.raises(AssertionError, match="did not converge"):
        assert_converges_to_constraint(result, target_nm=target, tol_nm=0.3,
                                       min_confidence=50)


def test_iterate_oracle_fires_on_vacuous_convergence(tmp_path, mock_oxdna_traj):
    """The non-vacuity guard: if the initial knob ALREADY meets the constraint, the
    loop 'converges' on attempt 0 with no adjustment work — the oracle rejects it."""
    target = 12.037                               # kappa=2.5 meets it immediately
    result = hox.iterate_to_constraint(
        _build_bent_bundle, _bisect_kappa(target),
        _e2e_constraint(target, tol=0.5), tmp_path,
        initial_knob={"kappa": 2.5, "lo": 0.0, "hi": 4.0}, max_iterations=4,
        production_steps=6000, min_bp_retained=0.0)
    assert result["status"] == "met"              # it DID meet — but on attempt 0
    with pytest.raises(AssertionError, match="vacuous|FIRST attempt"):
        assert_converges_to_constraint(result, target_nm=target, tol_nm=0.5,
                                       min_confidence=50)


def test_iterate_rejects_bad_constraint(tmp_path):
    """A malformed constraint raises at parse time — before any relaxation runs (no
    mock binary needed: it fails fast)."""
    from backend.core.oxdna_health import ConstraintSpecError

    def _build(knob):
        raise AssertionError("build_fn called despite a malformed constraint")

    with pytest.raises(ConstraintSpecError):
        hox.iterate_to_constraint(
            _build, lambda k, v: k, {"measure": "bogus", "landmarks": []},
            tmp_path, initial_knob={"kappa": 0.0})


# ── inter_helix_spacing — the first axis-grouping relaxed-structure measure ─────
# Each landmark only NAMES a helix; the measure groups all of that helix's backbone
# sites to fit its axis, then the radial centre-to-centre spacing in nm.

def _row_bundle():
    """A straight 3-in-a-row SQUARE bundle (2.25 nm lattice pitch) + its three
    helix ids sorted, for the inter-helix-spacing tests."""
    with hb.scratch_session(LatticeType.SQUARE):
        hb.create_bundle([[0, 0], [0, 1], [0, 2]], 32, lattice=LatticeType.SQUARE)
        design = _sequence_for_oxdna(design_state.get_or_404())
    from backend.core.design_geometry import _geometry_for_design
    by_h = {}
    for p in _geometry_for_design(design):
        by_h.setdefault(p["helix_id"], []).append(p)
    hids = sorted(by_h)

    def landmark(hid):
        p = by_h[hid][0]
        return (p["helix_id"], p["bp_index"], p["direction"])

    return design, hids, landmark


def _design_inter_helix_spacing(design, a, b):
    """Expected spacing: the design's OWN fit-axis radial gap (identity mock
    relaxation → the relaxed mean reproduces the design geometry)."""
    from backend.core.design_geometry import _geometry_for_design
    from backend.core.oxdna_health import measure_inter_helix_spacing
    return measure_inter_helix_spacing(_geometry_for_design(design), a, b)


def test_inter_helix_spacing_captures_separation():
    """THE LOAD-BEARING AUGMENT: inter_helix_spacing tracks real helix separation,
    not a constant.  On a straight 3-in-a-row SQUARE bundle the two adjacent pairs
    read the same lattice pitch (~2.25 nm), and the skip-one pair reads ~twice that —
    proving the measure reflects actual geometry.  Pure geometry (no oxDNA); a
    magnitude, so direction-agnostic (no frame/sign reasoning)."""
    design, hids, lm = _row_bundle()
    assert len(hids) == 3
    adj01 = _design_inter_helix_spacing(design, lm(hids[0]), lm(hids[1]))
    adj12 = _design_inter_helix_spacing(design, lm(hids[1]), lm(hids[2]))
    skip = _design_inter_helix_spacing(design, lm(hids[0]), lm(hids[2]))
    assert adj01 > 1.0                       # a physical lattice pitch (~2.25 nm)
    assert abs(adj01 - adj12) < 0.05         # uniform lattice → equal adjacent gaps
    assert skip > adj01 + 1.0                # tracks separation, not a constant
    assert abs(skip - 2 * adj01) < 0.1       # a straight row → ~twice the pitch


def test_assert_relaxed_measurement_inter_helix_spacing(tmp_path, mock_oxdna_traj):
    """The two-landmark inter_helix_spacing measure (nm) flows through the SAME
    oracle, certified against the bundle's own adjacent-helix spacing (identity mock
    → the relaxed mean reproduces the design geometry)."""
    design, hids, lm = _row_bundle()
    a, b = lm(hids[0]), lm(hids[1])
    target = _design_inter_helix_spacing(design, a, b)
    assert target > 1.0                                  # non-degenerate spacing
    job = _relaxed_with_production(design, tmp_path, steps=6000)
    result = assert_relaxed_measurement(
        job, {"measure": "inter_helix_spacing", "landmarks": [a, b]},
        target, 0.1, workspace=tmp_path, min_confidence=50)
    assert result["n_frames"] == 60
    assert abs(result["measured_nm"] - target) < 0.1     # identity mock → ~0 gap


def test_relaxed_measurement_inter_helix_spacing_fires_on_wrong_target(
        tmp_path, mock_oxdna_traj):
    """A spacing target the relaxed structure doesn't match raises the tolerance
    check (the message reports nm)."""
    design, hids, lm = _row_bundle()
    a, b = lm(hids[0]), lm(hids[1])
    target = _design_inter_helix_spacing(design, a, b)
    job = _relaxed_with_production(design, tmp_path, steps=6000)
    with pytest.raises(AssertionError, match="not within"):
        assert_relaxed_measurement(
            job, {"measure": "inter_helix_spacing", "landmarks": [a, b]},
            target + 5.0, 0.5, workspace=tmp_path, min_confidence=50)
