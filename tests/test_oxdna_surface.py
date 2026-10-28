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


def test_continued_surface_anchors_only_fix_surface_normal(design, geometry, tmp_path):
    """A post-deposition run must not freeze either coordinate in the surface plane."""
    from backend.physics.oxdna_interface import write_run_forces, write_configuration

    conf = tmp_path / "conf.dat"
    write_configuration(design, geometry, conf)
    s0 = design.strands[0]
    out = tmp_path / "run_forces.txt"
    info = write_run_forces(
        out,
        design,
        conf,
        wall={"dir": [0, 1, 0], "offset_nm": 0.0, "stiff": 5.0},
        surface_anchors=[{"kind": "domain", "strand_id": s0.id, "domain_index": 0}],
    )
    text = out.read_text()
    assert "type = lowdim_trap" in text
    assert "visibility = 0,1,0" in text
    assert "type = trap\n" not in text
    assert info["surface_anchor_particles"]


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
    from backend.physics.oxdna_interface import write_configuration, write_topology
    from backend.api.crud import _geometry_for_design
    from backend.core.oxdna_protocol import build_relaxation_stages

    specs = build_relaxation_stages(mc_steps=10, md_relax_steps=10, equil_steps=10)
    job = new_oxdna_job("d", [s.to_status() for s in specs])
    job.status = OxdnaStatus.completed
    jd = job.job_dir(tmp_path)
    jd.mkdir(parents=True, exist_ok=True)
    (jd / "design.json").write_text(design.model_dump_json())
    write_topology(design, jd / "topology.top")
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


def test_run_creates_child_queued_without_autostarting(design, monkeypatch, tmp_path):
    """append_oxdna_run creates the child queued but does NOT start it — the panel's
    single Run button (NAMD-parity job creation flow) starts it explicitly, matching
    how a freshly-created local relaxation already behaves."""
    from unittest.mock import MagicMock

    client, routes_oxdna = _run_client(monkeypatch, tmp_path)
    start_job_mock = MagicMock()
    monkeypatch.setattr(routes_oxdna, "start_job", start_job_mock)
    parent = _completed_parent(tmp_path, design)
    r = client.post(f"/api/oxdna/jobs/{parent.job_id}/run", json={"steps": 1000})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "queued"
    start_job_mock.assert_not_called()


def test_new_run_stage_settings_persist_and_validate(design, monkeypatch, tmp_path):
    client, routes = _run_client(monkeypatch, tmp_path)
    parent = _completed_parent(tmp_path, design)
    overrides = {"1_production": {
        "thermostat": "langevin", "diff_coeff": 0.5, "dt": 0.001,
        "refresh_vel": False, "temperature": "300K",
    }}
    response = client.post(f"/api/oxdna/jobs/{parent.job_id}/run", json={
        "steps": 1000, "stage_overrides": overrides,
    })
    assert response.status_code == 200, response.text
    job = response.json()
    assert job["status"] == "queued"
    assert job["run_config"]["stage_overrides"] == overrides
    spec = routes.load_stage_specs(tmp_path / "oxdna_jobs" / job["job_id"])[0]
    assert spec.thermostat == "langevin"
    assert spec.diff_coeff == 0.5
    assert spec.dt == 0.001
    assert spec.refresh_vel is False
    assert spec.temperature == "300K"
    for invalid in ({"thermostat": "langevin"}, {"external_forces": False}, {"dt": -1}):
        rejected = client.post(f"/api/oxdna/jobs/{parent.job_id}/run", json={
            "steps": 1000, "stage_overrides": {"1_production": invalid},
        })
        assert rejected.status_code == 422, rejected.text


