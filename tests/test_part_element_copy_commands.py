"""Same-part copy retains native placement without snapshot/string remapping."""

from copy import deepcopy

import pytest
from pydantic import ValidationError

from backend.api import part_element_copy_commands as commands
from backend.core import models as m
from backend.core.element_copy import paste_elements
from backend.core.part_command_errors import CommandContractError, ReferenceResolutionError
from backend.core.part_history_proof import AUTHORING_FIELDS
from backend.core.protein import parse_protein_pdb
from backend.core.quantum_dots import create_quantum_dot
from tests.test_protein import _SYNTH_PDB


def inputs(**changes):
    return {"_proof_version": 1, "copy_version": 1, "protein_ids": ["protein"],
        "protein_output_ids": ["protein-copy"], "nanoparticle_ids": ["gold", "dot"],
        "nanoparticle_output_ids": ["gold-copy", "dot-copy"], "paste_index": 1, **changes}


def source():
    asset = parse_protein_pdb(_SYNTH_PDB, name="Source protein")
    asset.id = "asset"
    protein = m.ProteinAttachment(id="protein", asset_id="asset", target=m.ProteinTargetFree(),
        conjugation_atom_serial=9, visible=False,
        pose=m.Mat4x4(values=[0, -1, 0, -4, 1, 0, 0, 2, 0, 0, 1, 1, 0, 0, 0, 1]))
    gold = m.Nanoparticle(id="gold", diameter_nm=10,
        pose=m.Mat4x4(values=[1, 0, 0, 4, 0, 1, 0, -3, 0, 0, 1, 2, 0, 0, 0, 1]))
    dot = create_quantum_dot("nn-hecz-600")
    dot.id = "dot"
    return m.Design(protein_assets=[asset], protein_attachments=[protein], nanoparticles=[gold, dot],
        staple_groups=[m.StapleGroup(id="independent-group", name="Retained empty")])


def authored(design):
    return design.model_dump(mode="json", include=AUTHORING_FIELDS)


def protein_batch(count, atom_count, *, shared):
    """Synthetic records exercise admission, independently of protein importing."""
    design = source()
    template = design.protein_assets[0]
    assets = [template.model_copy(deep=True, update={"id": f"asset-{index}",
        "atoms": [template.atoms[0].model_copy(update={"serial": serial + 1, "x": float(serial)})
                  for serial in range(atom_count)], "bonds": []})
        for index in range(1 if shared else count)]
    proteins = [design.protein_attachments[0].model_copy(deep=True, update={
        "id": f"protein-{index}", "asset_id": assets[0 if shared else index].id})
        for index in range(count)]
    design = design.copy_with(protein_assets=assets, protein_attachments=proteins, nanoparticles=[])
    params = inputs(protein_ids=[item.id for item in proteins],
        protein_output_ids=[f"{item.id}-copy" for item in proteins],
        nanoparticle_ids=[], nanoparticle_output_ids=[])
    return design, params


@pytest.mark.parametrize("selection", ["protein", "gold", "dot", "mixed"])
@pytest.mark.parametrize("paste_index", [1, 3, 10000])
def test_native_formula_matches_legacy_full_authoring_and_transport(selection, paste_index):
    design = source()
    pids = ["protein"] if selection in {"protein", "mixed"} else []
    nids = ["gold", "dot"] if selection == "mixed" else [selection] if selection != "protein" else []
    params = inputs(protein_ids=pids, protein_output_ids=[f"{item}-copy" for item in pids],
        nanoparticle_ids=nids, nanoparticle_output_ids=[f"{item}-copy" for item in nids], paste_index=paste_index)
    before = design.model_dump_json()
    legacy, old_refs = paste_elements(design, design, pids, nids, paste_index)
    for old, identity in zip(legacy.protein_attachments[len(design.protein_attachments):], params["protein_output_ids"]):
        old.id = identity
    for old, identity in zip(legacy.nanoparticles[len(design.nanoparticles):], params["nanoparticle_output_ids"]):
        old.id = identity
    candidate, refs = commands.evaluate("element-paste", design, params)
    assert authored(candidate) == authored(legacy)
    assert [item["kind"] for item in refs] == [item["kind"] for item in old_refs]
    assert [item["id"] for item in refs] == params["protein_output_ids"] + params["nanoparticle_output_ids"]
    assert design.model_dump_json() == before
    transported = m.Design.model_validate_json(design.model_dump_json())
    assert authored(commands.build("element-paste", transported, params)) == authored(candidate)
    assert commands.resources("element-paste", params) == {"sources": (), "imports": False}


def test_source_collection_order_is_preserved_with_correct_output_slot_binding():
    design = source()
    params = inputs(nanoparticle_ids=["dot", "gold"], nanoparticle_output_ids=["dot-copy", "gold-copy"])
    candidate, refs = commands.evaluate("element-paste", design, params)
    assert [item.id for item in candidate.nanoparticles] == ["gold", "dot", "gold-copy", "dot-copy"]
    assert refs == [{"kind": "protein", "id": "protein-copy"}, {"kind": "nanoparticle", "id": "gold-copy"},
                    {"kind": "nanoparticle", "id": "dot-copy"}]


