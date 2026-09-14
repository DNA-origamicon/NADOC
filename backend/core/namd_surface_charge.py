"""Fixed charge on a periodic restrained wall; not a silica/electrode model.

Sigma denotes total sheet charge per projected cell area (both exposed faces
share its screening cloud). Integer total charge permits explicit neutralization.
"""
import math

E_PER_NM2_TO_C_M2 = 0.1602176634
REFERENCE = 'https://doi.org/10.7567/JJAP.57.04FM02'


def charge_plan(spec, box_nm, n_sites):
    sigma = float(spec.get('charge_density_C_m2', 0))
    if not math.isfinite(sigma) or abs(sigma) > 0.5:
        raise ValueError('Surface charge density must be finite and within ±0.5 C/m²')
    if not sigma:
        return None
    if n_sites < 1 or spec.get('pore_diameter_nm', 0) != 0 or spec.get('layers', 1) != 1:
        raise ValueError('Charged screening control requires one closed wall layer (pore = 0)')
    normal = spec['dir']
    axis = max(range(3), key=lambda i: abs(normal[i]))
    if not math.isclose(abs(normal[axis]), 1, abs_tol=1e-8):
        raise ValueError('Charged screening wall requires a Cartesian normal')
    area = math.prod(float(box_nm[i]) for i in range(3) if i != axis)
    requested = sigma * area / E_PER_NM2_TO_C_M2
    charge = int(math.copysign(math.floor(abs(requested) + 0.5), requested))
    if charge == 0:
        raise ValueError('Requested surface charge rounds to zero; enlarge the lateral cell or increase charge density')
    # Match the PSF six-decimal representation, conserving integer total exactly.
    micro, remainder = divmod(charge * 1_000_000, n_sites)
    return dict(model='periodic_fixed_charge_sheet_v1', requested_C_m2=sigma,
                realized_C_m2=charge * E_PER_NM2_TO_C_M2 / area,
                area_nm2=area, total_charge_e=charge, n_sites=n_sites,
                site_charge_e=micro / 1e6, remainder_sites=remainder,
                charge_convention='total_sheet_charge_per_projected_area',
                electrostatics='3D PME periodic membrane stack; two solvent-exposed faces',
                reference=REFERENCE, exact_literature_reproduction=False)


def site_charges(plan):
    return [(round(plan['site_charge_e'] * 1e6) + (i < plan['remainder_sites'])) / 1e6
            for i in range(plan['n_sites'])]


def charge_psf(text, plan):
    if plan is None:
        return text
    charges = iter(site_charges(plan))
    lines = text.splitlines(keepends=True)
    start = next(i for i, s in enumerate(lines) if '!NATOM' in s)
    n = int(lines[start].split()[0])
    count = 0
    for i in range(start + 1, start + n + 1):
        fields = lines[i].split()
        if fields[3] == 'GRP':
            fields[6] = f'{next(charges):.6f}'
            lines[i] = ' '.join(fields) + '\n'
            count += 1
    if count != plan['n_sites']:
        raise ValueError('Wall charge map does not match PSF site count')
    return ''.join(lines)


def validate_charged_sites(values, plan):
    expected = site_charges(plan) if plan else [0.] * len(values)
    if len(values) != len(expected) or any(abs(a-b) > 1e-8 for a,b in zip(values, expected)):
        raise ValueError('Wall PSF charges differ from the saved surface charge map; rebuild this job')
