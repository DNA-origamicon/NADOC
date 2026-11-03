"""Conservative admission for orthorhombic explicit-solvent CUDA patch layouts.

The 2026-11-01 boundary probes found a separate per-block shared-memory limit.
The occupancy allowance is an operational envelope, not a proof of local density
at arbitrary future coordinates. Unknown layout controls are refused.
"""
from itertools import product
import math
import re

SHARED_BYTES = 49152
PATCH_DENSITY_ALLOWANCE = .20  # twice bulk solvated atom density, atoms / A^3
PATCH_CAPACITY_FRACTION = .75


def device_shared_bytes(devices):
    """Read the kernel's actual per-block capacity; an unreadable GPU is unknown."""
    import ctypes as C
    if not str(devices).isdigit():raise ValueError('Patch admission requires one CUDA device')
    try:
        cuda=C.CDLL('libcuda.so.1')
        device=C.c_int();shared=C.c_int()
        if cuda.cuInit(0) or cuda.cuDeviceGet(C.byref(device),int(devices)) or cuda.cuDeviceGetAttribute(C.byref(shared),8,device):
            raise ValueError('CUDA patch capacity could not be read')
        if shared.value<=0:raise ValueError('CUDA patch capacity is unavailable')
        return min(SHARED_BYTES,shared.value)
    except OSError as exc:raise ValueError('CUDA patch capacity could not be read') from exc


def _grid(box, size, away, cap):
    dims = tuple(max(a, int(d*a/size)) for d,a in zip(box,away))
    cap = max(math.prod(away), min(int(cap), math.prod(dims)))
    if cap == math.prod(dims):
        return dims
    best = tuple(away)
    # Mirrors PatchMap::sizeGrid's maximum-product search and tie order.
    for z in range(max(away[2], cap//dims[0]//dims[1]), dims[2]+1):
        for y in range(max(away[1], cap//dims[0]//z), dims[1]+1):
            x = min(dims[0], cap//y//z)
            if x >= away[0] and x*y*z > math.prod(best):best=(x,y,z)
    return best


def patch_layout(atoms, box, *, pairlist=13.5, margin=3, threads=16,
                 two_away=(None,None,None), shared_bytes=SHARED_BYTES):
    if len(box)!=3 or any(not math.isfinite(float(d)) or d<=0 for d in box):
        raise ValueError('A positive orthorhombic box is required for patch admission')
    if not all(math.isfinite(float(x)) for x in (pairlist,margin,threads,atoms,shared_bytes)) or pairlist<=0 or margin<0 or threads<1:
        raise ValueError('Invalid patch-layout settings')
    if len(two_away)!=3 or any(x not in (None,True,False) for x in two_away):
        raise ValueError('Invalid twoAway patch controls')
    size=pairlist+2.5+margin
    away=[2 if x else 1 for x in two_away]
    cap=10**9 if any(x is True for x in two_away) else max(1,int(atoms)//40)
    dims=_grid(box,size,away,cap)
    for axis in range(3):
        if math.prod(dims)<threads and two_away[axis] is None:
            away[axis]=2;dims=_grid(box,size,away,cap)
    n=math.prod(dims)
    if n%threads and n<=1.4*threads:
        exact=n-n%threads
        candidate=_grid(box,size,away,exact)
        if math.prod(candidate)==exact:dims=candidate
    occupancy=min(int(atoms),math.ceil(PATCH_DENSITY_ALLOWANCE*math.prod(d/n for d,n in zip(box,dims))))
    capacity=int(shared_bytes)//128*32
    allowed=int(capacity*PATCH_CAPACITY_FRACTION)
    return dict(grid=dims,away=tuple(away),patch_atoms_allowance=occupancy,
        kernel_capacity_atoms=capacity,admission_capacity_atoms=allowed,
        supported=occupancy<=allowed and math.prod(dims)>=threads,
        density_allowance=PATCH_DENSITY_ALLOWANCE)


def safe_patch_overrides(atoms, box, *, pairlist=13.5, margin=3, threads=16,
                         two_away=(None,None,None), shared_bytes=SHARED_BYTES):
    original=patch_layout(atoms,box,pairlist=pairlist,margin=margin,threads=threads,two_away=two_away,shared_bytes=shared_bytes)
    if original['supported']:return {}
    candidates=[]
    for flags in product(*[(x,) if x is not None else (None,True) for x in two_away]):
        layout=patch_layout(atoms,box,pairlist=pairlist,margin=margin,threads=threads,two_away=flags,shared_bytes=shared_bytes)
        if layout['supported']:candidates.append((math.prod(layout['grid']),sum(x is True for x in flags),flags))
    if not candidates:raise ValueError('No qualified CUDA patch layout for this box and neighbor settings; change settings or execution target')
    flags=min(candidates,key=lambda x:x[:2])[2]
    return {'twoAway'+axis:'on' for axis,before,after in zip('XYZ',two_away,flags) if before is None and after is True}


def literal_options(text):
    options={}
    for line in text.splitlines():
        parts=line.split('#',1)[0].strip().rstrip(';').split(None,1)
        if len(parts)==2:options[parts[0].lower()]=parts[1].strip()
    return options


def two_away_options(options):
    result=[]
    for axis in 'xyz':
        value=options.get('twoaway'+axis)
        if value is None:result.append(None)
        elif str(value).lower() in ('on','yes','true','1'):result.append(True)
        elif str(value).lower() in ('off','no','false','0'):result.append(False)
        else:raise ValueError('Unresolved twoAway patch control')
    return tuple(result)


def ensure_safe_patch_layout(text, *, atoms=3_000_000, threads=1):
    """Set only unspecified decomposition controls; keep physical settings intact."""
    opts=literal_options(text)
    if opts.get('pme','').lower() not in ('yes','on','true','1'):return text
    if not all('cellbasisvector'+str(i) in opts for i in (1,2,3)):return text
    vectors=[list(map(float,opts['cellbasisvector'+str(i)].split())) for i in (1,2,3)]
    if any(len(v)!=3 or any(x!=0 for j,x in enumerate(v) if j!=i) for i,v in enumerate(vectors)):
        raise ValueError('Skewed cells require separate patch-layout qualification')
    box=[vectors[i][i] for i in range(3)]
    # The read-only protocol preview uses a zero cell until preparation resolves
    # geometry. Do not select a layout there; configuration_memory rejects it at launch.
    if box==[0,0,0]:return text
    changes=safe_patch_overrides(atoms,box,pairlist=float(opts.get('pairlistdist',13.5)),margin=float(opts.get('margin',3)),threads=threads,two_away=two_away_options(opts))
    if not changes:return text
    block='# CUDA patch subdivision selected before launch (physical settings unchanged).\n'+''.join(f'{k:<18} {v}\n' for k,v in changes.items())
    # Must precede run/minimize: directives appended after integration are too late.
    match=re.search(r'^(?:# NADOC_ADAPTIVE_MIN_BEGIN|run\b|minimize\b|while\b|for\b|if\b)',text,re.M)
    pos=match.start() if match else len(text)
    return text[:pos]+block+text[pos:]