def test_typed_identity_namespaces_do_not_rewrite_text_asset_refs_or_catalog_metadata():
    design = source()
    design.protein_attachments[0].id = "same"
    design.protein_assets[0].id = "same"
    design.protein_assets[0].name = "same"
    design.protein_assets[0].metadata = {"same": "same"}
    design.protein_attachments[0].asset_id = "same"
    design.protein_attachments[0].handle_sequence = "same"
    design.nanoparticles[1].id = "same"
    design.nanoparticles[1].quantum_dot.product_name = "same"
    params = inputs(protein_ids=["same"], protein_output_ids=["same-output"],
        nanoparticle_ids=["same"], nanoparticle_output_ids=["same-output"])
    candidate = commands.build("element-paste", design, params)
    assert candidate.protein_attachments[-1].id == candidate.nanoparticles[-1].id == "same-output"
    assert candidate.protein_attachments[-1].asset_id == "same"
    assert candidate.protein_attachments[-1].handle_sequence == "same"
    assert candidate.nanoparticles[-1].quantum_dot.product_name == "same"
    assert candidate.protein_assets == design.protein_assets
    assert candidate.protein_assets[0].metadata == {"same": "same"}
    candidate.nanoparticles[-1].quantum_dot.product_name = "Changed copy"
    candidate.protein_attachments[-1].pose.values[3] += 1
    assert design.nanoparticles[1].quantum_dot.product_name == "same"
    assert candidate.protein_attachments[0].pose == design.protein_attachments[0].pose


def test_no_dna_geometry_library_lookup_or_unselected_deepcopy(monkeypatch):
    from backend.core import design_geometry, quantum_dots

    class Poison:
        def __deepcopy__(self, _memo):
            raise AssertionError("Copied unrelated data")

    design = source()
    design.feature_log = [Poison()]
    design.loadouts = [Poison()]
    design.helices = [Poison()]
    design.protein_assets.append(m.ProteinAsset(id="unselected", metadata={"poison": Poison()}))
    monkeypatch.setattr(design_geometry, "fitting_geometry", lambda *_a, **_k: pytest.fail("Copy generated DNA"))
    monkeypatch.setattr(quantum_dots, "catalog_entry", lambda *_a: pytest.fail("Copy read mutable catalog"))
    candidate = commands.build("element-paste", design, inputs())
    assert candidate.helices is design.helices and candidate.feature_log is design.feature_log
    assert candidate.loadouts is design.loadouts and candidate.protein_assets is design.protein_assets


@pytest.mark.parametrize("failure,expected_kind,path", [
    ("missing_protein", "protein_attachment", ["protein_ids", 0]),
    ("duplicate_protein", "protein_attachment", ["protein_ids", 0]),
    ("missing_particle", "nanoparticle", ["nanoparticle_ids", 0]),
    ("duplicate_particle", "nanoparticle", ["nanoparticle_ids", 0]),
    ("missing_asset", "protein_asset", ["protein_ids", 0]),
    ("duplicate_asset", "protein_asset", ["protein_ids", 0]),
    ("unselected_atom", "protein_attachment", ["protein_ids", 0]),
    ("missing_atom", "protein_atom", ["protein_ids", 0]),
    ("duplicate_atom", "protein_atom", ["protein_ids", 0]),
    ("protein_output", "protein_attachment", ["protein_output_ids", 0]),
    ("particle_output", "nanoparticle", ["nanoparticle_output_ids", 0]),
    ("dangling_owner", "nanoparticle", ["nanoparticle_output_ids", 0]),
    ("empty_asset", "protein_asset", ["protein_ids", 0]),
])
def test_reference_failures_are_structured_and_leave_source_unchanged(failure, expected_kind, path):
    design, params = source(), inputs()
    if failure == "missing_protein":
        design.protein_attachments = []
    elif failure == "duplicate_protein":
        design.protein_attachments *= 2
    elif failure == "missing_particle":
        design.nanoparticles = design.nanoparticles[1:]
    elif failure == "duplicate_particle":
        design.nanoparticles.append(deepcopy(design.nanoparticles[0]))
    elif failure == "missing_asset":
        design.protein_assets = []
    elif failure == "duplicate_asset":
        design.protein_assets *= 2
    elif failure == "unselected_atom":
        design.protein_attachments[0].conjugation_atom_serial = None
    elif failure == "missing_atom":
        design.protein_attachments[0].conjugation_atom_serial = 999
    elif failure == "duplicate_atom":
        design.protein_assets[0].atoms.append(deepcopy(design.protein_assets[0].atoms[8]))
    elif failure == "protein_output":
        params["protein_output_ids"] = ["protein"]
    elif failure == "particle_output":
        params["nanoparticle_output_ids"][0] = "dot"
    elif failure == "dangling_owner":
        design.nanoparticle_connection_versions = [m.NanoparticleConnectionVersion(
            nanoparticle_id="gold-copy", strand_id="missing", overhang_id="missing")]
    else:
        design.protein_assets[0].atoms = []
    before = design.model_dump_json()
    with pytest.raises(ReferenceResolutionError) as error:
        commands.build("element-paste", design, params)
    issue = error.value.as_issue()
    assert issue["references"][0]["kind"] == expected_kind
    assert issue["references"][0]["parameter_path"] == path
    assert design.model_dump_json() == before


