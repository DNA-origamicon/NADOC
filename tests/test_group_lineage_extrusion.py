"""Native extrusion follows old entities without inheriting placement membership.

All fixtures and proof results remain in memory. The ordinary native executor
with the organization wrapper removed is the model/geometry parity oracle; the
membership assertions below use explicit fixture branches, not the lineage
implementation. No active document, worker, simulation or artifact is created.
"""

from uuid import UUID

import pytest

from backend.api.part_proof_commands import dependencies, execute
from backend.core import lattice, models as m
from backend.core.constants import BDNA_RISE_PER_BP as RISE
from backend.core.deformation import deformed_frame_at_bp, deformed_helix_axes
from backend.core.design_geometry import _geometry_for_design
from backend.core.part_command_errors import CommandContractError


SEED = "2345ee56-bb57-44e7-8a2b-a3548a5d213b"
KINDS = ("extrude-segment", "circle-segment", "extrude-continuation",
         "extrude-deformed-continuation", "extrude-frame")


def source(*, posed=False, plane="XY"):
    design = lattice.make_bundle_design([(0, 0)], 21, plane=plane)
    return design.copy_with(cluster_transforms=[m.ClusterRigidTransform(
        id="placement", name="Original placement", helix_ids=[design.helices[0].id],
        translation=[4, -2, 3] if posed else [0, 0, 0],
        rotation=[0, 0, 0.6, 0.8] if posed else [0, 0, 0, 1])])


def strand_on(design, direction, helix_id=None):
    helix_id = helix_id or design.helices[0].id
    return next(s for s in design.strands if s.domains[0].helix_id == helix_id
                and s.domains[0].direction == direction)


def convert(design):
    current = execute("group-organize", design, {"_proof_version": 1,
        "expected_placement_ids": [c.id for c in design.cluster_transforms]})
    for identity, direction in (("forward", m.Direction.FORWARD),
                                ("forward-overlap", m.Direction.FORWARD),
                                ("reverse", m.Direction.REVERSE)):
        selected = strand_on(design, direction)
        current = execute("group-create", current, {"_proof_version": 1, "group": {
            "id": identity, "name": identity, "helix_ids": [design.helices[0].id],
            "domain_ids": [{"strand_id": selected.id, "domain_index": 0}],
            "color": "#abcdef", "opacity": 0.5}})
    return execute("group-create", current, {"_proof_version": 1, "group": {
        "id": "whole", "name": "Whole original helices",
        "helix_ids": [h.id for h in design.helices]}})


def group(design, identity):
    return next(g for g in design.group_organization.groups if g.id == identity)


def refs(design, identity):
    return [(r.strand_id, r.domain_index) for r in group(design, identity).domain_ids]


def selected(design, identity):
    strands = {s.id: s for s in design.strands}
    return [strands[sid].domains[index] for sid, index in refs(design, identity)]


def inputs(kind, **changes):
    params = {"_proof_version": 1, "history_seed": SEED,
              "cells": [[4, 4]], "plane": "XY", "length_bp": 7}
    if kind == "circle-segment":
        params.pop("length_bp")
        params["cell_lengths"] = [7]
    elif kind == "extrude-deformed-continuation":
        params.update(grid_origin=[0, 0, 0], axis_dir=[0, 0, 1],
                      frame_right=[1, 0, 0], frame_up=[0, 1, 0])
    params.update(changes)
    return params


