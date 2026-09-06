from __future__ import annotations

import json
import threading

import pytest

from backend.core.design_loadouts import encode_snapshot
from backend.core.models import Design, DesignLoadout, DesignMetadata
from backend.core.project_revisions import (
    BranchConflict,
    ProjectRevisionStore,
    RevisionCompatibilityError,
    refresh_active_revision,
    record_simulation_revision,
    migrate_job_revision_provenance,
)


def _design(project_id: str = "project-1") -> Design:
    design = Design(id=project_id, metadata=DesignMetadata(name="Part"))
    payload, size = encode_snapshot(design)
    return design.model_copy(
        update={
            "loadouts": [
                DesignLoadout(
                    id="main",
                    name="Main",
                    design_snapshot_gz_b64=payload,
                    snapshot_size_bytes=size,
                )
            ],
            "active_loadout_id": "main",
            "last_editable_loadout_id": "main",
        }
    )


def test_refresh_promotes_legacy_implicit_timeline_to_main_branch(tmp_path):
    legacy = Design(id="voltron", metadata=DesignMetadata(name="VoltronCoreArm"))
    refreshed = refresh_active_revision(tmp_path, legacy)

    assert refreshed.active_loadout_id == "main"
    assert [item.id for item in refreshed.loadouts] == ["main"]
    assert refreshed.loadouts[0].head_revision_id
    assert ProjectRevisionStore(tmp_path).branch_head("voltron", "main") == (
        refreshed.loadouts[0].head_revision_id
    )


def test_revision_object_is_content_addressed_and_round_trips(tmp_path):
    store = ProjectRevisionStore(tmp_path)
    design = _design()
    rev = store.commit(
        design,
        loadout_id="main",
        loadout_name="Main",
        parent_revision_id=None,
        expected_head=None,
    )

    assert len(rev.revision_id) == 64
    assert store.branch_head(design.id, "main") == rev.revision_id
    restored = store.load_design(design.id, rev.revision_id)
    assert restored.id == design.id
    assert restored.metadata.name == "Part"
    assert restored.loadouts == []
    record = json.loads(store.object_path(design.id, rev.revision_id).read_text())
    assert record["parent_revision_id"] is None
    assert record["snapshot_sha256"] == rev.snapshot_sha256


def test_branch_compare_and_swap_preserves_competing_head(tmp_path):
    store = ProjectRevisionStore(tmp_path)
    design = _design()
    first = store.commit(
        design,
        loadout_id="main",
        loadout_name="Main",
        parent_revision_id=None,
        expected_head=None,
    )

    with pytest.raises(BranchConflict) as caught:
        store.commit(
            design,
            loadout_id="main",
            loadout_name="Main",
            parent_revision_id=None,
            expected_head=None,
        )
    assert caught.value.current == first.revision_id
    assert store.branch_head(design.id, "main") == first.revision_id


def test_legacy_embedded_loadout_migrates_idempotently(tmp_path):
    design = _design()
    migrated = ProjectRevisionStore(tmp_path).materialize_loadouts(design)
    head = migrated.loadouts[0].head_revision_id
    assert head

    again = ProjectRevisionStore(tmp_path).materialize_loadouts(migrated)
    assert again.loadouts[0].head_revision_id == head
    assert len(list((tmp_path / ".nadoc-projects" / design.id / "objects").iterdir())) == 1


def test_stale_embedded_branch_pointer_is_divergence(tmp_path):
    store = ProjectRevisionStore(tmp_path)
    migrated = store.materialize_loadouts(_design())
    stale = migrated.model_copy(
        update={
            "loadouts": [
                migrated.loadouts[0].model_copy(update={"head_revision_id": "0" * 64})
            ]
        }
    )
    with pytest.raises(BranchConflict):
        store.materialize_loadouts(stale)


def test_refresh_active_revision_advances_history_and_updates_embedded_fallback(tmp_path):
    migrated = ProjectRevisionStore(tmp_path).materialize_loadouts(_design())
    old_head = migrated.loadouts[0].head_revision_id
    changed = migrated.model_copy(
        update={"metadata": migrated.metadata.model_copy(update={"name": "Changed"})}
    )
    refreshed = refresh_active_revision(tmp_path, changed)
    active = refreshed.loadouts[0]
    assert active.head_revision_id != old_head
    record = json.loads(
        ProjectRevisionStore(tmp_path)
        .object_path(refreshed.id, active.head_revision_id)
        .read_text()
    )
    assert record["parent_revision_id"] == old_head
    assert ProjectRevisionStore(tmp_path).load_design(
        refreshed.id, active.head_revision_id
    ).metadata.name == "Changed"


