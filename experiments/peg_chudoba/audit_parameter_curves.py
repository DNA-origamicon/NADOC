"""Audit Figure 5 curve precision independently of polymer-size observations.

Reconstructed drawing coefficients are evidence, not replacement parameters.
"""
import hashlib
import json
from pathlib import Path

import numpy as np
import pymupdf
from scipy.integrate import quad

from experiments.peg_chudoba.audit_potential_curves import energy
from tools.oxdna_peg.chudoba_reference import parameters


def main():
    root=Path(__file__).parent/'reference'
    source=root/'chudoba_2017_preprint.pdf'
    page=pymupdf.open(source)[6]
    curves={}
    # Axes verified against rendered Figure 5. Bottom panel spans m=5..11.
    for name,index,base,scale,y0 in [
        ('sigma',113,.4,.03/71.6,130.14999389648438),
        ('mu',124,.67,.05/71.6,130.14999389648438),
        ('m',138,5,6/71.65,205.75),
    ]:
        items=page.get_drawings()[index]['items']
        assert all(item[0]=='l' for item in items)
        xy=np.array(sorted(set(tuple(pt) for item in items for pt in item[1:])))
        temperature=260+(xy[:,0]-354.0360107421875)/166.5999755859375*140
        value=base+(y0-xy[:,1])*scale
        coefficients=np.polyfit(temperature,np.log(value) if name=='m' else value,1)
        prediction=np.polyval(coefficients,temperature)
        if name=='m':prediction=np.exp(prediction)
        curves[name]=dict(drawing_index=index,coefficients=coefficients.tolist(),
            form='exp(slope*T+intercept)' if name=='m' else 'slope*T+intercept',
            maximum_curve_residual=float(np.max(np.abs(prediction-value))),
            vector_points_T_value=np.column_stack((temperature,value)).tolist())

    def b2(p,t):
        def integrand(r):
            if r<.1:return r*r
            u=energy(r,p)
            if r>p['mu'] and u<0:u=0.
            return -np.expm1(-u/(.00831446261815324*t))*r*r
        return 2*np.pi*quad(integrand,0,.9,epsabs=1e-10,points=[.1,.4,.6,.8])[0]

    comparisons=[]
    for t in [294,320,347,361,371,381]:
        printed=parameters(t);drawing=dict(printed)
        for name,curve in curves.items():
            v=np.polyval(curve['coefficients'],t)
            drawing[name]=float(np.exp(v) if name=='m' else v)
        comparisons.append(dict(temperature_K=t,
            printed={k:printed[k] for k in curves},drawing={k:drawing[k] for k in curves},
            printed_pair_B2_nm3=b2(printed,t),drawing_pair_B2_nm3=b2(drawing,t)))
    report=dict(source='arXiv:1710.09191v1 Figure 5, page 7',
        source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),curves=curves,comparisons=comparisons,
        method='Linear fits to vector sigma/mu curves; log-linear fit to vector m curve. No chain-size observations fitted. Pair B2=2*pi*integral((1-exp(-U/RT))*r^2 dr), using the zero outer tail and 0.9 nm neighbor cutoff.',
        limitations='Drawing quantization limits recovered precision. These curves do not prove which full-precision coefficients generated the published chain runs. Pair B2 is a two-bead diagnostic, not the polymer osmotic second virial coefficient. Running model remains printed Table 2, with discrete SI parameters at 396 K.')
    (root/'parameter_curve_audit.json').write_text(json.dumps(report,indent=2)+'\n')
    for row in comparisons:print(json.dumps(row))


if __name__=='__main__':main()
