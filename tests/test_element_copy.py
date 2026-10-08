import pytest
import numpy as np
from backend.core.element_copy import paste_elements
from backend.core.models import (
    Design,
    Nanoparticle,
    ProteinAttachment,
)
from backend.core.nanoparticle import build_thiol_conjugation
from backend.core.design_geometry import fitting_geometry


def test_np_copy_is_independent_and_offsets_owned_dna():
    p = Nanoparticle(diameter_nm=10)
    c, hs, ss = build_thiol_conjugation(
        p, scheme="direct_thiol", sequence="ACGT", count=2
    )
    source = Design(
        nanoparticles=[p], nanoparticle_conjugations=[c], helices=hs, strands=ss
    )
    before = source.model_dump()
    out, refs = paste_elements(source, source, [], [p.id])
    assert source.model_dump() == before
    assert len(out.nanoparticles) == 2
    assert len(out.strands) == 4
    new = out.nanoparticles[-1]
    assert refs == [{"kind": "nanoparticle", "id": new.id}]
    assert new.id != p.id
    offset = new.pose.to_array()[:3, 3]
    assert offset[0] > 10
    old_geom = fitting_geometry(source)
    new_sids = {s.id for s in out.strands[2:]}
    new_geom = [n for n in fitting_geometry(out) if n["strand_id"] in new_sids]
    np.testing.assert_allclose(
        [n["backbone_position"] for n in new_geom],
        np.array([n["backbone_position"] for n in old_geom]) + offset,
    )
    assert {
        r.strand_id for r in out.nanoparticle_conjugations[-1].surface_strands
    } == new_sids
    again, _ = paste_elements(out, source, [], [p.id], 2)
    assert again.nanoparticles[-1].pose.values[3] == 2 * offset[0]


def test_protein_binder_copy_preserves_rotated_dna_and_asset():
    from backend.core.models import (
        ProteinAsset,
        Helix,
        Vec3,
        Strand,
        Domain,
        Direction,
        OverhangSpec,
        ProteinTargetDesign,
    )

    h = Helix(
        id="h",
        axis_start=Vec3(x=0, y=0, z=0),
        axis_end=Vec3(x=0, y=0, z=3.06),
        length_bp=10,
    )
    parent = Strand(
        id="parent",
        domains=[
            Domain(
                helix_id="h",
                start_bp=0,
                end_bp=9,
                direction=Direction.FORWARD,
                overhang_id="oh",
            )
        ],
    )
    binder = Strand(
        id="binder",
        sequence="ACGTACGTAC",
        domains=[
            Domain(
                helix_id="h",
                start_bp=9,
                end_bp=0,
                direction=Direction.REVERSE,
                binds_overhang_id="oh",
            )
        ],
    )
    oh = OverhangSpec(
        id="oh",
        helix_id="h",
        strand_id=parent.id,
        rotation=[0.0, 0.7071067811865475, 0.0, 0.7071067811865476],
    )
    asset = ProteinAsset()
    protein = ProteinAttachment(
        asset_id=asset.id,
        target=ProteinTargetDesign(overhang_id="oh"),
        binder_strand_id=binder.id,
    )
    source = Design(
        helices=[h],
        strands=[parent, binder],
        overhangs=[oh],
        protein_assets=[asset],
        protein_attachments=[protein],
    )
    out, _ = paste_elements(Design(), source, [protein.id], [])
    assert len(out.strands) == 1
    assert out.protein_attachments[0].binder_strand_id == out.strands[0].id
    assert out.protein_attachments[0].target.kind == "free"
    assert out.strands[0].domains[0].binds_overhang_id is None
    assert len(out.protein_assets) == 1
    old = [n for n in fitting_geometry(source) if n["strand_id"] == "binder"]
    new = fitting_geometry(out)
    deltas = np.array([n["backbone_position"] for n in new]) - np.array(
        [n["backbone_position"] for n in old]
    )
    np.testing.assert_allclose(deltas, np.tile(deltas[0], (len(deltas), 1)), atol=1e-8)
    assert deltas[0, 0] > 0
    np.testing.assert_allclose(
        [n["base_normal"] for n in new], [n["base_normal"] for n in old], atol=1e-8
    )


def test_paste_endpoint_undo_redo():
    from fastapi.testclient import TestClient
    from backend.api.main import app
    from backend.api import state

    p = Nanoparticle(diameter_nm=10)
    source = Design(nanoparticles=[p])
    state.set_design(source)
    try:
        client = TestClient(app)
        response = client.post(
            "/api/design/element-paste",
            json={"source": source.model_dump(mode="json"), "nanoparticle_ids": [p.id]},
        )
        assert response.status_code == 200, response.text
        assert len(state.get_design().nanoparticles) == 2
        assert state.get_design().feature_log[-1].op_kind == "element-paste"
        assert client.post("/api/design/undo").status_code == 200
        assert len(state.get_design().nanoparticles) == 1
        assert client.post("/api/design/redo").status_code == 200
        assert len(state.get_design().nanoparticles) == 2
    finally:
        state.close_session()


