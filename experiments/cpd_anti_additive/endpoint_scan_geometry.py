"""Graph-defined glycosidic rotations and independent constrained force metrics."""
import numpy as np
from backend.parameterization.photoproduct_qm import _dihedral_degrees


def wrapped(value):
    return (value+180)%360-180


def torsion(x, indices):
    return float(_dihedral_degrees(*np.asarray(x)[indices]))


def rotate_sugar(x, bonds, indices, offset_degrees):
    x=np.asarray(x,float);a,b=indices[1:3]
    neighbors={i:set() for i in range(len(x))}
    for i,j in bonds:neighbors[i].add(j);neighbors[j].add(i)
    if b not in neighbors[a]:raise ValueError('Glycosidic axis is not bonded')
    neighbors[a].remove(b);neighbors[b].remove(a)
    moving=set();pending=[a]
    while pending:
        i=pending.pop()
        if i in moving:continue
        moving.add(i);pending.extend(neighbors[i]-moving)
    if b in moving or indices[0] not in moving or indices[3] in moving:
        raise ValueError('Torsion axis does not separate the sugar; ring-bond scan refused')
    moving=sorted(moving);axis=x[a]-x[b];axis/=np.linalg.norm(axis)
    def rotate(degrees):
        theta=np.radians(degrees);v=x[moving]-x[b];y=x.copy()
        y[moving]=x[b]+v*np.cos(theta)+np.cross(axis,v)*np.sin(theta)+np.outer(v@axis,axis)*(1-np.cos(theta))
        return y
    slope=wrapped(torsion(rotate(1),indices)-torsion(x,indices))
    if not np.isclose(abs(slope),1,atol=1e-9):raise ValueError('Torsion convention check failed')
    result=rotate(offset_degrees/slope)
    if abs(wrapped(torsion(result,indices)-torsion(x,indices)-offset_degrees))>1e-9:
        raise ValueError('Requested torsion offset not obtained')
    if max(abs(np.linalg.norm(result[i]-result[j])-np.linalg.norm(x[i]-x[j])) for i,j in bonds)>1e-10:
        raise ValueError('Rigid sugar rotation changed a covalent bond length')
    return result,moving


def constraint_metrics(x, gradient, constraint, h=1e-5):
    x=np.asarray(x,float);g=np.asarray(gradient,float);indices=constraint['indices']
    if x.shape!=g.shape or not np.isfinite([x,g]).all():raise ValueError('Invalid constrained coordinates/gradient')
    normal=np.zeros_like(x)
    for i in indices:
        for axis in range(3):
            plus=x.copy();minus=x.copy();plus[i,axis]+=h;minus[i,axis]-=h
            normal[i,axis]=wrapped(torsion(plus,indices)-torsion(minus,indices))/(2*h)
    denom=float(np.sum(normal**2))
    if denom<1e-20:raise ValueError('Degenerate torsion normal')
    projected=g-normal*np.sum(g*normal)/denom
    norms=np.linalg.norm(projected,axis=1);angle=torsion(x,indices)
    values=dict(max_atom_gradient_au=float(norms.max()),rms_atom_gradient_au=float(np.sqrt(np.mean(norms**2))))
    return dict(**values,torsion_degrees=angle,torsion_error_degrees=abs(wrapped(angle-constraint['target_degrees'])),
        force_scope='Cartesian gradient projected tangent to the single fixed glycosidic torsion',
        passed=bool(values['max_atom_gradient_au']<1.5e-5 and values['rms_atom_gradient_au']<1e-5
                    and abs(wrapped(angle-constraint['target_degrees']))<.01)),normal