def parity(design, kind, params):
    before = design.model_dump(mode="json")
    legacy = design.copy_with(group_organization=None)
    legacy_before = legacy.model_dump(mode="json")
    expected = execute(kind, legacy, params)
    result = execute(kind, design, params)
    assert result.model_dump(mode="json", exclude={"group_organization"}) == expected.model_dump(
        mode="json", exclude={"group_organization"})
    assert _geometry_for_design(result) == _geometry_for_design(expected)
    assert deformed_helix_axes(result) == deformed_helix_axes(expected)
    assert design.model_dump(mode="json") == before
    assert legacy.model_dump(mode="json") == legacy_before
    assert group(result, "whole").helix_ids == group(design, "whole").helix_ids
    assert refs(result, "forward-overlap") == refs(result, "forward")
    for old in design.group_organization.groups:
        assert group(result, old.id).model_dump(exclude={"helix_ids", "domain_ids"}) == old.model_dump(
            exclude={"helix_ids", "domain_ids"})
    return result


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("separate", [False, True])
def test_five_fresh_extrusions_preserve_old_selections_and_exact_native_output(kind, separate):
    design = convert(source(posed=True))
    result = parity(design, kind, inputs(kind, separate_fresh_extrusions=separate))
    old_ids = {h.id for h in design.helices}
    assert len(result.helices) == len(design.helices) + 1
    for name in ("forward", "reverse"):
        assert refs(result, name) == refs(design, name)
        assert selected(result, name) == selected(design, name)
    assert all(set(g.helix_ids) <= old_ids for g in result.group_organization.groups)


@pytest.mark.parametrize("backward,inplace", [(False, True), (False, False),
                                               (True, True), (True, False)])
@pytest.mark.parametrize("mixed", [False, True])
@pytest.mark.parametrize("ligate", [False, True])
def test_continuation_growth_detached_and_mixed_cells_keep_exact_old_ancestors(
        backward, inplace, mixed, ligate):
    design = convert(source(posed=True))
    old_helix = design.helices[0]
    result = parity(design, "extrude-continuation", inputs("extrude-continuation",
        cells=[[0, 0], [12, 12]] if mixed else [[0, 0]],
        length_bp=-7 if backward else 7, offset_nm=0 if backward else 21 * RISE,
        extend_inplace=inplace, ligate_adjacent=ligate))
    grows_old = backward or inplace  # Native backward continuation always grows in place.
    current = next(h for h in result.helices if h.id == old_helix.id)
    assert current.length_bp == (28 if grows_old else 21)
    assert current.bp_start == (-7 if backward else 0)
    assert len(result.helices) == 1 + int(mixed) + int(not grows_old)
    for name, direction in (("forward", m.Direction.FORWARD), ("reverse", m.Direction.REVERSE)):
        old_strand = strand_on(design, direction)
        expected_ordinal = int(not grows_old and direction == m.Direction.REVERSE)
        assert refs(result, name) == [(old_strand.id, expected_ordinal)]
        chosen, = selected(result, name)
        assert chosen.helix_id == old_helix.id and chosen.direction == direction
        assert (min(chosen.start_bp, chosen.end_bp), max(chosen.start_bp, chosen.end_bp)) == (
            (-7 if backward else 0), (27 if not backward and inplace else 20))
    fresh = {h.id for h in result.helices} - {old_helix.id}
    assert all(d.helix_id not in fresh for name in ("forward", "reverse") for d in selected(result, name))


@pytest.mark.parametrize("strand_filter", ["both", "scaffold", "staples"])
def test_gap_on_existing_helix_does_not_invent_domain_group_membership(strand_filter):
    design = convert(source())
    result = parity(design, "extrude-continuation", inputs("extrude-continuation",
        cells=[[0, 0]], offset_nm=28 * RISE, strand_filter=strand_filter,
        ligate_adjacent=False))
    assert len(result.helices) == 1 and result.helices[0].length_bp == 35
    for name in ("forward", "reverse"):
        assert refs(result, name) == refs(design, name)
        assert selected(result, name) == selected(design, name)
    fresh = [s for s in result.strands if s.id not in {s.id for s in design.strands}]
    assert len(fresh) == (2 if strand_filter == "both" else 1)
    assert all(d.helix_id == design.helices[0].id and
               (min(d.start_bp, d.end_bp), max(d.start_bp, d.end_bp)) == (28, 34)
               for s in fresh for d in s.domains)
    assert group(result, "whole").helix_ids == [design.helices[0].id]


