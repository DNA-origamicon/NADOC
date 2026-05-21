"""Cross-part ds linker relax — rigid coaxial placement of a free part.

Covers the new `GET/POST /assembly/overhang-connections/{id}/relax[-status]`
routes + `backend/core/assembly_linker_relax.py`. The acceptance assertions
(post-relax chord == native length AND the two overhang axial directions are
antiparallel) catch a wrong axial-direction sign, which is the one geometric
risk flagged in the plan.
"""

from __future__ import annotations

import numpy as np
import pytest
from fastapi.testclient import TestClient

from backend.api import assembly_state
from backend.api.main import app
from backend.core.constants import BDNA_RISE_PER_BP
from backend.core.lattice import _find_overhang_domain
from backend.core.assembly_linker_relax import _world_anchor_axial
from backend.core.models import (
    Assembly,
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


# ── Fixtures (mirror tests/test_assembly_overhang_bindings.py) ────────────────
def _design_with_real_oh(oh_id: str, sequence: str | None) -> Design:
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
        domains=[Domain(helix_id=helix_id, start_bp=0, end_bp=length_bp - 1,
                        direction=direction, overhang_id=oh_id)],
        strand_type=StrandType.STAPLE,
    )
    ovhg = OverhangSpec(id=oh_id, helix_id=helix_id, strand_id=strand_id,
                        sequence=sequence, label=oh_id)
    return Design(helices=[helix], strands=[strand], overhangs=[ovhg])


def _seed(a_fixed: bool = False, b_fixed: bool = False) -> Assembly:
    """Two parts; B offset +10 nm on X so the overhangs start non-coaxial."""
    d_a = _design_with_real_oh("oh-A_5p", "ACGTACGT")
    d_b = _design_with_real_oh("oh-B_3p", "GGGGCCCC")
    t_b = Mat4x4(values=[1, 0, 0, 10, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1])
    a = Assembly(instances=[
        PartInstance(id="inst-A", name="PartA", source=PartSourceInline(design=d_a), fixed=a_fixed),
        PartInstance(id="inst-B", name="PartB", source=PartSourceInline(design=d_b),
                     transform=t_b, fixed=b_fixed),
    ])
    assembly_state.set_assembly(a)
    return a


def _conn(linker_type="ds", attach_a="free_end", attach_b="root", length_value=8):
    return {
        "instance_a_id": "inst-A", "overhang_a_id": "oh-A_5p", "overhang_a_attach": attach_a,
        "instance_b_id": "inst-B", "overhang_b_id": "oh-B_3p", "overhang_b_attach": attach_b,
        "linker_type": linker_type, "length_value": length_value, "length_unit": "bp",
    }


def _create_ds(**kw) -> str:
    r = client.post("/api/assembly/overhang-connections", json=_conn(**kw))
    assert r.status_code == 200, r.text
    return r.json()["assembly"]["overhang_connections"][0]["id"]


def _live_anchor(inst_id: str, oh_id: str, attach: str):
    asm = assembly_state.get_or_404()
    inst = next(i for i in asm.instances if i.id == inst_id)
    design = inst.source.design
    return _world_anchor_axial(design, inst, oh_id, attach, _find_overhang_domain(design, oh_id))


# ── Tests ─────────────────────────────────────────────────────────────────────
def test_relax_status_neither_fixed_moves_b():
    _seed()
    cid = _create_ds()
    st = client.get(f"/api/assembly/overhang-connections/{cid}/relax-status").json()
    assert st["available"] is True
    assert st["movable_instance_id"] == "inst-B"
    assert st["fixed_instance_id"] == "inst-A"


def test_relax_is_translation_only():
    """The relax moves the free part by PURE translation (no rotation)."""
    _seed()
    cid = _create_ds(length_value=8)
    T_before = np.array(assembly_state.get_or_404().instances[1].transform.values).reshape(4, 4)

    r = client.post(f"/api/assembly/overhang-connections/{cid}/relax")
    assert r.status_code == 200, r.text

    T_after = np.array(assembly_state.get_or_404().instances[1].transform.values).reshape(4, 4)
    assert T_after[:3, :3] == pytest.approx(T_before[:3, :3], abs=1e-9)   # rotation block unchanged
    assert not np.allclose(T_after[:3, 3], T_before[:3, 3])               # part actually moved


