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
from concurrent.futures import ThreadPoolExecutor
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
    RoutingClusterLogEntry,
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
    assert (
        meta["atom_count"] == len(asset.atoms) == 9
    )  # 9 protein atoms (water+ion dropped)
    assert meta["residue_count"] == 2  # ALA + CYS
    assert meta["chain_ids"] == asset.metadata.get("chain_ids", [])
    assert (
        meta["default_conjugation_atom_serial"] == asset.default_conjugation_atom_serial
    )
    assert (
        "atoms" not in meta
    )  # metadata-only — the heavy atom list must not be embedded


def test_parse_keeps_protein_drops_water_ions():
    asset = parse_protein_pdb(_SYNTH_PDB, name="synth", source_filename="synth.pdb")
    res = {a.res_name for a in asset.atoms}
    assert res == {"ALA", "CYS"}, f"water/ions not dropped: {res}"
    assert len(asset.atoms) == 9
    assert asset.name == "synth"
    assert asset.metadata["residue_count"] == 2
    assert asset.metadata["chain_ids"] == ["PROA"]  # falls back to segid


def test_element_inference_charmm_blank_column():
    """Blank element column → infer from name; 'CA' is carbon, 'SG' is sulfur."""
    asset = parse_protein_pdb(_SYNTH_PDB)
    by_name = {(a.res_name, a.name): a for a in asset.atoms}
    assert by_name[("ALA", "CA")].element == "C"  # NOT calcium
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
    att = ProteinAttachment(
        asset_id=asset.id, target=ProteinTargetDesign(overhang_id="ovhg_h0_5_3p")
    )
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
    d.protein_attachments = [
        ProteinAttachment(
            asset_id=asset.id,
            target=ProteinTargetDesign(overhang_id="ovhg_h0_5_3p"),
        )
    ]

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
        id="oh_helix",
        axis_start=Vec3(x=2.5, y=0.0, z=0.0),
        axis_end=Vec3(x=2.5, y=0.0, z=8 * BDNA_RISE_PER_BP),
        phase_offset=0.0,
        length_bp=8,
        grid_pos=(0, 0),
    )
    oh_strand = Strand(
        id="oh_strand",
        domains=[
            Domain(
                helix_id="oh_helix",
                start_bp=0,
                end_bp=7,
                direction=Direction.FORWARD,
                overhang_id="oh_5p",
            )
        ],
        strand_type=StrandType.STAPLE,
    )
    return base.model_copy(
        update={
            "helices": [*base.helices, oh_helix],
            "strands": [*base.strands, oh_strand],
            "overhangs": [
                OverhangSpec(
                    id="oh_5p", helix_id="oh_helix", strand_id="oh_strand", label="OHA"
                )
            ],
        }
    )


def test_resolve_overhang_anchor_points_outward():
    # Synthetic nucs: root at z=0, free tip at z=2 → outward should be +z.
    nucs = [
        {
            "overhang_id": "ov",
            "backbone_position": [1.0, 0.0, 0.0],
            "axis_tangent": [0, 0, 1],
        },
        {
            "overhang_id": "ov",
            "backbone_position": [1.0, 0.0, 2.0],
            "is_three_prime": True,
            "axis_tangent": [0, 0, 1],
        },
    ]
    tip, outward = resolve_overhang_anchor(nucs, "ov", "free_end")
    assert np.allclose(tip, [1.0, 0.0, 2.0])
    assert np.allclose(outward, [0.0, 0.0, 1.0])


def test_compose_places_conjugation_at_tip_body_outward():
    asset = parse_protein_pdb(_SYNTH_PDB)
    att = ProteinAttachment(
        asset_id=asset.id,
        target=ProteinTargetDesign(overhang_id="ov"),
        conjugation_atom_serial=asset.default_conjugation_atom_serial,
    )
    tip = np.array([1.0, 0.0, 2.0])
    outward = np.array([0.0, 0.0, 1.0])
    m = compose_protein_world_transform(asset, att, tip, outward)
    conj = next(a for a in asset.atoms if a.serial == att.conjugation_atom_serial)
    cw = m @ np.array([conj.x, conj.y, conj.z, 1.0])
    assert np.allclose(cw[:3], tip, atol=1e-6)  # conjugation atom at the tip
    com = m @ np.array([*asset.center_of_mass, 1.0])
    assert float(np.dot(com[:3] - tip, outward)) > 0  # protein body points outward


@pytest.fixture
def _clean_state():
    design_state.set_design(_design_with_overhang())
    for a in design_state.list_protein_assets():
        design_state.remove_protein_asset(a.id)
    yield
    design_state.close_session()


def _import_protein() -> str:
    r = client.post(
        "/api/design/protein/import", json={"content": _SYNTH_PDB, "name": "synth"}
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def test_attach_embeds_asset_and_preserves_topology(_clean_state):
    asset_id = _import_protein()
    strands_before = [s.id for s in design_state.get_design().strands]

    r = client.post(
        "/api/design/protein/attachments",
        json={"asset_id": asset_id, "overhang_id": "oh_5p"},
    )
    assert r.status_code == 201, r.text
    att_id = r.json()["attachment_id"]

    d = design_state.get_design()
    assert len(d.protein_attachments) == 1
    assert d.protein_attachments[0].id == att_id
    assert any(a.id == asset_id for a in d.protein_assets)  # asset embedded
    assert [s.id for s in d.strands] == strands_before  # topology untouched


def test_placement_endpoint_places_protein_at_overhang(_clean_state):
    asset_id = _import_protein()

    # Library-only (no attachment) renders NOTHING — the design's attachments are
    # the single source of truth (no render-at-origin fallback).
    before = client.get("/api/design/protein/atomistic").json()
    assert len(before["atoms"]) == 0

    client.post(
        "/api/design/protein/attachments",
        json={"asset_id": asset_id, "overhang_id": "oh_5p"},
    )

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
        {
            "overhang_id": "ov",
            "backbone_position": [1, 0, 0],
            "axis_tangent": [0, 0, 1],
        },
        {
            "overhang_id": "ov",
            "backbone_position": [1, 0, 2],
            "is_three_prime": True,
            "axis_tangent": [0, 0, 1],
        },
        {"strand_id": "bnd", "backbone_position": [1, 0, 2], "is_five_prime": True},
        {"strand_id": "bnd", "backbone_position": [1, 0, 0], "is_three_prime": True},
    ]
    assert azide_attach_end(nucs, "ov", "bnd", "5p") == "free_end"
    assert azide_attach_end(nucs, "ov", "bnd", "3p") == "root"


