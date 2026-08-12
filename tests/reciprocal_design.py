"""Small reciprocal-crossover design shared by atomistic geometry tests."""

from backend.core.lattice import make_bundle_design
from backend.core.models import (
    Crossover,
    Direction,
    Domain,
    HalfCrossover,
    Strand,
    StrandType,
)


def reciprocal_design(extra_bases: str | None, bp: int = 16, length_bp: int = 28):
    """Return two helices joined by an antiparallel reciprocal crossover pair."""
    base = make_bundle_design(cells=[(0, 0), (0, 1)], length_bp=length_bp, plane="XY")
    h0, h1 = base.helices[0].id, base.helices[1].id
    strand_a = Strand(
        id="stpl_a",
        strand_type=StrandType.STAPLE,
        domains=[
            Domain(
                helix_id=h0,
                start_bp=bp - 7,
                end_bp=bp,
                direction=Direction.FORWARD,
            ),
            Domain(
                helix_id=h1,
                start_bp=bp,
                end_bp=bp - 7,
                direction=Direction.REVERSE,
            ),
        ],
    )
    strand_b = Strand(
        id="stpl_b",
        strand_type=StrandType.STAPLE,
        domains=[
            Domain(
                helix_id=h1,
                start_bp=bp + 8,
                end_bp=bp + 1,
                direction=Direction.REVERSE,
            ),
            Domain(
                helix_id=h0,
                start_bp=bp + 1,
                end_bp=bp + 8,
                direction=Direction.FORWARD,
            ),
        ],
    )
    crossovers = [
        Crossover(
            id="xo_a",
            half_a=HalfCrossover(helix_id=h0, index=bp, strand=Direction.FORWARD),
            half_b=HalfCrossover(helix_id=h1, index=bp, strand=Direction.REVERSE),
            extra_bases=extra_bases,
        ),
        Crossover(
            id="xo_b",
            half_a=HalfCrossover(helix_id=h0, index=bp + 1, strand=Direction.FORWARD),
            half_b=HalfCrossover(helix_id=h1, index=bp + 1, strand=Direction.REVERSE),
            extra_bases=extra_bases,
        ),
    ]
    return base.model_copy(
        update={"strands": [strand_a, strand_b], "crossovers": crossovers}
    )
