"""Ordinary group PATCH owns authored edits independently of legacy log flags.

Memory-only route tests use a real native prefix and poison recovery payloads
before proof. Pose-only live previews retain their existing, nonrecording
contract; isolated preview lifecycle and group deletion are separate work.
"""

from dataclasses import replace

import pytest
from fastapi import HTTPException

from backend.api import doc_context, routes_clusters as routes, state
from backend.core.models import Design
from tests.test_geometry_group_history import _create, _proof, _stored, _verified
from tests.test_geometry_group_history import document as document


def _snapshot():
    session = state._session()
    return {
        "source": session.design,
        "stored": session.design.model_dump(mode="json"),
        "history": list(session.history), "redo": list(session.redo),
        "revision": session.revision,
        "request_revision": doc_context.current_request_revision(),
        "request_entry": doc_context.current_request_feature_log_entry_id(),
    }


def _unchanged(before):
    after = _snapshot()
    assert after.pop("source") is before["source"]
    assert after == {key: value for key, value in before.items() if key != "source"}


def _patch(source, field):
    return {
        "name": {"name": "Renamed arm"},
        "helix_ids": {"helix_ids": [h.id for h in source.helices]},
        "domain_ids": {"domain_ids": [{"strand_id": source.strands[0].id, "domain_index": 0}]},
        "color": {"color": "#123456"},
        "opacity": {"opacity": 0.4},
    }[field]


@pytest.mark.parametrize("field", ["name", "helix_ids", "domain_ids", "color", "opacity"])
def test_ordinary_authored_patch_records_exact_inputs_and_roundtrips(document, field):
    source, group, _ = _create(document)
    before = _snapshot()
    response = routes.update_cluster(group.id, routes.PatchClusterBody(**_patch(source, field)))
    updated = state.get_or_404()
    current = next(c for c in updated.cluster_transforms if c.id == group.id)
    row = updated.feature_log[-1]

    assert len(updated.feature_log) == len(source.feature_log) + 1
    assert row.feature_type == "cluster_op" and row.proof_version == 1
    assert row.cluster_id == current.id == group.id
    assert row.authored_fields == current.model_dump(mode="json", include={
        "name", "helix_ids", "domain_ids", "color", "opacity"})
    assert (row.translation, row.rotation, row.pivot) == (
        current.translation, current.rotation, current.pivot)
    assert updated.helices == source.helices and updated.strands == source.strands
    assert updated.deformations == source.deformations
    assert updated.recipe_root == source.recipe_root
    assert source.model_dump(mode="json") == before["stored"]
    assert state.undo_depth() == len(before["history"]) + 1
    assert state.revision() == before["revision"] + 1 == response["revision"]
    if field in {"helix_ids", "domain_ids"}:
        assert "nucleotides" in response and "helix_axes" in response
    else:
        assert not {"nucleotides", "helix_axes", "partial_geometry"} & response.keys()
    expected = _stored(updated)
    loaded = Design.from_json(updated.model_dump_json())
    assert _stored(loaded) == expected
    _verified(loaded)
    undone, _ = state.undo()
    assert _stored(undone) == _stored(source)
    _verified(undone)
    redone, _ = state.redo()
    assert _stored(redone) == expected
    _verified(redone)


def test_membership_response_embeds_native_candidate_geometry_outside_lock(document, monkeypatch):
    from backend.api import crud

    source, group, _ = _create(document)
    routes.update_cluster(group.id, routes.PatchClusterBody(translation=[7, 8, 9], commit=True))
    source = state.get_or_404()
    original = crud._geometry_for_design(source, measured_positioning=True, junction_balance=True)
    response_builder = crud._design_response_with_geometry
    captured = []

    def response_from_candidate(candidate, report, **kwargs):
        assert not state._lock.locked(), "Native response geometry must not hold the publication lock"
        assert candidate is state.get_or_404()
        captured.append(candidate)
        return response_builder(candidate, report, **kwargs)

    monkeypatch.setattr(crud, "_design_response_with_geometry", response_from_candidate)
    response = routes.update_cluster(group.id, routes.PatchClusterBody(helix_ids=[h.id for h in source.helices]))
    assert len(captured) == 1
    assert response["revision"] == state.revision()
    assert response["design"]["feature_log"][-1]["cluster_id"] == group.id
    assert "straight_positions_by_helix" in response
    assert len(response["nucleotides"]) == len(original)
    for before, after in zip(original, response["nucleotides"], strict=True):
        assert (before["helix_id"], before["bp_index"], before["direction"]) == (
            after["helix_id"], after["bp_index"], after["direction"])
        delta = [0, 0, 0] if before["helix_id"] == group.helix_ids[0] else [7, 8, 9]
        assert after["backbone_position"] == pytest.approx(
            [value + offset for value, offset in zip(before["backbone_position"], delta, strict=True)])
    _verified(captured[0])


