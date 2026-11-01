"""Intent-based NP fitting retains the existing kernels and exact owned anchors."""
from uuid import uuid4

import pytest

from backend.api import part_np_fitting_commands as commands
from backend.api.part_proof_commands import execute, execute_long, dependencies
from backend.core.part_command_errors import CommandContractError
from backend.core.part_history_proof import AUTHORING_FIELDS
from backend.core.nanoparticle import constrained_nanoparticle_move
from backend.core.nanoparticle_kinematics import solve_nanoparticle_anchors
from backend.core.design_geometry import fitting_geometry
from tests.test_nanoparticle_attachment import attachment_source as attachment_source
from tests.test_part_streptavidin_commands import sources as sources

# These tests exercise the real bounded native fit/solver, not physical sampling.
pytestmark = [pytest.mark.slow, pytest.mark.headless]


def inputs(design, particle_id, kind='nanoparticle-attach-overhang', **changes):
    public = {'nanoparticle_id': particle_id}
    if kind == 'nanoparticle-attach-overhang':
        public.update(overhang_id='target_3p', strand_id=design.nanoparticle_conjugations[0].surface_strands[0].strand_id)
    public.update(changes)
    return commands.prepare_command(kind, design, public, history_seed=str(uuid4()), created_at=1.)


def authored(design):
    return design.model_dump(mode='json', include=AUTHORING_FIELDS)


def test_fit_stable_identities_then_bound_move_and_relax_match_existing_kernels(attachment_source, sources):
    design, identity = attachment_source
    params = inputs(design, identity)
    before = design.model_dump_json()
    fitted, diagnostics = commands.evaluate('nanoparticle-attach-overhang', design, params)
    assert fitted.nanoparticle_connection_versions[-1].id == params['version_id']
    assert fitted.duplexes[-1].id == params['duplex_id']
    assert diagnostics['residual_nm'] < .02
    assert authored(execute_long('nanoparticle-attach-overhang', design, params)) == authored(fitted)
    assert design.model_dump_json() == before
    assert dependencies('nanoparticle-attach-overhang', params).known
    move = {'pivot': [0., 0., 0.], 'translation': [.1, .2, 0.], 'rotation': [0., 0., 0., 1.], 'preconstrained': False}
    move_inputs = inputs(fitted, identity, 'nanoparticle-bound-move', gizmo_move=move)
    native, expected = constrained_nanoparticle_move(fitted, identity, fitted.nanoparticle_connection_versions[0],
        fitting_geometry(fitted), **move)
    moved, actual = commands.evaluate('nanoparticle-bound-move', fitted, move_inputs)
    assert authored(moved) == authored(native) and actual == expected
    relax_inputs = inputs(moved, identity, 'nanoparticle-connection-relax')
    native, report = solve_nanoparticle_anchors(moved, identity)
    expected_versions = [v.model_copy(update={'relaxed': True, 'residual_nm': report['per_anchor_residual_nm'][v.id]})
                         for v in native.nanoparticle_connection_versions]
    native = native.copy_with(nanoparticle_connection_versions=expected_versions)
    relaxed, actual = commands.evaluate('nanoparticle-connection-relax', moved, relax_inputs)
    assert authored(relaxed) == authored(native) and actual == report


@pytest.mark.parametrize('damage', ['engine', 'runtime', 'handle', 'anchors', 'output'])
def test_bad_selection_or_provenance_cannot_run_fit(attachment_source, sources, monkeypatch, damage):
    design, identity = attachment_source
    params = inputs(design, identity)
    if damage == 'engine':
        params['engine']['implementation_sha256'] = '0' * 64
    elif damage == 'runtime':
        params['engine']['runtime_sha256'] = '0' * 64
    elif damage == 'handle':
        params['strand_id'] = 'absent'
    elif damage == 'anchors':
        params.update(applied_version_ids=['missing'], applied_duplex_ids=['missing'])
    else:
        params['duplex_id'] = design.helices[0].id
    from backend.api import nanoparticle_attachment
    monkeypatch.setattr(nanoparticle_attachment, 'attach_nanoparticle', lambda *_a, **_k: pytest.fail('Invalid source reached native fit'))
    before = design.model_dump_json()
    with pytest.raises(CommandContractError):
        execute_long('nanoparticle-attach-overhang', design, params)
    assert design.model_dump_json() == before


def test_normal_executor_requires_job_and_public_input_refuses_solved_pose(attachment_source, sources):
    design, identity = attachment_source
    params = inputs(design, identity)
    with pytest.raises(CommandContractError) as error:
        execute('nanoparticle-attach-overhang', design, params)
    assert error.value.code == 'long_job_required'
    with pytest.raises(ValueError):
        inputs(design, identity, pose=[1.] * 16)
