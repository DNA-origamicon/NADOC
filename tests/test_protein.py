"""
Tests for protein import + placement (display layer) — Phase 1.

Covers ``backend.core.protein`` (PDB parsing, asset→atomistic bridge) and the
serialization + Three-Layer-Law invariants of the new ``ProteinAsset`` /
``ProteinAttachment`` models on ``Design`` / ``Assembly``.

Fixtures are synthetic PDB text built inline (CHARMM-style, blank element
column, 4-char water residue name) so the tests don't depend on any shipped
structure file.
"""

from __future__ import annotations

import numpy as np
import pytest
from fastapi.testclient import TestClient

from backend.api import state as design_state
from backend.api.main import app
from backend.core.atomistic import atomistic_to_json, build_atomistic_model
from backend.core.constants import BDNA_RISE_PER_BP
from backend.core.models import (
    Assembly,
    Design,
    Direction,
    Domain,
    Helix,
    OverhangSpec,
    PartInstance,
    PartSourceInline,
    ProteinAttachment,
    ProteinTargetDesign,
    Strand,
    StrandType,
    Vec3,
)
from backend.core.protein import (
    PROTEIN_SENTINEL_PREFIX,
    compose_protein_world_transform,
    parse_protein_pdb,
    protein_asset_meta,
    protein_asset_to_atomistic,
    resolve_overhang_anchor,
)

from tests.conftest import make_minimal_design

client = TestClient(app)


# A tiny CHARMM-style PDB: one ALA + one CYS (with SG sulfur), plus a TIP3 water
# and a SOD ion that MUST be dropped.  The element column (cols 77-78) is left
# blank, exercising name-based element inference.
_SYNTH_PDB = """\
REMARK synthetic test structure
ATOM      1  N   ALA     1       0.000   0.000   0.000  1.00  0.00      PROA
ATOM      2  CA  ALA     1       1.500   0.000   0.000  1.00  0.00      PROA
ATOM      3  C   ALA     1       2.000   1.400   0.000  1.00  0.00      PROA
ATOM      4  O   ALA     1       1.300   2.400   0.000  1.00  0.00      PROA
ATOM      5  CB  ALA     1       2.000  -1.000   1.000  1.00  0.00      PROA
ATOM      6  N   CYS     2       3.300   1.500   0.000  1.00  0.00      PROA
ATOM      7  CA  CYS     2       4.100   2.700   0.000  1.00  0.00      PROA
ATOM      8  CB  CYS     2       5.600   2.400   0.000  1.00  0.00      PROA
ATOM      9  SG  CYS     2       6.700   3.900   0.000  1.00  0.00      PROA
ATOM     10  OH2 TIP3    1      12.000  12.000  12.000  1.00  0.00      WAT
ATOM     11  H1  TIP3    1      12.700  12.300  12.000  1.00  0.00      WAT
ATOM     12  SOD SOD     1      20.000  20.000  20.000  1.00  0.00      ION
END
"""


def test_protein_asset_meta_shape():
    # Direct input→output pin for the core helper service-pushed from crud.py
    # (Refactor #41): library metadata = id/name/source + counts + conjugation
    # serial, with NO atom list leaking into the dict.
    asset = parse_protein_pdb(_SYNTH_PDB, name="synth", source_filename="synth.pdb")
    meta = protein_asset_meta(asset)
    assert meta["id"] == asset.id
    assert meta["name"] == "synth"
    assert meta["source_filename"] == "synth.pdb"
    assert meta["atom_count"] == len(asset.atoms) == 9   # 9 protein atoms (water+ion dropped)
    assert meta["residue_count"] == 2                    # ALA + CYS
    assert meta["chain_ids"] == asset.metadata.get("chain_ids", [])
    assert meta["default_conjugation_atom_serial"] == asset.default_conjugation_atom_serial
    assert "atoms" not in meta   # metadata-only — the heavy atom list must not be embedded


