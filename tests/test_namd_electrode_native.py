"""The optional compiled callback must preserve the reference force equations."""
import numpy as np
import pytest
from backend.core.namd_electrode_native import install_native
from backend.core.namd_slab import slab_energy_forces


def test_compiled_electrode_forces_match_slab_confinement_and_springs(tmp_path):
    tkinter=pytest.importorskip('tkinter')
    (tmp_path/'electrode_forces.tcl').write_text('')
    result=install_native(tmp_path)
    if not result['enabled']:pytest.skip(result['reason'])
    t=tkinter.Tcl();t.call('load',str(tmp_path/'electrode_native.so'),'Electrodenative')
    t.eval('proc addforce {id f} {global forces;set forces($id) $f};proc addenergy {e} {global energy;set energy $e}')
    xyz=np.array([[2.,9.,17.],[18.,3.,8.],[11.,19.,1.]])
    charges=[-.8,.3,.5];sites=(1,(1.,8.,16.,5.))
    for axis in range(3):
        for i,x in enumerate(xyz):t.setvar(f'xyz({i+1})',tuple(x))
        coefficient=2*np.pi*332.0636/20**3
        t.call('nadoc_electrode_forces','xyz',(1,-.8,2,.3,3,.5),(1,2,3),axis,coefficient,5.,15.,10.,sites)
        energy,force=slab_energy_forces(xyz.tolist(),charges,[20.]*3,axis)
        force=np.array(force)
        for i,x in enumerate(xyz):
            delta=x[axis]-np.clip(x[axis],5,15)
            force[i,axis]-=10*delta;energy+=5*delta**2
        delta=xyz[0]-[1,8,16];force[0]-=5*delta;energy+=2.5*np.dot(delta,delta)
        observed=np.array([t.splitlist(t.getvar(f'forces({i+1})')) for i in range(3)],dtype=float)
        assert observed==pytest.approx(force,abs=1e-10)
        assert float(t.getvar('energy'))==pytest.approx(energy,abs=1e-10)