def _set_sequenced_overhang():
    d = _design_with_overhang()
    design_state.set_design(d)
    response = client.patch(
        "/api/design/overhang/oh_5p", json={"sequence": "ACGTACGT"}
    )
    assert response.status_code == 200, response.text


def test_conjugate_creates_binder_and_attachment(_clean_state):
    _set_sequenced_overhang()
    asset_id = _import_protein()
    strands_before = {s.id for s in design_state.get_design().strands}

    r = client.post(
        "/api/design/protein/conjugate",
        json={"asset_id": asset_id, "overhang_id": "oh_5p", "azide_end": "5p"},
    )
    assert r.status_code == 201, r.text
    payload = r.json()
    binder_id = payload["binder_strand_id"]
    validation = payload["element_validation"]
    assert validation["valid"], validation
    assert validation["failed_metrics"] == []
    assert validation["metrics"]["anchor_error_nm"]["value"] <= 1.0e-4
    assert validation["metrics"]["binder_cardinality"]["value"] == 1
    process = payload["process_metrics"]
    assert process["operation_id"]
    assert process["outcome"] == "committed"
    assert process["total_ms"] >= 0
    assert set(process["stages_ms"]) == {
        "resolve_inputs",
        "build_binder",
        "resolve_geometry",
        "commit",
        "validate_element",
    }

    d = design_state.get_design()
    # (1) the handle is a real overhang-binding domain
    binder = next(s for s in d.strands if s.id == binder_id)
    assert binder.id not in strands_before
    assert binder.strand_type == StrandType.OH_BINDER
    assert any(dom.binds_overhang_id == "oh_5p" for dom in binder.domains)
    assert binder.sequence and len(binder.sequence) == 8  # RC of the 8-nt overhang
    # (2) the protein is attached at the chosen site, asset embedded
    assert len(d.protein_attachments) == 1
    att = d.protein_attachments[0]
    assert att.target.overhang_id == "oh_5p"
    assert att.conjugation_atom_serial is not None
    assert att.conjugation_chemistry in {"lys", "cys", "nterm"}
    assert att.conjugation_accessible_fraction is not None
    evidence = validation["metrics"]["selection_evidence"]
    assert evidence["passed"] and evidence["value"]["persisted"]
    assert att.target.attach_end in ("free_end", "root")
    assert any(a.id == asset_id for a in d.protein_assets)


def test_conjugate_converts_imported_free_placement_without_duplication(_clean_state):
    _set_sequenced_overhang()
    client.post(
        "/api/design/import/pdb-auto", json={"content": _SYNTH_PDB, "name": "synth"}
    )
    before = design_state.get_design()
    source = before.protein_attachments[0]

    r = client.post(
        "/api/design/protein/conjugate",
        json={
            "asset_id": source.asset_id,
            "source_attachment_id": source.id,
            "overhang_id": "oh_5p",
            "azide_end": "5p",
        },
    )
    assert r.status_code == 201, r.text
    assert r.json()["element_validation"]["valid"]
    d = design_state.get_design()
    assert len(d.protein_assets) == 1
    assert len(d.protein_attachments) == 1
    assert d.protein_attachments[0].id == source.id
    assert d.protein_attachments[0].target.kind == "overhang"


def test_conjugate_rejects_mismatched_source_attachment(_clean_state):
    _set_sequenced_overhang()
    client.post("/api/design/import/pdb-auto", json={"content": _SYNTH_PDB})
    source = design_state.get_design().protein_attachments[0]
    other_asset_id = _import_protein()
    r = client.post(
        "/api/design/protein/conjugate",
        json={
            "asset_id": other_asset_id,
            "source_attachment_id": source.id,
            "overhang_id": "oh_5p",
        },
    )
    assert r.status_code == 400


def test_conjugate_does_not_orphan_binder_when_source_is_already_attached(_clean_state):
    _set_sequenced_overhang()
    asset_id = _import_protein()
    first = client.post(
        "/api/design/protein/conjugate",
        json={"asset_id": asset_id, "overhang_id": "oh_5p"},
    )
    source_id = first.json()["attachment_id"]
    strands_before = [s.id for s in design_state.get_design().strands]
    r = client.post(
        "/api/design/protein/conjugate",
        json={
            "asset_id": asset_id,
            "source_attachment_id": source_id,
            "overhang_id": "oh_5p",
        },
    )
    assert r.status_code == 409
    assert [s.id for s in design_state.get_design().strands] == strands_before


