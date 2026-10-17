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
from backend.core.part_history_contract import create_empty_part
from tests.test_part_pending_connection_versions import (
    CREATE, append, authored, creation, proof,
    native_prefix as native_prefix,
)


ACTION = "connection-version-apply-linker"
FINITE_TYPES = [f"{attach}-{material}dna-linker"
                for attach in ("root-to-root", "root-to-end", "end-to-root", "end-to-end")
                for material in ("ss", "ds")]


@pytest.fixture(scope="module")
def application_prefix(native_prefix):
    # The unchanged sequence patch currently resizes an extruded OH's entire
    # host. Use an explicit existing native input to give each selected OH its
    # own host; never patch generated coordinates or model a fictitious anchor.
    current = create_empty_part("Dedicated linker application", "HONEYCOMB")
    for entry in native_prefix.feature_log:
        params = deepcopy(entry.params)
        if entry.op_kind == "overhang-extrude":
            params["reuse_existing_helix"] = False
        current = append(current, entry.op_kind, params, entry.id)
    return current


@pytest.fixture
def source(application_prefix):
    return application_prefix.model_copy(deep=True)


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
        routes._apply_connection_version_legacy(params["version_id"])
    assert len(captured) == 1
    return captured[0]


def test_dedicated_host_fixture_is_recreated_by_actual_native_input(source):
    assert len({item.helix_id for item in source.overhangs}) == 2
    assert all(entry.params["reuse_existing_helix"] is False
               for entry in source.feature_log if entry.op_kind == "overhang-extrude")
    result = proof(source)
    assert result["status"] == "verified", result
    assert result["checked_commands"] == 3


def test_shared_overhang_host_refuses_before_legacy_sequence_resize(native_prefix):
    source = _pending(native_prefix.model_copy(deep=True))
    assert len({item.helix_id for item in source.overhangs}) == 1
    before = source.model_dump_json()
    with pytest.raises(CommandContractError) as caught:
        _build(source, _params(source))
    assert caught.value.code == "unsupported_connection_application_source"
    assert source.model_dump_json() == before


@pytest.mark.parametrize("change", ["larger_host", "additional_owner"])
def test_partial_or_multiply_owned_host_refuses_before_sequence_patch(source, monkeypatch, change):
    from backend.api import overhang_patch
    source = _pending(source)
    selected = source.overhangs[0]
    if change == "larger_host":
        source = source.copy_with(helices=[item.model_copy(update={"length_bp": item.length_bp + 1})
            if item.id == selected.helix_id else item for item in source.helices])
    else:
        source = source.copy_with(overhangs=[*source.overhangs,
            selected.model_copy(update={"id": "second-host-owner", "sub_domains": []})])
    before = source.model_dump_json()

    def unexpected(*_args, **_kwargs):
        pytest.fail("Unsupported host reached the existing sequence patch")

    monkeypatch.setattr(overhang_patch, "_build_overhang_patch", unexpected)
    with pytest.raises(CommandContractError) as caught:
        _build(source, _params(source))
    assert caught.value.code == "unsupported_connection_application_source"
    assert source.model_dump_json() == before


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
    {"_proof_version": True}, {"connection_application_version": 3},
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


def _complement(source):
    from backend.core.lattice import _make_complement_domain
    selected = source.overhangs[0]
    backing = next(domain for strand in source.strands for domain in strand.domains
                   if domain.overhang_id == selected.id)
    return _make_complement_domain(backing, selected.id)


def _trap_sequence_patch(monkeypatch):
    from backend.api import overhang_patch

    def unexpected(*_args, **_kwargs):
        pytest.fail("Unsafe complement ownership reached the existing sequence patch")

    monkeypatch.setattr(overhang_patch, "_build_overhang_patch", unexpected)