def test_parse_keeps_protein_drops_water_ions():
    asset = parse_protein_pdb(_SYNTH_PDB, name="synth", source_filename="synth.pdb")
    res = {a.res_name for a in asset.atoms}
    assert res == {"ALA", "CYS"}, f"water/ions not dropped: {res}"
    assert len(asset.atoms) == 9
    assert asset.name == "synth"
    assert asset.metadata["residue_count"] == 2
    assert asset.metadata["chain_ids"] == ["PROA"]   # falls back to segid


def test_element_inference_charmm_blank_column():
    """Blank element column → infer from name; 'CA' is carbon, 'SG' is sulfur."""
    asset = parse_protein_pdb(_SYNTH_PDB)
    by_name = {(a.res_name, a.name): a for a in asset.atoms}
    assert by_name[("ALA", "CA")].element == "C"   # NOT calcium
    assert by_name[("ALA", "N")].element == "N"
    assert by_name[("ALA", "O")].element == "O"
    assert by_name[("CYS", "SG")].element == "S"


def test_asset_to_atomistic_and_json():
    asset = parse_protein_pdb(_SYNTH_PDB)
    model = protein_asset_to_atomistic(asset)
    assert len(model.atoms) == len(asset.atoms)
    # Sentinel ids keep protein atoms out of the DNA helix namespace.
    assert all(a.helix_id.startswith(PROTEIN_SENTINEL_PREFIX) for a in model.atoms)
    j = atomistic_to_json(model)
    # element_meta must cover sulfur (present) and the four DNA elements.
    for el in ("S", "C", "N", "O", "P"):
        assert el in j["element_meta"], f"missing element_meta for {el}"
    assert j["element_meta"]["S"]["cpk_color"] == 0xFFFF30


def test_asset_to_atomistic_applies_pose():
    import numpy as np
    asset = parse_protein_pdb(_SYNTH_PDB)
    # Pure translation by (10, 0, 0) nm (row-major homogeneous).
    pose = np.eye(4)
    pose[0, 3] = 10.0
    model = protein_asset_to_atomistic(asset, pose_matrix=pose)
    a0 = asset.atoms[0]
    m0 = model.atoms[0]
    assert abs(m0.x - (a0.x + 10.0)) < 1e-9
    assert abs(m0.y - a0.y) < 1e-9


def test_design_roundtrip_with_protein():
    asset = parse_protein_pdb(_SYNTH_PDB)
    att = ProteinAttachment(
        asset_id=asset.id,
        target=ProteinTargetDesign(overhang_id="ovhg_h0_5_3p"),
        conjugation_atom_serial=asset.default_conjugation_atom_serial,
    )
    d = make_minimal_design()
    d.protein_assets = [asset]
    d.protein_attachments = [att]
    d2 = Design.model_validate_json(d.model_dump_json())
    assert d2.protein_assets[0].id == asset.id
    assert len(d2.protein_assets[0].atoms) == len(asset.atoms)
    assert d2.protein_attachments[0].target.overhang_id == "ovhg_h0_5_3p"
    assert d2.protein_attachments[0].target.kind == "overhang"


def test_assembly_roundtrip_v2_preserves_proteins():
    asset = parse_protein_pdb(_SYNTH_PDB)
    att = ProteinAttachment(asset_id=asset.id, target=ProteinTargetDesign(overhang_id="ovhg_h0_5_3p"))
    part = PartInstance(source=PartSourceInline(design=make_minimal_design()))
    asm = Assembly(instances=[part], protein_assets=[asset], protein_attachments=[att])
    # v2 wire format round-trip (the default for new writes).
    asm2 = Assembly.from_json(asm.to_json())
    assert len(asm2.protein_assets) == 1
    assert asm2.protein_assets[0].id == asset.id
    assert asm2.protein_attachments[0].asset_id == asset.id


