"""
Tests for ``backend.core.assembly_flatten.flatten_assembly``.

The regression gate here is **zero dangling domain→helix references** after
flattening an assembly that carries a cross-part linker. Before the 2026-07 fix
the linker complement domains (addressed as ``"<inst_id>::<helix_id>"``) were
blindly ``asm::``-prefixed to ``"asm::<inst_id>::<helix_id>"`` — matching neither
the flattened part helix (``"inst-<inst_id>::<helix_id>"``) nor any real helix,
so the linker bridge silently connected to nothing.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.api import assembly_state
from backend.api.main import app
from backend.core.assembly_flatten import flatten_assembly
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


def _design_with_real_oh(oh_id: str, sequence: str | None) -> Design:
    length_bp = 8
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


def _seed_real_two_part_assembly() -> Assembly:
    d_a = _design_with_real_oh("oh-A_5p", "ACGTACGT")
    d_b = _design_with_real_oh("oh-B_3p", "GGGGCCCC")
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


def _conn_payload(
    *, linker_type="ds", attach_a="free_end", attach_b="root", length_value=8
):
    return {
        "instance_a_id": "inst-A",
        "overhang_a_id": "oh-A_5p",
        "overhang_a_attach": attach_a,
        "instance_b_id": "inst-B",
        "overhang_b_id": "oh-B_3p",
        "overhang_b_attach": attach_b,
        "linker_type": linker_type,
        "length_value": length_value,
        "length_unit": "bp",
    }


def _dangling_refs(design) -> list[tuple[str, str]]:
    """Every (strand_id, helix_id) domain reference with no matching helix."""
    helix_ids = {h.id for h in design.helices}
    return [
        (s.id, d.helix_id)
        for s in design.strands
        for d in s.domains
        if d.helix_id not in helix_ids
    ]


def test_flatten_empty_assembly_has_no_dangling_refs():
    _seed_real_two_part_assembly()
    flat = flatten_assembly(assembly_state.get_or_404())
    assert _dangling_refs(flat) == []


@pytest.mark.parametrize(
    "payload",
    [
        _conn_payload(linker_type="ds", attach_a="free_end", attach_b="root"),
        _conn_payload(linker_type="ss", attach_a="free_end", attach_b="free_end"),
        _conn_payload(
            linker_type="ss", attach_a="free_end", attach_b="free_end", length_value=0
        ),  # indirect (zero-length ss)
    ],
)
def test_flatten_linkered_assembly_has_no_dangling_refs(payload):
    _seed_real_two_part_assembly()
    r = client.post("/api/assembly/overhang-connections", json=payload)
    assert r.status_code == 200, r.text

    asm = assembly_state.get_or_404()
    # Precondition: the linker really did materialise complement strands.
    assert asm.assembly_strands, "linker produced no assembly strands"

    flat = flatten_assembly(asm)
    dangling = _dangling_refs(flat)
    assert dangling == [], f"linker complement domains dangle: {dangling}"

    # And the complement domain lands on the REAL flattened part helix.
    part_helix_ids = {h.id for h in flat.helices if h.id.startswith("inst-")}
    lnk_strands = [s for s in flat.strands if s.id.startswith("asm::__lnk__")]
    complement_refs = {
        d.helix_id
        for s in lnk_strands
        for d in s.domains
        if not d.helix_id.startswith("asm::__lnk__")  # exclude the bridge domain
    }
    assert complement_refs, "no complement domains found on the linker strands"
    assert complement_refs <= part_helix_ids, (
        f"complement domains not on a part helix: {complement_refs - part_helix_ids}"
    )


# ── Direct WC binding materialization (Phase D) ─────────────────────────────────


def _binding(assembly: Assembly) -> AssemblyOverhangBinding:
    sda = assembly.instances[0].source.design.overhangs[0].sub_domains[0].id
    sdb = assembly.instances[1].source.design.overhangs[0].sub_domains[0].id
    return AssemblyOverhangBinding(
        name="AB1",
        instance_a_id="inst-A",
        sub_domain_a_id=sda,
        overhang_a_id="oh-A_5p",
        instance_b_id="inst-B",
        sub_domain_b_id=sdb,
        overhang_b_id="oh-B_3p",
    )


def test_flatten_materializes_direct_wc_binding_into_paired_topology():
    """A direct cross-part WC AssemblyOverhangBinding becomes a real duplex in the
    flattened Design: the driven overhang is relocated onto the driver's helix,
    antiparallel, over the same bp range."""
    a = _seed_real_two_part_assembly()
    a = a.model_copy(update={"overhang_bindings": [_binding(a)]})
    assembly_state.set_assembly(a)

    flat = flatten_assembly(a)
    assert _dangling_refs(flat) == []

    # Find a helix hosting two domains covering the SAME bp range in OPPOSITE
    # directions — the materialized duplex.
    from collections import defaultdict

    by_helix = defaultdict(list)
    for s in flat.strands:
        for d in s.domains:
            by_helix[d.helix_id].append(d)

    def _covered(d):
        lo, hi = sorted((d.start_bp, d.end_bp))
        return frozenset(range(lo, hi + 1))

    paired = False
    for doms in by_helix.values():
        for i in range(len(doms)):
            for j in range(i + 1, len(doms)):
                di, dj = doms[i], doms[j]
                if _covered(di) == _covered(dj) and di.direction != dj.direction:
                    paired = True
    assert paired, "no antiparallel co-located domain pair (duplex) in flattened design"

    # The two overhangs must now sit on ONE helix (the driven relocated onto the
    # driver), not two.
    oh_helices = {d.helix_id for s in flat.strands for d in s.domains if d.overhang_id}
    assert len(oh_helices) == 1, f"overhangs not co-located: {oh_helices}"


def test_import_derives_duplexes_from_legacy_bindings():
    """Loading a .nass that carries legacy AssemblyOverhangBindings (and no
    duplexes) populates Assembly.duplexes on import."""
    a = _seed_real_two_part_assembly()
    a = a.model_copy(update={"overhang_bindings": [_binding(a)]})
    assembly_state.close_session()

    r = client.post("/api/assembly/import", json={"content": a.to_json()})
    assert r.status_code == 200, r.text
    duplexes = r.json()["assembly"].get("duplexes", [])
    assert len(duplexes) == 1
    assert duplexes[0]["left"]["instance_id"] == "inst-A"
