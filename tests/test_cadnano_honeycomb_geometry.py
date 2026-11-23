"""External source imports must use the existing native nucleotide frame.

Fixtures are unmodified caDNAno source designs; no test fabricates a NADOC
structure or publishes a history-free molecular artifact. The large regression
is the exact deposited Gür source, compressed without changing its bytes.
"""
from collections import Counter
import gzip
import hashlib
import json
import math
from pathlib import Path

import numpy as np
import pytest

from backend.core.cadnano import import_cadnano
from backend.core.constants import (
    BDNA_RISE_PER_BP,
    HC_CROSSOVER_OFFSETS,
    HC_SCAFFOLD_CROSSOVER_OFFSETS,
)
from backend.core.crossover_positions import crossover_neighbor
from backend.core.deformation import effective_helix_for_geometry
from backend.core.design_geometry import (
    _geometry_for_design,
    native_full_arrays_for_helix,
    native_full_phase_roll_rad,
)
from backend.core.geometry import _frame_from_helix_axis
from backend.core.lattice import (
    _lattice_direction,
    _lattice_phase_offset,
    _lattice_position,
    _lattice_twist,
    autodetect_all_overhangs,
)
from backend.core.models import Direction
from backend.core.native_full_placement import positions_in_native_frame


ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / 'Examples' / 'cadnano'
GUR = ROOT / 'tests' / 'fixtures' / 'cadnano_gur_2016_6hb.json.gz'
GUR_SHA = '38d5779198fbc6227faa55bf4f16077771e1169f31ac41adbda6cce7c3d21b33'


def _source(name):
    raw = gzip.decompress(GUR.read_bytes()) if name == 'gur' else (EXAMPLES / name).read_bytes()
    if name == 'gur':
        assert hashlib.sha256(raw).hexdigest() == GUR_SHA
    return json.loads(raw)


def _native_point(design, helix, bp, direction):
    """Independent native-frame authority, without constructing a new helix."""
    row, col = helix.grid_pos
    x, y = _lattice_position(row, col, design.lattice_type)
    phase = _lattice_phase_offset(_lattice_direction(row, col, design.lattice_type), design.lattice_type)
    angle = phase + bp * _lattice_twist(design.lattice_type) + native_full_phase_roll_rad(design)
    frame = _frame_from_helix_axis(np.array([0., 0., 1.]))
    forward = math.cos(angle)*frame[:, 0] + math.sin(angle)*frame[:, 1]
    return positions_in_native_frame(
        np.array([x, y, bp*BDNA_RISE_PER_BP]), forward, frame[:, 2],
        np.array(direction == Direction.REVERSE),
    )[0]


@pytest.mark.parametrize('name', [
    'Honeycomb_6hb_test1.json', 'Honeycomb_18hb_test1.json',
    '6hb_cadnano_native_test1.json', '2x4hb_sq_test.json', 'gur',
])
def test_current_import_uses_consistent_native_frame_and_active_span(name):
    source = _source(name)
    untouched = json.dumps(source, sort_keys=True)
    design, _ = import_cadnano(source)
    by_cell = {(v['row'], v['col']): v for v in source['vstrands']}
    for helix in design.helices:
        track = by_cell[helix.grid_pos]
        active = [bp for bp in range(len(track['scaf']))
                  if track['scaf'][bp] != [-1]*4 or track['stap'][bp] != [-1]*4]
        assert helix.bp_start == min(active)
        assert helix.length_bp == max(active)-min(active)+1
        assert helix.axis_start.z == pytest.approx(min(active)*BDNA_RISE_PER_BP)
        assert helix.axis_end.z == pytest.approx((max(active)+1)*BDNA_RISE_PER_BP)
        assert [helix.axis_start.x, helix.axis_start.y] == pytest.approx(
            _lattice_position(*helix.grid_pos, design.lattice_type))
        native_twist = _lattice_twist(design.lattice_type)
        native_phase = _lattice_phase_offset(helix.direction, design.lattice_type)
        assert helix.twist_per_bp_rad == native_twist
        assert helix.phase_offset == pytest.approx(native_phase+helix.bp_start*native_twist)
        effective = effective_helix_for_geometry(helix, design)
        assert effective.phase_offset == pytest.approx(helix.phase_offset)
        assert effective.twist_per_bp_rad == helix.twist_per_bp_rad
        assert effective.axis_start == helix.axis_start
        assert effective.axis_end == helix.axis_end
        expected_indels = [(bp, delta) for bp in range(len(track['scaf']))
                           for delta in (track['loop'][bp], track['skip'][bp]) if delta]
        assert [(ls.bp_index, ls.delta) for ls in helix.loop_skips] == expected_indels
    assert json.dumps(source, sort_keys=True) == untouched


