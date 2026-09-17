"""Extract junction stability evidence and retain a compact solute trajectory."""
from pathlib import Path
import argparse
import json
import re

import mdtraj as md
import numpy as np
import parmed


def analyze(root):
    root = root.resolve()
    report = json.loads((root / 'gpu_check.json').read_text())
    if report['returncode'] != 0:
        raise ValueError('NAMD did not finish successfully')
    log = (root / 'namd.log').read_text()
    if 'Running with GPU-resident mode' not in log:
        raise ValueError('GPU-resident execution was not verified')
    last = report['last_energy'].split()
    if int(last[1]) != 22000 or not np.isfinite(np.array(last[2:], dtype=float)).all():
        raise ValueError('Run was incomplete or energy was nonfinite')
    structure = parmed.charmm.CharmmPsfFile(str(root / 'system.psf'))
    count = report['solute_atoms']
    identity = {(a.residue.segid, a.residue.number, a.name): a.idx for a in structure.atoms[:count]}
    pairs = [('linker_C_O', ('L000', 1, 'C8T'), ('L000', 1, 'O4T')),
             ('junction_O_P', ('L000', 1, 'O4T'), ('D000', 1, 'P')),
             ('DNA_P_O5', ('D000', 1, 'P'), ('D000', 1, "O5'")),
             ('DNA_O5_C5', ('D000', 1, "O5'"), ('D000', 1, "C5'"))]
    source_dcd = root / 'check.dcd'
    source_top = root / 'system.psf'
    if not source_dcd.exists():
        source_dcd, source_top = root / 'solute.dcd', root / 'solute.pdb'
    traj = md.join(list(md.iterload(str(source_dcd), top=str(source_top),
                                   atom_indices=np.arange(count), chunk=25)))
    if not np.isfinite(traj.xyz).all():
        raise ValueError('Nonfinite trajectory coordinates')
    distances = md.compute_distances(traj, [(identity[a], identity[b]) for _, a, b in pairs], periodic=False)
    # Output includes a pre-minimization frame; report all frames and the MD-only
    # samples separately, identifying the latter from the DCD step header.
    import struct
    header = source_dcd.open('rb')
    with header:
        start = header.read(24)
    endian = '<' if struct.unpack('<i', start[:4])[0] == 84 else '>'
    nset, first, stride = struct.unpack(endian + '3i', start[8:20])
    steps = first + np.arange(traj.n_frames) * stride
    if nset != traj.n_frames:
        raise ValueError('DCD frame count mismatch')
    md_mask = steps > 2000
    if not md_mask.any():
        raise ValueError('No dynamics samples')
    statistics = {name: dict(min_nm=float(distances[md_mask, i].min()),
                             max_nm=float(distances[md_mask, i].max()),
                             mean_nm=float(distances[md_mask, i].mean()),
                             std_nm=float(distances[md_mask, i].std())) for i, (name, _, _) in enumerate(pairs)}
    if not .12 < statistics['junction_O_P']['min_nm'] <= statistics['junction_O_P']['max_nm'] < .20:
        raise ValueError('Junction bond left the broad numerical-check interval')
    ca = [a.idx for a in structure.atoms[:count] if a.residue.segid.startswith('P') and a.name == 'CA']
    aligned = traj[md_mask]
    aligned.superpose(aligned, 0, atom_indices=ca)
    ring = [identity[('L000', 1, name)] for name in ['C2', 'S1', 'C6', 'C5', 'N1', 'C3', 'O3', 'N2', 'C4']]
    ring_rmsd = np.sqrt(np.mean(np.sum((aligned.xyz[:, ring] - aligned.xyz[0, ring])**2, axis=2), axis=1))
    timing = [float(x) for x in re.findall(r'Wall: [\d.]+, ([\d.]+)/step,', log)]
    result = dict(gpu_resident_verified=True, complete_20000_step_run=True,
                  frames=traj.n_frames, md_samples=int(md_mask.sum()), dcd_first_step=int(first),
                  dcd_stride=int(stride), bond_statistics_md=statistics,
                  biotin_ring_max_rmsd_after_protein_alignment_nm=float(ring_rmsd.max()),
                  median_md_seconds_per_step=float(np.median(timing[2:])),
                  simulation_ready=False, qualification='20 ps numerical stability only; no equilibrium or affinity claim')
    # MDTraj's writer supplies a generic time axis. Preserve the source DCD
    # start/stride and CHARMM DELTA fields in the reduced trajectory.
    with source_dcd.open('rb') as source:
        timing_header = source.read(48)
    traj.save_dcd(str(root / 'solute.dcd'))
    with (root / 'solute.dcd').open('r+b') as reduced:
        if reduced.read(4) != timing_header[:4]:
            raise ValueError('Reduced DCD header/endian mismatch')
        reduced.seek(12)
        reduced.write(timing_header[12:20])
        reduced.seek(44)
        reduced.write(timing_header[44:48])
    traj[0].save_pdb(str(root / 'solute.pdb'))
    np.savetxt(root / 'junction_distances.csv', np.column_stack([steps, distances]), delimiter=',',
               header='step,' + ','.join(name+'_nm' for name, _, _ in pairs), comments='')
    (root / 'trajectory_analysis.json').write_text(json.dumps(result, indent=2)+'\n')
    return result


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('directory', type=Path)
    print(json.dumps(analyze(p.parse_args().directory), indent=2))
