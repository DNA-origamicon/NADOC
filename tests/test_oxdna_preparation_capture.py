"""Tests first: one owned source for local DNA preparation and its archive.

No geometry, solver, package writer or production lifespan runs here. The new
boundary is deliberately absent until this dossier's contract is reviewed.
An owned source is not a complete physical receipt or native feature proof.
"""

from copy import deepcopy
from contextlib import contextmanager
from importlib import import_module
from uuid import uuid4

from fastapi import HTTPException
import pytest

from backend.api import doc_context, state
from backend.core import models as m
from backend.core.part_command_errors import CommandContractError


def host():
    return import_module("backend.api.oxdna_preparation_capture")


def core():
    return import_module("backend.core.oxdna_preparation_inputs")


def options(**changes):
    # This is the exact subset used for scope classification, not a new public
    # simulation DTO, parameter generator or source of numerical defaults.
    return {
        "execution_target": "local", "interaction_type": "DNA2", "backend": "CPU",
        "engine_variant": "auto", "surface": None, "anchors": [],
        "surface_anchors": [], "surface_strands": None, "stage_overrides": {},
        **changes,
    }


def source():
    helix = m.Helix(id="h_XY_0_0", axis_start=m.Vec3(x=0, y=0, z=0),
        axis_end=m.Vec3(x=0, y=0, z=2.38), length_bp=8,
        loop_skips=[m.LoopSkip(bp_index=2, delta=1)])
    strand = m.Strand(id="dna", sequence="ACGTACGTA", domains=[m.Domain(
        helix_id=helix.id, start_bp=0, end_bp=7, direction=m.Direction.FORWARD)])
    return m.Design(id="legacy-dna", helices=[helix], strands=[strand],
        metadata=m.DesignMetadata(name="Unrooted legacy design", tags=["kept"]),
        annotations=[m.Annotation(text="Archive this", refs=[{"kind": "strand", "id": "dna", "notes": ["kept"]}])],
        visibility_state=m.VisibilityState(hidden_base_keys=["h_XY_0_0:0:forward"]),
        feature_log=[m.SnapshotLogEntry(id="old", op_kind="overhang-bulk", label="Legacy",
            params={"legacy": {"values": [1, 2]}},
            design_snapshot_gz_b64="opaque recovery, not a proof input",
            post_state_gz_b64="opaque later recovery")],
        feature_log_cursor=0)


@contextmanager
def _document_context(make_source=source):
    # A failing fixture constructor must never strand the request context in a
    # temporary document. Install cleanup before the first shared-state write.
    identity = f"__oxdna_capture__{uuid4()}"
    original = make_source()
    session = state._DesignSession(design=original, revision=7)
    token = doc_context.set_current_doc(identity)
    try:
        with state._lock:
            state._sessions[identity] = session
        yield identity, session, original
    finally:
        try:
            state.drop_doc(identity)
        finally:
            doc_context.reset_current_doc(token)


@pytest.fixture
def document():
    with _document_context() as value:
        yield value


def test_fixture_source_failure_preserves_prior_document_and_sessions():
    identity = doc_context.get_current_doc()
    with state._lock:
        sessions = dict(state._sessions)

    def rejected_source():
        raise ValueError("fixture source failed")

    with pytest.raises(ValueError, match="fixture source failed"):
        with _document_context(rejected_source):
            pytest.fail("A failed source must not install a fixture")
    assert doc_context.get_current_doc() == identity
    with state._lock:
        assert state._sessions == sessions


def test_fixture_body_failure_restores_prior_document_and_sessions():
    identity = doc_context.get_current_doc()
    with state._lock:
        sessions = dict(state._sessions)
    with pytest.raises(ValueError, match="fixture body failed"):
        with _document_context():
            raise ValueError("fixture body failed")
    assert doc_context.get_current_doc() == identity
    with state._lock:
        assert state._sessions == sessions


def test_fixture_cleanup_failure_still_restores_prior_document(monkeypatch):
    identity = doc_context.get_current_doc()
    installed = None

    def rejected_cleanup(_identity):
        raise ValueError("fixture cleanup failed")

    monkeypatch.setattr(state, "drop_doc", rejected_cleanup)
    try:
        with pytest.raises(ValueError, match="fixture cleanup failed"):
            with _document_context() as value:
                installed = value[0]
        assert doc_context.get_current_doc() == identity
    finally:
        if installed is not None:
            with state._lock:
                state._sessions.pop(installed, None)