def test_all_honeycomb_site_classes_match_native_frame_and_repeat_after_21_bp():
    # The external 18HB covers every neighbour orientation and both parities.
    # Prospective site reads do not add any strand or crossover to the fixture.
    design, _ = import_cadnano(_source('Honeycomb_18hb_test1.json'))
    by_cell = {h.grid_pos: h for h in design.helices}
    arrays = {h.id: native_full_arrays_for_helix(h, design) for h in design.helices}
    positions = {
        (hid, int(bp), int(direction)): point
        for hid, arr in arrays.items()
        for bp, direction, point in zip(arr['bp_indices'], arr['directions'], arr['positions'])
    }
    covered = {False: set(), True: set()}
    for scaffold in [False, True]:
        for helix in design.helices:
            row, col = helix.grid_pos
            for bp in range(21):
                neighbor = by_cell.get(crossover_neighbor(design.lattice_type, row, col, bp, is_scaffold=scaffold))
                if neighbor is None:
                    continue
                da = helix.direction if scaffold else (Direction.REVERSE if helix.direction == Direction.FORWARD else Direction.FORWARD)
                db = neighbor.direction if scaffold else (Direction.REVERSE if neighbor.direction == Direction.FORWARD else Direction.FORWARD)
                lengths = []
                for index in [bp, bp+21]:
                    a = positions[(helix.id, index, int(da == Direction.REVERSE))]
                    b = positions[(neighbor.id, index, int(db == Direction.REVERSE))]
                    np.testing.assert_allclose(a, _native_point(design, helix, index, da), rtol=0, atol=1e-11)
                    np.testing.assert_allclose(b, _native_point(design, neighbor, index, db), rtol=0, atol=1e-11)
                    lengths.append(float(np.linalg.norm(a-b)))
                assert lengths[0] == pytest.approx(lengths[1], abs=1e-11)
                assert max(lengths) < 1.2
                covered[scaffold].add(((row+col)%2 == 0, bp))
    assert covered[False] == set(HC_CROSSOVER_OFFSETS)
    assert covered[True] == set(HC_SCAFFOLD_CROSSOVER_OFFSETS)


