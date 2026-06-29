"""ConnectionVersion CRUD + applied-mutex + persistence."""
from __future__ import annotations

from fastapi.testclient import TestClient

from backend.api import state as design_state
from backend.api.main import app
from backend.api.routes import _demo_design
from backend.core.constants import BDNA_RISE_PER_BP
from backend.core.models import (
    Design, OverhangSpec, Helix, Strand, Domain, Direction, StrandType, Vec3,
)
from tests.automation_harness import assert_end_to_root_binder

client = TestClient(app)

A, B, C = "ovhg_a_5p", "ovhg_b_3p", "ovhg_c_5p"


def _seed_real() -> Design:
    """Two real extruded overhangs (8 bp each on their own helix/strand) so the
    apply step can resize / set sequences / build linker or binding topology."""
    base = _demo_design()

    def _oh(hid, sid, oid, x):
        helix = Helix(id=hid, axis_start=Vec3(x=x, y=0.0, z=0.0),
                      axis_end=Vec3(x=x, y=0.0, z=8 * BDNA_RISE_PER_BP),
                      phase_offset=0.0, length_bp=8, grid_pos=(0, int(x)))
        strand = Strand(id=sid, strand_type=StrandType.STAPLE, domains=[
            Domain(helix_id=hid, start_bp=0, end_bp=7, direction=Direction.FORWARD, overhang_id=oid)])
        spec = OverhangSpec(id=oid, helix_id=hid, strand_id=sid, label=oid.upper())
        return helix, strand, spec

    ha, sa, oa = _oh("oh_helix_a", "oh_strand_a", "oh_a", 2)
    hb, sb, ob = _oh("oh_helix_b", "oh_strand_b", "oh_b", 5)
    hc, sc, oc = _oh("oh_helix_c", "oh_strand_c", "oh_c", 8)
    return base.model_copy(update={
        "helices": [*base.helices, ha, hb, hc],
        "strands": [*base.strands, sa, sb, sc],
        "overhangs": [oa, ob, oc],
    })


def _mk_version(**kw):
    body = {"overhang_a_id": "oh_a", "overhang_b_id": "oh_b",
            "connection_type": "end-to-end-dsdna-linker",
            "overhang_a_seq": "ACGTACGT", "overhang_b_seq": "ACGTACGT", "bridge_length": 5}
    body.update(kw)
    r = client.post("/api/design/connection-versions", json=body)
    assert r.status_code == 201, r.text
    return design_state.get_or_404().connection_versions[-1].id


def test_apply_creates_linker_sets_sequences_and_marks_applied():
    design_state.close_session(); design_state.set_design(_seed_real())
    vid = _mk_version()
    r = client.post(f"/api/design/connection-versions/{vid}/apply")
    assert r.status_code == 200, r.text
    d = design_state.get_or_404()
    assert len(d.overhang_connections) == 1                       # linker materialized
    assert next(o for o in d.overhangs if o.id == "oh_a").sequence == "ACGTACGT"
    assert next(v for v in d.connection_versions if v.id == vid).applied is True


def test_apply_resizes_overhang_to_sequence_length():
    design_state.close_session(); design_state.set_design(_seed_real())
    vid = _mk_version(overhang_a_seq="ACGTACGTAC", overhang_b_seq="ACGTACGTAC")  # 10 nt > 8
    r = client.post(f"/api/design/connection-versions/{vid}/apply")
    assert r.status_code == 200, r.text
    d = design_state.get_or_404()
    oh_a = next(o for o in d.overhangs if o.id == "oh_a")
    assert oh_a.sequence == "ACGTACGTAC"
    assert sum(sd.length_bp for sd in oh_a.sub_domains) == 10      # overhang resized


def test_apply_direct_creates_binding_not_linker():
    design_state.close_session(); design_state.set_design(_seed_real())
    vid = _mk_version(connection_type="root-to-root", overhang_a_seq="ACGTACGT",
                      overhang_b_seq="ACGTACGT", bridge_length=0)
    r = client.post(f"/api/design/connection-versions/{vid}/apply")
    assert r.status_code == 200, r.text
    d = design_state.get_or_404()
    assert len(d.overhang_bindings) == 1
    assert len(d.overhang_connections) == 0


