"""Tests first: private finite Apply/reapply routes over native input history.

Small real topology/geometry and recording execute in isolated in-memory
documents. No application lifespan, workers, simulation or file output runs.
"""

from importlib import import_module
from types import SimpleNamespace
from uuid import uuid4

from fastapi import HTTPException
import pytest

from backend.api import doc_context, routes_connection_versions as routes, state
from backend.core.models import Design, DesignLoadout, OverhangConnection
from backend.core.part_repair_draft import RepairDraft
from tests.test_part_connection_application_commands import (
    ACTION, _pending, application_prefix as application_prefix,
)
from tests.test_part_pending_connection_versions import (
    authored, native_prefix as native_prefix, proof,
)


def commands():
    return import_module("backend.api.part_connection_application_commands")


def forbidden(*_args, **_kwargs):
    pytest.fail("Owned Apply reached forbidden fallback or whole-design work")


def draft(design):
    return RepairDraft.model_validate({"version": 1, "draft_id": "retained-proposal",
        "generation": 2, "base_design_id": design.id, "repair_version": 1,
        "base": {"version": 1, "root_sha256": "a" * 64,
            "commands_sha256": "b" * 64, "sources_sha256": "c" * 64},
        "actions": [{"action": "set_input", "feature_id": "bundle",
            "parameter_path": ["length_bp"], "expected_old": 42, "value": 49}]})


@pytest.fixture
def document(application_prefix, monkeypatch):
    source = _pending(application_prefix.model_copy(deep=True))
    source.repair_draft = draft(source)
    session = state._DesignSession(design=source, revision=7)
    identity = f"__finite_apply_route__{uuid4()}"
    token = doc_context.set_current_doc(identity)
    previous_revision = doc_context.current_request_revision()
    previous_entry = doc_context.current_request_feature_log_entry_id()
    responses = []
    respond = routes._design_response_with_geometry

    def observed_response(updated, report, *args, **kwargs):
        result = respond(updated, report, *args, **kwargs)
        responses.append((updated, kwargs, result))
        return result

    monkeypatch.setattr(routes, "OWNED_FINITE_CONNECTION_APPLY_ENABLED", True, raising=False)
    monkeypatch.setattr(routes, "_design_response_with_geometry", observed_response)
    try:
        with state._lock:
            state._sessions[identity] = session
        doc_context.set_request_revision(None)
        doc_context.set_request_feature_log_entry_id(None)
        yield SimpleNamespace(source=source, session=session, responses=responses)
    finally:
        try:
            state.drop_doc(identity)
        finally:
            doc_context.reset_current_doc(token)
            doc_context.set_request_revision(previous_revision)
            doc_context.set_request_feature_log_entry_id(previous_entry)


def signature(session):
    return (session.design.model_dump_json(), session.revision,
        [item.model_dump_json() for item in session.history],
        [item.model_dump_json() for item in session.redo],
        doc_context.current_request_revision(), doc_context.current_request_feature_log_entry_id())


def assert_full_linker_response(result, connection_id):
    assert result.get("partial_geometry") is not True
    assert "changed_helix_ids" not in result
    design, nucleotides = result["design"], result["nucleotides"]
    identity = f"__lnk__{connection_id}"
    connection = next(row for row in design["overhang_connections"] if row["id"] == connection_id)
    virtual = next(row for row in design["helices"] if row["id"] == identity)
    assert virtual["length_bp"] == connection["length_value"]
    suffixes = ("s",) if connection["linker_type"] == "ss" else ("a", "b")
    owned_ids = {f"{identity}__{suffix}" for suffix in suffixes}
    strands = [row for row in design["strands"] if row["id"] in owned_ids]
    assert {row["id"] for row in strands} == owned_ids
    for strand in strands:
        bridges = [domain for domain in strand["domains"] if domain["helix_id"] == identity]
        assert len(bridges) == 1
        assert sorted((bridges[0]["start_bp"], bridges[0]["end_bp"])) == [0, virtual["length_bp"] - 1]
    complements = [(strand, domain) for strand in strands for domain in strand["domains"]
                   if domain["binds_overhang_id"] is not None]
    assert {domain["binds_overhang_id"] for _, domain in complements} == {
        connection["overhang_a_id"], connection["overhang_b_id"]}
    expected = {(strand["id"], domain["helix_id"], bp, domain["direction"])
                for strand, domain in complements
                for bp in range(min(domain["start_bp"], domain["end_bp"]),
                                max(domain["start_bp"], domain["end_bp"]) + 1)}
    actual = [row for row in nucleotides if row.get("strand_id") in owned_ids
              and row["helix_id"] != identity]
    assert {(row["strand_id"], row["helix_id"], row["bp_index"], row["direction"])
            for row in actual} == expected
    assert len(actual) == len(expected) and all(row["strand_type"] == "linker" for row in actual)

    # The full display pipeline emits ds bridge beads separately. ss bridge
    # beads are drawn by overhang_link_arcs from these complement anchors and
    # the recorded connection; neither type emits a regular virtual-axis stick.
    bridge = [row for row in nucleotides if row["helix_id"] == identity]
    if connection["linker_type"] == "ss":
        assert bridge == []
    else:
        assert len(bridge) == 2 * virtual["length_bp"]
        assert {row["bp_index"] for row in bridge} == set(range(virtual["length_bp"]))
        assert all(row["strand_id"] in owned_ids and row["strand_type"] == "linker" for row in bridge)
    assert {row["helix_id"] for row in result["helix_axes"]} == {
        row["id"] for row in design["helices"] if not row["id"].startswith("__lnk__")}


