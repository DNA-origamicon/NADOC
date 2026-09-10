"""PEG solution construction and an independent molecular-virial estimator.

All coordinates are nm. Pressure is kPa. The estimator differentiates energy
under scaling of molecular centers and the periodic box, holding internal
coordinates fixed; its ideal term counts molecules. This reduces stiff-bond
noise in equilibrium averages for continuous potentials. For raw truncation,
this smooth-force estimator omits the cutoff impulse and must not be used as
a thermodynamic EOS estimator.
"""
import numpy as np
from scipy.spatial import cKDTree

from tools.oxdna_peg.chudoba_reference import parameters

NA=6.02214076e23
R_KJ=.008314462618
REPEAT_MASS=44.05


def pair_values(r,temperature,*,zero_tail=False):
    p=parameters(temperature);d=p['n']-p['m'];l=np.log(p['sigma']/r)
    if abs(d)<1e-8:
        norm=p['n']*np.e*p['epsilon'];dd=l
    else:
        norm=p['n']*np.exp(p['m']*np.log1p(d/p['m'])/d)*p['epsilon']
        dd=np.expm1(d*l)/d
    power=np.exp(p['m']*l);z=(r-p['mu'])/p['delta'];g=p['gamma']*np.exp(-z*z)
    energy=norm*power*dd+g
    derivative=-norm*power*(p['m']*dd+np.exp(d*l))/r-2*z*g/p['delta']
    if zero_tail:
        removed=(r>p['mu']) & (energy<0)
        energy=np.where(removed,0.,energy);derivative=np.where(removed,0.,derivative)
    return energy,derivative


def pairs(xyz,n,box):
    ij=cKDTree(xyz%box,boxsize=box).query_pairs(.9,output_type='ndarray')
    if not len(ij):return ij,np.empty((0,3)),np.empty(0)
    i,j=ij.T
    keep=~((j-i==1)&(i//n==j//n))
    ij=ij[keep];i,j=ij.T
    delta=xyz[j]-xyz[i];delta-=box*np.rint(delta/box)
    return ij,delta,np.linalg.norm(delta,axis=1)


def molecular_pressure(xyz,n,box,temperature,*,zero_tail=False):
    xyz=np.asarray(xyz);chains=xyz.reshape(-1,n,3)
    centers=chains.mean(axis=1)
    offsets=(chains-centers[:,None,:]).reshape(-1,3)
    ij,delta,r=pairs(xyz,n,box)
    _,du=pair_values(r,temperature,zero_tail=zero_tail)
    if len(ij):
        i,j=ij.T
        molecular_delta=delta-(offsets[j]-offsets[i])
        virial=-np.sum(np.sum(molecular_delta*delta,axis=1)*du/r)
    else:virial=0.
    return (len(chains)*R_KJ*temperature+virial/3)/box**3*1e27/NA


def nonbonded_energy(xyz,n,box,temperature,*,zero_tail=False):
    _,_,r=pairs(xyz,n,box)
    return float(pair_values(r,temperature,zero_tail=zero_tail)[0].sum())


def initial_solution(n,count,concentration,seed,min_distance=.32):
    """Random nonoverlapping chains, with fixed starting bond/angle geometry.

    This is an initial state, not an equilibrium draw. Cell lookup handles PBC
    while each chain is kept unwrapped for bonded forces and COM calculations.
    """
    rng=np.random.default_rng(seed)
    box=(n*count*REPEAT_MASS/(.602214076*concentration))**(1/3)
    cells=max(3,int(box/min_distance));width=box/cells
    grid={};xyz=[]
    shifts=np.array([(i,j,k) for i in [-1,0,1] for j in [-1,0,1] for k in [-1,0,1]])
    def cell(p):return np.floor((p%box)/width).astype(int)%cells
    index=0;backtracks=0
    while index<n*count:
        for attempt in range(10000):
            if index%n==0:
                p=rng.uniform(0,box,3)
            else:
                axis=xyz[-1]-xyz[-2] if index%n>1 else rng.normal(size=3)
                axis=axis/np.linalg.norm(axis)
                perp=np.cross(axis,rng.normal(size=3));perp/=np.linalg.norm(perp)
                p=xyz[-1]+.33*(np.cos(np.deg2rad(50))*axis+np.sin(np.deg2rad(50))*perp)
            key=cell(p);valid=True
            for shift in shifts:
                for j in grid.get(tuple((key+shift)%cells),[]):
                    if index%n and j==index-1:continue
                    d=p-xyz[j];d-=box*np.rint(d/box)
                    if d@d<min_distance**2:valid=False;break
                if not valid:break
            if valid:break
        else:
            backtracks+=1
            if backtracks>1000:raise RuntimeError(f'Packing stalled at bead {index}')
            undo=min(index%n,10)
            if not undo:raise RuntimeError('Could not place a chain root')
            for _ in range(undo):
                j=len(xyz)-1
                grid[tuple(cell(xyz[-1]))].remove(j)
                xyz.pop()
            index=len(xyz)
            continue
        grid.setdefault(tuple(key),[]).append(index);xyz.append(p);index+=1
    return np.array(xyz),box