@pytest.mark.parametrize("strand_filter", ["scaffold", "staples"])
def test_inplace_filter_extends_only_the_native_selected_strand_family(strand_filter):
    design = convert(source())
    result = parity(design, "extrude-continuation", inputs("extrude-continuation",
        cells=[[0, 0]], offset_nm=21 * RISE, strand_filter=strand_filter))
    for name, direction in (("forward", m.Direction.FORWARD), ("reverse", m.Direction.REVERSE)):
        old = strand_on(design, direction)
        extends = old.is_scaffold if strand_filter == "scaffold" else old.strand_type == "staple"
        domain, = selected(result, name)
        assert abs(domain.end_bp - domain.start_bp) + 1 == (28 if extends else 21)


@pytest.mark.parametrize("ligate", [False, True])
def test_adjacent_segment_ligation_shifts_ordinals_but_does_not_select_new_helix(ligate):
    design = convert(source())
    result = parity(design, "extrude-segment", inputs("extrude-segment",
        cells=[[0, 0]], offset_nm=21 * RISE, ligate_adjacent=ligate))
    assert len(result.helices) == 2
    for name, direction in (("forward", m.Direction.FORWARD), ("reverse", m.Direction.REVERSE)):
        old = strand_on(design, direction)
        assert refs(result, name) == [(old.id, int(ligate and direction == m.Direction.REVERSE))]
        assert selected(result, name) == [old.domains[0]]
    assert len(result.strands) == (2 if ligate else 4)


def test_pending_cycle_is_retained_during_actual_inplace_continuation():
    original = source()
    hid = original.helices[0].id
    original = original.copy_with(crossovers=[m.Crossover(id="pending", half_a=m.HalfCrossover(
        helix_id=hid, index=20, strand=m.Direction.FORWARD), half_b=m.HalfCrossover(
            helix_id=hid, index=0, strand=m.Direction.FORWARD))])
    design = convert(original)
    # Native retry seeds same-strand cycles, not arbitrary separate termini.
    # Extrusion extends this strand; it does not split the cycle as nick does.
    assert lattice._unligated_ids_inline(design) == {"pending"}
    result = parity(design, "extrude-continuation", inputs("extrude-continuation",
        cells=[[0, 0]], offset_nm=21 * RISE, extend_inplace=True, ligate_adjacent=False))
    assert result.crossovers == design.crossovers
    assert [s.id for s in result.strands] == [s.id for s in design.strands]
    assert refs(result, "forward") == refs(design, "forward")
    domain, = selected(result, "forward")
    assert (domain.start_bp, domain.end_bp) == (0, 27)


@pytest.mark.parametrize("backward", [False, True])
@pytest.mark.parametrize("recompute", [False, True])
def test_deformed_continuation_keeps_native_baked_and_recomputed_frames(backward, recompute):
    original = source(posed=True)
    original = original.copy_with(deformations=[m.DeformationOp(id="bend", type="bend",
        plane_a_bp=1, plane_b_bp=15, cluster_ids=["placement"],
        affected_helix_ids=[original.helices[0].id],
        params=m.BendParams(curvature_deg_per_bp=0.5, direction_deg=20))])
    design = convert(original)
    bp = 0 if backward else 21
    frame = deformed_frame_at_bp(design, bp, design.helices[0].id)
    params = inputs("extrude-deformed-continuation", cells=[[0, 0]],
                    length_bp=-7 if backward else 7, ref_helix_id=design.helices[0].id,
                    **frame)
    if recompute:
        params["source_bp"] = bp
    result = parity(design, "extrude-deformed-continuation", params)
    assert len(result.helices) == 2 and result.helices[0] == design.helices[0]
    for name, direction in (("forward", m.Direction.FORWARD), ("reverse", m.Direction.REVERSE)):
        old = strand_on(design, direction)
        assert selected(result, name) == [old.domains[0]]
        assert refs(result, name) == [(old.id, int(backward == (direction == m.Direction.FORWARD)))]


