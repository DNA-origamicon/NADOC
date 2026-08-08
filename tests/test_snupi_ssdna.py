"""SS-0 oracle — the ssDNA topology classifier (``backend.physics.snupi_ssdna``).

Phase SS-0 of ``memory/project_snupi_ssdna.md``: teach the mesh layer to SEE the
single-stranded nucleotides it has always ignored, and change nothing else.

Three things are pinned here:

1. **The classification is right.** A ssDNA run with two meshed neighbours is a *bridge*
   (load-bearing, SNUPI models it); with exactly one it is a *tail* (an overhang or a
   dangling end — SNUPI structurally cannot represent it); with none it is *free*.
2. **The anchor rule is right.** Per the user: *the tail anchor is defined by which end has
   a crossover into the embedded staple*. So the anchor is found by walking the strand path
   to the meshed neighbour, and it is NOT fixed to 3' or 5' — a tail at the strand's 5'
   terminus anchors on its 3' side. Both orientations are pinned.
3. **Nothing else moved.** ``meshed_bp`` reproduces ``build_fem_mesh``'s node set exactly,
   and every node the mesh builds is still ``kind="bp"``. SS-0 is representation only.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.core.models import (
    Design,
    Direction,
    Domain,
    Helix,
    Strand,
    StrandType,
    Vec3,
)
from backend.physics.fem_solver import FEM_RISE_PER_BP, build_fem_mesh
from backend.physics.snupi_ssdna import (
    SSAnchor,
    classify_ssdna_runs,
    meshed_bp,
    ssdna_inventory,
)

EXAMPLES = Path(__file__).resolve().parents[1] / "Examples"


def _helix(hid: str, n_bp: int = 40, x: float = 0.0) -> Helix:
    return Helix(
        id=hid,
        axis_start=Vec3(x=x, y=0.0, z=0.0),
        axis_end=Vec3(x=x, y=0.0, z=n_bp * FEM_RISE_PER_BP),
        length_bp=n_bp,
        bp_start=0,
    )


def _dom(
    hid: str,
    lo: int,
    hi: int,
    direction: Direction = Direction.FORWARD,
    overhang_id: str | None = None,
) -> Domain:
    """Domain covering bp ``lo..hi`` on ``hid``.

    ``start_bp``/``end_bp`` are 5'→3' TRAVERSAL endpoints, so a REVERSE domain starts at the
    HIGH bp and ends at the low one (``domain_bp_range`` counts downward). Take (lo, hi) here
    and orient by direction, so a test can't silently build an empty domain.
    """
    start, end = (lo, hi) if direction == Direction.FORWARD else (hi, lo)
    return Domain(
        helix_id=hid,
        start_bp=start,
        end_bp=end,
        direction=direction,
        overhang_id=overhang_id,
    )


def _two_helix_design(staple_domains, scaffold_domains=None) -> Design:
    """Two 40-bp helices with a forward scaffold across both; caller supplies the staples.

    Any bp covered by BOTH scaffold and staple is duplex → an FEM node. Everything else the
    staples/scaffold cover is single-stranded, which is what the classifier sorts.
    """
    hA, hB = _helix("A"), _helix("B", x=2.5)
    scaffold_domains = scaffold_domains or [_dom("A", 0, 39), _dom("B", 0, 39)]
    strands = [
        Strand(id="scaf", strand_type=StrandType.SCAFFOLD, domains=scaffold_domains),
    ]
    for i, doms in enumerate(staple_domains):
        strands.append(
            Strand(id=f"stap{i}", strand_type=StrandType.STAPLE, domains=doms)
        )
    return Design(helices=[hA, hB], strands=strands)


# ── 1. classification ─────────────────────────────────────────────────────────────


def test_tail_has_exactly_one_anchor_and_a_bridge_has_two():
    """The number of meshed neighbours IS the discriminator (module docstring)."""
    # stap0: 10 bp duplex on A, then a 6-nt ssDNA run, then 10 bp duplex on B  → BRIDGE.
    # stap1: 10 bp duplex on A, then a 5-nt overhang tail hanging off the end   → TAIL.
    design = _two_helix_design(
        [
            [
                _dom("A", 0, 9, Direction.REVERSE),
                _dom("A", 10, 15, Direction.REVERSE),
                _dom("B", 0, 9, Direction.REVERSE),
            ],
            [
                _dom("A", 20, 29, Direction.REVERSE),
                _dom("A", 30, 34, Direction.REVERSE, overhang_id="oh1"),
            ],
        ]
    )
    # The scaffold covers A/B 0..39, so a staple bp is duplex; the 6-nt run on A 10..15 and
    # the 5-nt overhang on A 30..34 are staple-only *within* the scaffold's span... make them
    # single-stranded by having the scaffold NOT cover them:
    design.strands[0].domains = [_dom("A", 0, 9), _dom("A", 20, 29), _dom("B", 0, 9)]

    runs = classify_ssdna_runs(design)
    kinds = sorted(r.kind for r in runs)
    assert kinds == ["bridge", "tail"], [(r.kind, r.n_nt) for r in runs]

    bridge = next(r for r in runs if r.kind == "bridge")
    tail = next(r for r in runs if r.kind == "tail")

    # stap0's 5'→3' path (REVERSE domains descend): A9..A0 | A15..A10 | B9..B0
    #                                               meshed | 6-nt ssDNA  | meshed
    assert bridge.n_nt == 6
    assert bridge.anchor_5 == SSAnchor("A", 0) and bridge.anchor_3 == SSAnchor("B", 9)
    assert bridge.bridge_kind == "hop"  # anchors on different helices
    with pytest.raises(ValueError):
        _ = bridge.anchor  # two anchors — must be handled explicitly

    # stap1's path: A29..A20 (meshed) | A34..A30 (5-nt overhang) — anchored on its 5' side.
    assert tail.n_nt == 5
    assert (tail.anchor_5 is None) != (tail.anchor_3 is None)  # exactly one
    assert tail.anchor == SSAnchor("A", 20)
    assert tail.is_overhang and tail.overhang_ids == ("oh1",)


def test_interior_gap_and_hop_are_distinguished():
    """Both anchors on one helix = an unstapled interior gap; different helices = a hop.
    SS-1 treats them with the same element but they are different structures — keep them apart."""
    design = _two_helix_design(
        [
            [
                _dom("A", 0, 9, Direction.REVERSE),
                _dom("A", 10, 13, Direction.REVERSE),
                _dom("A", 14, 23, Direction.REVERSE),
            ],
        ]
    )
    design.strands[0].domains = [
        _dom("A", 0, 9),
        _dom("A", 14, 23),
    ]  # scaffold skips 10..13

    # path (REVERSE, descending): A9..A0 (meshed) | A13..A10 (4-nt gap) | A23..A14 (meshed)
    runs = classify_ssdna_runs(design)
    assert len(runs) == 1
    gap = runs[0]
    assert gap.kind == "bridge" and gap.bridge_kind == "interior" and gap.n_nt == 4
    assert gap.anchor_5 == SSAnchor("A", 0) and gap.anchor_3 == SSAnchor("A", 23)


def test_free_run_has_no_anchor():
    """A strand that never touches the duplex core is 'free' — reported, not silently dropped."""
    design = _two_helix_design([[_dom("A", 0, 9, Direction.REVERSE)]])
    design.strands.append(
        Strand(
            id="floater",
            strand_type=StrandType.STAPLE,
            domains=[_dom("B", 20, 27, Direction.REVERSE)],
        )
    )  # scaffold covers B, but...
    design.strands[0].domains = [_dom("A", 0, 9)]  # ...scaffold only on A now

    free = [r for r in classify_ssdna_runs(design) if r.kind == "free"]
    assert len(free) == 1 and free[0].n_nt == 8
    assert free[0].anchor is None


# ── 2. the anchor rule ────────────────────────────────────────────────────────────


def test_anchor_is_the_end_that_crosses_into_the_embedded_staple_not_a_fixed_polarity():
    """The user's rule. A tail whose ssDNA domain comes FIRST in the strand path (5' tail)
    anchors on its 3' side; a tail that comes LAST (3' tail) anchors on its 5' side. If we
    had hard-coded a polarity, one of these two would anchor to None."""
    # 5' tail: ssDNA domain first, then the embedded duplex.
    d5 = _two_helix_design(
        [
            [
                _dom("A", 30, 34, Direction.REVERSE, overhang_id="oh5"),
                _dom("A", 0, 9, Direction.REVERSE),
            ],
        ]
    )
    d5.strands[0].domains = [_dom("A", 0, 9)]
    t5 = next(r for r in classify_ssdna_runs(d5) if r.kind == "tail")
    assert t5.anchor_5 is None and t5.anchor_3 == SSAnchor(
        "A", 9
    )  # anchored on its 3' side
    assert t5.anchor == SSAnchor("A", 9)

    # 3' tail: the embedded duplex first, then the ssDNA domain.
    d3 = _two_helix_design(
        [
            [
                _dom("A", 0, 9, Direction.REVERSE),
                _dom("A", 30, 34, Direction.REVERSE, overhang_id="oh3"),
            ],
        ]
    )
    d3.strands[0].domains = [_dom("A", 0, 9)]
    t3 = next(r for r in classify_ssdna_runs(d3) if r.kind == "tail")
    assert t3.anchor_3 is None and t3.anchor_5 == SSAnchor(
        "A", 0
    )  # anchored on its 5' side
    assert t3.anchor == SSAnchor("A", 0)


def test_run_nucleotides_are_in_5_to_3_path_order():
    """The nt list must be traversal-ordered (a REVERSE domain counts bp downward), because
    SS-2 chains tail beads in this order from the anchor outward."""
    design = _two_helix_design(
        [
            [
                _dom("A", 0, 9, Direction.REVERSE),
                _dom("A", 30, 34, Direction.REVERSE, overhang_id="oh"),
            ],
        ]
    )
    design.strands[0].domains = [_dom("A", 0, 9)]
    tail = next(r for r in classify_ssdna_runs(design) if r.kind == "tail")
    bps = [bp for _, bp, _ in tail.nts]
    assert bps == [34, 33, 32, 31, 30]  # REVERSE → descending, 5'→3'
    assert all(d == "REVERSE" for _, _, d in tail.nts)


# ── 3. nothing else moved ─────────────────────────────────────────────────────────


@pytest.mark.parametrize("name", ["26hb_platform_v3.nadoc"])
def test_meshed_bp_reproduces_the_mesh_builders_node_set_exactly(name):
    """``meshed_bp`` must stay in lockstep with ``build_fem_mesh`` — the classifier is only
    correct if it agrees with the mesh about which bp are nodes."""
    path = EXAMPLES / name
    if not path.exists():
        pytest.skip(f"{name} not present")
    design = Design(**json.loads(path.read_text()))
    mesh = build_fem_mesh(design)

    from_mesh = {(n.helix_id, n.global_bp) for n in mesh.nodes}
    from_classifier = {(h, bp) for h, bps in meshed_bp(design).items() for bp in bps}
    assert from_mesh == from_classifier


@pytest.mark.parametrize("name", ["26hb_platform_v3.nadoc"])
def test_ss0_is_representation_only_every_node_is_still_a_bp_node(name):
    """SS-0 adds the ``kind`` field and emits no ss nodes. If this ever fails, the mesh
    started emitting ssDNA nodes into the static K — which the plan forbids (decision 1)."""
    path = EXAMPLES / name
    if not path.exists():
        pytest.skip(f"{name} not present")
    design = Design(**json.loads(path.read_text()))
    mesh = build_fem_mesh(design)
    assert mesh.nodes, "expected a non-empty mesh"
    assert all(n.kind == "bp" for n in mesh.nodes)
    assert all(n.direction is None for n in mesh.nodes)


def test_inventory_totals_add_up():
    design = _two_helix_design(
        [
            [
                _dom("A", 0, 9, Direction.REVERSE),
                _dom("A", 10, 15, Direction.REVERSE),
                _dom("B", 0, 9, Direction.REVERSE),
            ],
            [
                _dom("A", 20, 29, Direction.REVERSE),
                _dom("A", 30, 34, Direction.REVERSE, overhang_id="oh1"),
            ],
        ]
    )
    design.strands[0].domains = [_dom("A", 0, 9), _dom("A", 20, 29), _dom("B", 0, 9)]

    inv = ssdna_inventory(design)
    assert inv.n_ss_nt == sum(r.n_nt for r in inv.runs) == 11  # 6-nt bridge + 5-nt tail
    assert inv.n_nodes == 30  # 3 × 10 duplex bp
    assert len(inv.bridges("hop")) == 1 and len(inv.bridges("interior")) == 0
    assert len(inv.tails(overhang=True)) == 1 and len(inv.tails(overhang=False)) == 0


# ── SS-1: SNUPI's bridging ssDNA element (gap G9) ──────────────────────────────────
#
# The oracle is the REAL SNUPI binary. Designs carrying interior scaffold gaps of every
# length n = 1..24 were run through it and the ssDNA elements' (L, GJ, EI) read out of its
# `PROP` array; snupi_material._SS_TABLE is that measurement. The numbers below are lifted
# straight from those runs, so these tests pin us to SNUPI itself, not to our own algebra.

SNUPI_SS_OBSERVED = {  # n_nt -> (L_rest nm, GJ pN·nm², EI pN·nm²), from ~/SNUPI PROP
    6: (2.2667, 6.9368, 40.6013),
    10: (2.8647, 4.0393, 39.7882),
    18: (3.6686, 2.3584, 23.4259),
    24: (4.1470, 2.1018, 14.2396),
}


@pytest.mark.parametrize("n_nt,expected", sorted(SNUPI_SS_OBSERVED.items()))
def test_ssdna_element_reproduces_the_real_snupi_binary(n_nt, expected):
    from backend.physics.snupi_material import ssdna_element

    l_rest, gj, ei = expected
    el = ssdna_element(n_nt)
    assert el["l_rest"] == pytest.approx(l_rest, abs=1e-3)
    assert el["gj"] == pytest.approx(gj, rel=1e-3)
    assert el["ei"] == pytest.approx(ei, rel=1e-3)
    assert el["ea"] == pytest.approx(15.0)  # SS_EA_L — relaxed stretch rigidity


def test_ssdna_rest_length_is_the_wlc_end_to_end_not_the_contour():
    """The single most common way to get this element wrong. A 24-mer's CONTOUR is ~16 nm
    (0.68 nm/nt); its rest length as a collapsed beam is the WLC RMS end-to-end, ~4.1 nm."""
    from backend.physics.snupi_material import ssdna_element

    el = ssdna_element(24)
    assert el["l_rest"] == pytest.approx(4.147, abs=1e-3)
    assert el["l_rest"] < 0.3 * 24 * 0.68  # nowhere near the contour


def test_ssdna_element_is_length_dependent_and_smooth():
    """Short runs are stiff and taut, long ones relax to bulk-polymer floppiness — that IS
    the physics (ACS Nano 2021). Also pins that the n > 24 extrapolation joins the measured
    table continuously rather than stepping."""
    from backend.physics.snupi_material import SS_TABLE_MAX_NT, ssdna_element

    assert ssdna_element(1)["gj"] == pytest.approx(
        15.0
    )  # SS_GJ_H, the short-ssDNA limit
    ns = list(range(1, 41))
    els = [ssdna_element(n) for n in ns]
    lengths = [e["l_rest"] for e in els]
    gjs = [e["gj"] for e in els]
    assert lengths == sorted(lengths)  # rest length grows with n
    assert gjs == sorted(gjs, reverse=True)  # torsional rigidity decays
    assert gjs[-1] > 2.0  # toward SS_GJ_L = 2, never below
    edge = SS_TABLE_MAX_NT
    step_in = lengths[edge - 1] - lengths[edge - 2]  # last step inside the table
    step_out = lengths[edge] - lengths[edge - 1]  # first extrapolated step
    assert step_out == pytest.approx(step_in, rel=0.25)  # no discontinuity at the seam


def _ss_runs_in_mesh(mesh):
    from collections import Counter

    return sorted(
        Counter(e.ss_nt for e in mesh.elements if e.ss_nt is not None).items()
    )


@pytest.mark.parametrize(
    "stem,expected",
    [
        # The REAL SNUPI's own ssDNA element list for these two designs, read from its PROP array
        # (isotropic EIy == EIz is the discriminator). Our mesh must emit exactly the same runs:
        # one collapsed beam per contiguous unpaired run, no more, no fewer.
        ("6hbx100_noT", [(6, 2), (10, 2), (18, 2)]),
        ("3x4SQ", [(6, 2), (10, 1), (14, 1), (16, 4), (22, 2), (24, 1)]),
    ],
)
def test_snupi_mesh_ssdna_elements_match_the_real_binary(stem, expected):
    ws = Path(__file__).resolve().parents[1] / "workspace" / f"{stem}.nadoc"
    if not ws.exists():
        pytest.skip(f"{stem}.nadoc not present")
    design = Design.model_validate_json(ws.read_text())
    mesh = build_fem_mesh(design, material="snupi")
    assert _ss_runs_in_mesh(mesh) == expected


def _element_fingerprint(mesh):
    """Hashable projection of the element list (FEMElement holds ndarrays, so it is not
    directly comparable)."""
    return [
        (
            e.node_i,
            e.node_j,
            round(e.length, 9),
            round(e.ea, 6),
            round(e.ei, 6),
            round(e.gj, 6),
            e.motif_family,
            e.motif,
            e.ss_nt,
        )
        for e in mesh.elements
    ]


def test_cando_mesh_is_byte_identical_and_carries_no_ssdna_elements():
    """Decision 5: everything is gated behind material="snupi". If this fails, an SS-1 change
    leaked into the validated CanDo baseline."""
    ws = Path(__file__).resolve().parents[1] / "workspace" / "6hbx100_noT.nadoc"
    if not ws.exists():
        pytest.skip("6hbx100_noT.nadoc not present")
    design = Design.model_validate_json(ws.read_text())
    cando = build_fem_mesh(design)
    assert _element_fingerprint(
        build_fem_mesh(design, material="cando")
    ) == _element_fingerprint(cando)
    assert all(e.ss_nt is None for e in cando.elements)
    # ...and the snupi mesh keeps the SAME NODES (ssDNA bridges join existing bp nodes and
    # add none — SS-2 is what introduces ss nodes).
    snupi = build_fem_mesh(design, material="snupi")
    assert [(n.helix_id, n.global_bp) for n in snupi.nodes] == [
        (n.helix_id, n.global_bp) for n in cando.nodes
    ]
    # ...and every duplex beam is untouched: snupi only ADDS ssDNA elements here.
    assert [
        e for e in _element_fingerprint(snupi) if e[-1] is None
    ] == _element_fingerprint(cando)


def test_interior_gap_becomes_a_soft_ssdna_beam_not_a_rigid_duplex_one():
    """The gap that SS-1 closes: an unstapled interior gap used to be spanned by a dsDNA beam
    — carrying full duplex AXIAL stiffness across a stretch that has no duplex in it."""
    from backend.physics.fem_solver import EA_DS
    from backend.physics.snupi_material import ssdna_element

    design = _two_helix_design(
        [
            [
                _dom("A", 0, 9, Direction.REVERSE),
                _dom("A", 10, 13, Direction.REVERSE),
                _dom("A", 14, 23, Direction.REVERSE),
            ],
        ]
    )
    design.strands[0].domains = [
        _dom("A", 0, 9),
        _dom("A", 14, 23),
    ]  # scaffold skips 10..13

    cando = build_fem_mesh(design)
    span_c = [e for e in cando.elements if e.length > 1.5 * FEM_RISE_PER_BP]
    assert len(span_c) == 1  # the old duplex beam...
    assert (
        span_c[0].ss_nt is None and span_c[0].ea == EA_DS
    )  # ...with dsDNA stretch stiffness
    assert span_c[0].length == pytest.approx(
        5 * FEM_RISE_PER_BP
    )  # and a geometric length

    snupi = build_fem_mesh(design, material="snupi")
    ss = [e for e in snupi.elements if e.ss_nt is not None]
    assert len(ss) == 1 and ss[0].ss_nt == 4
    prop = ssdna_element(4)
    assert ss[0].ei == pytest.approx(prop["ei"]) and ss[0].gj == pytest.approx(
        prop["gj"]
    )
    assert ss[0].length == pytest.approx(
        prop["l_rest"]
    )  # SNUPI's REST length, not 5 rises
    assert ss[0].ea < 0.05 * EA_DS  # genuinely soft now (15 vs 1100 pN)
    # ...and no duplex beam is left spanning the gap.
    assert not [
        e
        for e in snupi.elements
        if e.ss_nt is None and e.length > 1.5 * FEM_RISE_PER_BP
    ]


def test_cross_helix_hop_becomes_a_real_beam():
    """A hop through ssDNA that stays on a MESHED helix was invisible to the old, domain-
    granularity `_add_ssdna_hops` (it asks whether the domain's HELIX is meshed, not whether
    these nucleotides are) — so the two duplex blocks got no coupling at all. The nucleotide-
    exact classifier sees it, and SNUPI's element couples it with bending + torsion."""
    design = _two_helix_design(
        [
            [
                _dom("A", 0, 9, Direction.REVERSE),
                _dom("A", 10, 15, Direction.REVERSE),
                _dom("B", 0, 9, Direction.REVERSE),
            ],
        ]
    )
    design.strands[0].domains = [_dom("A", 0, 9), _dom("B", 0, 9)]

    cando = build_fem_mesh(design)
    assert (
        cando.springs == [] and cando.rigid_links == []
    )  # the blind spot: no coupling

    snupi = build_fem_mesh(design, material="snupi")
    assert snupi.springs == []
    ss = [e for e in snupi.elements if e.ss_nt is not None]
    assert len(ss) == 1 and ss[0].ss_nt == 6
    assert ss[0].gj > 0.0 and ss[0].ei > 0.0  # HAS bending + torsion
    hi, hj = snupi.nodes[ss[0].node_i], snupi.nodes[ss[0].node_j]
    assert {hi.helix_id, hj.helix_id} == {"A", "B"}