def forbidden(*_args, **_kwargs):
    pytest.fail("Capture reached a forbidden builder, proof, I/O or source-copy path")


def test_full_archive_retains_legacy_history_and_every_declared_document_field():
    original = source()
    # An archive clone must not run a load validator or silently repair state.
    original.helices[0].grid_pos = None
    expected = original.model_dump(mode="json")
    owned = core().capture_archive(original)
    assert type(owned) is m.Design and owned is not original
    assert owned.model_dump(mode="json") == expected
    assert owned.recipe_root is None
    assert owned.feature_log[0].params == {"legacy": {"values": [1, 2]}}
    assert owned.feature_log[0].design_snapshot_gz_b64 == "opaque recovery, not a proof input"


def test_nested_authoring_history_and_presentation_aliases_are_independent():
    original = source()
    expected = original.model_dump(mode="json")
    owned = core().capture_archive(original)
    original.helices[0].axis_start.x += 100
    original.helices[0].loop_skips[0].delta = -1
    original.strands[0].domains[0].end_bp = 4
    original.metadata.tags.append("late")
    original.annotations[0].refs[0]["notes"].append("late")
    original.visibility_state.hidden_base_keys.append("late")
    original.feature_log[0].params["legacy"]["values"].append(3)
    assert owned.model_dump(mode="json") == expected
    owned.metadata.tags.append("private")
    assert "private" not in original.metadata.tags


@pytest.mark.parametrize("field", ["deformation", "cluster_domain_pose", "nucleotide_pose", "overhang_pose"])
def test_reviewed_dna_placement_inputs_are_preserved_without_recomputation(document, field):
    _identity, _session, original = document
    if field == "deformation":
        original.deformations = [m.DeformationOp(id="twist", type="twist", plane_a_bp=0,
            plane_b_bp=7, affected_helix_ids=[original.helices[0].id],
            params=m.TwistParams(total_degrees=5.0))]
    elif field == "cluster_domain_pose":
        original.cluster_transforms = [m.ClusterRigidTransform(id="cluster", helix_ids=[original.helices[0].id],
            domain_ids=[m.DomainRef(strand_id="dna", domain_index=0)], translation=[1., 2., 3.])]
    elif field == "nucleotide_pose":
        original.nucleotide_transforms = [m.NucleotideTransform(id="pose", kind="base",
            helix_id=original.helices[0].id, bp_index=2, direction=m.Direction.FORWARD,
            copy_k=1, translation=[1., 0., 0.])]
    else:
        original.strands[0].domains[0].overhang_id = "ordinary"
        original.overhangs = [m.OverhangSpec(id="ordinary", helix_id=original.helices[0].id,
            strand_id="dna", sequence="ACGTACGTA", translation=[1., 0., 0.])]
    expected = original.without_reference_geometry().model_dump(mode="json")
    captured = host().capture_current(options())
    assert captured.supported and captured.design.model_dump(mode="json") == expected


def test_reference_projection_runs_only_after_source_is_independently_owned(document, monkeypatch):
    _identity, _session, original = document
    original.helices.append(m.Helix(id="reference", axis_start=m.Vec3(x=3, y=0, z=0),
        axis_end=m.Vec3(x=3, y=0, z=2.38), length_bp=8))
    original.strands.append(m.Strand(id="backdrop", is_reference=True, sequence="ACGTACGT",
        domains=[m.Domain(helix_id="reference", start_bp=0, end_bp=7, direction=m.Direction.FORWARD)]))
    expected = original.without_reference_geometry().model_dump(mode="json")
    project = m.Design.without_reference_geometry

    def checked(value):
        assert value is not original
        assert value.helices[0] is not original.helices[0]
        assert value.feature_log[0].params is not original.feature_log[0].params
        return project(value)

    monkeypatch.setattr(m.Design, "without_reference_geometry", checked)
    captured = host().capture_current(options())
    assert captured.design.model_dump(mode="json") == expected
    assert len(original.strands) == 2 and len(captured.design.strands) == 1


