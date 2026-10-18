"""Preallocation guards for native transform-preview producer prefixes.

These are admission controls, not historical producer qualification. The
independent constraint-history dossier exercises real empty-root recipes.
"""

from copy import deepcopy
from uuid import UUID

import pytest

from backend.api import part_deformation_preview as preview
from backend.api.part_proof_commands import execute
from backend.core.part_command_errors import CommandContractError
from tests.test_part_duplex_commands import source as duplex_source
from tests.test_part_pending_connection_versions import native_prefix, creation, command
from tests.test_part_connection_application_commands import application_prefix, _params

from tests.preview_test_limits import preview_test_scale_limits  # noqa: F401  (fixture)

# Bounding-mechanism tests use tiny fixtures at the original test-scale allowances.
pytestmark = pytest.mark.usefixtures("preview_test_scale_limits")



def _trap(*_args, **_kwargs):
    raise AssertionError("Native allocation ran before preview admission")


def _admission():
    from backend.api import part_transform_prefix_admission
    return part_transform_prefix_admission


@pytest.fixture
def source():
    return application_prefix.__wrapped__(native_prefix.__wrapped__())


def test_current_fixture_is_within_unchanged_preview_limits(source):
    preview._work(source, lambda: None)
    assert preview._slots(source) < preview.MAX_SLOTS == 1024
    assert preview.MAX_HELICES == 16


@pytest.mark.parametrize("role", ["sequence", "pending", "linker-apply", "duplex"])
def test_admitted_producer_matches_registered_native_output_without_source_mutation(source, role):
    before = source.model_dump(mode="json")
    if role == "sequence":
        kind, values = "overhang-sequence", {"_proof_version": 1, "overhang_id": source.overhangs[0].id, "sequence": "ACGT" * 3}
    elif role in {"pending", "linker-apply"}:
        kind, values = command("connection-version-create", creation(source,
            connection_type="root-to-end-ssdna-linker", overhang_a_seq="ACGT" * 3, overhang_b_seq="TGCA" * 3))
        if role == "linker-apply":
            source = execute(kind, source, values)
            before = source.model_dump(mode="json")
            kind, values = "overhang-bulk", _params(source)
    else:
        kind = "duplex-connect"
        values = {"_proof_version": 1, "history_seed": str(UUID(int=901)),
            "duplex_id": "prefix-duplex", "created_at": 1.0, "binding_ids": [],
            "overhang_a_id": source.overhangs[0].id, "overhang_b_id": source.overhangs[1].id,
            "overhang_a_attach": "free_end", "overhang_b_attach": "root", "driver": "left"}
    expected = execute(kind, source.model_copy(deep=True), deepcopy(values))
    actual = preview._run(kind, source, values, lambda: None)
    assert actual.model_dump(mode="json") == expected.model_dump(mode="json")
    assert source.model_dump(mode="json") == before


@pytest.mark.parametrize("kind,values", [
    ("overhang-extrude", {"length_bp": 1025, "bp_index": 0}),
    ("overhang-sequence", {"overhang_id": "missing", "sequence": "A" * 1025}),
    ("linker-add", {"length_value": 1e308, "length_unit": "nm"}),
    ("linker-add", {"length_value": float("inf"), "length_unit": "bp"}),
    ("linker-add", {"length_value": 1025, "length_unit": "bp"}),
    ("overhang-bulk", {"action": "resize-free-end", "delta_bp": 1025, "overhang_id": "missing"}),
])
def test_growth_is_refused_before_native_builder(source, monkeypatch, kind, values):
    monkeypatch.setattr(preview, "execute", _trap)
    before = source.model_dump(mode="json")
    with pytest.raises(CommandContractError) as caught:
        preview._run(kind, source, values, lambda: None)
    assert caught.value.code == "preview_limit"
    assert source.model_dump(mode="json") == before


def test_pending_large_bridge_is_metadata_but_application_is_refused_before_builder(source, monkeypatch):
    kind, values = command("connection-version-create", creation(source, bridge_length=900))
    pending = execute(kind, source, values)
    assert _admission().admit(kind, source, values)
    monkeypatch.setattr(preview, "execute", _trap)
    with pytest.raises(CommandContractError) as caught:
        preview._run("overhang-bulk", pending, _params(pending), lambda: None)
    assert caught.value.code == "preview_limit"


def test_finite_apply_uses_native_live_length_for_stale_candidate_sequences(source):
    kind, values = command("connection-version-create", creation(source,
        connection_type="root-to-end-ssdna-linker", overhang_a_seq="A" * 200, overhang_b_seq="T" * 200))
    pending = execute(kind, source, values)
    params = _params(pending)
    expected = execute("overhang-bulk", pending.model_copy(deep=True), params)
    actual = preview._run("overhang-bulk", pending, params, lambda: None)
    assert actual.model_dump(mode="json") == expected.model_dump(mode="json")
    assert [len(item.sequence) for item in actual.overhangs] == [12, 12]