@pytest.mark.parametrize("patch", [{"name": "Moved", "translation": [3, 0, 0]},
                                   {"color": "#123456", "pivot": [2, 0, 0]}])
def test_mixed_authored_pose_response_is_geometry_bearing(document, patch):
    _, group, _ = _create(document)
    response = routes.update_cluster(group.id, routes.PatchClusterBody(**patch))
    assert "nucleotides" in response and "helix_axes" in response


def test_geometry_response_keeps_its_committed_source_and_revision(document, monkeypatch):
    from backend.api import crud

    _, group, _ = _create(document)
    response_builder = crud._design_response_with_geometry
    captured = []

    def later_document_change(candidate, report, **kwargs):
        # Simulate a separate request publishing after this commit. Its revision
        # is deliberately not installed into this request's context variable.
        own_revision = doc_context.current_request_revision()
        later = candidate.copy_with(cluster_transforms=[
            cluster.model_copy(update={"name": "Later concurrent edit"}) if cluster.id == group.id else cluster
            for cluster in candidate.cluster_transforms])
        state.set_design(later)
        doc_context.set_request_revision(own_revision)
        captured.append(candidate)
        return response_builder(candidate, report, **kwargs)

    monkeypatch.setattr(crud, "_design_response_with_geometry", later_document_change)
    response = routes.update_cluster(group.id, routes.PatchClusterBody(helix_ids=[]))
    assert response["revision"] == state.revision() - 1
    assert response["design"]["cluster_transforms"] == captured[0].model_dump(mode="json")["cluster_transforms"]
    assert response["design"]["cluster_transforms"] != state.get_or_404().model_dump(mode="json")["cluster_transforms"]


@pytest.mark.parametrize("flags", [
    {"commit": False, "log": False}, {"commit": True, "log": True},
], ids=["explicit-false", "explicit-true"])
def test_legacy_flags_cannot_suppress_or_duplicate_authored_row(document, flags):
    source, group, _ = _create(document)
    depth, revision = state.undo_depth(), state.revision()
    routes.update_cluster(group.id, routes.PatchClusterBody(name="Authored", **flags))
    current = state.get_or_404()
    assert len(current.feature_log) == len(source.feature_log) + 1
    assert state.undo_depth() == depth + 1 and state.revision() == revision + 1
    _verified(current)


@pytest.mark.parametrize("extra", [{}, {"name": None, "helix_ids": None, "domain_ids": None,
                                      "color": None, "opacity": None}], ids=["omitted", "null"])
def test_pose_only_preview_does_not_record_but_explicit_confirm_does(document, extra):
    source, group, _ = _create(document)
    depth, revision = state.undo_depth(), state.revision()
    routes.update_cluster(group.id, routes.PatchClusterBody(
        translation=[1, 2, 3], commit=False, log=False, **extra))
    preview = state.get_or_404()
    assert preview is not source
    assert next(c for c in preview.cluster_transforms if c.id == group.id).translation == [1, 2, 3]
    assert preview.feature_log == source.feature_log
    assert state.undo_depth() == depth and state.revision() == revision + 1
    routes.update_cluster(group.id, routes.PatchClusterBody(commit=True, log=False))
    final = state.get_or_404()
    assert len(final.feature_log) == len(source.feature_log) + 1
    assert final.feature_log[-1].translation == [1, 2, 3]
    assert state.undo_depth() == depth + 1
    _verified(final)


