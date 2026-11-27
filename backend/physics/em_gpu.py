"""Optional float64 CUDA exterior VSH evaluator; CPU coupling and shell interiors.

One thread per spatial point, all electric/magnetic modes retained. The outgoing
Hankel recurrence is stable here (real positive water wavenumber). Near-pole
points retain the qualified CPU convention. No approximate coefficient pruning.
"""
from functools import lru_cache
from math import factorial

import numpy as np


@lru_cache(maxsize=1)
def runtime():
    try:
        import cupy as cp
        if cp.cuda.runtime.getDeviceCount() < 1:
            raise RuntimeError('No CUDA device.')
        kernel = cp.RawKernel(_KERNEL, 'exterior', options=('--std=c++11',))
        kernel.compile()
        return cp, kernel
    except Exception as exc:
        raise RuntimeError('EM GPU unavailable: install the optional CUDA dependencies '
                           'and use a supported NVIDIA driver. No CPU fallback was performed.') from exc


def device_info():
    cp, _ = runtime()
    props = cp.cuda.runtime.getDeviceProperties(cp.cuda.Device().id)
    name = props['name']
    return {'name': name.decode() if isinstance(name, bytes) else name,
            'cupy': cp.__version__, 'precision': 'float64/complex128',
            'method': 'CUDA exterior VSH; CPU coupling, poles, source and shell interiors'}


@lru_cache(maxsize=9)
def factors(order):
    from miepy.cpp.vsh_functions import Emn
    cp, _ = runtime()
    return cp.asarray([1j * Emn(m, n) for n in range(1, order + 1) for m in range(-n, n + 1)]), cp.asarray(
        [((-1.)**m * factorial(n-m) / factorial(n+m) if m <= n else 0.)
         for n in range(order+1) for m in range(order+1)], dtype=cp.float64)


def exterior_electric_field(cluster, points):
    from backend.physics.em_field_evaluator import exterior_electric_field as cpu_field
    if cluster.interface is not None or not 1 <= cluster.lmax <= 12:
        raise ValueError('GPU exterior evaluator supports no interface and orders 1–12.')
    k = complex(cluster.material_data.k_b)
    if k.imag != 0 or k.real <= 0:
        raise ValueError('GPU exterior evaluator requires a real positive background wavenumber.')
    cp, kernel = runtime()
    points = np.ascontiguousarray(points, dtype=np.float64)
    if not len(points):
        return np.empty((3, 0), complex)
    delta = points[:, None, :] - cluster.position[None, :, :]
    radius = np.linalg.norm(delta, axis=2)
    pole = np.any(np.linalg.norm(delta[:, :, :2], axis=2) < 1e-5 * radius, axis=1)
    regular = points[~pole]
    result = np.empty((3, len(points)), complex)
    if len(regular):
        prefactors, negative = factors(cluster.lmax)
        output = cp.empty((len(regular), 3), dtype=cp.complex128)
        kernel(((len(regular)+127)//128,), (128,),
               (cp.asarray(regular), np.int32(len(regular)), cp.asarray(cluster.position),
                np.int32(len(cluster.position)), np.int32(cluster.lmax), np.float64(k.real),
                cp.asarray(np.ascontiguousarray(cluster.p_scat)), prefactors, negative, output))
        # asnumpy synchronizes: timings include kernel execution and both transfers.
        result[:, ~pole] = cp.asnumpy(output).T + cluster.E_source(*regular.T, far=False, spherical=False)
    if np.any(pole):
        result[:, pole] = cpu_field(cluster, points[pole])
    return result


_KERNEL = r'''
#include <cupy/complex.cuh>
extern "C" __global__ void exterior(const double* xyz, int count,
    const double* centers, int particles, int L, double k,
    const complex<double>* coefficients, const complex<double>* pref,
    const double* negative, complex<double>* out) {
    int i = blockDim.x * blockIdx.x + threadIdx.x;
    if (i >= count) return;
    const complex<double> I(0., 1.);
    complex<double> ex=0., ey=0., ez=0.;
    int modes = L*(L+2);
    for (int p=0; p<particles; ++p) {
        double x=xyz[3*i]-centers[3*p], y=xyz[3*i+1]-centers[3*p+1];
        double z=xyz[3*i+2]-centers[3*p+2];
        double r=sqrt(x*x+y*y+z*z), c=z/r, s=sqrt(x*x+y*y)/r;
        double phi=atan2(y,x), cp=cos(phi), sp=sin(phi), t=k*r;
        double P[13][13] = {};
        P[0][0]=1.;
        for (int m=1;m<=L;++m) P[m][m]=(2*m-1)*s*P[m-1][m-1];
        for (int m=0;m<L;++m) P[m+1][m]=(2*m+1)*c*P[m][m];
        for (int m=0;m<=L;++m)
            for (int n=m+2;n<=L;++n)
                P[n][m]=((2*n-1)*c*P[n-1][m]-(n+m-1)*P[n-2][m])/(n-m);
        complex<double> hprev(sin(t)/t,-cos(t)/t);
        complex<double> h(sin(t)/(t*t)-cos(t)/t,-cos(t)/(t*t)-sin(t)/t);
        complex<double> er=0., et=0., ep=0.;
        for (int n=1;n<=L;++n) {
            complex<double> tangent=hprev-double(n)*h/t;
            for (int m=-n;m<=n;++m) {
                int a=abs(m), j=n*n+n+m-1;
                double leg=P[n][a], pi=a*leg/s;
                double tau=(n*c*leg-(n+a)*(a<n?P[n-1][a]:0.))/s;
                if (m<0) {double f=negative[n*(L+1)+a]; leg*=f; pi*=-f; tau*=f;}
                complex<double> phase(cos(m*phi),sin(m*phi));
                complex<double> f=pref[j]*phase;
                complex<double> e=coefficients[p*2*modes+j];
                complex<double> b=coefficients[(p*2+1)*modes+j];
                er+=f*e*double(n*(n+1))*leg*h/t;
                et+=f*(e*tau*tangent+b*I*pi*h);
                ep+=f*(e*I*pi*tangent-b*tau*h);
            }
            complex<double> next=double(2*n+1)*h/t-hprev;
            hprev=h; h=next;
        }
        ex+=s*cp*er+c*cp*et-sp*ep;
        ey+=s*sp*er+c*sp*et+cp*ep;
        ez+=c*er-s*et;
    }
    out[3*i]=ex; out[3*i+1]=ey; out[3*i+2]=ez;
}
'''