def test_relax_collapses_both_connector_arcs():
    """Two-translation relax drives BOTH connector arcs to ~0, measured by the
    checker on the ACTUAL emitted backbone-bead coordinates (the same quantity
    the relax minimizes — mirrors the per-design arc-residual check)."""
    from backend.api.assembly import assembly_connector_arc_lengths

    _seed()                       # parts offset → a real arc gap exists pre-relax
    cid = _create_ds(length_value=8)

    pre = assembly_connector_arc_lengths(assembly_state.get_or_404())[cid]
    assert pre["a"] > 0.1 and pre["b"] > 0.1, f"expected a pre-relax gap, got {pre}"

    r = client.post(f"/api/assembly/overhang-connections/{cid}/relax")
    assert r.status_code == 200, r.text

    post = assembly_connector_arc_lengths(assembly_state.get_or_404())[cid]
    assert post["a"] == pytest.approx(0.0, abs=1e-6), f"fixed-side arc not closed: {post}"
    assert post["b"] == pytest.approx(0.0, abs=1e-6), f"moved-side arc not closed: {post}"


def test_relax_keeps_binding_domain_fixed_relative_to_overhang():
    """The moving overhang's binding domain (its complement anchor) must move by
    exactly the part's rigid delta — i.e. it stays fixed relative to its
    overhang rather than being repositioned independently."""
    _seed()
    cid = _create_ds(length_value=8)
    T_before = np.array(assembly_state.get_or_404().instances[1].transform.values).reshape(4, 4)
    p_before, _ = _live_anchor("inst-B", "oh-B_3p", "root")

    r = client.post(f"/api/assembly/overhang-connections/{cid}/relax")
    assert r.status_code == 200, r.text

    T_after = np.array(assembly_state.get_or_404().instances[1].transform.values).reshape(4, 4)
    p_after, _ = _live_anchor("inst-B", "oh-B_3p", "root")
    # complement_world = T @ complement_local, so a rigidly-attached binding
    # domain satisfies p_after == (T_after @ T_before^-1) @ p_before.
    D = T_after @ np.linalg.inv(T_before)
    expected = (D @ np.append(p_before, 1.0))[:3]
    assert p_after == pytest.approx(expected, abs=1e-6)


def test_relax_moves_unfixed_side_when_one_part_fixed():
    _seed(b_fixed=True)
    cid = _create_ds()
    st = client.get(f"/api/assembly/overhang-connections/{cid}/relax-status").json()
    assert st["available"] is True
    assert st["movable_instance_id"] == "inst-A"
    assert st["fixed_instance_id"] == "inst-B"

    # Fixed part B must not move; A moves.
    before_b = list(assembly_state.get_or_404().instances[1].transform.values)
    r = client.post(f"/api/assembly/overhang-connections/{cid}/relax")
    assert r.status_code == 200, r.text
    after_b = list(assembly_state.get_or_404().instances[1].transform.values)
    assert after_b == pytest.approx(before_b)


def test_relax_unavailable_when_both_fixed():
    _seed(a_fixed=True, b_fixed=True)
    cid = _create_ds()
    st = client.get(f"/api/assembly/overhang-connections/{cid}/relax-status").json()
    assert st["available"] is False
    assert "fixed" in st["reason"].lower()
    r = client.post(f"/api/assembly/overhang-connections/{cid}/relax")
    assert r.status_code == 400


def test_relax_unavailable_for_ss_linker():
    _seed()
    # ss end-to-end (opposite 5p/3p polarity) is an allowed ss combo.
    r = client.post("/api/assembly/overhang-connections",
                    json=_conn(linker_type="ss", attach_a="free_end", attach_b="free_end"))
    assert r.status_code == 200, r.text
    cid = r.json()["assembly"]["overhang_connections"][0]["id"]
    st = client.get(f"/api/assembly/overhang-connections/{cid}/relax-status").json()
    assert st["available"] is False
    assert "ss" in st["reason"].lower()


def test_relax_logs_one_entry_and_undo_restores_pose():
    _seed()
    cid = _create_ds()
    before = list(assembly_state.get_or_404().instances[1].transform.values)

    r = client.post(f"/api/assembly/overhang-connections/{cid}/relax")
    assert r.status_code == 200, r.text
    asm = assembly_state.get_or_404()
    moved = list(asm.instances[1].transform.values)
    assert moved != pytest.approx(before)             # B actually moved
    assert sum(e.op_kind == "assembly-overhang-connection-relax" for e in asm.feature_log) == 1

    ru = client.post("/api/assembly/undo")
    assert ru.status_code == 200, ru.text
    restored = list(assembly_state.get_or_404().instances[1].transform.values)
    assert restored == pytest.approx(before)


