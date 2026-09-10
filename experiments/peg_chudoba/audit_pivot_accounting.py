"""Offline check of the pivot affected-term accounting on saved N275 chains.

This tests the mathematical subset rule, not native cell-list maintenance or
the native Metropolis branch. It launches no simulations and changes no inputs.
"""
import hashlib
import json
from pathlib import Path

import numpy as np

from tools.oxdna_peg.chudoba_reference import bonded_energy, chain_energy, pair_energy_derivative


def local_energy(xyz, moved):
    n = len(xyz)
    # Engine owner bond i owns the bond, angle and torsion starting at i.
    owners = {i for p in moved for i in range(max(0, p-3), min(p+1, n-1))}
    energy = 0.
    for i in sorted(owners):
        fragment = xyz[i:min(i+4, n)]
        energy += bonded_energy(fragment)
        if len(fragment) > 2:
            energy -= bonded_energy(fragment[1:])
    # An independent exhaustive search substitutes for the native cell list.
    # Re-evaluate neighbors at each endpoint to include cutoff crossings.
    pairs = {(min(p, q), max(p, q)) for p in moved for q in range(n)
             if abs(p-q) > 1 and np.linalg.norm(xyz[p]-xyz[q]) < .9}
    for p, q in sorted(pairs):
        energy += pair_energy_derivative(np.linalg.norm(xyz[p]-xyz[q]), 320, zero_tail=True)[0]
    return energy, pairs


def main():
    root = Path(__file__).parent
    comparison = json.loads((root/'n275_t320_discrepancy.json').read_text())['comparison']
    rng = np.random.default_rng(20260910)
    checks = []
    for directory in comparison['directories']:
        path = Path(directory)/'last_conf.dat'
        xyz = np.loadtxt(path, skiprows=3)[:, :3]*.8518
        full_before = chain_energy(xyz, 320, zero_tail=True)
        for pivot, direction, angle in [(1, 1, .15), (137, 1, .65), (137, -1, -.65), (273, -1, .15)]:
            moved = list(range(pivot+1, len(xyz))) if direction == 1 else list(range(pivot))
            axis = rng.normal(size=3)
            axis /= np.linalg.norm(axis)
            v = xyz[moved]-xyz[pivot]
            trial = xyz.copy()
            trial[moved] = (v*np.cos(angle) + np.cross(axis, v)*np.sin(angle)
                            + np.outer(v@axis, axis)*(1-np.cos(angle)) + xyz[pivot])
            before, old_pairs = local_energy(xyz, moved)
            after, new_pairs = local_energy(trial, moved)
            full_delta = chain_energy(trial, 320, zero_tail=True)-full_before
            local_delta = after-before
            error = local_delta-full_delta
            assert abs(error) < 1e-7 + 1e-11*abs(full_delta), (directory, pivot, error)
            checks.append(dict(directory=directory,configuration_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                pivot=pivot,direction=direction,angle_radians=angle,full_delta_kj_mol=full_delta,
                local_delta_kj_mol=local_delta,error_kj_mol=error,
                pairs_entering_cutoff=len(new_pairs-old_pairs),pairs_leaving_cutoff=len(old_pairs-new_pairs)))
    result = dict(seed=20260910,checks=checks,maximum_absolute_error_kj_mol=max(abs(c['error_kj_mol']) for c in checks),
        scope='Offline affected-owner and pair-deduplication accounting; not native neighbor-list or acceptance execution.',
        script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    (root/'pivot_accounting_audit.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({k:v for k,v in result.items() if k != 'checks'}))


if __name__ == '__main__':
    main()
