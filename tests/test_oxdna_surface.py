"""Hard-surface (oxDNA repulsion-plane) feature: composed-run force writer, stage
builder, consolidated /run endpoint validation, and the no-penetration oracle.

Sibling of the E-field tests in test_oxdna_relaxation.py — same fixtures + mock
(no GPU): the oracle is exercised on synthetic position lists so the physical
property ("nothing penetrates the surface") is asserted, not an HTTP status."""
from __future__ import annotations

import pytest

from backend.core.oxdna_job import OxdnaStatus, new_oxdna_job
from tests.conftest import make_6hb_design


@pytest.fixture
def design():
    return make_6hb_design()


@pytest.fixture
def geometry(design):
    from backend.api.crud import _geometry_for_design
    return _geometry_for_design(design)


def _pos(hid, bp, direction, xyz):
    return {"helix_id": hid, "bp_index": bp, "direction": direction,
            "backbone_position": list(xyz)}


def test_resolved_wall_position_converts_to_world_axis_coordinate():
    from backend.api.routes_oxdna import _wall_axis_position_nm
    from backend.core.constants import NM_TO_OXDNA

    # oxDNA plane: dir·r + position = 0. For a -Y normal, the world Y
    # coordinate has the opposite sign from the scalar along the normal.
    meta = {"dir": [0, -1, 0], "position": 4 * NM_TO_OXDNA}
    assert _wall_axis_position_nm(meta) == pytest.approx(4.0)


# ── Force-block + plane-placement primitives ──────────────────────────────────

def test_repulsion_plane_block_format():
    from backend.physics.oxdna_interface import repulsion_plane_block
    txt = repulsion_plane_block(5.0, [0, 2, 0], -3.5)
    assert "type = repulsion_plane" in txt
    assert "particle = -1" in txt          # applies to every nucleotide
    assert "stiff = 5" in txt
    assert "dir = 0,1,0" in txt            # normalized
    assert "position = -3.5" in txt


def test_wall_position_from_extent():
    from backend.physics.oxdna_interface import wall_position_from_extent
    # Beads along +y at y = 2, 5, 9 → min projection 2.  Plane normal +y.
    cm = [[0, 2, 0], [1, 5, 0], [2, 9, 0]]
    position, min_proj = wall_position_from_extent(cm, [0, 1, 0], offset_oxdna=0.0)
    assert min_proj == pytest.approx(2.0)
    # position = offset - min_proj → dir·r + position >= 0 for every bead.
    assert position == pytest.approx(-2.0)
    for p in cm:
        assert p[1] + position >= -1e-9          # all start on the allowed side
    # A positive offset lowers the plane (more clearance) → position more negative.
    pos2, _ = wall_position_from_extent(cm, [0, 1, 0], offset_oxdna=1.0)
    assert pos2 == pytest.approx(-1.0)            # offset - min_proj = 1 - 2


# ── Composed external-forces writer ───────────────────────────────────────────

def test_write_run_forces_composes_field_surface_anchors(design, geometry, tmp_path):
    from backend.physics.oxdna_interface import (
        write_run_forces, write_configuration, resolve_anchor_particles,
        pn_to_oxdna_force)
    conf = tmp_path / "conf.dat"
    write_configuration(design, geometry, conf)
    s0 = design.strands[0]
    anchors = [{"kind": "domain", "strand_id": s0.id, "domain_index": 0}]
    parts, _ = resolve_anchor_particles(design, anchors)

    out = tmp_path / "run_forces.txt"
    info = write_run_forces(
        out, design, conf,
        field={"force_oxdna": pn_to_oxdna_force(2.0), "dir": [0, 0, 5]},
        wall={"dir": [0, 1, 0], "offset_nm": 1.0, "stiff": 5.0},
        anchors=anchors,
    )
    text = out.read_text()
    assert text.count("type = string") == 1                 # one uniform field force
    assert text.count("type = repulsion_plane") == 1        # one hard surface
    assert text.count("type = trap") == len(parts) == info["n_anchored"] > 0
    assert info["field"]["dir"] == [0, 0, 1]                # normalized
    assert info["wall"]["stiff"] == 5.0
    assert info["has_forces"] is True