def test_reused_overhang_host_charges_gap_union_before_builder(source, monkeypatch):
    host = source.find_helix(source.overhangs[0].helix_id)
    shifted = host.model_copy(update={"bp_start": 700})
    source = source.copy_with(helices=[shifted if h.id == host.id else h for h in source.helices])
    values = {"helix_id": source.helices[0].id, "bp_index": 0, "length_bp": 12,
        "neighbor_row": host.grid_pos[0], "neighbor_col": host.grid_pos[1],
        "direction": "FORWARD", "is_five_prime": False, "reuse_existing_helix": True}
    monkeypatch.setattr(preview, "execute", _trap)
    with pytest.raises(CommandContractError) as caught:
        preview._run("overhang-extrude", source, values, lambda: None)
    assert caught.value.code == "preview_limit"


def _saved_source():
    source = duplex_source(rooted=True, equal=True, binding=True)
    binding = source.overhang_bindings[0]
    helix = source.find_helix("b")
    domain = source.find_strand("st-b").domains[-1]
    saved = {"driver_oh_id": "oh-a", "driven_oh_id": "oh-b", "driven_helix": helix.model_dump(mode="json"),
        "strand_id": "st-b", "domain_index": 1, "prior_ovhg_helix_id": "b",
        "prior_domain": {"helix_id": "b", "start_bp": domain.start_bp, "end_bp": domain.end_bp,
            "direction": domain.direction.value}, "crossovers": []}
    return source.copy_with(overhang_bindings=[binding.model_copy(update={"bound": True,
        "driver_oh_id": "oh-a", "driven_oh_id": "oh-b", "prior_driven_topology": saved})])


def test_saved_topology_uses_shared_typed_admission_and_keeps_source_owned(monkeypatch):
    from backend.core import part_saved_topology

    source = _saved_source()
    before = source.model_dump(mode="json")
    calls = []
    original = part_saved_topology.snapshot_for
    def observe(owner):
        calls.append(owner.id)
        return original(owner)
    monkeypatch.setattr(part_saved_topology, "snapshot_for", observe)
    assert _admission().admit("overhang-bulk", source,
        {"action": "overhang-binding-patch", "binding_id": "binding", "bound": False})
    assert calls == ["binding"]
    assert source.model_dump(mode="json") == before


@pytest.mark.parametrize("damage", ["span", "loops", "extras", "grammar", "raw-budget"])
def test_restored_topology_refuses_before_native_allocation(monkeypatch, damage):
    source = _saved_source()
    saved = source.overhang_bindings[0].prior_driven_topology
    if damage == "span":
        saved["driven_helix"]["length_bp"] = 1025
    elif damage == "loops":
        saved["driven_helix"]["loop_skips"] = [{"bp_index": 0, "delta": 1}] * 1025
    elif damage == "extras":
        cross = source.crossovers[0].model_copy(update={"extra_bases": "A" * 1025})
        saved["crossovers"] = [cross.model_dump(mode="json")]
    elif damage == "grammar":
        saved["unknown"] = True
    else:
        saved["crossovers"] = [None] * 30001
        from backend.core import part_saved_topology
        monkeypatch.setattr(part_saved_topology, "snapshot_for", _trap)
    monkeypatch.setattr(preview, "execute", _trap)
    with pytest.raises(CommandContractError) as caught:
        preview._run("overhang-bulk", source,
            {"action": "overhang-binding-patch", "binding_id": "binding", "bound": False}, lambda: None)
    assert caught.value.code in {"preview_limit", "invalid_preview_definition"}


@pytest.mark.parametrize("kind,params", [
    ("photoproduct-create", {"method": "convert"}), ("photoproduct-relax", {}),
    ("duplex-relax", {}), ("overhang-bulk", {"action": "unknown-future-action"}),
])
def test_unadmitted_scientific_or_unknown_family_never_reaches_fast_executor(source, monkeypatch, kind, params):
    monkeypatch.setattr(preview, "execute", _trap)
    with pytest.raises(CommandContractError) as caught:
        preview._run(kind, source, params, lambda: None)
    assert caught.value.code == "unsupported_preview_scope"


def _extension(source, *, sequence="ACGT", modification=None, create=True):
    return {"_proof_version": 1, "entries": [{"create": create, "extension": {
        "id": "terminal-extension", "strand_id": source.strands[0].id,
        "end": "three_prime", "sequence": sequence, "modification": modification, "label": "Tip"}}]}


def test_extension_creation_replacement_and_deletion_match_native(source):
    for kind, params in (("extension-upsert", _extension(source)),
            ("extension-upsert", _extension(source, sequence="TT", create=False)),
            ("extension-delete", {"_proof_version": 1, "extension_ids": ["terminal-extension"]})):
        expected = execute(kind, source.model_copy(deep=True), params)
        actual = preview._run(kind, source, params, lambda: None)
        assert actual.model_dump(mode="json") == expected.model_dump(mode="json")
        source = actual
    assert source.extensions == []


