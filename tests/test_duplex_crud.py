"""Phase 1 — Duplex CRUD router (``/design/duplexes``).

Create / patch-register / set-driver / delete + the pairing readouts, driven
through the FastAPI TestClient against a seeded active design. The Watson-Crick
gate is intentionally KEPT (user decision) so a mismatched register is a 422.
See ``memory/project_overhang_duplex_foundation.md``.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.api import state as design_state
from backend.api.main import app
from backend.api.routes import _demo_design
from backend.core.models import (
    Design, Direction, Domain, OverhangBinding, OverhangSpec, Strand, StrandType,
    SubDomain,
)

client = TestClient(app)
API = "/api/design/duplexes"


@pytest.fixture(autouse=True)
def _reset_state():
    yield
    design_state.set_design(_demo_design())


def _seed(seq_a="AAAC", seq_b="GTTT") -> Design:
    """Overhang A on forward domain [0,3], overhang B on reverse domain [3,0];
    each a single 4 nt sub-domain. Set as the active design."""
    sa = Strand(id="st_a", strand_type=StrandType.STAPLE,
                domains=[Domain(helix_id="hA", start_bp=0, end_bp=3,
                                direction=Direction.FORWARD, overhang_id="ohA")])
    sb = Strand(id="st_b", strand_type=StrandType.STAPLE,
                domains=[Domain(helix_id="hB", start_bp=3, end_bp=0,
                                direction=Direction.REVERSE, overhang_id="ohB")])
    ohA = OverhangSpec(id="ohA", helix_id="hA", strand_id="st_a", sequence=seq_a,
                       sub_domains=[SubDomain(id="sdA", start_bp_offset=0, length_bp=4)])
    ohB = OverhangSpec(id="ohB", helix_id="hB", strand_id="st_b", sequence=seq_b,
                       sub_domains=[SubDomain(id="sdB", start_bp_offset=0, length_bp=4)])
    d = Design(strands=[sa, sb], overhangs=[ohA, ohB])
    design_state.set_design(d)
    return d


def _end(oid, s, e):
    return {"overhang_id": oid, "start_bp": s, "end_bp": e}


def _create(left, right, **kw):
    return client.post(API, json={"left": left, "right": right, **kw})


# ── Create ────────────────────────────────────────────────────────────────────

def test_create_complementary_duplex():
    _seed()
    r = _create(_end("ohA", 0, 3), _end("ohB", 3, 0), driver="right")
    assert r.status_code == 201, r.text
    body = r.json()
    assert "duplex_id" in body
    dups = body["design"]["duplexes"]
    assert len(dups) == 1 and dups[0]["driver"] == "right" and dups[0]["name"] == "D1"


def test_create_rejects_mismatch_while_wc_gate_kept():
    _seed(seq_a="AAAA", seq_b="AAAA")   # RC(AAAA)=TTTT ≠ AAAA → not complementary
    r = _create(_end("ohA", 0, 3), _end("ohB", 3, 0))
    assert r.status_code == 422 and "complementary" in r.text


def test_create_rejects_out_of_domain():
    _seed()
    r = _create(_end("ohA", 0, 9), _end("ohB", 3, -6))   # equal length, out of range
    assert r.status_code == 422 and "outside" in r.text


def test_create_rejects_unequal_length():
    _seed()
    r = _create(_end("ohA", 0, 3), _end("ohB", 3, 1))   # 4 vs 3
    assert r.status_code == 422


def test_create_rejects_unknown_overhang():
    _seed()
    r = _create(_end("ghost", 0, 3), _end("ohB", 3, 0))
    assert r.status_code == 404


def test_create_unsequenced_passes_via_n_wildcard():
    _seed(seq_a=None, seq_b=None)        # all-N assembled → allow_n_wildcard passes
    r = _create(_end("ohA", 0, 3), _end("ohB", 3, 0))
    assert r.status_code == 201, r.text


# ── Multivalency + double-pairing guard ───────────────────────────────────────

def test_multivalent_disjoint_ok_but_overlap_409():
    _seed(seq_a="AAAA", seq_b="TTTT")   # homopolymer → any aligned window is WC
    # First duplex claims ohA bp0-1.
    r1 = _create(_end("ohA", 0, 1), _end("ohB", 3, 2))
    assert r1.status_code == 201, r1.text
    # Second on disjoint ohA bp2-3 → allowed (multivalency).
    r2 = _create(_end("ohA", 2, 3), _end("ohB", 1, 0))
    assert r2.status_code == 201, r2.text
    # Third overlapping ohA bp1 → 409.
    r3 = _create(_end("ohA", 1, 2), _end("ohB", 2, 1))
    assert r3.status_code == 409 and "already paired" in r3.text


def test_connect_different_lengths_preserves_both():
    """Length-preservation invariant: connecting a 6 bp overhang to a 4 bp one must
    NOT resize either — the duplex pairs the 4 bp window and the longer overhang
    keeps its 2 bp toehold. (The OLD binding path forced equal length + resized.)"""
    sa = Strand(id="st_a", strand_type=StrandType.STAPLE,
                domains=[Domain(helix_id="hA", start_bp=0, end_bp=5,
                                direction=Direction.FORWARD, overhang_id="ohA")])
    sb = Strand(id="st_b", strand_type=StrandType.STAPLE,
                domains=[Domain(helix_id="hB", start_bp=3, end_bp=0,
                                direction=Direction.REVERSE, overhang_id="ohB")])
    ohA = OverhangSpec(id="ohA", helix_id="hA", strand_id="st_a", sequence="AAAAAA")  # 6 bp
    ohB = OverhangSpec(id="ohB", helix_id="hB", strand_id="st_b", sequence="TTTT")    # 4 bp
    design_state.set_design(Design(strands=[sa, sb], overhangs=[ohA, ohB]))

    # Pair the 4 bp window at each overhang's root end; no resize requested.
    r = _create(_end("ohA", 0, 3), _end("ohB", 3, 0))
    assert r.status_code == 201, r.text
    design = r.json()["design"]

    # Both backing domains keep their original spans (lengths untouched).
    dom = {d["overhang_id"]: d for s in design["strands"] for d in s["domains"]}
    assert (dom["ohA"]["start_bp"], dom["ohA"]["end_bp"]) == (0, 5)   # still 6 bp
    assert (dom["ohB"]["start_bp"], dom["ohB"]["end_bp"]) == (3, 0)   # still 4 bp

    # The longer overhang shows a 2 bp toehold; the shorter is fully paired.
    pm_a = client.get("/api/design/overhangs/ohA/pairing-map").json()["pairing_map"]
    assert [pm_a[str(bp)] for bp in range(6)] == ['paired'] * 4 + ['unpaired'] * 2
    pm_b = client.get("/api/design/overhangs/ohB/pairing-map").json()["pairing_map"]
    assert list(pm_b.values()).count('paired') == 4


# ── Patch / delete / driver ───────────────────────────────────────────────────

def test_patch_driver_and_bound():
    _seed()
    did = _create(_end("ohA", 0, 3), _end("ohB", 3, 0)).json()["duplex_id"]
    r = client.patch(f"{API}/{did}", json={"driver": "right", "bound": True})
    assert r.status_code == 200
    dx = next(d for d in r.json()["design"]["duplexes"] if d["id"] == did)
    assert dx["driver"] == "right" and dx["bound"] is True


def test_patch_register_revalidates_wc():
    # 6 bp homopolymer overhangs so a slid window stays complementary.
    sa = Strand(id="st_a", strand_type=StrandType.STAPLE,
                domains=[Domain(helix_id="hA", start_bp=0, end_bp=5,
                                direction=Direction.FORWARD, overhang_id="ohA")])
    sb = Strand(id="st_b", strand_type=StrandType.STAPLE,
                domains=[Domain(helix_id="hB", start_bp=5, end_bp=0,
                                direction=Direction.REVERSE, overhang_id="ohB")])
    ohA = OverhangSpec(id="ohA", helix_id="hA", strand_id="st_a", sequence="AAAAAA")
    ohB = OverhangSpec(id="ohB", helix_id="hB", strand_id="st_b", sequence="TTTTTT")
    design_state.set_design(Design(strands=[sa, sb], overhangs=[ohA, ohB]))
    did = _create(_end("ohA", 0, 3), _end("ohB", 5, 2)).json()["duplex_id"]
    # Slide the register to another window → still A/T complementary → ok.
    r = client.patch(f"{API}/{did}", json={"left": _end("ohA", 1, 4), "right": _end("ohB", 4, 1)})
    assert r.status_code == 200, r.text


def test_delete_duplex():
    _seed()
    did = _create(_end("ohA", 0, 3), _end("ohB", 3, 0)).json()["duplex_id"]
    r = client.delete(f"{API}/{did}")
    assert r.status_code == 200
    assert r.json()["design"]["duplexes"] == []
    assert client.delete(f"{API}/{did}").status_code == 404


# ── Producer: connect two overhangs into a duplex ─────────────────────────────

def _seed_split_toehold():
    """Overhang A = 6 bp forward [0,5], split into a 4 bp root sub-domain "AAAC" +
    a 2 bp free-tip toehold "GG". Overhang B = 4 bp reverse "GTTT" (= RC of AAAC)."""
    sa = Strand(id="st_a", strand_type=StrandType.STAPLE,
                domains=[Domain(helix_id="hA", start_bp=0, end_bp=5,
                                direction=Direction.FORWARD, overhang_id="ohA")])
    sb = Strand(id="st_b", strand_type=StrandType.STAPLE,
                domains=[Domain(helix_id="hB", start_bp=3, end_bp=0,
                                direction=Direction.REVERSE, overhang_id="ohB")])
    ohA = OverhangSpec(id="ohA", helix_id="hA", strand_id="st_a", sequence="AAACGG",
                       sub_domains=[SubDomain(id="sdA1", start_bp_offset=0, length_bp=4, sequence_override="AAAC"),
                                    SubDomain(id="sdA2", start_bp_offset=4, length_bp=2, sequence_override="GG")])
    ohB = OverhangSpec(id="ohB", helix_id="hB", strand_id="st_b", sequence="GTTT",
                       sub_domains=[SubDomain(id="sdB", start_bp_offset=0, length_bp=4, sequence_override="GTTT")])
    design_state.set_design(Design(strands=[sa, sb], overhangs=[ohA, ohB]))


def test_connect_produces_duplex_min_length_with_toehold():
    _seed_split_toehold()
    # Bind the 4 bp root windows; A keeps its 2 bp free-tip toehold, no resize.
    r = client.post("/api/design/duplexes/connect", json={
        "overhang_a_id": "ohA", "overhang_a_attach": "root",
        "overhang_b_id": "ohB", "overhang_b_attach": "root",
    })
    assert r.status_code == 201, r.text
    design = r.json()["design"]
    assert len(design["duplexes"]) == 1
    # Longest overhang (A, 6 bp) drives.
    assert design["duplexes"][0]["driver"] == "left"
    # A shows 4 paired + 2 toehold; both backing domains untouched.
    pm = client.get("/api/design/overhangs/ohA/pairing-map").json()["pairing_map"]
    assert [pm[str(bp)] for bp in range(6)] == ['paired'] * 4 + ['unpaired'] * 2
    dom = {d["overhang_id"]: d for s in design["strands"] for d in s["domains"]}
    assert (dom["ohA"]["start_bp"], dom["ohA"]["end_bp"]) == (0, 5)


def test_connect_is_idempotent_per_pair():
    _seed_split_toehold()
    body = {"overhang_a_id": "ohA", "overhang_a_attach": "root",
            "overhang_b_id": "ohB", "overhang_b_attach": "root"}
    assert client.post("/api/design/duplexes/connect", json=body).status_code == 201
    assert client.post("/api/design/duplexes/connect", json=body).status_code == 409


def test_patch_driver_propagates_to_linked_binding():
    # A design with a binding (ohA/ohB); sync creates the matching duplex.
    design_state.set_design(_design_with_binding())
    did = client.post("/api/design/duplexes/sync-from-bindings").json()["design"]["duplexes"][0]["id"]
    # Flip the duplex driver → the linked binding's driver_oh_id must follow (#4),
    # so the existing relax (which reads driver_oh_id) honors the user's choice.
    r = client.patch(f"/api/design/duplexes/{did}", json={"driver": "right"})
    assert r.status_code == 200
    b = r.json()["design"]["overhang_bindings"][0]
    assert b["driver_oh_id"] == "ohB" and b["driven_oh_id"] == "ohA"


def test_sync_from_bindings_populates_and_idempotent():
    design_state.set_design(_design_with_binding())
    r = client.post("/api/design/duplexes/sync-from-bindings")
    assert r.status_code == 200
    assert len(r.json()["design"]["duplexes"]) == 1
    # Second call is a no-op (pair already has a duplex).
    r2 = client.post("/api/design/duplexes/sync-from-bindings")
    assert len(r2.json()["design"]["duplexes"]) == 1


# ── Bridge: legacy bindings → duplexes on load ────────────────────────────────

def _design_with_binding() -> Design:
    sa = Strand(id="st_a", strand_type=StrandType.STAPLE,
                domains=[Domain(helix_id="hA", start_bp=0, end_bp=3,
                                direction=Direction.FORWARD, overhang_id="ohA")])
    sb = Strand(id="st_b", strand_type=StrandType.STAPLE,
                domains=[Domain(helix_id="hB", start_bp=3, end_bp=0,
                                direction=Direction.REVERSE, overhang_id="ohB")])
    ohA = OverhangSpec(id="ohA", helix_id="hA", strand_id="st_a", sequence="AAAC",
                       sub_domains=[SubDomain(id="sdA", start_bp_offset=0, length_bp=4)])
    ohB = OverhangSpec(id="ohB", helix_id="hB", strand_id="st_b", sequence="GTTT",
                       sub_domains=[SubDomain(id="sdB", start_bp_offset=0, length_bp=4)])
    binding = OverhangBinding(name="B1", sub_domain_a_id="sdA", sub_domain_b_id="sdB",
                              overhang_a_id="ohA", overhang_b_id="ohB")
    return Design(strands=[sa, sb], overhangs=[ohA, ohB], overhang_bindings=[binding])


def test_derive_duplexes_if_empty_populates_and_is_idempotent():
    from backend.api.crud import _derive_duplexes_if_empty
    d = _design_with_binding()
    assert d.duplexes == []
    d1 = _derive_duplexes_if_empty(d)
    assert len(d1.duplexes) == 1
    dx = d1.duplexes[0]
    assert dx.left.overhang_id == "ohA" and dx.right.overhang_id == "ohB"
    # Idempotent: a design that already has duplexes is untouched.
    assert _derive_duplexes_if_empty(d1) is d1 or len(_derive_duplexes_if_empty(d1).duplexes) == 1
    # No bindings → nothing derived.
    assert _derive_duplexes_if_empty(Design(strands=[], overhangs=[])).duplexes == []


def test_import_endpoint_derives_duplexes():
    d = _design_with_binding()
    r = client.post("/api/design/import", json={"content": d.model_dump_json()})
    assert r.status_code == 200, r.text
    assert len(r.json()["design"]["duplexes"]) == 1


# ── Pairing readouts ──────────────────────────────────────────────────────────

def test_pairing_endpoint():
    _seed()
    did = _create(_end("ohA", 0, 3), _end("ohB", 3, 0)).json()["duplex_id"]
    r = client.get(f"{API}/{did}/pairing")
    assert r.status_code == 200
    body = r.json()
    assert body["length"] == 4 and body["n_complementary"] == 4


def test_overhang_pairing_map_endpoint_reports_toehold():
    # 6 bp overhang, 4 bp duplex → 2 bp toehold.
    sa = Strand(id="st_a", strand_type=StrandType.STAPLE,
                domains=[Domain(helix_id="hA", start_bp=0, end_bp=5,
                                direction=Direction.FORWARD, overhang_id="ohA")])
    sb = Strand(id="st_b", strand_type=StrandType.STAPLE,
                domains=[Domain(helix_id="hB", start_bp=5, end_bp=0,
                                direction=Direction.REVERSE, overhang_id="ohB")])
    ohA = OverhangSpec(id="ohA", helix_id="hA", strand_id="st_a", sequence="AAACGG")
    ohB = OverhangSpec(id="ohB", helix_id="hB", strand_id="st_b", sequence="GTTTCC")
    design_state.set_design(Design(strands=[sa, sb], overhangs=[ohA, ohB]))
    _create(_end("ohA", 0, 3), _end("ohB", 5, 2))
    r = client.get("/api/design/overhangs/ohA/pairing-map")
    assert r.status_code == 200
    pm = r.json()["pairing_map"]
    assert [pm[str(bp)] for bp in range(6)] == ['paired'] * 4 + ['unpaired'] * 2
