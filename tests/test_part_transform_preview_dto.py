"""Private transform display preserves native geometry and complete control inputs.

These fixtures are owned models in memory, not a claim that every fixture's
historical producer is admitted by the separate prefix-replay service.
"""

from copy import deepcopy
from dataclasses import replace
import json

import pytest

from backend.core import deformation, design_geometry, models as m
from backend.core.part_command_errors import CommandContractError
from backend.core.part_overlay_commands import build, command_input
from backend.core.validator import ValidationReport
from tests.test_part_dna_comparison import small
from tests.test_part_transform_preview import FEATURE, source_recipe, service as previews
from tests.test_part_deformation_preview import owned_capture
from tests.test_part_connection_application_commands import application_prefix as application_prefix
from tests.test_part_pending_connection_versions import native_prefix as native_prefix, append


def dto():
    from backend.api import part_transform_preview_dto
    return part_transform_preview_dto


def projection():
    from backend.api import part_transform_projection
    return part_transform_projection


def moved(prefix, owner=None):
    from backend.api.part_transform_preview import EvaluatedTransform
    prefix = prefix.model_copy(deep=True)
    if not prefix.cluster_transforms:
        prefix.cluster_transforms = [m.ClusterRigidTransform(id="placement", helix_ids=[h.id for h in prefix.helices])]
    selected = next(c for c in prefix.cluster_transforms if c.id == owner) if owner else prefix.cluster_transforms[-1]
    row = m.ClusterOpLogEntry(id=FEATURE, cluster_id=selected.id, proof_version=1,
        translation=[1.5, -2.0, .25], rotation=[0, 0, .6, .8], pivot=[.1, .2, .3])
    _, params = command_input(row)
    candidate = build("cluster_op", prefix.model_copy(deep=True), params)
    return prefix, EvaluatedTransform(candidate, row, params, ValidationReport())


def native(design):
    records = design_geometry._geometry_for_design(design)
    axes = deformation.deformed_helix_axes(design)
    return records, deformation._apply_ovhg_rotations_to_axes(design, axes, records)


def assert_component(component, source):
    from backend.core.part_dna_comparison_codec import unpack_records
    records, axes = native(source)
    wire = json.loads(json.dumps(component, allow_nan=False))
    assert (unpack_records(wire["nucleotides"]) if wire["component_version"] == 2 else wire["nucleotides"]) == records
    assert wire["helix_axes"] == axes
    assert wire["component_kind"] == "transform-preview-dna"
    assert wire["component_version"] in {1, 2}
    assert wire["representation"] == "native-full-v1" and wire["units"] == "nm"


def test_compact_delta_is_exact_and_bound_to_validated_lease_rows():
    prefix, evaluated = moved(small())
    cache = {}
    preparation = dto().prepare_display(prefix, evaluated, envelope={"lease_id": "owned"}, display_cache=cache)
    full = dto().evaluate_display(prefix, evaluated, envelope={"lease_id": "owned"})
    delta = dto().evaluate_display(prefix, evaluated, envelope={"lease_id": "owned"}, display_cache=cache)
    assert delta["candidate"]["nucleotides"].pop("rows_ref") == "owned"
    delta["candidate"]["nucleotides"]["rows"] = cache["rows"]
    assert delta == full
    preparation["before"]["nucleotides"]["rows"][0][0] = "mutated-response"
    assert cache["rows"] == full["candidate"]["nucleotides"]["rows"]
    wrong_lease = dto().evaluate_display(prefix, evaluated, envelope={"lease_id": "other"}, display_cache=cache)
    assert "rows" in wrong_lease["candidate"]["nucleotides"]
    cache["rows"][0][0] = "different-ownership"
    assert dto().evaluate_display(prefix, evaluated, envelope={"lease_id": "owned"}, display_cache=cache) == full
    assert dto().evaluate_display(prefix, evaluated, include_geometry=False,
        envelope={"lease_id": "owned"}, display_cache=cache)["candidate"] is None


