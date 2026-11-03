"""Generated native commands must prove their full effects without saved results."""

from uuid import uuid4

import pytest

from backend.api import crud, state
from backend.api.doc_context import reset_current_doc, set_current_doc
from backend.api.generated_commands import fine_routing
from backend.api.generated_history import GeneratedHistory
from backend.api.part_history_verification import verify_current_part
from backend.api.part_proof_commands import execute
from backend.core.models import Design
from backend.core.two_np_generator import GeneratorSettings


@pytest.fixture(autouse=True)
def document():
    token = set_current_doc("generated-native-proof")
    try:
        crud.create_bundle(
            crud.BundleRequest(cells=[[8, 8]], length_bp=32, lattice_type="SQUARE")
        )
        yield
    finally:
        state.close_session()
        reset_current_doc(token)


def construction():
    source = state.get_or_404()
    history = GeneratedHistory(source, GeneratorSettings())
    raw = Design(lattice_type="SQUARE")
    commands = [
        (
            "extrude-segment",
            {
                "cells": [[r, c] for r in range(3) for c in range(2)],
                "length_bp": 32,
                "ligate_adjacent": False,
            },
        ),
        ("auto-scaffold-seamed", {}),
        ("full-autostaple", {"custom_sequence": "ACGT" * 100}),
    ]
    for i, (kind, params) in enumerate(commands):
        params = {**params, "history_seed": str(uuid4()), "_proof_version": 1}
        after = execute(kind, raw, params)
        history.record(raw, after, kind, kind, params, f"native:{i}")
        raw = after
    return history.design


def test_generated_scope_replays_and_edit_preserves_independent_part():
    source = state.get_or_404()
    generated = construction()
    assert [
        s for s in generated.strands if s.id in {s.id for s in source.strands}
    ] == source.strands
    state.set_design(generated)
    assert verify_current_part()["status"] == "verified"
    for entry in state.get_or_404().feature_log:
        entry.design_snapshot_gz_b64 = entry.post_state_gz_b64 = "not proof"
    crud.edit_feature(1, crud.EditFeatureBody(params={"length_bp": 48}))
    result = verify_current_part()
    assert result["status"] == "verified", result
    assert [
        h for h in state.get_or_404().helices if h.id in {h.id for h in source.helices}
    ] == source.helices
    generated_ids = {h.id for h in state.get_or_404().helices} - {
        h.id for h in source.helices
    }
    assert all(
        h.length_bp >= 48 for h in state.get_or_404().helices if h.id in generated_ids
    )
    crud.delete_feature(1, cascade=True)
    assert state.get_or_404().helices == source.helices
    assert verify_current_part()["status"] == "verified"


def test_generated_comparison_rejects_non_strand_authoring_changes():
    before = state.get_or_404()
    dom = before.strands[0].domains[0]
    params = dict(helix_id=dom.helix_id, bp_index=15, direction=dom.direction.value)
    after = execute("nick", before, {**params, "_proof_version": 1})
    # The old comparison checked only helices/strands and accepted these.
    after = after.copy_with(
        tm_settings=after.tm_settings.model_copy(update={"na_mM": 234})
    )
    with pytest.raises(ValueError, match="tm_settings"):
        fine_routing(before, after, [("nick", "Nick", params)])


def test_generated_compiler_rejects_planned_output_substitution():
    before = Design(lattice_type="SQUARE")
    params = {
        "cells": [[0, 0]],
        "length_bp": 32,
        "history_seed": str(uuid4()),
        "_proof_version": 1,
    }
    after = execute("extrude-segment", before, params)
    after = after.copy_with(
        helices=[after.helices[0].model_copy(update={"length_bp": 31})]
    )
    history = GeneratedHistory(state.get_or_404(), GeneratorSettings())
    with pytest.raises(ValueError, match="differs from native execution"):
        history.record(before, after, "extrude-segment", "Extrude", params, "native")
    assert history.design == state.get_or_404()


def nick_plan():
    from backend.api.two_np_build import _handles
    from tests.test_joined_branches import _source

    source = _source(True)  # Four particles with their existing native handles.
    original = source.model_dump_json()
    settings = GeneratorSettings(connections_per_particle=1)
    history = GeneratedHistory(source, settings)
    raw = Design(lattice_type=source.lattice_type)
    params = dict(cells=[[0, 0]], length_bp=32, history_seed=str(uuid4()), _proof_version=1)
    before = execute("extrude-segment", raw, params)
    history.record(raw, before, "extrude-segment", "Extrude", params, "extrude")
    dom = before.strands[0].domains[0]
    before, handles = _handles(source, before, source.nanoparticles, settings, history)
    assert all(reused for _, _, _, reused in handles)
    assert source.model_dump_json() == original
    params = dict(helix_id=dom.helix_id, bp_index=15, direction=dom.direction.value,
                  _proof_version=1)
    return source, history, before, execute("nick", before, params), params


