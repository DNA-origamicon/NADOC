"""Asset-specific numerical qualification of the CPD fast integrator.

This does not promote force-field scientific release or relax geometry gates.
Unqualified/changed parameter sets retain the ordinary-mass <=2 fs policy.
"""
from __future__ import annotations

import json
import re
from itertools import zip_longest
from pathlib import Path

EVIDENCE = Path(__file__).parents[1] / 'data/forcefield/cpd_hmr_validation.json'


def assets_hmr_qualified(assets: list[dict]) -> bool:
    """Require the exact parameter/topology identities of a passing native panel."""
    try:
        evidence = json.loads(EVIDENCE.read_text())
        if evidence['schema'] != 'nadoc.cpd-hmr-qualification.v1':
            return False
        if evidence['independent_audit_passed'] is not True:
            return False
        identities = {(a['product_id'], a['kind'], a['sha256']) for a in assets
                      if a['kind'] in {'parameters', 'topology', 'chemical_definition'}}
        products = {a['product_id'] for a in assets}
        if len(products) != 1 or not identities:
            return False
        for product in products:
            qualified = evidence['products'][product]
            expected = {(product, a['kind'], a['sha256']) for a in qualified['assets']
                        if a['kind'] in {'parameters', 'topology', 'chemical_definition'}}
            if {x for x in identities if x[0] == product} != expected:
                return False
            pairs = qualified['pairs']
            if ({p['start'] for p in pairs} != {'reseed', 'production_endpoint'}
                    or len(pairs) != 2 or not all(p['passed'] is True for p in pairs)):
                return False
        return True
    except (OSError, ValueError, KeyError, TypeError):
        return False


def design_hmr_qualified(design) -> bool:
    from backend.core.cpd_forcefield import photoproduct_package_assets

    return assets_hmr_qualified(photoproduct_package_assets(design))


def package_hmr_qualified(package_dir: Path) -> bool:
    from backend.core.cpd_forcefield import packaged_photoproduct_manifest

    manifest = packaged_photoproduct_manifest(package_dir)
    return bool(manifest and assets_hmr_qualified(manifest.get('assets', [])))


def validate_design_integrators(design, *, relax_dt, relax_hmr, relax_rigid,
                               production_dt, production_hmr, production_rigid):
    """Validate the two requested base integrators; softer ladder tiers stay separate."""
    from backend.core.cpd_forcefield import CpdCapabilityError
    from backend.core.md_integrator import resolve_integrator

    for label, dt, hmr, rigid in (
        ('relaxation', relax_dt, relax_hmr, relax_rigid),
        ('production', production_dt, production_hmr, production_rigid),
    ):
        choice = resolve_integrator(dt, rigid_bonds=rigid, hmr=hmr)
        if (dt > 2 or choice.hmr) and not (
            dt == 4 and choice.hmr and choice.rigid_bonds == 'all'
        ):
            raise CpdCapabilityError(
                f'Qualified CPD {label} fast integration requires 4 fs, HMR and '
                'rigidBonds all; ordinary-mass <=2 fs remains available.'
            )


def _mass_records(path: Path):
    # A protocol preview must not allocate two complete million-atom PSF graphs.
    with path.open() as stream:
        for line in stream:
            if '!NATOM' in line:
                count = int(line.split()[0])
                break
        else:
            raise ValueError('PSF is missing NATOM')
        for index in range(1, count+1):
            fields = next(stream, '').split()
            if len(fields) < 8 or int(fields[0]) != index:
                raise ValueError('PSF atom count/order is invalid')
            yield tuple(fields[:5]), float(fields[7])


def checkpoint_mass_changed(package_dir: Path, checkpoint: str, target_psf: str | Path) -> bool:
    """Compare actual PSF masses before reusing CPD checkpoint velocities."""
    from backend.core.cpd_forcefield import CpdCapabilityError
    try:
        conf = (package_dir / f'{checkpoint}.conf').read_text()
        name = re.search(r'^\s*structure\s+(\S+)', conf, re.M | re.I).group(1)
        changed = False
        for a, b in zip_longest(_mass_records(package_dir/name), _mass_records(package_dir/target_psf)):
            if a is None or b is None or a[0] != b[0]:
                raise ValueError('checkpoint and requested PSFs have different atom identities')
            changed |= a[1] != b[1]
        return changed
    except (OSError, ValueError, AttributeError) as exc:
        raise CpdCapabilityError(f'Cannot establish CPD checkpoint masses: {exc}') from exc


def reseed_mass_changed_config(conf: str, package_dir: Path, checkpoint: str,
                              target_psf: str, temperature: float) -> tuple[str, bool]:
    if not package_hmr_qualified(package_dir):
        return conf, False
    changed = checkpoint_mass_changed(package_dir, checkpoint, target_psf)
    if changed:
        conf, count = re.subn(r'^\s*binVelocities\s+.*$',
                             f'temperature {temperature:g}', conf, flags=re.M | re.I)
        if count != 1:
            from backend.core.cpd_forcefield import CpdCapabilityError
            raise CpdCapabilityError('CPD mass switch requires exactly one velocity input to reseed')
    return conf, changed


def mass_switch_requested(package_dir: Path, checkpoint: str, name_stem: str,
                          requested_hmr: bool) -> bool:
    """Preview without preparing an HMR PSF or altering any package."""
    if not package_hmr_qualified(package_dir):
        return False
    source_hmr = checkpoint_mass_changed(package_dir, checkpoint, f'{name_stem}.psf')
    return source_hmr != requested_hmr


def describe_mass_switch(plan: dict, changed: bool) -> dict:
    if not changed:
        return plan
    plan['continuation'] = False
    plan['cpd_mass_change_reseed'] = True
    detail = ('Coordinates and cell come from the parent. Changing CPD masses draws '
              'fresh velocities at the target temperature. This starts a new velocity '
              'ensemble; the shared starting conformation still correlates the runs.')
    for condition in plan['conditions']:
        if condition['id'] == 'seed_checkpoint':
            prior_warning = condition.get('detail', '') if condition.get('kind') == 'warning' else ''
            condition.update(title='CPD mass change: fresh velocities',
                             detail=f'{detail} {prior_warning}'.strip())
    for deferred in plan['deferred']:
        if deferred['key'] == 'seed':
            deferred.update(title='A new velocity seed is drawn at creation', detail=detail)
    return plan
