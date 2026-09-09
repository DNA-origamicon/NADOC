from fastapi.testclient import TestClient
import numpy as np
import pytest

from backend.api import state as design_state
from backend.api.main import app
from backend.core.models import Design, Direction, Domain, Helix, OverhangSpec, Strand, StrandType, Vec3

client = TestClient(app)


@pytest.fixture(autouse=True)
def clean_design():
    design_state.set_design(Design())
    yield
    design_state.close_session()


def test_gold_nanosphere_crud_move_and_feature_log():
    created = client.post(
        "/api/design/nanoparticles/gold-nanospheres", json={"diameter_nm": 12.5}
    )
    assert created.status_code == 201, created.text
    particle_id = created.json()["nanoparticle_id"]
    design = design_state.get_design()
    assert design.nanoparticles[0].diameter_nm == 12.5
    assert design.feature_log[-1].op_kind == "nanoparticle-create"
    assert design.feature_log[-1].params["nanoparticle_id"] == particle_id

    resized = client.patch(
        f"/api/design/nanoparticles/{particle_id}", json={"diameter_nm": 20}
    )
    assert resized.status_code == 200, resized.text
    assert design_state.get_design().nanoparticles[0].diameter_nm == 20
    assert design_state.get_design().feature_log[-1].op_kind == "nanoparticle-patch"

    moved = client.patch(
        f"/api/design/nanoparticles/{particle_id}",
        json={
            "gizmo_move": {
                "pivot": [0, 0, 0],
                "translation": [1, 2, 3],
                "rotation": [0, 0, 0, 1],
            }
        },
    )
    assert moved.status_code == 200, moved.text
    assert design_state.get_design().nanoparticles[0].pose.values[3::4][:3] == [1, 2, 3]

    deleted = client.delete(f"/api/design/nanoparticles/{particle_id}")
    assert deleted.status_code == 200, deleted.text
    assert design_state.get_design().nanoparticles == []
    assert design_state.get_design().feature_log[-1].op_kind == "nanoparticle-delete"


def test_gold_nanosphere_validation_and_undo():
    assert (
        client.post(
            "/api/design/nanoparticles/gold-nanospheres", json={"diameter_nm": 0}
        ).status_code
        == 422
    )
    created = client.post(
        "/api/design/nanoparticles/gold-nanospheres", json={"diameter_nm": 5}
    )
    assert created.status_code == 201
    undone = client.post("/api/design/undo")
    assert undone.status_code == 200
    assert design_state.get_design().nanoparticles == []


def test_gold_nanosphere_persists_through_nadoc_save_and_reload(tmp_path):
    created = client.post(
        "/api/design/nanoparticles/gold-nanospheres", json={"diameter_nm": 17.25}
    )
    particle_id = created.json()["nanoparticle_id"]
    moved = client.patch(
        f"/api/design/nanoparticles/{particle_id}",
        json={
            "gizmo_move": {
                "pivot": [0, 0, 0],
                "translation": [4, -2, 9],
                "rotation": [0, 0, 0, 1],
            }
        },
    )
    assert moved.status_code == 200, moved.text

    save_path = tmp_path / "nanoparticle-roundtrip.nadoc"
    saved = client.post("/api/design/save", json={"path": str(save_path)})
    assert saved.status_code == 200, saved.text
    assert '"nanoparticles"' in save_path.read_text()

    design_state.set_design(Design())
    assert design_state.get_design().nanoparticles == []
    loaded = client.post("/api/design/load", json={"path": str(save_path)})
    assert loaded.status_code == 200, loaded.text

    particle = design_state.get_design().nanoparticles[0]
    assert particle.id == particle_id
    assert particle.kind == "gold_nanosphere"
    assert particle.diameter_nm == 17.25
    assert particle.pose.values[3::4][:3] == [4, -2, 9]
    assert any(
        entry.op_kind == "nanoparticle-create"
        for entry in design_state.get_design().feature_log
    )