def test_no_beam_is_welded_across_a_stretch_with_no_strand_coverage():
    """The VoltronCore bug: the scaffold LEAVES a helix and comes back, so two duplex blocks
    sit on one helix with 54 bp of vacuum between them — and the mesh builder, assuming any
    two consecutive duplex bp on a helix are bonded, welded them with a full-stiffness 22.1 nm
    dsDNA beam. They are separate FEM bodies, coupled only through the real ssDNA hops."""
    # Scaffold: A 0..9 duplex, hops to B, comes back to A 30..39. A 10..29 is EMPTY — no
    # strand of any kind. So A's duplex bp jump 9 -> 30 with nothing in between.
    design = _two_helix_design(
        [
            [_dom("A", 0, 9, Direction.REVERSE)],
            [_dom("B", 0, 9, Direction.REVERSE)],
            [_dom("A", 30, 39, Direction.REVERSE)],
        ],
        scaffold_domains=[_dom("A", 0, 9), _dom("B", 0, 9), _dom("A", 30, 39)],
    )
    cando = build_fem_mesh(design)
    welded = [
        e
        for e in cando.elements
        if cando.nodes[e.node_i].helix_id == cando.nodes[e.node_j].helix_id
        and e.length > 3 * FEM_RISE_PER_BP
    ]
    assert len(welded) == 1  # the bug, still on the cando path

    snupi = build_fem_mesh(design, material="snupi")
    welded = [
        e
        for e in snupi.elements
        if e.ss_nt is None
        and snupi.nodes[e.node_i].helix_id == snupi.nodes[e.node_j].helix_id
        and e.length > 3 * FEM_RISE_PER_BP
    ]
    assert welded == [], "a beam was emitted across a stretch with no strand coverage"