def test_owned_finite_apply_gate_is_disabled_by_default():
    # The document fixture deliberately enables this private branch.
    assert routes.OWNED_FINITE_CONNECTION_APPLY_ENABLED is False


@pytest.mark.parametrize("material", ["ss", "ds"])
def test_real_apply_reapply_records_inputs_once_and_replays_from_root(document, material):
    session = document.session
    prefix = document.source.copy_with(connection_versions=[], feature_log=document.source.feature_log[:-1])
    source = _pending(prefix, f"root-to-root-{material}dna-linker")
    # Rebuild the pending definition through its native command, rather than
    # changing a published definition without changing its matching history.
    assert len(prefix.feature_log) == 3
    session.design = source
    before = source.model_dump_json()
    revision, depth = session.revision, len(session.history)

    first_response = routes.apply_connection_version("candidate")
    first = session.design
    first_row = first.feature_log[-1]
    assert first_row.params.get("action") == ACTION, "Apply kept a non-replayable legacy receipt"
    first_id = first.overhang_connections[0].id
    assert first_row.params["connection_id"] == first_id
    assert first_row.params["connection_application_version"] == 1
    assert first_row.params["conflict_connection_ids"] == []
    assert first_row.params["conflict_version_ids"] == ["candidate"]
    assert first_row.params["overhang_a_id"] == source.connection_versions[0].overhang_a_id
    assert first_row.params["overhang_b_id"] == source.connection_versions[0].overhang_b_id
    assert len(first.feature_log) == len(source.feature_log) + 1
    assert session.revision == revision + 1 and len(session.history) == depth + 1
    assert source.model_dump_json() == before
    assert_full_linker_response(first_response, first_id)
    first_json = first.model_dump_json()

    second_response = routes.apply_connection_version("candidate")
    second = session.design
    second_id = second.overhang_connections[0].id
    assert second_id != first_id
    assert second.feature_log[-1].params["conflict_connection_ids"] == [first_id]
    assert second.feature_log[-1].params["connection_id"] == second_id
    assert second.feature_log[-2].params == first_row.params
    assert not any(row.id.startswith(f"__lnk__{first_id}") for row in [*second.helices, *second.strands])
    assert first.model_dump_json() == first_json
    assert session.revision == revision + 2 and len(session.history) == depth + 2
    assert second.repair_draft == source.repair_draft
    assert_full_linker_response(second_response, second_id)

    transported = Design.model_validate_json(second.model_dump_json())
    for row in transported.feature_log:
        row.design_snapshot_gz_b64 = "not a recovery input"
        row.post_state_gz_b64 = "not a saved output"
    result = proof(transported)
    assert result["status"] == "verified", result
    assert result["checked_commands"] == 6
    state.undo()
    assert authored(session.design) == authored(first)
    assert session.design.repair_draft == source.repair_draft
    state.redo()
    assert authored(session.design) == authored(second)
    assert session.design.overhang_connections[0].id == second_id
    assert session.design.repair_draft == source.repair_draft