@pytest.mark.parametrize("kind,extra", [("cluster_op", False), ("nucleotide-transform", False),
    ("nucleotide-transform-batch", False), ("nucleotide-transform-delete", False),
    ("nucleotide-transform", True), ("nucleotide-transform-batch", True),
    ("nucleotide-transform-delete", True)])
def test_real_owned_transform_outputs_match_native_geometry_and_input_controls(kind, extra):
    source = source_recipe(kind, extra=extra)
    prepared = previews().prepare_from_capture(owned_capture(source), FEATURE)
    prefix, evaluated = prepared.copy_prefix(), previews().evaluate(prepared, {})
    before = prefix.model_dump_json(), evaluated.design.model_dump_json(), deepcopy(evaluated.params)
    packet = dto().prepare_display(prefix, evaluated)
    assert_component(packet["before"], prefix)
    assert_component(packet["candidate"], evaluated.design)
    assert packet["control_context"]["inputs"] == evaluated.params
    assert packet["control_state"]["inputs"] == evaluated.params
    assert packet["stage"] == "feature" and packet["projection_version"] == 1
    assert all(packet[key] is False for key in
        ("source_equivalence_checked", "downstream_evaluated", "physical_validity"))
    assert packet["command_kind"] == kind and packet["feature_id"] == FEATURE
    assert "deformation_id" not in packet
    topology = packet["candidate"]["display_topology"]
    assert topology["nucleotide_transforms"] == [v.model_dump(mode="json") for v in evaluated.design.nucleotide_transforms]
    if extra:
        assert any(item["extra_bases"] for item in topology["crossovers"])
    packet["control_state"]["inputs"].clear()
    packet["before"]["nucleotides"].clear()
    assert before == (prefix.model_dump_json(), evaluated.design.model_dump_json(), evaluated.params)


@pytest.mark.parametrize("variant", ["loops", "tails", "reference", "child", "frame", "overhang", "subdomain", "sweep"])
def test_complete_ordinary_native_record_and_axis_variants(variant):
    source = small(variant)
    original = source.model_dump_json()
    assert_component(projection().project(source), source)
    assert source.model_dump_json() == original


def test_empty_frame_owner_parent_local_and_overlapping_placements_keep_order_and_poses():
    prefix = small("child")
    prefix.cluster_transforms.insert(0, m.ClusterRigidTransform(id="empty-frame", translation=[9, 2, 3]))
    prefix.lattice_frames = [m.LatticeFrame(id="empty-frame-ref", placement_cluster_id="empty-frame")]
    prefix, evaluated = moved(prefix, "child")
    result = dto().prepare_display(prefix, evaluated)
    expected = [item.model_dump(mode="json") for item in evaluated.design.cluster_transforms]
    assert result["control_state"]["cluster_transforms"] == expected
    assert result["candidate"]["display_topology"]["cluster_transforms"] == expected
    assert result["control_context"]["lattice_frames"] == [item.model_dump(mode="json") for item in prefix.lattice_frames]
    assert result["control_context"]["cluster_transforms"] == [c.model_dump(mode="json") for c in prefix.cluster_transforms]


