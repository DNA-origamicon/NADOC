from __future__ import annotations

from backend.core.models import Design, DesignMetadata
from backend.core.project_collaboration import ProjectLeaseStore
from backend.core.project_revisions import ProjectRevisionStore


def _project(tmp_path):
    design = Design(id="project-1", metadata=DesignMetadata(name="Part"))
    store = ProjectRevisionStore(tmp_path)
    revision = store.commit(
        design,
        loadout_id="main",
        loadout_name="Main",
        parent_revision_id=None,
        expected_head=None,
    )
    return store, revision


def test_lease_is_single_writer_and_owner_can_renew_and_release(tmp_path):
    _project(tmp_path)
    leases = ProjectLeaseStore(tmp_path)
    first = leases.acquire(
        "project-1", "main", server_id="server-a", client_id="browser-a"
    )
    blocked = leases.acquire(
        "project-1", "main", server_id="server-b", client_id="browser-b"
    )
    renewed = leases.acquire(
        "project-1", "main", server_id="server-a", client_id="browser-a"
    )

    assert first.status == "acquired"
    assert blocked.status == "read_only"
    assert blocked.owner_server_id == "server-a"
    assert renewed.status == "acquired"
    assert not leases.release(
        "project-1", "main", server_id="server-b", client_id="browser-b"
    )
    assert leases.release(
        "project-1", "main", server_id="server-a", client_id="browser-a"
    )


def test_force_takeover_changes_owner(tmp_path):
    _project(tmp_path)
    leases = ProjectLeaseStore(tmp_path)
    leases.acquire(
        "project-1", "main", server_id="server-a", client_id="browser-a"
    )
    taken = leases.acquire(
        "project-1",
        "main",
        server_id="server-b",
        client_id="browser-b",
        force=True,
    )
    assert taken.status == "acquired"
    current = leases.current("project-1", "main")
    assert current["owner_server_id"] == "server-b"
    assert current["forced"] is True


def test_busy_branch_can_auto_fork_with_conflict_free_name(tmp_path):
    store, root = _project(tmp_path)
    leases = ProjectLeaseStore(tmp_path)
    leases.acquire(
        "project-1", "main", server_id="server-a", client_id="browser-a"
    )
    forked = leases.acquire(
        "project-1",
        "main",
        server_id="server-b",
        client_id="browser-b",
        server_name="Laptop",
        auto_fork=True,
    )

    assert forked.status == "forked"
    assert forked.forked_from_loadout_id == "main"
    assert forked.loadout_id != "main"
    manifest = store.project_manifest("project-1")
    ref = manifest["refs"][forked.loadout_id]
    assert ref["name"].startswith("Main — Laptop — ")
    fork_revision = store.read_revision("project-1", ref["head_revision_id"])
    assert fork_revision.parent_revision_id == root.revision_id


def test_case_insensitive_branch_name_conflict_gets_deterministic_suffix(tmp_path):
    store, root = _project(tmp_path)
    design = store.load_design("project-1", root.revision_id)
    store.commit(
        design,
        loadout_id="other",
        loadout_name="main",
        parent_revision_id=root.revision_id,
        expected_head=None,
    )
    leases = ProjectLeaseStore(tmp_path)
    name = leases._unique_branch_name("project-1", "MAIN", "Desktop")
    assert name.startswith("MAIN — Desktop — ")