def test_refresh_identical_autosave_is_idempotent(tmp_path):
    first = refresh_active_revision(tmp_path, _design())
    head = first.loadouts[0].head_revision_id
    again = refresh_active_revision(tmp_path, first)

    assert again.loadouts[0].head_revision_id == head
    objects = tmp_path / ".nadoc-projects" / first.id / "objects"
    assert len(list(objects.iterdir())) == 1


def test_overlapping_identical_autosave_adopts_winning_head(tmp_path):
    """A second save holding the pre-save embedded head must not report divergence."""
    baseline = ProjectRevisionStore(tmp_path).materialize_loadouts(_design())
    changed = baseline.model_copy(
        update={"metadata": baseline.metadata.model_copy(update={"name": "NP_test edited"})}
    )
    winner = refresh_active_revision(tmp_path, changed)
    loser_retry = refresh_active_revision(tmp_path, changed)

    assert loser_retry.loadouts[0].head_revision_id == winner.loadouts[0].head_revision_id
    assert ProjectRevisionStore(tmp_path).load_design(
        winner.id, winner.loadouts[0].head_revision_id
    ).metadata.name == "NP_test edited"


def test_simulation_revision_is_protected_exact_and_idempotent(tmp_path):
    design = _design()
    first = record_simulation_revision(tmp_path, design, "oxdna", "job-1")
    second = record_simulation_revision(tmp_path, design, "oxdna", "job-1")
    other = record_simulation_revision(tmp_path, design, "oxdna", "job-2")

    assert first == second
    assert first.protected is True
    assert first.revision_id != other.revision_id
    assert ProjectRevisionStore(tmp_path).load_design(
        design.id, first.revision_id
    ).id == design.id
    snapshots = list(
        (tmp_path / ".nadoc-projects" / design.id / "snapshots").iterdir()
    )
    assert len(snapshots) == 1  # both job tags share one immutable design blob


def test_all_simulation_job_models_round_trip_project_revision_provenance(tmp_path):
    from backend.core.blade_job import BladeJob, new_blade_job
    from backend.core.cando_job import CandoJob, new_cando_job
    from backend.core.lammps_job import LammpsJob, new_lammps_job
    from backend.core.md_job import MdJob, new_job
    from backend.core.mrdna_job import MrdnaJob, new_mrdna_job
    from backend.core.oxdna_job import OxdnaJob, new_oxdna_job
    from backend.core.snupi_job import SnupiJob, new_snupi_job

    provenance = {"project_id": "project-1", "design_revision_id": "a" * 64}
    jobs = [
        (
            new_job(
                "part",
                "min_equil",
                "part",
                "package",
                **provenance,
            ),
            MdJob,
        ),
        (new_oxdna_job("part", [], **provenance), OxdnaJob),
        (new_mrdna_job("part", **provenance), MrdnaJob),
        (new_snupi_job("part", **provenance), SnupiJob),
        (new_lammps_job("part", **provenance), LammpsJob),
        (new_cando_job("part", **provenance), CandoJob),
        (new_blade_job("part", **provenance), BladeJob),
    ]
    for job, cls in jobs:
        job.save(tmp_path)
        restored = cls.load(job.job_id, tmp_path)
        assert restored.project_id == "project-1"
        assert restored.design_revision_id == "a" * 64


def test_legacy_job_provenance_migrates_from_frozen_snapshot(tmp_path):
    from backend.core.oxdna_job import OxdnaJob, new_oxdna_job

    source = _design("stable-project")
    (tmp_path / "part.nadoc").write_text(source.to_json())
    legacy_snapshot = source.model_copy(update={"id": "legacy-copy-id"})
    job = new_oxdna_job("part", [], design_source_path="part.nadoc")
    job.save(tmp_path)
    (job.job_dir(tmp_path) / "design.json").write_text(legacy_snapshot.to_json())

    result = migrate_job_revision_provenance(tmp_path, "part.nadoc")
    restored = OxdnaJob.load(job.job_id, tmp_path)
    assert result["migrated"] == 1
    assert restored.project_id == "stable-project"
    assert restored.design_revision_id
    frozen = ProjectRevisionStore(tmp_path).load_design(
        restored.project_id, restored.design_revision_id
    )
    assert frozen.id == "stable-project"


