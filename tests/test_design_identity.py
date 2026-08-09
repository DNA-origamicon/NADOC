from backend.core.design_identity import (
    prepare_workspace_save,
    reconcile_open_identity,
    relocate_identity,
)
from backend.core.models import Design
from backend.core.job_cleanup import (
    reassign_job_snapshot_identity,
    remap_design_source_paths,
)
from backend.core.md_job import new_job as new_md_job
from backend.core.oxdna_job import new_oxdna_job


def test_legacy_file_claims_path_without_changing_id(tmp_path):
    design = Design(id="legacy")
    resolved, disposition, previous = reconcile_open_identity(
        design, "parts/a.nadoc", tmp_path
    )
    assert (resolved.id, disposition, previous) == ("legacy", "claimed", None)
    assert resolved.metadata.identity_last_known_path == "parts/a.nadoc"


def test_external_move_retains_id_when_old_location_is_gone(tmp_path):
    design, _, _ = reconcile_open_identity(Design(id="stable"), "old.nadoc", tmp_path)
    moved, disposition, previous = reconcile_open_identity(
        design, "folder/new.nadoc", tmp_path
    )
    assert (moved.id, disposition, previous) == ("stable", "move", "old.nadoc")


def test_external_copy_gets_new_id_when_original_still_exists(tmp_path):
    (tmp_path / "original.nadoc").write_text("present")
    design, _, _ = reconcile_open_identity(
        Design(id="original"), "original.nadoc", tmp_path
    )
    copied, disposition, previous = reconcile_open_identity(
        design, "copy.nadoc", tmp_path
    )
    assert copied.id != "original"
    assert (disposition, previous) == ("copy", "original.nadoc")


def test_save_as_forks_but_in_place_save_does_not():
    claimed, _, _ = prepare_workspace_save(Design(id="d"), "a.nadoc")
    same, disposition, _ = prepare_workspace_save(claimed, "a.nadoc")
    fork, fork_disposition, _ = prepare_workspace_save(claimed, "b.nadoc")
    assert same.id == "d" and disposition == "confirmed"
    assert fork.id != "d" and fork_disposition == "save_as"


def test_managed_relocation_retains_id_and_updates_signoff():
    claimed, _, _ = prepare_workspace_save(Design(id="d"), "a.nadoc")
    moved = relocate_identity(claimed, "a.nadoc", "sub/a.nadoc")
    assert moved.id == "d"
    assert moved.metadata.identity_last_known_path == "sub/a.nadoc"


def test_move_remaps_existing_job_provenance(tmp_path):
    md = new_md_job("d", "equilibrium_aware", "", "", design_source_path="a.nadoc")
    ox = new_oxdna_job("d", [], design_source_path="a.nadoc")
    md.save(tmp_path)
    ox.save(tmp_path)

    assert remap_design_source_paths(tmp_path, "a.nadoc", "parts/a.nadoc") == 2
    from backend.core.md_job import MdJob
    from backend.core.oxdna_job import OxdnaJob

    assert MdJob.load(md.job_id, tmp_path).design_source_path == "parts/a.nadoc"
    assert OxdnaJob.load(ox.job_id, tmp_path).design_source_path == "parts/a.nadoc"


def test_copy_rekeys_associated_frozen_snapshot_without_changing_history(tmp_path):
    snapshot = Design(id="shared")
    snapshot.metadata.name = "snapshot-content-must-survive"
    job = new_oxdna_job("d", [], design_source_path="copy.nadoc")
    job.save(tmp_path)
    snap_path = job.job_dir(tmp_path) / "design.json"
    snap_path.write_text(snapshot.to_json())

    assert reassign_job_snapshot_identity(
        tmp_path, "copy.nadoc", "shared", "independent"
    ) == 1
    migrated = Design.from_json(snap_path.read_text())
    assert migrated.id == "independent"
    assert migrated.model_dump(exclude={"id"}) == snapshot.model_dump(exclude={"id"})