@pytest.mark.parametrize("tagged", [False, True])
def test_retained_complement_occupant_refuses_before_native_sequence_patch(source, monkeypatch, tagged):
    from backend.core.models import Strand
    source = _pending(source)
    complement = _complement(source)
    if not tagged:
        complement = complement.model_copy(update={"binds_overhang_id": None})
    source = source.copy_with(strands=[*source.strands,
        Strand(id="retained-complement", domains=[complement])])
    before = source.model_dump_json()
    _trap_sequence_patch(monkeypatch)
    with pytest.raises(ReferenceResolutionError) as caught:
        _build(source, _params(source))
    assert caught.value.code == "invalid_selection"
    assert caught.value.references[0]["parameter_path"] == ["overhang_a_id"]
    assert source.model_dump_json() == before


@pytest.mark.parametrize("consumer", ["nucleotide_transform", "crossover", "forced_ligation"])
def test_dangling_complement_address_is_not_adopted_by_new_linker(source, monkeypatch, consumer):
    from backend.core.models import Crossover, ForcedLigation, HalfCrossover
    source = _pending(source)
    complement = _complement(source)
    other = source.strands[0].domains[0]
    if consumer == "nucleotide_transform":
        source = source.copy_with(nucleotide_transforms=[NucleotideTransform(
            id="unowned-address", kind="base", helix_id=complement.helix_id,
            bp_index=complement.start_bp, direction=complement.direction)])
    elif consumer == "crossover":
        source = source.copy_with(crossovers=[*source.crossovers, Crossover(id="unowned-address",
            half_a=HalfCrossover(helix_id=complement.helix_id,
                index=complement.start_bp, strand=complement.direction),
            half_b=HalfCrossover(helix_id=other.helix_id,
                index=complement.start_bp, strand=other.direction))])
    else:
        source = source.copy_with(forced_ligations=[*source.forced_ligations,
            ForcedLigation(id="unowned-address", three_prime_helix_id=complement.helix_id,
                three_prime_bp=complement.start_bp, three_prime_direction=complement.direction,
                five_prime_helix_id=other.helix_id, five_prime_bp=other.start_bp,
                five_prime_direction=other.direction)])
    before = source.model_dump_json()
    _trap_sequence_patch(monkeypatch)
    with pytest.raises(ReferenceResolutionError) as caught:
        _build(source, _params(source))
    assert caught.value.code == "invalid_selection"
    assert caught.value.references[0]["parameter_path"] == ["overhang_a_id"]
    assert source.model_dump_json() == before


def test_selected_domain_cluster_refuses_before_first_apply_not_after_reconciliation(source, monkeypatch):
    from backend.core.cluster_reconcile import reconcile_cluster_membership
    from backend.core.models import ClusterRigidTransform, DomainRef
    source = _pending(source)
    selected = source.overhangs[0]
    owner = next(strand for strand in source.strands if strand.id == selected.strand_id)
    index = next(i for i, domain in enumerate(owner.domains) if domain.overhang_id == selected.id)
    source = source.copy_with(cluster_transforms=[ClusterRigidTransform(id="domain-owner",
        helix_ids=[selected.helix_id], domain_ids=[DomainRef(strand_id=owner.id, domain_index=index)])])
    native, report = _legacy(source, _params(source), monkeypatch)
    reconciled = reconcile_cluster_membership(source, native, report)
    assert any(ref.strand_id == "__lnk__applied-linker__s"
               for cluster in reconciled.cluster_transforms for ref in cluster.domain_ids)
    before = source.model_dump_json()
    _trap_sequence_patch(monkeypatch)
    with pytest.raises(CommandContractError) as caught:
        _build(source, _params(source))
    assert caught.value.code == "unsupported_connection_application_source"
    assert source.model_dump_json() == before


