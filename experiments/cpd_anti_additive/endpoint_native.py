"""Numeric, whitespace-independent audits for corrected 49-atom endpoint QM."""
import re
import numpy as np

from experiments.cpd_anti_additive.corrected_core_stage1 import native_audit
from experiments.cpd_anti_additive.audit_corrected_core_stage1 import parse_native_table

NUMBER = r'[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[EeDd][-+]?\d+)?'


def require_fitting_condition(text, expected=1e-10):
    values=[float(v.replace('D','E').replace('d','e')) for v in
            re.findall(r'Fitting Condition:\s*('+NUMBER+r')',text)]
    if not values or any(v!=expected for v in values):
        raise ValueError(f'Fitting condition missing or changed: {values}')
    return values


def audit_native(text, elements, coordinates, expected_basis=None):
    x=np.asarray(coordinates,float)
    if x.shape!=(len(elements),3) or not np.isfinite(x).all():
        raise ValueError('Invalid input geometry')
    e,g=parse_native_table(text,len(elements))
    electronic=native_audit(text,e,g)
    fitting=require_fitting_condition(text)
    for phrase in ['RHF Reference','RMP2 Wavefunction','SCF Algorithm Type is DF.',
                   'gradient() will perform analytic gradient computation.',
                   'Energy threshold   = 1.00e-12','Density threshold  = 1.00e-12',
                   'Integral threshold = 1.00e-12']:
        if phrase not in text:raise ValueError(f'Missing electronic evidence: {phrase}')
    occupations=re.findall(r'PAIRS\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)',text)
    if occupations!=[('27','101','74','348','348','0')]:
        raise ValueError(f'Wrong endpoint frozen-core occupations: {occupations}')
    bases=re.findall(r'Basis Set:[^\n]+\n\s*Blend:\s*([^\n]+)\n\s*Number of shells:\s*\d+\n\s*Number of basis functions:\s*(\d+)\n\s*Number of Cartesian functions:\s*(\d+)\n\s*Spherical Harmonics\?:\s*(true|false)',text)
    expected_basis=expected_basis or {'6-31G(D)':(449,449,False),
        'CC-PVDZ-JKFIT':(2737,2737,False),'CC-PVDZ-RI':(1820,2112,True)}
    found={}
    for name,nbf,ncart,pure in bases:
        name=name.strip();actual=(int(nbf),int(ncart),pure=='true')
        if name not in expected_basis or actual!=tuple(expected_basis[name]):
            raise ValueError(f'Unexpected actual basis: {name} {actual}')
        found[name]=actual
    if set(found)!=set(expected_basis):raise ValueError('Incomplete native basis inventory')
    rows=re.findall(r'^\s*([CHNO])\s+('+NUMBER+r')\s+('+NUMBER+r')\s+('+NUMBER+r')\s+('+NUMBER+r')\s*$',text,re.M)
    n=len(elements)
    if len(rows)!=2*n or [v[0] for v in rows]!=elements*2 or text.count('Geometry (in Bohr), charge = 0, multiplicity = 1:')!=2:
        raise ValueError('Native geometry table count, units, charge or atom order changed')
    native_x=np.array([[float(v) for v in row[1:4]] for row in rows]).reshape(2,n,3)
    delta=float(np.max(abs(native_x-x)))
    if delta>5.1e-13:raise ValueError('Native geometry differs from pinned input')
    return e,g,dict(electronic=electronic,fitting_conditions=fitting,actual_bases=found,
        occupations=list(map(int,occupations[0])),geometry_tables=2,
        native_geometry_max_rounding_error_bohr=delta,gradient_components=3*n)