def test_joints_and_constraint_controls_are_native_and_available_without_visual_geometry(monkeypatch):
    from backend.api.crud import _inject_joint_world_axes
    from backend.core.flexible_segments import all_cluster_gates
    prefix = small("child")
    prefix.cluster_joints = [m.ClusterJoint(id="joint", cluster_id="child", local_axis_origin=[2, 1, 0],
        local_axis_direction=[0, 1, 0], min_angle_deg=-25, max_angle_deg=75)]
    prefix, evaluated = moved(prefix, "child")
    expected = {"cluster_transforms": [c.model_dump(mode="json") for c in evaluated.design.cluster_transforms],
                "cluster_joints": [j.model_dump(mode="json") for j in evaluated.design.cluster_joints]}
    _inject_joint_world_axes(expected)
    monkeypatch.setattr(design_geometry, "_geometry_for_design", lambda *_a, **_k: pytest.fail("ordinary controls derive no nucleotide arrays"))
    packet = dto().evaluate_display(prefix, evaluated, include_geometry=False)
    assert packet["candidate"] is None
    assert packet["control_state"]["cluster_joints"] == expected["cluster_joints"]
    assert packet["control_state"]["frame_provenance"]["joint_axes"]["joint"] == {
        "method": "native-owner-transform", "owner_id": "child", "parent_cluster_id": "parent", "parent_composed": False}
    assert packet["control_state"]["flexible_gates"] == all_cluster_gates(evaluated.design)
    assert packet["control_state"]["inputs"] == evaluated.params
    assert "control_context" not in packet and "before" not in packet


@pytest.mark.parametrize("modification", [None, "cy3"])
def test_extensions_and_modification_records_are_preserved_without_synthetic_slab_fields(modification):
    source = small()
    source.extensions = [m.StrandExtension(id="extension", strand_id="stap", end="three_prime", sequence="AT", modification=modification)]
    result = projection().project(source)
    assert_component(result, source)
    extensions = [n for n in result["nucleotides"] if n.get("extension_id") == "extension"]
    assert len(extensions) == 2 + bool(modification)
    assert all(n["slab_position"] is None and n["slab_quaternion"] is None for n in extensions)
    assert result["display_topology"]["extensions"] == [source.extensions[0].model_dump(mode="json")]


def cpd_source(*, incomplete=False):
    from backend.core.atomistic import _SUGAR, _DT_BASE
    source = small()
    atoms = {name: list(xyz) for name, _, *xyz in (*_SUGAR, *_DT_BASE)}
    if incomplete:
        atoms.pop("O5'")
    keys = ("h0:3:FORWARD", "h0:4:FORWARD")
    source.photoproduct_junctions = [m.PhotoproductJunction(id="cpd", base_key_1=keys[0], base_key_2=keys[1],
        design_coordinates={key: deepcopy(atoms) for key in keys})]
    return source


def test_cpd_native_landmarks_and_exact_extra_pose_inputs_are_not_omitted():
    from backend.core.cpd_representation import inject_cpd_representation
    source = cpd_source()
    expected = {"photoproduct_junctions": [source.photoproduct_junctions[0].model_dump(mode="json", exclude={"bond_relaxation"})]}
    inject_cpd_representation(expected)
    before = source.model_dump_json()
    result = projection().project(source)
    assert result["display_topology"]["photoproduct_junctions"] == expected["photoproduct_junctions"]
    assert source.model_dump_json() == before


def test_incomplete_cpd_landmarks_refuse_instead_of_empty_display_fallback():
    with pytest.raises(CommandContractError) as caught:
        projection().project(cpd_source(incomplete=True))
    assert caught.value.code == "invalid_preview_geometry"


@pytest.mark.parametrize("field", ["protein_assets", "protein_attachments", "nanoparticles", "nanoparticle_conjugations", "nanoparticle_connection_versions"])
def test_unsupported_whole_scope_refuses_before_geometry(field, monkeypatch):
    source = small().model_copy(update={field: [object()]})
    monkeypatch.setattr(design_geometry, "_geometry_for_design", lambda *_: pytest.fail("unsupported scope allocated geometry"))
    with pytest.raises(CommandContractError) as caught:
        projection().project(source)
    assert caught.value.code == "unsupported_transform_display" and field in str(caught.value)