def test_three_layer_law_protein_does_not_touch_topology():
    """Adding a protein attachment must leave the topological layer + the DNA
    all-atom model byte-identical."""
    asset = parse_protein_pdb(_SYNTH_PDB)
    d = make_minimal_design()

    strands_before = d.model_dump()["strands"]
    overhangs_before = d.model_dump()["overhangs"]
    crossovers_before = d.model_dump()["crossovers"]
    dna_atoms_before = atomistic_to_json(build_atomistic_model(d))["atoms"]

    d.protein_assets = [asset]
    d.protein_attachments = [ProteinAttachment(
        asset_id=asset.id, target=ProteinTargetDesign(overhang_id="ovhg_h0_5_3p"),
    )]

    assert d.model_dump()["strands"] == strands_before
    assert d.model_dump()["overhangs"] == overhangs_before
    assert d.model_dump()["crossovers"] == crossovers_before
    # The DNA all-atom build ignores protein data entirely.
    assert atomistic_to_json(build_atomistic_model(d))["atoms"] == dna_atoms_before


# ── Phase 2: anchor math + attachment CRUD + placement ─────────────────────────


def _design_with_overhang() -> Design:
    """Minimal design with one real extruded overhang helix (8 bp, +z axis at
    x=2.5) so geometry resolves a free-tip anchor."""
    base = make_minimal_design()
    oh_helix = Helix(
        id="oh_helix", axis_start=Vec3(x=2.5, y=0.0, z=0.0),
        axis_end=Vec3(x=2.5, y=0.0, z=8 * BDNA_RISE_PER_BP),
        phase_offset=0.0, length_bp=8, grid_pos=(0, 0),
    )
    oh_strand = Strand(
        id="oh_strand",
        domains=[Domain(helix_id="oh_helix", start_bp=0, end_bp=7,
                        direction=Direction.FORWARD, overhang_id="oh_5p")],
        strand_type=StrandType.STAPLE,
    )
    return base.model_copy(update={
        "helices": [*base.helices, oh_helix],
        "strands": [*base.strands, oh_strand],
        "overhangs": [OverhangSpec(id="oh_5p", helix_id="oh_helix",
                                   strand_id="oh_strand", label="OHA")],
    })


def test_resolve_overhang_anchor_points_outward():
    # Synthetic nucs: root at z=0, free tip at z=2 → outward should be +z.
    nucs = [
        {"overhang_id": "ov", "backbone_position": [1.0, 0.0, 0.0], "axis_tangent": [0, 0, 1]},
        {"overhang_id": "ov", "backbone_position": [1.0, 0.0, 2.0], "is_three_prime": True,
         "axis_tangent": [0, 0, 1]},
    ]
    tip, outward = resolve_overhang_anchor(nucs, "ov", "free_end")
    assert np.allclose(tip, [1.0, 0.0, 2.0])
    assert np.allclose(outward, [0.0, 0.0, 1.0])


def test_compose_places_conjugation_at_tip_body_outward():
    asset = parse_protein_pdb(_SYNTH_PDB)
    att = ProteinAttachment(
        asset_id=asset.id, target=ProteinTargetDesign(overhang_id="ov"),
        conjugation_atom_serial=asset.default_conjugation_atom_serial,
    )
    tip = np.array([1.0, 0.0, 2.0]); outward = np.array([0.0, 0.0, 1.0])
    m = compose_protein_world_transform(asset, att, tip, outward)
    conj = next(a for a in asset.atoms if a.serial == att.conjugation_atom_serial)
    cw = m @ np.array([conj.x, conj.y, conj.z, 1.0])
    assert np.allclose(cw[:3], tip, atol=1e-6)            # conjugation atom at the tip
    com = m @ np.array([*asset.center_of_mass, 1.0])
    assert float(np.dot(com[:3] - tip, outward)) > 0       # protein body points outward


@pytest.fixture
def _clean_state():
    design_state.set_design(_design_with_overhang())
    for a in design_state.list_protein_assets():
        design_state.remove_protein_asset(a.id)
    yield
    design_state.close_session()


def _import_protein() -> str:
    r = client.post("/api/design/protein/import",
                    json={"content": _SYNTH_PDB, "name": "synth"})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def test_attach_embeds_asset_and_preserves_topology(_clean_state):
    asset_id = _import_protein()
    strands_before = [s.id for s in design_state.get_design().strands]

    r = client.post("/api/design/protein/attachments",
                    json={"asset_id": asset_id, "overhang_id": "oh_5p"})
    assert r.status_code == 201, r.text
    att_id = r.json()["attachment_id"]

    d = design_state.get_design()
    assert len(d.protein_attachments) == 1
    assert d.protein_attachments[0].id == att_id
    assert any(a.id == asset_id for a in d.protein_assets)   # asset embedded
    assert [s.id for s in d.strands] == strands_before        # topology untouched


