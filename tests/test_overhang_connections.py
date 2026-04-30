"""
Tests for the metadata-only OverhangConnection feature.

Endpoints under test:
  POST   /design/overhang-connections
  DELETE /design/overhang-connections/{conn_id}

These records are pure annotations — no strand topology is mutated. The API
is tested against a synthetic design seeded with two minimal OverhangSpecs.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from backend.api import state as design_state
from backend.api.main import app
from backend.api.routes import _demo_design
from backend.core.constants import BDNA_RISE_PER_BP
from backend.core.lattice import assign_overhang_connection_names
from backend.core.models import (
    Design, Direction, Domain, Helix, OverhangConnection, OverhangSpec,
    Strand, StrandType, Vec3,
)


client = TestClient(app)


def _seed_with_two_overhangs() -> Design:
    """Demo design plus four synthetic OverhangSpec entries (no real geometry).

    Four overhangs (two 5p, two 3p) so tests can build multiple connections
    without bumping into the per-end uniqueness rule.
    """
    base = _demo_design()
    overhangs = [
        OverhangSpec(id="ovhg_inline_a_5p", helix_id="demo_helix", strand_id="staple_0", label="OH1"),
        OverhangSpec(id="ovhg_inline_a_3p", helix_id="demo_helix", strand_id="staple_0", label="OH2"),
        OverhangSpec(id="ovhg_inline_b_5p", helix_id="demo_helix", strand_id="staple_0", label="OH3"),
        OverhangSpec(id="ovhg_inline_b_3p", helix_id="demo_helix", strand_id="staple_0", label="OH4"),
    ]
    return base.model_copy(update={"overhangs": overhangs})


def _seed_with_two_5p_overhangs() -> Design:
    """Demo design with two 5p overhangs (same-end pair — rule constraints apply)."""
    base = _demo_design()
    overhangs = [
        OverhangSpec(id="ovhg_inline_a_5p", helix_id="demo_helix", strand_id="staple_0", label="OH1"),
        OverhangSpec(id="ovhg_inline_b_5p", helix_id="demo_helix", strand_id="staple_0", label="OH2"),
    ]
    return base.model_copy(update={"overhangs": overhangs})


def _seed_with_real_oh_domains() -> Design:
    """Two extruded overhang helices, each with a staple strand whose only
    domain has overhang_id set. Mirrors what an actual user design looks like
    after Tools → Extrude Overhang. Used to validate that ds linker complement
    domains are placed on the real OH helices.
    """
    base = _demo_design()
    oh_helix_a = Helix(
        id="oh_helix_a",
        axis_start=Vec3(x=2.5, y=0.0, z=0.0),
        axis_end=Vec3(x=2.5, y=0.0, z=8 * BDNA_RISE_PER_BP),
        phase_offset=0.0,
        length_bp=8,
    )
    oh_helix_b = Helix(
        id="oh_helix_b",
        axis_start=Vec3(x=5.0, y=0.0, z=0.0),
        axis_end=Vec3(x=5.0, y=0.0, z=8 * BDNA_RISE_PER_BP),
        phase_offset=0.0,
        length_bp=8,
    )
    oh_strand_a = Strand(
        id="oh_strand_a",
        domains=[Domain(
            helix_id="oh_helix_a", start_bp=0, end_bp=7,
            direction=Direction.FORWARD, overhang_id="oh_a_5p",
        )],
        strand_type=StrandType.STAPLE,
    )
    oh_strand_b = Strand(
        id="oh_strand_b",
        domains=[Domain(
            helix_id="oh_helix_b", start_bp=0, end_bp=7,
            direction=Direction.REVERSE, overhang_id="oh_b_5p",
        )],
        strand_type=StrandType.STAPLE,
    )
    overhangs = [
        OverhangSpec(id="oh_a_5p", helix_id="oh_helix_a", strand_id="oh_strand_a", label="OHA"),
        OverhangSpec(id="oh_b_5p", helix_id="oh_helix_b", strand_id="oh_strand_b", label="OHB"),
    ]
    return base.model_copy(update={
        "helices": [*base.helices, oh_helix_a, oh_helix_b],
        "strands": [*base.strands, oh_strand_a, oh_strand_b],
        "overhangs": overhangs,
    })


@pytest.fixture(autouse=True)
def _reset():
    design_state.set_design(_seed_with_two_overhangs())
    yield
    design_state.set_design(_demo_design())


# ── POST ──────────────────────────────────────────────────────────────────────


def _post_conn(**overrides) -> dict:
    body = {
        "overhang_a_id": "ovhg_inline_a_5p",
        "overhang_a_attach": "free_end",
        "overhang_b_id": "ovhg_inline_a_3p",
        "overhang_b_attach": "root",
        "linker_type": "ss",
        "length_value": 12,
        "length_unit": "bp",
    }
    body.update(overrides)
    r = client.post("/api/design/overhang-connections", json=body)
    return r


# Helper for tests that need a SECOND connection — uses OH3+OH4.
def _post_conn_2(**overrides) -> dict:
    body = {
        "overhang_a_id": "ovhg_inline_b_5p",
        "overhang_a_attach": "free_end",
        "overhang_b_id": "ovhg_inline_b_3p",
        "overhang_b_attach": "root",
        "linker_type": "ds",
        "length_value": 8,
        "length_unit": "bp",
    }
    body.update(overrides)
    r = client.post("/api/design/overhang-connections", json=body)
    return r


def test_post_creates_connection_with_l1_name():
    r = _post_conn()
    assert r.status_code == 201, r.text
    conns = r.json()["design"]["overhang_connections"]
    assert len(conns) == 1
    assert conns[0]["name"] == "L1"
    assert conns[0]["overhang_a_attach"] == "free_end"
    assert conns[0]["overhang_b_attach"] == "root"
    assert conns[0]["linker_type"] == "ss"
    assert conns[0]["length_value"] == 12
    assert conns[0]["length_unit"] == "bp"


def test_second_post_yields_l2():
    _post_conn()
    r = _post_conn_2(length_value=4.08, length_unit="nm")
    assert r.status_code == 201
    conns = r.json()["design"]["overhang_connections"]
    names = sorted(c["name"] for c in conns)
    assert names == ["L1", "L2"]


def test_delete_removes_by_id_and_preserves_others():
    _post_conn()
    r = _post_conn_2(length_value=20)
    conns = r.json()["design"]["overhang_connections"]
    l1_id = next(c["id"] for c in conns if c["name"] == "L1")

    r = client.delete(f"/api/design/overhang-connections/{l1_id}")
    assert r.status_code == 200
    remaining = r.json()["design"]["overhang_connections"]
    assert len(remaining) == 1
    assert remaining[0]["name"] == "L2"


def test_post_after_delete_reuses_lowest_unused_name():
    """After deleting L1, a fresh POST should fill the L1 slot, not L3."""
    _post_conn()       # L1 — uses OH1 + OH2
    _post_conn_2()     # L2 — uses OH3 + OH4
    r = client.get("/api/design").json()
    l1_id = next(c["id"] for c in r["design"]["overhang_connections"] if c["name"] == "L1")
    client.delete(f"/api/design/overhang-connections/{l1_id}")
    # OH1 + OH2 are now free; reposting fills the L1 slot.
    r = _post_conn()
    names = sorted(c["name"] for c in r.json()["design"]["overhang_connections"])
    assert names == ["L1", "L2"]


def test_same_overhang_on_both_sides_is_400():
    r = _post_conn(overhang_b_id="ovhg_inline_a_5p")
    assert r.status_code == 400


def test_unknown_overhang_id_is_404():
    r = _post_conn(overhang_a_id="ovhg_does_not_exist")
    assert r.status_code == 404


def test_zero_length_is_400():
    r = _post_conn(length_value=0)
    assert r.status_code == 400


def test_invalid_attach_value_is_422():
    r = _post_conn(overhang_a_attach="middle")  # not a Literal value
    assert r.status_code == 422


def test_delete_unknown_id_is_404():
    r = client.delete("/api/design/overhang-connections/does-not-exist")
    assert r.status_code == 404


# ── Persistence ───────────────────────────────────────────────────────────────


def test_round_trip_json_preserves_connections():
    design = assign_overhang_connection_names(
        _seed_with_two_overhangs().model_copy(update={
            "overhang_connections": [
                OverhangConnection(
                    overhang_a_id="ovhg_inline_a_5p",
                    overhang_a_attach="free_end",
                    overhang_b_id="ovhg_inline_a_3p",
                    overhang_b_attach="root",
                    linker_type="ds",
                    length_value=21,
                    length_unit="bp",
                ),
            ],
        })
    )
    text = design.to_json()
    parsed = Design.from_json(text)
    assert len(parsed.overhang_connections) == 1
    assert parsed.overhang_connections[0].name == "L1"
    assert parsed.overhang_connections[0].linker_type == "ds"


# ── Compatibility rules ───────────────────────────────────────────────────────


@pytest.fixture
def _seed_5p_pair():
    design_state.set_design(_seed_with_two_5p_overhangs())
    yield
    design_state.set_design(_demo_design())


def _post_5p(linker_type, attach_a, attach_b):
    return client.post("/api/design/overhang-connections", json={
        "overhang_a_id": "ovhg_inline_a_5p",
        "overhang_a_attach": attach_a,
        "overhang_b_id": "ovhg_inline_b_5p",
        "overhang_b_attach": attach_b,
        "linker_type": linker_type,
        "length_value": 8,
        "length_unit": "bp",
    })


@pytest.mark.usefixtures("_seed_5p_pair")
class TestSameEndRules:
    """Same-end (5p+5p or 3p+3p) overhangs trigger compatibility constraints."""

    def test_ds_with_matching_attach_is_allowed(self):
        assert _post_5p("ds", "root", "root").status_code == 201

    def test_ds_with_matching_attach_free_end_is_allowed(self):
        assert _post_5p("ds", "free_end", "free_end").status_code == 201

    def test_ds_with_mismatched_attach_is_400(self):
        r = _post_5p("ds", "root", "free_end")
        assert r.status_code == 400
        assert "matching attach points" in r.text

    def test_ss_with_mismatched_attach_is_allowed(self):
        assert _post_5p("ss", "root", "free_end").status_code == 201

    def test_ss_with_mismatched_attach_other_order_is_allowed(self):
        assert _post_5p("ss", "free_end", "root").status_code == 201

    def test_ss_with_matching_attach_is_400(self):
        r = _post_5p("ss", "root", "root")
        assert r.status_code == 400
        assert "opposite attach points" in r.text


def test_different_ends_have_no_attach_constraint():
    """5p+3p pair is unrestricted — all attach combos work for both ss and ds."""
    for linker_type in ("ss", "ds"):
        for a in ("root", "free_end"):
            for b in ("root", "free_end"):
                # reset between attempts (each post consumes the chosen ends).
                design_state.set_design(_seed_with_two_overhangs())
                r = client.post("/api/design/overhang-connections", json={
                    "overhang_a_id": "ovhg_inline_a_5p",
                    "overhang_a_attach": a,
                    "overhang_b_id": "ovhg_inline_a_3p",
                    "overhang_b_attach": b,
                    "linker_type": linker_type,
                    "length_value": 5,
                    "length_unit": "bp",
                })
                assert r.status_code == 201, f"{linker_type} {a}/{b}: {r.text}"


# ── PATCH (editable name + length) ────────────────────────────────────────────


def test_patch_renames_connection():
    r = _post_conn()
    cid = r.json()["design"]["overhang_connections"][0]["id"]
    r = client.patch(f"/api/design/overhang-connections/{cid}", json={"name": "MyLink"})
    assert r.status_code == 200
    assert r.json()["design"]["overhang_connections"][0]["name"] == "MyLink"


def test_patch_updates_length_and_unit():
    r = _post_conn()
    cid = r.json()["design"]["overhang_connections"][0]["id"]
    r = client.patch(f"/api/design/overhang-connections/{cid}",
                     json={"length_value": 6.8, "length_unit": "nm"})
    assert r.status_code == 200
    conn = r.json()["design"]["overhang_connections"][0]
    assert conn["length_value"] == 6.8
    assert conn["length_unit"] == "nm"


def test_patch_only_name_does_not_touch_length():
    r = _post_conn(length_value=20, length_unit="bp")
    cid = r.json()["design"]["overhang_connections"][0]["id"]
    r = client.patch(f"/api/design/overhang-connections/{cid}", json={"name": "Bridge"})
    conn = r.json()["design"]["overhang_connections"][0]
    assert conn["name"] == "Bridge"
    assert conn["length_value"] == 20
    assert conn["length_unit"] == "bp"


def test_patch_empty_name_is_400():
    r = _post_conn()
    cid = r.json()["design"]["overhang_connections"][0]["id"]
    r = client.patch(f"/api/design/overhang-connections/{cid}", json={"name": "  "})
    assert r.status_code == 400


def test_patch_duplicate_name_is_400():
    _post_conn()
    _post_conn_2()
    conns = client.get("/api/design").json()["design"]["overhang_connections"]
    l2 = next(c for c in conns if c["name"] == "L2")
    r = client.patch(f"/api/design/overhang-connections/{l2['id']}", json={"name": "L1"})
    assert r.status_code == 400


def test_patch_unknown_id_is_404():
    r = client.patch("/api/design/overhang-connections/nope", json={"name": "x"})
    assert r.status_code == 404


def test_patch_zero_length_is_400():
    r = _post_conn()
    cid = r.json()["design"]["overhang_connections"][0]["id"]
    r = client.patch(f"/api/design/overhang-connections/{cid}", json={"length_value": 0})
    assert r.status_code == 400


# ── Per-end uniqueness ───────────────────────────────────────────────────────


def test_reusing_overhang_end_is_400():
    """Each (overhang, attach) pair can only be in one connection."""
    _post_conn()  # uses (OH1, free_end) and (OH2, root)
    r = _post_conn(overhang_b_id="ovhg_inline_b_3p")  # would re-use (OH1, free_end)
    assert r.status_code == 400
    assert "already linked" in r.text


def test_reusing_root_end_is_400():
    _post_conn()  # uses (OH2, root)
    r = _post_conn(overhang_a_id="ovhg_inline_b_5p", overhang_b_id="ovhg_inline_a_3p")
    # would re-use (OH2, root)
    assert r.status_code == 400


def test_two_connections_per_overhang_when_other_end_is_free():
    """OH can appear in two connections if it uses both root and free_end."""
    _post_conn()  # (OH1 free_end) + (OH2 root)
    # Second connection uses OH1's root end + a fresh OH3.
    r = client.post("/api/design/overhang-connections", json={
        "overhang_a_id": "ovhg_inline_a_5p", "overhang_a_attach": "root",
        "overhang_b_id": "ovhg_inline_b_5p", "overhang_b_attach": "free_end",
        "linker_type": "ss", "length_value": 5, "length_unit": "bp",
    })
    assert r.status_code == 201, r.text


# ── Linker topology generation ────────────────────────────────────────────────


def _linker_strands_for(design_dict, conn_id):
    prefix = f"__lnk__{conn_id}"
    return [s for s in design_dict["strands"] if s["id"].startswith(prefix)]


def _linker_helices_for(design_dict, conn_id):
    prefix = f"__lnk__{conn_id}"
    return [h for h in design_dict["helices"] if h["id"].startswith(prefix)]


def test_ss_linker_creates_two_complement_strands_no_bridge_helix():
    """ss linker against a real-OH-domain seed: 2 complement strands, NO virtual
    bridge helix (the bridge is the frontend arc only).
    """
    design_state.set_design(_seed_with_real_oh_domains())
    r = client.post("/api/design/overhang-connections", json={
        "overhang_a_id": "oh_a_5p", "overhang_a_attach": "free_end",
        "overhang_b_id": "oh_b_5p", "overhang_b_attach": "root",
        "linker_type": "ss", "length_value": 12, "length_unit": "bp",
    })
    assert r.status_code == 201, r.text
    design = r.json()["design"]
    cid = design["overhang_connections"][0]["id"]
    strands = _linker_strands_for(design, cid)
    helices = _linker_helices_for(design, cid)
    assert len(strands) == 2, "ss linker should create one complement strand per overhang"
    assert len(helices) == 0, "ss linker should not create a virtual bridge helix"
    # Each complement strand has exactly 1 domain — the complement on a real OH helix.
    for s in strands:
        assert s["strand_type"] == "linker"
        assert s["color"] == "#ffffff"
        assert len(s["domains"]) == 1
        assert not s["domains"][0]["helix_id"].startswith("__lnk__"), \
            f"ss linker complement domain should be on a real helix, got {s['domains'][0]['helix_id']}"


def test_ss_linker_no_strands_when_overhangs_lack_domains():
    """Synthetic seed (no real OH domains): ss linker has nothing to anchor —
    no strands, no virtual helix. Connection metadata is still recorded.
    """
    r = _post_conn(linker_type="ss", length_value=10)
    design = r.json()["design"]
    cid = design["overhang_connections"][0]["id"]
    assert len(_linker_strands_for(design, cid)) == 0
    assert len(_linker_helices_for(design, cid)) == 0


def test_ds_linker_creates_two_strands_one_bridge_helix():
    r = _post_conn(linker_type="ds", length_value=8)
    design = r.json()["design"]
    cid = design["overhang_connections"][0]["id"]
    # 2 strands (one per overhang side); 1 virtual bridge helix shared between them.
    assert len(_linker_strands_for(design, cid)) == 2
    assert len(_linker_helices_for(design, cid)) == 1
    types = sorted(s["strand_type"] for s in _linker_strands_for(design, cid))
    assert types == ["linker", "linker"]


def test_ds_linker_complement_domains_on_real_oh_helices():
    """The two ds-linker strands each carry a complement domain on the same
    real helix as the overhang they pair with, with antiparallel direction.
    """
    design_state.set_design(_seed_with_real_oh_domains())
    r = client.post("/api/design/overhang-connections", json={
        "overhang_a_id": "oh_a_5p", "overhang_a_attach": "free_end",
        "overhang_b_id": "oh_b_5p", "overhang_b_attach": "free_end",
        "linker_type": "ds", "length_value": 6, "length_unit": "bp",
    })
    assert r.status_code == 201, r.text
    design = r.json()["design"]
    cid = design["overhang_connections"][0]["id"]

    strand_a = next(s for s in design["strands"] if s["id"] == f"__lnk__{cid}__a")
    strand_b = next(s for s in design["strands"] if s["id"] == f"__lnk__{cid}__b")

    # 2 domains each: complement (real OH helix) + bridge (virtual __lnk__ helix).
    assert len(strand_a["domains"]) == 2
    assert len(strand_b["domains"]) == 2

    # Complement A on oh_helix_a, opposite direction to OH-A (FORWARD → REVERSE),
    # same bp range, swapped start/end (start=oh.end_bp, end=oh.start_bp).
    comp_a, bridge_a = strand_a["domains"]
    assert comp_a["helix_id"]  == "oh_helix_a"
    assert comp_a["direction"] == "REVERSE"
    assert comp_a["start_bp"]  == 7
    assert comp_a["end_bp"]    == 0
    assert bridge_a["helix_id"] == f"__lnk__{cid}"
    assert bridge_a["direction"] == "FORWARD"

    # Complement B on oh_helix_b, opposite to OH-B (REVERSE → FORWARD).
    comp_b, bridge_b = strand_b["domains"]
    assert comp_b["helix_id"]  == "oh_helix_b"
    assert comp_b["direction"] == "FORWARD"
    assert comp_b["start_bp"]  == 7
    assert comp_b["end_bp"]    == 0
    assert bridge_b["helix_id"] == f"__lnk__{cid}"
    assert bridge_b["direction"] == "REVERSE"


def test_ds_linker_complement_renders_via_geometry_pipeline():
    """The complement nucleotides must appear in /design/geometry tagged with
    the linker strand id and color so the frontend can render them.
    """
    design_state.set_design(_seed_with_real_oh_domains())
    r = client.post("/api/design/overhang-connections", json={
        "overhang_a_id": "oh_a_5p", "overhang_a_attach": "free_end",
        "overhang_b_id": "oh_b_5p", "overhang_b_attach": "free_end",
        "linker_type": "ds", "length_value": 6, "length_unit": "bp",
    })
    cid = r.json()["design"]["overhang_connections"][0]["id"]

    geom = client.get("/api/design/geometry").json()
    nucs = geom["nucleotides"]

    # Strand A's complement nucs: helix=oh_helix_a, REVERSE, bp 0..7, strand_id=__lnk__<cid>__a.
    a_nucs = [n for n in nucs if n.get("strand_id") == f"__lnk__{cid}__a"]
    assert len(a_nucs) == 8, f"expected 8 complement nucs for strand A, got {len(a_nucs)}"
    assert all(n["strand_type"] == "linker" for n in a_nucs)
    assert all(n["direction"] == "REVERSE" for n in a_nucs)
    assert {n["bp_index"] for n in a_nucs} == set(range(8))

    b_nucs = [n for n in nucs if n.get("strand_id") == f"__lnk__{cid}__b"]
    assert len(b_nucs) == 8
    assert all(n["direction"] == "FORWARD" for n in b_nucs)


def test_ss_linker_complement_renders_via_geometry_pipeline():
    """ss linker (like ds) emits complement nucleotides on each real OH helix,
    tagged strand_type='linker' so the frontend renders them.
    """
    design_state.set_design(_seed_with_real_oh_domains())
    r = client.post("/api/design/overhang-connections", json={
        "overhang_a_id": "oh_a_5p", "overhang_a_attach": "free_end",
        "overhang_b_id": "oh_b_5p", "overhang_b_attach": "root",
        "linker_type": "ss", "length_value": 10, "length_unit": "bp",
    })
    cid = r.json()["design"]["overhang_connections"][0]["id"]
    geom = client.get("/api/design/geometry").json()
    nucs = geom["nucleotides"]
    a_nucs = [n for n in nucs if n.get("strand_id") == f"__lnk__{cid}__a"]
    b_nucs = [n for n in nucs if n.get("strand_id") == f"__lnk__{cid}__b"]
    assert len(a_nucs) == 8
    assert len(b_nucs) == 8
    assert all(n["strand_type"] == "linker" for n in a_nucs + b_nucs)
    assert all(n["helix_id"] in ("oh_helix_a", "oh_helix_b") for n in a_nucs + b_nucs)


def test_nm_unit_converts_to_bp():
    """4 nm ≈ 12 bp at 0.334 nm/bp. Tested on the ds bridge (only ds creates a
    virtual helix whose length we can read back)."""
    r = _post_conn(linker_type="ds", length_value=4.0, length_unit="nm")
    design = r.json()["design"]
    cid = design["overhang_connections"][0]["id"]
    helices = _linker_helices_for(design, cid)
    assert len(helices) == 1
    assert helices[0]["length_bp"] == 12   # round(4.0 / 0.334) == 12


def test_delete_cleans_up_linker_topology():
    r = _post_conn(linker_type="ds", length_value=8)
    design = r.json()["design"]
    cid = design["overhang_connections"][0]["id"]
    assert _linker_strands_for(design, cid)   # sanity

    r = client.delete(f"/api/design/overhang-connections/{cid}")
    design = r.json()["design"]
    assert _linker_strands_for(design, cid) == []
    assert _linker_helices_for(design, cid) == []


def test_patch_length_rebuilds_linker():
    """ds linker: PATCHing length must rebuild the bridge helix to the new bp."""
    r = _post_conn(linker_type="ds", length_value=5)
    cid = r.json()["design"]["overhang_connections"][0]["id"]
    r = client.patch(f"/api/design/overhang-connections/{cid}",
                     json={"length_value": 25})
    design = r.json()["design"]
    helices = _linker_helices_for(design, cid)
    assert len(helices) == 1
    assert helices[0]["length_bp"] == 25
    # Still 2 ds linker strands (one per overhang side).
    assert len(_linker_strands_for(design, cid)) == 2


def test_patch_name_only_does_not_rebuild():
    """ds linker: renaming must NOT touch the bridge helix."""
    r = _post_conn(linker_type="ds", length_value=5)
    cid = r.json()["design"]["overhang_connections"][0]["id"]
    helix_id_before = _linker_helices_for(r.json()["design"], cid)[0]["id"]

    r = client.patch(f"/api/design/overhang-connections/{cid}", json={"name": "MyLink"})
    design = r.json()["design"]
    helices = _linker_helices_for(design, cid)
    # Helix wasn't rebuilt — same id, same length.
    assert len(helices) == 1
    assert helices[0]["id"] == helix_id_before


def test_linker_strands_excluded_from_validator():
    """Adding a linker shouldn't trip the 'unknown helix reference' validator."""
    r = _post_conn(linker_type="ds", length_value=8)
    assert r.status_code == 201
    validation = r.json()["validation"]
    # No bad-reference error — virtual __lnk__ helices are skipped by validator.
    failures = [v for v in validation["results"] if not v["ok"]]
    bad_ref_failures = [v for v in failures if "unknown helix" in v["message"]]
    assert bad_ref_failures == []


# ── Misc ──────────────────────────────────────────────────────────────────────


def test_assign_names_preserves_existing_and_picks_lowest_unused():
    """An incoming connection without a name is given L1 even if other Ln exist."""
    design = _seed_with_two_overhangs().model_copy(update={
        "overhang_connections": [
            OverhangConnection(
                name="L3",
                overhang_a_id="ovhg_inline_a_5p",
                overhang_a_attach="root",
                overhang_b_id="ovhg_inline_a_3p",
                overhang_b_attach="root",
                linker_type="ss",
                length_value=5,
                length_unit="bp",
            ),
            OverhangConnection(
                overhang_a_id="ovhg_inline_a_5p",
                overhang_a_attach="free_end",
                overhang_b_id="ovhg_inline_a_3p",
                overhang_b_attach="free_end",
                linker_type="ds",
                length_value=10,
                length_unit="bp",
            ),
        ],
    })
    out = assign_overhang_connection_names(design)
    assert out.overhang_connections[0].name == "L3"
    assert out.overhang_connections[1].name == "L1"
