"""Isolated same-topology whole-Corner closure candidate, never production.

The unchanged source is natively recorded. Only derived atom coordinates move;
atom identities, bonds, sequences and the authored insertion counts are retained.
Sequential passes include every other current seam in the fixed environment.
Exact whole-model ring and contact validation remains independent of fitting.
"""

from dataclasses import replace

import numpy as np

from backend.core.atomistic import AtomisticModel
from experiments.corner_seam_candidate import candidate_atoms, PROCESS as FRAME_PROCESS
from experiments.corner_seam_closure import close_component

PROVIDER = 'corner-joint-seam-closure-diagnostic-v1'
PROCESS = [*FRAME_PROCESS,
    'Keep the natively recorded insertion counts, atom identities, sequence and connectivity.',
    'Optimize each existing seam with rigid insert rings and flexible phosphate atoms in the complete current atom environment.',
    'Repeat in recorded seam order twice; retain all duplex rigid atoms and all preceding seam updates.',
    'Measure exact whole-model clashes, covalent distances and ring piercings independently of the optimization.',
]


def closed_candidate_atoms(design, *, passes=2):
    if passes not in (1, 2):
        raise ValueError('The diagnostic is bounded to one or two passes.')
    model = candidate_atoms(design)
    for _ in range(passes):
        for link in design.forced_ligations:
            if not link.extra_bases:
                continue
            endpoints = {(getattr(link, end+'_helix_id'), getattr(link, end+'_bp'),
                          getattr(link, end+'_direction').value) for end in ('three_prime', 'five_prime')}
            ids = [a.serial for a in model.atoms if a.crossover_id == link.id
                   or (not a.crossover_id and not a.copy_k
                       and (a.helix_id, a.bp_index, a.direction) in endpoints)]
            mapping = {serial: i for i, serial in enumerate(ids)}
            local = AtomisticModel(atoms=[replace(model.atoms[serial], serial=i) for i, serial in enumerate(ids)],
                bonds=[(mapping[i], mapping[j]) for i, j in model.bonds if i in mapping and j in mapping])
            environment = [[a.x, a.y, a.z] for a in model.atoms if a.serial not in mapping]
            close_component(local, environment=environment)
            for serial, atom in zip(ids, local.atoms):
                model.atoms[serial].x, model.atoms[serial].y, model.atoms[serial].z = atom.x, atom.y, atom.z
    if not np.isfinite([[a.x, a.y, a.z] for a in model.atoms]).all():
        raise ValueError('Nonfinite closed candidate.')
    return model