def frame_source(plane="XY", *, second=False):
    from backend.core.lattice_frames import append_independent_bundle
    design = append_independent_bundle(m.Design(), [[0, 0]], 21, plane=plane,
        translation_nm=[12, -4, 8], rotation_xyzw=[0, 0.6, 0, 0.8],
        identity_seed=UUID("dfbfbe9c-d6dc-4e70-9195-822480c0d45f"))
    if second:
        design = append_independent_bundle(design, [[0, 0]], 42, plane=plane,
            translation_nm=[30, 0, 0], identity_seed=UUID("d2ca0e21-a091-4e56-8dc3-98a9ef07f1f9"))
    return design


@pytest.mark.parametrize("plane", ["XY", "XZ", "YZ"])
@pytest.mark.parametrize("backward", [False, True])
def test_continuation_addresses_exact_rotated_frame_without_adopting_same_cell_frame(plane, backward):
    design = convert(frame_source(plane, second=True))
    other = design.helices[1]
    other_strands = [s for s in design.strands if s.domains[0].helix_id == other.id]
    result = parity(design, "extrude-continuation", inputs("extrude-continuation",
        cells=[[0, 0]], plane=plane, length_bp=-7 if backward else 7,
        offset_nm=0 if backward else 21 * RISE,
        source_frame_id=design.lattice_frames[0].id))
    assert result.helices[0].length_bp == 28
    assert result.helices[1] == other
    assert [s for s in result.strands if s.id in {s.id for s in other_strands}] == other_strands
    assert result.lattice_frames == design.lattice_frames


@pytest.mark.parametrize("frame_mode", ["existing", "independent", "legacy-plane"])
@pytest.mark.parametrize("separate", [False, True])
def test_frame_extrusion_separates_lattice_placement_from_group_inheritance(frame_mode, separate):
    design = convert(source(posed=True) if frame_mode == "legacy-plane" else frame_source())
    options = {"source_frame_id": design.lattice_frames[0].id} if frame_mode == "existing" else (
        {"source_legacy_plane": True} if frame_mode == "legacy-plane" else
        {"translation_nm": [-3, 7, 2], "rotation_xyzw": [0.6, 0, 0, 0.8]})
    result = parity(design, "extrude-frame", inputs("extrude-frame", cells=[[0, 1]],
        separate_fresh_extrusions=separate, **options))
    assert len(result.helices) == len(design.helices) + 1
    for name in ("forward", "reverse"):
        assert refs(result, name) == refs(design, name)
        assert selected(result, name) == selected(design, name)
    fresh = result.helices[-1]
    if frame_mode == "existing":
        assert fresh.lattice_frame_id == design.lattice_frames[0].id
    elif frame_mode == "independent":
        assert fresh.lattice_frame_id not in {f.id for f in design.lattice_frames}
    assert all(fresh.id not in g.helix_ids for g in result.group_organization.groups)


@pytest.mark.parametrize("wrong", ["missing-frame", "wrong-plane"])
def test_invalid_continuation_frame_never_falls_back_to_same_cell(wrong):
    design = convert(frame_source(second=True))
    before = design.model_dump(mode="json")
    with pytest.raises(ValueError):
        execute("extrude-continuation", design, inputs("extrude-continuation",
            cells=[[0, 0]], offset_nm=21 * RISE,
            source_frame_id="missing" if wrong == "missing-frame" else design.lattice_frames[0].id,
            plane="XZ" if wrong == "wrong-plane" else "XY"))
    assert design.model_dump(mode="json") == before


def append(design, kind, params):
    result = execute(kind, design, params)
    row = m.SnapshotLogEntry(op_kind=kind, label=kind, params=params,
        design_snapshot_gz_b64="poisoned-before", post_state_gz_b64="poisoned-after")
    return result.copy_with(id=design.id, recipe_root=design.recipe_root,
                           feature_log=[*design.feature_log, row])