def test_thiol_conjugation_creates_real_strands_moves_validates_and_undoes():
    particle_id = client.post(
        "/api/design/nanoparticles/gold-nanospheres", json={"diameter_nm": 10}
    ).json()["nanoparticle_id"]
    estimated = client.post(
        f"/api/design/nanoparticles/{particle_id}/conjugation/estimate",
        json={"scheme": "direct_thiol"},
    )
    assert estimated.status_code == 200
    assert estimated.json()["estimated_capacity"] == 31
    assert estimated.json()["estimated_capacity_range"] == [16, 47]
    assert estimated.json()["source_url"].endswith("ac0613582")

    created = client.put(
        f"/api/design/nanoparticles/{particle_id}/conjugation",
        json={"scheme": "direct_thiol", "sequence": "ACGTAC", "count": 3,
              "attach_end": "5p", "seed": 17},
    )
    assert created.status_code == 200, created.text
    strand_ids = created.json()["strand_ids"]
    design = design_state.get_design()
    assert len(strand_ids) == 3
    assert all(design.find_strand(sid) is not None for sid in strand_ids)
    conjugation = design.nanoparticle_conjugations[0]
    assert conjugation.requested_count == len(conjugation.surface_strands) == 3
    assert all(design.find_helix(item.helix_id) for item in conjugation.surface_strands)
    conjugate_group = next(
        group for group in design.staple_groups
        if set(group.strand_ids) == set(strand_ids)
    )
    assert conjugate_group.name == "NP-1"
    assert conjugate_group.color == "#c050d0"
    assert [design.find_strand(sid).name for sid in strand_ids] == [
        "NP-1:S1", "NP-1:S2", "NP-1:S3"
    ]
    assert {design.find_strand(sid).color for sid in strand_ids} == {"#c050d0"}
    measured_before = client.get(
        f"/api/design/nanoparticles/{particle_id}/conjugation"
    ).json()["tether_measurements"]
    assert len(measured_before) == 3
    assert all(item["render_endpoint_error_nm"] == 0 for item in measured_before)
    assert all(item["measured_length_nm"] == pytest.approx(
        item["nominal_unbound_length_nm"], abs=1e-6
    ) for item in measured_before)
    before = {h.id: h.axis_start.to_array().copy() for h in design.helices if h.id.startswith("__np__")}

    moved = client.patch(f"/api/design/nanoparticles/{particle_id}", json={
        "gizmo_move": {"pivot": [0, 0, 0], "translation": [3, 4, 5], "rotation": [0, 0, 0, 1]}
    })
    assert moved.status_code == 200, moved.text
    measured_after_move = client.get(
        f"/api/design/nanoparticles/{particle_id}/conjugation"
    ).json()["tether_measurements"]
    before_by_strand = {item["strand_id"]: item for item in measured_before}
    for item in measured_after_move:
        prior = before_by_strand[item["strand_id"]]
        assert item["measured_length_nm"] == pytest.approx(prior["measured_length_nm"], abs=1e-6)
        assert np.subtract(item["sulfur_position_nm"], prior["sulfur_position_nm"]).tolist() == pytest.approx([3, 4, 5])
        assert np.subtract(item["backbone_position_nm"], prior["backbone_position_nm"]).tolist() == pytest.approx([3, 4, 5])
    design = design_state.get_design()
    for helix in (h for h in design.helices if h.id in before):
        assert (helix.axis_start.to_array() - before[helix.id]).tolist() == pytest.approx([3, 4, 5])

    # Rotate 90 degrees around the nanoparticle centre.  Every owned helix must
    # keep its surface-relative placement rather than remaining in world space.
    before_rotation = {
        h.id: (h.axis_start.to_array().copy(), h.axis_end.to_array().copy())
        for h in design.helices if h.id in before
    }
    rotated = client.patch(f"/api/design/nanoparticles/{particle_id}", json={
        "gizmo_move": {
            "pivot": [3, 4, 5], "translation": [0, 0, 0],
            "rotation": [0, 0, 2 ** -0.5, 2 ** -0.5],
        }
    })
    assert rotated.status_code == 200, rotated.text
    design = design_state.get_design()
    for helix in (h for h in design.helices if h.id in before_rotation):
        old_start, old_end = before_rotation[helix.id]
        expected_start = [3 - (old_start[1] - 4), 4 + (old_start[0] - 3), old_start[2]]
        expected_axis = [-(old_end[1] - old_start[1]), old_end[0] - old_start[0], old_end[2] - old_start[2]]
        assert helix.axis_start.to_array().tolist() == pytest.approx(expected_start)
        assert (helix.axis_end.to_array() - helix.axis_start.to_array()).tolist() == pytest.approx(expected_axis)
    validation = client.get(f"/api/design/nanoparticles/{particle_id}/conjugation/validate").json()
    assert validation["valid"] is True
    assert validation["errors"] == []
    assert validation["conjugation_count"] == 1
    assert validation["strand_count"] == validation["atomistic_linker_count"] == 3
    assert validation["namd"]["passed"] is True

    assert client.post("/api/design/undo").status_code == 200  # undo rotation
    assert client.post("/api/design/undo").status_code == 200  # undo translation
    assert client.post("/api/design/undo").status_code == 200  # undo conjugation
    design = design_state.get_design()
    assert design.nanoparticle_conjugations == []
    assert all(sid not in {s.id for s in design.strands} for sid in strand_ids)


def test_thiol_conjugation_replacement_delete_and_roundtrip(tmp_path):
    particle_id = client.post(
        "/api/design/nanoparticles/gold-nanospheres", json={"diameter_nm": 20}
    ).json()["nanoparticle_id"]
    url = f"/api/design/nanoparticles/{particle_id}/conjugation"
    first = client.put(url, json={"scheme": "peg_backfill", "sequence": "TTTT", "count": 2, "attach_end": "3p", "seed": 2})
    assert first.status_code == 200, first.text
    old_ids = set(first.json()["strand_ids"])
    second = client.put(url, json={"scheme": "peg_thiol", "sequence": "AACCGG", "count": 5, "attach_end": "5p", "seed": 3})
    assert second.status_code == 200, second.text
    design = design_state.get_design()
    assert old_ids.isdisjoint({s.id for s in design.strands})
    assert len(design.nanoparticle_conjugations[0].surface_strands) == 5

    path = tmp_path / "thiol-roundtrip.nadoc"
    assert client.post("/api/design/save", json={"path": str(path)}).status_code == 200
    design_state.set_design(Design())
    assert client.post("/api/design/load", json={"path": str(path)}).status_code == 200
    assert client.get(url).json()["conjugations"][0]["scheme"] == "peg_thiol"
    restored = design_state.get_design()
    group = next(group for group in restored.staple_groups if group.name == "NP-1")
    assert [restored.find_strand(sid).name for sid in group.strand_ids] == [
        f"NP-1:S{i}" for i in range(1, 6)
    ]
    assert client.delete(url).status_code == 200
    design = design_state.get_design()
    assert design.nanoparticle_conjugations == []
    assert not any(h.id.startswith("__np__") for h in design.helices)
    assert not any(group.name == "NP-1" for group in design.staple_groups)


