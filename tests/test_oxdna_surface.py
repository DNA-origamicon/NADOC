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
    return {
        "helix_id": hid,
        "bp_index": bp,
        "direction": direction,
        "backbone_position": list(xyz),
    }


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
    assert "particle = -1" in txt  # applies to every nucleotide
    assert "stiff = 5" in txt
    assert "dir = 0,1,0" in txt  # normalized
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
        assert p[1] + position >= -1e-9  # all start on the allowed side
    # A positive offset lowers the plane (more clearance) → position more negative.
    pos2, _ = wall_position_from_extent(cm, [0, 1, 0], offset_oxdna=1.0)
    assert pos2 == pytest.approx(-1.0)  # offset - min_proj = 1 - 2


def test_absolute_wall_position_is_independent_of_structure_extent():
    from backend.core.constants import NM_TO_OXDNA
    from backend.physics.oxdna_interface import wall_position_from_absolute

    expected = 7.5 * NM_TO_OXDNA
    assert wall_position_from_absolute([0, 1, 0], -7.5) == pytest.approx(expected)
    assert wall_position_from_absolute([0, 9, 0], -7.5) == pytest.approx(expected)


def test_deposition_approach_pulls_only_selected_beads_toward_wall(design, geometry, tmp_path):
    from backend.physics.oxdna_interface import (
        resolve_anchor_particles,
        write_configuration,
        write_surface_deposition_approach_forces,
    )
    conf = tmp_path / "conf.dat"
    out = tmp_path / "approach.txt"
    write_configuration(design, geometry, conf)
    anchor = {"kind": "domain", "strand_id": design.strands[0].id, "domain_index": 0}
    particles, _ = resolve_anchor_particles(design, [anchor])
    info = write_surface_deposition_approach_forces(
        out, design, conf,
        wall={"dir": [0, 1, 0], "offset_nm": 0, "stiff": 5},
        anchors=[anchor], force_pn=0.25,
    )
    text = out.read_text()
    assert "type = repulsion_plane" in text
    assert "type = trap" not in text
    assert "type = attraction_plane" in text
    assert "type = string" not in text
    floor_particles = text.split("type = repulsion_plane", 1)[1].split("}", 1)[0]
    for particle in particles:
        assert str(particle) not in floor_particles.split("particle = ", 1)[1].splitlines()[0].split(",")
    attraction_particles = text.split("type = attraction_plane", 1)[1].split("particle = ", 1)[1].splitlines()[0]
    assert set(attraction_particles.split(",")) == {str(particle) for particle in particles}
    assert info["n_anchored"] == len(particles) > 0


def test_deposition_placement_is_rigid_and_keeps_whole_structure_above_floor(design, geometry, tmp_path):
    from backend.core.constants import NM_TO_OXDNA
    from backend.physics.oxdna_interface import (
        place_configuration_against_surface,
        read_cm_positions_oxdna,
        resolve_anchor_particles,
        write_configuration,
    )

    conf = tmp_path / "conf.dat"
    write_configuration(design, geometry, conf)
    anchor = {"kind": "base", "helix_id": geometry[0]["helix_id"],
              "bp": geometry[0]["bp_index"], "direction": geometry[0]["direction"]}
    particles, _ = resolve_anchor_particles(design, [anchor])
    before = read_cm_positions_oxdna(conf)
    plane_nm = min(point[1] for point in before) / NM_TO_OXDNA + 4.0
    info = place_configuration_against_surface(
        conf, design,
        wall={"dir": [0, 1, 0], "position_nm": plane_nm, "stiff": 5},
        anchors=[anchor],
    )
    after = read_cm_positions_oxdna(conf)

    assert min(point[1] for point in after) / NM_TO_OXDNA == pytest.approx(plane_nm + 0.05)
    assert info["minimum_clearance_before_nm"] == pytest.approx(-4.0)
    assert info["minimum_clearance_after_nm"] == pytest.approx(0.05)
    assert info["max_penetration_after_nm"] == 0
    shift = [after[0][i] - before[0][i] for i in range(3)]
    for particle in range(len(before)):
        assert [after[particle][i] - before[particle][i] for i in range(3)] == pytest.approx(shift)