def test_peer_ingest_validates_blob_object_and_fast_forwards(tmp_path):
    source = ProjectRevisionStore(tmp_path / "source")
    design = _design()
    revision = source.commit(
        design,
        loadout_id="main",
        loadout_name="Main",
        parent_revision_id=None,
        expected_head=None,
    )
    manifest = source.project_manifest(design.id)
    assert manifest["refs"]["main"]["head_revision_id"] == revision.revision_id

    target = ProjectRevisionStore(tmp_path / "target")
    target.ingest_snapshot(
        design.id,
        revision.snapshot_sha256,
        source.snapshot_path(design.id, revision.snapshot_sha256).read_bytes(),
    )
    ingested = target.ingest_revision(
        source.export_revision(design.id, revision.revision_id)
    )
    target.advance_branch(
        design.id,
        "main",
        ingested.revision_id,
        expected_head=None,
        name="Main",
        require_fast_forward=True,
    )
    assert target.branch_head(design.id, "main") == revision.revision_id
    assert target.load_design(design.id, revision.revision_id).id == design.id


def test_peer_ingest_rejects_tampering_and_unknown_schema(tmp_path):
    source = ProjectRevisionStore(tmp_path / "source")
    revision = source.commit(
        _design(),
        loadout_id="main",
        loadout_name="Main",
        parent_revision_id=None,
        expected_head=None,
    )
    record = source.export_revision("project-1", revision.revision_id)
    target = ProjectRevisionStore(tmp_path / "target")
    with pytest.raises(ValueError, match="checksum"):
        target.ingest_snapshot("project-1", revision.snapshot_sha256, b"not-gzip")
    target.ingest_snapshot(
        "project-1",
        revision.snapshot_sha256,
        source.snapshot_path("project-1", revision.snapshot_sha256).read_bytes(),
    )
    tampered = {**record, "snapshot_sha256": "0" * 64}
    with pytest.raises(ValueError, match="identity checksum"):
        target.ingest_revision(tampered)
    with pytest.raises(RevisionCompatibilityError):
        target.ingest_revision({**record, "schema_version": 999})


def test_revision_relation_classifies_ahead_behind_and_diverged(tmp_path):
    store = ProjectRevisionStore(tmp_path)
    design = _design()
    root = store.commit(
        design,
        loadout_id="main",
        loadout_name="Main",
        parent_revision_id=None,
        expected_head=None,
    )
    second = store.commit(
        design.model_copy(
            update={"metadata": design.metadata.model_copy(update={"name": "Second"})}
        ),
        loadout_id="main",
        loadout_name="Main",
        parent_revision_id=root.revision_id,
        expected_head=root.revision_id,
    )
    assert store.relation(design.id, root.revision_id, second.revision_id) == "behind"
    assert store.relation(design.id, second.revision_id, root.revision_id) == "ahead"

    branch = store.commit(
        design.model_copy(
            update={"metadata": design.metadata.model_copy(update={"name": "Branch"})}
        ),
        loadout_id="other",
        loadout_name="Other",
        parent_revision_id=root.revision_id,
        expected_head=None,
    )
    assert store.relation(design.id, second.revision_id, branch.revision_id) == "diverged"


def test_cross_process_style_cas_allows_only_one_competing_writer(tmp_path):
    store = ProjectRevisionStore(tmp_path)
    design = _design()
    root = store.commit(
        design,
        loadout_id="main",
        loadout_name="Main",
        parent_revision_id=None,
        expected_head=None,
    )
    barrier = threading.Barrier(2)
    results: list[str] = []

    def writer(name: str) -> None:
        candidate = design.model_copy(
            update={"metadata": design.metadata.model_copy(update={"name": name})}
        )
        barrier.wait()
        try:
            store.commit(
                candidate,
                loadout_id="main",
                loadout_name="Main",
                parent_revision_id=root.revision_id,
                expected_head=root.revision_id,
            )
            results.append("won")
        except BranchConflict:
            results.append("conflict")

    threads = [threading.Thread(target=writer, args=(name,)) for name in ("A", "B")]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert sorted(results) == ["conflict", "won"]


def test_revision_history_and_comparison_report_lineage_and_deltas(tmp_path):
    store = ProjectRevisionStore(tmp_path)
    design = _design()
    root = store.commit(
        design,
        loadout_id="main",
        loadout_name="Main",
        parent_revision_id=None,
        expected_head=None,
    )
    changed_design = design.model_copy(
        update={"metadata": design.metadata.model_copy(update={"name": "Changed"})}
    )
    changed = store.commit(
        changed_design,
        loadout_id="main",
        loadout_name="Main",
        parent_revision_id=root.revision_id,
        expected_head=root.revision_id,
    )
    history = store.revision_history(design.id, changed.revision_id)
    assert [item["revision_id"] for item in history] == [
        changed.revision_id,
        root.revision_id,
    ]
    comparison = store.compare_revisions(
        design.id, root.revision_id, changed.revision_id
    )
    assert comparison["identical"] is False
    assert comparison["left"]["name"] == "Part"
    assert comparison["right"]["name"] == "Changed"
    assert all(value == 0 for value in comparison["delta"].values())