def test_placement_endpoint_places_protein_at_overhang(_clean_state):
    asset_id = _import_protein()

    # Library-only (no attachment) renders NOTHING — the design's attachments are
    # the single source of truth (no render-at-origin fallback).
    before = client.get("/api/design/protein/atomistic").json()
    assert len(before["atoms"]) == 0

    client.post("/api/design/protein/attachments",
                json={"asset_id": asset_id, "overhang_id": "oh_5p"})

    after = client.get("/api/design/protein/atomistic").json()
    assert len(after["atoms"]) == 9
    c_after = np.mean([[a["x"], a["y"], a["z"]] for a in after["atoms"]], axis=0)
    # The overhang helix sits at x≈2.5; placement moves the protein there.
    assert abs(c_after[0] - 2.5) < 1.5


def test_azide_attach_end_picks_nearer_overhang_end():
    from backend.core.protein import azide_attach_end
    # Overhang "ov": root at z=0, free tip at z=2. Binder "bnd" antiparallel:
    # its 5' terminus is co-located with the free tip (z=2), 3' with the root (z=0).
    nucs = [
        {"overhang_id": "ov", "backbone_position": [1, 0, 0], "axis_tangent": [0, 0, 1]},
        {"overhang_id": "ov", "backbone_position": [1, 0, 2], "is_three_prime": True, "axis_tangent": [0, 0, 1]},
        {"strand_id": "bnd", "backbone_position": [1, 0, 2], "is_five_prime": True},
        {"strand_id": "bnd", "backbone_position": [1, 0, 0], "is_three_prime": True},
    ]
    assert azide_attach_end(nucs, "ov", "bnd", "5p") == "free_end"
    assert azide_attach_end(nucs, "ov", "bnd", "3p") == "root"


def _set_sequenced_overhang():
    d = _design_with_overhang()
    d = d.model_copy(update={"overhangs": [d.overhangs[0].model_copy(update={"sequence": "ACGTACGT"})]})
    design_state.set_design(d)


def test_conjugate_creates_binder_and_attachment(_clean_state):
    _set_sequenced_overhang()
    asset_id = _import_protein()
    strands_before = {s.id for s in design_state.get_design().strands}

    r = client.post("/api/design/protein/conjugate",
                    json={"asset_id": asset_id, "overhang_id": "oh_5p", "azide_end": "5p"})
    assert r.status_code == 201, r.text
    binder_id = r.json()["binder_strand_id"]

    d = design_state.get_design()
    # (1) the handle is a real overhang-binding domain
    binder = next(s for s in d.strands if s.id == binder_id)
    assert binder.id not in strands_before
    assert binder.strand_type == StrandType.OH_BINDER
    assert any(dom.binds_overhang_id == "oh_5p" for dom in binder.domains)
    assert binder.sequence and len(binder.sequence) == 8        # RC of the 8-nt overhang
    # (2) the protein is attached at the chosen site, asset embedded
    assert len(d.protein_attachments) == 1
    att = d.protein_attachments[0]
    assert att.target.overhang_id == "oh_5p"
    assert att.conjugation_atom_serial is not None
    assert att.target.attach_end in ("free_end", "root")
    assert any(a.id == asset_id for a in d.protein_assets)


def test_conjugate_azide_end_flips_attach_end(_clean_state):
    _set_sequenced_overhang()
    asset_id = _import_protein()
    r5 = client.post("/api/design/protein/conjugate",
                     json={"asset_id": asset_id, "overhang_id": "oh_5p", "azide_end": "5p"})
    end5 = design_state.get_design().protein_attachments[-1].target.attach_end
    client.post("/api/design/undo")
    r3 = client.post("/api/design/protein/conjugate",
                     json={"asset_id": asset_id, "overhang_id": "oh_5p", "azide_end": "3p"})
    end3 = design_state.get_design().protein_attachments[-1].target.attach_end
    assert r5.status_code == 201 and r3.status_code == 201
    assert {end5, end3} == {"free_end", "root"}      # the two azide ends land on opposite ends