def test_apply_replaces_prior_version_topology():
    design_state.close_session(); design_state.set_design(_seed_real())
    v1 = _mk_version()
    client.post(f"/api/design/connection-versions/{v1}/apply")
    v2 = _mk_version(connection_type="root-to-root", bridge_length=0)
    client.post(f"/api/design/connection-versions/{v2}/apply")
    d = design_state.get_or_404()
    # v2 (direct) applied → its binding present, v1's linker torn down, no coexisting topology.
    assert len(d.overhang_connections) == 0
    assert len(d.overhang_bindings) == 1
    by_id = {v.id: v for v in d.connection_versions}
    assert by_id[v2].applied is True and by_id[v1].applied is False


def _seed_end_to_root() -> Design:
    """A as a lone overhang; B as a bundle-anchored staple (a root domain + the
    overhang tip) so the end-to-root splice has a root to attach the binder to."""
    base = _demo_design()
    ha = Helix(id="e2r_ha", axis_start=Vec3(x=2.0, y=0.0, z=0.0),
               axis_end=Vec3(x=2.0, y=0.0, z=8 * BDNA_RISE_PER_BP),
               phase_offset=0.0, length_bp=8, grid_pos=(0, 2))
    hbx = Helix(id="e2r_hb", axis_start=Vec3(x=5.0, y=0.0, z=0.0),
                axis_end=Vec3(x=5.0, y=0.0, z=8 * BDNA_RISE_PER_BP),
                phase_offset=0.0, length_bp=8, grid_pos=(0, 5))
    sa = Strand(id="e2r_sa", strand_type=StrandType.STAPLE, domains=[
        Domain(helix_id="e2r_ha", start_bp=0, end_bp=7, direction=Direction.FORWARD, overhang_id="oh_a")])
    sb = Strand(id="e2r_sb", strand_type=StrandType.STAPLE, domains=[
        Domain(helix_id="e2r_hb", start_bp=0, end_bp=3, direction=Direction.FORWARD),                       # root
        Domain(helix_id="e2r_hb", start_bp=4, end_bp=7, direction=Direction.FORWARD, overhang_id="oh_b")])  # tip
    return base.model_copy(update={
        "helices": [*base.helices, ha, hbx],
        "strands": [*base.strands, sa, sb],
        "overhangs": [OverhangSpec(id="oh_a", helix_id="e2r_ha", strand_id="e2r_sa", label="OHA"),
                      OverhangSpec(id="oh_b", helix_id="e2r_hb", strand_id="e2r_sb", label="OHB")],
    })


def test_apply_end_to_root_splices_rc_binder_into_b():
    """Applying an end-to-root version regenerates overhang B as A's reverse
    complement: a binder domain (on A's helix, antiparallel, RC of A) is spliced
    into B's root staple and B's spec is consumed — no binding/linker record is
    created. The reusable oracle proves the geometry + splice + RC + round-trip."""
    design_state.close_session(); design_state.set_design(_seed_end_to_root())
    r = client.post("/api/design/connection-versions", json={
        "overhang_a_id": "oh_a", "overhang_b_id": "oh_b",
        "connection_type": "end-to-root", "overhang_a_seq": "AAACCCGG"})
    assert r.status_code == 201, r.text
    vid = design_state.get_or_404().connection_versions[-1].id
    r = client.post(f"/api/design/connection-versions/{vid}/apply")
    assert r.status_code == 200, r.text
    d = design_state.get_or_404()
    assert_end_to_root_binder(d, overhang_a_id="oh_a", overhang_b_id="oh_b")
    assert len(d.overhang_bindings) == 0      # end-to-root is a pure topological splice
    assert len(d.overhang_connections) == 0
    assert next(v for v in d.connection_versions if v.id == vid).applied is True


def test_apply_404_for_unknown_version():
    design_state.close_session(); design_state.set_design(_seed_real())
    assert client.post("/api/design/connection-versions/nope/apply").status_code == 404


def test_apply_unapplies_connection_sharing_an_overhang():
    design_state.close_session(); design_state.set_design(_seed_real())
    # Applied a↔b linker.
    v_ab = _mk_version(overhang_a_id="oh_a", overhang_b_id="oh_b")
    client.post(f"/api/design/connection-versions/{v_ab}/apply")
    assert len(design_state.get_or_404().overhang_connections) == 1
    # Apply b↔c — shares oh_b, so a↔b must be torn down + unapplied.
    v_bc = _mk_version(overhang_a_id="oh_b", overhang_b_id="oh_c")
    r = client.post(f"/api/design/connection-versions/{v_bc}/apply")
    assert r.status_code == 200, r.text
    d = design_state.get_or_404()
    assert len(d.overhang_connections) == 1                       # only b↔c remains
    conn = d.overhang_connections[0]
    assert {conn.overhang_a_id, conn.overhang_b_id} == {"oh_b", "oh_c"}
    by_id = {v.id: v for v in d.connection_versions}
    assert by_id[v_bc].applied is True
    assert by_id[v_ab].applied is False                           # old one unapplied