def test_free_conjugate_move_composes_saved_dna_poses():
    from backend.core.element_copy import move_free_conjugate
    from backend.core.models import ProteinAsset

    p = Nanoparticle(diameter_nm=10)
    c, hs, ss = build_thiol_conjugation(
        p, scheme="direct_thiol", sequence="ACGT", count=1
    )
    design = Design(helices=hs, strands=ss)
    before = fitting_geometry(design)
    delta = np.eye(4)
    delta[:3, 3] = [4, 5, 6]
    move_free_conjugate(design, ss[0].id, delta)
    move_free_conjugate(design, ss[0].id, delta)
    after = fitting_geometry(design)
    np.testing.assert_allclose(
        [n["backbone_position"] for n in after],
        np.array([n["backbone_position"] for n in before]) + [8, 10, 12],
    )
    # A copied free protein with owned DNA must also accept the normal gizmo API.
    from fastapi.testclient import TestClient
    from backend.api.main import app
    from backend.api import state
    from backend.core.models import ProteinTargetFree

    asset = ProteinAsset()
    att = ProteinAttachment(
        asset_id=asset.id, target=ProteinTargetFree(), binder_strand_id=ss[0].id
    )
    design.protein_assets = [asset]
    design.protein_attachments = [att]
    state.set_design(design)
    try:
        response = TestClient(app).patch(
            f"/api/design/protein/attachments/{att.id}",
            json={
                "gizmo_move": {
                    "pivot": [0, 0, 0],
                    "translation": [1, 2, 3],
                    "rotation": [0, 0, 0, 1],
                }
            },
        )
        assert response.status_code == 200, response.text
        moved = fitting_geometry(state.get_design())
        np.testing.assert_allclose(
            [n["backbone_position"] for n in moved],
            np.array([n["backbone_position"] for n in before]) + [9, 12, 15],
        )
    finally:
        state.close_session()


@pytest.mark.parametrize(
    "kind,prefix", [("nanoparticle", "NP"), ("protein", "Protein")]
)
def test_pasted_group_names_increment_past_existing_numbers(kind, prefix):
    from backend.core.models import ProteinAsset, ProteinTargetFree, StapleGroup

    particle = Nanoparticle(diameter_nm=10)
    conjugation, helices, strands = build_thiol_conjugation(
        particle,
        scheme="direct_thiol",
        sequence="ACGT",
        count=1,
    )
    strands[0].name = f"{prefix}-1:S1"
    group = StapleGroup(id="group-1", name=f"{prefix}-1", strand_ids=[strands[0].id])
    source = Design(helices=helices, strands=strands, staple_groups=[group])
    protein_ids, nanoparticle_ids = [], []
    if kind == "nanoparticle":
        source.nanoparticles = [particle]
        source.nanoparticle_conjugations = [conjugation]
        nanoparticle_ids = [particle.id]
    else:
        asset = ProteinAsset()
        protein = ProteinAttachment(
            asset_id=asset.id,
            target=ProteinTargetFree(),
            binder_strand_id=strands[0].id,
        )
        source.protein_assets = [asset]
        source.protein_attachments = [protein]
        protein_ids = [protein.id]
    destination = source.model_copy(
        update={
            "staple_groups": [
                group,
                StapleGroup(id="group-3", name=f"{prefix.lower()}-3"),
            ]
        }
    )
    out, _ = paste_elements(destination, source, protein_ids, nanoparticle_ids)
    assert out.staple_groups[-1].name == f"{prefix}-4"
    assert out.strands[-1].name == f"{prefix}-4:S1"
    again, _ = paste_elements(out, source, protein_ids, nanoparticle_ids, 2)
    assert again.staple_groups[-1].name == f"{prefix}-5"
    assert again.strands[-1].name == f"{prefix}-5:S1"
    assert source.staple_groups[0].name == f"{prefix}-1"
    assert source.strands[0].name == f"{prefix}-1:S1"


def test_paste_allocates_distinct_names_within_batch_and_preserves_custom_oligo_names():
    from backend.core.models import StapleGroup

    particle = Nanoparticle(diameter_nm=10)
    conjugation, helices, strands = build_thiol_conjugation(
        particle,
        scheme="direct_thiol",
        sequence="ACGT",
        count=2,
    )
    strands[0].name = "Custom oligo"
    groups = [
        StapleGroup(id=f"group-{i}", name=f"NP-{i + 1}", strand_ids=[s.id])
        for i, s in enumerate(strands)
    ]
    source = Design(
        nanoparticles=[particle],
        nanoparticle_conjugations=[conjugation],
        helices=helices,
        strands=strands,
        staple_groups=groups,
    )
    out, _ = paste_elements(source, source, [], [particle.id])
    assert [g.name for g in out.staple_groups] == ["NP-1", "NP-2", "NP-3", "NP-4"]
    assert out.strands[2].name == "Custom oligo"