def test_conjugate_one_undo_reverts_binder_and_attachment(_clean_state):
    _set_sequenced_overhang()
    asset_id = _import_protein()
    n_strands = len(design_state.get_design().strands)
    client.post("/api/design/protein/conjugate",
                json={"asset_id": asset_id, "overhang_id": "oh_5p", "azide_end": "5p"})
    assert len(design_state.get_design().strands) == n_strands + 1
    r = client.post("/api/design/undo")
    assert r.status_code == 200, r.text
    d = design_state.get_design()
    assert len(d.strands) == n_strands                  # binder gone
    assert len(d.protein_attachments) == 0              # attachment gone (single undo)


def test_undo_import_removes_rendered_protein(_clean_state):
    # Free import → protein renders; undo → it disappears (no orphan at origin).
    client.post("/api/design/import/pdb-auto", json={"content": _SYNTH_PDB, "name": "synth"})
    assert len(client.get("/api/design/protein/atomistic").json()["atoms"]) == 9
    r = client.post("/api/design/undo")
    assert r.status_code == 200, r.text
    assert len(design_state.get_design().protein_attachments) == 0
    assert len(client.get("/api/design/protein/atomistic").json()["atoms"]) == 0  # gone, not at origin


def test_delete_attachment_clears_render(_clean_state):
    client.post("/api/design/import/pdb-auto", json={"content": _SYNTH_PDB, "name": "synth"})
    att_id = design_state.get_design().protein_attachments[0].id
    client.delete(f"/api/design/protein/attachments/{att_id}")
    assert len(client.get("/api/design/protein/atomistic").json()["atoms"]) == 0


def test_delete_protein_import_feature_clears_render(_clean_state):
    # Deleting the protein-import feature-log row must remove the imported
    # protein from the view (it's a root op: the asset/attachment it created
    # have no other creating entry in the log).
    client.post("/api/design/import/pdb-auto", json={"content": _SYNTH_PDB, "name": "synth"})
    d = design_state.get_design()
    assert d.feature_log[-1].op_kind == "protein-import"
    idx = len(d.feature_log) - 1
    r = client.delete(f"/api/design/features/{idx}")
    assert r.status_code == 200, r.text
    after = design_state.get_design()
    assert len(after.protein_attachments) == 0
    assert len(after.protein_assets) == 0
    assert len(client.get("/api/design/protein/atomistic").json()["atoms"]) == 0


def test_delete_last_protein_import_keeps_earlier(_clean_state):
    # Two imports; deleting the LAST import row surgically removes just it and
    # keeps the earlier protein (it has no later dependents).
    client.post("/api/design/import/pdb-auto", json={"content": _SYNTH_PDB, "name": "synth1"})
    client.post("/api/design/import/pdb-auto", json={"content": _SYNTH_PDB, "name": "synth2"})
    assert len(design_state.get_design().protein_attachments) == 2
    last_idx = len(design_state.get_design().feature_log) - 1
    r = client.delete(f"/api/design/features/{last_idx}")
    assert r.status_code == 200, r.text
    j = r.json()
    assert not j.get("needs_cascade_decision")
    after = design_state.get_design()
    assert len(after.protein_attachments) == 1
    assert len(after.protein_assets) == 1
    assert len(client.get("/api/design/protein/atomistic").json()["atoms"]) == 9


def test_delete_earlier_protein_import_lists_dependent(_clean_state):
    # protein-import is non-reconstructable, so a later import baked on top is a
    # dependent: deleting the first lists the second instead of silently
    # corrupting (design unchanged until the user cascades).
    client.post("/api/design/import/pdb-auto", json={"content": _SYNTH_PDB, "name": "synth1"})
    first_idx = len(design_state.get_design().feature_log) - 1
    client.post("/api/design/import/pdb-auto", json={"content": _SYNTH_PDB, "name": "synth2"})
    r = client.delete(f"/api/design/features/{first_idx}")
    assert r.status_code == 200, r.text
    j = r.json()
    assert j.get("needs_cascade_decision") is True
    assert len(design_state.get_design().protein_attachments) == 2  # unchanged
    # Cascade clears both.
    r = client.delete(f"/api/design/features/{first_idx}?cascade=true")
    assert r.status_code == 200, r.text
    assert len(design_state.get_design().protein_attachments) == 0