def test_empty_authored_values_clear_membership_and_color_with_one_row(document):
    source, group, _ = _create(document)
    routes.update_cluster(group.id, routes.PatchClusterBody(
        helix_ids=[], domain_ids=[], color="", name="", opacity=0))
    current = state.get_or_404()
    row = current.feature_log[-1]
    assert len(current.feature_log) == len(source.feature_log) + 1
    assert row.authored_fields == {
        "helix_ids": [], "domain_ids": [], "color": None, "name": "", "opacity": 0.0}
    _verified(current)


@pytest.mark.parametrize("case", [
    "missing-group", "duplicate-group", "missing-helix", "duplicate-helix",
    "missing-strand", "duplicate-strand", "missing-domain",
])
def test_invalid_or_ambiguous_targets_refuse_before_publication(document, monkeypatch, case):
    source, group, _ = _create(document)
    target, patch = group.id, {"name": "Attempt"}
    if case == "missing-group":
        target = "missing-group"
    elif case == "duplicate-group":
        source = source.copy_with(cluster_transforms=[*source.cluster_transforms, group.model_copy(deep=True)])
    elif case == "missing-helix":
        patch = {"helix_ids": ["missing-helix"]}
    elif case == "duplicate-helix":
        source = source.copy_with(helices=[*source.helices, source.helices[0].model_copy(deep=True)])
        patch = {"helix_ids": [source.helices[0].id]}
    else:
        if case == "duplicate-strand":
            source = source.copy_with(strands=[*source.strands, source.strands[0].model_copy(deep=True)])
        patch = {"domain_ids": [{
            "strand_id": "missing-strand" if case == "missing-strand" else source.strands[0].id,
            "domain_index": len(source.strands[0].domains) if case == "missing-domain" else 0,
        }]}
    state.load_design(source)
    before = _snapshot()

    def unexpected(*_args, **_kwargs):
        raise AssertionError("Invalid group targets must refuse before publication or undo copying")

    from backend.api import part_group_recording
    with monkeypatch.context() as traps:
        traps.setattr(part_group_recording, "publish_replacement", unexpected)
        traps.setattr(state, "_snapshot_copy", unexpected)
        with pytest.raises(HTTPException) as caught:
            routes.update_cluster(target, routes.PatchClusterBody(**patch))
    assert caught.value.status_code in {404, 409, 422}
    assert isinstance(caught.value.detail, dict) and caught.value.detail.get("code")
    _unchanged(before)


@pytest.mark.parametrize("cursor,sub_cursor", [(-2, None), (0, None), (0, 0), (-1, 0)])
def test_historical_authored_patch_refuses_before_build(document, monkeypatch, cursor, sub_cursor):
    from backend.api import part_group_recording

    source, group, _ = _create(document)
    state.load_design(source.copy_with(feature_log_cursor=cursor, feature_log_sub_cursor=sub_cursor))
    before = _snapshot()

    def unexpected(*_args, **_kwargs):
        raise AssertionError("Historical group edit must refuse before native build or undo")

    with monkeypatch.context() as traps:
        traps.setattr(part_group_recording, "build", unexpected)
        traps.setattr(state, "_snapshot_copy", unexpected)
        with pytest.raises(HTTPException) as caught:
            routes.update_cluster(group.id, routes.PatchClusterBody(name="Historical edit"))
    assert caught.value.status_code == 409
    assert caught.value.detail["code"] == "historical_cursor"
    _unchanged(before)


@pytest.mark.parametrize("failure", ["validation", "publication", "cancellation"])
def test_authored_edit_failure_restores_exact_source_and_stacks(document, monkeypatch, failure):
    from backend.core import validator

    source, group, _ = _create(document)
    _create(source, name="Redo-only")
    state.undo()
    before = _snapshot()

    class Cancelled(BaseException):
        pass

    error_type = Cancelled if failure == "cancellation" else RuntimeError
    with monkeypatch.context() as faults:
        if failure == "validation":
            def fail(_candidate):
                raise error_type("group edit validation failed")
            faults.setattr(validator, "validate_design", fail)
            faults.setattr(state, "validate_design", fail)
        else:
            bump = state._bump_revision

            def fail(session):
                bump(session)
                raise error_type("group edit publication failed")
            faults.setattr(state, "_bump_revision", fail)
        with pytest.raises(error_type, match="group edit .* failed"):
            routes.update_cluster(group.id, routes.PatchClusterBody(name="Attempt"))
    _unchanged(before)