def test_thiol_conjugation_rejects_invalid_sequence_but_allows_manual_over_capacity():
    particle_id = client.post(
        "/api/design/nanoparticles/gold-nanospheres", json={"diameter_nm": 5}
    ).json()["nanoparticle_id"]
    url = f"/api/design/nanoparticles/{particle_id}/conjugation"
    assert client.put(url, json={"sequence": "AUGC", "count": 1}).status_code == 400
    capacity = client.post(
        f"/api/design/nanoparticles/{particle_id}/conjugation/estimate",
        json={"scheme": "direct_thiol"},
    ).json()["estimated_capacity"]
    requested = capacity + 4
    response = client.put(url, json={"sequence": "ACGT", "count": requested})
    assert response.status_code == 200, response.text
    conjugation = design_state.get_design().nanoparticle_conjugations[0]
    assert conjugation.requested_count == requested
    assert len(conjugation.surface_strands) == requested
    validation = client.get(url + "/validate").json()
    assert validation["valid"] is True
    assert validation["errors"] == []
    assert "exceeds estimated capacity" in validation["warnings"][0]


def test_surface_strand_binds_to_overhang_as_same_first_class_strand():
    design = Design()
    helix = Helix(id="target-oh", axis_start=Vec3(x=5, y=0, z=0), axis_end=Vec3(x=5, y=0, z=2.38), length_bp=8)
    overhang_strand = Strand(id="target-strand", domains=[Domain(
        helix_id=helix.id, start_bp=0, end_bp=7, direction=Direction.FORWARD, overhang_id="target-overhang"
    )], strand_type=StrandType.STAPLE, sequence="ACGTACGT")
    design = design.copy_with(
        helices=[*design.helices, helix], strands=[*design.strands, overhang_strand],
        overhangs=[OverhangSpec(id="target-overhang", helix_id=helix.id, strand_id=overhang_strand.id, sequence="ACGTACGT")],
    )
    design_state.set_design(design)
    particle_id = client.post("/api/design/nanoparticles/gold-nanospheres", json={"diameter_nm": 10}).json()["nanoparticle_id"]
    created = client.put(f"/api/design/nanoparticles/{particle_id}/conjugation", json={
        "scheme": "direct_thiol", "sequence": "ACGTACGT", "count": 1, "attach_end": "5p", "seed": 1
    })
    strand_id = created.json()["strand_ids"][0]
    bound = client.post(f"/api/design/nanoparticles/{particle_id}/strands/{strand_id}/bind", json={"overhang_id": "target-overhang"})
    assert bound.status_code == 200, bound.text
    result = design_state.get_design()
    strand = result.find_strand(strand_id)
    assert strand.strand_type == StrandType.OH_BINDER
    assert strand.domains[0].binds_overhang_id == "target-overhang"
    record = result.nanoparticle_conjugations[0].surface_strands[0]
    assert record.strand_id == strand_id
    assert record.bound_overhang_id == "target-overhang"
    assert not any(h.id.startswith("__np__") for h in result.helices)


def test_direct_thiol_builds_covalent_c3_phosphodiester_and_full_psf():
    """The atomistic linker is chemistry/topology, not a display overlay."""
    from backend.core.atomistic import build_atomistic_model
    from backend.core.namd_topology import build_charmm_psfgen_topology

    particle_id = client.post(
        "/api/design/nanoparticles/gold-nanospheres", json={"diameter_nm": 10}
    ).json()["nanoparticle_id"]
    created = client.put(
        f"/api/design/nanoparticles/{particle_id}/conjugation",
        json={"scheme": "direct_thiol", "sequence": "ACGT", "count": 1,
              "attach_end": "5p", "seed": 7},
    ).json()
    design = design_state.get_design()
    strand_id = design.nanoparticle_conjugations[0].surface_strands[0].strand_id
    model = build_atomistic_model(design)
    linker = {a.name: a for a in model.atoms if a.strand_id == strand_id and a.is_modified}
    assert set(linker) == {"SNP", "C1L", "C2L", "C3L", "O4L", "PLK", "O1L", "O2L"}
    target = next(a for a in model.atoms if a.strand_id == strand_id and a.seq_num == 1 and a.name == "O5'")
    bond_names = {
        frozenset((model.atoms[i].name, model.atoms[j].name)) for i, j in model.bonds
        if model.atoms[i].strand_id == strand_id and model.atoms[j].strand_id == strand_id
    }
    assert frozenset(("SNP", "C1L")) in bond_names
    assert frozenset(("PLK", target.name)) in bond_names
    assert created["design"]["nanoparticle_conjugations"][0]["scheme"] == "direct_thiol"

    topology = build_charmm_psfgen_topology(design, atomistic_model=model)
    assert " SNP " in topology.psf_text
    assert " PLK " in topology.psf_text
    assert topology.metadata["audit"]["passed"] is True
    assert round(topology.metadata["audit"]["total_charge"]) == -4

    validation = client.get(
        f"/api/design/nanoparticles/{particle_id}/conjugation/validate"
    ).json()
    assert validation["atomistic_linker_count"] == 1
    assert validation["namd"]["passed"] is True
    assert validation["namd"]["gold_model"] == "implicit_fixed_sphere"


