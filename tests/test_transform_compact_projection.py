"""Array transport must preserve the general native producer bit for bit."""
import json

import pytest

from backend.api.part_transform_display_contract import inventory
from backend.api.part_transform_projection import project_admitted
from backend.core.part_dna_comparison_codec import pack_records_compact
from tests.test_part_dna_comparison import small


@pytest.mark.parametrize('kind', ['straight', 'loops', 'child', 'sweep', 'tails', 'bend', 'twist', 'reference', 'frame', 'periodic'])
@pytest.mark.parametrize('posed', [False, True])
def test_array_projection_matches_complete_general_packet(kind, posed):
    from backend.core.models import NucleotideTransform, Direction
    source = small(kind)
    if posed:
        source.nucleotide_transforms = [NucleotideTransform(kind='base', helix_id=source.helices[0].id,
            bp_index=4, direction=Direction.FORWARD, translation=[1, -3, .2],
            rotation=[0, 0, .6, .8], pivot=[2, 1, 0])]
    admitted = inventory(source, lambda: None)
    ordinary = project_admitted(source, admitted, lambda: None)
    actual = project_admitted(source, admitted, lambda: None, compact=True)
    expected = dict(ordinary, component_version=2,
                    nucleotides=pack_records_compact(ordinary['nucleotides']))
    assert json.dumps(actual, sort_keys=True) == json.dumps(expected, sort_keys=True)


@pytest.mark.parametrize('mutation', ['missing', 'duplicate', 'nonfinite', 'registration'])
def test_array_transport_refuses_incomplete_or_corrupt_native_output(monkeypatch, mutation):
    import numpy as np
    from backend.core import design_geometry as geometry
    from backend.core.part_command_errors import CommandContractError
    source = small()
    admitted = inventory(source, lambda: None)
    original = geometry.native_full_arrays_for_helix
    def corrupt(*args, **kwargs):
        arrays = original(*args, **kwargs)
        if mutation == 'missing':
            count = len(arrays['bp_indices'])
            arrays = {k: v[2:] if isinstance(v, np.ndarray) and len(v) == count else v
                      for k, v in arrays.items()}
        elif mutation == 'duplicate':
            arrays['bp_indices'][2:4] = arrays['bp_indices'][:2]
        elif mutation == 'nonfinite':
            arrays['axis_points'][0, 0] = np.nan
        else:
            arrays['base_positions'][0] += 100
        return arrays
    monkeypatch.setattr(geometry, 'native_full_arrays_for_helix', corrupt)
    with pytest.raises(CommandContractError) as caught:
        project_admitted(source, admitted, lambda: None, compact=True)
    assert caught.value.code == 'invalid_preview_geometry'


def test_loop_copy_pose_and_partial_occupancy_remain_exact():
    from backend.core.models import NucleotideTransform, Direction
    source = small('loops')
    source.strands[1].domains[0].start_bp = 6
    source.nucleotide_transforms = [NucleotideTransform(kind='base', helix_id='h0',
        bp_index=3, direction=Direction.FORWARD, copy_k=1, translation=[2, 1, -3])]
    admitted = inventory(source, lambda: None)
    ordinary = project_admitted(source, admitted, lambda: None)
    actual = project_admitted(source, admitted, lambda: None, compact=True)
    expected = dict(ordinary, component_version=2,
                    nucleotides=pack_records_compact(ordinary['nucleotides']))
    assert json.dumps(actual, sort_keys=True) == json.dumps(expected, sort_keys=True)


def test_prefix_copy_preserves_aliases_and_isolates_every_mutable_container():
    from copy import deepcopy
    from backend.api.part_transform_preview import _copy_transform_prefix
    source = small('loops')
    domain = source.strands[0].domains[0]
    source.metadata.__dict__['domain'] = domain
    source.metadata.__dict__['fields'] = domain.__dict__
    source.metadata.__dict__['field_set'] = domain.__pydantic_fields_set__
    copied = _copy_transform_prefix(source)
    assert copied == deepcopy(source)
    target = copied.strands[0].domains[0]
    assert target is copied.metadata.__dict__['domain'] and target is not domain
    assert target.__dict__ is copied.metadata.__dict__['fields'] and target.__dict__ is not domain.__dict__
    assert target.__pydantic_fields_set__ is copied.metadata.__dict__['field_set']
    assert target.__pydantic_fields_set__ is not domain.__pydantic_fields_set__
    target.start_bp = -9
    target.__pydantic_fields_set__.add('test')
    assert domain.start_bp != -9 and 'test' not in domain.__pydantic_fields_set__
    # Cached/future data must retain ordinary recursive copy behavior.
    domain.__dict__['cached'] = [1, 2]
    copied = _copy_transform_prefix(source)
    copied.strands[0].domains[0].__dict__['cached'].append(3)
    assert domain.__dict__['cached'] == [1, 2]


@pytest.mark.parametrize('kind', ['cluster', 'child', 'bend', 'twist', 'sweep', 'frame'])
def test_reused_segment_frames_match_uncached_arithmetic_exactly(kind, monkeypatch):
    from backend.core import deformation
    from backend.core.models import ClusterRigidTransform
    source = small(kind)
    if not source.cluster_transforms:
        source.cluster_transforms = [ClusterRigidTransform(id='placement', helix_ids=['h0'],
            translation=[4, -2, .7], rotation=[0, 0, .6, .8], pivot=[-1, 3, 2])]
    actual = deformation.deformed_helix_axes(source)
    original = deformation._apply_clusters_to_seg_point
    monkeypatch.setattr(deformation, '_apply_clusters_to_seg_point',
        lambda point, seg, hid, owners, frames=None: original(point, seg, hid, owners))
    assert json.dumps(actual) == json.dumps(deformation.deformed_helix_axes(source))


@pytest.mark.parametrize('change', ['pose', 'loop', 'owner', 'duplicate', 'direction-type'])
def test_retained_occupancy_matches_fresh_admission_and_refuses_changed_invalid_sources(change):
    from copy import deepcopy
    from backend.core.models import ClusterRigidTransform, LoopSkip
    from backend.core.part_command_errors import CommandContractError
    source = small()
    previous = inventory(deepcopy(source), lambda: None)
    if change == 'pose':
        source.cluster_transforms = [ClusterRigidTransform(helix_ids=['h0'], translation=[1, 2, 3])]
    elif change == 'loop':
        source.helices[0].loop_skips = [LoopSkip(bp_index=3, delta=1)]
    elif change == 'owner':
        source.strands[0].id = 'different-owner'
    elif change == 'duplicate':
        source.strands.append(source.strands[0].model_copy(update={'id': 'duplicate'}))
    else:
        object.__setattr__(source.strands[0].domains[0], 'direction', 'FORWARD')
    if change in {'duplicate', 'direction-type'}:
        with pytest.raises(CommandContractError):
            inventory(source, lambda: None, previous=previous)
    else:
        assert inventory(source, lambda: None, previous=previous).sites == inventory(source, lambda: None).sites