def test_continuation_inherits_resolved_final_stage_and_allows_overrides(design, monkeypatch, tmp_path):
    import json
    from dataclasses import asdict
    client, routes = _run_client(monkeypatch, tmp_path)
    parent = _completed_parent(tmp_path, design)
    specs = routes.load_stage_specs(parent.job_dir(tmp_path))
    final = specs[-1]
    final.thermostat, final.diff_coeff = 'langevin', 0.7
    final.dt, final.temperature = 0.001, '310K'
    final.refresh_vel, final.newtonian_steps = False, 71
    (parent.job_dir(tmp_path) / 'stages_spec.json').write_text(json.dumps([asdict(s) for s in specs]))
    inherited = client.get(f'/api/oxdna/jobs/{parent.job_id}').json()['continuation_parameters']
    assert inherited['thermostat'] == 'langevin'
    assert inherited['diff_coeff'] == 0.7
    for overrides, expected in (({}, 0.7), ({'1_production': {'diff_coeff': 0.2}}, 0.2)):
        response = client.post(f'/api/oxdna/jobs/{parent.job_id}/run', json={'steps': 1000, 'stage_overrides': overrides})
        assert response.status_code == 200, response.text
        spec = routes.load_stage_specs(tmp_path / 'oxdna_jobs' / response.json()['job_id'])[0]
        assert spec.thermostat == 'langevin'
        assert spec.diff_coeff == expected
        assert spec.dt == 0.001
        assert spec.temperature == '310K'
        assert spec.refresh_vel is False
        assert spec.newtonian_steps == 71
        # Relaxation-only force caps are not carried into production sampling.
        assert spec.max_backbone_force is None
    # Continue again from the edited production child, not its relaxation ancestor.
    from backend.core.oxdna_job import OxdnaJob
    child = OxdnaJob.load(response.json()['job_id'], tmp_path)
    child.status = OxdnaStatus.completed
    stage_dir = child.stage_dir(tmp_path, spec.name)
    stage_dir.mkdir(parents=True, exist_ok=True)
    (stage_dir / 'last_conf.dat').write_bytes((child.job_dir(tmp_path) / 'conf.dat').read_bytes())
    child.save(tmp_path)
    chained = client.post(f'/api/oxdna/jobs/{child.job_id}/run', json={'steps': 1000})
    assert chained.status_code == 200, chained.text
    chained_spec = routes.load_stage_specs(tmp_path / 'oxdna_jobs' / chained.json()['job_id'])[0]
    assert chained_spec.diff_coeff == 0.2
    assert chained_spec.thermostat == 'langevin'
    # Deposition keeps the thermostat and its own conservative timestep ceiling.
    deposition = routes.build_surface_deposition_stages()
    routes._inherit_continuation_parameters(deposition, child, tmp_path, deposition=True)
    assert all(stage.thermostat == 'langevin' and stage.diff_coeff == 0.2 and stage.dt == 0.001 for stage in deposition)


def test_queued_field_edits_persist_and_enable_engine_forces(design, monkeypatch, tmp_path):
    from unittest.mock import Mock
    from backend.core.oxdna_job import OxdnaJob
    client, routes = _run_client(monkeypatch, tmp_path)
    start = Mock()
    monkeypatch.setattr(routes, 'start_job', start)
    parent = _completed_parent(tmp_path, design)
    created = client.post(f'/api/oxdna/jobs/{parent.job_id}/run', json={'steps': 1234})
    assert created.status_code == 200, created.text
    jid = created.json()['job_id']
    jd = tmp_path / 'oxdna_jobs' / jid
    assert not routes.load_stage_specs(jd)[0].external_forces
    for field in ({'field_pN': 2.0, 'dir': [0, 0, 1]},
                  {'field_pN': 3.0, 'dir': [0, -1, 0]}, None):
        saved = client.put(f'/api/oxdna/jobs/{jid}/settings', json={'field': field})
        assert saved.status_code == 200, saved.text
        job = OxdnaJob.load(jid, tmp_path)
        assert job.status == OxdnaStatus.queued
        assert job.run_config['field'] == field
        spec = routes.load_stage_specs(jd)[0]
        assert spec.steps == 1234
        assert spec.external_forces == bool(field)
        assert bool(spec.efield) == bool(field)
        assert bool(job.efield) == bool(field)
        if field:
            forces = (jd / spec.forces_file).read_text()
            assert 'type = string' in forces
            assert 'dir = ' + ','.join(f'{v:g}' for v in field['dir']) in forces
            assert spec.efield['force_pN'] == field['field_pN']
            assert spec.efield['dir'] == field['dir']
    start.assert_not_called()


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
    assert "type = lowdim_trap" in forces
    assert "visibility = 0,1,0" in forces