def test_gur_long_import_preserves_all_source_paths_and_native_junction_geometry():
    source = _source('gur')
    design, warnings = import_cadnano(source)
    assert warnings == []
    by_cell = {(v['row'],v['col']):v for v in source['vstrands']}
    by_num = {v['num']:v for v in source['vstrands']}
    source_number = {h.id:by_cell[h.grid_pos]['num'] for h in design.helices}
    helices = {h.id:h for h in design.helices}
    assert max(h.bp_start+h.length_bp-1 for h in design.helices) == 1229
    assert min(h.bp_start for h in design.helices) > 0
    assert not any(h.loop_skips for h in design.helices)
    nucs = _geometry_for_design(design)
    positions = {(n['helix_id'], n['bp_index'], n['direction']):np.array(n['backbone_position']) for n in nucs}
    core = {dom.helix_id for s in design.strands if s.is_scaffold for dom in s.domains}
    counts = Counter()
    staple_lengths = []
    for strand in design.strands:
        path = [(source_number[dom.helix_id],bp) for dom in strand.domains
                for bp in range(dom.start_bp,dom.end_bp+(1 if dom.direction == Direction.FORWARD else -1),
                                1 if dom.direction == Direction.FORWARD else -1)]
        source_kind = 'scaf' if strand.is_scaffold else 'stap'
        source_path, seen, current = [], set(), path[0]
        while current != (-1,-1) and current not in seen:
            source_path.append(current); seen.add(current)
            current = tuple(by_num[current[0]][source_kind][current[1]][2:])
        assert path == source_path
        for a,b in zip(strand.domains,strand.domains[1:]):
            if a.helix_id == b.helix_id or a.helix_id not in core or b.helix_id not in core:
                continue
            pa = positions[(a.helix_id,a.end_bp,a.direction.value)]
            pb = positions[(b.helix_id,b.start_bp,b.direction.value)]
            na = _native_point(design,helices[a.helix_id],a.end_bp,a.direction)
            nb = _native_point(design,helices[b.helix_id],b.start_bp,b.direction)
            np.testing.assert_allclose(pa,na,rtol=0,atol=1e-10)
            np.testing.assert_allclose(pb,nb,rtol=0,atol=1e-10)
            distance = float(np.linalg.norm(pa-pb))
            assert distance == pytest.approx(float(np.linalg.norm(na-nb)),abs=1e-10)
            assert distance < 1.2
            counts[strand.strand_type.value] += 1
            if not strand.is_scaffold:
                staple_lengths.append(distance)
    assert len(design.strands) == 167
    assert counts == {'scaffold':10,'staple':332}
    # Both complementary halves keep the existing native landmark asymmetry.
    assert sum(abs(v-0.80956135795118)<1e-9 for v in staple_lengths) == 166
    assert sum(abs(v-0.80972335653097)<1e-9 for v in staple_lengths) == 166
    assert len(design.crossovers) == 350
    assert len(design.forced_ligations) == 16
    assert not any(f.three_prime_helix_id in core and f.five_prime_helix_id in core for f in design.forced_ligations)
    classified = autodetect_all_overhangs(design)
    assert len(classified.overhangs) == 24
    assert not classified.extensions


@pytest.mark.parametrize('name,version,expected', [
    ('Honeycomb_6hb_test1.json',1,'7944ef0faa6a929469c331fc100dfe91e1b375683ade6d566b6b118cef6787b3'),
    ('Honeycomb_6hb_test1.json',2,'4a015d54a28eae06c72dda75bc47839ce5b1b308b690578a4a95864fa5208df0'),
    ('6hb_cadnano_native_test1.json',1,'6e33350314d6e16cb9bf37752ad37bccb10e85bb139432c99cfae7b49358e7c7'),
    ('6hb_cadnano_native_test1.json',2,'4fa58aff13635937276681735f24107d959b2f928d5ada1c6198a862d51b9bca'),
    ('2x4hb_sq_test.json',1,'080d1e8f40b00a992842fea4436ac1d377ce896562c9f32e674f908585e1e61c'),
    ('2x4hb_sq_test.json',2,'080d1e8f40b00a992842fea4436ac1d377ce896562c9f32e674f908585e1e61c'),
])
def test_legacy_import_authoring_state_is_unchanged(name,version,expected):
    """Digests captured before v3 implementation; do not rebaseline replay."""
    design,_ = import_cadnano(_source(name),importer_version=version)
    dumped = design.model_dump(mode='json')
    value = {k:dumped[k] for k in ['helices','strands','crossovers','forced_ligations','lattice_type','metadata']}
    for kind in ['crossovers','forced_ligations']:
        for row in value[kind]:
            # Direct import's allocation ID is nondeterministic; the replay
            # adapter separately pins identities. All molecular fields remain.
            row.pop('id')
    digest = hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    assert digest == expected
