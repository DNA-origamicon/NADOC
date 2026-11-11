"""Compare an authored/reopened D003 part to the independent figure/table inputs."""

from tools.design_archive.d003_recipe import sequence_mapping, require


def audit_reconstruction(design, graph, rows, scaffold_sequence):
    scaffold, staples, mapping = sequence_mapping(graph, rows, scaffold_sequence)
    expected = {'M13mp18': scaffold, **{s['name']: s['walk'] for s in staples}}
    require(len(design.helices) == 88 and len(design.strands) == 211,
            'D003 helix/strand count changed')
    require(len({s.name for s in design.strands}) == 211, 'D003 strand names are not unique')
    labels = {h.id: h.grid_pos[0] for h in design.helices}
    require(set(labels.values()) == set(range(88)), 'D003 helix row mapping changed')
    ordered_helices = sorted(design.helices, key=lambda h: labels[h.id])
    require(all(abs(b.axis_start.y - a.axis_start.y - 3.0) < 1e-9
                for a, b in zip(ordered_helices, ordered_helices[1:])),
            'D003 must use the published 3 nm helix spacing')
    indels = {(h.id, m.bp_index): m.delta for h in design.helices for m in h.loop_skips}
    require({(labels[h], b): v for (h, b), v in indels.items()} == {
        (h['num'], b): v for h in graph['vstrands'] for b, v in enumerate(h['skip']) if v},
        'D003 drawn deletions changed')
    junctions = {}
    for xo in design.crossovers:
        a, b = xo.half_a, xo.half_b
        key = frozenset(((a.helix_id, a.index, a.strand.value), (b.helix_id, b.index, b.strand.value)))
        require(key not in junctions, 'Duplicate D003 junction')
        junctions[key] = xo.extra_bases or ''
    for fl in design.forced_ligations:
        key = frozenset(((fl.three_prime_helix_id, fl.three_prime_bp, fl.three_prime_direction.value),
                         (fl.five_prime_helix_id, fl.five_prime_bp, fl.five_prime_direction.value)))
        require(key not in junctions, 'Duplicate D003 junction')
        require(not fl.is_periodic_seam, 'D003 bridges must remain intrapart connections')
        junctions[key] = fl.extra_bases or ''
    used, full_sequences = set(), {}
    for strand in design.strands:
        route, sequence, cursor = [], '', 0
        for i, d in enumerate(strand.domains):
            step = 1 if d.direction.value == 'FORWARD' else -1
            sites = [(d.helix_id, b) for b in range(d.start_bp, d.end_bp + step, step)]
            route.extend((labels[h], b) for h, b in sites)
            n = sum(1 + indels.get(a, 0) for a in sites)
            sequence += strand.sequence[cursor:cursor+n]
            cursor += n
            if i + 1 < len(strand.domains):
                b = strand.domains[i+1]
                key = frozenset(((d.helix_id, d.end_bp, d.direction.value),
                                 (b.helix_id, b.start_bp, b.direction.value)))
                require(key in junctions and key not in used, 'Missing/reused D003 connection record')
                used.add(key)
                sequence += junctions[key]
        require(route == expected.get(strand.name), f'Directed figure route differs: {strand.name}')
        require(cursor == len(strand.sequence), f'Sequence span differs: {strand.name}')
        full_sequences[strand.name] = sequence
    require(used == junctions.keys(), 'Unused D003 connection record')
    for row in rows:
        require(full_sequences[row['name']] == row['sequence'], f"Published sequence differs: {row['name']}")
    offset = mapping['scaffold_offset_0based']
    require(full_sequences['M13mp18'] == scaffold_sequence[offset:] + scaffold_sequence[:offset],
            'Scaffold sequence differs')
    # Exercise the downstream simulation topology builder without launching a
    # simulation or inventing a physical conformation. Junction bases live
    # separately from strand.sequence and must survive this boundary.
    from backend.physics.oxdna_interface import topology_rows
    exported, count = topology_rows(design)
    require(count == len(design.strands), 'Export lost a strand')
    assembled = {i: [] for i in range(1, count + 1)}
    for i, (sid, base, n3, n5) in enumerate(exported):
        assembled[sid].append(base)
        for neighbor, reciprocal in ((n3, 3), (n5, 2)):
            require(neighbor == -1 or (0 <= neighbor < len(exported)
                and exported[neighbor][0] == sid and exported[neighbor][reciprocal] == i),
                'Export backbone connectivity is not reciprocal')
    require(all(''.join(assembled[i]) == full_sequences[s.name]
                for i, s in enumerate(design.strands, 1)), 'Export changed a published sequence')
    from backend.core.validator import validate_design
    validation = validate_design(design)
    require(validation.passed, 'Native design validation failed: ' +
            '; '.join(r.message for r in validation.results if not r.ok))
    return {**mapping, 'directed_routes_checked': len(expected), 'connections_checked': len(used),
            'deletions_checked': len(indels),
            'total_nucleotides_including_junction_bases': sum(map(len, full_sequences.values())),
            'oxdna_topology_particles': len(exported), 'oxdna_topology_sequences_and_bonds': 'verified',
            'native_validation_checks_passed': len(validation.results),
            'figure_and_sequence_equivalence': 'verified'}