@pytest.mark.parametrize("damage", ["remote_span", "loop_expansion", "missing_member", "ambiguous_helix"])
def test_preallocation_work_and_references_are_checked(damage, monkeypatch):
    source = small("child")
    if damage == "remote_span":
        source.strands[0].domains[0].end_bp = 100_000
    elif damage == "loop_expansion":
        source.helices[0].loop_skips = [m.LoopSkip(bp_index=3, delta=100_000)]
    elif damage == "missing_member":
        source.cluster_transforms[-1].domain_ids[0].domain_index = 99
    else:
        source.helices.append(source.helices[0].model_copy(deep=True))
    before = source.model_dump_json()
    monkeypatch.setattr(design_geometry, "_geometry_for_design", lambda *_: pytest.fail("invalid source allocated geometry"))
    with pytest.raises(CommandContractError) as caught:
        projection().project(source)
    assert caught.value.code in {"preview_limit", "invalid_preview_reference"}
    assert source.model_dump_json() == before


def envelope():
    return {"family": "transform", "command_kind": "cluster_op", "feature_id": FEATURE,
        "preview_id": "nonce", "lease_id": "lease", "doc_id": "document", "expected_design_id": "design",
        "expected_revision": 2, "request_sequence": 3, "remaining_seconds": 60.0}


def test_whole_envelope_is_bounded_once_and_returned_without_alias(monkeypatch):
    prefix, evaluated = moved(small())
    values = {**envelope(), "expected_design_id": prefix.id}
    seen = []
    original = dto()._bounded
    def checked(packet):
        assert packet["lease_id"] == "lease"
        seen.append(packet)
        return original(packet)
    monkeypatch.setattr(dto(), "_bounded", checked)
    result = dto().evaluate_display(prefix, evaluated, include_geometry=False, envelope=values)
    assert seen == [result]
    values["lease_id"] = "changed"
    assert result["lease_id"] == "lease" and "deformation_id" not in result


@pytest.mark.parametrize("patch", [{"candidate": None}, {"deformation_id": "wrong-family"},
    {"family": "sweep"}, {"command_kind": "nucleotide-transform"}, {"feature_id": "other"},
    {"expected_revision": True}, {"remaining_seconds": float("inf")}])
def test_envelope_is_closed_scalar_and_cannot_relabel_output(patch):
    prefix, evaluated = moved(small())
    with pytest.raises(CommandContractError):
        dto().evaluate_display(prefix, evaluated, include_geometry=False, envelope={**envelope(), **patch})


def test_output_limit_includes_envelope_and_controls(monkeypatch):
    prefix, evaluated = moved(small())
    monkeypatch.setattr(dto(), "MAX_OUTPUT_BYTES", 128)
    with pytest.raises(CommandContractError) as caught:
        dto().evaluate_display(prefix, evaluated, include_geometry=False,
                               envelope={**envelope(), "expected_design_id": prefix.id})
    assert caught.value.code == "preview_limit"


def test_flag_and_evaluation_identity_are_strict():
    prefix, evaluated = moved(small())
    for value in (0, "false", None):
        with pytest.raises(CommandContractError):
            dto().evaluate_display(prefix, evaluated, include_geometry=value)
    with pytest.raises(CommandContractError):
        dto().evaluate_display(prefix, replace(evaluated, source_equivalence_checked=True))


def test_missing_native_record_never_returns_partial_component(monkeypatch):
    source = small()
    original = design_geometry._geometry_for_design
    monkeypatch.setattr(design_geometry, "_geometry_for_design", lambda value: original(value)[1:])
    with pytest.raises(CommandContractError) as caught:
        projection().project(source)
    assert caught.value.code == "invalid_preview_geometry"


