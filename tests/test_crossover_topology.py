"""Topology-only enumeration of crossover connectors and reciprocal pairs."""

from backend.core.junction_topology import crossover_connectors, reciprocal_pairs
from backend.core.lattice import make_bundle_design
from backend.core.models import Direction, Domain, Strand, StrandType
from tests.reciprocal_design import reciprocal_design


def test_connectors_enumerate_both_helix_hops():
    connectors = crossover_connectors(reciprocal_design("T"))
    assert len(connectors) == 2
    assert {connector.n_inserts for connector in connectors} == {1}
    assert connectors[0].from_helix != connectors[1].from_helix


def test_reciprocal_pair_is_identified():
    assert reciprocal_pairs(crossover_connectors(reciprocal_design("T"))) == [(0, 1)]


def test_parallel_crossovers_are_not_reciprocal():
    base = make_bundle_design(cells=[(0, 0), (0, 1)], length_bp=21, plane="XY")
    h0, h1 = base.helices[0].id, base.helices[1].id
    strands = [
        Strand(
            id="s1",
            strand_type=StrandType.STAPLE,
            domains=[
                Domain(
                    helix_id=h0,
                    start_bp=3,
                    end_bp=10,
                    direction=Direction.FORWARD,
                ),
                Domain(
                    helix_id=h1,
                    start_bp=10,
                    end_bp=17,
                    direction=Direction.FORWARD,
                ),
            ],
        ),
        Strand(
            id="s2",
            strand_type=StrandType.STAPLE,
            domains=[
                Domain(
                    helix_id=h0,
                    start_bp=0,
                    end_bp=11,
                    direction=Direction.FORWARD,
                ),
                Domain(
                    helix_id=h1,
                    start_bp=11,
                    end_bp=18,
                    direction=Direction.FORWARD,
                ),
            ],
        ),
    ]
    connectors = crossover_connectors(base.model_copy(update={"strands": strands}))
    assert len(connectors) == 2
    assert reciprocal_pairs(connectors) == []


def test_connector_without_extra_bases_has_no_inserts():
    connectors = crossover_connectors(reciprocal_design(None))
    assert {connector.n_inserts for connector in connectors} == {0}