@pytest.mark.parametrize("external_dir", [False, True])
def test_surface_deposition_creates_staged_child(design, monkeypatch, tmp_path, external_dir):
    from unittest.mock import Mock
    client, routes = _run_client(monkeypatch, tmp_path)
    start = Mock()
    monkeypatch.setattr(routes, 'start_job', start)
    parent = _completed_parent(tmp_path, design)
    anchor = {"kind": "domain", "strandId": design.strands[0].id, "domainIndex": 0}
    destination = tmp_path / "external"
    destination.mkdir()
    r = client.post(
        f"/api/oxdna/jobs/{parent.job_id}/surface-deposition",
        json={
            "run_dir": str(destination) if external_dir else None,
            "surface": {"dir": [0, 1, 0], "position_nm": -10, "stiff": 5},
            "surface_anchors": [anchor],
        },
    )
    assert r.status_code == 200, r.text
    from backend.core.oxdna_job import OxdnaJob
    child = OxdnaJob.load(r.json()["job_id"], tmp_path)
    assert child.parent_job_id == parent.job_id
    assert child.run_config["kind"] == "surface_deposition"
    assert child.status == OxdnaStatus.queued
    start.assert_not_called()
    assert [s.kind for s in child.stages] == [
        "deposition_gentle", "deposition_approach", "deposition_settle", "deposition_equil"
    ]
    jd = child.job_dir(tmp_path)
    assert jd.parent == (destination if external_dir else tmp_path / "oxdna_jobs")
    approach = (jd / "deposition_approach_forces.txt").read_text()
    assert "type = attraction_plane" in approach and "type = trap" not in approach
    import json
    specs = json.loads((jd / "stages_spec.json").read_text())
    assert specs[2]["forces_meta"]["materialize_contact_traps"] is True
    assert specs[2]["forces_meta"]["anchor_stiff"] == pytest.approx(2.0)
    assert child.run_config["approach_retry_chunk_steps"] == 10_000
    assert child.run_config["max_approach_windows"] == 40
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


def test_run_keeps_surface_anchors_free_in_plane(design, monkeypatch, tmp_path):
    client, _ = _run_client(monkeypatch, tmp_path)
    parent = _completed_parent(tmp_path, design)
    s0 = design.strands[0]
    r = client.post(
        f"/api/oxdna/jobs/{parent.job_id}/run",
        json={
            "steps": 1000,
            "surface": {"dir": [0, 1, 0], "offset_nm": 0.0, "stiff": 5.0},
            "surface_anchors": [
                {"kind": "domain", "strandId": s0.id, "domainIndex": 0}
            ],
        },
    )
    assert r.status_code == 200, r.text
    from backend.core.oxdna_job import OxdnaJob

    child = OxdnaJob.load(r.json()["job_id"], tmp_path)
    forces = (child.job_dir(tmp_path) / "run_forces.txt").read_text()
    assert "type = lowdim_trap" in forces
    assert "visibility = 0,1,0" in forces
    assert "type = trap\n" not in forces