def test_existing_surface_placement_is_preserved_and_penetration_rejected(design, geometry, tmp_path):
    from backend.core.constants import NM_TO_OXDNA
    from backend.physics.oxdna_interface import (
        place_configuration_against_surface, read_cm_positions_oxdna, write_configuration,
    )
    conf = tmp_path / "conf.dat"
    write_configuration(design, geometry, conf)
    before = read_cm_positions_oxdna(conf)
    anchor = {"kind": "base", "helix_id": geometry[0]["helix_id"],
              "bp": geometry[0]["bp_index"], "direction": geometry[0]["direction"]}
    plane_nm = min(point[1] for point in before) / NM_TO_OXDNA + 1.0

    with pytest.raises(ValueError, match="intersects the hard floor"):
        place_configuration_against_surface(
            conf, design,
            wall={"dir": [0, 1, 0], "position_nm": plane_nm, "stiff": 5},
            anchors=[anchor], translate=False,
        )
    after = read_cm_positions_oxdna(conf)
    for particle in range(len(before)):
        assert after[particle] == pytest.approx(before[particle])


def test_deposition_settle_requires_contact_and_projects_trap_to_exact_plane(design, geometry, tmp_path):
    from backend.core.constants import NM_TO_OXDNA
    from backend.physics.oxdna_interface import (
        read_cm_positions_oxdna, resolve_anchor_particles, write_configuration,
        write_surface_deposition_settle_forces,
    )
    conf, out = tmp_path / "conf.dat", tmp_path / "settle.txt"
    write_configuration(design, geometry, conf)
    anchor = {"kind": "base", "helix_id": geometry[0]["helix_id"],
              "bp": geometry[0]["bp_index"], "direction": geometry[0]["direction"]}
    particles, _ = resolve_anchor_particles(design, [anchor])
    cm = read_cm_positions_oxdna(conf)
    plane_nm = cm[particles[0]][1] / NM_TO_OXDNA - 0.2
    info = write_surface_deposition_settle_forces(
        out, design, conf,
        wall={"dir": [0, 1, 0], "position_nm": plane_nm, "stiff": 5},
        anchors=[anchor],
    )
    text = out.read_text()
    assert "type = lowdim_trap" in text
    assert "visibility = 0,1,0" in text
    assert "type = trap\n" not in text
    assert "stiff = 1" in text
    import re
    trap_y = float(re.search(r"pos0 = [^,]+,([^,]+),", text).group(1))
    assert trap_y / NM_TO_OXDNA == pytest.approx(plane_nm, abs=1e-5)
    assert info["max_contact_gap_nm"] == pytest.approx(0.2)
    floor_line = text.split("type = repulsion_plane", 1)[1].split("particle = ", 1)[1].splitlines()[0]
    assert str(particles[0]) not in floor_line.split(",")
    with pytest.raises(ValueError, match="did not reach contact"):
        write_surface_deposition_settle_forces(
            out, design, conf,
            wall={"dir": [0, 1, 0], "position_nm": plane_nm - 2, "stiff": 5},
            anchors=[anchor],
        )


def test_surface_contact_gap_uses_nearest_periodic_plane_image():
    from backend.physics.oxdna_interface import _nearest_periodic_gap

    assert _nearest_periodic_gap(128.784, 50.0) == pytest.approx(-21.216)
    assert _nearest_periodic_gap(50.2, 50.0) == pytest.approx(0.2)
    assert _nearest_periodic_gap(-49.8, 50.0) == pytest.approx(0.2)


# ── Composed external-forces writer ───────────────────────────────────────────


def test_write_run_forces_composes_field_surface_anchors(design, geometry, tmp_path):
    from backend.physics.oxdna_interface import (
        write_run_forces,
        write_configuration,
        resolve_anchor_particles,
        pn_to_oxdna_force,
    )

    conf = tmp_path / "conf.dat"
    write_configuration(design, geometry, conf)
    s0 = design.strands[0]
    anchors = [{"kind": "domain", "strand_id": s0.id, "domain_index": 0}]
    parts, _ = resolve_anchor_particles(design, anchors)

    out = tmp_path / "run_forces.txt"
    info = write_run_forces(
        out,
        design,
        conf,
        field={"force_oxdna": pn_to_oxdna_force(2.0), "dir": [0, 0, 5]},
        wall={"dir": [0, 1, 0], "offset_nm": 1.0, "stiff": 5.0},
        anchors=anchors,
    )
    text = out.read_text()
    assert text.count("type = string") == 1  # one uniform field force
    assert text.count("type = repulsion_plane") == 1  # one hard surface
    assert text.count("type = trap") == len(parts) == info["n_anchored"] > 0
    assert info["field"]["dir"] == [0, 0, 1]  # normalized
    assert info["wall"]["stiff"] == 5.0
    assert info["has_forces"] is True


