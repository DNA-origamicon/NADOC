"""Bounded local CUDA smoke check of the isolated solvated junction complex.

This is numerical/short-time stability evidence, not affinity qualification.
"""
from pathlib import Path
import argparse
import json
import os
import re
import subprocess
import sys
import time

import numpy as np
import parmed

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from backend.core.namd_solvate import _gmx_solvate, _place_ions, _extend_psf, _build_solvated_pdb
from experiments.strep_biotin_namd.prepare_parameterization import dump, digest
from experiments.strep_biotin_namd.build_dna_junction import parameter_set


def run(complex_path, package, junction, output, namd):
    complex_path, package, junction, output, namd = [p.resolve() for p in (complex_path, package, junction, output, namd)]
    subprocess.run(['nvidia-smi', '--query-gpu=name', '--format=csv,noheader'], check=True, capture_output=True)
    output.mkdir(parents=True, exist_ok=False)
    prep = output / 'solvation_work'
    prep.mkdir()
    pdb = (complex_path / 'system.pdb').read_text()
    psf = (complex_path / 'system.psf').read_text()
    s = parmed.charmm.CharmmPsfFile(str(complex_path / 'system.psf'))
    q = sum(a.charge for a in s.atoms)
    if abs(q-round(q)) > 1e-6:
        raise ValueError('Solute charge is not integral')
    waters, box, centered = _gmx_solvate(pdb, 1.5, prep, box_mode='bbox')
    pairs = round(.15 * .602214076 * np.prod(box))
    n_na, n_cl = pairs + max(0, -round(q)), pairs + max(0, round(q))
    waters, na, cl = _place_ions(waters, n_na, n_cl, seed=20260916)
    (output / 'system.psf').write_text(_extend_psf(psf, waters, na, cl))
    (output / 'system.pdb').write_text(_build_solvated_pdb(centered, waters, na, cl, box, len(s.atoms)))
    ff = package / 'reference_forcefield'
    solvated = parmed.charmm.CharmmPsfFile(str(output / 'system.psf'))
    # NAMD requires LJ definitions even for types mentioned only by an unused
    # NBFIX. Drop pairs that cannot occur, without dummy types or changing any
    # pair correction between atoms actually present in this system.
    active_types = {a.type for a in solvated.atoms}
    water_source = ROOT / 'backend/data/forcefield/toppar_water_ions_cufix.str'
    kept, removed, nbfix = [], [], False
    for line in water_source.read_text().splitlines():
        fields = line.split('!')[0].split()
        if fields and fields[0].upper() == 'NBFIX':
            nbfix = True
        elif fields and fields[0].upper() in ('END', 'RETURN', 'HBOND', 'NONBONDED'):
            nbfix = False
        elif nbfix and len(fields) >= 4 and not set(fields[:2]) <= active_types:
            removed.append(fields[:2])
            continue
        kept.append(line)
    water_file = output / 'water_ions_active.str'
    water_file.write_text('\n'.join(kept)+'\n')
    dump(output / 'nbfix_filter.json', dict(source_sha256=digest(water_source),
         active_types=sorted(active_types), removed_absent_type_pairs=removed,
         rule='Keep every NBFIX pair whose two atom types are present.'))
    ff_files = [ff / 'par_all36_na.prm', ff / 'par_all36m_prot.prm', ff / 'par_all36_cgenff.prm',
                package / 'BTMP.str', junction / 'biotin_teg_boundary.prm', water_file]
    # The general CGenFF library also contains cross-family NBFIX references
    # (e.g. carbohydrate types), so apply the same presence rule to every file.
    active_ff = output / 'forcefield'
    active_ff.mkdir()
    filter_records = []
    for index, source in enumerate(ff_files):
        lines, dropped, in_nbfix = [], [], False
        for line in source.read_text().splitlines():
            fields = line.split('!')[0].split()
            if fields and fields[0].upper() == 'NBFIX':
                in_nbfix = True
            elif fields and fields[0].upper() in ('END', 'RETURN', 'HBOND', 'NONBONDED'):
                in_nbfix = False
            elif in_nbfix and len(fields) >= 4 and not set(fields[:2]) <= active_types:
                dropped.append(fields[:2])
                continue
            lines.append(line)
        destination = active_ff / source.name
        destination.write_text('\n'.join(lines)+'\n')
        filter_records.append(dict(source=str(source), source_sha256=digest(source),
                                   active_sha256=digest(destination), removed_absent_type_pairs=dropped))
        ff_files[index] = destination
    dump(output / 'active_forcefield_provenance.json', filter_records)
    solvated.load_parameters(parameter_set(*ff_files))
    if abs(sum(a.charge for a in solvated.atoms)) > 1e-5:
        raise ValueError('Solvated system is not neutral')
    box_a = np.array(box) * 10
    config = '\n'.join(['structure system.psf', 'coordinates system.pdb', 'paraTypeCharmm on'] +
                        [f'parameters {{{p}}}' for p in ff_files])
    config += f'''
GPUresident on
exclude scaled1-4
1-4scaling 1.0
switching on
switchdist 10
cutoff 12
pairlistdist 14
PME on
PMEGridSpacing 1
cellBasisVector1 {box_a[0]} 0 0
cellBasisVector2 0 {box_a[1]} 0
cellBasisVector3 0 0 {box_a[2]}
cellOrigin {box_a[0]/2} {box_a[1]/2} {box_a[2]/2}
temperature 300
seed 20260916
timestep 1.0
rigidBonds all
nonbondedFreq 1
fullElectFrequency 2
stepspercycle 20
langevin on
langevinTemp 300
langevinDamping 1
langevinHydrogen off
wrapAll off
outputName check
outputEnergies 100
outputTiming 1000
DCDfile check.dcd
DCDfreq 100
restartfreq 1000
minimize 2000
reinitvels 300
run 20000
'''
    (output / 'check.conf').write_text(config)
    start = time.monotonic()
    with (output / 'namd.log').open('w') as log:
        try:
            proc = subprocess.run([str(namd), '+p4', '+devices', '0', 'check.conf'], cwd=output,
                                  stdout=log, stderr=subprocess.STDOUT, timeout=240,
                                  env={**os.environ, 'CUDA_VISIBLE_DEVICES': '0'})
            code = proc.returncode
        except subprocess.TimeoutExpired:
            code = 'timeout_240s'
    elapsed = time.monotonic()-start
    text = (output / 'namd.log').read_text()
    gpu_lines = [line for line in text.splitlines() if re.search(r'GPU|CUDA', line)]
    energies = [line for line in text.splitlines() if line.startswith('ENERGY:')]
    report = dict(status='numerical_check_completed' if code == 0 else 'numerical_check_failed',
                  simulation_ready=False, returncode=code, elapsed_seconds=elapsed,
                  atoms=len(solvated.atoms), solute_atoms=len(s.atoms), water_molecules=len(waters),
                  sodium=n_na, chloride=n_cl, box_nm=box, gpu_log_evidence=gpu_lines,
                  intended_md_steps=20000, intended_md_ps=20, last_energy=energies[-1] if energies else None,
                  forcefield_sha256={str(p): digest(p) for p in ff_files},
                  limitation='Short GPU numerical check; no claim of binding affinity, lifetime, or equilibrium conformational accuracy.')
    dump(output / 'gpu_check.json', report)
    # Solvation scratch has no continuing purpose; final solvated input is retained.
    import shutil
    shutil.rmtree(prep)
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--complex', type=Path, required=True)
    parser.add_argument('--package', type=Path, required=True)
    parser.add_argument('--junction', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--namd', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(run(args.complex, args.package, args.junction, args.output, args.namd), indent=2))