def test_conjugate_rejects_an_occupied_overhang_without_mutation(_clean_state):
    _set_sequenced_overhang()
    first_asset = _import_protein()
    assert client.post(
        "/api/design/protein/conjugate",
        json={"asset_id": first_asset, "overhang_id": "oh_5p"},
    ).status_code == 201
    second_asset = _import_protein()
    before = design_state.get_design().model_dump(mode="json")
    r = client.post(
        "/api/design/protein/conjugate",
        json={"asset_id": second_asset, "overhang_id": "oh_5p"},
    )
    assert r.status_code == 422
    assert "binder_cardinality" in r.json()["detail"]["element_validation"][
        "failed_metrics"
    ]
    assert design_state.get_design().model_dump(mode="json") == before


def test_conjugate_operation_id_prevents_duplicate_commit(_clean_state):
    _set_sequenced_overhang()
    asset_id = _import_protein()
    body = {
        "asset_id": asset_id,
        "overhang_id": "oh_5p",
        "operation_id": "conjugation-request-1",
    }
    first = client.post("/api/design/protein/conjugate", json=body)
    assert first.status_code == 201
    before = design_state.get_design().model_dump(mode="json")
    second = client.post("/api/design/protein/conjugate", json=body)
    assert second.status_code == 409
    assert design_state.get_design().model_dump(mode="json") == before


def test_conjugate_rejects_stale_design_revision_before_commit(_clean_state):
    _set_sequenced_overhang()
    asset_id = _import_protein()
    stale_revision = design_state.revision()
    design_state.set_design_silent(design_state.get_design().model_copy(deep=True))
    current = design_state.get_design().model_dump(mode="json")
    r = client.post(
        "/api/design/protein/conjugate",
        json={
            "asset_id": asset_id,
            "overhang_id": "oh_5p",
            "expected_revision": stale_revision,
        },
    )
    assert r.status_code == 409
    assert r.json()["detail"]["expected_revision"] == stale_revision
    assert r.json()["detail"]["current_revision"] == stale_revision + 1
    assert design_state.get_design().model_dump(mode="json") == current


def test_concurrent_conjugate_requests_commit_exactly_once(_clean_state):
    _set_sequenced_overhang()
    asset_id = _import_protein()
    revision = design_state.revision()
    body = {
        "asset_id": asset_id,
        "overhang_id": "oh_5p",
        "operation_id": "concurrent-conjugation-1",
        "expected_revision": revision,
    }
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(
            pool.map(
                lambda _: client.post("/api/design/protein/conjugate", json=body),
                range(2),
            )
        )
    assert sorted(r.status_code for r in responses) == [201, 409]
    design = design_state.get_design()
    assert len(design.protein_attachments) == 1
    binders = [
        strand
        for strand in design.strands
        if any(domain.binds_overhang_id == "oh_5p" for domain in strand.domains)
    ]
    assert len(binders) == 1
    assert sum(entry.op_kind == "protein-conjugate" for entry in design.feature_log) == 1


def test_conjugate_validation_exception_leaves_design_and_undo_history_untouched(
    _clean_state, monkeypatch
):
    _set_sequenced_overhang()
    asset_id = _import_protein()
    before = design_state.get_design().model_dump(mode="json")
    with design_state._lock:
        history_len = len(design_state._session().history)

    def _boom(*args, **kwargs):
        raise RuntimeError("injected validation failure")

    monkeypatch.setattr(
        "backend.core.protein_validation.validate_protein_conjugate", _boom
    )
    no_raise_client = TestClient(app, raise_server_exceptions=False)
    r = no_raise_client.post(
        "/api/design/protein/conjugate",
        json={"asset_id": asset_id, "overhang_id": "oh_5p"},
    )
    assert r.status_code == 500
    assert design_state.get_design().model_dump(mode="json") == before
    with design_state._lock:
        assert len(design_state._session().history) == history_len


def test_conjugate_invalid_site_is_rejected_atomically_with_metrics(_clean_state):
    _set_sequenced_overhang()
    asset_id = _import_protein()
    before = design_state.get_design().model_dump(mode="json")
    r = client.post(
        "/api/design/protein/conjugate",
        json={
            "asset_id": asset_id,
            "overhang_id": "oh_5p",
            "conjugation_atom_serial": 999999,
            "operation_id": "bad-site-1",
        },
    )
    assert r.status_code == 422
    detail = r.json()["detail"]
    assert detail["process_metrics"]["outcome"] == "rejected_invalid"
    assert "conjugation_atom_integrity" in detail["element_validation"]["failed_metrics"]
    assert design_state.get_design().model_dump(mode="json") == before


def test_persisted_validation_detects_voltron_free_plus_conjugated_duplicate(
    _clean_state,
):
    _set_sequenced_overhang()
    imported = client.post(
        "/api/design/import/pdb-auto", json={"content": _SYNTH_PDB, "name": "synth"}
    )
    assert imported.status_code == 200
    asset_id = imported.json()["protein"]["id"]
    committed = client.post(
        "/api/design/protein/conjugate",
        json={"asset_id": asset_id, "overhang_id": "oh_5p"},
    )
    assert committed.status_code == 201

    r = client.get("/api/design/protein/validation")
    assert r.status_code == 200, r.text
    report = r.json()
    assert not report["valid"]
    assert report["summary"] == {
        "asset_count": 1,
        "placement_count": 2,
        "free_placement_count": 1,
        "conjugated_placement_count": 1,
        "failed_element_count": 0,
        "error_count": 1,
        "warning_count": 0,
    }
    duplicate = next(
        f
        for f in report["findings"]
        if f["code"] == "legacy_unconverted_free_placement"
    )
    assert duplicate["repairable"] is True
    assert len(duplicate["free_attachment_ids"]) == 1
    assert duplicate["conjugated_attachment_ids"] == [
        committed.json()["attachment_id"]
    ]

    repair_body = {
        "free_attachment_id": duplicate["free_attachment_ids"][0],
        "conjugated_attachment_id": duplicate["conjugated_attachment_ids"][0],
    }
    preview = client.post(
        "/api/design/protein/validation/repair-duplicate", json=repair_body
    )
    assert preview.status_code == 200
    assert preview.json()["applied"] is False
    assert len(design_state.get_design().protein_attachments) == 2

    applied = client.post(
        "/api/design/protein/validation/repair-duplicate",
        json={**repair_body, "apply": True},
    )
    assert applied.status_code == 200, applied.text
    assert applied.json()["validation_after"]["valid"]
    assert len(design_state.get_design().protein_attachments) == 1
    assert design_state.get_design().protein_attachments[0].id == repair_body[
        "conjugated_attachment_id"
    ]
    assert design_state.get_design().feature_log[-1].params["repair"] == (
        "legacy-import-conjugate-duplicate"
    )

    assert client.post("/api/design/undo").status_code == 200
    assert len(design_state.get_design().protein_attachments) == 2
    assert client.post("/api/design/redo").status_code == 200
    assert len(design_state.get_design().protein_attachments) == 1