def test_ssdna_element_assembles_an_isotropic_symmetric_stiffness():
    """SNUPI's ssDNA element is the ONE isotropic element in the model — a plain
    Euler-Bernoulli beam that must bypass the anisotropic motif 6×6 entirely."""
    import numpy as np

    from backend.physics.fem_solver import assemble_global_stiffness

    design = _two_helix_design(
        [
            [
                _dom("A", 0, 9, Direction.REVERSE),
                _dom("A", 10, 15, Direction.REVERSE),
                _dom("B", 0, 9, Direction.REVERSE),
            ],
        ]
    )
    design.strands[0].domains = [_dom("A", 0, 9), _dom("B", 0, 9)]
    mesh = build_fem_mesh(design, material="snupi")
    for material in ("cando", "snupi"):
        K, _ = assemble_global_stiffness(mesh, material=material)
        A = K.toarray()
        assert np.allclose(A, A.T), f"{material}: K not symmetric"
        assert np.all(np.isfinite(A))


# ── 5. SS-2: free ssDNA tails as explicit Langevin chains ─────────────────────────
#
# These pin the phase's load-bearing invariant (tails are DYNAMICS-ONLY — decision 1), the
# element choice (the intrinsic per-nt link, NOT the collapsed end-to-end element), and the
# corotational property that lets a tail wave at all.


def _tail_design(n_tail_nt: int = 16):
    """A 20-bp duplex on helix A + a staple carrying an `n_tail_nt` overhang TAIL on helix B.

    Helix B is meshed nowhere (the scaffold never reaches it), so the overhang domain's nucleotides
    are all single-stranded and the run has exactly ONE meshed neighbour — a tail.  The scaffold is
    trimmed to the staple's own span on purpose: run it past bp 19 and the uncovered remainder is
    itself a dangling-scaffold-end tail, which would quietly add beads to every count below.
    """
    hi = 39
    lo = hi - n_tail_nt + 1
    return _two_helix_design(
        [
            [
                _dom("A", 0, 19, Direction.REVERSE),
                _dom("B", lo, hi, Direction.REVERSE, overhang_id="oh1"),
            ]
        ],
        scaffold_domains=[_dom("A", 0, 19)],
    )


def test_ss2_tails_never_enter_the_mesh_the_static_k_or_the_nma():
    """DECISION 1, the load-bearing one: a free tail's DOF are dynamics-only.

    A floppy tail has near-zero eigenvalues. If they reached the NMA operator the 200 lowest
    modes would ALL be tail modes and the validated duplex-core RMSF would be destroyed; the
    static shape solve would near-singularise. Enforced structurally — the tail block is built
    by the dynamics side and never handed to build_fem_mesh — so this pins that the mesh, and
    everything derived from it, still sees duplex base pairs ONLY.
    """
    from backend.physics.fem_solver import assemble_global_stiffness
    from backend.physics.snupi_tails import build_tail_block

    design = _tail_design(16)
    mesh = build_fem_mesh(design, material="snupi")

    block = build_tail_block(design, mesh)
    assert block.n_tail == 16, (
        "fixture must actually have a 16-nt tail to make this test mean anything"
    )

    assert all(nd.kind == "bp" for nd in mesh.nodes), "an ss node reached the FEM mesh"
    assert len(mesh.nodes) == block.n_bp
    K, _ = assemble_global_stiffness(mesh, material="snupi")
    assert K.shape == (6 * block.n_bp, 6 * block.n_bp), "the static K grew tail DOF"


def test_tail_block_matches_the_classifiers_tails_one_bead_per_nucleotide():
    from backend.physics.snupi_tails import build_tail_block

    design = _tail_design(16)
    mesh = build_fem_mesh(design, material="snupi")
    block = build_tail_block(design, mesh)

    tails = [r for r in classify_ssdna_runs(design) if r.kind == "tail"]
    assert block.n_tail == sum(r.n_nt for r in tails)  # 1 bead / nt
    assert len(block.elements) == block.n_tail  # anchor→b0, b0→b1, … : one per bead
    assert len(block.anchors) == len(tails)
    # every bead carries its render-bead key, so SS-4 can map it back to what is drawn
    assert all(nd.helix_id and nd.direction for nd in block.nodes)
    assert [nd.index_in_run for nd in block.nodes] == list(range(16))
    # the anchor is a real CORE node, and the chain hangs off it
    assert block.anchors[0] < block.n_bp
    assert block.elements[0][0] == block.anchors[0]


