"""Neutral-cell Yeh–Berkowitz correction for fixed-volume orthorhombic PME.

Coordinates Å, charges e, energies kcal/mol. This is EW3DC with vacuum padding,
not an exact 2D Ewald solver. Convergence against vacuum height is mandatory.
Reference: Yeh & Berkowitz, JCP 111, 3155 (1999), doi:10.1063/1.479595.
"""
import math

COULOMB = 332.0636  # NAMD common.h, dielectric=1


def validate_slab(charges, cell_angstrom, axis):
    if axis not in (0, 1, 2) or len(cell_angstrom) != 3:
        raise ValueError('Slab requires an orthorhombic cell and Cartesian normal')
    if not charges or any(not math.isfinite(q) for q in charges):
        raise ValueError('Slab charges must be finite and nonempty')
    if abs(math.fsum(charges)) > 1e-6:
        raise ValueError('Slab correction requires explicit cell neutrality, including electrodes')
    if any(not math.isfinite(v) or v <= 0 for v in cell_angstrom):
        raise ValueError('Slab cell dimensions must be positive and finite')


def slab_energy_forces(positions, charges, cell_angstrom, axis=2):
    validate_slab(charges, cell_angstrom, axis)
    if len(positions) != len(charges) or any(len(p) != 3 or any(not math.isfinite(v) for v in p) for p in positions):
        raise ValueError('Coordinates must match the charge map')
    dipole = math.fsum(q * p[axis] for q, p in zip(charges, positions))
    coefficient = 2 * math.pi * COULOMB / math.prod(cell_angstrom)
    forces = [[0., 0., 0.] for _ in charges]
    for force, q in zip(forces, charges):
        force[axis] = -2 * coefficient * q * dipole
    return coefficient * dipole**2, forces


def render_slab_tcl(charges, cell_angstrom, axis=2, *, mobile_ids=(), bounds=None, wall_k=10.):
    """Complete TclForces callback: correction on ALL charges plus optional confinement.

    Atom IDs are one-based. bounds are inner wall coordinates in Å. Harmonic
    confinement uses U=0.5*k*penetration²; it is separate from electrode restraints.
    No virial/barostat support: callers must run fixed-volume NVT/NVE.
    """
    validate_slab(charges, cell_angstrom, axis)
    mobile_ids = list(mobile_ids)
    if len(set(mobile_ids)) != len(mobile_ids) or any(i < 1 or i > len(charges) for i in mobile_ids):
        raise ValueError('Invalid mobile atom map')
    if mobile_ids and (bounds is None or len(bounds) != 2 or not all(math.isfinite(v) for v in bounds) or not 0 < bounds[0] < bounds[1] < cell_angstrom[axis]):
        raise ValueError('Confinement must lie inside the padded cell')
    if not math.isfinite(wall_k) or wall_k <= 0:
        raise ValueError('Confinement stiffness must be positive')
    selected = sorted(set(i+1 for i,q in enumerate(charges) if q) | set(mobile_ids))
    charge_map = ' '.join(f'{i+1} {q:.12g}' for i,q in enumerate(charges) if q)
    low, high = bounds if bounds is not None else (0, cell_angstrom[axis])
    return f'''# NADOC EW3DC v1; ALL PSF charges; fixed cell; no coordinate wrapping.
set slab_charges {{{charge_map}}}
set slab_mobile {{{' '.join(map(str,mobile_ids))}}}
set slab_axis {axis}
set slab_coefficient {2 * math.pi * COULOMB / math.prod(cell_angstrom):.17g}
set slab_low {low:.12g}
set slab_high {high:.12g}
set slab_wall_k {wall_k:.12g}
foreach atom {{{' '.join(map(str,selected))}}} {{ addatom $atom }}
proc calcforces {{}} {{
    global slab_charges slab_mobile slab_axis slab_coefficient slab_low slab_high slab_wall_k
    loadcoords xyz
    set dipole 0.0
    foreach {{atom charge}} $slab_charges {{
        set dipole [expr {{$dipole + $charge * [lindex $xyz($atom) $slab_axis]}}]
    }}
    addenergy [expr {{$slab_coefficient * $dipole * $dipole}}]
    foreach {{atom charge}} $slab_charges {{
        set force {{0.0 0.0 0.0}}
        lset force $slab_axis [expr {{-2.0 * $slab_coefficient * $charge * $dipole}}]
        addforce $atom $force
    }}
    foreach atom $slab_mobile {{
        set z [lindex $xyz($atom) $slab_axis]
        set delta 0.0
        if {{$z < $slab_low}} {{ set delta [expr {{$z - $slab_low}}] }}
        if {{$z > $slab_high}} {{ set delta [expr {{$z - $slab_high}}] }}
        if {{$delta != 0.0}} {{
            set force {{0.0 0.0 0.0}}
            lset force $slab_axis [expr {{-$slab_wall_k * $delta}}]
            addforce $atom $force
            addenergy [expr {{0.5 * $slab_wall_k * $delta * $delta}}]
        }}
    }}
}}
'''
