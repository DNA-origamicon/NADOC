"""Water geometry with explicit DCD-coordinate quantization uncertainty."""
import numpy as np
from scipy.spatial import cKDTree
BOX=np.array([44.93,67.438,112.763])

def water_checks(x,quantized=False):
 x=np.asarray(x,dtype=np.float64);w=x[3043:30712].reshape(-1,3,3)
 delta=w[:,1:]-w[:,:1];delta-=np.rint(delta/BOX)*BOX
 length=np.linalg.norm(delta,axis=2);error=abs(length-.9572)
 if quantized:
  # A decoded float32 is at most half a float32 ULP from the saved double.
  half=.5*abs(np.spacing(w.astype(np.float32)).astype(np.float64))
  bound=np.linalg.norm(half[:,1:]+half[:,:1],axis=2)
 else:bound=np.zeros_like(length)
 oxygen=w[:,0]%BOX;dist,_=cKDTree(oxygen,boxsize=BOX).query(oxygen,k=2)
 return dict(minimum_periodic_OO_A=float(dist[:,1].min()),max_observed_OH_error_A=float(error.max()),max_coordinate_quantization_bound_A=float(bound.max()),max_error_beyond_quantization_A=float(np.maximum(0,error-bound).max()),physical_OH_limit_A=1e-5,representation='DCD float32 interval consistency' if quantized else 'binary float64 measurement',passed=bool(dist[:,1].min()>2 and np.maximum(0,error-bound).max()<1e-5))
