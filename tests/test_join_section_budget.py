"""Join sizing estimates include square skips on continuous crossbars."""

from pathlib import Path

import numpy as np
import pytest

from backend.core.curved_rod_generator import physical_scaffold_nt
from backend.core.generated_sweep import encode_sweep
from backend.core.join_branch_layouts import join_branch_layouts
from backend.core.join_crossbars import crossbar_summary
from backend.core.joined_branches import _section_route_stats, joined_seed
from backend.core.models import Design, LatticeType
from backend.core.seamed_router import auto_scaffold_seamed_bounded
from backend.core.two_np_generator import scaffold_nt


@pytest.mark.parametrize("lattice", [LatticeType.SQUARE, LatticeType.HONEYCOMB])
@pytest.mark.parametrize("tail_bp", [7, 21])
def test_section_budget_matches_encoded_straight_crossbar(lattice, tail_bp):
    source = Design.model_validate_json(
        (Path(__file__).parent / "fixtures/4np_gen_aligned.json").read_text()
    ).copy_with(lattice_type=lattice)
    centers = np.array([p.pose.to_array()[:3, 3] for p in source.nanoparticles])
    # Midpoint junctions produce straight crossbars with the same sweep encoding
    # as curved candidates, isolating the lattice correction from bend demand.
    summary = crossbar_summary(
        source, centers, join_branch_layouts(centers)[1], 12, 12, tail_bp=tail_bp
    )
    spec = summary["join_sections"][1]
    seed = joined_seed(lattice, summary)
    ids = set(seed.cluster_transforms[1].helix_ids)
    part = Design(
        lattice_type=lattice,
        helices=[h for h in seed.helices if h.id in ids],
        strands=[s for s in seed.strands if all(d.helix_id in ids for d in s.domains)],
        deformations=[op for op in seed.deformations if set(op.affected_helix_ids) <= ids],
    )
    routed, result = auto_scaffold_seamed_bounded(part)
    assert result.valid
    encoded = encode_sweep(routed)
    cells = tuple(map(tuple, spec["cells"]))
    raw_estimate = _section_route_stats(lattice, cells, spec["length_bp"])
    physical_estimate = _section_route_stats(
        lattice, cells, spec["length_bp"], encoded=True
    )
    assert raw_estimate[0] == scaffold_nt(routed)
    assert physical_estimate[0] == physical_scaffold_nt(encoded)
    assert physical_estimate[1:] == raw_estimate[1:]
    if lattice == LatticeType.SQUARE:
        assert physical_estimate[0] < raw_estimate[0]
        assert any(h.loop_skips for h in encoded.helices)
    else:
        assert physical_estimate == raw_estimate