def test_nonparameterized_thiol_scheme_is_not_claimed_namd_ready():
    particle_id = client.post(
        "/api/design/nanoparticles/gold-nanospheres", json={"diameter_nm": 20}
    ).json()["nanoparticle_id"]
    client.put(
        f"/api/design/nanoparticles/{particle_id}/conjugation",
        json={"scheme": "peg_thiol", "sequence": "ACGT", "count": 1,
              "attach_end": "5p", "seed": 2},
    )
    validation = client.get(
        f"/api/design/nanoparticles/{particle_id}/conjugation/validate"
    ).json()
    assert validation["valid"] is True
    assert validation["namd"]["passed"] is False
    assert "peg_thiol" in validation["namd"]["errors"][0]


def test_multiple_nanoparticle_conjugates_get_sequential_groups():
    particle_ids = [
        client.post(
            "/api/design/nanoparticles/gold-nanospheres", json={"diameter_nm": 10}
        ).json()["nanoparticle_id"]
        for _ in range(2)
    ]
    for particle_id in particle_ids:
        client.put(
            f"/api/design/nanoparticles/{particle_id}/conjugation",
            json={"scheme": "direct_thiol", "sequence": "ACGT", "count": 2},
        )
    design = design_state.get_design()
    groups = [group for group in design.staple_groups if group.name.startswith("NP-")]
    assert [group.name for group in groups] == ["NP-1", "NP-2"]
    assert [design.find_strand(sid).name for group in groups for sid in group.strand_ids] == [
        "NP-1:S1", "NP-1:S2", "NP-2:S1", "NP-2:S2"
    ]


@pytest.mark.parametrize(
    ("attach_end", "variant", "expected_np_attach", "allowed"),
    [
        ("5p", "end-to-root", "free_end", True),
        ("5p", "root-to-root", "root", False),
        ("3p", "end-to-root", "root", False),
        ("3p", "root-to-root", "free_end", True),
    ],
)
def test_np_connection_respects_chemical_end_direction_and_requested_variant(
    attach_end, variant, expected_np_attach, allowed,
):
    handle_sequence = "AACCGGTTAA"
    target_sequence = "TTAACCGGTT"  # reverse complement
    target = Helix(
        id="direction-target", axis_start=Vec3(x=14, y=3, z=0),
        axis_end=Vec3(x=14, y=3, z=3.06), length_bp=10,
    )
    target_strand = Strand(
        id="direction-target-strand",
        domains=[Domain(
            helix_id=target.id, start_bp=0, end_bp=9,
            direction=Direction.FORWARD, overhang_id="direction-oh_3p",
        )],
        strand_type=StrandType.STAPLE, sequence=target_sequence,
    )
    design_state.set_design(Design(
        helices=[target], strands=[target_strand],
        overhangs=[OverhangSpec(
            id="direction-oh_3p", helix_id=target.id,
            strand_id=target_strand.id, sequence=target_sequence,
        )],
    ))
    particle_id = client.post(
        "/api/design/nanoparticles/gold-nanospheres", json={"diameter_nm": 10},
    ).json()["nanoparticle_id"]
    handle_id = client.put(
        f"/api/design/nanoparticles/{particle_id}/conjugation",
        json={
            "scheme": "direct_thiol", "sequence": handle_sequence,
            "count": 1, "attach_end": attach_end, "seed": 3,
        },
    ).json()["strand_ids"][0]
    before = design_state.get_design()
    before_record = before.nanoparticle_conjugations[0].surface_strands[0]
    base = f"/api/design/nanoparticles/{particle_id}/connection-versions"
    created = client.post(base, json={
        "strand_id": handle_id, "overhang_id": "direction-oh_3p",
        "connection_type": "direct", "direct_variant": variant,
    })
    if not allowed:
        assert created.status_code == 422
        assert "forbidden" in created.text and "parallel" in created.text
        return
    assert created.status_code == 201, created.text
    version_id = created.json()["version_id"]
    version = next(v for v in design_state.get_design().nanoparticle_connection_versions
                   if v.id == version_id)
    assert version.nanoparticle_attach == expected_np_attach
    assert version.target_attach == "root"

    applied = client.patch(f"{base}/{version_id}", json={"applied": True})
    assert applied.status_code == 200, applied.text
    design = design_state.get_design()
    version = next(v for v in design.nanoparticle_connection_versions if v.id == version_id)
    duplex = next(dx for dx in design.duplexes if dx.id == version.duplex_id)
    assert duplex.connection_type == f"nanoparticle-{variant}"
    assert version.direct_variant == variant
    handle = design.find_strand(handle_id)
    assert handle.sequence == handle_sequence
    assert len(handle.domains) == len(before.find_strand(handle_id).domains)
    assert sum(abs(d.end_bp - d.start_bp) + 1 for d in handle.domains) == len(handle_sequence)

    from backend.core.models import _overhang_backing_domain
    _s, np_domain = _overhang_backing_domain(design, before_record.overhang_id)
    _s, target_domain = _overhang_backing_domain(design, "direction-oh_3p")
    assert np_domain.direction != target_domain.direction
    # The chemistry-selected terminal remains the endpoint used by the NP
    # tether after relocation; it is not silently swapped to the other end.
    tether = next(item for item in client.get(
        f"/api/design/nanoparticles/{particle_id}/conjugation"
    ).json()["tether_measurements"] if item["strand_id"] == handle_id)
    assert tether["bound"] is True
    assert before_record.backbone_attachment_local_nm is None
    assert next(r for r in design.nanoparticle_conjugations[0].surface_strands
                if r.strand_id == handle_id).backbone_attachment_local_nm is not None