def test_patch_visible_false_hides_protein(_clean_state):
    asset_id = _import_protein()
    att_id = client.post("/api/design/protein/attachments",
                         json={"asset_id": asset_id, "overhang_id": "oh_5p"}).json()["attachment_id"]

    r = client.patch(f"/api/design/protein/attachments/{att_id}", json={"visible": False})
    assert r.status_code == 200, r.text
    # Hidden, NOT relocated to the origin.
    hidden = client.get("/api/design/protein/atomistic").json()
    assert len(hidden["atoms"]) == 0


def test_delete_attachment(_clean_state):
    asset_id = _import_protein()
    att_id = client.post("/api/design/protein/attachments",
                         json={"asset_id": asset_id, "overhang_id": "oh_5p"}).json()["attachment_id"]
    r = client.delete(f"/api/design/protein/attachments/{att_id}")
    assert r.status_code == 200, r.text
    assert len(design_state.get_design().protein_attachments) == 0


def test_attach_unknown_overhang_404(_clean_state):
    asset_id = _import_protein()
    r = client.post("/api/design/protein/attachments",
                    json={"asset_id": asset_id, "overhang_id": "nope"})
    assert r.status_code == 404


# ── Merged "Import PDB": classification + auto-routing ──────────────────────────

_DD12_DNA = "backend/data/dd12_na.pdb"   # Drew-Dickerson dodecamer (B-DNA)


def test_classify_pdb_content():
    from backend.core.protein import classify_pdb_content
    assert classify_pdb_content(_SYNTH_PDB) == (False, True)          # protein only
    dna = open(_DD12_DNA).read()
    assert classify_pdb_content(dna) == (True, False)                 # DNA only
    # Water/ions alone classify as neither.
    water = "ATOM      1  OH2 TIP3    1       0.000   0.000   0.000  1.00  0.00      WAT\n"
    assert classify_pdb_content(water) == (False, False)