@pytest.mark.parametrize("replacement", ["source", "session"], ids=["source-object-aba", "session-incarnation"])
def test_candidate_cannot_publish_over_replaced_source_or_session(document, monkeypatch, replacement):
    from backend.core import validator

    source, group, _ = _create(document)
    stored = source.model_dump(mode="json")
    original_validate = state.validate_design
    observed = []

    def replace_after_validation(candidate):
        report = original_validate(candidate)
        session = state._session()
        if replacement == "source":
            session.design = source.model_copy(deep=True)
        else:
            # Same Design object and revision, but a new document incarnation.
            state._sessions[doc_context.get_current_doc()] = replace(session, identity="replacement-session")
        observed.append(_snapshot())
        return report

    with monkeypatch.context() as hooks:
        hooks.setattr(state, "validate_design", replace_after_validation)
        hooks.setattr(validator, "validate_design", replace_after_validation)
        with pytest.raises(HTTPException) as caught:
            routes.update_cluster(group.id, routes.PatchClusterBody(name="Attempt"))
    assert caught.value.status_code == 409 and caught.value.detail["code"] == "source_changed"
    assert len(observed) == 1
    _unchanged(observed[0])
    assert source.model_dump(mode="json") == stored


def test_authored_edit_owns_one_nonreentrant_lock_without_proof_or_reconcile(document, monkeypatch):
    from backend.api import part_group_recording as recording, part_proof_commands
    from backend.core import part_history_contract

    source, group, _ = _create(document)

    class GuardedLock:
        held = False

        def __enter__(self):
            assert not self.held, "Group edit reacquired the non-reentrant state lock"
            self.held = True
            return self

        def __exit__(self, *_args):
            self.held = False

    lock, events = GuardedLock(), []
    build, validate, snapshot, publish = recording.build, state.validate_design, state._snapshot_copy, recording.publish_replacement

    def built(kind, selected, params):
        assert lock.held and selected is source and kind == "cluster_op"
        events.append("build")
        return build(kind, selected, params)

    def validated(candidate):
        assert lock.held and candidate is not source
        events.append("validate")
        return validate(candidate)

    def copied(selected):
        assert lock.held and selected is source
        events.append("undo")
        return snapshot(selected)

    def published(session, candidate):
        assert lock.held and session.design is source
        events.append("publish")
        return publish(session, candidate)

    def unexpected(*_args, **_kwargs):
        raise AssertionError("Group edit must not run full proof or reconciliation")

    with monkeypatch.context() as hooks:
        hooks.setattr(state, "_lock", lock)
        hooks.setattr(recording, "build", built)
        hooks.setattr(state, "validate_design", validated)
        hooks.setattr(state, "_snapshot_copy", copied)
        hooks.setattr(recording, "publish_replacement", published)
        hooks.setattr(state, "reconcile_cluster_membership", unexpected)
        hooks.setattr(state, "_retry_pending_ligations", unexpected)
        hooks.setattr(part_history_contract, "assess_part_history", unexpected)
        hooks.setattr(part_proof_commands, "execute", unexpected)
        routes.update_cluster(group.id, routes.PatchClusterBody(name="Single-lock edit"))
    assert not lock.held
    assert events == ["build", "validate", "publish", "undo"]
    _verified(state.get_or_404())


def test_authored_patch_does_not_bless_rootless_legacy_source(document):
    source, group, _ = _create(document)
    legacy = source.copy_with(recipe_root=None, feature_log=[])
    state.load_design(legacy)
    routes.update_cluster(group.id, routes.PatchClusterBody(name="Legacy renamed"))
    current = state.get_or_404()
    assert current.recipe_root is None and len(current.feature_log) == 1
    result = _proof(current)
    assert result["status"] == "unverified" and result["native_editable"] is False
    assert any(issue["code"] == "missing_recipe_root" for issue in result["issues"])


