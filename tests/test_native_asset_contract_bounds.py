"""Numerical asset admission protects exact ownership before solver work."""
from uuid import uuid4

import pytest
from backend.api import part_biotin_commands as biotin, part_np_fitting_commands as fitting
from backend.core.models import (Design, Direction, Domain, Helix, Nanoparticle,
    NanoparticleConnectionVersion, OverhangSpec, Strand, StrandType, Vec3)
from backend.core.nanoparticle import build_thiol_conjugation
from backend.core.nanoparticle_connections import ensure_duplex_endpoint, set_version_applied
from backend.core.nanoparticle_kinematics import solve_nanoparticle_anchors
from backend.core.part_command_errors import CommandContractError
from tests.test_part_streptavidin_commands import sources as sources
from tests.test_part_biotin_commands import initial, inputs as biotin_inputs
from tests.test_part_np_fitting_commands import authored
from tests.test_nanoparticle_attachment import attachment_source as attachment_source

pytestmark = [pytest.mark.slow, pytest.mark.headless]


@pytest.mark.parametrize('count', [2, 4])
def test_collective_relaxation_matches_native_solver_for_every_anchor(count, sources):
    particle = Nanoparticle(id='gold', diameter_nm=10.)
    owner, helices, strands = build_thiol_conjugation(particle, scheme='direct_thiol',
        sequence='ACGTACGT', count=count, seed=4)
    design = Design(nanoparticles=[particle], nanoparticle_conjugations=[owner], helices=helices, strands=strands)
    for index, record in enumerate(owner.surface_strands):
        design, _ = ensure_duplex_endpoint(design, particle.id, record.strand_id)
        hid, sid, oid = f'target-{index}', f'target-strand-{index}', f'target-{index}_3p'
        x, y = [(18., 8.), (-14., 8.), (0., 18.), (0., -18.)][index]
        helix = Helix(id=hid, axis_start=Vec3(x=x, y=y, z=0.), axis_end=Vec3(x=x, y=y, z=2.38), length_bp=8)
        strand = Strand(id=sid, domains=[Domain(helix_id=hid, start_bp=0, end_bp=7,
            direction=Direction.FORWARD, overhang_id=oid)], strand_type=StrandType.STAPLE, sequence='ACGTACGT')
        version = NanoparticleConnectionVersion(id=f'anchor-{index}', nanoparticle_id=particle.id,
            strand_id=record.strand_id, overhang_id=oid, nanoparticle_attach='free_end', target_attach='root')
        design = design.copy_with(helices=[*design.helices, helix], strands=[*design.strands, strand],
            overhangs=[*design.overhangs, OverhangSpec(id=oid, helix_id=hid, strand_id=sid, sequence='ACGTACGT')],
            nanoparticle_connection_versions=[*design.nanoparticle_connection_versions, version])
        design = set_version_applied(design, version.id, True)
    kind = 'nanoparticle-connection-relax'
    params = fitting.prepare_command(kind, design, {'nanoparticle_id': particle.id},
        history_seed=str(uuid4()), created_at=1.)
    before = design.model_dump_json()
    expected, diagnostics = solve_nanoparticle_anchors(design, particle.id)
    expected = expected.copy_with(nanoparticle_connection_versions=[v.model_copy(update={
        'relaxed': True, 'residual_nm': diagnostics['per_anchor_residual_nm'][v.id]})
        for v in expected.nanoparticle_connection_versions])
    actual, result = fitting.evaluate(kind, design, params)
    assert len(result['version_ids']) == count
    assert authored(actual) == authored(expected) and result == diagnostics
    assert design.model_dump_json() == before
    assert fitting.validate_inputs(kind, actual, params)


@pytest.mark.parametrize('damage', ['count', 'domain', 'coordinates', 'parent'])
def test_inconsistent_graft_fails_before_fitting(attachment_source, sources, damage):
    design, particle = attachment_source
    owner = design.nanoparticle_conjugations[0]
    record = owner.surface_strands[0]
    if damage == 'count':
        owner.requested_count += 1
    elif damage == 'domain':
        design.find_strand(record.strand_id).domains[0].end_bp -= 1
    elif damage == 'coordinates':
        record.backbone_attachment_local_nm = (float('inf'), 0., 0.)
    else:
        next(o for o in design.overhangs if o.id == record.overhang_id).parent_overhang_id = 'foreign'
    with pytest.raises(CommandContractError):
        fitting.prepare_command('nanoparticle-attach-overhang', design, {'nanoparticle_id': particle,
            'overhang_id': 'target_3p', 'strand_id': record.strand_id}, history_seed=str(uuid4()), created_at=1.)


@pytest.mark.parametrize('damage', ['scale', 'reflection', 'translation', 'nan', 'duplicate-extension'])
def test_biotin_operational_bounds_and_exact_extension_ownership(sources, damage):
    design = initial(sources)
    params = biotin_inputs(design)
    if damage == 'duplicate-extension':
        from backend.api.part_biotin_append import prepare_command
        from backend.core.part_input_sources import EmbeddedResolver
        design = biotin.build(biotin.KIND, design, params, resolver=EmbeddedResolver(design.input_sources))
        params = prepare_command(design, {'action': 'remove', 'nanoparticle_id': 'gold'}, history_seed=str(uuid4()))
        design.extensions.append(design.extensions[0].model_copy(deep=True))
    else:
        pose = design.nanoparticles[0].coating.poses[0].to_array()
        if damage == 'scale':
            pose[:3, :3] *= 10
        elif damage == 'reflection':
            pose[:3, 0] *= -1
        elif damage == 'translation':
            pose[0, 3] = 1e6
        else:
            pose[0, 0] = float('nan')
        design.nanoparticles[0].coating.poses[0] = design.nanoparticles[0].pose.from_array(pose)
    with pytest.raises(CommandContractError):
        biotin.validate_inputs(biotin.KIND, design, params)
