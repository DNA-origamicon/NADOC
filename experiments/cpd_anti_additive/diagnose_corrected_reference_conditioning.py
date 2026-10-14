"""Bounded fixed-geometry density-fitting conditioning diagnostic."""
import os
from pathlib import Path
import sys
import time
import numpy as np

REPO = Path(os.environ.get('NADOC_REPO_ROOT', Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(REPO))
from experiments.cpd_anti_additive.corrected_core_stage1 import (
    read, save, checked, pin, now, native_audit, geometry_audit, stationary,
)
from experiments.cpd_anti_additive.audit_corrected_core_stage1 import parse_native_table


def run(root):
    import psi4
    os.chdir(root)
    plan = read(root/'plan.json')
    for source in plan['sources']:
        checked(source)
    if checked(plan['worker']) != Path(__file__).resolve():
        raise ValueError('Executed worker changed')
    original = read(checked(plan['source_options']))
    stage = read(checked(plan['source_stage1']))
    old = read(checked(stage['final_result']))
    schema = read(checked(plan['qcschema_input']))
    x = np.load(checked(stage['final_binary_geometry']))
    with (root/'started.json').open('x') as f:
        f.write(now()+'\n')
    results = []
    for case in plan['cases']:
        start = time.monotonic()
        psi4.core.clean(); psi4.core.clean_options(); psi4.core.clean_variables()
        psi4.set_memory('4 GiB'); psi4.set_num_threads(4)
        psi4.core.IOManager.shared_object().set_default_path(str(root/'scratch'))
        options = {**original['options'], **plan['option_changes']}
        psi4.set_options(options)
        output = root/(case+'.dat'); psi4.set_output_file(str(output), False)
        if case == 'text-15-decimals':
            lines = '\n'.join(el+' '+' '.join(f'{v:.15f}' for v in pos)
                              for el, pos in zip(original['elements'], x))
            mol = psi4.geometry('0 1\n'+lines+'\nunits bohr\nsymmetry c1\nno_com\nno_reorient')
        else:
            mol = psi4.core.Molecule.from_schema(schema['molecule'], nonphysical=True)
        grad, wfn = psi4.gradient('mp2', molecule=mol, return_wfn=True)
        g = np.asarray(grad); e = float(wfn.energy()); psi4.core.flush_outfile()
        native = native_audit(output.read_text(), e, g)
        table_e, table_g = parse_native_table(output.read_text(), len(x))
        if np.max(abs(table_g-g)) > 1e-11 or abs(e-table_e) > 1e-9:
            raise ValueError('Native output/result discrepancy')
        actual_x = np.asarray(wfn.molecule().geometry())
        if np.max(abs(actual_x-x)) > 1e-14 or not geometry_audit(actual_x, original)['passed']:
            raise ValueError('Geometry changed')
        row = dict(case=case, options=options, energy_hartree=e, gradient=g.tolist(),
                   native=native, stationary=stationary(native), output=pin(output),
                   returned_geometry_bohr=actual_x.tolist(),
                   old_energy_delta=e-old['energy_hartree'],
                   old_gradient_max_delta=float(np.max(abs(g-np.array(old['gradient_hartree_bohr'])))),
                   seconds=time.monotonic()-start)
        save(root/(case+'.json'), row); results.append(row)
        print({k: row[k] for k in ['case','old_energy_delta','old_gradient_max_delta','stationary','seconds']}, flush=True)
    energies = [r['energy_hartree'] for r in results]
    gs = [np.array(r['gradient']) for r in results]
    delta = max(float(np.max(abs(a-b))) for a in gs for b in gs)
    save(root/'assessment.json', dict(at=now(), completed=True, new_gradients=len(results),
         results=[pin(root/(c+'.json')) for c in plan['cases']],
         energy_spread_hartree=max(energies)-min(energies),
         maximum_pairwise_gradient_difference_au=delta,
         reproducibility_pass=delta <= plan['gradient_reproducibility_limit_au'],
         all_stationary=all(r['stationary'] for r in results),
         minimum_certified=False, gate_effect='none'))
    psi4.core.clean()


if __name__ == '__main__':
    run(Path(sys.argv[1]).resolve())
