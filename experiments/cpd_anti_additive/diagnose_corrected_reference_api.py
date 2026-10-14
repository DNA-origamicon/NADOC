"""Two bounded fixed-geometry API diagnostics; never silently relax audit tolerances."""
import os
from pathlib import Path
import sys
import time
import numpy as np

REPO=Path(os.environ.get('NADOC_REPO_ROOT',Path(__file__).resolve().parents[2]))
sys.path.insert(0,str(REPO))
from experiments.cpd_anti_additive.corrected_core_stage1 import read,save,checked,pin,now,native_audit


def run(root):
    import psi4
    os.chdir(root)
    plan=read(root/'plan.json')
    for key in ['authorization','failed_batch','source_stage1','source_options','qcschema_input','qcschema_result']:
        checked(plan[key])
    with (root/'started.json').open('x') as f:f.write(now()+'\n')
    original=read(checked(plan['source_options']))
    audit=read(checked(plan['source_stage1']))
    old=read(checked(audit['final_result']))
    schema=read(checked(plan['qcschema_input']))
    previous=read(checked(plan['qcschema_result']))
    x=np.load(checked(audit['final_binary_geometry']))
    results=[]
    for case in ['direct-text-15-decimals','direct-schema']:
        start=time.monotonic()
        psi4.core.clean();psi4.core.clean_options();psi4.core.clean_variables()
        psi4.set_memory('4 GiB');psi4.set_num_threads(4)
        psi4.core.IOManager.shared_object().set_default_path(str(root/'scratch'))
        psi4.set_options(original['options'])
        output=root/(case+'.dat');psi4.set_output_file(str(output),False)
        if case=='direct-text-15-decimals':
            lines='\n'.join(el+' '+' '.join(f'{v:.15f}' for v in pos) for el,pos in zip(original['elements'],x))
            mol=psi4.geometry('0 1\n'+lines+'\nunits bohr\nsymmetry c1\nno_com\nno_reorient')
        else:
            mol=psi4.core.Molecule.from_schema(schema['molecule'],nonphysical=True)
        grad,wfn=psi4.gradient('mp2',molecule=mol,return_wfn=True)
        g=np.asarray(grad);e=float(wfn.energy());psi4.core.flush_outfile()
        native=native_audit(output.read_text(),e,g)
        row=dict(case=case,energy_hartree=e,gradient=g.tolist(),native=native,output=pin(output),
             returned_geometry_bohr=np.asarray(wfn.molecule().geometry()).tolist(),
             max_geometry_delta_bohr=float(np.max(abs(np.asarray(wfn.molecule().geometry())-x))),
             old_energy_delta=e-old['energy_hartree'],
             old_gradient_max_delta=float(np.max(abs(g-np.array(old['gradient_hartree_bohr'])))),
             qcschema_energy_delta=e-float(previous['properties']['return_energy']),
             qcschema_gradient_max_delta=float(np.max(abs(g-np.array(previous['return_result']).reshape(-1,3)))),
             seconds=time.monotonic()-start)
        save(root/(case+'.json'),row);results.append(row)
        print({k:row[k] for k in ['case','old_energy_delta','old_gradient_max_delta','qcschema_gradient_max_delta','seconds']},flush=True)
        psi4.core.clean()
    save(root/'assessment.json',dict(at=now(),completed=True,new_gradients=len(results),results=results,minimum_certified=False))


if __name__=='__main__':run(Path(sys.argv[1]).resolve())