def test_queued_run_deposition_toggle_edits_same_job_and_waits_for_run(design, monkeypatch, tmp_path):
    from unittest.mock import Mock
    from backend.core.oxdna_job import OxdnaJob
    client, routes = _run_client(monkeypatch, tmp_path)
    start = Mock()
    monkeypatch.setattr(routes, 'start_job', start)
    parent = _completed_parent(tmp_path, design)
    # Hybrid children must carry the frozen parameter data; it is not in topology.top.
    (parent.job_dir(tmp_path) / 'anm.par').write_text('frozen protein parameters')
    import backend.physics.oxdna_protein as proteins
    monkeypatch.setattr(proteins, 'has_proteins', lambda _: True)
    created = client.post(f'/api/oxdna/jobs/{parent.job_id}/run', json={'steps': 3000})
    assert created.status_code == 200, created.text
    jid = created.json()['job_id']
    jd = tmp_path / 'oxdna_jobs' / jid
    assert (jd / 'anm.par').read_text() == 'frozen protein parameters'
    anchor = {'kind': 'domain', 'strandId': design.strands[0].id, 'domainIndex': 0}
    patch = {'surface_deposition': True, 'surface': {'dir': [0, 1, 0], 'position_nm': -10, 'stiff': 5},
             'anchors': [], 'surface_anchors': [anchor], 'surface_strands': None}
    saved = client.put(f'/api/oxdna/jobs/{jid}/settings', json=patch)
    assert saved.status_code == 200, saved.text
    assert saved.json()['job_id'] == jid
    assert saved.json()['status'] == 'queued'
    assert len(saved.json()['stages']) == 4
    assert (jd / 'anm.par').read_text() == 'frozen protein parameters'
    assert len(list((tmp_path / 'oxdna_jobs').glob('*/job.json'))) == 2
    start.assert_not_called()
    edited = client.put(f'/api/oxdna/jobs/{jid}/settings', json={
        **saved.json()['run_config'],
        'stages': [{'name': '1_surface_gentle', 'steps': 2000, 'dt': 0.001}],
    })
    assert edited.status_code == 200, edited.text
    changed = client.put(f'/api/oxdna/jobs/{jid}/settings', json={
        'surface': {'dir': [0, 1, 0], 'position_nm': -11, 'stiff': 5},
    })
    assert changed.status_code == 200, changed.text
    assert changed.json()['stages'][0]['steps'] == 2000
    assert routes.load_stage_specs(jd)[0].dt == 0.001
    off = client.put(f'/api/oxdna/jobs/{jid}/settings', json={'surface_deposition': False})
    assert off.status_code == 200, off.text
    assert off.json()['run_config']['kind'] == 'run'
    assert off.json()['stages'][0]['steps'] == 3000
    assert off.json()['run_config']['surface_anchors'] == [anchor]
    on = client.put(f'/api/oxdna/jobs/{jid}/settings', json={'surface_deposition': True})
    assert on.status_code == 200, on.text
    start.assert_not_called()
    # Resume also repairs legacy children that were prepared without anm.par.
    (jd / 'anm.par').unlink()
    assert client.post(f'/api/oxdna/jobs/{jid}/start').status_code == 200
    assert (jd / 'anm.par').read_text() == 'frozen protein parameters'
    start.assert_called_once()
    assert client.put(f'/api/oxdna/jobs/{jid}/settings', json={'surface_deposition': False}).status_code == 409


def test_deposition_invalid_edit_leaves_prepared_job_untouched(design, monkeypatch, tmp_path):
    client, routes = _run_client(monkeypatch, tmp_path)
    parent = _completed_parent(tmp_path, design)
    created = client.post(f'/api/oxdna/jobs/{parent.job_id}/run', json={'steps': 1000}).json()
    jd = tmp_path / 'oxdna_jobs' / created['job_id']
    before = {name: (jd / name).read_bytes() for name in ['job.json', 'stages_spec.json', 'conf.dat']}
    bad = client.put(f"/api/oxdna/jobs/{created['job_id']}/settings", json={'surface_deposition': True})
    assert bad.status_code == 422, bad.text
    assert all((jd / name).read_bytes() == content for name, content in before.items())


def test_surface_capture_retains_adsorption_without_waiving_first_contact(design, geometry, tmp_path):
    import numpy as np
    from backend.physics.oxdna_interface import (
        write_configuration, resolve_anchor_particles, NM_TO_OXDNA,
        write_surface_deposition_approach_forces, write_surface_deposition_settle_forces,
    )
    conf = tmp_path / 'conf.dat'
    write_configuration(design, geometry, conf)
    lines = conf.read_text().splitlines()
    rows = np.loadtxt(conf, skiprows=3)
    anchors = [{'kind': 'domain', 'strand_id': design.strands[0].id, 'domain_index': 0}]
    particles, _ = resolve_anchor_particles(design, anchors)
    wall = {'dir': [0, 1, 0], 'position_nm': 0, 'stiff': 5}
    def at_gap(nm):
        rows[particles, 1] = nm * NM_TO_OXDNA
        with conf.open('w') as stream:
            stream.write('\n'.join(lines[:3]) + '\n')
            np.savetxt(stream, rows)
    def approach(**kwargs):
        return write_surface_deposition_approach_forces(tmp_path / 'approach.txt', design, conf,
            wall=wall, anchors=anchors, force_pn=5, capture_contacted=True, **kwargs)
    at_gap(0.9)  # Capturable, but not yet inside the actual 0.75 nm contact threshold.
    near = approach()
    assert set(near['captured_particles']) == set(particles)
    assert near['contacted_particles'] == []
    with pytest.raises(ValueError, match='did not reach contact'):
        write_surface_deposition_settle_forces(tmp_path / 'settle.txt', design, conf,
            wall=wall, anchors=anchors, contacted_particles=near['contacted_particles'])
    at_gap(0.5)
    reached = approach(captured_particles=near['captured_particles'])
    assert set(reached['contacted_particles']) == set(particles)
    at_gap(1.25)  # A later fluctuation must not switch an established bond off.
    retained = approach(captured_particles=reached['captured_particles'],
                        contacted_particles=reached['contacted_particles'])
    assert set(retained['captured_particles']) == set(particles)
    assert set(retained['contacted_particles']) == set(particles)
    assert retained['remaining_particles'] == []
    before = conf.read_bytes()
    write_surface_deposition_settle_forces(tmp_path / 'settle.txt', design, conf,
        wall=wall, anchors=anchors, contacted_particles=retained['contacted_particles'])
    assert conf.read_bytes() == before  # No coordinate projection/teleportation.
    assert 'lowdim_trap' in (tmp_path / 'settle.txt').read_text()
    with pytest.raises(ValueError, match='did not reach contact'):
        write_surface_deposition_settle_forces(tmp_path / 'fresh.txt', design, conf,
            wall=wall, anchors=anchors)  # An unbound distant anchor still fails.