def test_tail_chain_starts_at_the_ssdna_contour_not_the_duplex_rise():
    """The rendered pose spaces nucleotides at the 0.34 nm duplex rise — half the ssDNA contour
    per nt. Starting there would compress every bond ~2× and inject a large spurious axial stress
    into the trajectory, so the chain is laid out at its REST bond length instead."""
    import numpy as np

    from backend.physics.fem_solver import FEM_RISE_PER_BP
    from backend.physics.snupi_material import SS_CONTOUR_PER_NT
    from backend.physics.snupi_tails import build_tail_block

    design = _tail_design(16)
    mesh = build_fem_mesh(design, material="snupi")
    block = build_tail_block(design, mesh)

    X = np.vstack([np.array([nd.position for nd in mesh.nodes]), block.positions])
    bonds = [float(np.linalg.norm(X[j] - X[i])) for (i, j, _r, _k) in block.elements]
    assert np.allclose(bonds, SS_CONTOUR_PER_NT, atol=1e-9)
    assert not np.isclose(
        SS_CONTOUR_PER_NT, FEM_RISE_PER_BP
    )  # the two really are different


def test_the_per_nt_link_is_not_the_collapsed_end_to_end_element():
    """Reusing ``ssdna_element(1)`` per link would DOUBLE-COUNT the chain's entropy: that element
    is an effective one whose softness IS the run's conformational freedom, integrated out, while
    an explicit chain represents that freedom with its beads. The link must carry the INTRINSIC
    (enthalpic) constants — in particular the taut stretch modulus, not the entropic one."""
    from backend.physics.snupi_material import (
        SS_EA_RELAXED,
        SS_EA_TAUT,
        SS_EI_DISCRETE_FACTOR,
        SS_PERSISTENCE_NM,
        ssdna_element,
        ssdna_link_element,
    )

    link = ssdna_link_element()
    collapsed = ssdna_element(1)

    # Bending starts from EI = k_BT·L_p (the definition of persistence length — and the value SNUPI
    # itself reports for the one run in its output short enough to be near-taut, TALOS poly-T:
    # EI = 2.775), then carries the measured discretisation correction, because a chain whose bond
    # IS its persistence length is nowhere near the continuum limit that identity assumes.
    assert link["ei"] == pytest.approx(
        4.142 * SS_PERSISTENCE_NM * SS_EI_DISCRETE_FACTOR, rel=1e-6
    )
    assert link["ei"] == pytest.approx(1.593, abs=0.005)
    assert 0.4 < SS_EI_DISCRETE_FACTOR < 0.8, (
        "the calibration should soften, and only modestly"
    )
    assert link["ea"] == SS_EA_TAUT == 710.0
    assert collapsed["ea"] == SS_EA_RELAXED == 15.0
    assert link["ea"] > 40 * collapsed["ea"], (
        "the link must use the TAUT stretch modulus"
    )
    # and it must be length-independent — the chain's length lives in the bead count
    assert ssdna_link_element() == link


def test_tail_force_vanishes_at_rest_and_under_rigid_body_motion():
    """THE corotational property, and the reason a linear beam would not do: swinging a straight
    tail about its anchor must cost NOTHING (rigid-body motion is not deformation), while bending
    it costs the ssDNA bending energy. A linear beam would penalise the swing and pin the tail
    near its initial pose — its end-to-end distance could never relax to the polymer value.

    ``coil=False`` on purpose: the REST state of the elements is the straight chain, so that is the
    configuration at which the force must vanish. SS-3 starts a tail from a thermal coil instead, and
    a coil is not stress-free — it carries a few kT of bend, as it physically must."""
    import numpy as np

    from backend.physics.snupi_corotational import exp_so3
    from backend.physics.snupi_tails import build_tail_block, tail_internal_force

    design = _tail_design(16)
    mesh = build_fem_mesh(design, material="snupi")
    block = build_tail_block(design, mesh, coil=False)
    n_tot = block.n_total
    X0 = np.vstack([np.array([nd.position for nd in mesh.nodes]), block.positions])

    f0 = tail_internal_force(np.zeros(6 * n_tot), X0, block)
    assert np.abs(f0).max() < 1e-8, "the rest configuration is not stress-free"

    # Rigid rotation of EVERYTHING about the origin + a translation.
    phi = np.array([0.3, -0.7, 0.45])
    R = exp_so3(phi)
    t = np.array([1.5, -2.0, 0.75])
    q = np.zeros(6 * n_tot)
    qn = q.reshape(n_tot, 6)
    qn[:, :3] = (X0 @ R.T + t) - X0
    qn[:, 3:] = phi
    f = tail_internal_force(q, X0, block)
    assert np.abs(f).max() < 1e-6, "a rigid-body move produced an internal force"

    # A genuine BEND, though, must cost something.
    qb = np.zeros(6 * n_tot)
    qb.reshape(n_tot, 6)[block.n_bp + 8 :, :3] += np.array([1.0, 0.0, 0.0])
    assert np.abs(tail_internal_force(qb, X0, block)).max() > 1.0


def test_tails_are_gated_on_snupi():
    """Free tails are a snupi-only NADOC extension; the cando path stays byte-identical (decision 5).
    (Their hydrodynamic drag arrived in SS-3 — see
    ``test_ss3_hydrodynamics_with_tails_requires_the_coarse_blob_model``.)"""
    from backend.physics.snupi_dynamics import simulate_equilibrium

    design = _tail_design(16)
    with pytest.raises(ValueError, match="snupi"):
        simulate_equilibrium(design, material="cando", tails=True, n_steps=1, n_equil=0)


def test_simulate_equilibrium_with_tails_keeps_every_core_observable_core_only():
    """The tails ride ALONGSIDE the core payload, never mixed into it. Mixing floppy tail beads
    into `frames`/`rmsf` would put badly-placed points into every downstream Kabsch fit and RMSF
    comparison — precisely the bug the VoltronCore DISPLAY fix had to undo."""
    from backend.physics.snupi_dynamics import simulate_equilibrium

    design = _tail_design(16)
    mesh = build_fem_mesh(design, material="snupi")
    n = len(mesh.nodes)

    out = simulate_equilibrium(
        design,
        material="snupi",
        tails=True,
        n_steps=400,
        n_equil=100,
        sample_every=50,
        seed=0,
    )

    assert out["n_tail_nodes"] == 16
    assert out["positions0"].shape == (n, 3)
    assert out["frames"].shape[1] == n  # core only
    assert out["rmsf"].shape == (n,)
    assert len(out["helix_ids"]) == n
    assert out["mass_diag"].shape == (6 * n,)
    assert out["stiffness"].shape == (6 * n, 6 * n)
    # the tails arrive separately, and the full stack is available for the SS-4 display path
    assert out["tail_frames"].shape[1] == 16
    assert out["frames_all"].shape[1] == n + 16
    assert len(out["tail_nodes"]) == 16
    assert out["tail_nodes"][0]["overhang_ids"] == ["oh1"]


def test_a_design_with_no_tails_takes_the_plain_path_unchanged():
    """`tails=True` on a design that has none must not perturb anything — no extra DOF, no
    different code path, so every existing snupi dynamics number stays exactly as it was."""
    import numpy as np

    from backend.physics.snupi_dynamics import simulate_equilibrium

    # Fully duplex: scaffold and staple span exactly the same bp, so there is no ssDNA anywhere.
    # (Let the scaffold overrun the staple and the uncovered remainder is a dangling-end TAIL —
    # which is precisely what the classifier should say, and did.)
    design = _two_helix_design(
        [[_dom("A", 0, 19, Direction.REVERSE)]], scaffold_domains=[_dom("A", 0, 19)]
    )
    kw = dict(material="snupi", n_steps=300, n_equil=100, sample_every=50, seed=0)
    off = simulate_equilibrium(design, tails=False, **kw)
    on = simulate_equilibrium(design, tails=True, **kw)
    assert "tail_frames" not in on
    assert np.allclose(off["frames"], on["frames"])
    # (ARPACK is not bit-reproducible across the two calls' differently-sliced mass arrays, so the
    # auto-sized step agrees to round-off rather than exactly — the trajectory above is the real pin.)
    assert off["dt_ns"] == pytest.approx(on["dt_ns"], rel=1e-9)


def test_wlc_oracle_formula_matches_the_snupi_measured_rest_lengths():
    """Cross-check the oracle itself before trusting it as a gate: SNUPI's own MEASURED collapsed
    ssDNA rest lengths ARE WLC RMS end-to-end distances, so the formula must reproduce them to
    within the contour-per-nt ambiguity (SNUPI's contour per nt is itself length-dependent,
    SS_LCT1_S=0.38 → SS_LCT1_L=0.68, so an exact match is not expected — a close one is)."""
    import math

    from backend.physics.snupi_material import ssdna_element
    from backend.physics.snupi_tails import wlc_mean_square_end_to_end

    for n in (6, 10, 16, 24):
        wlc = math.sqrt(wlc_mean_square_end_to_end(n))
        snupi = ssdna_element(n)["l_rest"]
        assert snupi == pytest.approx(wlc, rel=0.22), (
            f"n={n}: SNUPI {snupi} vs WLC {wlc}"
        )


# ── 6. SS-2: the ssDNA chain's polymer mechanics ──────────────────────────────────


