from backend.core.scaffold_sequence_cache import scaffold_base_entries


def test_scaffold_cache_tracks_sequence_traversal_modifications_and_reference_order():
    active = ('ACGT', (('h', 'FORWARD', (0, 1, 2)),))
    reference = ('TTTT', (('h', 'FORWARD', (0, 1, 2, 3)),))
    base = dict(scaffold_base_entries((active, reference), ()))
    assert base[('h', 0, 'FORWARD')] == ('A',)
    assert base[('h', 3, 'FORWARD')] == ('T',)
    changed = dict(scaffold_base_entries((('TGCA', active[1]), reference), ()))
    assert changed[('h', 0, 'FORWARD')] == ('T',)
    modified = dict(scaffold_base_entries((active,), ((('h', 0), 1), (('h', 1), -1))))
    assert modified == {('h', 0, 'FORWARD'): ('A', 'C'), ('h', 2, 'FORWARD'): ('G',)}
    reversed_order = dict(scaffold_base_entries((reference, active), ()))
    assert reversed_order[('h', 0, 'FORWARD')] == ('T',)
    reversed_path = dict(scaffold_base_entries((('ACG', (('h', 'REVERSE', (2, 1, 0)),)),), ()))
    assert reversed_path[('h', 2, 'REVERSE')] == ('A',)


def test_targeted_assignment_matches_full_derivation_without_touching_other_strands():
    from backend.api import headless_build as hb, state
    from backend.api.doc_context import set_current_doc, reset_current_doc
    from backend.core.sequences import assign_staple_sequences, build_scaffold_base_map
    token = set_current_doc('__test_targeted_sequence_assignment')
    try:
        hb.new_design()
        hb.create_bundle([[0, 1], [0, 2], [0, 3], [1, 1], [1, 2], [1, 3]], 42, lattice=hb.LatticeType.HONEYCOMB)
        hb.auto_scaffold(seamless=False)
        hb.auto_crossover()
        hb.auto_break()
        hb.assign_scaffold_sequence()
        design = state.get_or_404()
        full = assign_staple_sequences(design)
        wanted = {next(s.id for s in design.strands if not s.is_scaffold)}
        partial = assign_staple_sequences(design, strand_ids=wanted)
        for before, after, expected in zip(design.strands, partial.strands, full.strands, strict=True):
            assert after == (expected if before.id in wanted else before)
        first = build_scaffold_base_map(design)
        key = next(iter(first))
        expected = list(first[key])
        first[key].append('X')
        assert build_scaffold_base_map(design)[key] == expected
    finally:
        state.close_session()
        reset_current_doc(token)