def test_copy_deposition_discards_runtime_contact_history(design, monkeypatch, tmp_path):
    from backend.core.oxdna_job import OxdnaJob
    client, _ = _run_client(monkeypatch, tmp_path)
    parent = _completed_parent(tmp_path, design)
    created = client.post(f'/api/oxdna/jobs/{parent.job_id}/surface-deposition', json={
        'surface': {'dir': [0, 1, 0], 'position_nm': -10, 'stiff': 5},
        'surface_anchors': [{'kind': 'domain', 'strandId': design.strands[0].id, 'domainIndex': 0}],
    })
    assert created.status_code == 200, created.text
    job = OxdnaJob.load(created.json()['job_id'], tmp_path)
    job.run_config.update(surface_captured_particles=[0], surface_contacted_particles=[0], approach_retry_count=5)
    job.save(tmp_path)
    (job.job_dir(tmp_path) / 'deposition_approach_forces.txt').write_text('stale lowdim_trap')
    (job.job_dir(tmp_path) / 'deposition_settle_forces.txt').write_text('stale contacts')
    response = client.post(f'/api/oxdna/jobs/{job.job_id}/copy')
    assert response.status_code == 200, response.text
    copied = OxdnaJob.load(response.json()['job']['job_id'], tmp_path)
    assert 'surface_contacted_particles' not in copied.run_config
    assert 'surface_captured_particles' not in copied.run_config
    assert 'approach_retry_count' not in copied.run_config
    assert copied.run_config['approach_retry_chunk_steps'] == 10000
    assert not (copied.job_dir(tmp_path) / 'deposition_settle_forces.txt').exists()
    assert 'attraction_plane' in (copied.job_dir(tmp_path) / 'deposition_approach_forces.txt').read_text()