def test_native_duplex_driver_pivots_tethers_and_links_match_complete_controls(application_prefix):
    from backend.core.duplex_cluster import duplex_cluster_rotation_points, duplex_cluster_tethers
    from backend.core.connection_tethers import cluster_connection_tethers, cluster_movable_links
    first, second = application_prefix.overhangs[:2]
    source = append(application_prefix, "duplex-connect", {
        "_proof_version": 1, "history_seed": "212cb729-37fa-49e4-bb35-c6a0cbd2cd2e",
        "duplex_id": "display-duplex", "created_at": 4.0,
        "overhang_a_id": first.id, "overhang_b_id": second.id, "binding_ids": [],
    }, "display-duplex-connect")
    child = next(c for c in source.cluster_transforms if c.overhang_duplex_driver_id)
    prefix, evaluated = moved(source, child.id)
    before = prefix.model_dump_json(), evaluated.design.model_dump_json()
    packet = dto().evaluate_display(prefix, evaluated, include_geometry=False)
    expected = []
    for owner in evaluated.design.cluster_transforms:
        expected.append({"cluster_id": owner.id,
            "rotation_points": duplex_cluster_rotation_points(evaluated.design, owner) if owner.overhang_duplex_driver_id else [],
            "tethers": (duplex_cluster_tethers(evaluated.design, owner) if owner.overhang_duplex_driver_id
                        else cluster_connection_tethers(evaluated.design, owner)),
            "movable_links": [] if owner.overhang_duplex_driver_id else cluster_movable_links(evaluated.design, owner)})
    assert packet["control_state"]["placement_constraints"] == expected
    assert len(next(item for item in expected if item["cluster_id"] == child.id)["rotation_points"]) == 3
    assert packet["control_state"]["frame_provenance"]["rotation_points"][child.id] == {
        "frame": "native-rest-with-placement-poses-removed"}
    assert packet["candidate"] is None
    assert before == (prefix.model_dump_json(), evaluated.design.model_dump_json())
    assert_component(projection().project(evaluated.design), evaluated.design)


def flexible_source():
    from backend.core.flexible_segments import apply_marks
    source = small()
    source.strands = [m.Strand(id="flex", strand_type=m.StrandType.SCAFFOLD, domains=[
        m.Domain(helix_id="h0", start_bp=0, end_bp=3, direction=m.Direction.FORWARD),
        m.Domain(helix_id="h0", start_bp=4, end_bp=7, direction=m.Direction.FORWARD),
        m.Domain(helix_id="h0", start_bp=8, end_bp=11, direction=m.Direction.FORWARD)])]
    source.cluster_transforms = [m.ClusterRigidTransform(id="a", domain_ids=[m.DomainRef(strand_id="flex", domain_index=0)]),
                                 m.ClusterRigidTransform(id="b", domain_ids=[m.DomainRef(strand_id="flex", domain_index=2)])]
    source.flexible_segment_marks = [m.FlexibleSegmentMark(id=f"mark-{bp}", strand_id="flex", domain_index=1,
        bp_index=bp, direction=m.Direction.FORWARD) for bp in range(4, 8)]
    return apply_marks(source)


def test_native_flexible_records_connections_and_gates_are_preserved():
    from backend.core.flexible_segments import all_cluster_gates
    source = flexible_source()
    assert len(source.flexible_connections) == 1, "native fixture must contain an actual derived tether"
    prefix, evaluated = moved(source)
    result = dto().prepare_display(prefix, evaluated)
    assert_component(result["candidate"], evaluated.design)
    assert any(record["is_flexible_segment"] for record in result["candidate"]["nucleotides"])
    expected = [connection.model_dump(mode="json") for connection in evaluated.design.flexible_connections]
    assert result["candidate"]["display_topology"]["flexible_connections"] == expected
    assert result["control_state"]["flexible_connections"] == expected
    assert result["control_state"]["flexible_gates"] == all_cluster_gates(evaluated.design)
    assert "flexible-arcs" in result["candidate"]["required_renderers"]


def test_flexible_axis_exclusion_does_not_hide_missing_rigid_axis_segment(monkeypatch):
    source = flexible_source()
    original = deformation.deformed_helix_axes
    def missing(design):
        result = original(design)
        assert len(result[0]["segments"]) == 2
        result[0]["segments"].pop()
        return result
    monkeypatch.setattr(deformation, "deformed_helix_axes", missing)
    with pytest.raises(CommandContractError) as caught:
        projection().project(source)
    assert caught.value.code == "invalid_preview_geometry"