def test_promotion_preserves_displaced_head_as_recoverable_version(tmp_path):
    store = ProjectRevisionStore(tmp_path)
    design = _design()
    root = store.commit(
        design,
        loadout_id="main",
        loadout_name="Main",
        parent_revision_id=None,
        expected_head=None,
    )
    branch = store.commit(
        design.model_copy(
            update={"metadata": design.metadata.model_copy(update={"name": "Candidate"})}
        ),
        loadout_id="candidate",
        loadout_name="Candidate",
        parent_revision_id=root.revision_id,
        expected_head=None,
    )
    result = store.promote_branch(
        design.id,
        "candidate",
        "main",
        expected_target_head=root.revision_id,
        recovery_name="Main before candidate",
    )
    assert store.branch_head(design.id, "main") == branch.revision_id
    recovery = result["recovery_version"]
    assert recovery["kind"] == "version"
    assert recovery["name"] == "Main before candidate"
    assert recovery["head_revision_id"] == root.revision_id
    assert store.branch_head(design.id, recovery["loadout_id"]) == root.revision_id


def test_stale_promotion_is_rejected_without_extra_recovery_version(tmp_path):
    store = ProjectRevisionStore(tmp_path)
    design = _design()
    root = store.commit(
        design,
        loadout_id="main",
        loadout_name="Main",
        parent_revision_id=None,
        expected_head=None,
    )
    candidate = store.commit(
        design,
        loadout_id="candidate",
        loadout_name="Candidate",
        parent_revision_id=root.revision_id,
        expected_head=None,
    )
    before = set(store.project_manifest(design.id)["refs"])
    with pytest.raises(BranchConflict):
        store.promote_branch(
            design.id,
            "candidate",
            "main",
            expected_target_head="0" * 64,
        )
    assert store.branch_head(design.id, "main") == root.revision_id
    assert store.branch_head(design.id, "candidate") == candidate.revision_id
    assert set(store.project_manifest(design.id)["refs"]) == before


def test_overlapping_topology_autosave_adopts_identical_winning_head(tmp_path):
    from backend.api.routes import _demo_design
    from backend.core.lattice import _ligate

    baseline = refresh_active_revision(tmp_path, _demo_design())
    changed = _ligate(baseline, baseline.strands[0], baseline.strands[1])
    winner = refresh_active_revision(tmp_path, changed)
    repeated = refresh_active_revision(tmp_path, changed)

    assert repeated.loadouts[0].head_revision_id == winner.loadouts[0].head_revision_id
    assert len(ProjectRevisionStore(tmp_path).load_design(
        winner.id, winner.loadouts[0].head_revision_id
    ).strands) == len(changed.strands)


def test_overlapping_different_topology_autosave_preserves_conflict(tmp_path):
    from backend.api.routes import _demo_design
    from backend.core.lattice import _ligate

    baseline = refresh_active_revision(tmp_path, _demo_design())
    winner = refresh_active_revision(
        tmp_path, _ligate(baseline, baseline.strands[0], baseline.strands[1])
    )
    competing = _ligate(baseline, baseline.strands[1], baseline.strands[0])
    with pytest.raises(BranchConflict):
        refresh_active_revision(tmp_path, competing)
    assert ProjectRevisionStore(tmp_path).branch_head(winner.id, winner.active_loadout_id) == winner.loadouts[0].head_revision_id


@pytest.mark.parametrize("identical", [True, False])
def test_topology_autosave_commit_race(monkeypatch, tmp_path, identical):
    from backend.api.routes import _demo_design
    from backend.core.lattice import _ligate

    baseline = refresh_active_revision(tmp_path, _demo_design())
    changed = _ligate(baseline, baseline.strands[0], baseline.strands[1])
    competing = changed if identical else _ligate(baseline, baseline.strands[1], baseline.strands[0])
    commit = ProjectRevisionStore.commit
    winners = []

    def interleaved_commit(store, design, **kwargs):
        if not winners:
            winners.append(commit(store, competing, **kwargs))
        return commit(store, design, **kwargs)

    monkeypatch.setattr(ProjectRevisionStore, "commit", interleaved_commit)
    if identical:
        saved = refresh_active_revision(tmp_path, changed)
        assert saved.loadouts[0].head_revision_id == winners[0].revision_id
    else:
        with pytest.raises(BranchConflict):
            refresh_active_revision(tmp_path, changed)
    assert ProjectRevisionStore(tmp_path).branch_head(baseline.id, "main") == winners[0].revision_id