def test_write_run_forces_surface_only_needs_no_anchor(design, geometry, tmp_path):
    """A bare hard surface (steric only) is valid with zero anchors — only a FIELD
    requires anchors (that rule lives in the route)."""
    from backend.physics.oxdna_interface import write_run_forces, write_configuration

    conf = tmp_path / "conf.dat"
    write_configuration(design, geometry, conf)
    out = tmp_path / "run_forces.txt"
    info = write_run_forces(
        out, design, conf, wall={"dir": [0, 1, 0], "offset_nm": 0.0, "stiff": 5.0}
    )
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
    info = write_run_forces(
        tmp_path / "f.txt",
        design,
        conf,
        anchors=[{"kind": "domain", "strand_id": s0.id, "domain_index": 0}],
    )
    assert info["n_anchored"] > 0 and info["field"] is None and info["wall"] is None
    assert info["has_forces"] is True


# ── Stage builder ─────────────────────────────────────────────────────────────


def test_build_run_stage_with_forces_renders():
    from backend.core.oxdna_protocol import build_run_stage, render_stage_input

    st = build_run_stage(
        name="1_production",
        steps=5000,
        external_forces=True,
        forces_file="run_forces.txt",
        forces_meta={"has_field": True, "has_surface": True},
    )
    assert st.kind == "production" and st.sim_type == "MD"  # pools into RMSD/RMSF
    assert st.min_bp_retained == 0.0  # sampling → no bp gate
    assert st.forces_meta == {"has_field": True, "has_surface": True}
    txt = render_stage_input(
        st, "topology.top", "conf.dat", forces_name="run_forces.txt"
    )
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
    above = [
        _pos(0, 0, "forward", (0, 0.5, 0)),
        _pos(0, 1, "forward", (1, 3.0, 0)),
        _pos(0, 2, "reverse", (2, 1.2, 0)),
    ]
    r = measure_wall_response(above, [0, 1, 0], 0.0)
    assert r["passed"] is True
    assert r["n_below"] == 0 and r["n_total"] == 3
    assert r["min_clearance_nm"] == pytest.approx(0.5)

    # One bead sunk well below the plane → fails (penetration).
    sunk = [_pos(0, 0, "forward", (0, 0.5, 0)), _pos(0, 1, "forward", (1, -2.0, 0))]
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
    sd = job.stage_dir(tmp_path, specs[-1].name)
    sd.mkdir(parents=True, exist_ok=True)
    write_configuration(design, geom, sd / "last_conf.dat", box_nm=80.0)
    import json
    from dataclasses import asdict

    (jd / "stages_spec.json").write_text(
        json.dumps([asdict(s) for s in specs], indent=2)
    )
    job.save(tmp_path)
    return job