def test_ssdna_chain_joint_stiffness_is_ei_over_the_bond_length():
    """The element-level pin behind the whole tail model, and it is EXACT — no simulation needed.

    Integrating out the nodal triads of a chain of these corotational Euler-Bernoulli beams leaves
    a joint energy U = ½·(EI/b)·θ² per kink, i.e. a discrete worm-like chain whose *small-angle*
    persistence length is EI/k_BT. Impose a uniform kink, relax the triads, read the energy back.

    (The chain's EMERGENT persistence length is larger than EI/k_BT — the bond is as long as the
    persistence length itself, far from the continuum limit this identity assumes — which is what
    SS_EI_DISCRETE_FACTOR corrects. This test pins the mechanics; the calibration handles the rest.)
    """
    import numpy as np
    from scipy.optimize import minimize

    from backend.physics.snupi_corotational import (
        _cr_frame,
        _local_defo,
        element_reference,
        exp_so3,
        local_beam_stiffness_12,
    )
    from backend.physics.snupi_material import SS_CONTOUR_PER_NT

    b, ei = SS_CONTOUR_PER_NT, 2.775

    def relaxed_energy(theta, n_node):
        X = np.zeros((n_node, 3))
        ang = 0.0
        for i in range(1, n_node):
            X[i] = X[i - 1] + b * np.array([np.sin(ang), 0.0, np.cos(ang)])
            ang += theta
        Xr = np.zeros((n_node, 3))
        Xr[:, 2] = np.arange(n_node) * b
        K12 = local_beam_stiffness_12(b, 710.0, 15.0, ei, ei)
        refs = [
            element_reference(Xr[i], Xr[i + 1], np.eye(3), np.eye(3), rest_length=b)
            for i in range(n_node - 1)
        ]

        def U(p):
            R = [exp_so3(p[3 * i : 3 * i + 3]) for i in range(n_node)]
            tot = 0.0
            for i in range(n_node - 1):
                E, _ = _cr_frame(X[i], X[i + 1], R[i], R[i + 1])
                d = _local_defo(X[i], X[i + 1], R[i], R[i + 1], refs[i], E)
                tot += 0.5 * d @ K12 @ d
            return tot

        p0 = np.zeros(3 * n_node)
        p0[1::3] = np.arange(n_node) * theta  # triads start tangent to the arc
        return minimize(
            U, p0, method="L-BFGS-B", options=dict(maxiter=4000, ftol=1e-14, gtol=1e-12)
        ).fun

    theta = 0.05
    # Energy DIFFERENCE between a 24- and a 14-node chain = 10 interior joints, free of end effects.
    per_joint = (relaxed_energy(theta, 24) - relaxed_energy(theta, 14)) / 10.0
    kappa_eff = 2.0 * per_joint / theta**2
    assert kappa_eff == pytest.approx(ei / b, rel=1e-3)


def test_tail_langevin_thermalises_its_bonds_to_kt():
    """Equipartition in the SHIPPED engine: ½·(EA/b)·⟨Δb²⟩ = ½·k_BT.

    One number that simultaneously validates the tail bead mass, the Langevin noise amplitude, and
    the fluctuation–dissipation consistency of the integrator over the NEW (tail) DOF. Chosen as
    the gate because bond stretch is a fast, LOCAL mode — it relaxes in ~1e-5 ns, so a short run
    converges it. (The chain's end-to-end distance is the opposite: a slow, long-wavelength mode,
    which is why the WLC oracle needs the pivot sampler in scripts/snupi_tail_calibrate.py.)
    """
    import numpy as np

    from backend.physics.snupi_dynamics import KBT_300, simulate_equilibrium
    from backend.physics.snupi_material import SS_CONTOUR_PER_NT, SS_EA_TAUT

    design = _tail_design(8)
    out = simulate_equilibrium(
        design,
        material="snupi",
        tails=True,
        n_steps=3000,
        n_equil=500,
        sample_every=5,
        seed=1,
    )

    beads = out["frames_all"][
        :, out["frames"].shape[1] :, :
    ]  # (F, 8, 3) tail beads only
    bonds = np.linalg.norm(beads[:, 1:, :] - beads[:, :-1, :], axis=2)
    var = float(np.var(bonds))
    expected = KBT_300 / (SS_EA_TAUT / SS_CONTOUR_PER_NT)  # k_BT / k_stretch
    assert var == pytest.approx(expected, rel=0.30), (
        f"tail bonds not thermalised: var={var:.5f} nm², expected k_BT/(EA/b)={expected:.5f}"
    )
    assert float(np.mean(bonds)) == pytest.approx(SS_CONTOUR_PER_NT, abs=0.05)


@pytest.mark.slow
@pytest.mark.cando
@pytest.mark.parametrize("n_nt", [8, 16, 28])
def test_free_tail_reproduces_the_wlc_end_to_end_distribution(n_nt):
    """THE SS-2 ORACLE. A free n-nt ssDNA tail at equilibrium must reproduce the worm-like-chain
    end-to-end distribution, ⟨R_ee²⟩ = 2·L_p·L_c·[1 − (L_p/L_c)(1 − e^{−L_c/L_p})], with the real
    ssDNA persistence length L_p = 0.67 nm. One number that validates the element, the calibration,
    and the whole "a tail is a polymer" claim at once.

    Sampled with the PIVOT sampler, not molecular dynamics — see `pivot_sample_chain`. A chain's
    end-to-end distance is a slow, long-wavelength mode; an MD run converges the local bond angles
    long before it converges this, and reports a confidently wrong (far too extended) answer.

    The calibrated chain lands within ±5% for n ≥ 8 (see the SS-2 table in
    memory/project_snupi_ssdna.md); the tolerance here is 20% because this runs far fewer sweeps
    than the calibration did, and because a discrete chain whose bond IS its persistence length is
    not exactly a continuum WLC — an exact match is not on offer. 3-mers (24 of VoltronCore's 55
    tails) sit ~13% too extended and are deliberately not tuned away: fixing them would break the
    other lengths.
    """
    from backend.physics.snupi_material import ssdna_link_element
    from backend.physics.snupi_tails import (
        pivot_sample_chain,
        wlc_mean_square_end_to_end,
    )

    ei = ssdna_link_element()["ei"]
    got = pivot_sample_chain(n_nt, ei, n_sweep=12000, seed=0)
    want = wlc_mean_square_end_to_end(n_nt)

    # the chain must be a real WLC, i.e. its tangent correlation DECAYS TO ZERO rather than
    # plateauing (a plateau is the signature of an unequilibrated chain — it is how this phase
    # was fooled twice)
    assert abs(got["corr"][min(6, n_nt - 1)]) < 0.1, (
        "tangent correlation plateaus — not a WLC"
    )
    assert got["r2"] == pytest.approx(want, rel=0.20), (
        f"{n_nt}-nt tail: ⟨R_ee²⟩ = {got['r2']:.2f} nm², WLC predicts {want:.2f} nm²"
    )


def test_vectorised_tail_force_equals_the_scalar_reference():
    """The tail force is vectorised over elements because the scalar Python loop costs ~19 ms per
    evaluation on VoltronCore's 571 beads vs ~0.3 ms for the whole 7088-node duplex core — twice a
    step, that is a 68x slowdown and a 20-minute trajectory. This pins the fast path against the
    scalar one, which goes through the already-validated snupi_corotational kernel element by
    element. Checked at LARGE rotations too: that is where a batched log/exp map would diverge.
    """
    import numpy as np

    from backend.physics.snupi_tails import (
        _tail_internal_force_scalar,
        build_tail_block,
        tail_internal_force,
    )

    design = _tail_design(16)
    mesh = build_fem_mesh(design, material="snupi")
    block = build_tail_block(design, mesh)
    X0 = np.vstack([np.array([nd.position for nd in mesh.nodes]), block.positions])
    rng = np.random.default_rng(7)

    for amp in (
        0.0,
        0.05,
        0.5,
        1.4,
    ):  # 1.4 rad ≈ 80° per node — a genuinely waving tail
        q = amp * rng.standard_normal(6 * block.n_total)
        fast = tail_internal_force(q, X0, block)
        ref = _tail_internal_force_scalar(q, X0, block)
        assert np.allclose(fast, ref, atol=1e-9, rtol=1e-7), (
            f"diverged at amplitude {amp}"
        )


# ── 6. SS-3: hydrodynamic drag on the tails ───────────────────────────────────────
#
# Two species now share one blob model. The invariant that makes that legitimate is that
# each keeps its OWN bead radius where it matters (the self-drag, via D) while every blob
# stays the SAME sphere (so C is still a single-radius RPY — no unequal-radius tensor, and
# the existing PD guarantee and k=8 calibration carry over). These pin exactly that, plus
# the initial conformation, which SS-3's gate showed was the thing actually keeping the
# tails from moving.


def _tail_mesh_and_block(n_tail=16, **kw):
    from backend.physics.snupi_tails import build_tail_block

    design = _tail_design(n_tail)
    mesh = build_fem_mesh(design, material="snupi")
    return design, mesh, build_tail_block(design, mesh, **kw)