@pytest.mark.parametrize('thermal_excursion', [False, True])
def test_deposition_continuation_uses_previous_final_frame(design, monkeypatch, tmp_path, thermal_excursion):
    """Create -> edit -> run supports repeated deposition without repositioning."""
    from unittest.mock import Mock
    from backend.core.oxdna_job import OxdnaJob
    client, routes = _run_client(monkeypatch, tmp_path)
    start = Mock()
    monkeypatch.setattr(routes, 'start_job', start)
    parent = _completed_parent(tmp_path, design)
    settings = {
        'surface': {'dir': [0, 1, 0], 'position_nm': -10, 'stiff': 5},
        'surface_anchors': [{'kind': 'domain', 'strandId': design.strands[0].id, 'domainIndex': 0}],
    }
    first = client.post(f'/api/oxdna/jobs/{parent.job_id}/surface-deposition', json=settings)
    assert first.status_code == 200, first.text
    deposited = OxdnaJob.load(first.json()['job_id'], tmp_path)
    jd = deposited.job_dir(tmp_path)
    # Give the final checkpoint a distinct lateral displacement from the starting frame.
    lines = (jd / 'conf.dat').read_text().splitlines()
    for i in range(3, len(lines)):
        values = lines[i].split()
        values[0] = str(float(values[0]) + 0.25)
        lines[i] = ' '.join(values)
    if thermal_excursion:
        from backend.core.constants import NM_TO_OXDNA
        values = lines[3].split()
        values[1] = str((-10 - 0.321) * NM_TO_OXDNA)
        lines[3] = ' '.join(values)
    final = '\n'.join(lines) + '\n'
    checkpoint = deposited.stage_dir(tmp_path, deposited.stages[-1].name) / 'last_conf.dat'
    checkpoint.parent.mkdir(parents=True)
    checkpoint.write_text(final)
    deposited.status = OxdnaStatus.completed
    for stage in deposited.stages:
        stage.status = 'done'
    deposited.save(tmp_path)
    parent_record = (jd / 'job.json').read_bytes()
    continuation = client.post(f'/api/oxdna/jobs/{deposited.job_id}/run', json=settings)
    assert continuation.status_code == 200, continuation.text
    child_id = continuation.json()['job_id']
    toggled = client.put(f'/api/oxdna/jobs/{child_id}/settings', json={
        **settings, 'surface_deposition': True,
    })
    assert toggled.status_code == 200, toggled.text
    child = OxdnaJob.load(child_id, tmp_path)
    assert child.status == OxdnaStatus.queued
    assert child.parent_job_id == deposited.job_id
    assert child.run_config['kind'] == 'surface_deposition'
    assert child.run_config['surface'] == deposited.run_config['surface']
    assert len(child.stages) == 4
    import numpy as np
    from io import StringIO
    actual = (child.job_dir(tmp_path) / 'conf.dat').read_text()
    assert actual.splitlines()[:3] == final.splitlines()[:3]
    np.testing.assert_allclose(np.loadtxt(StringIO(actual), skiprows=3),
                               np.loadtxt(StringIO(final), skiprows=3), rtol=0, atol=1e-12)
    assert (jd / 'job.json').read_bytes() == parent_record
    assert checkpoint.read_text() == final
    # Add another anchor without Run, then read it through a fresh API client
    # and a fresh job load: persistence must not depend on a frontend cache.
    added = {'kind': 'domain', 'strandId': design.strands[1].id, 'domainIndex': 0}
    anchors = [*settings['surface_anchors'], added]
    saved = client.put(f'/api/oxdna/jobs/{child_id}/settings', json={'surface_anchors': anchors})
    assert saved.status_code == 200, saved.text
    reloaded = OxdnaJob.load(child_id, tmp_path)
    assert reloaded.run_config['surface_anchors'] == anchors
    assert reloaded.status == OxdnaStatus.queued
    fresh_client, _ = _run_client(monkeypatch, tmp_path)
    fetched = fresh_client.get(f'/api/oxdna/jobs/{child_id}')
    assert fetched.status_code == 200, fetched.text
    assert fetched.json()['run_config']['surface_anchors'] == anchors
    start.assert_not_called()


def test_surface_approach_retry_preserves_checkpoint_velocities(design, monkeypatch, tmp_path):
    import shutil
    from backend.core.oxdna_job import OxdnaJob
    client, routes = _run_client(monkeypatch, tmp_path)
    parent = _completed_parent(tmp_path, design)
    response = client.post(f'/api/oxdna/jobs/{parent.job_id}/surface-deposition', json={
        'surface': {'dir': [0, 1, 0], 'position_nm': -10, 'stiff': 5},
        'surface_anchors': [{'kind': 'domain', 'strandId': design.strands[0].id, 'domainIndex': 0}],
    })
    assert response.status_code == 200, response.text
    job = OxdnaJob.load(response.json()['job_id'], tmp_path)
    jd = job.job_dir(tmp_path)
    specs = routes.load_stage_specs(jd)
    checkpoint = jd / specs[1].name / 'last_conf.dat'
    checkpoint.parent.mkdir()
    shutil.copy(jd / 'conf.dat', checkpoint)
    before = checkpoint.read_bytes()
    old_steps = specs[1].steps
    updated = routes._prepare_surface_approach_retry(job, specs, tmp_path)
    assert updated[1].refresh_vel is False
    assert updated[1].steps == old_steps + 10000
    assert routes.load_stage_specs(jd)[1].refresh_vel is False
    assert checkpoint.read_bytes() == before