def test_host_origin_is_bound_without_claiming_native_or_complete_physical_proof(document, monkeypatch):
    from backend.core import part_history_contract

    monkeypatch.setattr(part_history_contract, "assess_part_history", forbidden)
    identity, session, original = document
    captured = host().capture_current(options(), expected_revision=7)
    assert captured.supported
    assert (captured.doc_id, captured.design_id, captured.source_revision, captured.session_identity) == (
        identity, original.id, 7, session.identity)
    assert captured.coverage["status"] == "unknown" and captured.coverage["reasons"]
    assert not captured.coverage.get("native_editable", False)
    assert not captured.coverage.get("complete", False)
    assert captured.design is not original and captured.design.recipe_root is None
    host().require_current(captured)


@pytest.mark.parametrize("backend", ["CPU", "CUDA"])
def test_owned_capture_does_not_change_cpu_or_cuda_protocol_selection(document, backend):
    captured = host().capture_current(options(backend=backend))
    assert captured.supported
    assert captured.design.model_dump(mode="json") == document[2].model_dump(mode="json")


@pytest.mark.parametrize("change", ["revision", "source", "close", "close_reopen_aba"])
def test_stale_origin_fails_before_lineage_or_package_consumers(document, change):
    identity, session, original = document
    captured = host().capture_current(options())
    expected = captured.design.model_dump(mode="json")
    with state._lock:
        if change == "revision":
            session.revision += 1
        elif change == "source":
            session.design = original.model_copy(deep=True)
        else:
            state._sessions.pop(identity)
            if change == "close_reopen_aba":
                state._sessions[identity] = state._DesignSession(design=original, revision=7)
    with pytest.raises(HTTPException) as error:
        host().require_current(captured)
    assert error.value.status_code == 409
    assert captured.design.model_dump(mode="json") == expected
    if change == "close":
        assert identity not in state._sessions


def test_captured_input_cannot_be_rebound_by_switching_document_context(document):
    captured = host().capture_current(options())
    token = doc_context.set_current_doc(f"__other_oxdna__{uuid4()}")
    try:
        with pytest.raises(HTTPException) as error:
            host().require_current(captured)
        assert error.value.status_code == 409
    finally:
        doc_context.reset_current_doc(token)


def test_wrong_expected_revision_refuses_before_copy(document, monkeypatch):
    monkeypatch.setattr(core(), "capture_archive", forbidden)
    with pytest.raises(HTTPException) as error:
        host().capture_current(options(), expected_revision=8)
    assert error.value.status_code == 409
    assert document[1].design is document[2] and document[1].revision == 7


def test_absent_part_refuses_without_lazy_session_creation(document, monkeypatch):
    identity, _session, _original = document
    state.drop_doc(identity)
    monkeypatch.setattr(state, "_session", forbidden)
    with pytest.raises(HTTPException) as error:
        host().capture_current(options())
    assert error.value.status_code == 404 and identity not in state._sessions


@pytest.mark.parametrize("field,value", [
    ("interaction_type", "DNA"), ("execution_target", "alpine"),
    ("execution_target", "runpod"), ("engine_variant", "dnanm"),
    ("surface", {"stiff": 1.0}), ("anchors", [{"strand_id": "dna"}]),
    ("surface_anchors", [{"strand_id": "dna"}]), ("surface_strands", {"enabled": True}),
    ("stage_overrides", {"relax": {"external_forces_file": "other"}}),
])
def test_unsupported_settings_remain_explicit_unknown_without_a_partial_dna_input(document, monkeypatch, field, value):
    monkeypatch.setattr(core(), "capture_archive", forbidden)
    captured = host().capture_current(options(**{field: value}))
    assert not captured.supported and captured.design is None
    assert captured.coverage["status"] == "unknown" and captured.coverage["reasons"]
    assert document[1].design is document[2]


@pytest.mark.parametrize("family", ["nanoparticles", "protein_assets", "photoproduct_junctions",
                                    "overhang_connections", "atomistic_reference", "native_source"])
