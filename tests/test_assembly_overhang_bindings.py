"""
Tests for assembly-level overhang bindings (cross-part) and the
``POST /assembly/features/seek`` route that scrubs the assembly feature log.

Covers:
  - AssemblyOverhangBinding model: round-trip + self-binding rejection.
  - POST /assembly/overhang-bindings: 200 / 404 / 400 / 409.
  - PATCH /assembly/overhang-bindings/{id}: binding_mode / allow_n_wildcard.
  - DELETE /assembly/overhang-bindings/{id}: removal + feature_log entry.
  - POST /assembly/features/seek: position -1 / -2 / explicit index.
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
    AssemblyOverhangConnection,
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


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _design_with_overhang(oh_id: str, seq: str) -> Design:
    """Design carrying a single overhang with a deterministic id + sequence.

    Use canonical id suffix '_5p' / '_3p' so server-side polarity rules can
    recover end polarity from the id.
    """
    ovhg = OverhangSpec(
        id=oh_id,
        helix_id="h-stub",
        strand_id="s-stub",
        sequence=seq,
        label=oh_id,
    )
    return Design(overhangs=[ovhg])


def _two_part_assembly() -> Assembly:
    """Assembly with two PartInstances; each carries one overhang."""
    d_a = _design_with_overhang("oh-A", "ACGT")
    d_b = _design_with_overhang("oh-B", "ACGT")
    return Assembly(
        instances=[
            PartInstance(id="inst-A", name="PartA", source=PartSourceInline(design=d_a)),
            PartInstance(id="inst-B", name="PartB", source=PartSourceInline(design=d_b)),
        ]
    )


def _sub_domain_id(assembly: Assembly, instance_id: str, overhang_id: str) -> str:
    inst = next(i for i in assembly.instances if i.id == instance_id)
    ovhg = next(o for o in inst.source.design.overhangs if o.id == overhang_id)
    return ovhg.sub_domains[0].id


def _seed_two_part_assembly() -> tuple[Assembly, dict]:
    """Push a two-part assembly into state and return (assembly, sub-domain map)."""
    a = _two_part_assembly()
    assembly_state.set_assembly(a)
    sd_map = {
        "A": _sub_domain_id(a, "inst-A", "oh-A"),
        "B": _sub_domain_id(a, "inst-B", "oh-B"),
    }
    return a, sd_map


# ── Model-level tests ─────────────────────────────────────────────────────────

def test_assembly_overhang_binding_roundtrip():
    b = AssemblyOverhangBinding(
        name="AB1",
        instance_a_id="iA", sub_domain_a_id="sda", overhang_a_id="oA",
        instance_b_id="iB", sub_domain_b_id="sdb", overhang_b_id="oB",
    )
    data = b.model_dump()
    b2 = AssemblyOverhangBinding.model_validate(data)
    assert b2 == b


def test_assembly_overhang_binding_rejects_self_binding():
    with pytest.raises(ValueError):
        AssemblyOverhangBinding(
            name="AB-bad",
            instance_a_id="iX", sub_domain_a_id="sdX", overhang_a_id="oX",
            instance_b_id="iX", sub_domain_b_id="sdX", overhang_b_id="oX",
        )


def test_assembly_overhang_bindings_serialise_on_assembly():
    a = _two_part_assembly()
    b = AssemblyOverhangBinding(
        name="AB1",
        instance_a_id="inst-A", sub_domain_a_id="sda", overhang_a_id="oh-A",
        instance_b_id="inst-B", sub_domain_b_id="sdb", overhang_b_id="oh-B",
    )
    a2 = a.model_copy(update={"overhang_bindings": [b]})
    a3 = Assembly.from_json(a2.to_json())
    assert len(a3.overhang_bindings) == 1
    assert a3.overhang_bindings[0].name == "AB1"


# ── Create binding ─────────────────────────────────────────────────────────────

def test_create_binding_200():
    _, sd = _seed_two_part_assembly()
    r = client.post("/api/assembly/overhang-bindings", json={
        "instance_a_id": "inst-A", "sub_domain_a_id": sd["A"], "overhang_a_id": "oh-A",
        "instance_b_id": "inst-B", "sub_domain_b_id": sd["B"], "overhang_b_id": "oh-B",
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body["assembly"]["overhang_bindings"]) == 1
    binding = body["assembly"]["overhang_bindings"][0]
    assert binding["name"] == "AB1"
    assert binding["instance_a_id"] == "inst-A"
    # Feature log captured the bind op.
    assert len(body["assembly"]["feature_log"]) == 1
    entry = body["assembly"]["feature_log"][0]
    assert entry["op_kind"] == "assembly-overhang-bind"
    assert "PartA" in entry["label"] and "PartB" in entry["label"]


def test_create_binding_unknown_instance_404():
    _, sd = _seed_two_part_assembly()
    r = client.post("/api/assembly/overhang-bindings", json={
        "instance_a_id": "nope", "sub_domain_a_id": sd["A"], "overhang_a_id": "oh-A",
        "instance_b_id": "inst-B", "sub_domain_b_id": sd["B"], "overhang_b_id": "oh-B",
    })
    assert r.status_code == 404


def test_create_binding_unknown_overhang_404():
    _, sd = _seed_two_part_assembly()
    r = client.post("/api/assembly/overhang-bindings", json={
        "instance_a_id": "inst-A", "sub_domain_a_id": sd["A"], "overhang_a_id": "missing",
        "instance_b_id": "inst-B", "sub_domain_b_id": sd["B"], "overhang_b_id": "oh-B",
    })
    assert r.status_code == 404


def test_create_binding_self_rejected_400():
    _, sd = _seed_two_part_assembly()
    r = client.post("/api/assembly/overhang-bindings", json={
        "instance_a_id": "inst-A", "sub_domain_a_id": sd["A"], "overhang_a_id": "oh-A",
        "instance_b_id": "inst-A", "sub_domain_b_id": sd["A"], "overhang_b_id": "oh-A",
    })
    assert r.status_code == 400


def test_create_binding_duplicate_409():
    _, sd = _seed_two_part_assembly()
    body = {
        "instance_a_id": "inst-A", "sub_domain_a_id": sd["A"], "overhang_a_id": "oh-A",
        "instance_b_id": "inst-B", "sub_domain_b_id": sd["B"], "overhang_b_id": "oh-B",
    }
    r1 = client.post("/api/assembly/overhang-bindings", json=body)
    assert r1.status_code == 200
    r2 = client.post("/api/assembly/overhang-bindings", json=body)
    assert r2.status_code == 409
    # Order swapped — still duplicate.
    swapped = {
        "instance_a_id": "inst-B", "sub_domain_a_id": sd["B"], "overhang_a_id": "oh-B",
        "instance_b_id": "inst-A", "sub_domain_b_id": sd["A"], "overhang_b_id": "oh-A",
    }
    r3 = client.post("/api/assembly/overhang-bindings", json=swapped)
    assert r3.status_code == 409


# ── Patch binding ──────────────────────────────────────────────────────────────

def test_patch_binding_changes_mode_and_logs_entry():
    _, sd = _seed_two_part_assembly()
    r = client.post("/api/assembly/overhang-bindings", json={
        "instance_a_id": "inst-A", "sub_domain_a_id": sd["A"], "overhang_a_id": "oh-A",
        "instance_b_id": "inst-B", "sub_domain_b_id": sd["B"], "overhang_b_id": "oh-B",
    })
    binding_id = r.json()["assembly"]["overhang_bindings"][0]["id"]

    r2 = client.patch(
        f"/api/assembly/overhang-bindings/{binding_id}",
        json={"binding_mode": "toehold"},
    )
    assert r2.status_code == 200, r2.text
    asm = r2.json()["assembly"]
    assert asm["overhang_bindings"][0]["binding_mode"] == "toehold"
    assert len(asm["feature_log"]) == 2
    assert asm["feature_log"][1]["op_kind"] == "assembly-overhang-bind-patch"


def test_patch_binding_unknown_404():
    _seed_two_part_assembly()
    r = client.patch("/api/assembly/overhang-bindings/missing", json={"binding_mode": "toehold"})
    assert r.status_code == 404


# ── Delete binding ─────────────────────────────────────────────────────────────

def test_delete_binding_removes_and_logs():
    _, sd = _seed_two_part_assembly()
    r = client.post("/api/assembly/overhang-bindings", json={
        "instance_a_id": "inst-A", "sub_domain_a_id": sd["A"], "overhang_a_id": "oh-A",
        "instance_b_id": "inst-B", "sub_domain_b_id": sd["B"], "overhang_b_id": "oh-B",
    })
    binding_id = r.json()["assembly"]["overhang_bindings"][0]["id"]
    r2 = client.delete(f"/api/assembly/overhang-bindings/{binding_id}")
    assert r2.status_code == 200, r2.text
    asm = r2.json()["assembly"]
    assert asm["overhang_bindings"] == []
    assert len(asm["feature_log"]) == 2
    assert asm["feature_log"][1]["op_kind"] == "assembly-overhang-unbind"


# ── Seek ───────────────────────────────────────────────────────────────────────

def test_seek_to_empty_then_end_round_trips_binding():
    _, sd = _seed_two_part_assembly()
    body = {
        "instance_a_id": "inst-A", "sub_domain_a_id": sd["A"], "overhang_a_id": "oh-A",
        "instance_b_id": "inst-B", "sub_domain_b_id": sd["B"], "overhang_b_id": "oh-B",
    }
    r = client.post("/api/assembly/overhang-bindings", json=body)
    assert r.status_code == 200
    assert len(r.json()["assembly"]["overhang_bindings"]) == 1

    # Seek back to empty — binding should disappear.
    r_back = client.post("/api/assembly/features/seek", json={"position": -2})
    assert r_back.status_code == 200, r_back.text
    asm_back = r_back.json()["assembly"]
    assert asm_back["overhang_bindings"] == []
    assert asm_back["feature_log_cursor"] == -2

    # Seek to end — binding returns.
    r_fwd = client.post("/api/assembly/features/seek", json={"position": -1})
    assert r_fwd.status_code == 200
    asm_fwd = r_fwd.json()["assembly"]
    assert len(asm_fwd["overhang_bindings"]) == 1
    assert asm_fwd["feature_log_cursor"] == -1


# ── Assembly overhang connections (cross-part linkers) ────────────────────────

def _connection_payload(*, instance_a="inst-A", overhang_a="oh-A_5p",
                        instance_b="inst-B", overhang_b="oh-B_3p",
                        attach_a="free_end", attach_b="root",
                        linker_type="ss", length_value=12, length_unit="bp",
                        bridge_sequence=None, name=None):
    body = {
        "instance_a_id": instance_a, "overhang_a_id": overhang_a,
        "overhang_a_attach": attach_a,
        "instance_b_id": instance_b, "overhang_b_id": overhang_b,
        "overhang_b_attach": attach_b,
        "linker_type": linker_type,
        "length_value": length_value, "length_unit": length_unit,
    }
    if bridge_sequence is not None: body["bridge_sequence"] = bridge_sequence
    if name is not None:            body["name"] = name
    return body


def _seed_polarity_assembly() -> Assembly:
    """Two parts each with one overhang whose id suffix encodes polarity."""
    d_a = _design_with_overhang("oh-A_5p", "ACGT")
    d_b = _design_with_overhang("oh-B_3p", "ACGT")
    a = Assembly(instances=[
        PartInstance(id="inst-A", name="PartA", source=PartSourceInline(design=d_a)),
        PartInstance(id="inst-B", name="PartB", source=PartSourceInline(design=d_b)),
    ])
    assembly_state.set_assembly(a)
    return a


def test_create_connection_200():
    _seed_polarity_assembly()
    # end-to-end ss linker requires OPPOSITE polarity → 5p/3p OK.
    r = client.post("/api/assembly/overhang-connections", json=_connection_payload(
        attach_a="free_end", attach_b="free_end", linker_type="ss",
    ))
    assert r.status_code == 200, r.text
    asm = r.json()["assembly"]
    assert len(asm["overhang_connections"]) == 1
    conn = asm["overhang_connections"][0]
    assert conn["linker_type"] == "ss"
    assert conn["length_value"] == 12
    assert conn["name"] == "AL1"
    # Feature log captured.
    assert any(e["op_kind"] == "assembly-overhang-connection-add" for e in asm["feature_log"])


def test_create_connection_polarity_forbidden_422():
    # ss linker with mixed attach (end-to-root) requires SAME polarity (5p/5p
    # or 3p/3p). Seed gives us 5p/3p → server should reject.
    _seed_polarity_assembly()
    r = client.post("/api/assembly/overhang-connections", json=_connection_payload(
        attach_a="free_end", attach_b="root", linker_type="ss",
    ))
    assert r.status_code == 422, r.text
    assert "polarity" in r.text.lower()


def test_create_connection_unknown_instance_404():
    _seed_polarity_assembly()
    r = client.post("/api/assembly/overhang-connections",
                    json=_connection_payload(instance_a="bogus"))
    assert r.status_code == 404


def test_create_connection_rejects_negative_length_400():
    _seed_polarity_assembly()
    # Length 0 is now allowed (indirect variants use it); only strictly
    # negative is rejected.
    r = client.post("/api/assembly/overhang-connections",
                    json=_connection_payload(length_value=-1))
    assert r.status_code == 400


def test_create_connection_allows_zero_length_for_indirect():
    _seed_polarity_assembly()
    # Indirect ss linker with same-attach (end-to-end-indirect) requires
    # opposite polarity, which the 5p/3p seed satisfies. length_value=0
    # mirrors what the frontend sends for indirect variants.
    r = client.post("/api/assembly/overhang-connections", json=_connection_payload(
        attach_a="free_end", attach_b="free_end", linker_type="ss",
        length_value=0,
    ))
    assert r.status_code == 200, r.text
    assert r.json()["assembly"]["overhang_connections"][0]["length_value"] == 0


def test_patch_connection_changes_length():
    _seed_polarity_assembly()
    # Use ds with end-to-root attach: ds + mixed attach wants OPPOSITE
    # polarity, which our 5p/3p seed satisfies.
    r = client.post("/api/assembly/overhang-connections", json=_connection_payload(
        linker_type="ds", attach_a="free_end", attach_b="root",
    ))
    cid = r.json()["assembly"]["overhang_connections"][0]["id"]
    r2 = client.patch(f"/api/assembly/overhang-connections/{cid}", json={"length_value": 24})
    assert r2.status_code == 200, r2.text
    conn = r2.json()["assembly"]["overhang_connections"][0]
    assert conn["length_value"] == 24


def test_delete_connection_removes_row():
    _seed_polarity_assembly()
    r = client.post("/api/assembly/overhang-connections", json=_connection_payload(
        linker_type="ds", attach_a="free_end", attach_b="root",
    ))
    cid = r.json()["assembly"]["overhang_connections"][0]["id"]
    r2 = client.delete(f"/api/assembly/overhang-connections/{cid}")
    assert r2.status_code == 200, r2.text
    asm = r2.json()["assembly"]
    assert asm["overhang_connections"] == []
    assert any(e["op_kind"] == "assembly-overhang-connection-delete" for e in asm["feature_log"])


def test_connection_seek_round_trip():
    _seed_polarity_assembly()
    r = client.post("/api/assembly/overhang-connections", json=_connection_payload(
        linker_type="ds", attach_a="free_end", attach_b="root",
    ))
    assert r.status_code == 200
    r_back = client.post("/api/assembly/features/seek", json={"position": -2})
    assert r_back.json()["assembly"]["overhang_connections"] == []
    r_fwd = client.post("/api/assembly/features/seek", json={"position": -1})
    assert len(r_fwd.json()["assembly"]["overhang_connections"]) == 1


def test_seek_to_explicit_index():
    _, sd = _seed_two_part_assembly()
    body1 = {
        "instance_a_id": "inst-A", "sub_domain_a_id": sd["A"], "overhang_a_id": "oh-A",
        "instance_b_id": "inst-B", "sub_domain_b_id": sd["B"], "overhang_b_id": "oh-B",
    }
    r1 = client.post("/api/assembly/overhang-bindings", json=body1)
    binding_id = r1.json()["assembly"]["overhang_bindings"][0]["id"]
    r2 = client.patch(f"/api/assembly/overhang-bindings/{binding_id}", json={"binding_mode": "toehold"})
    assert len(r2.json()["assembly"]["feature_log"]) == 2

    # Seek to position 0 — bind applied, patch undone.
    r_seek = client.post("/api/assembly/features/seek", json={"position": 0})
    assert r_seek.status_code == 200, r_seek.text
    asm = r_seek.json()["assembly"]
    assert len(asm["overhang_bindings"]) == 1
    assert asm["overhang_bindings"][0]["binding_mode"] == "duplex"
    assert asm["feature_log_cursor"] == 0


# ── Linker topology generation (cross-part) ───────────────────────────────────
#
# When an AssemblyOverhangConnection is created, the assembly should also
# materialise the linker as complement strands + a virtual __lnk__ helix +
# bridge strand on `assembly_strands` / `assembly_helices`, so the linker is
# visible in the 3D workspace and shows up in the strand spreadsheet.

def _design_with_real_oh(oh_id: str, sequence: str | None) -> Design:
    """Design with a real Helix + Strand whose only domain carries overhang_id.

    Mirrors `_seed_with_real_oh_domains` in test_overhang_connections.py but
    parameterised so the same shape works for each assembly side. The OH id
    suffix (`_5p` / `_3p`) is preserved so the polarity rule still applies."""
    length_bp = 8
    helix_id  = f"hx_{oh_id}"
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
        domains=[Domain(
            helix_id=helix_id, start_bp=0, end_bp=length_bp - 1,
            direction=direction, overhang_id=oh_id,
        )],
        strand_type=StrandType.STAPLE,
    )
    ovhg = OverhangSpec(
        id=oh_id, helix_id=helix_id, strand_id=strand_id,
        sequence=sequence, label=oh_id,
    )
    return Design(helices=[helix], strands=[strand], overhangs=[ovhg])


def _seed_real_two_part_assembly(seq_a="ACGTACGT", seq_b="GGGGCCCC") -> Assembly:
    """Two-part assembly with real OH-tagged domains. Each part is offset on
    the +X axis so their world-space anchors differ — gives the bridge axis a
    meaningful chord."""
    d_a = _design_with_real_oh("oh-A_5p", seq_a)
    d_b = _design_with_real_oh("oh-B_3p", seq_b)
    # Offset side B along +X by 10 nm — simple translation matrix in
    # row-major form. (See Mat4x4 docstring; default is identity.)
    t_b = Mat4x4(values=[
        1, 0, 0, 10,
        0, 1, 0, 0,
        0, 0, 1, 0,
        0, 0, 0, 1,
    ])
    a = Assembly(instances=[
        PartInstance(id="inst-A", name="PartA", source=PartSourceInline(design=d_a)),
        PartInstance(id="inst-B", name="PartB", source=PartSourceInline(design=d_b), transform=t_b),
    ])
    assembly_state.set_assembly(a)
    return a


def _conn_payload_real(*, linker_type="ds", attach_a="free_end", attach_b="root",
                        length_value=8, length_unit="bp", bridge_sequence=None):
    body = {
        "instance_a_id": "inst-A", "overhang_a_id": "oh-A_5p",
        "overhang_a_attach": attach_a,
        "instance_b_id": "inst-B", "overhang_b_id": "oh-B_3p",
        "overhang_b_attach": attach_b,
        "linker_type": linker_type,
        "length_value": length_value, "length_unit": length_unit,
    }
    if bridge_sequence is not None:
        body["bridge_sequence"] = bridge_sequence
    return body


def test_post_overhang_connection_generates_ds_linker_topology():
    _seed_real_two_part_assembly()
    r = client.post("/api/assembly/overhang-connections",
                    json=_conn_payload_real(linker_type="ds",
                                            attach_a="free_end", attach_b="root"))
    assert r.status_code == 200, r.text
    asm = r.json()["assembly"]
    cid = asm["overhang_connections"][0]["id"]
    # One virtual helix + two per-side strands.
    helix_ids  = [h["id"] for h in asm["assembly_helices"]]
    strand_ids = [s["id"] for s in asm["assembly_strands"]]
    assert f"__lnk__{cid}" in helix_ids
    assert f"__lnk__{cid}__a" in strand_ids
    assert f"__lnk__{cid}__b" in strand_ids
    # Each strand has a complement domain (on the namespaced part helix) +
    # a bridge domain (on the virtual __lnk__ helix).
    strand_a = next(s for s in asm["assembly_strands"] if s["id"] == f"__lnk__{cid}__a")
    helix_ids_in_a = {d["helix_id"] for d in strand_a["domains"]}
    assert any("::" in hid for hid in helix_ids_in_a)        # namespaced complement
    assert f"__lnk__{cid}" in helix_ids_in_a                  # bridge


def test_post_overhang_connection_generates_ss_linker_topology():
    _seed_real_two_part_assembly()
    # ss with end-to-end (mixed-attach + opposite polarity 5p/3p) is allowed.
    r = client.post("/api/assembly/overhang-connections",
                    json=_conn_payload_real(linker_type="ss",
                                            attach_a="free_end", attach_b="free_end"))
    assert r.status_code == 200, r.text
    asm = r.json()["assembly"]
    cid = asm["overhang_connections"][0]["id"]
    strand_ids = [s["id"] for s in asm["assembly_strands"]]
    assert strand_ids.count(f"__lnk__{cid}__s") == 1
    # ss strand carries [complementA, bridge, complementB] = 3 domains.
    strand_s = next(s for s in asm["assembly_strands"] if s["id"] == f"__lnk__{cid}__s")
    assert len(strand_s["domains"]) == 3


def test_delete_overhang_connection_removes_linker_topology():
    _seed_real_two_part_assembly()
    r = client.post("/api/assembly/overhang-connections",
                    json=_conn_payload_real(linker_type="ds"))
    cid = r.json()["assembly"]["overhang_connections"][0]["id"]
    r_del = client.delete(f"/api/assembly/overhang-connections/{cid}")
    assert r_del.status_code == 200, r_del.text
    asm = r_del.json()["assembly"]
    helix_ids  = [h["id"] for h in asm["assembly_helices"]]
    strand_ids = [s["id"] for s in asm["assembly_strands"]]
    assert not any(hid.startswith(f"__lnk__{cid}") for hid in helix_ids)
    assert not any(sid.startswith(f"__lnk__{cid}") for sid in strand_ids)


def test_patch_length_regenerates_linker_topology():
    _seed_real_two_part_assembly()
    r = client.post("/api/assembly/overhang-connections",
                    json=_conn_payload_real(linker_type="ds", length_value=8))
    cid = r.json()["assembly"]["overhang_connections"][0]["id"]

    # The bridge domain on the regenerated strands should span the new bp range.
    r2 = client.patch(f"/api/assembly/overhang-connections/{cid}",
                      json={"length_value": 12})
    assert r2.status_code == 200, r2.text
    asm = r2.json()["assembly"]
    strand_a = next(s for s in asm["assembly_strands"] if s["id"] == f"__lnk__{cid}__a")
    bridge_dom = next(d for d in strand_a["domains"] if d["helix_id"] == f"__lnk__{cid}")
    assert {bridge_dom["start_bp"], bridge_dom["end_bp"]} == {0, 11}


def test_patch_bridge_sequence_updates_strand_sequence():
    _seed_real_two_part_assembly()
    r = client.post("/api/assembly/overhang-connections",
                    json=_conn_payload_real(linker_type="ss",
                                            attach_a="free_end", attach_b="free_end",
                                            length_value=4, bridge_sequence="AAAA"))
    cid = r.json()["assembly"]["overhang_connections"][0]["id"]
    # Sanity: composed sequence at create time = RC(oh-A) + AAAA + RC(oh-B).
    s_before = next(s for s in r.json()["assembly"]["assembly_strands"]
                    if s["id"] == f"__lnk__{cid}__s")
    assert "AAAA" in (s_before["sequence"] or "")

    r2 = client.patch(f"/api/assembly/overhang-connections/{cid}",
                      json={"bridge_sequence": "GGGG"})
    assert r2.status_code == 200, r2.text
    s_after = next(s for s in r2.json()["assembly"]["assembly_strands"]
                   if s["id"] == f"__lnk__{cid}__s")
    assert "GGGG" in (s_after["sequence"] or "")
    assert "AAAA" not in (s_after["sequence"] or "")


def test_ds_linker_strand_sequence_composition():
    """ds linker side A (comp-first polarity) = RC(OH-A) + bridge_sequence."""
    _seed_real_two_part_assembly(seq_a="ACGTACGT", seq_b="GGGGCCCC")
    # 5p + free_end → comp_first = True.  Bridge on side A reads as written
    # (the user-typed bridge_sequence is in side A's 5'→3' frame).
    r = client.post("/api/assembly/overhang-connections",
                    json=_conn_payload_real(linker_type="ds",
                                            attach_a="free_end", attach_b="root",
                                            length_value=4, bridge_sequence="TTTT"))
    cid = r.json()["assembly"]["overhang_connections"][0]["id"]
    strand_a = next(s for s in r.json()["assembly"]["assembly_strands"]
                    if s["id"] == f"__lnk__{cid}__a")
    # RC("ACGTACGT") = "ACGTACGT" (palindrome) + "TTTT".
    assert strand_a["sequence"] == "ACGTACGT" + "TTTT"


def test_ss_linker_strand_sequence_composition():
    """ss linker = RC(OH-A) + bridge_sequence + RC(OH-B)."""
    _seed_real_two_part_assembly(seq_a="AAAAGGGG", seq_b="TTTTCCCC")
    r = client.post("/api/assembly/overhang-connections",
                    json=_conn_payload_real(linker_type="ss",
                                            attach_a="free_end", attach_b="free_end",
                                            length_value=4, bridge_sequence="NNNN"))
    cid = r.json()["assembly"]["overhang_connections"][0]["id"]
    strand_s = next(s for s in r.json()["assembly"]["assembly_strands"]
                    if s["id"] == f"__lnk__{cid}__s")
    # RC("AAAAGGGG") = "CCCCTTTT";  RC("TTTTCCCC") = "GGGGAAAA".
    assert strand_s["sequence"] == "CCCCTTTT" + "NNNN" + "GGGGAAAA"