def test_write_run_forces_surface_only_needs_no_anchor(design, geometry, tmp_path):
    """A bare hard surface (steric only) is valid with zero anchors — only a FIELD
    requires anchors (that rule lives in the route)."""
    from backend.physics.oxdna_interface import write_run_forces, write_configuration
    conf = tmp_path / "conf.dat"
    write_configuration(design, geometry, conf)
    out = tmp_path / "run_forces.txt"
    info = write_run_forces(out, design, conf,
                            wall={"dir": [0, 1, 0], "offset_nm": 0.0, "stiff": 5.0})
    text = out.read_text()
    assert text.count("type = repulsion_plane") == 1
    assert text.count("type = trap") == 0 and info["n_anchored"] == 0
    assert info["field"] is None and info["wall"] is not None


def test_write_run_forces_anchors_only(design, geometry, tmp_path):
    """Anchors with no field/surface = a plain production with some strands pinned."""
    from backend.physics.oxdna_interface import write_run_forces, write_configuration
    conf = tmp_path / "conf.dat"
    write_configuration(design, geometry, conf)
    s0 = design.strands[0]
    info = write_run_forces(tmp_path / "f.txt", design, conf,
                            anchors=[{"kind": "domain", "strand_id": s0.id, "domain_index": 0}])
    assert info["n_anchored"] > 0 and info["field"] is None and info["wall"] is None
    assert info["has_forces"] is True


# ── Stage builder ─────────────────────────────────────────────────────────────

def test_build_run_stage_with_forces_renders():
    from backend.core.oxdna_protocol import build_run_stage, render_stage_input
    st = build_run_stage(name="1_production", steps=5000, external_forces=True,
                         forces_file="run_forces.txt",
                         forces_meta={"has_field": True, "has_surface": True})
    assert st.kind == "production" and st.sim_type == "MD"   # pools into RMSD/RMSF
    assert st.min_bp_retained == 0.0                         # sampling → no bp gate
    assert st.forces_meta == {"has_field": True, "has_surface": True}
    txt = render_stage_input(st, "topology.top", "conf.dat", forces_name="run_forces.txt")
    assert "external_forces = true" in txt
    assert "external_forces_file = run_forces.txt" in txt


def test_build_run_stage_plain_has_no_forces():
    from backend.core.oxdna_protocol import build_run_stage, render_stage_input
    st = build_run_stage(name="1_production", steps=5000)
    assert st.external_forces is False and st.forces_file is None
    txt = render_stage_input(st, "topology.top", "conf.dat")
    assert "external_forces = true" not in txt


# ── No-penetration oracle ─────────────────────────────────────────────────────

def test_measure_wall_response_pass_and_fail():
    from backend.core.oxdna_health import measure_wall_response
    # Plane at y = 0 (dir +y, position 0): everything with y >= 0 is allowed.
    above = [_pos(0, 0, "forward", (0, 0.5, 0)),
             _pos(0, 1, "forward", (1, 3.0, 0)),
             _pos(0, 2, "reverse", (2, 1.2, 0))]
    r = measure_wall_response(above, [0, 1, 0], 0.0)
    assert r["passed"] is True
    assert r["n_below"] == 0 and r["n_total"] == 3
    assert r["min_clearance_nm"] == pytest.approx(0.5)

    # One bead sunk well below the plane → fails (penetration).
    sunk = [_pos(0, 0, "forward", (0, 0.5, 0)),
            _pos(0, 1, "forward", (1, -2.0, 0))]
    rf = measure_wall_response(sunk, [0, 1, 0], 0.0)
    assert rf["passed"] is False and rf["n_below"] == 1
    assert rf["min_clearance_nm"] == pytest.approx(-2.0)


def test_measure_wall_response_zero_dir_raises():
    from backend.core.oxdna_health import measure_wall_response
    with pytest.raises(ValueError, match="wall_dir is ~zero"):
        measure_wall_response([_pos(0, 0, "forward", (0, 1, 0))], [0, 0, 0], 0.0)


# ── Consolidated /run endpoint ────────────────────────────────────────────────

def _completed_parent(tmp_path, design):
    """A minimal completed relaxation parent the /run endpoint can branch from."""
    from backend.physics.oxdna_interface import write_configuration
    from backend.api.crud import _geometry_for_design
    from backend.core.oxdna_protocol import build_relaxation_stages
    specs = build_relaxation_stages(mc_steps=10, md_relax_steps=10, equil_steps=10)
    job = new_oxdna_job("d", [s.to_status() for s in specs])
    job.status = OxdnaStatus.completed
    jd = job.job_dir(tmp_path)
    jd.mkdir(parents=True, exist_ok=True)
    (jd / "design.json").write_text(design.model_dump_json())
    (jd / "topology.top").write_text("placeholder\n")
    geom = _geometry_for_design(design)
    write_configuration(design, geom, jd / "conf.dat", box_nm=80.0)
    # The relaxed seed _latest_relaxed_conf reads: the final stage's last_conf.
    sd = job.stage_dir(tmp_path, specs[-1].name); sd.mkdir(parents=True, exist_ok=True)
    write_configuration(design, geom, sd / "last_conf.dat", box_nm=80.0)
    import json
    from dataclasses import asdict
    (jd / "stages_spec.json").write_text(json.dumps([asdict(s) for s in specs], indent=2))
    job.save(tmp_path)
    return job