def test_unsupported_families_are_not_silently_dropped_or_labeled_owned(document, monkeypatch, family):
    original = document[2]
    if family == "native_source":
        original.helices[0].native_source = "unreviewed-import"
    elif family == "atomistic_reference":
        original.atomistic_reference = m.AtomisticReference.model_construct()
    else:
        model = {"nanoparticles": m.Nanoparticle, "protein_assets": m.ProteinAsset,
                 "photoproduct_junctions": m.PhotoproductJunction,
                 "overhang_connections": m.OverhangConnection}[family]
        # Scope refuses a nonempty family before reading, normalizing or copying
        # its opaque contents; no valid simulation fixture is needed here.
        setattr(original, family, [model.model_construct(id="unsupported")])
    monkeypatch.setattr(core(), "capture_archive", forbidden)
    captured = host().capture_current(options())
    assert not captured.supported and captured.design is None
    assert captured.coverage["status"] == "unknown" and captured.coverage["reasons"]
    assert document[1].design is original


@pytest.mark.parametrize("damage", ["bytes", "nodes", "recovery", "rows"])
def test_reviewed_profile_capture_limit_is_an_explicit_complete_refusal(document, damage):
    original = document[2]
    if damage == "bytes":
        original.metadata.description = "x" * 500_001
    elif damage == "nodes":
        original.annotations[0].refs = [{"kind": "strand", "many": list(range(30_001))}]
    elif damage == "recovery":
        original.feature_log[0].design_snapshot_gz_b64 = "x" * 8_000_001
    else:
        original.feature_log = [m.SnapshotLogEntry(id=str(index), op_kind="overhang-bulk", label="Legacy")
                                for index in range(2001)]
    with pytest.raises(CommandContractError) as error:
        host().capture_current(options())
    assert error.value.code == "oxdna_input_capture_limit"
    assert document[1].design is original and document[1].revision == 7
    assert not document[1].history and not document[1].redo


def test_recovery_payload_is_counted_but_never_decoded_or_promoted_to_evidence(document, monkeypatch):
    monkeypatch.setattr(state, "decode_design_snapshot", forbidden)
    original = document[2]
    original.feature_log[0].design_snapshot_gz_b64 = "not-base64" * 10_000
    captured = host().capture_current(options())
    assert captured.supported and captured.coverage["status"] == "unknown"
    assert captured.design.feature_log[0].design_snapshot_gz_b64 == original.feature_log[0].design_snapshot_gz_b64


def test_private_source_remains_consistent_when_legacy_alias_changes_without_revision(document):
    captured = host().capture_current(options())
    expected = deepcopy(captured.design.model_dump(mode="json"))
    document[2].strands[0].sequence = "TTTTTTTTT"
    document[2].feature_log[0].params["legacy"]["values"].append(99)
    assert captured.design.model_dump(mode="json") == expected
    # Identity/revision alone cannot detect rogue mutable aliases. This capture
    # makes the package internally consistent; it never certifies current input.
    assert captured.coverage["status"] == "unknown"


@pytest.mark.parametrize("schema", ["document_role", "nested_helix"])
def test_new_unreviewed_fields_refuse_coverage_before_copy(document, monkeypatch, schema):
    module = core()
    if schema == "document_role":
        monkeypatch.setattr(module, "FIELD_ROLES", {**module.FIELD_ROLES, "future_input": "authoring"})
    else:
        monkeypatch.setattr(m.Helix, "model_fields", {
            **m.Helix.model_fields, "future_pose": m.Helix.model_fields["phase_offset"]})
    monkeypatch.setattr(module, "capture_archive", forbidden)
    captured = host().capture_current(options())
    assert not captured.supported and captured.design is None
    assert captured.coverage["status"] == "unknown" and captured.coverage["reasons"]


def test_copy_cancellation_propagates_without_partial_capture_or_state_changes(document, monkeypatch):
    class Cancelled(BaseException):
        pass

    def cancelled(_source):
        raise Cancelled()

    original = document[2]
    expected = original.model_dump(mode="json")
    monkeypatch.setattr(core(), "capture_archive", cancelled)
    with pytest.raises(Cancelled):
        host().capture_current(options())
    assert original.model_dump(mode="json") == expected
    assert document[1].design is original and document[1].revision == 7
    assert not document[1].history and not document[1].redo
