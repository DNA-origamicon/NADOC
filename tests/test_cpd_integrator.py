"""Fast CPD admission depends on exact native-tested asset identities."""
import json

import pytest

from backend.core import cpd_integrator
from backend.core.cpd_forcefield import (
    CpdCapabilityError, assert_packaged_photoproduct_integrator,
)


def qualified_assets():
    evidence = json.loads(cpd_integrator.EVIDENCE.read_text())
    pid, product = next(iter(evidence['products'].items()))
    return [dict(a, product_id=pid) for a in product['assets']]


def test_exact_native_tested_assets_only():
    assets = qualified_assets()
    assert cpd_integrator.assets_hmr_qualified(assets)
    modified = [dict(a) for a in assets]
    next(a for a in modified if a['kind'] == 'parameters')['sha256'] = '0'*64
    assert not cpd_integrator.assets_hmr_qualified(modified)
    assert not cpd_integrator.assets_hmr_qualified([])
    assert not cpd_integrator.assets_hmr_qualified([dict(assets[0], product_id='unknown')])
    assert not cpd_integrator.assets_hmr_qualified([*assets, dict(assets[0], product_id='other')])


def test_missing_or_failed_evidence_stays_blocked(tmp_path, monkeypatch):
    assets = qualified_assets()
    original = json.loads(cpd_integrator.EVIDENCE.read_text())
    monkeypatch.setattr(cpd_integrator, 'EVIDENCE', tmp_path/'evidence.json')
    assert not cpd_integrator.assets_hmr_qualified(assets)
    next(iter(original['products'].values()))['pairs'][0]['passed'] = False
    cpd_integrator.EVIDENCE.write_text(json.dumps(original))
    assert not cpd_integrator.assets_hmr_qualified(assets)


def test_qualified_package_accepts_only_tested_fast_combination(tmp_path, monkeypatch):
    from backend.core import cpd_forcefield
    monkeypatch.setattr(cpd_forcefield, 'package_has_photoproducts', lambda p: True)
    monkeypatch.setattr(cpd_integrator, 'package_hmr_qualified', lambda p: True)
    assert_packaged_photoproduct_integrator(tmp_path, timestep_fs=4, hmr=True, path='test')
    assert_packaged_photoproduct_integrator(tmp_path, timestep_fs=2, hmr=False, path='test')
    for dt, hmr in [(4, False), (8, True), (2, True)]:
        with pytest.raises(CpdCapabilityError):
            assert_packaged_photoproduct_integrator(tmp_path, timestep_fs=dt, hmr=hmr, path='test')
    with pytest.raises(CpdCapabilityError, match='rigidBonds all'):
        assert_packaged_photoproduct_integrator(
            tmp_path, timestep_fs=4, hmr=True, rigid_bonds='none', path='test')


@pytest.mark.parametrize('parent_hmr', [False, True])
def test_cpd_continuation_reseeds_only_when_mass_assignment_changes(tmp_path, monkeypatch, parent_hmr):
    from backend.core import cpd_forcefield
    from backend.core.md_protocols import write_hmr_psf
    from tests.test_md_ensemble import _make_parent, _build_replica, _write_minimal_psf, READY

    parent = _make_parent(tmp_path)
    parent.run_kind = 'production'
    pkg = parent.package_dir(tmp_path)
    _write_minimal_psf(pkg/'demo.psf')
    write_hmr_psf(pkg/'demo.psf', pkg/'demo_hmr.psf')
    (pkg/f'{READY}.conf').write_text('structure demo_hmr.psf\n' if parent_hmr else 'structure demo.psf\n')
    for ext in ('coor', 'vel', 'xsc'):
        (pkg/'output'/f'{READY}.restart.{ext}').write_text(ext)
    monkeypatch.setattr(cpd_forcefield, 'package_has_photoproducts', lambda p: True)
    monkeypatch.setattr(cpd_integrator, 'package_hmr_qualified', lambda p: True)
    child = _build_replica(tmp_path, parent, fast=True, timestep_fs=4, hmr=True)
    child_pkg = child.package_dir(tmp_path)
    conf = (child_pkg/'demo_00_reseed.conf').read_text()
    assert ('binVelocities' in conf) is parent_hmr
    assert ('reinitvels' in conf) is (not parent_hmr)
    result = json.loads((child_pkg/'manifest.json').read_text())
    assert result['ensemble']['cpd_mass_change_reseed'] is (not parent_hmr)
    assert result['photoproduct_integrator_policy']['hmr_4fs_validated'] is True


def test_appended_cpd_mass_switch_gets_fresh_velocities(tmp_path, monkeypatch):
    from backend.core.md_protocols import write_hmr_psf
    from tests.test_md_ensemble import _write_minimal_psf

    _write_minimal_psf(tmp_path/'demo.psf')
    write_hmr_psf(tmp_path/'demo.psf', tmp_path/'demo_hmr.psf')
    (tmp_path/'old.conf').write_text('structure demo.psf\n')
    monkeypatch.setattr(cpd_integrator, 'package_hmr_qualified', lambda p: True)
    original = 'seed 731041\nbinVelocities output/old.vel\nrun 1000\n'
    conf, changed = cpd_integrator.reseed_mass_changed_config(
        original, tmp_path, 'old', 'demo_hmr.psf', 300)
    assert changed and 'temperature 300\nrun' in conf and 'binVelocities' not in conf
    conf, changed = cpd_integrator.reseed_mass_changed_config(
        original, tmp_path, 'old', 'demo.psf', 300)
    assert not changed and conf == original


def test_mass_switch_preview_explains_the_new_velocity_ensemble():
    plan = {'continuation': True,
            'conditions': [{'id': 'seed_checkpoint', 'detail': 'old'}],
            'deferred': [{'key': 'seed', 'detail': 'old'}]}
    result = cpd_integrator.describe_mass_switch(plan, True)
    assert not result['continuation'] and result['cpd_mass_change_reseed']
    assert 'fresh velocities' in result['conditions'][0]['title']
    assert 'correlates' in result['deferred'][0]['detail']


def test_cpd_hmr_failure_does_not_downgrade_requested_timestep(tmp_path, monkeypatch):
    from backend.core import cpd_forcefield
    from tests.test_md_ensemble import _make_parent, _build_replica

    parent = _make_parent(tmp_path)  # deliberately unparseable PSF
    monkeypatch.setattr(cpd_forcefield, 'package_has_photoproducts', lambda p: True)
    monkeypatch.setattr(cpd_integrator, 'package_hmr_qualified', lambda p: True)
    with pytest.raises(CpdCapabilityError, match='not downgraded'):
        _build_replica(tmp_path, parent, fast=True, timestep_fs=4, hmr=True)