def test_loop_work_is_charged_for_every_emitted_domain_not_two_assumed_occupants(source, monkeypatch):
    from backend.api import part_connection_application_commands as commands
    from backend.core.models import Domain, LoopSkip, Strand
    from backend.core.sequences import strand_sequence_length
    helix = source.helices[0].model_copy(update={"bp_start": 0, "length_bp": 1,
        "loop_skips": [LoopSkip(bp_index=0, delta=1)]})
    domain = Domain(helix_id=helix.id, start_bp=0, end_bp=0, direction=helix.direction)
    # Deliberately repeated occupancy is an admission input, not a valid native
    # design claim. Work accounting must not assume it was already validated.
    source = source.copy_with(helices=[helix], strands=[Strand(id="repeated",
        domains=[domain.model_copy(deep=True) for _ in range(3)])])
    assert strand_sequence_length(source, source.strands[0]) == 6
    monkeypatch.setattr(commands, "MAX_APPLICATION_BASES", 7)
    with pytest.raises(CommandContractError) as caught:
        commands._work_admission(source, bridge_length=1, complement_domains=[])
    assert caught.value.code == "unsupported_connection_application_source"


@pytest.mark.parametrize("retained", ["backing_pose", "unrelated_domain_cluster"])
def test_complement_guard_keeps_unaffected_authored_scopes_and_native_parity(source, monkeypatch, retained):
    from backend.core.models import ClusterRigidTransform, DomainRef
    source = _pending(source)
    if retained == "backing_pose":
        backing = next(domain for strand in source.strands for domain in strand.domains
                       if domain.overhang_id == source.overhangs[0].id)
        source = source.copy_with(nucleotide_transforms=[NucleotideTransform(id="backing-pose",
            kind="base", helix_id=backing.helix_id, bp_index=backing.start_bp,
            direction=backing.direction, translation=[1.0, 2.0, 3.0])])
    else:
        selected_hosts = {row.helix_id for row in source.overhangs}
        strand, index, domain = next((strand, i, domain) for strand in source.strands
            for i, domain in enumerate(strand.domains) if domain.helix_id not in selected_hosts)
        source = source.copy_with(cluster_transforms=[ClusterRigidTransform(id="unrelated-domain-owner",
            helix_ids=[domain.helix_id], domain_ids=[DomainRef(strand_id=strand.id, domain_index=index)])])
    before = source.model_dump_json()
    expected, expected_report = _legacy(source, _params(source), monkeypatch)
    actual, report = _build(source, _params(source))
    assert authored(actual) == authored(expected)
    assert report == expected_report
    assert source.model_dump_json() == before


def test_prospective_complement_loop_copies_are_charged_before_native_patching(source, monkeypatch):
    from backend.api import part_connection_application_commands as commands
    from backend.core.lattice import _make_complement_domain
    from backend.core.models import LoopSkip, Strand
    from backend.core.sequences import strand_nucleotide_count
    source = _pending(source)
    selected = source.overhangs[0]
    source = source.copy_with(helices=[helix.model_copy(update={"loop_skips": [
        LoopSkip(bp_index=helix.bp_start + 1, delta=1)]}) if helix.id == selected.helix_id
        else helix for helix in source.helices])
    complements = [_make_complement_domain(domain, domain.overhang_id)
        for strand in source.strands for domain in strand.domains
        if domain.overhang_id in {row.id for row in source.overhangs}]
    prospective = strand_nucleotide_count(Strand(id="prospective", domains=complements), source)
    plain_complements = sum(abs(domain.end_bp - domain.start_bp) + 1 for domain in complements)
    assert prospective == plain_complements + 1
    source_work = sum(strand_nucleotide_count(strand, source) for strand in source.strands)
    # Both old and prospective work use the existing native nucleotide counter
    # as the oracle. No geometry is evaluated and no solver budget is changed.
    monkeypatch.setattr(commands, "MAX_APPLICATION_BASES", source_work + 2 * 7 + prospective - 1)
    before = source.model_dump_json()
    _trap_sequence_patch(monkeypatch)
    with pytest.raises(CommandContractError) as caught:
        _build(source, _params(source))
    assert caught.value.code == "unsupported_connection_application_source"
    assert source.model_dump_json() == before


