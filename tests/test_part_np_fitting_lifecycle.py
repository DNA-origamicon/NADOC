"""Fitted/relaxed anchors retain the native restoration geometry and other owners."""
from uuid import uuid4

import pytest

from backend.api import part_np_application_commands as application, part_np_fitting_commands as fitting
from backend.api.part_proof_commands import dependencies, execute_long
from backend.core.models import Design, Direction, Domain, Helix, Nanoparticle, NanoparticleConnectionVersion, OverhangSpec, Strand, StrandType, Vec3
from backend.core.nanoparticle import build_thiol_conjugation
from backend.core.nanoparticle_connections import ensure_duplex_endpoint, set_version_applied
from backend.core.part_history_contract import assess_part_history
from backend.core.part_command_errors import CommandContractError
from tests.test_part_np_application_commands import application_params, oracle
from tests.test_part_pending_np_connections import CREATE, PATCH, DELETE, append, authored, native_prefix as native_prefix


def multi_anchor_source(count):
    # Same admitted native construction as test_native_asset_contract_bounds.
    particle = Nanoparticle(id='gold', diameter_nm=10.)
    owner, helices, strands = build_thiol_conjugation(particle, scheme='direct_thiol', sequence='ACGTACGT', count=count, seed=4)
    design = Design(nanoparticles=[particle], nanoparticle_conjugations=[owner], helices=helices, strands=strands)
    for index, record in enumerate(owner.surface_strands):
        design, _ = ensure_duplex_endpoint(design, particle.id, record.strand_id)
        hid, sid, oid = f'target-{index}', f'target-strand-{index}', f'target-{index}_3p'
        x, y = [(18., 8.), (-14., 8.), (0., 18.), (0., -18.)][index]
        helix = Helix(id=hid, axis_start=Vec3(x=x, y=y, z=0.), axis_end=Vec3(x=x, y=y, z=2.38), length_bp=8)
        strand = Strand(id=sid, domains=[Domain(helix_id=hid, start_bp=0, end_bp=7, direction=Direction.FORWARD, overhang_id=oid)], strand_type=StrandType.STAPLE, sequence='ACGTACGT')
        version = NanoparticleConnectionVersion(id=f'anchor-{index}', nanoparticle_id=particle.id, strand_id=record.strand_id, overhang_id=oid, nanoparticle_attach='free_end', target_attach='root')
        design = design.copy_with(helices=[*design.helices, helix], strands=[*design.strands, strand],
            overhangs=[*design.overhangs, OverhangSpec(id=oid, helix_id=hid, strand_id=sid, sequence='ACGTACGT')],
            nanoparticle_connection_versions=[*design.nanoparticle_connection_versions, version])
        design = set_version_applied(design, version.id, True)
    params = fitting.prepare_command('nanoparticle-connection-relax', design, {'nanoparticle_id': particle.id}, history_seed=str(uuid4()), created_at=1.)
    return fitting.build('nanoparticle-connection-relax', design, params)


@pytest.mark.parametrize('count', [2, 4])
@pytest.mark.parametrize('action', ['unapply', 'delete', 'reapply', 'rename'])
def test_relaxed_lifecycle_matches_native_and_preserves_other_anchors(count, action, monkeypatch):
    source = multi_anchor_source(count)
    kind = DELETE if action == 'delete' else PATCH
    params = application_params(source, kind, version_id='anchor-0', applied=action == 'reapply')
    params['nanoparticle_application_version'] = 2
    if action == 'rename':
        params.pop('applied')
        params['name'] = 'Renamed relaxed anchor'
        expected = source.copy_with(nanoparticle_connection_versions=[v.model_copy(update={'name': params['name']}) if v.id == 'anchor-0' else v for v in source.nanoparticle_connection_versions])
    else:
        expected = oracle(source, kind, params, monkeypatch)
    before = source.model_dump_json()
    actual = application.build(kind, source, params)
    assert authored(actual) == authored(expected)
    assert source.model_dump_json() == before
    assert actual.nanoparticle_connection_versions[1:] == expected.nanoparticle_connection_versions[1:]
    retained = {v.duplex_id for v in source.nanoparticle_connection_versions if v.id != 'anchor-0'}
    assert [d for d in actual.duplexes if d.id in retained] == [d for d in source.duplexes if d.id in retained]


def test_relaxed_lifecycle_keeps_v1_refusal_and_rejects_foreign_owner():
    source = multi_anchor_source(2)
    params = application_params(source, DELETE, version_id='anchor-0', applied=False)
    with pytest.raises(CommandContractError):
        application.build(DELETE, source, params)
    params['nanoparticle_application_version'] = 2
    source.nanoparticle_conjugations[0].surface_strands[1].bound_overhang_id = 'foreign'
    before = source.model_dump_json()
    with pytest.raises(CommandContractError):
        application.build(DELETE, source, params)
    assert source.model_dump_json() == before


def test_relaxed_delete_cold_replays_from_empty_root(native_prefix):
    source = native_prefix.model_copy(deep=True)
    source = append(source, CREATE, application_params(source), 'applied')
    params = fitting.prepare_command('nanoparticle-connection-relax', source, {'nanoparticle_id': 'gold'}, history_seed=str(uuid4()), created_at=1.)
    from backend.core.models import SnapshotLogEntry
    source = fitting.build('nanoparticle-connection-relax', source, params).copy_with(feature_log=[*source.feature_log,
        SnapshotLogEntry(id='relax', label='Relax', op_kind='nanoparticle-connection-relax', params=params)])
    params = application_params(source, DELETE, applied=False)
    params['nanoparticle_application_version'] = 2
    result = append(source, DELETE, params, 'removed')
    assert assess_part_history(result, execute=execute_long, dependencies=dependencies)['status'] == 'verified'
