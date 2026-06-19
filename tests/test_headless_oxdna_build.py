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
    # Running a field from a field child is refused.
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc:
        hox.append_field(ids[0], tmp_path, field_pN=2.0, dir=[0, 0, 1], anchors=[anchor])
    assert exc.value.status_code == 400


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
