"""Deferred-prep DRAFT NAMD jobs ("Use as NAMD seed").

A draft records the seed source + provenance but DEFERS the expensive solvation so
the user can set advanced options first; the prep runs later on
POST /md/jobs/{id}/prepare ("Relax from oxDNA").  These pin that a draft persists
as its own state and that the local status-reconciler never disturbs it.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import backend.api.routes_md as routes_md
from backend.core.oxdna_job import OxdnaJob
from backend.core.md_job import MdJob, MdStatus, new_job
from backend.core.namd_runner import reconcile_job_status


def test_oxdna_seed_inherits_ordinary_and_surface_anchors_without_graphene(monkeypatch):
    ordinary = {"kind": "strand", "strandId": "s1"}
    surface = {"kind": "base", "strandId": "s2", "baseIndex": 4}
    monkeypatch.setattr(
        OxdnaJob, "load",
        lambda *_: SimpleNamespace(run_config={
            "anchors": [ordinary], "surface_anchors": [surface],
        }),
    )
    body = routes_md.CreateJobRequest(oxdna_job_id="ox1", anchors=None)

    inherited = routes_md._inherit_oxdna_seed_anchors(body)

    assert inherited.anchors == [ordinary, surface]
    assert inherited.surface_anchors is None


def test_oxdna_seed_keeps_surface_anchor_group_with_graphene(monkeypatch):
    surface = {"kind": "base", "strandId": "s2", "baseIndex": 4}
    monkeypatch.setattr(
        OxdnaJob, "load",
        lambda *_: SimpleNamespace(run_config={"surface_anchors": [surface]}),
    )
    body = routes_md.CreateJobRequest(
        oxdna_job_id="ox1", graphene_nanopore=True, surface_anchors=None,
    )

    inherited = routes_md._inherit_oxdna_seed_anchors(body)

    assert inherited.anchors is None
    assert inherited.surface_anchors == [surface]


def test_explicit_empty_anchor_list_opts_out_of_seed_inheritance(monkeypatch):
    surface = {"kind": "base", "strandId": "s2", "baseIndex": 4}
    monkeypatch.setattr(
        OxdnaJob, "load",
        lambda *_: SimpleNamespace(run_config={"surface_anchors": [surface]}),
    )
    body = routes_md.CreateJobRequest(oxdna_job_id="ox1", anchors=[])

    inherited = routes_md._inherit_oxdna_seed_anchors(body)

    assert inherited.anchors == []
    assert inherited.surface_anchors is None


def test_namd_hard_surface_atomistic_options_validate():
    body = routes_md.CreateJobRequest(
        graphene_nanopore=True,
        graphene_pore_diameter_nm=2.1,
        graphene_layers=3,
        graphene_layer_spacing_nm=0.34,
        graphene_atomistic_clearance_nm=0.35,
        graphene_water_clearance_nm=0.31,
        graphene_sheet_margin_nm=2.0,
    )
    assert body.graphene_layers == 3
    assert body.graphene_layer_spacing_nm == 0.34
    assert body.graphene_sheet_margin_nm == 2.0


def test_seed_anchor_harmonic_composition_keeps_anchor_constant(tmp_path):
    pkg = tmp_path
    pdb_lines = [
        "ATOM      1  P    DA A   1       0.000   0.000   0.000  1.00  1.00          P \n",
        "HETATM    2  C   GRP G   1       1.000   0.000   0.000  1.00  0.00          C GR00\n",
    ]
    (pkg / "demo.pdb").write_text("".join(pdb_lines))
    (pkg / "release.pdb").write_text("".join(pdb_lines))
    marker = [pdb_lines[0][:60] + "  0.00" + pdb_lines[0][66:],
              pdb_lines[1][:60] + "  1.00" + pdb_lines[1][66:]]
    (pkg / "anchors.pdb").write_text("".join(marker))
    (pkg / "stage.conf").write_text(
        "coordinates        demo.pdb\nconstraints on\nconsref release.pdb\n"
        "conskfile release.pdb\nconskcol B\nconstraintScaling 0.25\nrun 100\n"
    )
    (pkg / "manifest.json").write_text('{"files":{"anchors":"anchors.pdb"}}')

    routes_md._harmonicize_seed_anchors(
        pkg, name_stem="demo", force_constant=50.0, force_gpu_resident=True,
    )

    conf = (pkg / "stage.conf").read_text()
    combined = (pkg / "restraints_combined_stage.pdb").read_text().splitlines()
    assert "GPUresident        on" in conf
    assert "fixedAtoms" not in conf
    assert "constraintScaling  1" in conf
    assert float(combined[0][60:66]) == 0.25
    assert float(combined[1][60:66]) == 50.0


def test_draft_status_roundtrips(tmp_path):
    job = new_job(
        design_name="D",
        protocol="mgh_slow_release",
        name_stem="",
        package_subdir="",
        seed_oxdna_job_id="ox1",
    )
    job.status = MdStatus.draft
    job.prep_params = {"padding_nm": 1.2, "draft": True}
    job.save(tmp_path)

    loaded = MdJob.load(job.job_id, tmp_path)
    assert loaded.status == MdStatus.draft
    assert loaded.seed_oxdna_job_id == "ox1"
    assert loaded.package_subdir == ""  # no package built yet


def test_reconcile_leaves_draft_untouched(tmp_path):
    """The /proc reconciler only repairs stale RUNNING jobs — a draft is inert."""
    job = new_job(
        design_name="D",
        protocol="p",
        name_stem="",
        package_subdir="",
        seed_oxdna_job_id="ox1",
    )
    job.status = MdStatus.draft
    job.save(tmp_path)

    out = reconcile_job_status(job, tmp_path)
    assert out.status == MdStatus.draft


def test_spawn_draft_job_defers_prep(tmp_path, monkeypatch):
    """_spawn_draft_job creates a persisted draft (no solvation) that remembers its
    seed + default advanced params for later pre-fill."""
    monkeypatch.setattr(routes_md, "_workspace", lambda: tmp_path)
    monkeypatch.setattr(routes_md, "random_seed", lambda: 987654321)
    body = routes_md.CreateJobRequest(
        oxdna_job_id="ox1",
        draft=True,
        design_source_path="part.nadoc",
    )
    job = routes_md._spawn_draft_job(body, name="GT_corner_v2")

    assert job.status == MdStatus.draft
    assert job.seed_oxdna_job_id == "ox1"
    assert job.seed_mrdna_job_id is None
    assert job.design_name == "GT_corner_v2"
    assert job.namd_seed == 987654321
    assert job.prep_params["seed"] == 987654321
    assert job.prep_params["draft"] is True
    # Persisted to disk in the draft state, with no package.
    loaded = MdJob.load(job.job_id, tmp_path)
    assert loaded.status == MdStatus.draft
    assert loaded.package_subdir == ""


def test_copy_draft_preserves_settings_and_changes_only_seed(tmp_path, monkeypatch):
    monkeypatch.setattr(routes_md, "_workspace", lambda: tmp_path)
    monkeypatch.setattr(routes_md, "random_seed", lambda exclude=(): 246802468)
    body = routes_md.CreateJobRequest(
        oxdna_job_id="ox1", draft=True, seed=135791357,
        design_source_path="part.nadoc", protocol="mgh_slow_release",
        threads=7, devices="0,1", padding_nm=2.4, box_mode="bbox",
        salt_mode="custom", ion_conc_mM=125.0, mg_conc_mM=8.0,
        minimize_steps=7200, force_soft=True, fast=False,
        graphene_nanopore=True, graphene_only=False,
        graphene_pore_diameter_nm=2.6, graphene_layers=3,
        graphene_layer_spacing_nm=0.34,
        graphene_atomistic_clearance_nm=0.36,
        graphene_water_clearance_nm=0.29,
        graphene_sheet_margin_nm=2.2,
        surface_anchors=[{"kind": "surface", "id": "sheet-edge"}],
        execution_target="alpine", cluster_name="alpine", partition="aa100",
        slurm_resources={"nodes": 2, "tasks_per_node": 4},
    )
    source = routes_md._spawn_draft_job(body, name="D")

    result = asyncio.run(routes_md.copy_md_job(source.job_id))
    copied = MdJob.load(result["job"]["job_id"], tmp_path)

    assert copied.status == MdStatus.draft
    assert copied.job_id != source.job_id
    assert copied.namd_seed == result["seed"] == 246802468
    expected_params = {
        **source.prep_params,
        "seed": 246802468,
        "autostart": False,
        "draft": True,
    }
    assert copied.prep_params == expected_params
    for key in (
        "graphene_nanopore", "graphene_only", "graphene_pore_diameter_nm",
        "graphene_layers", "graphene_layer_spacing_nm",
        "graphene_atomistic_clearance_nm", "graphene_water_clearance_nm",
        "graphene_sheet_margin_nm", "surface_anchors",
    ):
        assert copied.prep_params[key] == source.prep_params[key]
    assert copied.prep_params_set == source.prep_params_set
    assert (
        copied.protocol,
        copied.threads,
        copied.devices,
        copied.execution_target,
        copied.cluster_name,
        copied.partition,
        copied.requested_resources,
        copied.seed_oxdna_job_id,
    ) == (
        source.protocol,
        source.threads,
        source.devices,
        source.execution_target,
        source.cluster_name,
        source.partition,
        source.requested_resources,
        source.seed_oxdna_job_id,
    )
    assert result["previous_seed"] == 135791357


def test_editing_a_draft_updates_the_same_record_without_preparing(tmp_path, monkeypatch):
    """Save changes is an update, never clone-and-delete or an implicit launch."""
    monkeypatch.setattr(routes_md, "_workspace", lambda: tmp_path)
    job = new_job(
        design_name="D", protocol="old", name_stem="", package_subdir="",
        seed_oxdna_job_id="ox1",
    )
    job.status = MdStatus.draft
    job.prep_params = {"protocol": "old", "draft": True}
    job.save(tmp_path)
    from backend.core import md_queue
    md_queue.enqueue(tmp_path, job.job_id)  # stale/manual entry must not survive an edit

    out = asyncio.run(routes_md.update_md_job_settings(job.job_id, {
        "protocol": "mgh_slow_release", "threads": 7, "draft": False,
    }))

    assert out["job_id"] == job.job_id
    saved = MdJob.load(job.job_id, tmp_path)
    assert saved.status == MdStatus.draft
    assert saved.threads == 7
    assert saved.protocol == "mgh_slow_release"
    assert [j.job_id for j in MdJob.list_jobs(tmp_path)] == [job.job_id]
    assert md_queue.load_queue(tmp_path) == []


def test_edit_cleanup_preserves_job_identity_but_removes_every_stale_artifact(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(routes_md, "_workspace", lambda: tmp_path)
    job = new_job(design_name="D", protocol="p", name_stem="s", package_subdir="package/x")
    job.status = MdStatus.queued
    job.save(tmp_path)
    job_dir = job.job_dir(tmp_path)
    (job_dir / "package" / "x" / "output").mkdir(parents=True)
    (job_dir / "package" / "x" / "output" / "old.dcd").write_text("stale")
    (job_dir / "prep_progress.json").write_text("old")

    routes_md._clear_editable_job_artifacts(job)

    assert (job_dir / "job.json").exists()
    assert [p.name for p in job_dir.iterdir()] == ["job.json"]
    assert MdJob.load(job.job_id, tmp_path).job_id == job.job_id


def test_edit_rejects_a_submitted_queued_job(tmp_path, monkeypatch):
    monkeypatch.setattr(routes_md, "_workspace", lambda: tmp_path)
    job = new_job(design_name="D", protocol="p", name_stem="s", package_subdir="p")
    job.status = MdStatus.queued
    job.slurm_job_id = "123"
    job.save(tmp_path)

    from fastapi import HTTPException

    try:
        asyncio.run(routes_md.update_md_job_settings(job.job_id, {"threads": 4}))
        assert False, "submitted job was editable"
    except HTTPException as exc:
        assert exc.status_code == 409


# ── Live-Display design resolution (2026-07-16) ──────────────────────────────
# The live "Display MD" WS must map a trajectory onto the RUN's OWN design, not
# whatever design is open in the editor — a mismatch scrambles the P-atom→(helix,bp)
# assignment into cross-structure streaks.  _md_run_design / md_display_design_for_job
# resolve the run's design WITHOUT the active-session fallback.


def _tiny_design_json(tmp_path, name="run_design"):
    """A minimal valid Design .nadoc on disk (via the demo design)."""
    from backend.api.routes import _demo_design

    d = _demo_design()
    d = d.model_copy(update={"metadata": d.metadata.model_copy(update={"name": name})})
    p = tmp_path / f"{name}.nadoc"
    p.write_text(d.model_dump_json())
    return p, d


def test_md_run_design_resolves_from_source_path(tmp_path, monkeypatch):
    monkeypatch.setattr(routes_md, "_workspace", lambda: tmp_path)
    _tiny_design_json(tmp_path, "run_design")
    job = new_job(
        design_name="run_design",
        protocol="p",
        name_stem="s",
        package_subdir="",
        design_source_path="run_design.nadoc",
    )
    job.save(tmp_path)
    # no design.json snapshot in the job dir → falls back to the recorded source .nadoc
    got = routes_md._md_run_design(job)
    assert got is not None
    assert got.metadata.name == "run_design"


def test_md_run_design_none_when_unresolvable(tmp_path, monkeypatch):
    monkeypatch.setattr(routes_md, "_workspace", lambda: tmp_path)
    job = new_job(
        design_name="d",
        protocol="p",
        name_stem="s",
        package_subdir="",
        design_source_path="missing.nadoc",
    )
    job.save(tmp_path)
    # neither snapshot nor a loadable source → None (NO active-session fallback)
    assert routes_md._md_run_design(job) is None


def test_md_display_design_for_job_returns_design_and_name(tmp_path, monkeypatch):
    monkeypatch.setattr(routes_md, "_workspace", lambda: tmp_path)
    _tiny_design_json(tmp_path, "run_design")
    job = new_job(
        design_name="run_design",
        protocol="p",
        name_stem="s",
        package_subdir="",
        design_source_path="run_design.nadoc",
    )
    job.save(tmp_path)
    design, name = routes_md.md_display_design_for_job(job.job_id)
    assert design is not None and design.metadata.name == "run_design"
    assert name == "run_design"


def test_md_display_design_for_job_unknown_id(tmp_path, monkeypatch):
    monkeypatch.setattr(routes_md, "_workspace", lambda: tmp_path)
    assert routes_md.md_display_design_for_job("nope") == (None, None)