def test_repeated_control_work_is_admitted_before_native_helpers(monkeypatch):
    from backend.core import flexible_segments
    prefix, evaluated = moved(small())
    monkeypatch.setattr(dto(), "MAX_CONTROL_WORK", 1)
    monkeypatch.setattr(flexible_segments, "all_cluster_gates", lambda *_: pytest.fail("unadmitted control helper"))
    with pytest.raises(CommandContractError) as caught:
        dto().evaluate_display(prefix, evaluated, include_geometry=False)
    assert caught.value.code == "preview_limit"


def test_shared_extra_base_namespace_collision_refuses_before_geometry(monkeypatch):
    source = small("crossover")
    source.forced_ligations = [m.ForcedLigation(id=source.crossovers[0].id, three_prime_helix_id="h0", three_prime_bp=11,
        three_prime_direction=m.Direction.FORWARD, five_prime_helix_id="h0", five_prime_bp=11,
        five_prime_direction=m.Direction.REVERSE, extra_bases="TT")]
    monkeypatch.setattr(design_geometry, "_geometry_for_design", lambda *_: pytest.fail("ambiguous extra-base namespace"))
    with pytest.raises(CommandContractError) as caught:
        projection().project(source)
    assert caught.value.code == "invalid_preview_reference"


@pytest.mark.parametrize("material", ["ss", "ds"])
def test_actual_native_linker_records_and_companion_topology_are_complete(application_prefix, material):
    from tests.test_part_connection_application_commands import _pending, _params, _build
    # These source OHs have opposite terminal polarity. The native root-to-end
    # DS input creates antiparallel bridge halves; root-to-root remains the
    # separately asserted refused native mixed-polarity case below.
    pending = _pending(application_prefix.model_copy(deep=True), f"root-to-end-{material}dna-linker")
    source, _ = _build(pending, _params(pending))
    original = source.model_dump_json()
    result = projection().project(source)
    assert_component(result, source)
    assert result["display_topology"]["overhang_connections"] == [c.model_dump(mode="json") for c in source.overhang_connections]
    if material == "ss":
        assert "ss-linker-arcs" in result["required_renderers"]
    else:
        assert any(n["helix_id"].startswith("__lnk__") for n in result["nucleotides"])
        assert {d.direction for strand in source.strands for d in strand.domains
                if d.helix_id.startswith("__lnk__")} == {m.Direction.FORWARD, m.Direction.REVERSE}
    assert source.model_dump_json() == original


def test_orphan_linker_owner_refuses_with_typed_reference_failure(monkeypatch):
    source = small()
    source.helices[0].id = "__lnk__missing"
    for strand in source.strands:
        strand.domains[0].helix_id = "__lnk__missing"
    monkeypatch.setattr(design_geometry, "_geometry_for_design", lambda *_: pytest.fail("orphan linker allocated geometry"))
    with pytest.raises(CommandContractError) as caught:
        projection().project(source)
    assert caught.value.code == "invalid_preview_reference"


def test_native_parallel_ds_bridge_is_explicitly_refused_not_silently_deduplicated(application_prefix, monkeypatch):
    from tests.test_part_connection_application_commands import _pending, _params, _build
    pending = _pending(application_prefix.model_copy(deep=True), "root-to-root-dsdna-linker")
    source, _ = _build(pending, _params(pending))
    domains = [d for strand in source.strands for d in strand.domains if d.helix_id.startswith("__lnk__")]
    assert len(domains) == 2 and domains[0].direction == domains[1].direction
    assert {domains[0].start_bp, domains[0].end_bp} == {domains[1].start_bp, domains[1].end_bp}
    before = source.model_dump_json()
    monkeypatch.setattr(design_geometry, "_geometry_for_design", lambda *_: pytest.fail("ambiguous native bridge projected"))
    with pytest.raises(CommandContractError) as caught:
        projection().project(source)
    assert caught.value.code == "invalid_preview_reference"
    assert source.model_dump_json() == before


