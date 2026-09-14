"""Repulsive planar slit for an isolated, GPU-resident NAMD PEG qualification.

U = k * penetration_A**2 per atom; k has NAMD restraint units kcal/mol/A^2.
This finite-stiffness barrier has no adsorption, material identity or wall atoms.
The opposing plane closes the normal periodic boundary; NVT is required.
"""
from dataclasses import dataclass

import numpy as np

from backend.core.surface_transforms import SurfaceFrame


@dataclass(frozen=True)
class RepulsiveSlit:
    box_nm: tuple = (4.8, 4.8, 4.8)
    axis: int = 2
    inset_nm: float = 0.2
    k_kcal_mol_A2: float = 10.0

    def __post_init__(self):
        box = np.asarray(self.box_nm, dtype=float)
        if box.shape != (3,) or not np.isfinite(box).all() or np.any(box <= 0):
            raise ValueError('box_nm must contain three finite positive lengths')
        if type(self.axis) is not int or self.axis not in (0, 1, 2):
            raise ValueError('axis must be 0, 1 or 2')
        if not np.isfinite(self.inset_nm) or not 0 < 2*self.inset_nm < box[self.axis]:
            raise ValueError('inset must leave a nonempty allowed slit')
        if not np.isfinite(self.k_kcal_mol_A2) or self.k_kcal_mol_A2 <= 0:
            raise ValueError('wall stiffness must be finite and positive')
        object.__setattr__(self, 'box_nm', tuple(box))

    @property
    def frames(self):
        normal = np.eye(3)[self.axis]
        tangent = np.eye(3)[(self.axis + 1) % 3]
        return (SurfaceFrame(normal*self.inset_nm, normal, tangent),
                SurfaceFrame(normal*(self.box_nm[self.axis]-self.inset_nm), -normal, tangent))

    def energy_forces(self, xyz_A):
        """Analytic oracle; total kcal/mol and per-atom kcal/mol/A forces."""
        xyz = np.asarray(xyz_A, dtype=float)
        if xyz.ndim != 2 or xyz.shape[1] != 3 or not np.isfinite(xyz).all():
            raise ValueError('coordinates must be finite N by 3 angstroms')
        wrapped_nm = np.mod(xyz / 10, self.box_nm)
        force = np.zeros_like(xyz)
        energy = 0.0
        for frame in self.frames:
            penetration_A = np.minimum(frame.signed_distance(wrapped_nm)*10, 0)
            energy += self.k_kcal_mol_A2 * float(penetration_A @ penetration_A)
            force += (-2*self.k_kcal_mol_A2*penetration_A[:, None]) * frame.normal
        return energy, force

    def tcl_forces(self, atom_ids):
        """NAMD TclForces: one-based IDs, every selected atom, every step.

        Host callbacks preserve GPUresident integration but have transfer overhead.
        Explicit modulo coordinates make the wall invariant to image wrapping.
        """
        ids = list(atom_ids)
        if not ids or any(type(i) is not int or i < 1 for i in ids) or len(set(ids)) != len(ids):
            raise ValueError('wall atom IDs must be nonempty, unique positive integers')
        return f'''# Generated repulsive slit; requires fixed orthorhombic NVT cell at origin L/2.
set peg_wall_ids {{{' '.join(map(str, ids))}}}
foreach id $peg_wall_ids {{ addatom $id }}
proc calcforces {{}} {{
    global peg_wall_ids
    loadcoords xyz
    set energy 0.0
    foreach id $peg_wall_ids {{
        set q [lindex $xyz($id) {self.axis}]
        set L {self.box_nm[self.axis]*10:.12g}
        set q [expr {{$q - $L*floor($q/$L)}}]
        set lo {self.inset_nm*10:.12g}
        set hi {10*(self.box_nm[self.axis]-self.inset_nm):.12g}
        set d 0.0
        if {{$q < $lo}} {{ set d [expr {{$q-$lo}}] }}
        if {{$q > $hi}} {{ set d [expr {{$q-$hi}}] }}
        if {{$d != 0.0}} {{
            set f {{0.0 0.0 0.0}}
            lset f {self.axis} [expr {{-2.0*{self.k_kcal_mol_A2:.12g}*$d}}]
            addforce $id $f
            set energy [expr {{$energy+{self.k_kcal_mol_A2:.12g}*$d*$d}}]
        }}
    }}
    addenergy $energy
}}
'''


def harmonic_graft_block(k_kcal_mol_A2):
    """Native 3D positional spring: U=k|r-r0|², never fixedAtoms or a fake bond."""
    if not np.isfinite(k_kcal_mol_A2) or not 0 < k_kcal_mol_A2 <= 999.99:
        raise ValueError('graft stiffness must fit the positive PDB beta field')
    return f'''constraints on
consref grafts.pdb
conskfile grafts.pdb
conskcol B
consexp 2
constraintScaling {k_kcal_mol_A2:.12g}
'''
