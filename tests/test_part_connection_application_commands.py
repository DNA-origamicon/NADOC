"""Tests-first finite ordinary-linker Apply contract, without route admission.

The old route callback is the molecular/topology oracle. Only its random
connection identity is injected; no coordinates or polarity are recreated here.
Registration, combined Connect and direct/indirect application are separate.
"""

from copy import deepcopy

from fastapi import HTTPException
import pytest

from backend.api import routes_connection_versions as routes
from backend.core.cluster_reconcile import MutationReport
from backend.core.models import NucleotideTransform, OverhangBinding
from backend.core.part_command_errors import CommandContractError, ReferenceResolutionError
from tests.test_part_pending_connection_versions import (
    CREATE, append, authored, creation,
    native_prefix as native_prefix,
    source as source,
)


ACTION = "connection-version-apply-linker"
FINITE_TYPES = [f"{attach}-{material}dna-linker"
                for attach in ("root-to-root", "root-to-end", "end-to-root", "end-to-end")
                for material in ("ss", "ds")]


def _pending(source, connection_type="root-to-root-ssdna-linker", **changes):
    return append(source, CREATE, creation(source, connection_type=connection_type,
        overhang_a_seq="ACGTACGTACGTAC", overhang_b_seq="TGCA", bridge_seq="GGNN",
        **changes), "pending-candidate")


def _params(design, *, version_id="candidate", connection_id="applied-linker"):
    version = next(item for item in design.connection_versions if item.id == version_id)
    selected = {version.overhang_a_id, version.overhang_b_id}
    return {"_proof_version": 1, "connection_application_version": 1, "action": ACTION,
        "version_id": version.id, "overhang_a_id": version.overhang_a_id,
        "overhang_b_id": version.overhang_b_id, "connection_type": version.connection_type,
        "connection_id": connection_id,
        "conflict_connection_ids": [item.id for item in design.overhang_connections
            if selected.intersection((item.overhang_a_id, item.overhang_b_id))],
        "conflict_version_ids": [item.id for item in design.connection_versions
            if selected.intersection((item.overhang_a_id, item.overhang_b_id))]}


def _build(design, params):
    # Keep collection and the existing-algorithm fixture controls runnable before
    # production exists; the red failure must identify the absent pure adapter.
    from backend.api.part_connection_application_commands import build
    return build(design, params)


def _legacy(design, params, monkeypatch):
    captured = []
    private = design.model_copy(deep=True)
    connection_model = routes.OverhangConnection

    def run_callback(*, fn, **_kwargs):
        value = fn(private)
        updated, report = value if isinstance(value, tuple) else (value, None)
        captured.append((updated, report))
        return updated, None, None

    with monkeypatch.context() as patch:
        patch.setattr(routes.design_state, "get_or_404", lambda: private)
        patch.setattr(routes.design_state, "mutate_with_feature_log", run_callback)
        patch.setattr(routes, "OverhangConnection", lambda **values:
                      connection_model(id=params["connection_id"], **values))
        patch.setattr(routes, "_design_response_with_geometry", lambda *_args, **_kwargs: {})
        routes._apply_connection_version_impl(params["version_id"])
    assert len(captured) == 1
    return captured[0]


@pytest.mark.parametrize("connection_type", [FINITE_TYPES[0], FINITE_TYPES[1]])
def test_existing_callback_oracle_materializes_real_native_prefix(source, monkeypatch, connection_type):
    source = _pending(source, connection_type)
    before = source.model_dump_json()
    result, report = _legacy(source, _params(source), monkeypatch)
    assert isinstance(report, MutationReport)
    assert report.new_helix_origins == {"__lnk__applied-linker": None}
    assert result.connection_versions[0].applied
    assert len(result.helices) == len(source.helices) + 1
    assert len(result.strands) == len(source.strands) + (2 if "dsdna" in connection_type else 1)
    assert source.model_dump_json() == before


@pytest.mark.parametrize("connection_type", FINITE_TYPES)
def test_finite_apply_exactly_matches_existing_callback_and_preserves_source(source, monkeypatch, connection_type):
    source = _pending(source, connection_type)
    values, before = _params(source), source.model_dump_json()
    expected, expected_report = _legacy(source, values, monkeypatch)
    actual, report = _build(source, values)
    assert authored(actual) == authored(expected)
    assert report == expected_report
    assert source.model_dump_json() == before
    assert actual.feature_log == source.feature_log
    assert actual.recipe_root == source.recipe_root
    assert _build(source, deepcopy(values))[0].model_dump_json() == actual.model_dump_json()


