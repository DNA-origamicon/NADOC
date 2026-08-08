"""Phase 4b — validation + automation coverage for the Duplex graph.

  * `validate_design` surfaces a zero-complementary (non-pairing) duplex.
  * headless `hb.connect_duplex` + harness `assert_duplex_relocated` oracle pin the
    different-length relocation without the HTTP layer.
See `memory/project_overhang_duplex_foundation.md`.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from backend.api import state as design_state
from backend.api.routes import _demo_design
from backend.core.constants import BDNA_RISE_PER_BP
from backend.core.models import (
    Design,
    Direction,
    Domain,
    Duplex,
    DuplexEnd,
    Helix,
    OverhangSpec,
    Strand,
    StrandType,
    SubDomain,
    Vec3,
)
from backend.core.validator import validate_design

_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "relax_2x2_binding.nadoc"


@pytest.fixture(autouse=True)
def _reset_state():
    yield
    design_state.set_design(_demo_design())


# ── validate_design: zero-complementary duplex is flagged ─────────────────────


def test_validate_design_flags_non_pairing_duplex():
    sa = Strand(
        id="sa",
        strand_type=StrandType.STAPLE,
        domains=[
            Domain(
                helix_id="hA",
                start_bp=0,
                end_bp=3,
                direction=Direction.FORWARD,
                overhang_id="ohA",
            )
        ],
    )
    sb = Strand(
        id="sb",
        strand_type=StrandType.STAPLE,
        domains=[
            Domain(
                helix_id="hB",
                start_bp=3,
                end_bp=0,
                direction=Direction.REVERSE,
                overhang_id="ohB",
            )
        ],
    )
    # A=AAAA, B=AAAA → RC(AAAA)=TTTT ≠ AAAA → every position mismatches.
    ohA = OverhangSpec(id="ohA", helix_id="hA", strand_id="sa", sequence="AAAA")
    ohB = OverhangSpec(id="ohB", helix_id="hB", strand_id="sb", sequence="AAAA")
    dx = Duplex(
        left=DuplexEnd(overhang_id="ohA", start_bp=0, end_bp=3),
        right=DuplexEnd(overhang_id="ohB", start_bp=3, end_bp=0),
    )
    design = Design(strands=[sa, sb], overhangs=[ohA, ohB], duplexes=[dx])
    msgs = [
        r.message
        for r in validate_design(design).results
        if not r.ok and "no complementary bases" in r.message
    ]
    assert msgs, "validate_design should flag the non-pairing duplex"


def test_validate_design_does_not_flag_all_N_or_complementary():
    sa = Strand(
        id="sa",
        strand_type=StrandType.STAPLE,
        domains=[
            Domain(
                helix_id="hA",
                start_bp=0,
                end_bp=3,
                direction=Direction.FORWARD,
                overhang_id="ohA",
            )
        ],
    )
    sb = Strand(
        id="sb",
        strand_type=StrandType.STAPLE,
        domains=[
            Domain(
                helix_id="hB",
                start_bp=3,
                end_bp=0,
                direction=Direction.REVERSE,
                overhang_id="ohB",
            )
        ],
    )
    ohA = OverhangSpec(id="ohA", helix_id="hA", strand_id="sa", sequence="AAAC")
    ohB = OverhangSpec(
        id="ohB", helix_id="hB", strand_id="sb", sequence="GTTT"
    )  # RC(AAAC)
    dx = Duplex(
        left=DuplexEnd(overhang_id="ohA", start_bp=0, end_bp=3),
        right=DuplexEnd(overhang_id="ohB", start_bp=3, end_bp=0),
    )
    design = Design(strands=[sa, sb], overhangs=[ohA, ohB], duplexes=[dx])
    msgs = [
        r.message
        for r in validate_design(design).results
        if not r.ok and "no complementary bases" in r.message
    ]
    assert not msgs, "a fully complementary duplex must not be flagged"


# ── headless hb.connect_duplex + assert_duplex_relocated oracle ───────────────


def _helix(hid, length):
    return Helix(
        id=hid,
        axis_start=Vec3(x=0.0, y=0.0, z=0.0),
        axis_end=Vec3(x=0.0, y=0.0, z=length * BDNA_RISE_PER_BP),
        phase_offset=0.0,
        length_bp=length,
        grid_pos=(0, 0),
    )


def _diff_length_design() -> Design:
    st_drv = Strand(
        id="st_drv",
        strand_type=StrandType.STAPLE,
        domains=[
            Domain(
                helix_id="h_drv",
                start_bp=0,
                end_bp=23,
                direction=Direction.FORWARD,
                overhang_id="OHd",
            )
        ],
    )
    st_drvn = Strand(
        id="st_drvn",
        strand_type=StrandType.STAPLE,
        domains=[
            Domain(
                helix_id="h_drvn",
                start_bp=0,
                end_bp=9,
                direction=Direction.FORWARD,
                overhang_id="OHn",
            )
        ],
    )
    ohd = OverhangSpec(
        id="OHd",
        helix_id="h_drv",
        strand_id="st_drv",
        sequence="A" * 24,
        sub_domains=[SubDomain(id="sdd", start_bp_offset=0, length_bp=24)],
    )
    ohn = OverhangSpec(
        id="OHn",
        helix_id="h_drvn",
        strand_id="st_drvn",
        sequence="T" * 10,
        sub_domains=[SubDomain(id="sdn", start_bp_offset=0, length_bp=10)],
    )
    return Design(
        helices=[_helix("h_drv", 24), _helix("h_drvn", 10)],
        strands=[st_drv, st_drvn],
        overhangs=[ohd, ohn],
    )


def test_headless_connect_duplex_relocates_driven():
    from backend.api import headless_build as hb
    from tests.automation_harness import assert_duplex_relocated

    design_state.set_design(_diff_length_design())
    hb.connect_duplex("OHd", "OHn", overhang_a_attach="root", overhang_b_attach="root")
    # Oracle: driven (10 bp) relocated onto the driver's helix keeping its length.
    assert_duplex_relocated(
        design_state.get_design(),
        driver_oh_id="OHd",
        driven_oh_id="OHn",
        driven_length_bp=10,
    )


# ── headless hb.relax_duplex + assert_duplex_relaxed oracle ───────────────────


def _fixture_bound_duplex_design() -> tuple[Design, str]:
    """Frozen 2x2 design with its display duplex marked bound (the relocation already
    exists, shared with the binding) so the duplex route can drive the shared solve."""
    d = Design.model_validate(json.loads(_FIXTURE.read_text()))
    dx = d.duplexes[0].model_copy(update={"bound": True})
    return d.model_copy(update={"duplexes": [dx]}), dx.id


@pytest.mark.skipif(
    not _FIXTURE.exists(), reason="relax_2x2_binding.nadoc fixture missing"
)
def test_headless_relax_duplex_closes_bond_and_oracle():
    """hb.relax_duplex on a bound duplex closes the driven overhang's stretched
    tip↔root bond (pose-only) — pinned by assert_duplex_relaxed. Start from a
    neutralised pose so there's a real ~7 nm bond to close (require_reduced)."""
    from backend.api import headless_build as hb
    from tests.automation_harness import assert_duplex_relaxed

    before, dxid = _fixture_bound_duplex_design()
    # Neutralise the stored pose so the bond is genuinely stretched pre-relax.
    c2 = before.cluster_transforms[1].model_copy(
        update={"rotation": [0, 0, 0, 1.0], "translation": [0, 0, 0.0]}
    )
    ohs = [
        o.model_copy(update={"rotation": [0, 0, 0, 1.0]})
        if o.id == before.duplexes[0].left.overhang_id
        else o
        for o in before.overhangs
    ]
    before = before.model_copy(
        update={
            "cluster_transforms": [before.cluster_transforms[0], c2],
            "overhangs": ohs,
        }
    )
    design_state.set_design(before)

    after = hb.relax_duplex(dxid)
    # Oracle: chord closed + a pose moved + topology unchanged (can-go-red on a no-op).
    assert_duplex_relaxed(before, after, dxid)


@pytest.mark.skipif(
    not _FIXTURE.exists(), reason="relax_2x2_binding.nadoc fixture missing"
)
def test_headless_relax_duplex_is_idempotent():
    """The bridge-method relax is idempotent in its FINAL pose: after one relax, a second
    relax reproduces the same driven-cluster transform (arc-min already at target; the
    duplex clash spin re-derives the same absolute angle), so nothing drifts."""
    from backend.api import headless_build as hb

    before, dxid = _fixture_bound_duplex_design()
    design_state.set_design(before)
    once = hb.relax_duplex(dxid)
    design_state.set_design(once)
    twice = hb.relax_duplex(dxid)

    def cluster_pose(d):
        c = d.cluster_transforms[1]
        return np.asarray(list(c.rotation) + list(c.translation), dtype=float)

    assert float(np.linalg.norm(cluster_pose(twice) - cluster_pose(once))) < 1e-2