def _run_client(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient
    from backend.api.main import app
    import backend.api.routes_oxdna as routes_oxdna
    monkeypatch.setattr(routes_oxdna, "_WORKSPACE_DIR", tmp_path)
    monkeypatch.setattr(routes_oxdna, "find_oxdna", lambda: "/usr/bin/true")
    monkeypatch.setattr(routes_oxdna, "is_running", lambda *_a, **_k: False)
    monkeypatch.setattr(routes_oxdna, "start_job", lambda *_a, **_k: None)  # don't launch oxDNA
    # These tests exercise /run COMPOSITION (field/surface/anchor branching), not the
    # design-staleness guard (which has its own tests). The guard compares the job
    # snapshot's fingerprint to the *global* active design — ambient state another
    # test left behind — so without this it spuriously 409s under parallel/reordered
    # runs. Neutralize it so the run logic is what's under test.
    monkeypatch.setattr(routes_oxdna, "_current_design_fingerprint", lambda: None)
    return TestClient(app), routes_oxdna


def test_run_field_without_anchor_allowed(design, monkeypatch, tmp_path):
    """A field with no anchor is no longer rejected — it branches a child job with a
    field-only forces file (the UI warns about the resulting COM drift)."""
    client, _ = _run_client(monkeypatch, tmp_path)
    parent = _completed_parent(tmp_path, design)
    r = client.post(f"/api/oxdna/jobs/{parent.job_id}/run",
                    json={"steps": 1000, "field": {"field_pN": 2.0, "dir": [0, 0, 1]}})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["parent_job_id"] == parent.job_id
    from backend.core.oxdna_job import OxdnaJob
    child = OxdnaJob.load(body["job_id"], tmp_path)
    forces = (child.job_dir(tmp_path) / "run_forces.txt").read_text()
    assert "type = string" in forces         # the uniform field is present
    assert "type = trap" not in forces        # but no anchor traps


def test_run_surface_only_branches_child(design, monkeypatch, tmp_path):
    client, routes_oxdna = _run_client(monkeypatch, tmp_path)
    parent = _completed_parent(tmp_path, design)
    r = client.post(f"/api/oxdna/jobs/{parent.job_id}/run",
                    json={"steps": 1000,
                          "surface": {"dir": [0, 1, 0], "offset_nm": 1.0, "stiff": 5.0}})
    assert r.status_code == 200, r.text
    body = r.json()
    # A child job seeded from the relaxed parent, with a composed forces file.
    assert body["parent_job_id"] == parent.job_id
    from backend.core.oxdna_job import OxdnaJob
    child = OxdnaJob.load(body["job_id"], tmp_path)
    forces = (child.job_dir(tmp_path) / "run_forces.txt").read_text()
    assert "type = repulsion_plane" in forces
    assert "type = string" not in forces                # no field requested


# ── fix_diffusion off for absolute-coordinate forces (the VoltronCore failure) ─

def test_absolute_forces_render_fix_diffusion_false():
    """A stage carrying a repulsion plane / anchor traps must disable oxDNA's COM
    diffusion-fix, or it recenters coordinates mid-run and shoves the structure
    through the wall (the VoltronCore md_relax explosion)."""
    from backend.core.oxdna_protocol import build_run_stage, render_stage_input
    surf = build_run_stage(name="1_production", steps=5000, external_forces=True,
                           forces_file="run_forces.txt", absolute_forces=True)
    txt = render_stage_input(surf, "topology.top", "conf.dat", forces_name="run_forces.txt")
    assert "fix_diffusion = false" in txt

    # A plain run (uniform field only / no absolute forces) keeps the default.
    plain = build_run_stage(name="1_production", steps=5000, external_forces=True,
                            forces_file="run_forces.txt", absolute_forces=False)
    txt2 = render_stage_input(plain, "topology.top", "conf.dat", forces_name="run_forces.txt")
    assert "fix_diffusion" not in txt2


def test_relax_with_surface_sets_absolute_forces_and_field_too():
    from backend.core.oxdna_protocol import (
        build_relaxation_stages, build_field_stage, render_stage_input)
    surf = build_relaxation_stages(surface_present=True)
    assert all(s.absolute_forces for s in surf)        # all 3 relax stages
    plain = build_relaxation_stages()
    assert not any(s.absolute_forces for s in plain)   # no surface → diffusion-fix on
    # The mc relax stage renders fix_diffusion=false when surface-bound.
    txt = render_stage_input(surf[0], "topology.top", "conf.dat", forces_name="forces.txt")
    assert "fix_diffusion = false" in txt
    # E-field stages (anchor traps) are always absolute.
    fs = build_field_stage(name="1_field", field_oxdna=0.04, field_dir=[1, 0, 0],
                           forces_file="field_forces.txt", steps=2000)
    assert fs.absolute_forces is True


# ── Relax-on-a-surface (surface + anchors during relaxation, no field) ────────

def test_build_relaxation_stages_surface_present():
    from backend.core.oxdna_protocol import build_relaxation_stages
    plain = build_relaxation_stages()
    assert plain[2].external_forces is False and plain[2].forces_file is None
    surf = build_relaxation_stages(surface_present=True)
    # Equil keeps the surface/anchors (its own file, no mutual traps).
    assert surf[2].external_forces is True and surf[2].forces_file == "equil_forces.txt"
    # MC + MD relax still carry the default mutual-trap forces.txt.
    assert surf[0].external_forces is True and surf[1].external_forces is True


def test_prepare_relax_with_surface_and_anchors(design, geometry, tmp_path):
    """Relaxation forces compose mutual traps + surface + anchors; the equil file
    keeps the surface/anchors but drops the mutual traps."""
    from backend.core.oxdna_runner import prepare_oxdna_job
    from backend.core.oxdna_protocol import build_relaxation_stages
    s0 = design.strands[0]
    anchors = [{"kind": "domain", "strand_id": s0.id, "domain_index": 0}]
    surface = {"dir": [0, 1, 0], "offset_nm": 0.0, "stiff": 5.0}
    specs = build_relaxation_stages(surface_present=True)
    job = new_oxdna_job("d", [s.to_status() for s in specs])
    info = prepare_oxdna_job(design, geometry, job, tmp_path, specs,
                             surface=surface, anchors=anchors)
    jd = job.job_dir(tmp_path)
    forces = (jd / "forces.txt").read_text()
    assert "type = mutual_trap" in forces        # WC pairs still held during relax
    assert "type = repulsion_plane" in forces     # ... while bound to the surface
    assert forces.count("type = trap") > 0        # ... and anchored
    assert "type = string" not in forces          # NO field in relaxation
    equil = (jd / "equil_forces.txt").read_text()
    assert "type = repulsion_plane" in equil
    assert "type = mutual_trap" not in equil       # equil drops the pair traps
    assert info["n_anchored"] > 0


def test_prepare_relax_plain_unchanged(design, geometry, tmp_path):
    """No surface/anchors → forces.txt is just mutual traps, no equil_forces.txt."""
    from backend.core.oxdna_runner import prepare_oxdna_job
    from backend.core.oxdna_protocol import build_relaxation_stages
    specs = build_relaxation_stages()
    job = new_oxdna_job("d", [s.to_status() for s in specs])
    prepare_oxdna_job(design, geometry, job, tmp_path, specs)
    jd = job.job_dir(tmp_path)
    forces = (jd / "forces.txt").read_text()
    assert "type = mutual_trap" in forces
    assert "type = repulsion_plane" not in forces and "type = trap" not in forces
    assert not (jd / "equil_forces.txt").exists()


def test_run_composes_field_surface_anchors(design, monkeypatch, tmp_path):
    client, _ = _run_client(monkeypatch, tmp_path)
    parent = _completed_parent(tmp_path, design)
    s0 = design.strands[0]
    r = client.post(f"/api/oxdna/jobs/{parent.job_id}/run",
                    json={"steps": 1000,
                          "field": {"field_pN": 2.0, "dir": [0, 0, 1]},
                          "surface": {"dir": [0, 1, 0], "offset_nm": 0.0, "stiff": 5.0},
                          "anchors": [{"kind": "domain", "strandId": s0.id, "domainIndex": 0}]})
    assert r.status_code == 200, r.text
    from backend.core.oxdna_job import OxdnaJob
    child = OxdnaJob.load(r.json()["job_id"], tmp_path)
    forces = (child.job_dir(tmp_path) / "run_forces.txt").read_text()
    assert "type = string" in forces and "type = repulsion_plane" in forces
    assert forces.count("type = trap") > 0