def test_persisted_validation_survives_design_serialization(_clean_state):
    from backend.core.design_geometry import _geometry_for_design
    from backend.core.protein_validation import audit_protein_design

    _set_sequenced_overhang()
    asset_id = _import_protein()
    r = client.post(
        "/api/design/protein/conjugate",
        json={"asset_id": asset_id, "overhang_id": "oh_5p"},
    )
    assert r.status_code == 201
    design = design_state.get_design()
    geometry = _geometry_for_design(design)
    before = audit_protein_design(design, geometry)
    restored = Design.model_validate_json(design.model_dump_json())
    after = audit_protein_design(restored, _geometry_for_design(restored))
    assert before == after


def test_conjugate_save_load_preserves_identity_topology_and_validation(
    _clean_state, tmp_path
):
    _set_sequenced_overhang()
    asset_id = _import_protein()
    committed = client.post(
        "/api/design/protein/conjugate",
        json={"asset_id": asset_id, "overhang_id": "oh_5p"},
    )
    assert committed.status_code == 201, committed.text
    before = client.get("/api/design/protein/validation").json()
    attachment_id = committed.json()["attachment_id"]
    binder_id = committed.json()["binder_strand_id"]
    save_path = tmp_path / "protein-conjugate.nadoc"
    saved = client.post("/api/design/save", json={"path": str(save_path)})
    assert saved.status_code == 200, saved.text

    design_state.set_design(Design())
    loaded = client.post("/api/design/load", json={"path": str(save_path)})
    assert loaded.status_code == 200, loaded.text
    restored = design_state.get_design()
    assert [a.id for a in restored.protein_attachments] == [attachment_id]
    assert any(s.id == binder_id for s in restored.strands)
    after = client.get("/api/design/protein/validation").json()
    before.pop("audit_ms")
    after.pop("audit_ms")
    before.pop("process_metrics")
    after.pop("process_metrics")
    assert after == before


def test_conjugated_pose_matches_viewer_atomistic_export_and_oxdna_beads(_clean_state):
    from backend.core.design_geometry import _geometry_for_design
    from backend.core.protein import build_protein_attachment_atoms
    from backend.physics.oxdna_protein import build_protein_blocks

    _set_sequenced_overhang()
    asset_id = _import_protein()
    r = client.post(
        "/api/design/protein/conjugate",
        json={"asset_id": asset_id, "overhang_id": "oh_5p"},
    )
    assert r.status_code == 201
    design = design_state.get_design()
    geometry = _geometry_for_design(design)

    viewer_model = client.get("/api/design/protein/atomistic").json()
    viewer = viewer_model["atoms"]
    exported, exported_bonds, _ = build_protein_attachment_atoms(
        design, geometry=geometry
    )
    assert len(viewer) == len(exported)
    viewer_xyz = np.array([[a["x"], a["y"], a["z"]] for a in viewer])
    export_xyz = np.array([[a.x, a.y, a.z] for a in exported])
    # Viewer JSON intentionally rounds coordinates to 5 decimals; export keeps
    # full precision. Their discrepancy must stay below that display quantum.
    assert np.max(np.linalg.norm(viewer_xyz - export_xyz, axis=1)) <= 1.0e-5
    assert viewer_model["bonds"]
    assert {tuple(pair) for pair in viewer_model["bonds"]} == set(exported_bonds)

    attachments, blocks = build_protein_blocks(design, geometry)
    assert [a.id for a in attachments] == [r.json()["attachment_id"]]
    viewer_ca = {
        (atom["chain_id"], atom["seq_num"]): np.array(
            [atom["x"], atom["y"], atom["z"]]
        )
        for atom in viewer
        if atom["name"] == "CA"
    }
    assert blocks and blocks[0]
    for bead in blocks[0]:
        assert np.allclose(
            bead.pos_nm, viewer_ca[(bead.chain_id, bead.res_seq)], atol=1.0e-5
        )


def test_conjugate_azide_end_flips_attach_end(_clean_state):
    _set_sequenced_overhang()
    asset_id = _import_protein()
    r5 = client.post(
        "/api/design/protein/conjugate",
        json={"asset_id": asset_id, "overhang_id": "oh_5p", "azide_end": "5p"},
    )
    end5 = design_state.get_design().protein_attachments[-1].target.attach_end
    client.post("/api/design/undo")
    r3 = client.post(
        "/api/design/protein/conjugate",
        json={"asset_id": asset_id, "overhang_id": "oh_5p", "azide_end": "3p"},
    )
    end3 = design_state.get_design().protein_attachments[-1].target.attach_end
    assert r5.status_code == 201 and r3.status_code == 201
    assert {end5, end3} == {
        "free_end",
        "root",
    }  # the two azide ends land on opposite ends