@pytest.mark.parametrize('checkpoint', [False, True])
def test_hybrid_deposition_targets_selected_dna_not_leading_proteins(design, geometry, tmp_path, checkpoint):
    from backend.core.constants import NM_TO_OXDNA
    from backend.physics.oxdna_interface import (
        write_configuration, _strand_nucleotide_order,
        write_surface_deposition_approach_forces, write_surface_deposition_settle_forces,
        place_configuration_against_surface,
    )
    seed = tmp_path / 'conf.dat'
    write_configuration(design, geometry, seed)
    lines = seed.read_text().splitlines()
    n_dna = len(lines) - 3
    # Two leading protein beads; DNA index zero is absolute particle two.
    row = '0 0.1 0 1 0 0 0 0 1 0 0 0 0 0 0'
    dna = ['0 20 0 1 0 0 0 0 1 0 0 0 0 0 0'] * n_dna
    seed.write_text('\n'.join(lines[:3] + [row, row] + dna) + '\n')
    (tmp_path / 'topology.top').write_text(f'{n_dna + 2} 3 {n_dna} 2 2\n')
    if checkpoint:
        stage = tmp_path / '2_surface_approach'; stage.mkdir()
        conf = stage / 'last_conf.dat'; conf.write_bytes(seed.read_bytes())
    else:
        conf = seed
    key = _strand_nucleotide_order(design)[0]
    anchor = {'kind': 'base', 'helixId': key[0], 'bp': key[1], 'direction': key[2]}
    wall = {'dir': [0, 1, 0], 'position_nm': 0, 'stiff': 5}
    placement = place_configuration_against_surface(conf, design, wall=wall, anchors=[anchor], translate=False)
    assert placement['anchor_gap_min_nm'] == pytest.approx(20 / NM_TO_OXDNA)
    approach = write_surface_deposition_approach_forces(tmp_path/'approach.txt', design, conf,
        wall=wall, anchors=[anchor], capture_contacted=True)
    assert approach['anchor_particles'] == [2]
    assert approach['captured_particles'] == []
    assert 'type = attraction_plane' in (tmp_path/'approach.txt').read_text()
    with pytest.raises(ValueError, match='did not reach contact'):
        write_surface_deposition_settle_forces(tmp_path/'settle.txt', design, conf, wall=wall, anchors=[anchor])
    # The old wrong-particle contact history cannot bypass the corrected gate.
    with pytest.raises(ValueError, match='different particle indices'):
        write_surface_deposition_settle_forces(tmp_path/'settle.txt', design, conf,
            wall=wall, anchors=[anchor], contacted_particles=[0])
    data = conf.read_text().splitlines(); data[5] = row
    conf.write_text('\n'.join(data) + '\n')
    before = conf.read_bytes()
    captured = write_surface_deposition_approach_forces(tmp_path/'retry.txt', design, conf,
        wall=wall, anchors=[anchor], capture_contacted=True)
    assert captured['captured_particles'] == [2]
    assert captured['contacted_particles'] == [2]
    settled = write_surface_deposition_settle_forces(tmp_path/'settle.txt', design, conf,
        wall=wall, anchors=[anchor], contacted_particles=captured['contacted_particles'])
    assert settled['anchor_particles'] == [2]
    text = (tmp_path/'settle.txt').read_text()
    assert 'type = lowdim_trap\nparticle = 2\n' in text
    assert conf.read_bytes() == before
    # Missing/mismatched topology must never silently fall back to DNA-only indices.
    (tmp_path/'topology.top').unlink()
    with pytest.raises(ValueError, match='requires topology.top'):
        write_surface_deposition_approach_forces(tmp_path/'bad.txt', design, conf, wall=wall, anchors=[anchor])


def test_legacy_hybrid_deposition_cannot_resume_old_wrong_particle_forces(tmp_path):
    import asyncio
    from backend.core.oxdna_runner import run_job
    job = new_oxdna_job('legacy SD', [], run_config={'kind': 'surface_deposition'})
    jd = job.job_dir(tmp_path); jd.mkdir(parents=True)
    (jd / 'topology.top').write_text('5 2 3 2 1\n')
    job.status = OxdnaStatus.running; job.save(tmp_path)
    asyncio.run(run_job(job, tmp_path, []))
    assert job.status == OxdnaStatus.failed
    assert 'corrected anchor indexing' in job.error
