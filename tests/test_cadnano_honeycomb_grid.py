"""Regression for reflected HC cells misclassifying ordinary crossovers."""
from backend.core.cadnano import import_cadnano


def source():
    tracks = [dict(num=n, row=13, col=17+n, scaf=[[-1]*4 for _ in range(42)],
                   stap=[[-1]*4 for _ in range(42)], loop=[0]*42, skip=[0]*42,
                   stap_colors=[]) for n in range(3)]
    tracks[2].update(row=14, col=18)
    def route(kind, path):
        for i, (h, b) in enumerate(path):
            tracks[h][kind][b] = list(path[i-1] if i else (-1, -1)) + list(path[i+1] if i+1 < len(path) else (-1, -1))
    route('scaf', [(0,b) for b in range(3,35)])
    route('scaf', [(1,b) for b in range(34,2,-1)])
    route('scaf', [(2,b) for b in range(3,35)])
    route('stap', [(0,b) for b in range(30,26,-1)] + [(1,b) for b in range(27,31)])
    return dict(name='translated HC crossover', vstrands=tracks)


def test_source_cells_restore_crossover_without_changing_bp_or_geometry():
    old, _ = import_cadnano(source(), importer_version=1)
    fixed, _ = import_cadnano(source(), importer_version=2)
    assert len(old.forced_ligations) == 1 and not old.crossovers
    assert len(fixed.crossovers) == 1 and not fixed.forced_ligations
    assert [h.grid_pos for h in fixed.helices] == [(13,17), (13,18), (14,18)]
    for a, b in zip(old.helices, fixed.helices):
        assert a.model_dump(exclude={'grid_pos'}) == b.model_dump(exclude={'grid_pos'})
        assert b.bp_start == 3
    paths = lambda d: sorted((s.strand_type.value, tuple((x.helix_id,x.start_bp,x.end_bp,x.direction.value) for x in s.domains)) for s in d.strands)
    assert paths(old) == paths(fixed)


def test_pinned_import_versions_replay_the_selected_coordinate_convention():
    from tests.test_part_cadnano_commands import inputs
    from backend.api import part_cadnano_commands as commands
    import json
    initial, params, resolver = inputs(raw=json.dumps(source()).encode())
    legacy = commands.build('cadnano-import', initial, params, resolver=resolver)
    fixed = commands.build('cadnano-import', initial, {**params, 'importer_version':2}, resolver=resolver)
    assert len(legacy.forced_ligations) == 1 and not legacy.crossovers
    assert len(fixed.crossovers) == 1 and not fixed.forced_ligations