def test_conjugate_one_undo_reverts_binder_and_attachment(_clean_state):
    _set_sequenced_overhang()
    asset_id = _import_protein()
    n_strands = len(design_state.get_design().strands)
    client.post(
        "/api/design/protein/conjugate",
        json={"asset_id": asset_id, "overhang_id": "oh_5p", "azide_end": "5p"},
    )
    assert len(design_state.get_design().strands) == n_strands + 1
    r = client.post("/api/design/undo")
    assert r.status_code == 200, r.text
    d = design_state.get_design()
    assert len(d.strands) == n_strands  # binder gone
    assert len(d.protein_attachments) == 0  # attachment gone (single undo)


def test_undo_import_removes_rendered_protein(_clean_state):
    # Free import → protein renders; undo → it disappears (no orphan at origin).
    client.post(
        "/api/design/import/pdb-auto", json={"content": _SYNTH_PDB, "name": "synth"}
    )
    assert len(client.get("/api/design/protein/atomistic").json()["atoms"]) == 9
    r = client.post("/api/design/undo")
    assert r.status_code == 200, r.text
    assert len(design_state.get_design().protein_attachments) == 0
    assert (
        len(client.get("/api/design/protein/atomistic").json()["atoms"]) == 0
    )  # gone, not at origin


def test_delete_attachment_clears_render(_clean_state):
    client.post(
        "/api/design/import/pdb-auto", json={"content": _SYNTH_PDB, "name": "synth"}
    )
    att_id = design_state.get_design().protein_attachments[0].id
    client.delete(f"/api/design/protein/attachments/{att_id}")
    assert len(client.get("/api/design/protein/atomistic").json()["atoms"]) == 0


def test_delete_protein_import_feature_clears_render(_clean_state):
    # Deleting the protein-import feature-log row must remove the imported
    # protein from the view (it's a root op: the asset/attachment it created
    # have no other creating entry in the log).
    client.post(
        "/api/design/import/pdb-auto", json={"content": _SYNTH_PDB, "name": "synth"}
    )
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
    client.post(
        "/api/design/import/pdb-auto", json={"content": _SYNTH_PDB, "name": "synth1"}
    )
    client.post(
        "/api/design/import/pdb-auto", json={"content": _SYNTH_PDB, "name": "synth2"}
    )
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


def test_delete_earlier_protein_import_keeps_independent_later_import(_clean_state):
    # Reference-based delete: a later protein import that does not reference the
    # first import's ids survives. Non-reconstructable alone is not a dependency.
    client.post(
        "/api/design/import/pdb-auto", json={"content": _SYNTH_PDB, "name": "synth1"}
    )
    first_idx = len(design_state.get_design().feature_log) - 1
    client.post(
        "/api/design/import/pdb-auto", json={"content": _SYNTH_PDB, "name": "synth2"}
    )
    r = client.delete(f"/api/design/features/{first_idx}")
    assert r.status_code == 200, r.text
    j = r.json()
    assert not j.get("needs_cascade_decision")
    after = design_state.get_design()
    assert len(after.protein_attachments) == 1
    assert len(after.protein_assets) == 1
    assert len(client.get("/api/design/protein/atomistic").json()["atoms"]) == 9


def test_patch_visible_false_hides_protein(_clean_state):
    asset_id = _import_protein()
    att_id = client.post(
        "/api/design/protein/attachments",
        json={"asset_id": asset_id, "overhang_id": "oh_5p"},
    ).json()["attachment_id"]

    r = client.patch(
        f"/api/design/protein/attachments/{att_id}", json={"visible": False}
    )
    assert r.status_code == 200, r.text
    # Hidden, NOT relocated to the origin.
    hidden = client.get("/api/design/protein/atomistic").json()
    assert len(hidden["atoms"]) == 0


def test_patch_rejects_invalid_conjugation_site_without_mutation(_clean_state):
    asset_id = _import_protein()
    att_id = client.post(
        "/api/design/protein/attachments",
        json={"asset_id": asset_id, "overhang_id": "oh_5p"},
    ).json()["attachment_id"]
    before = design_state.get_design().model_dump(mode="json")
    r = client.patch(
        f"/api/design/protein/attachments/{att_id}",
        json={"conjugation_atom_serial": 999999},
    )
    assert r.status_code == 422
    assert design_state.get_design().model_dump(mode="json") == before


def test_delete_attachment(_clean_state):
    asset_id = _import_protein()
    att_id = client.post(
        "/api/design/protein/attachments",
        json={"asset_id": asset_id, "overhang_id": "oh_5p"},
    ).json()["attachment_id"]
    r = client.delete(f"/api/design/protein/attachments/{att_id}")
    assert r.status_code == 200, r.text
    assert len(design_state.get_design().protein_attachments) == 0


def test_delete_conjugate_removes_owned_binder_and_undo_restores_both(_clean_state):
    _set_sequenced_overhang()
    asset_id = _import_protein()
    created = client.post(
        "/api/design/protein/conjugate",
        json={"asset_id": asset_id, "overhang_id": "oh_5p"},
    ).json()
    r = client.delete(
        f"/api/design/protein/attachments/{created['attachment_id']}"
    )
    assert r.status_code == 200, r.text
    design = design_state.get_design()
    assert not any(a.id == created["attachment_id"] for a in design.protein_attachments)
    assert not any(s.id == created["binder_strand_id"] for s in design.strands)

    assert client.post("/api/design/undo").status_code == 200
    restored = design_state.get_design()
    assert any(a.id == created["attachment_id"] for a in restored.protein_attachments)
    assert any(s.id == created["binder_strand_id"] for s in restored.strands)