def test_np_connection_rejects_noncomplementary_and_non_target_endpoints():
    target = Helix(
        id="bad-target", axis_start=Vec3(x=12, y=0, z=0),
        axis_end=Vec3(x=12, y=0, z=2.38), length_bp=8,
    )
    target_strand = Strand(
        id="bad-target-strand",
        domains=[Domain(
            helix_id=target.id, start_bp=0, end_bp=7,
            direction=Direction.FORWARD, overhang_id="bad-target-oh_3p",
        )], strand_type=StrandType.STAPLE, sequence="AAAAAAAA",
    )
    design_state.set_design(Design(
        helices=[target], strands=[target_strand],
        overhangs=[OverhangSpec(
            id="bad-target-oh_3p", helix_id=target.id,
            strand_id=target_strand.id, sequence="AAAAAAAA",
        )],
    ))
    particle_id = client.post(
        "/api/design/nanoparticles/gold-nanospheres", json={"diameter_nm": 10},
    ).json()["nanoparticle_id"]
    handles = client.put(
        f"/api/design/nanoparticles/{particle_id}/conjugation",
        json={"sequence": "AAAAAAAA", "count": 2},
    ).json()["strand_ids"]
    design = design_state.get_design()
    auxiliary = design.nanoparticle_conjugations[0].surface_strands[1].overhang_id
    base = f"/api/design/nanoparticles/{particle_id}/connection-versions"
    rejected = client.post(base, json={
        "strand_id": handles[0], "overhang_id": auxiliary,
    })
    assert rejected.status_code == 400
    assert "non-nanoparticle" in rejected.text
    version_id = client.post(base, json={
        "strand_id": handles[0], "overhang_id": "bad-target-oh_3p",
    }).json()["version_id"]
    mismatch = client.patch(f"{base}/{version_id}", json={"applied": True})
    assert mismatch.status_code == 422
    assert "not complementary" in mismatch.text