@pytest.mark.parametrize("sequence,modification", [("A" * 1025, None), ("A" * 500, "biotin")])
def test_extension_growth_is_charged_with_existing_sites_before_builder(source, monkeypatch, sequence, modification):
    monkeypatch.setattr(preview, "execute", _trap)
    with pytest.raises(CommandContractError) as caught:
        preview._run("extension-upsert", source, _extension(source, sequence=sequence, modification=modification), lambda: None)
    assert caught.value.code == "preview_limit"


def test_native_bound_to_unbound_restoration_matches_existing_executor():
    source = duplex_source(rooted=True, equal=True, binding=True)
    source = source.copy_with(overhang_bindings=[source.overhang_bindings[0].model_copy(update={
        "driver_oh_id": "oh-a", "driven_oh_id": "oh-b"})])
    bound = execute("overhang-bulk", source, {"_proof_version": 1,
        "action": "overhang-binding-patch", "binding_id": "binding", "bound": True})
    assert bound.overhang_bindings[0].prior_driven_topology
    params = {"_proof_version": 1, "action": "overhang-binding-patch", "binding_id": "binding", "bound": False}
    expected = execute("overhang-bulk", bound.model_copy(deep=True), params)
    actual = preview._run("overhang-bulk", bound, params, lambda: None)
    assert actual.model_dump(mode="json") == expected.model_dump(mode="json")
    assert not actual.overhang_bindings[0].bound
    assert actual.find_helix("b") is not None


def _insertion_heavy_source(*, grow_tip=False):
    # Hostile repeated occupancy/insert descriptors are intentional: admission
    # must count every native visit before any builder can reach later display
    # validity checks. This is not a valid-molecular-geometry qualification.
    from backend.core import models as m
    source = duplex_source(rooted=True, equal=True, binding=True)
    driver = source.find_helix("a").model_copy(update={
        "loop_skips": [m.LoopSkip(bp_index=0, delta=1) for _ in range(200)]})
    helices = [driver if h.id == "a" else h for h in source.helices]
    if grow_tip:
        helices = [h.model_copy(update={"length_bp": 9,
            "loop_skips": [m.LoopSkip(bp_index=8, delta=1) for _ in range(200)]}) if h.id == "b" else h
            for h in helices]
    template = source.find_strand("st-a").domains[-1]
    extras = [m.Strand(id=f"repeated-visit-{i}", strand_type=m.StrandType.STAPLE,
        domains=[template.model_copy()]) for i in range(3)]
    return source.copy_with(helices=helices, strands=[*source.strands, *extras],
        overhang_bindings=[source.overhang_bindings[0].model_copy(update={
            "driver_oh_id": "oh-a", "driven_oh_id": "oh-b"})])


def test_binding_relocation_charges_new_driver_loop_copies_before_native(monkeypatch):
    source = _insertion_heavy_source()
    preview._work(source, lambda: None)
    monkeypatch.setattr(preview, "execute", _trap)
    with pytest.raises(CommandContractError) as caught:
        preview._run("overhang-bulk", source, {"_proof_version": 1,
            "action": "overhang-binding-patch", "binding_id": "binding", "bound": True}, lambda: None)
    assert caught.value.code == "preview_limit"


def test_free_end_resize_charges_newly_included_loop_copies_before_native(monkeypatch):
    source = _insertion_heavy_source(grow_tip=True)
    preview._work(source, lambda: None)
    monkeypatch.setattr(preview, "execute", _trap)
    with pytest.raises(CommandContractError) as caught:
        preview._run("overhang-bulk", source, {"_proof_version": 1,
            "action": "resize-free-end", "overhang_id": "oh-b", "end": "3p", "delta_bp": 1}, lambda: None)
    assert caught.value.code == "preview_limit"


@pytest.mark.parametrize("kind", ["duplex-patch", "duplex-delete"])
def test_bound_driver_switch_and_edge_delete_keep_exact_native_semantics(kind):
    from backend.api.part_duplex_commands import prepare_command
    from tests.test_part_duplex_commands import bound_source, params
    source = bound_source()
    values = prepare_command(kind, source, params(**({"driver": "right"} if kind == "duplex-patch" else {})))
    before = source.model_dump(mode="json")
    expected = execute(kind, source.model_copy(deep=True), values)
    actual = preview._run(kind, source, values, lambda: None)
    assert actual.model_dump(mode="json") == expected.model_dump(mode="json")
    assert source.model_dump(mode="json") == before
    if kind == "duplex-patch":
        assert actual.overhang_bindings[0].driver_oh_id == "oh-b"
        assert actual.overhang_bindings[0].prior_driven_topology["driven_oh_id"] == "oh-a"
    else:
        assert actual.overhang_bindings[0].bound
        assert actual.overhang_bindings[0].prior_driven_topology == source.overhang_bindings[0].prior_driven_topology
        assert actual.find_helix("b") is None  # Edge deletion is not native unbinding.