def test_delete_display_only_overhang_attachment_keeps_unowned_topology(_clean_state):
    asset_id = _import_protein()
    strands_before = [s.id for s in design_state.get_design().strands]
    attachment_id = client.post(
        "/api/design/protein/attachments",
        json={"asset_id": asset_id, "overhang_id": "oh_5p"},
    ).json()["attachment_id"]
    assert client.delete(
        f"/api/design/protein/attachments/{attachment_id}"
    ).status_code == 200
    assert [s.id for s in design_state.get_design().strands] == strands_before


def test_delete_then_reconjugate_same_overhang_is_clean(_clean_state):
    _set_sequenced_overhang()
    asset_id = _import_protein()
    first = client.post(
        "/api/design/protein/conjugate",
        json={"asset_id": asset_id, "overhang_id": "oh_5p"},
    ).json()
    assert client.delete(
        f"/api/design/protein/attachments/{first['attachment_id']}"
    ).status_code == 200
    second = client.post(
        "/api/design/protein/conjugate",
        json={"asset_id": asset_id, "overhang_id": "oh_5p"},
    )
    assert second.status_code == 201, second.text
    design = design_state.get_design()
    assert len(design.protein_attachments) == 1
    assert sum(
        any(domain.binds_overhang_id == "oh_5p" for domain in strand.domains)
        for strand in design.strands
    ) == 1


def test_attach_unknown_overhang_404(_clean_state):
    asset_id = _import_protein()
    r = client.post(
        "/api/design/protein/attachments",
        json={"asset_id": asset_id, "overhang_id": "nope"},
    )
    assert r.status_code == 404


# ── Merged "Import PDB": classification + auto-routing ──────────────────────────

_DD12_DNA = "backend/data/dd12_na.pdb"  # Drew-Dickerson dodecamer (B-DNA)


def test_classify_pdb_content():
    from backend.core.protein import classify_pdb_content

    assert classify_pdb_content(_SYNTH_PDB) == (False, True)  # protein only
    dna = open(_DD12_DNA).read()
    assert classify_pdb_content(dna) == (True, False)  # DNA only
    # Water/ions alone classify as neither.
    water = (
        "ATOM      1  OH2 TIP3    1       0.000   0.000   0.000  1.00  0.00      WAT\n"
    )
    assert classify_pdb_content(water) == (False, False)


def test_pdb_auto_routes_protein_to_library_without_touching_design(_clean_state):
    strands_before = [s.id for s in design_state.get_design().strands]
    r = client.post(
        "/api/design/import/pdb-auto", json={"content": _SYNTH_PDB, "name": "synth"}
    )
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

    monkeypatch.setattr(
        pdb_to_design, "import_pdb", lambda content: (make_minimal_design(), None, [])
    )
    monkeypatch.setattr(
        pdb_to_design,
        "merge_pdb_into_design",
        lambda d, content: (make_minimal_design(), None, []),
    )

    dna = open(_DD12_DNA).read()
    r = client.post("/api/design/import/pdb-auto", json={"content": dna})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["imported"]["dna"] is True
    assert "design" in body and body["design"]["helices"]  # full design response


def test_pdb_auto_rejects_empty_and_irrelevant(_clean_state):
    assert client.post("/api/design/import/pdb-auto", json={}).status_code == 400
    water = (
        "ATOM      1  OH2 TIP3    1       0.000   0.000   0.000  1.00  0.00      WAT\n"
    )
    response = client.post("/api/design/import/pdb-auto", json={"content": water})
    assert response.status_code == 400


def test_pdb_auto_enforces_input_and_atom_resource_limits(_clean_state, monkeypatch):
    from backend.api import routes_design_interchange

    before = design_state.get_design().model_dump(mode="json")
    monkeypatch.setattr(routes_design_interchange, "MAX_PDB_INPUT_BYTES", 10)
    too_many_bytes = client.post(
        "/api/design/import/pdb-auto", json={"content": _SYNTH_PDB}
    )
    assert too_many_bytes.status_code == 413
    assert design_state.get_design().model_dump(mode="json") == before

    monkeypatch.setattr(routes_design_interchange, "MAX_PDB_INPUT_BYTES", 50_000)
    monkeypatch.setattr(routes_design_interchange, "MAX_PROTEIN_ATOMS", 1)
    too_many_atoms = client.post(
        "/api/design/import/pdb-auto", json={"content": _SYNTH_PDB}
    )
    assert too_many_atoms.status_code == 413
    assert design_state.get_design().model_dump(mode="json") == before


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
    assert len(full.atoms) == 12  # 9 protein + 3 DNA
    assert len(stripped.atoms) == 9  # DNA removed
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
    assert (
        len(design_state.get_design().protein_attachments) == 0
    )  # nothing imported yet

    # Remove DNA → protein-only asset (9 atoms).
    r2 = client.post(
        "/api/design/import/pdb-auto",
        json={"content": content, "remove_dna_from_protein": True},
    )
    assert r2.json()["protein"]["atom_count"] == 9