def test_protected_loadout_refuses_before_group_preparation(document, monkeypatch):
    from backend.api import part_group_recording

    _, group, _ = _create(document)
    before = _snapshot()
    calls = []

    def protected(source, *_args):
        assert source is before["source"]
        calls.append("protected")
        raise HTTPException(409, detail={"code": "protected_loadout"})

    def unexpected(*_args, **_kwargs):
        raise AssertionError("Protected branch must refuse before group preparation or undo")

    with monkeypatch.context() as traps:
        traps.setattr(state, "_assert_active_loadout_editable", protected)
        traps.setattr(part_group_recording, "build", unexpected)
        traps.setattr(part_group_recording.ClusterRigidTransform, "model_validate", unexpected)
        traps.setattr(state, "_snapshot_copy", unexpected)
        with pytest.raises(HTTPException) as caught:
            routes.update_cluster(group.id, routes.PatchClusterBody(name="Protected edit"))
    assert caught.value.status_code == 409 and caught.value.detail["code"] == "protected_loadout"
    assert calls == ["protected"]
    _unchanged(before)


@pytest.mark.parametrize("patch", [
    {"translation": [1, 2]}, {"rotation": [0, 0, 1]}, {"pivot": [0, 0, 0, 0]},
    {"translation": [float("inf"), 0, 0]}, {"pivot": [0, float("nan"), 0]},
    {"rotation": [0, 0, 0, float("-inf")]}, {"rotation": [0, 0, 0, 0]},
    {"opacity": float("nan")}, {"opacity": float("inf")},
], ids=["translation-size", "rotation-size", "pivot-size", "translation-infinite",
        "pivot-nan", "rotation-infinite", "zero-quaternion", "opacity-nan", "opacity-infinite"])
def test_invalid_authored_pose_or_opacity_refuses_before_build(document, monkeypatch, patch):
    from backend.api import part_group_recording

    _, group, _ = _create(document)
    before = _snapshot()
    body = routes.PatchClusterBody(name="Malformed edit", **patch)

    def unexpected(*_args, **_kwargs):
        raise AssertionError("Malformed group pose must refuse before build or undo")

    with monkeypatch.context() as traps:
        traps.setattr(part_group_recording, "build", unexpected)
        traps.setattr(state, "_snapshot_copy", unexpected)
        with pytest.raises(HTTPException) as caught:
            routes.update_cluster(group.id, body)
    assert caught.value.status_code == 422
    assert caught.value.detail["code"] in {
        "invalid_group_pose", "invalid_group_opacity", "invalid_group_input"}
    _unchanged(before)


@pytest.mark.parametrize("opacity,expected", [(-1, 0.0), (2, 1.0)])
def test_finite_opacity_keeps_existing_clamp_and_authors_clamped_input(document, opacity, expected):
    source, group, _ = _create(document)
    routes.update_cluster(group.id, routes.PatchClusterBody(opacity=opacity))
    current = state.get_or_404()
    assert len(current.feature_log) == len(source.feature_log) + 1
    assert current.feature_log[-1].authored_fields["opacity"] == expected
    assert next(c for c in current.cluster_transforms if c.id == group.id).opacity == expected
    _verified(current)


@pytest.mark.parametrize("selection", ["helices", "domains"])
def test_repeated_member_selection_refuses_before_build(document, monkeypatch, selection):
    from backend.api import part_group_recording

    source, group, _ = _create(document)
    before = _snapshot()
    ref = {"strand_id": source.strands[0].id, "domain_index": 0}
    patch = ({"helix_ids": [source.helices[0].id] * 2} if selection == "helices"
             else {"domain_ids": [ref, ref]})

    def unexpected(*_args, **_kwargs):
        raise AssertionError("Repeated selectors must refuse before build or undo")

    with monkeypatch.context() as traps:
        traps.setattr(part_group_recording, "build", unexpected)
        traps.setattr(state, "_snapshot_copy", unexpected)
        with pytest.raises(HTTPException) as caught:
            routes.update_cluster(group.id, routes.PatchClusterBody(**patch))
    assert caught.value.status_code == 409
    assert caught.value.detail["code"] == "invalid_selection"
    assert caught.value.detail["references"]
    _unchanged(before)


