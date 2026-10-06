import numpy as np
from experiments.cpd_anti_additive.gpu_water_precision_v3 import water_checks

def fixture():
 x=np.zeros((30867,3));w=x[3043:30712].reshape(-1,3,3)
 oxygen=np.array([(2.5*i,2.5*j,4*k) for i in range(17) for j in range(25) for k in range(22)])[:9223]+10000
 w[:,0]=oxygen;w[:,1]=oxygen+[.9572,0,0]
 angle=np.deg2rad(104.52);w[:,2]=oxygen+[.9572*np.cos(angle),.9572*np.sin(angle),0]
 return x

def test_quantization_does_not_masquerade_as_constraint_failure():
 x=fixture();assert water_checks(x)['passed']
 stored=x.astype(np.float32)
 assert not water_checks(stored,False)['passed']
 assert water_checks(stored,True)['passed']

def test_real_stretch_and_periodic_overlap_remain_failures():
 x=fixture();x[3044,0]+=.05
 assert not water_checks(x.astype(np.float32),True)['passed']
 x=fixture();x[3046:3049]=x[3043:3046]+[44.93,0,0]
 assert not water_checks(x.astype(np.float32),True)['passed']
