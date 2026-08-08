from experiments.exp43_7bp_crossover_transition.run import (
    CONDITIONS,
    TOKEN,
    build_condition,
)


def test_exp43_token_and_conditions_are_matched():
    assert TOKEN == {"start_bp": 7, "end_bp_exclusive": 14, "length_bp": 7}
    assert CONDITIONS["no_crossover"] == set()
    assert CONDITIONS["left_crossover"] == {7}
    assert CONDITIONS["bracketed_crossovers"] == {7, 14}


def test_exp43_builds_exact_crossover_topologies():
    for name, expected in CONDITIONS.items():
        design = build_condition(name)
        actual = {int(x.half_a.index) for x in design.crossovers}
        assert actual == expected
        assert len(design.helices) == 3
        assert all(s.sequence for s in design.strands)