@pytest.mark.parametrize("limit_case", ["source-count", "requested-helices", "requested-domains",
                                        "target-identity", "source-identity"])
def test_input_limits_refuse_before_group_or_domain_model_parsing(document, monkeypatch, limit_case):
    from backend.api import part_group_recording
    from backend.core import models

    source, group, _ = _create(document)
    target, patch = group.id, {"name": "Bounded edit"}
    maximum = len(source.helices) + len(source.strands) + len(group.helix_ids)
    if limit_case == "source-count":
        maximum -= 1
    elif limit_case == "requested-helices":
        patch = {"helix_ids": [source.helices[0].id] * (maximum + 1)}
    elif limit_case == "requested-domains":
        patch = {"domain_ids": [{"strand_id": source.strands[0].id, "domain_index": 0}] * (maximum + 1)}
    elif limit_case == "target-identity":
        target = "x" * 51
    else:
        replacement = source.helices[0].model_copy(update={"id": "x" * 51})
        source = source.copy_with(helices=[replacement, *source.helices[1:]])
        state.load_design(source)
    before = _snapshot()
    body = routes.PatchClusterBody(**patch)

    def unexpected(*_args, **_kwargs):
        raise AssertionError("Input bounds must refuse before group/domain parsing, native build or undo")

    with monkeypatch.context() as traps:
        traps.setattr(part_group_recording, "MAX_ITEMS", maximum)
        traps.setattr(part_group_recording, "MAX_ID_CHARS", 50)
        traps.setattr(part_group_recording.ClusterRigidTransform, "model_validate", unexpected)
        traps.setattr(models, "DomainRef", unexpected)
        traps.setattr(part_group_recording, "build", unexpected)
        traps.setattr(state, "_snapshot_copy", unexpected)
        with pytest.raises(HTTPException) as caught:
            routes.update_cluster(target, body)
    assert caught.value.status_code == 409
    assert caught.value.detail["code"] == "group_input_limit"
    _unchanged(before)


def test_unrelated_validation_failure_remains_a_report_without_blessing_source(document, monkeypatch):
    from backend.core.validator import ValidationReport, ValidationResult

    source, group, _ = _create(document)
    report = ValidationReport()
    report.results.append(ValidationResult(False, "Existing unrelated scientific diagnostic"))
    calls = []

    def diagnosed(candidate):
        assert candidate is not source
        calls.append(candidate)
        return report

    with monkeypatch.context() as hooks:
        hooks.setattr(state, "validate_design", diagnosed)
        response = routes.update_cluster(group.id, routes.PatchClusterBody(name="Diagnostic retained"))
    current = state.get_or_404()
    assert calls == [current]
    assert len(current.feature_log) == len(source.feature_log) + 1
    assert response["validation"]["passed"] is False
    assert any(item["message"] == "Existing unrelated scientific diagnostic" and item["ok"] is False
               for item in response["validation"]["results"])
    # Reproduction is separate from the report's scientific verdict.
    _verified(current)


@pytest.mark.parametrize("scope", ["request", "emitted-command"])
def test_operation_envelope_refuses_before_unbudgeted_candidate_or_build(document, monkeypatch, scope):
    from backend.api import part_group_recording
    from backend.core import part_operation_input

    _, group, _ = _create(document)
    before = _snapshot()

    def unexpected(*_args, **_kwargs):
        raise AssertionError("Operation envelope must be admitted before preparation or native build")

    with monkeypatch.context() as traps:
        # The request has two nodes; the complete recorded v1 pose/membership
        # command has more. Both allowances are tiny, with no large fixture.
        traps.setattr(part_operation_input, "MAX_OPERATION_NODES", 1 if scope == "request" else 3)
        if scope == "request":
            traps.setattr(part_group_recording.ClusterRigidTransform, "model_validate", unexpected)
        traps.setattr(part_group_recording, "build", unexpected)
        traps.setattr(state, "_snapshot_copy", unexpected)
        with pytest.raises(HTTPException) as caught:
            routes.update_cluster(group.id, routes.PatchClusterBody(name="Bounded"))
    assert caught.value.status_code == 422
    assert caught.value.detail["code"] == "invalid_group_input"
    _unchanged(before)