def test_nanoparticle_connection_versions_apply_mutex_unapply_and_collective_relax():
    helices, strands, overhangs = [], [], []
    for index, x in enumerate((18.0, -14.0), start=1):
        oid, hid, sid = f"oh-{index}_3p", f"target-{index}", f"target-strand-{index}"
        helix = Helix(id=hid, axis_start=Vec3(x=x, y=8, z=0),
                      axis_end=Vec3(x=x, y=8, z=2.38), length_bp=8)
        strand = Strand(id=sid, domains=[Domain(
            helix_id=hid, start_bp=0, end_bp=7, direction=Direction.FORWARD,
            overhang_id=oid)], strand_type=StrandType.STAPLE, sequence="ACGTACGT")
        helices.append(helix); strands.append(strand)
        overhangs.append(OverhangSpec(id=oid, helix_id=hid, strand_id=sid,
                                      sequence="ACGTACGT", label=f"Target {index}"))
    design_state.set_design(Design(helices=helices, strands=strands, overhangs=overhangs))
    particle_id = client.post(
        "/api/design/nanoparticles/gold-nanospheres", json={"diameter_nm": 10}
    ).json()["nanoparticle_id"]
    made = client.put(f"/api/design/nanoparticles/{particle_id}/conjugation", json={
        "scheme": "direct_thiol", "sequence": "ACGTACGT", "count": 2, "seed": 4,
    }).json()
    s1, s2 = made["strand_ids"]
    base = f"/api/design/nanoparticles/{particle_id}/connection-versions"
    assert client.post(base, json={"strand_id": s1, "overhang_id": "oh-1_3p",
                                   "connection_type": "ssdna"}).status_code == 422
    v1 = client.post(base, json={"strand_id": s1, "overhang_id": "oh-1_3p"}).json()["version_id"]
    v2 = client.post(base, json={"strand_id": s1, "overhang_id": "oh-1_3p"}).json()["version_id"]
    v3 = client.post(base, json={"strand_id": s2, "overhang_id": "oh-2_3p"}).json()["version_id"]
    versions = client.get(base).json()["versions"]
    assert [v["name"] for v in versions] == ["V1", "V2", "V1"]

    assert client.patch(f"{base}/{v1}", json={"applied": True}).status_code == 200
    assert client.patch(f"{base}/{v2}", json={"applied": True}).status_code == 200
    assert client.patch(f"{base}/{v3}", json={"applied": True}).status_code == 200
    versions = client.get(base).json()["versions"]
    assert {v["id"] for v in versions if v["applied"]} == {v2, v3}
    assert all(v["connection_type"] == "direct" for v in versions)
    measurements = [v["duplex_measurement"] for v in versions if v["applied"]]
    assert all(m["paired_base_count"] == 8 for m in measurements), measurements
    assert all(m["native_position_match"] for m in measurements)
    assert all(m["backbone_rms_error_nm"] == pytest.approx(0.0) for m in measurements)
    assert all(m["mean_backbone_separation_nm"] > 1.0 for m in measurements)
    connected = design_state.get_design()
    records = connected.nanoparticle_conjugations[0].surface_strands
    assert {record.bound_overhang_id for record in records} == {"oh-1_3p", "oh-2_3p"}
    # Applied NP connections use the same first-class, registered Duplex model
    # as an ordinary overhang connection (and superseding V1 removed its edge).
    assert len(connected.duplexes) == 2
    assert all(dx.bound and dx.connection_type in {
        "nanoparticle-end-to-root", "nanoparticle-root-to-root",
    } for dx in connected.duplexes)
    assert {dx.connection_type for dx in connected.duplexes} == {
        "nanoparticle-end-to-root"
    }
    assert {dx.right.overhang_id for dx in connected.duplexes} == {"oh-1_3p", "oh-2_3p"}
    assert all(dx.left.overhang_id.startswith("__np_oh__") for dx in connected.duplexes)
    assert all(v.duplex_id in {dx.id for dx in connected.duplexes}
               for v in connected.nanoparticle_connection_versions if v.applied)
    reloaded = Design.model_validate_json(connected.model_dump_json())
    assert {(dx.left.overhang_id, dx.right.overhang_id) for dx in reloaded.duplexes} == {
        (dx.left.overhang_id, dx.right.overhang_id) for dx in connected.duplexes
    }

    # With two applied handles the collective system remains on the multi-link
    # relax path. Reduce to one and verify protein-parity two-ball-joint motion.
    assert client.patch(f"{base}/{v3}", json={"applied": False}).status_code == 200
    unbound_tether_length = next(
        item["nominal_unbound_length_nm"]
        for item in client.get(
            f"/api/design/nanoparticles/{particle_id}/conjugation"
        ).json()["tether_measurements"]
        if item["strand_id"] == s1
    )
    constrained = client.patch(f"/api/design/nanoparticles/{particle_id}", json={
        "gizmo_move": {"pivot": [0, 0, 0], "translation": [20, -5, 3],
                       "rotation": [0, 0, 2 ** -0.5, 2 ** -0.5]}
    })
    assert constrained.status_code == 200, constrained.text
    constraint = constrained.json()["movement_constraint"]
    assert constraint["mode"] == "two_ball_joint"
    assert constraint["clamped"] is True
    assert constraint["joint_error_nm"] < 1e-8
    moved_tether = next(
        item for item in client.get(
            f"/api/design/nanoparticles/{particle_id}/conjugation"
        ).json()["tether_measurements"]
        if item["strand_id"] == s1
    )
    assert moved_tether["measured_length_nm"] == pytest.approx(
        unbound_tether_length, abs=1e-6
    )
    # The committed child-cluster transform—not merely its live preview—must
    # survive NADOC serialization with identical duplex bead coordinates.
    from backend.core.design_geometry import fitting_geometry
    committed = design_state.get_design()
    committed_cluster = next(
        cluster for cluster in committed.cluster_transforms
        if cluster.overhang_duplex_driver_id == "oh-1_3p"
    )
    relevant_before = {
        (item["strand_id"], item["bp_index"]): item["backbone_position"]
        for item in fitting_geometry(committed)
        if item.get("strand_id") == s1 or item.get("overhang_id") == "oh-1_3p"
    }
    round_tripped = Design.model_validate_json(committed.model_dump_json())
    restored_cluster = next(
        cluster for cluster in round_tripped.cluster_transforms
        if cluster.overhang_duplex_driver_id == "oh-1_3p"
    )
    relevant_after = {
        (item["strand_id"], item["bp_index"]): item["backbone_position"]
        for item in fitting_geometry(round_tripped)
        if item.get("strand_id") == s1 or item.get("overhang_id") == "oh-1_3p"
    }
    assert restored_cluster == committed_cluster
    assert relevant_after == pytest.approx(relevant_before, abs=1e-9)
    # Re-apply the second handle for the existing collective-relax assertions.
    assert client.patch(f"{base}/{v3}", json={"applied": True}).status_code == 200

    before_pose = design_state.get_design().nanoparticles[0].pose.values.copy()
    before_duplex_rotations = {
        cluster.overhang_duplex_driver_id: cluster.rotation.copy()
        for cluster in design_state.get_design().cluster_transforms
        if cluster.overhang_duplex_driver_id in {"oh-1_3p", "oh-2_3p"}
    }
    relaxed = client.post(base + "/relax")
    assert relaxed.status_code == 200, relaxed.text
    assert relaxed.json()["rms_residual_nm"] >= 0
    after = design_state.get_design()
    assert after.nanoparticles[0].pose.values != before_pose
    assert relaxed.json()["relaxation_stages"] == [
        "closed_loop_pose_solve", "duplex_reorientation"
    ]
    assert relaxed.json()["solver"] == "closed_loop_least_squares"
    assert relaxed.json()["anchor_count"] == 2
    assert set(relaxed.json()["per_anchor_residual_nm"]) == {v2, v3}
    assert relaxed.json()["max_joint_error_nm"] >= 0
    assert relaxed.json()["max_penetration_nm"] >= 0
    assert set(relaxed.json()["duplex_reorientation_version_ids"]) == {v2, v3}
    after_duplex_rotations = {
        cluster.overhang_duplex_driver_id: cluster.rotation
        for cluster in after.cluster_transforms
        if cluster.overhang_duplex_driver_id in {"oh-1_3p", "oh-2_3p"}
    }
    assert any(after_duplex_rotations[key] != rotation
               for key, rotation in before_duplex_rotations.items())
    relaxed_particle = next(p for p in after.nanoparticles if p.id == particle_id)
    relaxed_conjugation = next(
        c for c in after.nanoparticle_conjugations if c.nanoparticle_id == particle_id
    )
    relaxed_matrix = relaxed_particle.pose.to_array()
    expected_free_ids = []
    for record in relaxed_conjugation.surface_strands:
        if record.bound_overhang_id is not None:
            continue
        expected_free_ids.append(record.strand_id)
        expected = (relaxed_matrix @ np.array([
            *(np.asarray(record.site_local) * (
                relaxed_particle.diameter_nm / 2 + relaxed_conjugation.spacer_nm
            )), 1.0
        ]))[:3]
        assert after.find_helix(record.helix_id).axis_start.to_array() == pytest.approx(
            expected, abs=1e-9
        )
    assert set(relaxed.json()["moved_surface_strand_ids"]) == set(expected_free_ids)
    assert 0 <= relaxed.json()["dna_avoidance_shift_magnitude_nm"] <= 50.0 + 1e-9
    if relaxed.json()["nearest_dna_center_distance_after_nm"] is not None:
        assert (relaxed.json()["nearest_dna_center_distance_after_nm"] + 1e-9
                >= relaxed.json()["dna_clearance_target_nm"])
    assert all(v.relaxed and v.residual_nm is not None
               for v in after.nanoparticle_connection_versions if v.applied)
    # Applied strands occupy the target's native opposite-direction backbone
    # slots; unapply restores their original NP-owned surface helices.
    assert all(v["native_position_match"] for v in relaxed.json()["duplex_measurements"].values())

    assert client.patch(f"{base}/{v2}", json={"applied": False}).status_code == 200
    after = design_state.get_design()
    assert next(record for record in after.nanoparticle_conjugations[0].surface_strands
                if record.strand_id == s1).bound_overhang_id is None
    assert len(after.duplexes) == 1
    assert after.find_helix(next(record for record in records if record.strand_id == s1).helix_id) is not None