def test_ss3_an_ssdna_blob_is_the_same_sphere_as_a_duplex_blob():
    """The single-radius RPY assumes every blob is the same sphere, so what varies between the
    species is how many NUCLEOTIDES fit in it — found by inverting the WLC, not by the naive
    contour ratio (ssDNA's 0.68 nm/nt vs the 0.34 nm rise would say 4 nt; a coil is far more
    compact than the chain laid straight, so 11 fit)."""
    import math

    from backend.physics.snupi_hydro_coarse import blob_radius_nm, ss_blob_nt
    from backend.physics.snupi_tails import (
        SS_HYDRO_RADIUS_NM,
        wlc_mean_square_end_to_end,
    )

    assert ss_blob_nt(8) == 11
    assert ss_blob_nt(8) != 4, "this is not the contour ratio — a coil is not a rod"
    for k in (4, 8, 16):
        n = ss_blob_nt(k)
        coil = math.hypot(
            0.5 * math.sqrt(wlc_mean_square_end_to_end(n)), SS_HYDRO_RADIUS_NM
        )
        assert coil == pytest.approx(blob_radius_nm(k), rel=0.10), (
            f"k={k}: the {n}-nt ssDNA blob ({coil:.2f} nm) is not the duplex blob "
            f"({blob_radius_nm(k):.2f} nm) — C is no longer a single-radius RPY"
        )
    assert ss_blob_nt(4) < ss_blob_nt(8) < ss_blob_nt(16)  # monotone in the blob size


def test_ss3_tails_get_their_own_blobs_and_never_join_a_duplex_one():
    """A blob shares ONE mobility among its members. A tail merged into its anchor helix's blob
    would be dragged bodily around by the duplex instead of fluctuating — the tails would not wave,
    which is the whole point. So tail blobs must be disjoint from duplex blobs, even for a 3-mer."""
    from backend.physics.snupi_hydro_coarse import blob_count, blob_partition

    for n_tail in (3, 16):
        _d, mesh, block = _tail_mesh_and_block(n_tail)
        n_core = len(mesh.nodes)
        with_tails = blob_partition(mesh, 8, block)

        assert len(with_tails) == block.n_total
        core_blobs = set(with_tails[:n_core].tolist())
        tail_blobs = set(with_tails[n_core:].tolist())
        assert not (core_blobs & tail_blobs), (
            "a tail bead shares a blob with a duplex node"
        )
        assert blob_count(mesh, 8, block) == len(core_blobs) + len(tail_blobs)
        if n_tail == 3:
            assert len(tail_blobs) == 1, (
                "a short tail is one blob, not one blob per bead"
            )


def test_ss3_adding_tails_does_not_touch_a_single_core_blob():
    """The core partition must come out byte-identical with the tails plumbed in — otherwise every
    validated hydrodynamic number (the k=8 τ/τ_exact = 0.97 calibration) silently moves."""
    import numpy as np

    from backend.physics.snupi_hydro_coarse import blob_partition

    _d, mesh, block = _tail_mesh_and_block(16)
    n_core = len(mesh.nodes)
    assert np.array_equal(
        blob_partition(mesh, 8), blob_partition(mesh, 8, block)[:n_core]
    )


def test_ss3_each_species_keeps_its_exact_self_drag_and_xi_stays_spd():
    """THE SS-3 pin. Ξ = D + AᵀCA must (a) be SPD — this is where the last RPY parity bug showed up
    — and (b) give every node the EXACT Stokes self-drag of its own species: μ_self(1.1 nm) for a
    base pair, μ_self(0.5 nm) for an ssDNA nucleotide. (b) is what D is constructed to deliver, and
    it is the reason a single-radius C is legitimate at all: the species-dependent part of the drag
    is carried entirely by D."""
    import numpy as np

    from backend.physics.fem_solver import assemble_mass_matrix
    from backend.physics.snupi_dynamics import MASS_G6_TO_DYN
    from backend.physics.snupi_hydro_coarse import build_coarse_friction, node_radii
    from backend.physics.snupi_hydrodynamics import mu_self_rot, mu_self_trans

    design, mesh, block = _tail_mesh_and_block(16)
    n_core = len(mesh.nodes)
    m_core = (
        np.asarray(assemble_mass_matrix(mesh, design).tocsr().diagonal(), float)
        * MASS_G6_TO_DYN
    )
    m_diag = np.concatenate([m_core, block.mass_diag()])
    X0 = np.vstack([np.array([nd.position for nd in mesh.nodes]), block.positions])

    a = node_radii(mesh, block)
    assert (a[:n_core] == 1.1).all() and (a[n_core:] == 0.5).all()

    want = np.empty((block.n_total, 6))
    want[:, :3] = mu_self_trans(a)[:, None]
    want[:, 3:] = mu_self_rot(a)[:, None]

    for generalized in (False, True):
        fric = build_coarse_friction(
            mesh, X0, m_diag, 8, generalized=generalized, block=block
        )
        assert fric.n_nodes == block.n_total
        d = 1.0 / fric.dinv  # diag(D)
        C = fric.Lc @ fric.Lc.T  # (6B,6B) — the blob RPY mobility

        # SPD, argued and then measured. D > 0 and C SPD ⇒ Ξ = D + AᵀCA is SPD identically; the
        # Cholesky IS the C-is-SPD statement, and it is the cheap guard that would catch a repeat of
        # the μ^tr/μ^rt cross-block parity bug (which is what made Ξ indefinite last time).
        assert (d > 0).all(), (
            "D is not positive — some blob is smaller than a bead it contains"
        )
        np.linalg.cholesky(C)

        # Ξ = D + AᵀCA, assembled straight from the operator (never inverting anything).
        Xi = np.column_stack(
            [
                d * e + fric._gather(C @ fric._scatter(e))
                for e in np.eye(6 * fric.n_nodes)
            ]
        )
        assert np.allclose(Xi, Xi.T, atol=1e-12)
        assert np.linalg.eigvalsh(Xi).min() > 0, (
            f"Ξ not SPD (generalized={generalized})"
        )

        # …and every node's self-drag is its OWN species', exactly. This is the identity that lets C
        # be a single-radius RPY: the species-dependent part of the drag lives entirely in D.
        assert np.allclose(np.diag(Xi).reshape(fric.n_nodes, 6), want, rtol=1e-12)


def test_ss3_the_memory_guard_counts_the_real_blobs():
    """B is not ⌈N/k⌉: blobs never straddle a helix and every tail is chunked on its own, so the
    naive count UNDERSTATES the friction's only dense object (6B×6B) — the wrong way for a guard
    that exists to stop the OOM killer taking the user's editor."""
    from backend.physics.snupi_hydro_coarse import blob_count
    from backend.physics.snupi_hydrodynamics import estimate_friction_memory_gb

    # 20 core bp (one helix → 3 blobs of ≤8) + a 3-nt tail (1 blob of its own) = 4 blobs, where
    # ⌈23/8⌉ would have said 3.
    _d, mesh, block = _tail_mesh_and_block(3)
    nb = blob_count(mesh, 8, block)
    n = block.n_total
    assert nb > -(-n // 8), (
        "the fixture should fragment — otherwise this test proves nothing"
    )
    assert estimate_friction_memory_gb(n, 8, nb) > estimate_friction_memory_gb(n, 8)
    assert estimate_friction_memory_gb(n, 8, nb) < estimate_friction_memory_gb(
        n
    )  # ≪ exact


def test_ss3_hydrodynamics_with_tails_requires_the_coarse_blob_model():
    """The exact per-bp friction is single-radius; giving the tails their smaller bead radius there
    would need an unequal-radius RPY tensor (Zuk 2014) with its own overlap regularizations. Refuse,
    rather than silently drop the tails' drag."""
    from backend.physics.snupi_dynamics import simulate_equilibrium

    with pytest.raises(ValueError, match="coarse"):
        simulate_equilibrium(
            _tail_design(16),
            material="snupi",
            tails=True,
            hydrodynamics=True,
            hydro_coarse_bp=None,
            n_steps=1,
        )


def test_ss3_a_tails_and_hydro_run_drives_the_coarse_friction():
    import numpy as np

    from backend.physics.snupi_dynamics import simulate_equilibrium

    out = simulate_equilibrium(
        _tail_design(16),
        material="snupi",
        tails=True,
        hydrodynamics=True,
        hydro_coarse_bp=8,
        n_steps=400,
        n_equil=100,
        sample_every=50,
        seed=0,
    )
    assert out["friction"] == "rpy-coarse8"
    assert out["n_tail_nodes"] == 16
    assert out["tail_frames"].shape[1] == 16
    assert np.isfinite(out["tail_frames"]).all()
    # the core observables stay strictly core-only (decision 1 / the VoltronCore DISPLAY fix)
    assert out["frames"].shape[1] == len(out["helix_ids"]) == out["rmsf"].size


# ── 7. SS-3: the initial conformation (a coil, not a rod) ────────────────────────


def test_ss3_a_tail_starts_at_the_wlc_size_not_fully_extended():
    """SS-2 laid every tail out STRAIGHT and reasoned the pose would not survive equilibration.
    It does: collapsing a rod into a coil IS the slow long-wavelength mode that SS-2's own finding 3
    established MD cannot converge. A 16-mer starts as a 10.9 nm rod (⟨R²⟩ = 118 nm² against the WLC's
    13.7) and 4000 steps move it to 101. Started as a rod it STAYS a rod — so start it at equilibrium.
    """
    import numpy as np

    from backend.physics.snupi_tails import build_tail_block, wlc_mean_square_end_to_end

    for n_nt in (8, 16, 28):
        design = _tail_design(n_nt)
        mesh = build_fem_mesh(design, material="snupi")
        X0core = np.array([nd.position for nd in mesh.nodes])
        r2, rod2 = [], []
        for seed in range(40):
            coil = build_tail_block(design, mesh, seed=seed)
            rod = build_tail_block(design, mesh, seed=seed, coil=False)
            a = X0core[coil.anchors[0]]
            r2.append(float(((coil.positions[-1] - a) ** 2).sum()))
            rod2.append(float(((rod.positions[-1] - a) ** 2).sum()))
        want = wlc_mean_square_end_to_end(n_nt)
        assert np.mean(r2) == pytest.approx(want, rel=0.20), (
            f"{n_nt}-nt tail starts at ⟨R²⟩ = {np.mean(r2):.1f} nm², WLC says {want:.1f}"
        )
        assert np.mean(rod2) > 4 * want, (
            "the straight control should be wildly over-extended"
        )