def test_rcsb_complex_decision_reuses_id_without_echoing_pdb(
    _clean_state, monkeypatch
):
    from backend.api import routes_design_interchange

    monkeypatch.setattr(
        routes_design_interchange, "_download_rcsb_pdb", lambda _pdb_id: _SYNTH_PROT_DNA
    )
    decision = client.post(
        "/api/design/import/pdb-auto", json={"pdb_id": "8scp", "name": "8SCP"}
    )
    assert decision.status_code == 200, decision.text
    payload = decision.json()
    assert payload["needs_dna_decision"] is True
    assert payload["pdb_id"] == "8SCP"
    assert "content" not in payload

    imported = client.post(
        "/api/design/import/pdb-auto",
        json={
            "pdb_id": payload["pdb_id"],
            "name": payload["name"],
            "remove_dna_from_protein": True,
        },
    )
    assert imported.status_code == 200, imported.text
    assert imported.json()["source"] == "rcsb:8SCP"
    assert imported.json()["protein"]["atom_count"] == 9


def test_pdb_auto_complex_keep_dna(_clean_state):
    r = client.post(
        "/api/design/import/pdb-auto",
        json={"content": _SYNTH_PROT_DNA, "remove_dna_from_protein": False},
    )
    assert r.json()["protein"]["atom_count"] == 12  # DNA kept in the protein object


def test_import_places_free_protein_and_logs(_clean_state):
    r = client.post(
        "/api/design/import/pdb-auto", json={"content": _SYNTH_PDB, "name": "synth"}
    )
    assert r.status_code == 200, r.text
    assert r.json()["imported"] == {"dna": False, "protein": True}
    d = design_state.get_design()
    assert len(d.protein_attachments) == 1
    assert d.protein_attachments[0].target.kind == "free"
    # Import is recorded in the feature log.
    assert d.feature_log[-1].op_kind == "protein-import"
    payload = r.json()["protein"]
    assert payload["atom_count"] == 9
    assert payload["bond_count"] > 0
    assert payload["input_atom_record_count"] == 12
    assert payload["filtered_atom_record_count"] == 3
    assert payload["malformed_atom_record_count"] == 0