def test_three_anchor_relax_moves_all_links_preserves_rigidity_and_roundtrips():
    helices, strands, overhangs = [], [], []
    positions = ((18.0, 7.0), (-14.0, 9.0), (3.0, -17.0))
    for index, (x, y) in enumerate(positions, start=1):
        oid, hid, sid = f"tri-oh-{index}_3p", f"tri-target-{index}", f"tri-strand-{index}"
        helices.append(Helix(
            id=hid, axis_start=Vec3(x=x, y=y, z=0),
            axis_end=Vec3(x=x, y=y, z=3.06), length_bp=10,
        ))
        strands.append(Strand(
            id=sid,
            domains=[Domain(
                helix_id=hid, start_bp=0, end_bp=9,
            direction=Direction.FORWARD, overhang_id=oid,
            )],
            strand_type=StrandType.STAPLE, sequence="GTACGTACGT",
        ))
        overhangs.append(OverhangSpec(
            id=oid, helix_id=hid, strand_id=sid,
                sequence="GTACGTACGT", label=f"Triangle {index}",
        ))
    design_state.set_design(Design(helices=helices, strands=strands, overhangs=overhangs))
    particle_id = client.post(
        "/api/design/nanoparticles/gold-nanospheres", json={"diameter_nm": 10}
    ).json()["nanoparticle_id"]
    handle_ids = client.put(
        f"/api/design/nanoparticles/{particle_id}/conjugation",
        json={"scheme": "direct_thiol", "sequence": "ACGTACGTAC", "count": 3, "seed": 11},
    ).json()["strand_ids"]
    base = f"/api/design/nanoparticles/{particle_id}/connection-versions"
    version_ids = []
    for index, handle_id in enumerate(handle_ids, start=1):
        version_id = client.post(base, json={
            "strand_id": handle_id, "overhang_id": f"tri-oh-{index}_3p",
        }).json()["version_id"]
        assert client.patch(f"{base}/{version_id}", json={"applied": True}).status_code == 200
        version_ids.append(version_id)

    from backend.core.design_geometry import fitting_geometry

    def internal_distances(design, strand_id):
        points = np.asarray([
            item["backbone_position"] for item in fitting_geometry(design)
            if item.get("strand_id") == strand_id
        ])
        return np.asarray([
            np.linalg.norm(points[j] - points[i])
            for i in range(len(points)) for j in range(i + 1, len(points))
        ])

    before = design_state.get_design()
    rigid_before = {sid: internal_distances(before, sid) for sid in handle_ids}
    transforms_before = {
        c.overhang_duplex_driver_id: (tuple(c.rotation), tuple(c.translation))
        for c in before.cluster_transforms
        if c.overhang_duplex_driver_id in {f"tri-oh-{i}_3p" for i in range(1, 4)}
    }
    response = client.post(base + "/relax")
    assert response.status_code == 200, response.text
    report = response.json()
    assert report["anchor_count"] == 3
    assert set(report["version_ids"]) == set(version_ids)
    assert set(report["duplex_reorientation_version_ids"]) == set(version_ids)
    assert len(report["per_anchor_residual_nm"]) == 3

    after = design_state.get_design()
    transforms_after = {
        c.overhang_duplex_driver_id: (tuple(c.rotation), tuple(c.translation))
        for c in after.cluster_transforms
        if c.overhang_duplex_driver_id in transforms_before
    }
    assert transforms_after.keys() == transforms_before.keys()
    assert all(transforms_after[key] != transforms_before[key] for key in transforms_before)
    for strand_id in handle_ids:
        assert internal_distances(after, strand_id) == pytest.approx(
            rigid_before[strand_id], abs=1e-8,
        )
    geometry_after = fitting_geometry(after)
    particle_after = after.nanoparticles[0]
    conjugation_after = after.nanoparticle_conjugations[0]
    records_after = {r.strand_id: r for r in conjugation_after.surface_strands}
    versions_after = {v.strand_id: v for v in after.nanoparticle_connection_versions}
    for strand_id in handle_ids:
        record = records_after[strand_id]
        endpoint = next(
            item for item in geometry_after
            if item.get("strand_id") == strand_id and item.get("is_five_prime")
        )
        local_joint = np.asarray(record.backbone_attachment_local_nm)
        surface_joint = (particle_after.pose.to_array() @ np.r_[local_joint, 1.0])[:3]
        measured_error = np.linalg.norm(
            np.asarray(endpoint["backbone_position"]) - surface_joint
        )
        assert measured_error == pytest.approx(
            report["per_anchor_residual_nm"][versions_after[strand_id].id], abs=1e-6,
        )

    restored = Design.model_validate_json(after.model_dump_json())
    assert restored.nanoparticles[0].pose == after.nanoparticles[0].pose
    assert {
        c.id: (c.rotation, c.translation, c.pivot)
        for c in restored.cluster_transforms if c.overhang_duplex_driver_id
    } == {
        c.id: (c.rotation, c.translation, c.pivot)
        for c in after.cluster_transforms if c.overhang_duplex_driver_id
    }
    assert {
        v.id: (v.relaxed, v.residual_nm)
        for v in restored.nanoparticle_connection_versions
    } == {
        v.id: (v.relaxed, v.residual_nm)
        for v in after.nanoparticle_connection_versions
    }