@pytest.mark.parametrize("shared", [True, False])
@pytest.mark.parametrize("count,atom_count", [(5, 1000), (16, 251)])
def test_total_atom_work_counts_each_placement_and_rejects_before_world_math(monkeypatch, shared, count, atom_count):
    design, params = protein_batch(count, atom_count, shared=shared)
    before = design.model_dump_json()
    monkeypatch.setattr("backend.core.protein.compose_protein_world_transform",
                        lambda *_a: pytest.fail("Oversized selection reached world placement"))
    with pytest.raises(CommandContractError) as error:
        commands.build("element-paste", design, params)
    assert error.value.code == "source_limit" and error.value.status == "unverified"
    assert design.model_dump_json() == before


@pytest.mark.parametrize("shared", [True, False])
@pytest.mark.parametrize("count,atom_count", [(4, 1000), (16, 250)])
def test_exact_atom_work_boundary_retains_complete_legacy_authoring(shared, count, atom_count):
    design, params = protein_batch(count, atom_count, shared=shared)
    assert count * atom_count == commands.MAX_ATOM_WORK
    legacy, _ = paste_elements(design, design, params["protein_ids"], [], 1)
    for item, identity in zip(legacy.protein_attachments[count:], params["protein_output_ids"]):
        item.id = identity
    assert authored(commands.build("element-paste", design, params)) == authored(legacy)


@pytest.mark.parametrize("unsupported", ["anchor", "binder", "azide", "coating", "biotin", "owner", "wrong_kind", "large_asset", "large_bonds"])
def test_unsupported_families_are_unverified_and_do_not_enter_legacy_builder(unsupported, monkeypatch):
    from backend.core import element_copy

    design = source()
    if unsupported == "anchor":
        design.protein_attachments[0].target = m.ProteinTargetDesign(overhang_id="target")
    elif unsupported == "binder":
        design.protein_attachments[0].binder_strand_id = "binder"
    elif unsupported == "azide":
        design.protein_attachments[0].azide_end = "5p"
    elif unsupported == "coating":
        design.nanoparticles[0].coating = m.StreptavidinCoating(target_count=1, protein=design.protein_assets[0])
    elif unsupported == "biotin":
        design.nanoparticles[0].biotin_dna = [m.BiotinDNA(strand_id="dna", helix_id="helix", chain="A")]
    elif unsupported == "owner":
        design.nanoparticle_connection_versions = [m.NanoparticleConnectionVersion(
            nanoparticle_id="gold", strand_id="dna", overhang_id="target")]
    elif unsupported == "wrong_kind":
        design.nanoparticles[0].quantum_dot = design.nanoparticles[1].quantum_dot
    elif unsupported == "large_asset":
        design.protein_assets[0].atoms = [design.protein_assets[0].atoms[0]] * 1001
    else:
        design.protein_assets[0].bonds = [(0, 1)] * 4001
    monkeypatch.setattr(element_copy, "paste_elements", lambda *_a: pytest.fail("Native failure fell back to snapshot paste"))
    with pytest.raises(CommandContractError) as error:
        commands.build("element-paste", design, inputs())
    assert error.value.status == "unverified" and error.value.code == "unsupported_element_copy_source"


@pytest.mark.parametrize("field", ["protein_pose", "particle_pose", "diameter", "atom"])
def test_nonfinite_selected_geometry_is_rejected(field):
    design = source()
    if field == "protein_pose":
        design.protein_attachments[0].pose.values[3] = float("nan")
    elif field == "particle_pose":
        design.nanoparticles[0].pose.values[3] = float("inf")
    elif field == "diameter":
        design.nanoparticles[0].diameter_nm = float("inf")
    else:
        design.protein_assets[0].atoms[0].x = float("nan")
    with pytest.raises(ReferenceResolutionError):
        commands.build("element-paste", design, inputs())


@pytest.mark.parametrize("changes", [
    {"copy_version": True}, {"copy_version": 2}, {"_proof_version": True}, {"paste_index": True},
    {"paste_index": 0}, {"paste_index": 10001}, {"source": {}}, {"pose": [0] * 16}, {"atoms": []},
    {"protein_ids": ["protein", "protein"], "protein_output_ids": ["one", "two"]},
    {"nanoparticle_output_ids": ["same", "same"]}, {"protein_output_ids": []},
    {"protein_ids": [""]}, {"protein_ids": [], "protein_output_ids": [], "nanoparticle_ids": [], "nanoparticle_output_ids": []},
    {"protein_ids": [str(i) for i in range(commands.MAX_ELEMENTS + 1)],
     "protein_output_ids": [f"copy-{i}" for i in range(commands.MAX_ELEMENTS + 1)]},
])
def test_strict_contract_rejects_saved_outputs_ambiguous_slots_and_oversized_batches(changes):
    with pytest.raises(ValidationError):
        commands.parse_command("element-paste", inputs(**changes))
