"""Route tests for attaching forces to an already-prepared job."""
from __future__ import annotations
import json
from pathlib import Path
import pytest


def _prepared_job(ws: Path, status="queued"):
    from backend.core.md_job import MdSegmentStatus, MdStatus, new_job
    from backend.core.atomistic import build_atomistic_model
    from backend.core.namd_topology import _write_segment_pdbs
    from tests.conftest import make_6hb_design
    job = new_job(design_name="D", protocol="mgh_slow_release",
                  name_stem="D", package_subdir="package/D_namd_solvated")
    job.status = getattr(MdStatus, status)
    job.segments.append(MdSegmentStatus(name="D_01_stage", stage="s", percent=100.0,
                                        steps=10, status="pending"))
    job.save(ws)
    pkg = job.package_dir(ws); pkg.mkdir(parents=True, exist_ok=True)
    design = make_6hb_design()
    model = build_atomistic_model(design)
    _segs, full = _write_segment_pdbs(design, pkg, model)
    (pkg / "D.pdb").write_text(full)
    (pkg / "manifest.json").write_text(json.dumps({
        "name_stem": "D", "box_ang": [100.0, 100.0, 100.0], "files": {},
        "charge_audit": {"topology_builder": "charmm_psfgen"},
        "segments": [{"name": "D_01_stage", "steps": 10}]}))
    (pkg / "D_01_stage.conf").write_text(
        "structure          D.psf\ntimestep           2\nconstraints        off\n"
        "binCoordinates     output/prev.coor\nrun                10\n")
    job.job_dir(ws).mkdir(parents=True, exist_ok=True)
    (job.job_dir(ws) / "design.json").write_text(design.model_dump_json())
    return job, design, pkg


def _routes(ws: Path, monkeypatch):
    from backend.api import routes_md
    monkeypatch.setattr(routes_md, "_workspace", lambda: ws)
    monkeypatch.setattr(routes_md, "is_running", lambda jid: False)
    return routes_md


def test_forces_attach_to_a_prepared_job_without_re_prepping(tmp_path, monkeypatch):
    """The wizard's Create builds the package; forces are chosen afterwards against the
    job you can see in the list. Attaching must patch the confs in place."""
    import asyncio
    routes_md = _routes(tmp_path, monkeypatch)
    job, design, pkg = _prepared_job(tmp_path)
    before = (pkg / "D_01_stage.conf").read_text()

    r = asyncio.run(routes_md.set_md_job_forces(job.job_id, routes_md.JobForcesRequest(
        anchors=[{"kind": "strand", "id": design.strands[0].id}], anchor_atoms=["C1'"])))

    assert r["ok"] and r["anchors"]["n_atoms_fixed"] > 0
    assert (pkg / "restraints_anchors.pdb").exists()
    conf = (pkg / "D_01_stage.conf").read_text()
    assert "fixedAtomsFile     restraints_anchors.pdb" in conf
    # everything the prep decided is untouched — this is the whole point of patching
    for keep in ("timestep           2", "run                10",
                 "binCoordinates     output/prev.coor"):
        assert keep in conf and keep in before
    m = json.loads((pkg / "manifest.json").read_text())
    assert m["files"]["anchors"] == "restraints_anchors.pdb"
    assert m["anchors"]["attached_after_prep"] is True


def test_forces_can_be_cleared_again(tmp_path, monkeypatch):
    import asyncio
    routes_md = _routes(tmp_path, monkeypatch)
    job, design, pkg = _prepared_job(tmp_path)
    req = routes_md.JobForcesRequest
    asyncio.run(routes_md.set_md_job_forces(job.job_id, req(
        anchors=[{"kind": "strand", "id": design.strands[0].id}], anchor_atoms=["C1'"])))
    asyncio.run(routes_md.set_md_job_forces(job.job_id, req(anchors=[], field=None)))
    conf = (pkg / "D_01_stage.conf").read_text()
    assert "fixedAtoms" not in conf and "eField" not in conf
    assert not (pkg / "restraints_anchors.pdb").exists()
    assert json.loads((pkg / "manifest.json").read_text())["files"]["anchors"] is None


def test_forces_refused_once_the_job_has_run(tmp_path, monkeypatch):
    """A completed job's forces describe the trajectory it produced. Rewriting them would
    make the record disagree with the DCD on disk."""
    import asyncio
    from fastapi import HTTPException
    routes_md = _routes(tmp_path, monkeypatch)
    job, design, _pkg = _prepared_job(tmp_path, status="completed")
    with pytest.raises(HTTPException) as e:
        asyncio.run(routes_md.set_md_job_forces(job.job_id, routes_md.JobForcesRequest(
            anchors=[{"kind": "strand", "id": design.strands[0].id}])))
    assert e.value.status_code == 400 and "already run" in e.value.detail


def test_bad_atom_filter_is_rejected_not_silently_unanchored(tmp_path, monkeypatch):
    import asyncio
    from fastapi import HTTPException
    routes_md = _routes(tmp_path, monkeypatch)
    job, design, _ = _prepared_job(tmp_path)
    with pytest.raises(HTTPException) as e:
        asyncio.run(routes_md.set_md_job_forces(job.job_id, routes_md.JobForcesRequest(
            anchors=[{"kind": "strand", "id": design.strands[0].id}], anchor_atoms=["CA"])))
    assert e.value.status_code == 400 and "matched no heavy atom" in e.value.detail