def test_stale_sequences_preserve_live_lengths_and_finite_zero_clamps_to_one(source, monkeypatch):
    source = _pending(source, bridge_length=0)
    actual, _ = _build(source, _params(source))
    expected, _ = _legacy(source, _params(source), monkeypatch)
    assert authored(actual) == authored(expected)
    version = actual.connection_versions[0]
    assert version.overhang_a_seq == "ACGTACGTACGT"
    assert version.overhang_b_seq == "TGCANNNNNNNN"
    assert actual.overhang_connections[0].length_value == 1
    assert next(h for h in actual.helices if h.id == "__lnk__applied-linker").length_bp == 1
    for original in source.overhangs:
        updated = next(item for item in actual.overhangs if item.id == original.id)
        assert sum(item.length_bp for item in updated.sub_domains) == sum(
            item.length_bp for item in original.sub_domains)


def test_sequenced_scaffolds_preserve_unrelated_manual_strand_sequence(source, monkeypatch):
    source = _pending(source, "end-to-end-dsdna-linker")
    unrelated = next(item for item in source.strands if not item.is_scaffold
                     and all(domain.overhang_id is None for domain in item.domains))
    source = source.copy_with(strands=[item.model_copy(update={"sequence":
        "A" * sum(abs(d.end_bp - d.start_bp) + 1 for d in item.domains)}) if item.is_scaffold
        else item.model_copy(update={"sequence": "TGCA"}) if item.id == unrelated.id else item
        for item in source.strands])
    actual, _ = _build(source, _params(source))
    expected, _ = _legacy(source, _params(source), monkeypatch)
    assert authored(actual) == authored(expected)
    assert next(item for item in actual.strands if item.id == unrelated.id).sequence == "TGCA"
    assert all(item.sequence for item in actual.strands if item.id.startswith("__lnk__applied-linker"))


def test_reapply_replaces_exact_existing_linker_and_preserves_pending_alternative(source, monkeypatch):
    source = _pending(source)
    applied, _ = _legacy(source, _params(source, connection_id="old-linker"), monkeypatch)
    alternative = applied.connection_versions[0].model_copy(update={
        "id": "alternative", "name": "V2", "applied": False})
    applied = applied.copy_with(connection_versions=[*applied.connection_versions, alternative])
    params = _params(applied)
    actual, report = _build(applied, params)
    expected, expected_report = _legacy(applied, params, monkeypatch)
    assert authored(actual) == authored(expected)
    assert report == expected_report
    assert [item.id for item in actual.overhang_connections] == ["applied-linker"]
    assert [item.applied for item in actual.connection_versions] == [True, False]
    assert not any(item.id.startswith("__lnk__old-linker") for item in [*actual.helices, *actual.strands])


@pytest.mark.parametrize("field,kind", [("version_id", "connection_version"),
    ("overhang_a_id", "overhang"), ("overhang_b_id", "overhang")])
def test_missing_inputs_have_exact_typed_repair_paths(source, field, kind):
    source = _pending(source)
    params = _params(source)
    if field == "version_id":
        source = source.copy_with(connection_versions=[])
    else:
        source = source.copy_with(overhangs=[item for item in source.overhangs if item.id != params[field]])
    before = source.model_dump_json()
    with pytest.raises(ReferenceResolutionError) as caught:
        _build(source, params)
    assert caught.value.code == "missing_reference"
    assert caught.value.as_issue()["references"] == [{
        "kind": kind, "identity": params[field], "parameter_path": [field],
    }]
    assert source.model_dump_json() == before


@pytest.mark.parametrize("field", ["conflict_connection_ids", "conflict_version_ids"])
def test_changed_conflict_set_refuses_instead_of_consuming_new_topology(source, monkeypatch, field):
    source = _pending(source)
    source, _ = _legacy(source, _params(source, connection_id="old-linker"), monkeypatch)
    params, before = _params(source), source.model_dump_json()
    params[field] = []
    with pytest.raises(ReferenceResolutionError) as caught:
        _build(source, params)
    assert caught.value.code == "invalid_selection"
    assert caught.value.as_issue()["references"][0]["parameter_path"][0] == field
    assert source.model_dump_json() == before