def test_linker_geometry_emits_bridge_nucleotides():
    """Regression: GET /assembly/linker-geometry must 200 AND emit bridge nucs on
    the __lnk__ helix. Two bugs hid here: (1) the synthetic Design used a lowercase
    'honeycomb' lattice_type → Pydantic 500; (2) the per-design pipeline skips
    __lnk__ helices and emits the bridge via _emit_bridge_nucs (which reads
    design.overhang_connections — empty on the assembly synthetic design), so the
    bridge rendered as zero nucs. The frontend swallows the error → invisible bridge."""
    for linker_type, attach in (("ds", ("root", "free_end")), ("ss", ("free_end", "free_end"))):
        _seed()
        r = client.post("/api/assembly/overhang-connections",
                        json=_conn(linker_type=linker_type, attach_a=attach[0], attach_b=attach[1]))
        assert r.status_code == 200, r.text
        g = client.get("/api/assembly/linker-geometry")
        assert g.status_code == 200, g.text          # was 500 on lowercase lattice_type
        nucs = g.json().get("nucleotides") or []
        bridge = [n for n in nucs if (n.get("helix_id") or "").startswith("__lnk__")]
        assert len(bridge) > 0, f"[{linker_type}] no bridge nucleotides emitted on __lnk__ helix"


def test_linker_complement_phase_matches_tilted_overhang():
    """Regression: the overhang's binding domain (the linker complement) must
    land at the correct helical phase relative to its overhang even when the
    part is tilted off world-Z. Its world position must equal T @ (part-local
    complement position) — not the wrong roll the world-aliased helix produces
    on its own (``_frame_from_helix_axis`` is not rotation-equivariant;
    ``get_linker_geometry`` corrects it with a phase_offset δ)."""
    import math as _math
    from backend.core.geometry import nucleotide_positions_arrays
    from backend.core.assembly_linker import namespaced_helix_id
    from backend.core.lattice import _opposite_direction

    th = _math.radians(37.0)
    c, s = _math.cos(th), _math.sin(th)
    t_b = Mat4x4(values=[1, 0, 0, 10, 0, c, -s, 0, 0, s, c, 0, 0, 0, 0, 1])   # tilt about X + offset
    d_a = _design_with_real_oh("oh-A_5p", "ACGTACGT")
    d_b = _design_with_real_oh("oh-B_3p", "GGGGCCCC")
    assembly_state.set_assembly(Assembly(instances=[
        PartInstance(id="inst-A", name="A", source=PartSourceInline(design=d_a)),
        PartInstance(id="inst-B", name="B", source=PartSourceInline(design=d_b), transform=t_b),
    ]))
    cid = _create_ds()

    oh_dom = _find_overhang_domain(d_b, "oh-B_3p")
    comp_dir_int = 0 if _opposite_direction(oh_dom.direction) == Direction.FORWARD else 1
    arrs = nucleotide_positions_arrays(d_b.find_helix(oh_dom.helix_id))
    T = np.array(t_b.values).reshape(4, 4)
    expected = {
        int(arrs["bp_indices"][i]): (T @ np.append(arrs["positions"][i], 1.0))[:3]
        for i in range(len(arrs["bp_indices"])) if int(arrs["directions"][i]) == comp_dir_int
    }

    g = client.get("/api/assembly/linker-geometry").json()
    comp_helix  = namespaced_helix_id("inst-B", oh_dom.helix_id)
    comp_strand = f"__lnk__{cid}__b"
    actual = {
        int(n["bp_index"]): np.array(n["backbone_position"])
        for n in g["nucleotides"]
        if n.get("strand_id") == comp_strand and n.get("helix_id") == comp_helix
    }

    shared = set(expected) & set(actual)
    assert shared, "no complement nucs found on the namespaced helix"
    for bp in sorted(shared):
        assert actual[bp] == pytest.approx(expected[bp], abs=1e-6), f"complement bp {bp} at wrong phase"


def test_relax_missing_connection_404():
    _seed()
    assert client.get("/api/assembly/overhang-connections/nope/relax-status").status_code == 404
    assert client.post("/api/assembly/overhang-connections/nope/relax").status_code == 404
