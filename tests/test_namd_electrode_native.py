"""The optional compiled callback must preserve the reference force equations."""
import shutil
import subprocess

import numpy as np
import pytest
from backend.core.namd_electrode_native import install_native
from backend.core.namd_slab import slab_energy_forces


def test_compiled_electrode_forces_match_slab_confinement_and_springs(tmp_path):
    tclsh = shutil.which('tclsh')
    if tclsh is None:
        pytest.skip('Tcl execution oracle requires tclsh')
    (tmp_path/'electrode_forces.tcl').write_text('')
    result=install_native(tmp_path)
    if not result['enabled']:pytest.skip(result['reason'])
    preamble = f'''
load {{{tmp_path / 'electrode_native.so'}}} Electrodenative
proc addforce {{id f}} {{global forces;set forces($id) $f}}
proc addenergy {{e}} {{global energy;set energy $e}}
'''
    xyz=np.array([[2.,9.,17.],[18.,3.,8.],[11.,19.,1.]])
    charges=[-.8,.3,.5]
    for axis in range(3):
        script = preamble + '\n'.join(
            f'set xyz({i+1}) {{{" ".join(map(str, x))}}}' for i, x in enumerate(xyz)
        ) + '\n'
        coefficient=2*np.pi*332.0636/20**3
        script += (f'nadoc_electrode_forces xyz {{1 -.8 2 .3 3 .5}} {{1 2 3}} '
                   f'{axis} {coefficient} 5 15 10 {{1 {{1 8 16 5}}}}\n'
                   'puts $energy\nforeach i {1 2 3} {puts $forces($i)}\n')
        script_path = tmp_path / 'oracle.tcl'
        script_path.write_text(script)
        result = subprocess.run([tclsh, str(script_path)], capture_output=True, text=True, check=True)
        lines = result.stdout.splitlines()
        energy,force=slab_energy_forces(xyz.tolist(),charges,[20.]*3,axis)
        force=np.array(force)
        for i,x in enumerate(xyz):
            delta=x[axis]-np.clip(x[axis],5,15)
            force[i,axis]-=10*delta;energy+=5*delta**2
        delta=xyz[0]-[1,8,16];force[0]-=5*delta;energy+=2.5*np.dot(delta,delta)
        observed=np.array([line.split() for line in lines[1:]],dtype=float)
        assert observed==pytest.approx(force,abs=1e-10)
        assert float(lines[0])==pytest.approx(energy,abs=1e-10)