def test_unrelated_manual_sequence_and_saved_draft_survive_application(document):
    source = document.source
    hosts = {row.helix_id for row in source.overhangs}
    unrelated = next(row for row in source.strands
        if row.id not in {item.strand_id for item in source.overhangs}
        and not any(domain.helix_id in hosts for domain in row.domains))
    unrelated.sequence = "TGCA"
    before = unrelated.model_dump_json()
    result = routes.apply_connection_version("candidate")
    current = document.session.design
    assert current.feature_log[-1].params.get("action") == ACTION
    assert current.find_strand(unrelated.id).model_dump_json() == before
    assert current.repair_draft == source.repair_draft
    assert result["repair_draft"]["draft_id"] == source.repair_draft.draft_id
    assert (result["repair_draft"]["status"], result["repair_draft"]["base_status"]) == ("pending", "unchecked")
    assert "repair_draft" not in result["design"]


def test_preparation_inventory_and_recording_work_are_not_duplicated(document, monkeypatch):
    adapter = commands()
    counts = {}

    def observe(owner, name):
        original = getattr(owner, name)
        counts[name] = 0

        def observed(*args, **kwargs):
            counts[name] += 1
            return original(*args, **kwargs)

        monkeypatch.setattr(owner, name, observed)

    for owner, names in ((adapter, ("_bounded_source", "identity_index", "_materialize")),
                         (state, ("_snapshot_copy", "encode_design_snapshot",
                                  "reconcile_cluster_membership", "_retry_pending_ligations", "validate_design"))):
        for name in names:
            observe(owner, name)
    monkeypatch.setattr(import_module("backend.api.part_proof_commands"), "execute", forbidden)
    routes.apply_connection_version("candidate")
    assert counts == {"_bounded_source": 1, "identity_index": 1, "_materialize": 1,
        "_snapshot_copy": 1, "encode_design_snapshot": 2, "reconcile_cluster_membership": 1,
        "_retry_pending_ligations": 1, "validate_design": 1}
    assert document.session.design.feature_log[-1].params["action"] == ACTION


@pytest.mark.parametrize("missing", ["version_id", "overhang_a_id", "overhang_b_id", "self_pair"])
def test_selected_input_errors_precede_snapshots_and_never_fall_back(document, monkeypatch, missing):
    source = document.source
    version = source.connection_versions[0]
    identity = "candidate"
    if missing == "version_id":
        identity = "missing-version"
        selected, kind, path, status = identity, "connection_version", "version_id", 404
    elif missing == "self_pair":
        version.overhang_b_id = version.overhang_a_id
        selected, kind, path, status = version.overhang_a_id, "overhang", "overhang_b_id", 422
    else:
        selected = getattr(version, missing)
        source.overhangs = [row for row in source.overhangs if row.id != selected]
        kind, path, status = "overhang", missing, 404
    before = signature(document.session)
    monkeypatch.setattr(routes, "_apply_connection_version_legacy", forbidden, raising=False)
    monkeypatch.setattr(commands(), "_materialize", forbidden)
    monkeypatch.setattr(state, "_snapshot_copy", forbidden)
    monkeypatch.setattr(state, "encode_design_snapshot", forbidden)
    with pytest.raises(HTTPException) as caught:
        routes.apply_connection_version(identity)
    assert caught.value.status_code == status
    assert caught.value.detail["code"] == ("missing_reference" if status == 404 else "invalid_selection")
    assert caught.value.detail["references"] == [{"kind": kind, "identity": selected, "parameter_path": [path]}]
    assert signature(document.session) == before
    assert document.responses == []