def test_repeated_insertion_descriptors_bound_native_arrays_and_prospective_domains(source, monkeypatch):
    from backend.api import part_connection_application_commands as commands
    from backend.core.geometry import nucleotide_positions_arrays
    from backend.core.models import Domain, LoopSkip, Strand
    helix = source.helices[0].model_copy(update={"bp_start": 0, "length_bp": 1,
        "loop_skips": [LoopSkip(bp_index=0, delta=1), LoopSkip(bp_index=0, delta=1)]})
    domain = Domain(helix_id=helix.id, start_bp=0, end_bp=0, direction=helix.direction)
    # Existing native geometry sums descriptors: three residues per direction,
    # even though the sequence map's last-wins result is only two.
    native_slots = len(nucleotide_positions_arrays(helix)["positions"]) // 2
    assert native_slots == 3
    source = source.copy_with(helices=[helix], strands=[Strand(id="occupied", domains=[domain])])
    monkeypatch.setattr(commands, "MAX_APPLICATION_BASES", 2 + 2 * native_slots - 1)
    with pytest.raises(CommandContractError):
        commands._work_admission(source, bridge_length=1, complement_domains=[domain])
    # Anchor arrays also include currently unoccupied residues. Do not infer
    # their cost only from emitted/occupied strand domains.
    monkeypatch.setattr(commands, "MAX_APPLICATION_BASES", native_slots)
    with pytest.raises(CommandContractError):
        commands._work_admission(source.copy_with(strands=[]), bridge_length=1, complement_domains=[])


def test_generated_identity_length_refuses_before_materialization(source, monkeypatch):
    source = _pending(source)
    before = source.model_dump_json()
    _trap_sequence_patch(monkeypatch)
    with pytest.raises(ValueError):
        _build(source, _params(source, connection_id="x" * 247))
    assert source.model_dump_json() == before


def test_maximum_generated_identity_remains_reapplicable(source):
    source = _pending(source)
    source, _ = _build(source, _params(source, connection_id="x" * 246))
    assert len(next(row.id for row in source.strands if row.id.startswith("__lnk__"))) == 256
    before = source.model_dump_json()
    reapplied, _ = _build(source, _params(source, connection_id="y" * 246))
    assert [row.id for row in reapplied.overhang_connections] == ["y" * 246]
    assert source.model_dump_json() == before


def test_output_cannot_enter_retained_connection_prefix_namespace(source, monkeypatch):
    from uuid import UUID
    from tests.conftest import valid_overhang_sites
    source = _pending(source)
    source, _ = _build(source, _params(source, connection_id="retained-owner"))
    original_ends = {row.id for row in source.overhangs}
    for i, five_prime in enumerate((False, True)):
        host_ids = {row.helix_id for row in source.overhangs}
        site = next(item for item in valid_overhang_sites(source)
                    if item["is_five_prime"] == five_prime and item["helix_id"] not in host_ids)
        source = append(source, "overhang-extrude", {"_proof_version": 1,
            "history_seed": str(UUID(int=9000 + i)), **site,
            "direction": site["direction"].value, "length_bp": 12,
            "reuse_existing_helix": False}, f"unrelated-endpoint-{i}")
    added = [row.id for row in source.overhangs if row.id not in original_ends]
    assert len(added) == 2
    source = append(source, CREATE, creation(source, version_id="unrelated-version",
        overhang_a_id=added[0], overhang_b_id=added[1]), "unrelated-pending")
    params = _params(source, version_id="unrelated-version", connection_id="retained-owner-child")
    assert params["conflict_connection_ids"] == []
    before = source.model_dump_json()
    _trap_sequence_patch(monkeypatch)
    with pytest.raises(ReferenceResolutionError) as caught:
        _build(source, params)
    assert caught.value.references[0]["parameter_path"] == ["connection_id"]
    assert source.model_dump_json() == before


def test_replacement_may_reuse_namespace_of_explicitly_removed_complete_owner(source):
    source = _pending(source)
    source, _ = _build(source, _params(source, connection_id="removed-owner"))
    params = _params(source, connection_id="removed-owner-child")
    assert params["conflict_connection_ids"] == ["removed-owner"]
    before = source.model_dump_json()
    replaced, _ = _build(source, params)
    assert [row.id for row in replaced.overhang_connections] == ["removed-owner-child"]
    assert not any(row.id == "__lnk__removed-owner" for row in replaced.helices)
    assert source.model_dump_json() == before