def test_pdb_auto_routes_protein_to_library_without_touching_design(_clean_state):
    strands_before = [s.id for s in design_state.get_design().strands]
    r = client.post("/api/design/import/pdb-auto",
                    json={"content": _SYNTH_PDB, "name": "synth"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["imported"] == {"dna": False, "protein": True}
    assert body["protein"]["atom_count"] == 9
    assert body["source"] == "file"
    # Design (the DNA topology) is untouched.
    assert [s.id for s in design_state.get_design().strands] == strands_before


def test_pdb_auto_routes_dna_to_design(_clean_state, monkeypatch):
    # Verify the DNA *routing branch* without running the real (heavy,
    # globally-stateful) import_pdb — classification still uses real DNA content.
    from backend.core import pdb_to_design
    monkeypatch.setattr(pdb_to_design, "import_pdb",
                        lambda content: (make_minimal_design(), None, []))
    monkeypatch.setattr(pdb_to_design, "merge_pdb_into_design",
                        lambda d, content: (make_minimal_design(), None, []))

    dna = open(_DD12_DNA).read()
    r = client.post("/api/design/import/pdb-auto", json={"content": dna})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["imported"]["dna"] is True
    assert "design" in body and body["design"]["helices"]   # full design response


def test_pdb_auto_rejects_empty_and_irrelevant(_clean_state):
    assert client.post("/api/design/import/pdb-auto", json={}).status_code == 400
    water = "ATOM      1  OH2 TIP3    1       0.000   0.000   0.000  1.00  0.00      WAT\n"
    assert client.post("/api/design/import/pdb-auto", json={"content": water}).status_code == 400


def test_pdb_auto_invalid_rcsb_id_400(_clean_state):
    # Bad id is rejected by the format check before any network call.
    r = client.post("/api/design/import/pdb-auto", json={"pdb_id": "zz"})
    assert r.status_code == 400


# Protein (ALA+CYS) plus a couple of DNA residues → a "complex".
_SYNTH_PROT_DNA = _SYNTH_PDB.replace("END\n", "") + (
    "ATOM     20  P   DA  B   1      30.000  30.000  30.000  1.00  0.00      DNA\n"
    "ATOM     21  C1' DA  B   1      31.000  30.000  30.000  1.00  0.00      DNA\n"
    "ATOM     22  P   DT  B   2      32.000  30.000  30.000  1.00  0.00      DNA\n"
    "END\n"
)


def test_parse_exclude_dna():
    full = parse_protein_pdb(_SYNTH_PROT_DNA, exclude_dna=False)
    stripped = parse_protein_pdb(_SYNTH_PROT_DNA, exclude_dna=True)
    assert len(full.atoms) == 12          # 9 protein + 3 DNA
    assert len(stripped.atoms) == 9       # DNA removed
    assert {a.res_name for a in stripped.atoms} == {"ALA", "CYS"}


def test_classify_complex():
    from backend.core.protein import classify_pdb_content
    assert classify_pdb_content(_SYNTH_PROT_DNA) == (True, True)


def test_pdb_auto_complex_needs_dna_decision_then_imports(_clean_state):
    # Undecided → ask, no import yet.
    r = client.post("/api/design/import/pdb-auto", json={"content": _SYNTH_PROT_DNA})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body.get("needs_dna_decision") is True
    assert body["has_dna"] and body["has_protein"]
    assert body["imported"] == {"dna": False, "protein": False}
    content = body["content"]
    assert len(design_state.get_design().protein_attachments) == 0   # nothing imported yet

    # Remove DNA → protein-only asset (9 atoms).
    r2 = client.post("/api/design/import/pdb-auto",
                     json={"content": content, "remove_dna_from_protein": True})
    assert r2.json()["protein"]["atom_count"] == 9


def test_pdb_auto_complex_keep_dna(_clean_state):
    r = client.post("/api/design/import/pdb-auto",
                    json={"content": _SYNTH_PROT_DNA, "remove_dna_from_protein": False})
    assert r.json()["protein"]["atom_count"] == 12   # DNA kept in the protein object


def test_import_places_free_protein_and_logs(_clean_state):
    r = client.post("/api/design/import/pdb-auto", json={"content": _SYNTH_PDB, "name": "synth"})
    assert r.status_code == 200, r.text
    assert r.json()["imported"] == {"dna": False, "protein": True}
    d = design_state.get_design()
    assert len(d.protein_attachments) == 1
    assert d.protein_attachments[0].target.kind == "free"
    # Import is recorded in the feature log.
    assert d.feature_log[-1].op_kind == "protein-import"


def test_gizmo_move_to_pose_math():
    from backend.core.protein import gizmo_move_to_pose
    new = gizmo_move_to_pose(np.eye(4), pivot=[0, 0, 0],
                             translation=[5, 0, 0], rotation=[0, 0, 0, 1])
    assert np.allclose(new[:3, 3], [5, 0, 0])


def test_gizmo_move_translates_free_protein_and_logs(_clean_state):
    client.post("/api/design/import/pdb-auto", json={"content": _SYNTH_PDB})
    att_id = design_state.get_design().protein_attachments[-1].id

    before = client.get("/api/design/protein/atomistic").json()
    c0 = np.mean([[a["x"], a["y"], a["z"]] for a in before["atoms"]], axis=0)

    r = client.patch(f"/api/design/protein/attachments/{att_id}",
                     json={"gizmo_move": {"pivot": [0, 0, 0],
                                          "translation": [5, 0, 0],
                                          "rotation": [0, 0, 0, 1]}})
    assert r.status_code == 200, r.text
    after = client.get("/api/design/protein/atomistic").json()
    c1 = np.mean([[a["x"], a["y"], a["z"]] for a in after["atoms"]], axis=0)
    assert np.allclose(c1 - c0, [5, 0, 0], atol=1e-4)   # whole protein translated +5 in x
    assert design_state.get_design().feature_log[-1].op_kind == "protein-attach-patch"