@pytest.mark.parametrize("failure", ["materialize", "post_encode", "validation", "publish", "cancel", "cpd"])
def test_admitted_failures_roll_back_recording_without_legacy_retry(document, monkeypatch, failure):
    session = document.session
    # Keep nonempty redo so the publication failure tests real restoration.
    session.redo.append(session.design.model_copy(deep=True))
    before = signature(session)
    monkeypatch.setattr(routes, "_apply_connection_version_legacy", forbidden, raising=False)

    def fail(*_args, **_kwargs):
        raise RuntimeError("Injected finite Apply failure")

    if failure == "materialize":
        monkeypatch.setattr(commands(), "_materialize", fail)
    elif failure in {"post_encode", "cancel"}:
        encode, calls = state.encode_design_snapshot, []

        def encode_or_fail(design):
            calls.append(design)
            if len(calls) == 2:
                if failure == "cancel":
                    raise KeyboardInterrupt("Cancelled finite Apply")
                fail()
            return encode(design)

        monkeypatch.setattr(state, "encode_design_snapshot", encode_or_fail)
    elif failure == "validation":
        monkeypatch.setattr(state, "validate_design", fail)
    elif failure == "publish":
        bump = state._bump_revision

        def bump_or_fail(current):
            bump(current)
            fail()

        monkeypatch.setattr(state, "_bump_revision", bump_or_fail)
    else:
        monkeypatch.setattr(import_module("backend.core.photoproducts"),
            "stale_photoproduct_ids", lambda *_args: ["formed-cpd"])
    expected = KeyboardInterrupt if failure == "cancel" else HTTPException if failure == "cpd" else RuntimeError
    with pytest.raises(expected):
        routes.apply_connection_version("candidate")
    assert signature(session) == before
    assert document.responses == []


@pytest.mark.parametrize("profile", ["disabled", "direct", "indirect", "combined", "outside_bound"])
def test_compatibility_dispatch_stays_explicit_and_never_claims_native_history(document, monkeypatch, profile):
    source = document.source
    if profile == "disabled":
        monkeypatch.setattr(routes, "OWNED_FINITE_CONNECTION_APPLY_ENABLED", False)
        monkeypatch.setattr(commands(), "try_record", forbidden, raising=False)
    elif profile == "direct":
        source.connection_versions[0].connection_type = "root-to-root"
    elif profile == "indirect":
        source.connection_versions[0].connection_type = "root-to-root-indirect"
    elif profile == "outside_bound":
        monkeypatch.setattr(commands(), "MAX_APPLICATION_BASES", 1)
    before = signature(document.session)
    calls, response = [], {"legacy_dispatch": True}

    def legacy(version_id, *, new_version=None):
        calls.append((version_id, new_version))
        return response

    monkeypatch.setattr(routes, "_apply_connection_version_legacy", legacy, raising=False)
    monkeypatch.setattr(commands(), "_materialize", forbidden)
    if profile == "combined":
        monkeypatch.setattr(commands(), "try_record", forbidden, raising=False)
        a, b = source.overhangs
        actual = routes.create_and_apply_connection_version(routes.ConnectionVersionCreateRequest(
            overhang_a_id=a.id, overhang_b_id=b.id,
            connection_type="root-to-root-ssdna-linker", bridge_length=7))
        assert len(calls) == 1 and calls[0][1] is not None
        assert calls[0][0] == calls[0][1].id
    else:
        actual = routes.apply_connection_version("candidate")
        assert calls == [("candidate", None)]
    assert actual is response
    assert signature(document.session) == before


def test_disabled_finite_legacy_still_uses_actual_full_geometry_response(document, monkeypatch):
    monkeypatch.setattr(routes, "OWNED_FINITE_CONNECTION_APPLY_ENABLED", False)
    monkeypatch.setattr(commands(), "try_record", forbidden, raising=False)
    response = routes.apply_connection_version("candidate")
    current = document.session.design
    assert current.feature_log[-1].params.get("action") != ACTION
    assert_full_linker_response(response, current.overhang_connections[0].id)
    assert len(document.responses) == 1 and document.responses[0][1] == {}


def forbid_source_preparation(monkeypatch):
    """Version-only refusal/classification must not reach whole-source work."""
    for name in ("_source_index", "_materialize", "uuid4"):
        monkeypatch.setattr(commands(), name, forbidden)
    monkeypatch.setattr(state, "_snapshot_copy", forbidden)
    monkeypatch.setattr(state, "encode_design_snapshot", forbidden)


@pytest.mark.parametrize("connection_type", [
    "root-to-root", "end-to-root", "root-to-root-indirect", "end-to-end-indirect",
])
def test_unsupported_version_type_precedes_source_inventory_even_with_duplicate_helix(
    document, monkeypatch, connection_type,
):
    source = document.source
    source.connection_versions[0].connection_type = connection_type
    source.helices.append(source.helices[0].model_copy(deep=True))
    before = signature(document.session)
    forbid_source_preparation(monkeypatch)
    calls, expected = [], {"legacy_dispatch": connection_type}

    def legacy(version_id, *, new_version=None):
        calls.append((version_id, new_version))
        return expected

    monkeypatch.setattr(routes, "_apply_connection_version_legacy", legacy)
    assert routes.apply_connection_version("candidate") is expected
    assert calls == [("candidate", None)]
    assert signature(document.session) == before
    assert document.responses == []


