"""
Shared pytest fixtures and hooks.
"""


from backend.core.constants import BDNA_RISE_PER_BP
from backend.core.models import (
    Design,
    Direction,
    Domain,
    Helix,
    LatticeType,
    Strand,
    StrandType,
    Vec3,
)


def make_minimal_design(
    *,
    n_helices: int = 1,
    helix_length_bp: int = 42,
    lattice: LatticeType = LatticeType.HONEYCOMB,
    with_scaffold: bool = True,
    with_staple: bool = True,
) -> Design:
    """Minimal fixture: 1–2 honeycomb/square helices, optional scaffold + staple
    spanning a single domain each. Used by tests that need a valid Design but
    don't care about the topology specifics. Larger or bespoke designs should
    be built inline.
    """
    if n_helices not in (1, 2):
        raise ValueError("n_helices must be 1 or 2")

    helices = [
        Helix(
            id=f"h{i}",
            axis_start=Vec3(x=i * 2.5, y=0.0, z=0.0),
            axis_end=Vec3(x=i * 2.5, y=0.0, z=helix_length_bp * BDNA_RISE_PER_BP),
            length_bp=helix_length_bp,
            bp_start=0,
        )
        for i in range(n_helices)
    ]

    strands = []
    if with_scaffold:
        strands.append(Strand(
            id="scaf",
            strand_type=StrandType.SCAFFOLD,
            domains=[Domain(
                helix_id="h0",
                start_bp=0,
                end_bp=helix_length_bp - 1,
                direction=Direction.FORWARD,
            )],
        ))
    if with_staple:
        strands.append(Strand(
            id="stap",
            strand_type=StrandType.STAPLE,
            domains=[Domain(
                helix_id="h0",
                start_bp=0,
                end_bp=helix_length_bp - 1,
                direction=Direction.REVERSE,
            )],
        ))

    return Design(helices=helices, strands=strands, lattice_type=lattice)