def test_ss3_coiling_preserves_every_bond_length_exactly():
    """The coil is built by RIGID pivots — rotate everything beyond bead k about bead k. A rigid
    rotation preserves distance, so every bond stays at the ssDNA rest length and the chain still
    enters the trajectory with ZERO stretch energy, exactly as the straight layout did."""
    import numpy as np

    from backend.physics.snupi_material import SS_CONTOUR_PER_NT
    from backend.physics.snupi_tails import build_tail_block

    design = _tail_design(28)
    mesh = build_fem_mesh(design, material="snupi")
    X0core = np.array([nd.position for nd in mesh.nodes])
    for seed in range(20):
        block = build_tail_block(design, mesh, seed=seed)
        P = np.vstack([X0core[block.anchors[0]], block.positions])
        bonds = np.linalg.norm(np.diff(P, axis=0), axis=1)
        assert np.allclose(bonds, SS_CONTOUR_PER_NT, atol=1e-12)


def test_ss3_the_coil_must_carry_its_triads_or_the_bend_error_accumulates():
    """The elements' rest state is the STRAIGHT chain, so a coiled chain whose triads were left at
    the identity reads as bent by the angle between each bond and the REST direction — an error that
    accumulates down the chain (bond 20 can point 120° away) rather than staying local. Hence
    ``TailBlock.q0``: the bead triads the rigid pivots produced. With them the chain carries a local,
    thermal-sized bend per element; without them it starts several times hotter, and worse the longer
    it is."""
    import numpy as np

    from backend.physics import snupi_corotational as cr
    from backend.physics.snupi_dynamics import KBT_300
    from backend.physics.snupi_tails import build_tail_block

    def energy_per_element(block, X0core, q):
        X0 = np.vstack([X0core, block.positions])
        qn = q.reshape(len(X0), 6)
        X = X0 + qn[:, :3]
        R = [cr.exp_so3(qn[i, 3:6]) for i in range(len(X0))]
        U = 0.0
        for i, j, ref, K12 in block.elements:
            E, _ = cr._cr_frame(X[i], X[j], R[i], R[j])
            d = cr._local_defo(X[i], X[j], R[i], R[j], ref, E)
            U += 0.5 * float(d @ K12 @ d)
        return U / len(block.elements) / KBT_300

    naive = {}
    for n_nt in (3, 28):
        design = _tail_design(n_nt)
        mesh = build_fem_mesh(design, material="snupi")
        X0core = np.array([nd.position for nd in mesh.nodes])
        with_q0, without = [], []
        for seed in range(20):
            block = build_tail_block(design, mesh, seed=seed)
            q = np.zeros(6 * block.n_total)
            q[6 * block.n_bp :] = block.q0
            with_q0.append(energy_per_element(block, X0core, q))
            without.append(
                energy_per_element(block, X0core, np.zeros(6 * block.n_total))
            )
            # the rest state really is the straight chain: zero energy there
            rod = build_tail_block(design, mesh, seed=seed, coil=False)
            assert energy_per_element(
                rod, X0core, np.zeros(6 * rod.n_total)
            ) == pytest.approx(0.0, abs=1e-9)
        assert np.mean(with_q0) < 3.5, (
            "a thermal coil should cost only a few kT per element"
        )
        assert np.mean(without) > 2 * np.mean(with_q0), (
            "dropping the triads must hurt, and it does"
        )
        naive[n_nt] = np.mean(without)
    assert naive[28] > naive[3], (
        "the identity-triad error ACCUMULATES with chain length"
    )


# ── 7. SS-4: the simulated tails reach the DISPLAY ────────────────────────────────
#
# The figure payoff. Two things have to hold at once and they pull against each other:
# the tail beads must be EMITTED at their simulated positions (else the overhangs stand
# frozen at their rendered pose while the core breathes), and they must stay OUT of the
# Kabsch fit (a floppy coil in the fit is exactly the bug the VoltronCore DISPLAY fix had
# to undo — misplaced beads skewed the whole-structure superposition into a phantom 7.6 nm
# duplex offset). Both are pinned below, plus the payload plumbing end-to-end.


def _tail_node_dicts(block):
    """The ``tail_nodes`` metadata list, exactly as ``simulate_equilibrium`` returns it."""
    return [
        {
            "helix_id": nd.helix_id,
            "bp_index": nd.bp,
            "direction": nd.direction,
            "run": nd.run,
            "index_in_run": nd.index_in_run,
            "overhang_ids": list(nd.overhang_ids),
        }
        for nd in block.nodes
    ]


def test_ss4_the_display_still_omits_tail_beads_that_were_not_simulated():
    """The default is unchanged: no tail data → no tail beads, so the renderer keeps them at
    their rendered ball-joint pose (the VoltronCore DISPLAY fix, project_snupi_gaps)."""
    import numpy as np

    from backend.physics.fem_solver import deformed_positions_with_axis

    design = _tail_design(16)
    mesh = build_fem_mesh(design, material="snupi")
    pos, _axis = deformed_positions_with_axis(
        design, mesh, np.zeros(6 * len(mesh.nodes))
    )

    assert pos, "the duplex core must still be emitted"
    assert not [p for p in pos if p["helix_id"] == "B"], (
        "an unsimulated tail bead was emitted"
    )


def test_ss4_simulated_tail_beads_are_emitted_without_moving_the_core():
    """Every tail bead comes back keyed to its render bead — and the duplex core comes back
    byte-identical, because the Kabsch fit is still computed on the core alone."""
    import numpy as np

    from backend.physics.fem_solver import deformed_positions_with_axis
    from backend.physics.snupi_tails import build_tail_block

    design = _tail_design(16)
    mesh = build_fem_mesh(design, material="snupi")
    block = build_tail_block(design, mesh, seed=3)
    u = np.zeros(6 * len(mesh.nodes))

    core_only, _ = deformed_positions_with_axis(design, mesh, u)
    with_tails, _ = deformed_positions_with_axis(
        design,
        mesh,
        u,
        tail_positions=block.positions,
        tail_nodes=_tail_node_dicts(block),
    )

    assert with_tails[: len(core_only)] == core_only, (
        "emitting tails perturbed the duplex core"
    )

    tail_beads = with_tails[len(core_only) :]
    assert len(tail_beads) == block.n_tail == 16
    assert [(p["helix_id"], p["bp_index"], p["direction"]) for p in tail_beads] == [
        (nd.helix_id, nd.bp, nd.direction) for nd in block.nodes
    ]
    assert all(p["copy"] == 0 for p in tail_beads)  # no loop copies in this fixture
    # the slab frame is finite and orthonormal-ish (normal ⊥ chain tangent), not a degenerate zero
    for p in tail_beads:
        n = np.array([p["nx"], p["ny"], p["nz"]])
        t = np.array([p["tx"], p["ty"], p["tz"]])
        assert np.isclose(np.linalg.norm(n), 1.0, atol=1e-6)
        assert abs(float(n @ t)) < 1e-6


def test_ss4_a_tail_bead_never_enters_the_kabsch_fit():
    """The load-bearing one. A tail is a thermal coil sitting nowhere near its rendered pose; if it
    reached the superposition it would drag the whole structure off (the phantom 7.6 nm duplex
    offset). Shove the tails 1000 nm away and the core must not move by so much as a float."""
    import numpy as np

    from backend.physics.fem_solver import deformed_positions_with_axis
    from backend.physics.snupi_tails import build_tail_block

    design = _tail_design(16)
    mesh = build_fem_mesh(design, material="snupi")
    block = build_tail_block(design, mesh, seed=3)
    u = np.zeros(6 * len(mesh.nodes))
    nodes = _tail_node_dicts(block)

    core_only, axis_only = deformed_positions_with_axis(design, mesh, u)
    absurd, axis_absurd = deformed_positions_with_axis(
        design, mesh, u, tail_positions=block.positions + 1000.0, tail_nodes=nodes
    )

    assert absurd[: len(core_only)] == core_only
    assert axis_absurd == axis_only  # the cylinder rep is core-only too


def test_ss4_the_emitted_tail_is_still_a_chain():
    """The display transform is rigid, so the chain arrives with its bonds intact — an emitted tail
    is a real ssDNA chain at the contour bond length, not a smear."""
    import numpy as np

    from backend.physics.fem_solver import deformed_positions_with_axis
    from backend.physics.snupi_material import SS_CONTOUR_PER_NT
    from backend.physics.snupi_tails import build_tail_block

    design = _tail_design(16)
    mesh = build_fem_mesh(design, material="snupi")
    block = build_tail_block(design, mesh, seed=7)
    pos, _ = deformed_positions_with_axis(
        design,
        mesh,
        np.zeros(6 * len(mesh.nodes)),
        tail_positions=block.positions,
        tail_nodes=_tail_node_dicts(block),
    )

    beads = np.array([p["backbone_position"] for p in pos if p["helix_id"] == "B"])
    bonds = np.linalg.norm(np.diff(beads, axis=0), axis=1)
    assert np.allclose(bonds, SS_CONTOUR_PER_NT, atol=1e-6)