@pytest.mark.parametrize("duplicate_unrelated", [False, True])
def test_protected_finite_loadout_precedes_source_inventory_and_identity_allocation(
    document, monkeypatch, duplicate_unrelated,
):
    source = document.source
    source.loadouts = [DesignLoadout(id="simulation", name="Simulation", protected=True)]
    source.active_loadout_id = "simulation"
    if duplicate_unrelated:
        source.helices.append(source.helices[0].model_copy(deep=True))
    before = signature(document.session)
    forbid_source_preparation(monkeypatch)
    monkeypatch.setattr(routes, "_apply_connection_version_legacy", forbidden)
    with pytest.raises(HTTPException) as caught:
        routes.apply_connection_version("candidate")
    assert caught.value.status_code == 409
    assert caught.value.detail["code"] == "protected_simulation_loadout"
    assert signature(document.session) == before
    assert document.responses == []


@pytest.mark.parametrize("legacy_first", [False, True])
def test_duplicate_selected_version_is_ambiguous_before_type_fallback_or_source_walk(
    document, monkeypatch, legacy_first,
):
    source = document.source
    finite = source.connection_versions[0]
    direct = finite.model_copy(update={"connection_type": "root-to-root"})
    source.connection_versions = [direct, finite] if legacy_first else [finite, direct]
    before = signature(document.session)
    forbid_source_preparation(monkeypatch)
    monkeypatch.setattr(routes, "_apply_connection_version_legacy", forbidden)
    with pytest.raises(HTTPException) as caught:
        routes.apply_connection_version("candidate")
    assert caught.value.status_code == 422
    assert caught.value.detail["code"] == "invalid_selection"
    assert caught.value.detail["references"] == [{
        "kind": "connection_version", "identity": "candidate", "parameter_path": ["version_id"]}]
    assert signature(document.session) == before
    assert document.responses == []


def test_missing_selected_version_is_structured_before_source_inventory(document, monkeypatch):
    before = signature(document.session)
    forbid_source_preparation(monkeypatch)
    monkeypatch.setattr(routes, "_apply_connection_version_legacy", forbidden)
    with pytest.raises(HTTPException) as caught:
        routes.apply_connection_version("missing-version")
    assert caught.value.status_code == 404
    assert caught.value.detail["code"] == "missing_reference"
    assert caught.value.detail["references"] == [{
        "kind": "connection_version", "identity": "missing-version", "parameter_path": ["version_id"]}]
    assert signature(document.session) == before
    assert document.responses == []


def test_oversized_version_table_falls_back_before_inspecting_records(document, monkeypatch):
    source, session = document.source, document.session
    versions = source.connection_versions
    before = signature(session)

    class UninspectedVersion:
        @property
        def id(self):
            forbidden()

    # Real list length exceeds even the shared source-node ceiling. The single
    # repeated opaque object makes accidental record inspection observable;
    # no geometry, huge model graph or claimed caller size is involved.
    oversized = [UninspectedVersion()] * (commands().MAX_OPERATION_NODES + 1)
    forbid_source_preparation(monkeypatch)
    calls, expected = [], {"legacy_dispatch": "oversized-version-table"}

    def legacy(version_id, *, new_version=None):
        assert source.connection_versions is oversized
        calls.append((version_id, new_version))
        return expected

    monkeypatch.setattr(routes, "_apply_connection_version_legacy", legacy)
    try:
        source.connection_versions = oversized
        assert routes.apply_connection_version("candidate") is expected
        assert calls == [("candidate", None)]
        assert session.design is source and source.connection_versions is oversized
        assert document.responses == []
    finally:
        # Restore ordinary model storage even when the red expectation fails,
        # before the document fixture's own session/context cleanup runs.
        source.connection_versions = versions
    assert signature(session) == before