def test_direct_thiol_complete_namd_package_passes_engine_preflight(tmp_path):
    import io
    import shutil
    import subprocess
    import zipfile

    from backend.core.namd_package import build_namd_package

    namd = shutil.which("namd3") or next(
        iter(sorted((__import__("pathlib").Path.home() / "Applications").glob("NAMD_*/namd3"))),
        None,
    )
    if namd is None:
        pytest.skip("NAMD is not installed")
    particle_id = client.post(
        "/api/design/nanoparticles/gold-nanospheres", json={"diameter_nm": 10}
    ).json()["nanoparticle_id"]
    client.put(
        f"/api/design/nanoparticles/{particle_id}/conjugation",
        json={"scheme": "direct_thiol", "sequence": "ACGT", "count": 1,
              "attach_end": "5p", "seed": 3},
    )
    package = build_namd_package(design_state.get_design())
    with zipfile.ZipFile(io.BytesIO(package)) as archive:
        archive.extractall(tmp_path)
    root = next(tmp_path.glob("*_namd_complete"))
    conf = root / "namd.conf"
    text = conf.read_text().replace("minimize           2000", "minimize           10")
    text = text.replace("run                50000", "run                0")
    conf.write_text(text)
    (root / "output").mkdir(exist_ok=True)
    proc = subprocess.run(
        [str(namd), "+p1", "namd.conf"], cwd=root, text=True,
        capture_output=True, timeout=30, check=False,
    )
    log = proc.stdout + proc.stderr
    assert proc.returncode == 0, log[-6000:]
    assert "FATAL ERROR" not in log
    assert "End of program" in log