@pytest.mark.parametrize("kind", KINDS)
def test_native_recipe_reload_cold_replay_binds_extrusion_membership_without_recovery(kind):
    from backend.api.crud import BundleRequest
    from backend.core.part_history_contract import assess_part_history, create_empty_part

    design = create_empty_part("Extrusion ancestry", "HONEYCOMB")
    params = BundleRequest(cells=[[0, 0]], length_bp=21, name="Extrusion ancestry",
                           history_seed=SEED).model_dump(mode="json")
    design = append(design, "bundle-create", {**params, "_proof_version": 1})
    design = append(design, "group-organize", {"_proof_version": 1,
        "expected_placement_ids": [c.id for c in design.cluster_transforms]})
    chosen = strand_on(design, m.Direction.FORWARD)
    design = append(design, "group-create", {"_proof_version": 1, "group": {
        "id": "selected", "helix_ids": [],
        "domain_ids": [{"strand_id": chosen.id, "domain_index": 0}]}})
    params = inputs(kind, history_seed="bb9b159c-06fb-45d9-a497-cef59dff3b9f")
    if kind == "extrude-continuation":
        params.update(cells=[[0, 0]], offset_nm=21 * RISE)
    design = append(design, kind, params)
    loaded = m.Design.model_validate_json(design.model_dump_json())
    assert loaded.group_organization == design.group_organization
    proof = assess_part_history(loaded, execute=execute, dependencies=dependencies)
    assert proof["status"] == "verified", proof
    assert proof["native_editable"] is True and proof["checked_commands"] == 4
    groups = [g.model_copy(update={"domain_ids": []}) if g.id == "selected" else g
              for g in loaded.group_organization.groups]
    tampered = loaded.copy_with(group_organization=loaded.group_organization.model_copy(
        update={"groups": groups}))
    failed = assess_part_history(tampered, execute=execute, dependencies=dependencies)
    assert failed["status"] != "verified"
    assert any(issue["code"] == "authoring_state_mismatch" for issue in failed["issues"]), failed


@pytest.mark.parametrize("kind", KINDS)
def test_extrusion_cannot_erase_old_material_under_additive_lineage(kind):
    from backend.core.part_group_lineage import apply_lineage, prepare_lineage
    design = convert(source())
    params = inputs(kind)
    plan = prepare_lineage(design, kind, params)
    native = execute(kind, design.copy_with(group_organization=None), params)
    lost = strand_on(design, m.Direction.FORWARD)
    changed = native.copy_with(strands=[s for s in native.strands if s.id != lost.id])
    with pytest.raises(CommandContractError) as error:
        apply_lineage(plan, changed)
    assert error.value.code == "unsupported_group_lineage_output"


@pytest.mark.parametrize("kind", [k for k in KINDS if k != "extrude-continuation"])
def test_fresh_only_contract_does_not_admit_unexplained_old_helix_growth(kind):
    from backend.core.part_group_lineage import apply_lineage, prepare_lineage
    design = convert(source())
    params = inputs(kind)
    plan = prepare_lineage(design, kind, params)
    native = execute(kind, design.copy_with(group_organization=None), params)
    old = strand_on(native, m.Direction.FORWARD)
    grown = old.model_copy(update={"domains": [old.domains[0].model_copy(update={"end_bp": 21})]})
    changed = native.copy_with(strands=[grown if s.id == old.id else s for s in native.strands])
    with pytest.raises(CommandContractError) as error:
        apply_lineage(plan, changed)
    assert error.value.code == "unsupported_group_lineage_output"


def test_source_metadata_limit_refuses_before_extrusion_builder(monkeypatch):
    from backend.api import part_extrusion_commands
    from backend.core import part_group_lineage
    design = convert(source())
    monkeypatch.setattr(part_group_lineage, "MAX_ITEMS", 1)

    def forbidden(*args, **kwargs):
        raise AssertionError("The native builder ran before organization metadata admission")

    monkeypatch.setattr(part_extrusion_commands, "build", forbidden)
    with pytest.raises(CommandContractError) as error:
        execute("extrude-continuation", design, inputs("extrude-continuation"))
    assert error.value.code == "group_lineage_limit"
