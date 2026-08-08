"""
Route tests for the cross-part AssemblyDuplex CRUD (Proposal-B convergence,
Phase B) in ``backend.api.routes_assembly_overhangs``.

Covers the endpoints the assembly UI needs to create / flip-driver / delete
cross-part duplexes (reading existing pairs already works via load-derivation):

  - POST   /assembly/duplexes/connect          — producer (min-length register)
  - POST   /assembly/duplexes                   — explicit register + WC gate (422)
  - POST   /assembly/duplexes/sync-from-bindings
  - PATCH  /assembly/duplexes/{id}              — driver flip persists
  - DELETE /assembly/duplexes/{id}
  - GET    /assembly/duplexes + /{id}/pairing + /assembly/overhangs/pairing-map
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.api import assembly_state
from backend.api.main import app
from backend.core.constants import BDNA_RISE_PER_BP
from backend.core.models import (
    Assembly,
    AssemblyOverhangBinding,
    Design,
    Direction,
    Domain,
    Helix,
    Mat4x4,
    OverhangSpec,
    PartInstance,
    PartSourceInline,
    Strand,
    StrandType,
    Vec3,
)

client = TestClient(app)


@pytest.fixture(autouse=True)
def _reset():
    assembly_state.close_session()
    yield
    assembly_state.close_session()


# ── Fixtures (real OH-tagged backing domains so registers/pairing resolve) ──────


def _design_with_real_oh(
    oh_id: str, sequence: str | None, length_bp: int = 8
) -> Design:
    helix_id = f"hx_{oh_id}"
    strand_id = f"str_{oh_id}"
    helix = Helix(
        id=helix_id,
        axis_start=Vec3(x=0.0, y=0.0, z=0.0),
        axis_end=Vec3(x=0.0, y=0.0, z=length_bp * BDNA_RISE_PER_BP),
        phase_offset=0.0,
        length_bp=length_bp,
    )
    direction = Direction.FORWARD if oh_id.endswith("_5p") else Direction.REVERSE
    strand = Strand(
        id=strand_id,
        domains=[
            Domain(
                helix_id=helix_id,
                start_bp=0,
                end_bp=length_bp - 1,
                direction=direction,
                overhang_id=oh_id,
            )
        ],
        strand_type=StrandType.STAPLE,
    )
    ovhg = OverhangSpec(
        id=oh_id,
        helix_id=helix_id,
        strand_id=strand_id,
        sequence=sequence,
        label=oh_id,
    )
    return Design(helices=[helix], strands=[strand], overhangs=[ovhg])


def _seed(seq_a="ACGTACGT", seq_b="ACGTACGT") -> Assembly:
    """Two-part assembly. ``ACGTACGT`` is self-reverse-complementary, so a
    default A↔B pair is fully Watson-Crick."""
    d_a = _design_with_real_oh("oh-A_5p", seq_a)
    d_b = _design_with_real_oh("oh-B_3p", seq_b)
    t_b = Mat4x4(values=[1, 0, 0, 10, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1])
    a = Assembly(
        instances=[
            PartInstance(
                id="inst-A", name="PartA", source=PartSourceInline(design=d_a)
            ),
            PartInstance(
                id="inst-B",
                name="PartB",
                source=PartSourceInline(design=d_b),
                transform=t_b,
            ),
        ]
    )
    assembly_state.set_assembly(a)
    return a


def _connect(**over):
    body = {
        "instance_a_id": "inst-A",
        "overhang_a_id": "oh-A_5p",
        "overhang_a_attach": "free_end",
        "instance_b_id": "inst-B",
        "overhang_b_id": "oh-B_3p",
        "overhang_b_attach": "root",
    }
    body.update(over)
    return client.post("/api/assembly/duplexes/connect", json=body)


# ── connect producer ────────────────────────────────────────────────────────────


def test_connect_creates_duplex():
    _seed()
    r = _connect()
    assert r.status_code == 200, r.text
    body = r.json()
    dux = body["assembly"]["duplexes"]
    assert len(dux) == 1
    dx = dux[0]
    assert dx["left"]["instance_id"] == "inst-A"
    assert dx["right"]["instance_id"] == "inst-B"
    _len = lambda e: abs(e["end_bp"] - e["start_bp"]) + 1
    assert _len(dx["left"]) == 8 and _len(dx["right"]) == 8
    assert body["duplex_id"] == dx["id"]
    # feature-log entry recorded.
    assert body["assembly"]["feature_log"][-1]["op_kind"] == "assembly-duplex-connect"


def test_connect_longest_drives_default():
    # A is 8 bp; give B a genuinely longer (12 bp) backing domain so B drives.
    d_a = _design_with_real_oh("oh-A_5p", "ACGTACGT", length_bp=8)
    d_b = _design_with_real_oh("oh-B_3p", "ACGTACGTACGT", length_bp=12)
    a = Assembly(
        instances=[
            PartInstance(
                id="inst-A", name="PartA", source=PartSourceInline(design=d_a)
            ),
            PartInstance(
                id="inst-B", name="PartB", source=PartSourceInline(design=d_b)
            ),
        ]
    )
    assembly_state.set_assembly(a)
    r = _connect()
    assert r.status_code == 200, r.text
    assert r.json()["assembly"]["duplexes"][0]["driver"] == "right"


def test_connect_duplicate_pair_409():
    _seed()
    assert _connect().status_code == 200
    assert _connect().status_code == 409


def test_connect_self_pair_400():
    _seed()
    r = _connect(instance_b_id="inst-A", overhang_b_id="oh-A_5p")
    assert r.status_code == 400, r.text


def test_connect_non_complementary_422():
    _seed(seq_b="TTTTTTTT")  # not WC to A → WC gate rejects
    r = _connect()
    assert r.status_code == 422, r.text


def test_connect_unknown_instance_404():
    _seed()
    r = _connect(instance_a_id="nope")
    assert r.status_code == 404, r.text


# ── explicit create + WC gate ───────────────────────────────────────────────────


def test_create_explicit_register():
    _seed()
    r = client.post(
        "/api/assembly/duplexes",
        json={
            "left": {
                "instance_id": "inst-A",
                "overhang_id": "oh-A_5p",
                "start_bp": 0,
                "end_bp": 7,
            },
            "right": {
                "instance_id": "inst-B",
                "overhang_id": "oh-B_3p",
                "start_bp": 0,
                "end_bp": 7,
            },
        },
    )
    assert r.status_code == 200, r.text
    assert len(r.json()["assembly"]["duplexes"]) == 1


def test_create_out_of_range_422():
    _seed()
    r = client.post(
        "/api/assembly/duplexes",
        json={
            "left": {
                "instance_id": "inst-A",
                "overhang_id": "oh-A_5p",
                "start_bp": 0,
                "end_bp": 20,
            },
            "right": {
                "instance_id": "inst-B",
                "overhang_id": "oh-B_3p",
                "start_bp": 0,
                "end_bp": 20,
            },
        },
    )
    assert r.status_code == 422, r.text


# ── patch (driver flip) ─────────────────────────────────────────────────────────


def test_patch_driver_persists():
    _seed()
    dux_id = _connect().json()["duplex_id"]
    r = client.patch(f"/api/assembly/duplexes/{dux_id}", json={"driver": "right"})
    assert r.status_code == 200, r.text
    dx = next(d for d in r.json()["assembly"]["duplexes"] if d["id"] == dux_id)
    assert dx["driver"] == "right"


def test_patch_unknown_404():
    _seed()
    r = client.patch("/api/assembly/duplexes/nope", json={"driver": "right"})
    assert r.status_code == 404


# ── delete ──────────────────────────────────────────────────────────────────────


def test_delete_removes_duplex():
    _seed()
    dux_id = _connect().json()["duplex_id"]
    r = client.delete(f"/api/assembly/duplexes/{dux_id}")
    assert r.status_code == 200, r.text
    assert r.json()["assembly"]["duplexes"] == []


# ── sync-from-bindings ──────────────────────────────────────────────────────────


def test_sync_from_bindings_derives():
    a = _seed()
    sda = a.instances[0].source.design.overhangs[0].sub_domains[0].id
    sdb = a.instances[1].source.design.overhangs[0].sub_domains[0].id
    b = AssemblyOverhangBinding(
        name="AB1",
        instance_a_id="inst-A",
        sub_domain_a_id=sda,
        overhang_a_id="oh-A_5p",
        instance_b_id="inst-B",
        sub_domain_b_id=sdb,
        overhang_b_id="oh-B_3p",
    )
    assembly_state.set_assembly(a.model_copy(update={"overhang_bindings": [b]}))
    r = client.post("/api/assembly/duplexes/sync-from-bindings")
    assert r.status_code == 200, r.text
    assert len(r.json()["assembly"]["duplexes"]) == 1
    # idempotent — second call adds nothing.
    r2 = client.post("/api/assembly/duplexes/sync-from-bindings")
    assert len(r2.json()["assembly"]["duplexes"]) == 1


# ── read endpoints ──────────────────────────────────────────────────────────────


def test_list_and_pairing():
    _seed()
    dux_id = _connect().json()["duplex_id"]
    assert len(client.get("/api/assembly/duplexes").json()["duplexes"]) == 1
    pr = client.get(f"/api/assembly/duplexes/{dux_id}/pairing")
    assert pr.status_code == 200
    assert pr.json()["n_complementary"] == 8


def test_pairing_map():
    _seed()
    _connect()
    r = client.get(
        "/api/assembly/overhangs/pairing-map",
        params={"instance_id": "inst-A", "overhang_id": "oh-A_5p"},
    )
    assert r.status_code == 200, r.text
    assert set(r.json()["pairing_map"].values()) == {"paired"}


def test_pairing_map_unknown_overhang_404():
    _seed()
    r = client.get(
        "/api/assembly/overhangs/pairing-map",
        params={"instance_id": "inst-A", "overhang_id": "nope"},
    )
    assert r.status_code == 404