def _run_client(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient
    from backend.api.main import app
    import backend.api.routes_oxdna as routes_oxdna

    monkeypatch.setattr(routes_oxdna, "_WORKSPACE_DIR", tmp_path)
    monkeypatch.setattr(routes_oxdna, "find_oxdna", lambda: "/usr/bin/true")
    monkeypatch.setattr(routes_oxdna, "is_running", lambda *_a, **_k: False)
    monkeypatch.setattr(
        routes_oxdna, "start_job", lambda *_a, **_k: None
    )  # don't launch oxDNA
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
    r = client.post(
        f"/api/oxdna/jobs/{parent.job_id}/run",
        json={"steps": 1000, "field": {"field_pN": 2.0, "dir": [0, 0, 1]}},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["parent_job_id"] == parent.job_id
    from backend.core.oxdna_job import OxdnaJob

    child = OxdnaJob.load(body["job_id"], tmp_path)
    forces = (child.job_dir(tmp_path) / "run_forces.txt").read_text()
    assert "type = string" in forces  # the uniform field is present
    assert "type = trap" not in forces  # but no anchor traps


def test_run_surface_only_branches_child(design, monkeypatch, tmp_path):
    client, routes_oxdna = _run_client(monkeypatch, tmp_path)
    parent = _completed_parent(tmp_path, design)
    r = client.post(
        f"/api/oxdna/jobs/{parent.job_id}/run",
        json={
            "steps": 1000,
            "surface": {"dir": [0, 1, 0], "offset_nm": 1.0, "stiff": 5.0},
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    # A child job seeded from the relaxed parent, with a composed forces file.
    assert body["parent_job_id"] == parent.job_id
    from backend.core.oxdna_job import OxdnaJob

    child = OxdnaJob.load(body["job_id"], tmp_path)
    forces = (child.job_dir(tmp_path) / "run_forces.txt").read_text()
    assert "type = repulsion_plane" in forces
    assert "type = string" not in forces  # no field requested


def test_run_preserves_surface_anchor_provenance(design, monkeypatch, tmp_path):
    client, _ = _run_client(monkeypatch, tmp_path)
    parent = _completed_parent(tmp_path, design)
    anchor = {
        "kind": "domain",
        "strandId": design.strands[0].id,
        "domainIndex": 0,
    }
    r = client.post(
        f"/api/oxdna/jobs/{parent.job_id}/run",
        json={
            "steps": 1000,
            "surface": {"dir": [0, 1, 0], "offset_nm": 1.0, "stiff": 5.0},
            "surface_anchors": [anchor],
        },
    )
    assert r.status_code == 200, r.text
    from backend.core.oxdna_job import OxdnaJob

    child = OxdnaJob.load(r.json()["job_id"], tmp_path)
    assert child.run_config["anchors"] == []
    assert child.run_config["surface_anchors"] == [anchor]
    forces = (child.job_dir(tmp_path) / "run_forces.txt").read_text()
    assert "type = repulsion_plane" in forces
    assert "type = trap" in forces


def test_surface_deposition_creates_staged_child(design, monkeypatch, tmp_path):
    client, _ = _run_client(monkeypatch, tmp_path)
    parent = _completed_parent(tmp_path, design)
    anchor = {"kind": "domain", "strandId": design.strands[0].id, "domainIndex": 0}
    r = client.post(
        f"/api/oxdna/jobs/{parent.job_id}/surface-deposition",
        json={
            "surface": {"dir": [0, 1, 0], "position_nm": -10, "stiff": 5},
            "surface_anchors": [anchor],
        },
    )
    assert r.status_code == 200, r.text
    from backend.core.oxdna_job import OxdnaJob
    child = OxdnaJob.load(r.json()["job_id"], tmp_path)
    assert child.parent_job_id == parent.job_id
    assert child.run_config["kind"] == "surface_deposition"
    assert [s.kind for s in child.stages] == [
        "deposition_gentle", "deposition_approach", "deposition_settle", "deposition_equil"
    ]
    jd = child.job_dir(tmp_path)
    approach = (jd / "deposition_approach_forces.txt").read_text()
    assert "type = attraction_plane" in approach and "type = trap" not in approach
    import json
    specs = json.loads((jd / "stages_spec.json").read_text())
    assert specs[2]["forces_meta"]["materialize_contact_traps"] is True
    assert specs[2]["forces_meta"]["anchor_stiff"] == pytest.approx(1.0)
    assert child.run_config["approach_retry_chunk_steps"] == 50_000
    assert child.run_config["max_approach_windows"] == 8
    assert child.run_config["capture_gap_nm"] == pytest.approx(1.0)
    assert child.run_config["contact_gap_nm"] == pytest.approx(0.75)


def test_surface_deposition_rejects_force_ceiling_below_initial_force(
    design, monkeypatch, tmp_path
):
    client, _ = _run_client(monkeypatch, tmp_path)
    parent = _completed_parent(tmp_path, design)
    anchor = {"kind": "domain", "strandId": design.strands[0].id, "domainIndex": 0}
    r = client.post(
        f"/api/oxdna/jobs/{parent.job_id}/surface-deposition",
        json={
            "surface": {"dir": [0, 1, 0], "position_nm": -10, "stiff": 5},
            "surface_anchors": [anchor],
            "approach_force_pn": 10,
            "max_approach_force_pn": 5,
        },
    )
    assert r.status_code == 400
    assert "must be >=" in r.text


def _completed_surface_parent(tmp_path, design, *, subject_to_field):
    """A completed relaxation parent that really has surface capture strands built in
    (origami + capture beads in its topology/conf), with the 'Subject strands to
    E-field' toggle stored as ``subject_to_field`` — the state the /run handler reads."""
    import json
    from dataclasses import asdict
    from backend.core.oxdna_protocol import build_relaxation_stages
    from backend.core.oxdna_runner import prepare_oxdna_job
    from backend.api.crud import _geometry_for_design
    from backend.physics.oxdna_interface import _strand_nucleotide_order

    geom = _geometry_for_design(design)
    n_origami = len(_strand_nucleotide_order(design))
    specs = build_relaxation_stages(
        mc_steps=10, md_relax_steps=10, equil_steps=10, surface_present=True
    )
    job = new_oxdna_job("d", [s.to_status() for s in specs])
    surface = {
        "dir": [0, -1, 0],
        "offset_nm": 20.0,
        "stiff": 5.0,
    }  # generous → no clash
    strands = {
        "enabled": True,
        "sequence": "ACGTACGT",
        "attachEnd": "5'",
        "shape": "circle",
        "sizeNm": 60.0,
        "densityPerUm2": 4000.0,
        "seed": 7,
        "subjectToField": subject_to_field,
    }
    info = prepare_oxdna_job(
        design, geom, job, tmp_path, specs, surface=surface, surface_strands=strands
    )
    cap = info["capture"]
    jd = job.job_dir(tmp_path)
    # The relaxed seed _latest_relaxed_conf reads = the final stage's last_conf: reuse the
    # built (origami+caps) conf so the child inherits both the origami and capture beads.
    sd = job.stage_dir(tmp_path, specs[-1].name)
    sd.mkdir(parents=True, exist_ok=True)
    (sd / "last_conf.dat").write_text((jd / "conf.dat").read_text())
    (jd / "stages_spec.json").write_text(
        json.dumps([asdict(s) for s in specs], indent=2)
    )
    job.status = OxdnaStatus.completed
    job.n_nucleotides = n_origami + cap["n_beads"]
    job.run_config = {
        "kind": "relax",
        "surface": surface,
        "surface_strands": {**strands, "built": cap},
    }
    job.save(tmp_path)
    return job, n_origami, cap["n_beads"]


def test_run_field_excludes_capture_strands_when_toggle_off(
    design, monkeypatch, tmp_path
):
    """The 'Subject surface strands to the E-field' toggle OFF → the /run handler writes a
    field the simulation applies to the ORIGAMI ONLY: the string block names particles
    [0, n_origami) and omits every trailing capture-strand bead."""
    client, _ = _run_client(monkeypatch, tmp_path)
    parent, n_origami, n_caps = _completed_surface_parent(
        tmp_path, design, subject_to_field=False
    )
    assert n_caps > 0
    r = client.post(
        f"/api/oxdna/jobs/{parent.job_id}/run",
        json={
            "steps": 1000,
            "field": {"field_pN": 2.0, "dir": [0, 0, 1]},
            "surface": {"dir": [0, -1, 0], "offset_nm": 20.0, "stiff": 5.0},
        },
    )
    assert r.status_code == 200, r.text
    from backend.core.oxdna_job import OxdnaJob

    child = OxdnaJob.load(r.json()["job_id"], tmp_path)
    forces = (child.job_dir(tmp_path) / "run_forces.txt").read_text()

    import re

    # Exactly one uniform field; its particle spec is a comma list of the origami indices.
    assert forces.count("type = string") == 1
    m = re.search(r"type = string\nparticle = ([^\n]+)", forces)
    spec = m.group(1)
    assert spec != "-1"  # NOT field-on-all
    idxs = [int(x) for x in spec.split(",")]
    assert idxs == list(range(n_origami))  # origami only
    n_total = n_origami + n_caps
    assert all(
        cap_idx not in idxs for cap_idx in range(n_origami, n_total)
    )  # caps excluded


def test_run_field_includes_capture_strands_when_toggle_on(
    design, monkeypatch, tmp_path
):
    """Toggle ON (default) → the field is applied to every nucleotide (particle = -1),
    capture strands included — the mirror of the exclusion test."""
    client, _ = _run_client(monkeypatch, tmp_path)
    parent, _n_origami, n_caps = _completed_surface_parent(
        tmp_path, design, subject_to_field=True
    )
    assert n_caps > 0
    r = client.post(
        f"/api/oxdna/jobs/{parent.job_id}/run",
        json={
            "steps": 1000,
            "field": {"field_pN": 2.0, "dir": [0, 0, 1]},
            "surface": {"dir": [0, -1, 0], "offset_nm": 20.0, "stiff": 5.0},
        },
    )
    assert r.status_code == 200, r.text
    from backend.core.oxdna_job import OxdnaJob

    child = OxdnaJob.load(r.json()["job_id"], tmp_path)
    forces = (child.job_dir(tmp_path) / "run_forces.txt").read_text()
    assert "type = string\nparticle = -1" in forces  # field on all nucleotides


def test_run_absolute_surface_position_is_preserved(design, monkeypatch, tmp_path):
    client, _ = _run_client(monkeypatch, tmp_path)
    parent = _completed_parent(tmp_path, design)
    r = client.post(
        f"/api/oxdna/jobs/{parent.job_id}/run",
        json={
            "steps": 1000,
            "surface": {
                "dir": [0, 1, 0],
                "offset_nm": 99.0,
                "position_nm": -7.5,
                "stiff": 5.0,
            },
        },
    )
    assert r.status_code == 200, r.text
    from backend.core.oxdna_job import OxdnaJob

    child = OxdnaJob.load(r.json()["job_id"], tmp_path)
    assert child.run_config["surface"]["position_nm"] == pytest.approx(-7.5)
    assert r.json()["run_config"]["surface"]["position_nm"] == pytest.approx(-7.5)


# ── fix_diffusion off for absolute-coordinate forces (the VoltronCore failure) ─


def test_absolute_forces_render_fix_diffusion_false():
    """A stage carrying a repulsion plane / anchor traps must disable oxDNA's COM
    diffusion-fix, or it recenters coordinates mid-run and shoves the structure
    through the wall (the VoltronCore md_relax explosion)."""
    from backend.core.oxdna_protocol import build_run_stage, render_stage_input

    surf = build_run_stage(
        name="1_production",
        steps=5000,
        external_forces=True,
        forces_file="run_forces.txt",
        absolute_forces=True,
    )
    txt = render_stage_input(
        surf, "topology.top", "conf.dat", forces_name="run_forces.txt"
    )
    assert "fix_diffusion = false" in txt

    # A plain run (uniform field only / no absolute forces) keeps the default.
    plain = build_run_stage(
        name="1_production",
        steps=5000,
        external_forces=True,
        forces_file="run_forces.txt",
        absolute_forces=False,
    )
    txt2 = render_stage_input(
        plain, "topology.top", "conf.dat", forces_name="run_forces.txt"
    )
    assert "fix_diffusion" not in txt2


def test_relax_with_surface_sets_absolute_forces_and_field_too():
    from backend.core.oxdna_protocol import (
        build_relaxation_stages,
        build_field_stage,
        render_stage_input,
    )

    surf = build_relaxation_stages(surface_present=True)
    assert all(s.absolute_forces for s in surf)  # all 3 relax stages
    plain = build_relaxation_stages()
    assert not any(s.absolute_forces for s in plain)  # no surface → diffusion-fix on
    # The mc relax stage renders fix_diffusion=false when surface-bound.
    txt = render_stage_input(
        surf[0], "topology.top", "conf.dat", forces_name="forces.txt"
    )
    assert "fix_diffusion = false" in txt
    # E-field stages (anchor traps) are always absolute.
    fs = build_field_stage(
        name="1_field",
        field_oxdna=0.04,
        field_dir=[1, 0, 0],
        forces_file="field_forces.txt",
        steps=2000,
    )
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
    info = prepare_oxdna_job(
        design, geometry, job, tmp_path, specs, surface=surface, anchors=anchors
    )
    jd = job.job_dir(tmp_path)
    forces = (jd / "forces.txt").read_text()
    assert "type = mutual_trap" in forces  # WC pairs still held during relax
    assert "type = repulsion_plane" in forces  # ... while bound to the surface
    assert forces.count("type = trap") > 0  # ... and anchored
    assert "type = string" not in forces  # NO field in relaxation
    equil = (jd / "equil_forces.txt").read_text()
    assert "type = repulsion_plane" in equil
    assert "type = mutual_trap" not in equil  # equil drops the pair traps
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
    r = client.post(
        f"/api/oxdna/jobs/{parent.job_id}/run",
        json={
            "steps": 1000,
            "field": {"field_pN": 2.0, "dir": [0, 0, 1]},
            "surface": {"dir": [0, 1, 0], "offset_nm": 0.0, "stiff": 5.0},
            "anchors": [{"kind": "domain", "strandId": s0.id, "domainIndex": 0}],
        },
    )
    assert r.status_code == 200, r.text
    from backend.core.oxdna_job import OxdnaJob

    child = OxdnaJob.load(r.json()["job_id"], tmp_path)
    forces = (child.job_dir(tmp_path) / "run_forces.txt").read_text()
    assert "type = string" in forces and "type = repulsion_plane" in forces
    assert forces.count("type = trap") > 0