def test_generated_reused_handles_preserve_native_order_through_nick_and_edit():
    from backend.core.part_history_proof import AUTHORING_FIELDS

    source, history, before, after, params = nick_plan()
    history.record(before, after, "nick", "Nick", params, "nick")
    target = after.strands[-1]
    params = dict(strand_id=target.id, name="Edited strand", _proof_version=1)
    edited = execute("strand-patch", after, params)
    history.record(after, edited, "strand-patch", "Name strand", params, "name")
    # Independently replay inputs, without consuming any stored result snapshots.
    replayed = source
    for entry in history.design.feature_log[len(source.feature_log):]:
        if getattr(entry, "children", None):
            for child in entry.children:
                replayed = execute(child.op_subtype, replayed, child.params)
        else:
            replayed = execute(entry.op_kind, replayed, entry.params)
    assert history.design.model_dump(include=AUTHORING_FIELDS) == replayed.model_dump(
        include=AUTHORING_FIELDS
    )
    assert [s for s in history.design.strands if s.id in {s.id for s in source.strands}] == source.strands


@pytest.mark.parametrize("defect", ["content", "missing"])
def test_generated_nick_rejects_planned_strand_changes_atomically(defect):
    source, history, before, after, params = nick_plan()
    target = next(s for s in after.strands if s.id not in {s.id for s in source.strands})
    if defect == "content":
        target.name = "Substituted planned strand"
    else:
        after = after.copy_with(strands=[s for s in after.strands if s.id != target.id])
    original = history.design.model_dump_json()
    with pytest.raises(ValueError, match="differs from native execution"):
        history.record(before, after, "nick", "Nick", params, "nick")
    assert history.design.model_dump_json() == original


def test_legacy_compound_output_is_explicitly_unverified():
    from backend.api.generated_commands import certify_entries
    from backend.core.models import SnapshotLogEntry
    from backend.api.part_proof_commands import dependencies, capabilities

    before = state.get_or_404()
    entry = SnapshotLogEntry(
        op_kind="generate-design", label="Legacy branched result", params={}
    )
    entries, reason = certify_entries(before, before, [entry])
    assert reason and entries == [entry]
    assert not dependencies(entries[0].op_kind, entries[0].params).known
    c = capabilities()
    assert not c["certifies_history"]
    assert c["command_editors"]["nick"]["history_ui"] == "not_available"
    assert c["history_edit"]["routing_child_query"] == "sub_index"
    assert c["repair_contract"]["draft_endpoints"] == {
        "inspect": "GET /api/design/features/repair-draft",
        "mutate": "POST /api/design/features/repair-draft",
        "evaluate": "POST /api/design/features/repair-draft/evaluate",
        "source_inspect": "POST /api/design/features/repair-draft/source/inspect",
        "source_upload": "POST /api/design/features/repair-draft/source",
    }
    assert "saved status is not readiness" in c["repair_contract"]["drafts"]
    assert "restoration requires rebase" in c["repair_contract"]["source_repair"]
    assert "apply retains proposal" in c["repair_contract"]["draft_evaluation"]
    assert "desktop input/reference repair" in c["repair_contract"]["ui"]
    assert "native DNA candidate comparison enabled" in c["repair_contract"]["comparison"]
    assert "streptavidin-coating" in c["evaluation_jobs"]["append_kinds"]
    assert c["coating_contract"]["live_append"].startswith("Enabled")
    assert "ordinary limits unchanged" in c["coating_contract"]["capture"]
    assert "bounded native coating/biotin rows" in c["coating_contract"]["publication_scope"]
    assert c["evaluation_jobs"]["registered_batch_enabled"] is False
    assert "batch" not in c["evaluation_jobs"]["operations"]
    assert c["photoproduct_create_methods"] == ["preflight", "convert"]
    assert "photoproduct-create:convert" in c["long_job_methods"]
    assert "legacy photoproduct-create:convert" in c["unverified_methods"]
    assert not dependencies("photoproduct-create", {
        "_proof_version": 1, "method": "convert", "history_seed": "legacy",
    }).known