def test_ss4_tails_are_refused_without_the_dynamics_engine():
    """Free tails exist only inside the Langevin engine (decision 1). Asking for them from the
    static solve is a mistake, and it must say so rather than silently drop them."""
    from backend.physics.fem_solver import predict_shape

    design = _tail_design(16)
    with pytest.raises(ValueError, match="requires dynamics"):
        predict_shape(design, material="snupi", tails=True, with_rmsf=False)


def test_ss4_a_dynamics_job_with_tails_carries_them_into_positions_and_every_frame():
    """End-to-end through the real payload: predict_shape → the display list AND the trajectory
    player's frames both carry the tail beads.

    Also pins the mean-shape choice: the tails in ``positions`` are an actual equilibrium
    CONFORMATION, not the time-mean of the beads. Averaging a freely-fluctuating chain over its
    conformations shrinks it toward its anchor — the mean of a coil is not a coil — so a mean-of-
    beads payload would show every overhang as a collapsed stub with sub-bond-length bonds. Here
    the bonds must still be ssDNA bonds.
    """
    import numpy as np

    from backend.physics.fem_solver import predict_shape
    from backend.physics.snupi_material import SS_CONTOUR_PER_NT

    design = _tail_design(16)
    res = predict_shape(
        design,
        material="snupi",
        dynamics=True,
        tails=True,
        dynamics_steps=400,
        with_rmsf=False,
    )

    assert res["solver"].endswith("+tails")
    assert res["n_tail_nodes"] == 16

    tail_beads = [p for p in res["positions"] if p["helix_id"] == "B"]
    assert len(tail_beads) == 16, "the simulated tail never reached the display payload"
    beads = np.array([p["backbone_position"] for p in tail_beads])
    bonds = np.linalg.norm(np.diff(beads, axis=0), axis=1)
    # a real conformation: bonds within a few % of the contour length (a collapsed time-mean
    # would be far shorter, and the whole tail would span a fraction of its size)
    assert bonds.mean() == pytest.approx(SS_CONTOUR_PER_NT, rel=0.1)

    traj = res["trajectory"]
    keys = [tuple(k[:3]) for k in traj["keys"]]
    assert sum(1 for k in keys if k[0] == "B") == 16, (
        "the trajectory frames drop the tails"
    )
    assert all(len(f) == 6 * len(traj["keys"]) for f in traj["frames"])
    # and the tails actually MOVE between frames (the whole point of the phase)
    tail_cols = [i for i, k in enumerate(keys) if k[0] == "B"]
    f0 = np.array(traj["frames"][0]).reshape(len(keys), 6)[tail_cols, :3]
    f1 = np.array(traj["frames"][-1]).reshape(len(keys), 6)[tail_cols, :3]
    assert np.abs(f1 - f0).max() > 1e-3, (
        "the tail beads are frozen across the trajectory"
    )


def test_ss4_the_job_layer_carries_the_tail_flags(tmp_path):
    """The flags reach the worker: a persisted job round-trips them, an OLD job.json without them
    still loads, and the stage label names them (a tails run costs ~2× the per-step force)."""
    from backend.core.snupi_job import SnupiJob, new_snupi_job

    job = new_snupi_job("d", dynamics=True, tails=True, tail_max_nt=12)
    assert job.stages[0].name == "dynamics+tails"
    job.save(tmp_path)
    back = SnupiJob.load(job.job_id, tmp_path)
    assert (back.tails, back.tail_max_nt) == (True, 12)

    plain = new_snupi_job("d")  # the default is unchanged
    assert (plain.tails, plain.tail_max_nt) == (False, None)


# ── 8. The anchor is not always the 5' end (the OH15 bug) ─────────────────────────
#
# A tail's anchor is whichever end crosses back into the embedded staple — NOT a fixed
# polarity (the user's rule, pinned for the CLASSIFIER since SS-0). But `build_tail_block`
# chained every tail from `nts[0]`, i.e. from its 5' end, which is only the anchor when the
# overhang sits at the strand's 3' terminus. For a 5'-terminal overhang the chain got bonded
# to the anchor by its FREE TIP, and the nucleotide covalently continuous with the staple was
# flung to the far end of the coil — a backbone bond stretched by the tail's whole end-to-end
# distance. Found on VoltronCore (user): OH3 (3'-terminal, fine) sat next to OH15 (5'-terminal,
# broken) on one helix, and OH15's anchor bond read 3.78 nm against OH3's 0.40. 24 of that
# design's 55 tails were 3'-anchored, worst bond 8.18 nm on a 28-mer — the error IS the coil
# span, so it grows with tail length. Every SS-2/SS-3 fixture happened to be 5'-anchored, which
# is exactly why this survived; both polarities are pinned from here on.


def _tail_design_5p_terminal(n_tail_nt: int = 16):
    """The MIRROR of `_tail_design`: the overhang is the staple's FIRST domain, so the run sits at
    the strand's 5' terminus and its anchor is on its 3' side (`anchor_3`)."""
    hi = 39
    lo = hi - n_tail_nt + 1
    return _two_helix_design(
        [
            [
                _dom("B", lo, hi, Direction.REVERSE, overhang_id="oh1"),
                _dom("A", 0, 19, Direction.REVERSE),
            ]
        ],
        scaffold_domains=[_dom("A", 0, 19)],
    )


def test_the_fixture_pair_really_does_cover_both_anchor_polarities():
    """Guard the guard: if both fixtures drifted to the same polarity, the tests below would pass
    while proving nothing — which is how the bug survived SS-2 and SS-3."""
    a = [r for r in classify_ssdna_runs(_tail_design(16)) if r.kind == "tail"]
    b = [
        r for r in classify_ssdna_runs(_tail_design_5p_terminal(16)) if r.kind == "tail"
    ]
    assert len(a) == len(b) == 1
    assert a[0].anchor_5 is not None and a[0].anchor_3 is None  # 3'-terminal overhang
    assert b[0].anchor_3 is not None and b[0].anchor_5 is None  # 5'-terminal overhang


@pytest.mark.parametrize(
    "design_fn", [_tail_design, _tail_design_5p_terminal], ids=["anchor_5", "anchor_3"]
)
def test_a_tail_chain_hangs_from_its_anchor_by_the_nucleotide_that_adjoins_it(
    design_fn,
):
    """The chain is built ANCHOR-OUTWARD in both polarities: bead 0 is the nucleotide covalently
    continuous with the anchor, and it is one ssDNA bond away from it — not a coil span."""
    import numpy as np

    from backend.physics.snupi_material import SS_CONTOUR_PER_NT
    from backend.physics.snupi_tails import build_tail_block

    design = design_fn(16)
    mesh = build_fem_mesh(design, material="snupi")
    run = next(r for r in classify_ssdna_runs(design) if r.kind == "tail")
    block = build_tail_block(
        design, mesh, coil=False
    )  # rod: isolate the topology from the coil

    # the nucleotide that adjoins the anchor along the strand path
    adjoining = run.nts[0] if run.anchor_5 else run.nts[-1]
    b0 = block.nodes[0]
    assert (b0.helix_id, b0.bp, b0.direction) == adjoining, (
        "the chain hangs from the wrong end"
    )
    assert block.nodes[-1] != b0
    tip = run.nts[-1] if run.anchor_5 else run.nts[0]
    bl = block.nodes[-1]
    assert (bl.helix_id, bl.bp, bl.direction) == tip, (
        "the free tip is not at the end of the chain"
    )

    # and the first element really joins the anchor node to that bead, one bond long
    a_idx = block.anchors[0]
    assert block.elements[0][0] == a_idx
    d = np.linalg.norm(block.positions[0] - mesh.nodes[a_idx].position)
    assert d == pytest.approx(SS_CONTOUR_PER_NT, abs=1e-6)


@pytest.mark.parametrize(
    "design_fn", [_tail_design, _tail_design_5p_terminal], ids=["anchor_5", "anchor_3"]
)
def test_the_drawn_bond_from_an_overhang_to_its_anchor_is_never_overstretched(
    design_fn,
):
    """The user-visible symptom, pinned in the DISPLAY payload: the backbone bond drawn between the
    anchor's bead and the overhang nucleotide continuous with it must be a bond, not a coil span.
    Pre-fix this read 3.78 nm on VoltronCore's OH15 (and 8.18 nm on a 28-mer)."""
    import numpy as np

    from backend.physics.fem_solver import deformed_positions_with_axis
    from backend.physics.snupi_tails import build_tail_block

    design = design_fn(16)
    mesh = build_fem_mesh(design, material="snupi")
    block = build_tail_block(design, mesh, seed=1)
    run = next(r for r in classify_ssdna_runs(design) if r.kind == "tail")
    pos, _ = deformed_positions_with_axis(
        design,
        mesh,
        np.zeros(6 * len(mesh.nodes)),
        tail_positions=block.positions,
        tail_nodes=_tail_node_dicts(block),
    )
    P = {
        (p["helix_id"], p["bp_index"], p["direction"]): np.array(p["backbone_position"])
        for p in pos
    }

    adjoining = run.nts[0] if run.anchor_5 else run.nts[-1]
    anchor = run.anchor
    # the anchor's own nucleotide on this strand — same direction as the overhang domain here
    a_key = (anchor.helix_id, anchor.bp, "REVERSE")
    bond = float(np.linalg.norm(P[a_key] - P[adjoining]))
    assert bond < 1.5, f"overhang→anchor bond is {bond:.2f} nm — overstretched"