def test_get_forces_reports_what_the_job_actually_holds(tmp_path, monkeypatch):
    import asyncio
    routes_md = _routes(tmp_path, monkeypatch)
    job, design, _pkg = _prepared_job(tmp_path)

    before = asyncio.run(routes_md.get_md_job_forces(job.job_id))
    assert before["prepared"] and before["editable"] and before["anchors"] is None

    asyncio.run(routes_md.set_md_job_forces(job.job_id, routes_md.JobForcesRequest(
        anchors=[{"kind": "strand", "id": design.strands[0].id}], anchor_atoms=["C1'"])))
    after = asyncio.run(routes_md.get_md_job_forces(job.job_id))
    assert after["anchors"]["applied"] is True
    assert after["anchors"]["n_atoms_fixed"] > 0
    assert after["anchors"]["requested"]          # the card repopulates from this
    assert after["editable"] is True


def test_get_forces_marks_a_selection_that_resolved_to_nothing_as_not_applied(
        tmp_path, monkeypatch):
    """A recorded `requested` list with zero resolved atoms must not read as anchored —
    that ambiguity is exactly what made the card misleading."""
    import asyncio, json as _json
    routes_md = _routes(tmp_path, monkeypatch)
    job, _design, pkg = _prepared_job(tmp_path)
    m = _json.loads((pkg / "manifest.json").read_text())
    m["anchors"] = {"requested": [{"kind": "base"}], "n_atoms_fixed": 0, "file": None}
    (pkg / "manifest.json").write_text(_json.dumps(m))

    d = asyncio.run(routes_md.get_md_job_forces(job.job_id))
    assert d["anchors"]["applied"] is False


def test_get_forces_locks_editing_once_the_run_owns_its_confs(tmp_path, monkeypatch):
    import asyncio
    routes_md = _routes(tmp_path, monkeypatch)
    job, _design, _pkg = _prepared_job(tmp_path, status="completed")
    d = asyncio.run(routes_md.get_md_job_forces(job.job_id))
    assert d["editable"] is False and d["status"] == "completed"


def test_per_anchor_atoms_round_trip_through_the_forces_route(tmp_path, monkeypatch):
    """Each anchor carries its own atom list, and it survives the round-trip verbatim —
    that manifest echo is what lets the card repopulate a per-row choice when you select
    a job.  Before this, the atoms select was write-only."""
    import asyncio
    routes_md = _routes(tmp_path, monkeypatch)
    job, design, pkg = _prepared_job(tmp_path)
    a0 = {"kind": "strand", "id": design.strands[0].id, "atoms": ["C1'"]}
    a1 = {"kind": "strand", "id": design.strands[1].id, "atoms": ["P"]}

    r = asyncio.run(routes_md.set_md_job_forces(
        job.job_id, routes_md.JobForcesRequest(anchors=[a0, a1])))
    assert r["ok"] and r["anchors"]["n_atoms_fixed"] > 0

    got = asyncio.run(routes_md.get_md_job_forces(job.job_id))["anchors"]["requested"]
    assert [a.get("atoms") for a in got] == [["C1'"], ["P"]]

    # One atom per residue on the C1' side; the P side is one-per-residue MINUS the 5'
    # termini, which have no phosphorus. So the mixed run marks fewer atoms than an
    # all-heavy run over the same two strands, and more than either filter alone.
    marked = sum(1 for ln in (pkg / "restraints_anchors.pdb").read_text().splitlines()
                 if ln.startswith("ATOM") and float(ln[60:66]) > 0)
    assert marked == r["anchors"]["n_atoms_fixed"]


def test_a_per_anchor_atom_list_overrides_the_job_level_default(tmp_path, monkeypatch):
    """`anchor_atoms` is now only the DEFAULT for anchors that state no opinion."""
    import asyncio
    routes_md = _routes(tmp_path, monkeypatch)
    job, design, pkg = _prepared_job(tmp_path)

    asyncio.run(routes_md.set_md_job_forces(job.job_id, routes_md.JobForcesRequest(
        anchors=[{"kind": "strand", "id": design.strands[0].id, "atoms": None}],
        anchor_atoms=["C1'"])))

    names = {ln[12:16].strip() for ln in
             (pkg / "restraints_anchors.pdb").read_text().splitlines()
             if ln.startswith("ATOM") and float(ln[60:66]) > 0}
    assert names != {"C1'"}, "an explicit atoms:null must beat the job-level default"


def test_a_bad_per_anchor_atom_list_is_rejected_too(tmp_path, monkeypatch):
    import asyncio
    from fastapi import HTTPException
    routes_md = _routes(tmp_path, monkeypatch)
    job, design, _ = _prepared_job(tmp_path)
    with pytest.raises(HTTPException) as e:
        asyncio.run(routes_md.set_md_job_forces(job.job_id, routes_md.JobForcesRequest(
            anchors=[{"kind": "strand", "id": design.strands[0].id, "atoms": ["CA"]}])))
    assert e.value.status_code == 400
    assert "matched no heavy atom" in e.value.detail and "CA" in e.value.detail