def test_short_connection_control_traversals_are_charged_before_helpers(application_prefix, monkeypatch):
    from backend.core import connection_tethers, flexible_segments
    first, second = application_prefix.overhangs[:2]
    source = application_prefix.model_copy(deep=True)
    source.overhang_connections = [m.OverhangConnection(id=f"pending-{i}", overhang_a_id=first.id,
        overhang_b_id=second.id, overhang_a_attach="root", overhang_b_attach="root",
        linker_type="ss", length_value=0, length_unit="bp") for i in range(32)]
    prefix, evaluated = moved(source)
    # Native-residue work is small; repeated anchor/owner/domain traversals
    # would exceed this metadata allowance even for zero-length annotations.
    monkeypatch.setattr(dto(), "MAX_CONTROL_WORK", 1500)
    monkeypatch.setattr(flexible_segments, "all_cluster_gates", lambda *_: pytest.fail("unadmitted repeated control work"))
    monkeypatch.setattr(connection_tethers, "cluster_connection_tethers", lambda *_: pytest.fail("unadmitted connection traversal"))
    with pytest.raises(CommandContractError) as caught:
        dto().evaluate_display(prefix, evaluated, include_geometry=False)
    assert caught.value.code == "preview_limit"


def test_native_gate_cache_retains_pose_independence_order_and_ownership(monkeypatch):
    from backend.core import flexible_segments
    source = flexible_source()
    original = flexible_segments.all_cluster_gates
    calls = []
    def native_gates(design):
        calls.append(1)
        return original(design)
    monkeypatch.setattr(flexible_segments, "all_cluster_gates", native_gates)
    cache = {}
    def controls():
        result = dto()._controls(source, {}, lambda: None, cache)
        assert result["flexible_gates"] == original(source)
        return result
    controls()
    source.cluster_transforms[0].translation = [9, 2, 1]
    source.cluster_transforms[0].rotation = [0, 0, .6, .8]
    source.cluster_transforms[0].pivot = [1, 2, 3]
    controls()
    assert len(calls) == 1
    source.cluster_transforms.reverse()
    controls()
    source.cluster_transforms[0].helix_ids.append("h0")
    controls()
    source.flexible_segment_marks.pop()
    controls()
    source.cluster_transforms[0].is_default = True
    controls()
    assert len(calls) == 5


def test_gate_cache_is_lease_owned_and_not_changed_by_failed_packet(monkeypatch):
    from backend.core import flexible_segments
    prefix, evaluated = moved(small())
    cache = {}
    opened = dto().prepare_display(prefix, evaluated, envelope={"lease_id": "owned"}, display_cache=cache)
    expected = deepcopy(cache)
    opened["control_state"]["flexible_gates"].clear()
    assert cache == expected
    original = flexible_segments.all_cluster_gates
    calls = []
    def native_gates(design):
        calls.append(1)
        return original(design)
    monkeypatch.setattr(flexible_segments, "all_cluster_gates", native_gates)
    result = dto().evaluate_display(prefix, evaluated, include_geometry=False,
        envelope={"lease_id": "owned"}, display_cache=cache)
    assert calls == []
    result["control_state"]["flexible_gates"].clear()
    assert cache == expected
    dto().evaluate_display(prefix, evaluated, include_geometry=False,
        envelope={"lease_id": "different"}, display_cache=cache)
    assert len(calls) == 1 and cache == expected
    monkeypatch.setattr(dto(), "MAX_OUTPUT_BYTES", 1)
    with pytest.raises(CommandContractError):
        dto().evaluate_display(prefix, evaluated, include_geometry=False,
            envelope={"lease_id": "owned"}, display_cache=cache)
    assert cache == expected