def _seed() -> Design:
    base = _demo_design()
    overhangs = [
        OverhangSpec(id=A, helix_id="demo_helix", strand_id="staple_0", label="OHA"),
        OverhangSpec(id=B, helix_id="demo_helix", strand_id="staple_0", label="OHB"),
        OverhangSpec(id=C, helix_id="demo_helix", strand_id="staple_0", label="OHC"),
    ]
    return base.model_copy(update={"overhangs": overhangs})


def _versions():
    return design_state.get_or_404().connection_versions


def _create(**kw):
    body = {"overhang_a_id": A, "overhang_b_id": B, "connection_type": "root-to-root-ssdna-linker"}
    body.update(kw)
    r = client.post("/api/design/connection-versions", json=body)
    assert r.status_code == 201, r.text
    return r


def test_create_assigns_v1_v2_per_pair():
    design_state.close_session()
    design_state.set_design(_seed())
    _create()
    _create()
    names = [v.name for v in _versions()]
    assert names == ["V1", "V2"]
    assert all(v.overhang_a_id == A and v.overhang_b_id == B for v in _versions())


def test_create_404_for_unknown_overhang():
    design_state.close_session()
    design_state.set_design(_seed())
    r = client.post("/api/design/connection-versions", json={
        "overhang_a_id": A, "overhang_b_id": "nope", "connection_type": "root-to-root",
    })
    assert r.status_code == 404


def test_applied_is_mutually_exclusive_per_pair():
    design_state.close_session()
    design_state.set_design(_seed())
    _create(applied=True)            # V1 applied
    v1 = _versions()[0].id
    _create()                        # V2 unapplied
    v2 = _versions()[1].id
    # Apply V2 → V1 must flip to unapplied.
    r = client.patch(f"/api/design/connection-versions/{v2}", json={"applied": True})
    assert r.status_code == 200, r.text
    by_id = {v.id: v for v in _versions()}
    assert by_id[v2].applied is True
    assert by_id[v1].applied is False


def test_applied_mutex_is_per_pair_not_global():
    design_state.close_session()
    design_state.set_design(_seed())
    _create(applied=True)                                    # pair A/B applied
    r = client.post("/api/design/connection-versions", json={
        "overhang_a_id": A, "overhang_b_id": C,
        "connection_type": "root-to-root-ssdna-linker", "applied": True,
    })
    assert r.status_code == 201, r.text
    # Both stay applied — different pairs.
    assert all(v.applied for v in _versions())


def test_patch_sequences_and_bridge():
    design_state.close_session()
    design_state.set_design(_seed())
    _create()
    vid = _versions()[0].id
    r = client.patch(f"/api/design/connection-versions/{vid}", json={
        "overhang_a_seq": "acgt", "overhang_b_seq": "ACGT", "bridge_length": 5, "bridge_seq": "ggGG",
    })
    assert r.status_code == 200, r.text
    v = _versions()[0]
    assert v.overhang_a_seq == "ACGT"           # uppercased
    assert v.bridge_length == 5
    assert v.bridge_seq == "GGGG"


def test_delete_version():
    design_state.close_session()
    design_state.set_design(_seed())
    _create()
    vid = _versions()[0].id
    r = client.delete(f"/api/design/connection-versions/{vid}")
    assert r.status_code == 200, r.text
    assert _versions() == []
    assert client.delete(f"/api/design/connection-versions/{vid}").status_code == 404


def test_versions_persist_through_nadoc_round_trip():
    design_state.close_session()
    design_state.set_design(_seed())
    _create(overhang_a_seq="ACGT", applied=True)
    _create(bridge_length=7)
    before = design_state.get_or_404()
    restored = Design.from_json(before.to_json())
    assert [v.name for v in restored.connection_versions] == ["V1", "V2"]
    assert restored.connection_versions[0].overhang_a_seq == "ACGT"
    assert restored.connection_versions[0].applied is True
    assert restored.connection_versions[1].bridge_length == 7