def test_existing_pending_identity_is_not_treated_as_provisional_output_on_reapply(document, monkeypatch):
    allocated = iter(("pending", "after-pending"))
    monkeypatch.setattr(commands(), "uuid4", lambda: next(allocated))
    monkeypatch.setattr(routes, "_apply_connection_version_legacy", forbidden)
    session = document.session
    original = signature(session)
    first_response = routes.apply_connection_version("candidate")
    first = session.design
    first_json = first.model_dump_json()
    assert first.feature_log[-1].params["connection_id"] == "pending"
    assert [row.id for row in first.overhang_connections] == ["pending"]
    assert_full_linker_response(first_response, "pending")

    second_response = routes.apply_connection_version("candidate")
    second = session.design
    assert second.feature_log[-1].params["connection_id"] == "after-pending"
    assert second.feature_log[-1].params["conflict_connection_ids"] == ["pending"]
    assert second.feature_log[-2].params["connection_id"] == "pending"
    assert [row.id for row in second.overhang_connections] == ["after-pending"]
    assert not any(row.id.startswith("__lnk__pending") for row in [*second.helices, *second.strands])
    assert first.model_dump_json() == first_json
    assert session.revision == original[1] + 2 and len(session.history) == len(original[2]) + 2
    assert_full_linker_response(second_response, "after-pending")
    assert next(allocated, None) is None  # Exactly one host identity per apply.


def test_allocated_existing_connection_identity_refuses_before_recording_on_reapply(document, monkeypatch):
    identity = "00000000-0000-0000-0000-000000000907"
    monkeypatch.setattr(commands(), "uuid4", lambda: identity)
    routes.apply_connection_version("candidate")
    session = document.session
    source = session.design
    before = signature(session)
    response_count = len(document.responses)
    assert source.feature_log[-1].params["connection_id"] == identity
    monkeypatch.setattr(commands(), "_materialize", forbidden)
    monkeypatch.setattr(state, "_snapshot_copy", forbidden)
    monkeypatch.setattr(state, "encode_design_snapshot", forbidden)
    monkeypatch.setattr(routes, "_apply_connection_version_legacy", forbidden)
    monkeypatch.setattr(routes, "_connection_apply_response", forbidden)

    with pytest.raises(HTTPException) as caught:
        routes.apply_connection_version("candidate")
    assert caught.value.status_code == 422
    assert caught.value.detail["code"] == "invalid_selection"
    references = caught.value.detail["references"]
    assert len(references) == 1 and references[0]["parameter_path"] == ["connection_id"]
    assert (references[0]["kind"], references[0]["identity"]) in {
        ("overhang_connection", identity), ("helix", f"__lnk__{identity}"),
        ("strand", f"__lnk__{identity}__s")}
    assert session.design is source and signature(session) == before
    assert len(document.responses) == response_count


@pytest.mark.parametrize("collection", ["connection_versions", "overhang_connections"])
def test_existing_conflict_set_over_native_limit_falls_back_before_command_parsing(
    document, monkeypatch, collection,
):
    source = document.source
    version = source.connection_versions[0]
    if collection == "connection_versions":
        rows = [version, *(version.model_copy(update={"id": f"alternative-{index}"})
                          for index in range(128))]
    else:
        rows = [OverhangConnection(id=f"connection-{index}",
            overhang_a_id=version.overhang_a_id, overhang_a_attach="root",
            overhang_b_id=version.overhang_b_id, overhang_b_attach="root",
            linker_type="ss", length_value=4, length_unit="bp")
            for index in range(129)]
    setattr(source, collection, rows)
    assert len(rows) == 129 and len({row.id for row in rows}) == 129
    # These are valid, modestly sized legacy records. A different source-work
    # refusal must not accidentally satisfy the conflict-contract regression.
    commands()._bounded_source(source)
    before = signature(document.session)
    for name in ("parse_command", "_materialize", "uuid4"):
        monkeypatch.setattr(commands(), name, forbidden)
    monkeypatch.setattr(state, "_snapshot_copy", forbidden)
    monkeypatch.setattr(state, "encode_design_snapshot", forbidden)
    calls, expected = [], {"legacy_dispatch": collection}

    def legacy(version_id, *, new_version=None):
        assert document.session.design is source and getattr(source, collection) is rows
        calls.append((version_id, new_version))
        return expected

    monkeypatch.setattr(routes, "_apply_connection_version_legacy", legacy)
    assert routes.apply_connection_version("candidate") is expected
    assert calls == [("candidate", None)]
    assert signature(document.session) == before
    assert document.responses == []