def test_import_reports_malformed_atom_records(_clean_state):
    malformed = _SYNTH_PDB.replace(
        "ATOM      2  CA  ALA     1       1.500   0.000   0.000  1.00  0.00      PROA\n",
        "ATOM      2 malformed\n",
    )
    response = client.post(
        "/api/design/import/pdb-auto", json={"content": malformed}
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["protein"]["malformed_atom_record_count"] == 1
    assert payload["import_warnings"] == [
        "Skipped 1 malformed ATOM/HETATM record(s)."
    ]


def test_repeated_import_operation_id_is_rejected_without_mutation(_clean_state):
    operation_id = "import-once"
    first_revision = design_state.get_design_with_revision()[1]
    first = client.post(
        "/api/design/import/pdb-auto",
        json={
            "content": _SYNTH_PDB,
            "operation_id": operation_id,
            "expected_revision": first_revision,
        },
    )
    assert first.status_code == 200, first.text
    before = design_state.get_design().model_dump(mode="json")
    current_revision = design_state.get_design_with_revision()[1]

    repeated = client.post(
        "/api/design/import/pdb-auto",
        json={
            "content": _SYNTH_PDB,
            "operation_id": operation_id,
            "expected_revision": current_revision,
        },
    )
    assert repeated.status_code == 409
    assert "already committed" in str(repeated.json()["detail"])
    assert design_state.get_design().model_dump(mode="json") == before


def test_import_conjugate_and_audit_tolerate_routing_cluster_log_entries(
    _clean_state,
):
    design = _design_with_overhang()
    design.feature_log = [RoutingClusterLogEntry()]
    design_state.set_design(design)
    imported = client.post(
        "/api/design/import/pdb-auto",
        json={"content": _SYNTH_PDB, "operation_id": "after-routing-cluster"},
    )
    assert imported.status_code == 200, imported.text
    attachment_id = design_state.get_design().protein_attachments[0].id
    sequenced = client.patch(
        "/api/design/overhang/oh_5p", json={"sequence": "ACGTACGT"}
    )
    assert sequenced.status_code == 200, sequenced.text
    conjugated = client.post(
        "/api/design/protein/conjugate",
        json={
            "asset_id": imported.json()["protein"]["id"],
            "source_attachment_id": attachment_id,
            "overhang_id": "oh_5p",
            "operation_id": "conjugate-after-routing-cluster",
        },
    )
    assert conjugated.status_code == 201, conjugated.text
    audit = client.get("/api/design/protein/validation")
    assert audit.status_code == 200, audit.text
    assert audit.json()["valid"] is True


def test_cancelled_import_is_rejected_before_any_commit(_clean_state, monkeypatch):
    from backend.api import routes_design_interchange

    before = design_state.get_design().model_dump(mode="json")
    library_ids = {asset.id for asset in design_state.list_protein_assets()}

    async def _cancel(*_args, **_kwargs):
        from fastapi import HTTPException

        raise HTTPException(499, detail={"message": "Protein import cancelled before commit."})

    monkeypatch.setattr(
        routes_design_interchange, "_reject_disconnected_import", _cancel
    )
    response = client.post(
        "/api/design/import/pdb-auto",
        json={"content": _SYNTH_PDB, "operation_id": "cancel-before-commit"},
    )
    assert response.status_code == 499
    assert design_state.get_design().model_dump(mode="json") == before
    assert {asset.id for asset in design_state.list_protein_assets()} == library_ids


def test_feature_log_mutation_exception_restores_design_and_history(_clean_state):
    before = design_state.get_design().model_dump(mode="json")

    def _partial_then_fail(design):
        design.metadata.name = "should roll back"
        raise RuntimeError("injected mutation failure")

    with pytest.raises(RuntimeError, match="injected mutation failure"):
        design_state.mutate_with_feature_log(
            "protein-import", "fault injection", {}, _partial_then_fail
        )
    assert design_state.get_design().model_dump(mode="json") == before


def test_import_library_only_is_explicit_measured_and_does_not_place(_clean_state):
    before = design_state.get_design().model_dump(mode="json")
    r = client.post(
        "/api/design/import/pdb-auto",
        json={
            "content": _SYNTH_PDB,
            "name": "library synth",
            "protein_placement": "library",
            "operation_id": "import-library-1",
        },
    )
    assert r.status_code == 200, r.text
    payload = r.json()
    assert payload["protein_placement"] == "library"
    assert payload["process_metrics"]["operation_id"] == "import-library-1"
    assert payload["process_metrics"]["outcome"] == "imported"
    assert set(payload["process_metrics"]["stages_ms"]) == {
        "acquire",
        "classify",
        "parse_protein",
        "deduplicate",
        "commit",
    }
    assert design_state.get_design().model_dump(mode="json") == before
    assert any(a.id == payload["protein"]["id"] for a in design_state.list_protein_assets())


def test_repeated_placed_import_detects_duplicate_but_preserves_independent_assets(
    _clean_state,
):
    first = client.post(
        "/api/design/import/pdb-auto", json={"content": _SYNTH_PDB, "name": "first"}
    ).json()
    second = client.post(
        "/api/design/import/pdb-auto", json={"content": _SYNTH_PDB, "name": "second"}
    ).json()
    assert first["protein"]["deduplicated"] is False
    assert second["protein"]["deduplicated"] is False
    assert second["protein"]["duplicate_detected"] is True
    assert first["protein"]["id"] != second["protein"]["id"]
    design = design_state.get_design()
    assert len(design.protein_assets) == 2
    assert len(design.protein_attachments) == 2  # two explicit Place-in-design actions


def test_repeated_library_import_deduplicates_without_design_lifecycle_coupling(
    _clean_state,
):
    body = {
        "content": _SYNTH_PDB,
        "name": "library copy",
        "protein_placement": "library",
    }
    first = client.post("/api/design/import/pdb-auto", json=body).json()
    second = client.post("/api/design/import/pdb-auto", json=body).json()
    assert first["protein"]["id"] == second["protein"]["id"]
    assert second["protein"]["deduplicated"] is True
    matching = [
        asset
        for asset in design_state.list_protein_assets()
        if asset.id == first["protein"]["id"]
    ]
    assert len(matching) == 1


def test_candidate_endpoint_reports_cache_miss_then_hit(_clean_state):
    from backend.core.conjugation import clear_conjugation_candidate_cache

    clear_conjugation_candidate_cache()
    asset_id = _import_protein()
    first = client.get(
        f"/api/design/protein/conjugation-candidates?asset_id={asset_id}"
    ).json()
    second = client.get(
        f"/api/design/protein/conjugation-candidates?asset_id={asset_id}"
    ).json()
    assert first["candidates"] == second["candidates"]
    assert first["process_metrics"]["cache_hit"] is False
    assert second["process_metrics"]["cache_hit"] is True
    assert first["process_metrics"]["candidate_count"] == len(first["candidates"])
    assert first["design_revision"] == design_state.revision()


def test_process_metrics_endpoint_aggregates_workflow_without_raw_ids(_clean_state):
    _set_sequenced_overhang()
    imported = client.post(
        "/api/design/import/pdb-auto",
        json={"content": _SYNTH_PDB, "operation_id": "metrics-import"},
    ).json()
    asset_id = imported["protein"]["id"]
    client.get(
        "/api/design/protein/conjugation-candidates",
        params={"asset_id": asset_id, "operation_id": "metrics-candidates"},
    )
    source_id = design_state.get_design().protein_attachments[0].id
    client.post(
        "/api/design/protein/conjugate",
        json={
            "asset_id": asset_id,
            "overhang_id": "oh_5p",
            "source_attachment_id": source_id,
            "operation_id": "metrics-conjugation",
        },
    )
    metrics = client.get("/api/design/protein/metrics").json()
    assert metrics["retained_run_count"] == 3
    assert set(metrics["operations"]) == {
        "candidate_analysis",
        "conjugation",
        "import",
    }
    assert all(
        operation["correlation_rate"] == 1.0
        for operation in metrics["operations"].values()
    )
    assert "metrics-import" not in str(metrics)


def test_gizmo_move_to_pose_math():
    from backend.core.protein import gizmo_move_to_pose

    new = gizmo_move_to_pose(
        np.eye(4), pivot=[0, 0, 0], translation=[5, 0, 0], rotation=[0, 0, 0, 1]
    )
    assert np.allclose(new[:3, 3], [5, 0, 0])


def test_gizmo_move_translates_free_protein_and_logs(_clean_state):
    client.post("/api/design/import/pdb-auto", json={"content": _SYNTH_PDB})
    att_id = design_state.get_design().protein_attachments[-1].id

    before = client.get("/api/design/protein/atomistic").json()
    c0 = np.mean([[a["x"], a["y"], a["z"]] for a in before["atoms"]], axis=0)

    r = client.patch(
        f"/api/design/protein/attachments/{att_id}",
        json={
            "gizmo_move": {
                "pivot": [0, 0, 0],
                "translation": [5, 0, 0],
                "rotation": [0, 0, 0, 1],
            }
        },
    )
    assert r.status_code == 200, r.text
    after = client.get("/api/design/protein/atomistic").json()
    c1 = np.mean([[a["x"], a["y"], a["z"]] for a in after["atoms"]], axis=0)
    assert np.allclose(
        c1 - c0, [5, 0, 0], atol=1e-4
    )  # whole protein translated +5 in x
    assert design_state.get_design().feature_log[-1].op_kind == "protein-attach-patch"
