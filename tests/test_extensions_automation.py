"""Extensions (terminal sequence / fluorophore-quencher modification) — validation
+ automation coverage.

  * validate_design flags a bad extension (dangling strand / unknown modification /
    non-ACGTN sequence).
  * headless hb.add_strand_extension + assert_extension_present oracle pin the add.
"""

from __future__ import annotations

import pytest

from backend.api import state as design_state
from backend.api.routes import _demo_design
from backend.core.constants import BDNA_RISE_PER_BP
from backend.core.models import (
    Design,
    Direction,
    Domain,
    Helix,
    Strand,
    StrandExtension,
    StrandType,
    Vec3,
)
from backend.core.validator import validate_design


@pytest.fixture(autouse=True)
def _reset_state():
    yield
    design_state.set_design(_demo_design())


def _design_one_staple() -> Design:
    h = Helix(
        id="hA",
        axis_start=Vec3(x=0.0, y=0.0, z=0.0),
        axis_end=Vec3(x=0.0, y=0.0, z=16 * BDNA_RISE_PER_BP),
        phase_offset=0.0,
        length_bp=16,
        grid_pos=(0, 0),
    )
    st = Strand(
        id="st",
        strand_type=StrandType.STAPLE,
        sequence="ACGTACGTACGTACGT",
        domains=[
            Domain(helix_id="hA", start_bp=0, end_bp=15, direction=Direction.FORWARD)
        ],
    )
    return Design(helices=[h], strands=[st])


# ── validate_design ───────────────────────────────────────────────────────────


def test_valid_extension_not_flagged():
    d = _design_one_staple()
    d = d.model_copy(
        update={
            "extensions": [
                StrandExtension(strand_id="st", end="three_prime", modification="cy3"),
                StrandExtension(strand_id="st", end="five_prime", sequence="TTTT"),
            ]
        }
    )
    bad = [
        r.message
        for r in validate_design(d).results
        if not r.ok and "Strand extension" in r.message
    ]
    assert not bad


def test_validate_flags_dangling_strand_and_bad_sequence():
    d = _design_one_staple()
    # model_copy skips the route guard, so we can plant invalid states.
    d = d.model_copy(
        update={
            "extensions": [
                StrandExtension(
                    strand_id="ghost", end="three_prime", modification="cy3"
                ),
                StrandExtension(strand_id="st", end="five_prime", sequence="TTXZ"),
            ]
        }
    )
    msgs = [
        r.message
        for r in validate_design(d).results
        if not r.ok and "Strand extension" in r.message
    ]
    assert msgs and "does not exist" in msgs[0] and "non-ACGTN" in msgs[0]


# ── headless + oracle ─────────────────────────────────────────────────────────


def test_headless_add_extension_fluorophore_and_oracle():
    from backend.api import headless_build as hb
    from tests.automation_harness import assert_extension_present

    design_state.set_design(_design_one_staple())
    hb.add_strand_extension("st", "three_prime", modification="cy3", label="Cy3")
    ext = design_state.get_design().extensions[0]
    assert_extension_present(
        design_state.get_design(),
        ext.id,
        strand_id="st",
        end="three_prime",
        modification="cy3",
    )


def test_headless_add_extension_sequence():
    from backend.api import headless_build as hb
    from tests.automation_harness import assert_extension_present

    design_state.set_design(_design_one_staple())
    hb.add_strand_extension("st", "five_prime", sequence="TTTT")
    ext = design_state.get_design().extensions[0]
    assert_extension_present(
        design_state.get_design(),
        ext.id,
        strand_id="st",
        end="five_prime",
        sequence="TTTT",
    )