@pytest.mark.parametrize("owner", ["helix", "strand"])
def test_generated_output_identity_cannot_adopt_existing_owners(source, owner):
    source = _pending(source)
    if owner == "helix":
        source = source.copy_with(helices=[*source.helices,
            source.helices[0].model_copy(update={"id": "__lnk__applied-linker"})])
    else:
        source = source.copy_with(strands=[*source.strands,
            source.strands[0].model_copy(update={"id": "__lnk__applied-linker__s"})])
    before = source.model_dump_json()
    with pytest.raises(ReferenceResolutionError) as caught:
        _build(source, _params(source))
    assert caught.value.code == "invalid_selection"
    assert source.model_dump_json() == before


@pytest.mark.parametrize("unsafe", ["prefix_collision", "incoming_nucleotide_pose"])
def test_removed_linker_requires_complete_ownership_closure(source, monkeypatch, unsafe):
    source = _pending(source)
    source, _ = _legacy(source, _params(source, connection_id="old-linker"), monkeypatch)
    bridge = next(item for item in source.helices if item.id == "__lnk__old-linker")
    if unsafe == "prefix_collision":
        source = source.copy_with(helices=[*source.helices,
            bridge.model_copy(update={"id": "__lnk__old-linker-other"})])
    else:
        source = source.copy_with(nucleotide_transforms=[NucleotideTransform(
            id="retained-pose", kind="base", helix_id=bridge.id, bp_index=0,
            direction=source.strands[0].domains[0].direction)])
    before = source.model_dump_json()
    with pytest.raises(ReferenceResolutionError) as caught:
        _build(source, _params(source))
    assert caught.value.code == "invalid_selection"
    assert source.model_dump_json() == before


def test_overlapping_binding_refuses_without_reverting_saved_topology(source):
    source = _pending(source)
    a, b = source.overhangs
    source = source.copy_with(overhang_bindings=[OverhangBinding(id="bound-owner", name="B1",
        created_at=12.0, sub_domain_a_id=a.sub_domains[0].id, sub_domain_b_id=b.sub_domains[0].id,
        overhang_a_id=a.id, overhang_b_id=b.id, bound=True)])
    before = source.model_dump_json()
    with pytest.raises(CommandContractError):
        _build(source, _params(source))
    assert source.model_dump_json() == before


def test_existing_subdomain_override_conflict_remains_failure_atomic(source):
    source = _pending(source)
    a, b = source.overhangs
    a = a.model_copy(update={"sub_domains": [a.sub_domains[0].model_copy(update={"sequence_override": "A" * 12})]})
    source = source.copy_with(overhangs=[a, b])
    before = source.model_dump_json()
    with pytest.raises((HTTPException, CommandContractError)):
        _build(source, _params(source))
    assert source.model_dump_json() == before


@pytest.mark.parametrize("oversize", ["selected_helix", "prospective_bridge"])
def test_work_bounds_refuse_before_native_geometry(source, monkeypatch, oversize):
    from backend.core import lattice
    source = _pending(source, bridge_length=50_000 if oversize == "prospective_bridge" else 7)
    if oversize == "selected_helix":
        identity = source.overhangs[0].helix_id
        source = source.copy_with(helices=[item.model_copy(update={"length_bp": 50_001})
            if item.id == identity else item for item in source.helices])
    before = source.model_dump_json()

    def unexpected(*_args, **_kwargs):
        pytest.fail("Out-of-budget Apply reached native linker geometry")

    monkeypatch.setattr(lattice, "generate_linker_topology", unexpected)
    with pytest.raises(ValueError):
        _build(source, _params(source))
    assert source.model_dump_json() == before


@pytest.mark.parametrize("change", [
    {"_proof_version": True}, {"connection_application_version": 2},
    {"action": "connection-version-apply-direct"}, {"connection_id": ""},
    {"connection_type": "root-to-root"}, {"connection_type": "root-to-root-indirect"},
    {"conflict_connection_ids": ["repeated", "repeated"]},
    {"prior_driven_topology": {}}, {"points_nm": [[0, 0, 0]]}, {"saved_design": {}},
])
def test_contract_is_closed_and_never_accepts_direct_or_opaque_geometry(source, change):
    from backend.api.part_connection_application_commands import parse_command
    source = _pending(source)
    with pytest.raises(ValueError):
        parse_command({**_params(source), **change})
