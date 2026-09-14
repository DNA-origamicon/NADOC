"""Compile the production math and compare to the independent Python oracle."""
import ctypes
import subprocess
from pathlib import Path

import numpy as np
import pytest

from tools.oxdna_peg.chudoba_reference import chain_energy, finite_difference_forces


@pytest.fixture(scope='module')
def library(tmp_path_factory):
    root = Path(__file__).resolve().parents[1]
    work = tmp_path_factory.mktemp('chudoba_math')
    src = work/'check.cpp'
    src.write_text('''#include "chudoba_math.h"
extern "C" double evaluate(double* x, double* out, int count, double t) {
    using V=chudoba::Vec<double>;
    V p[16],f[4]; double e=0;
    for(int i=0;i<count;i++) p[i]=V(x[3*i],x[3*i+1],x[3*i+2]);
    auto add=[&](int i,int n){for(int j=0;j<n;j++){
        out[3*(i+j)]+=f[j].x;out[3*(i+j)+1]+=f[j].y;out[3*(i+j)+2]+=f[j].z;}};
    for(int i=0;i<count-1;i++){e+=chudoba::bond(p[i+1]-p[i],f);add(i,2);}
    for(int i=0;i<count-2;i++){e+=chudoba::angle(p[i+1]-p[i],p[i+2]-p[i+1],f);add(i,3);}
    for(int i=0;i<count-3;i++){e+=chudoba::torsion(p[i+1]-p[i],p[i+2]-p[i+1],p[i+3]-p[i+2],f);add(i,4);}
    for(int i=0;i<count;i++)for(int j=i+2;j<count;j++){
        V u=p[j]-p[i];double r=sqrt(chudoba::dot(u,u)),du;
        e+=chudoba::pair(r,t,du);V v=u*(du/r);
        out[3*i]+=v.x;out[3*i+1]+=v.y;out[3*i+2]+=v.z;
        out[3*j]-=v.x;out[3*j+1]-=v.y;out[3*j+2]-=v.z;
    }
    return e;
}''')
    subprocess.run(['c++','-O2','-shared','-fPIC','-I'+str(root/'tools/oxdna_peg'),str(src),'-o',str(work/'check.so')],check=True)
    lib=ctypes.CDLL(str(work/'check.so'))
    ptr=np.ctypeslib.ndpointer(dtype=np.float64,flags='C_CONTIGUOUS')
    lib.evaluate.argtypes=[ptr,ptr,ctypes.c_int,ctypes.c_double]
    lib.evaluate.restype=ctypes.c_double
    return lib


@pytest.mark.parametrize('seed',range(8))
@pytest.mark.parametrize('temperature',[294,347,371,396])
def test_compiled_forces(library,seed,temperature):
    rng=np.random.default_rng(seed)
    xyz=np.cumsum(rng.normal(size=(6,3))*.15+[.24,.03,0],axis=0)
    forces=np.zeros_like(xyz)
    energy=library.evaluate(xyz,forces,len(xyz),temperature)
    assert energy==pytest.approx(chain_energy(xyz,temperature),rel=1e-10)
    assert np.allclose(forces,finite_difference_forces(xyz,temperature),rtol=2e-6,atol=2e-5)
