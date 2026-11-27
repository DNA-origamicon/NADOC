"""Compile the actual native proposal predicate against an observed failing move."""
import ctypes
import json
import subprocess
from pathlib import Path

import numpy as np
import pytest


@pytest.fixture(scope='module')
def predicate(tmp_path_factory):
    root=Path(__file__).resolve().parents[1]
    work=tmp_path_factory.mktemp('vmmc_periodic')
    code=work/'guard.cpp'
    code.write_text('''#include "tools/oxdna_vmmc/periodic_geometry.h"
struct V { double x,y,z; V operator-(V b)const{return {x-b.x,y-b.y,z-b.z};}
 double norm()const{return x*x+y*y+z*z;} };
struct M { const double* m; V operator*(V v)const{return {
 m[0]*v.x+m[1]*v.y+m[2]*v.z,m[3]*v.x+m[4]*v.y+m[5]*v.z,m[6]*v.x+m[7]*v.y+m[8]*v.z};} };
extern "C" bool accepts(const double*a,const double*b,const double*r,double L){
 return nadoc_vmmc_periodic_pair_is_rigid(V{a[0],a[1],a[2]},V{b[0],b[1],b[2]},M{r},L);}
''')
    subprocess.run(['c++','-O2','-shared','-fPIC','-I'+str(root),str(code),'-o',str(work/'guard.so')],check=True)
    lib=ctypes.CDLL(str(work/'guard.so'))
    pointer=np.ctypeslib.ndpointer(dtype=np.float64,flags='C_CONTIGUOUS')
    lib.accepts.argtypes=[pointer,pointer,pointer,ctypes.c_double];lib.accepts.restype=ctypes.c_bool
    def call(old,new,rotation,side):
        return lib.accepts(np.ascontiguousarray(old,dtype=float),np.ascontiguousarray(new,dtype=float),np.ascontiguousarray(rotation,dtype=float),side)
    return call


def test_observed_electrostatic_image_change_is_rejected_in_both_directions(predicate):
    witness=json.loads((Path(__file__).parent/'fixtures/vmmc/periodic_rotation.json').read_text())
    old,new,R=map(np.array,[witness['old_minimum_image'],witness['new_minimum_image'],witness['rotation']])
    assert witness['old_debye_energy'] != witness['new_debye_energy']
    assert not predicate(old,new,R,witness['box_side'])
    assert not predicate(new,old,R.T,witness['box_side'])


def test_rigid_rotations_roundoff_and_inverse_symmetry(predicate):
    rng=np.random.default_rng(7241)
    for _ in range(1000):
        R,_=np.linalg.qr(rng.normal(size=(3,3)))
        if np.linalg.det(R)<0:R[:,0]*=-1
        old=rng.normal(size=3)
        new=R@old
        assert predicate(old,new,R,7.65)
        assert predicate(new,old,R.T,7.65)
        assert predicate(old,new+1e-12,R,7.65)
        # Image reassignment is not a rigid move, in either direction.
        shifted=new+[7.65,0,0]
        assert not predicate(old,shifted,R,7.65)
        assert not predicate(shifted,old,R.T,7.65)
