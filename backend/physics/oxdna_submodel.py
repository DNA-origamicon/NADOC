"""Derived oxDNA-only cropping with explicit source-index and boundary provenance.

Never author a NADOC part from these files. Original source construction histories
remain intact and are carried beside the derived simulation inputs.
"""
import numpy as np
from scipy.spatial.transform import Rotation


def box_distance(points, box):
    lo,hi=np.array(box['min_corner']),np.array(box['max_corner'])
    local=(np.asarray(points)-(lo+hi)/2)@Rotation.from_quat(box['rotation']).as_matrix()
    return np.linalg.norm(np.maximum(np.abs(local)-(hi-lo)/2,0),axis=1)


def crop(topology, configuration, points, box, radius):
    rows=[line.split() for line in topology.splitlines()[1:] if line.strip()]
    n,strands=map(int,topology.splitlines()[0].split())
    if n!=len(rows) or len(points)!=n:raise ValueError('Input particle count mismatch')
    neighbors=np.array([[int(r[2]),int(r[3])] for r in rows])
    for i,(n3,n5) in enumerate(neighbors):
        if (n3!=-1 and (not 0<=n3<n or neighbors[n3,1]!=i)) or (n5!=-1 and (not 0<=n5<n or neighbors[n5,0]!=i)):
            raise ValueError('Nonreciprocal topology')
    if radius is not None and (not np.isfinite(radius) or radius<0):raise ValueError('Invalid shell radius')
    distance=box_distance(points,box);mobile=distance<=1e-10
    if not mobile.any():raise ValueError('Empty mobile region')
    kept=np.ones(n,dtype=bool) if radius is None else distance<=radius+1e-10
    immediate={int(j) for i in np.flatnonzero(mobile) for j in neighbors[i] if j!=-1}
    kept[list(immediate)]=True
    ids=np.flatnonzero(kept);mapping={int(old):new for new,old in enumerate(ids)}
    # A cut can split a strand. Each remaining connected component is a strand,
    # while original particle order and n3/n5 direction are preserved exactly.
    components={};count=0
    for old in ids:
        if int(old) in components:continue
        count+=1;todo=[int(old)]
        while todo:
            i=todo.pop()
            if i in components:continue
            components[i]=count
            todo.extend(int(j) for j in neighbors[i] if j in mapping and j not in components)
    cuts=[];out=[]
    for old in ids:
        adjacent=[]
        for j in neighbors[old]:
            adjacent.append(mapping.get(int(j),-1))
            if j!=-1 and j not in mapping:
                if mobile[old]:raise ValueError('Cannot cut a mobile backbone bond')
                cuts.append([int(old),int(j)])
        out.append(f'{components[int(old)]} {rows[old][1]} {adjacent[0]} {adjacent[1]}')
    lines=configuration.splitlines()
    if len(lines)!=n+3:raise ValueError('Expected exactly one complete configuration')
    recipe={'version':1,'operation':'simulation-submodel-extraction','shell_nm':radius,
            'distance_metric':'Euclidean distance of aligned backbone site from oriented mobile box, nm',
            'box':box,'source_particle_count':n,'retained_source_indices':ids.tolist(),
            'mobile_source_indices':np.flatnonzero(mobile).tolist(),
            'mobile_output_indices':[mapping[int(i)] for i in np.flatnonzero(mobile)],
            'mandatory_bonded_source_indices':sorted(immediate-set(np.flatnonzero(mobile))),
            'cut_bonds_source_indices':cuts,'strand_components':count,
            'cut_policy':'Cut only outside-mobile bonds; leave native oxDNA terminal behavior; no artificial caps'}
    return f'{len(ids)} {count}\n'+'\n'.join(out)+'\n', '\n'.join(lines[:3]+[lines[3+i] for i in ids])+'\n',recipe


def expand_frame(configuration, context, recipe):
    """Scatter native output into immutable full-design display context.

    This is a physical display projection, never an authored Design or native
    engine input. Removed particles remain at their recorded starting poses.
    """
    source = context.splitlines()
    native = configuration.splitlines()
    ids = recipe["retained_source_indices"]
    if len(source) != recipe["source_particle_count"] + 3 or len(native) != len(ids) + 3:
        raise ValueError("Incomplete submodel frame or display context")
    values = np.array([[float(v) for v in row.split()] for row in native[3:]])
    if values.shape != (len(ids), 15) or not np.isfinite(values).all():
        raise ValueError("Invalid submodel particle data")
    output = []
    for row in source[3:]:
        fields = row.split()
        output.append(" ".join(fields[:9] + ["0"] * 6))
    for i, old in enumerate(ids):
        output[old] = native[i + 3]
    return "\n".join(native[:3] + output) + "\n"


def remap_pair_forces(text, recipe):
    """Remap ordinary relaxation pair traps; reject unknown force semantics."""
    import re
    ids = {old: new for new, old in enumerate(recipe["retained_source_indices"])}
    mobile = set(recipe["mobile_source_indices"])
    blocks = re.findall(r"\{([^{}]*)\}", text, re.S)
    if text.strip() and not blocks:
        raise ValueError("Unrecognized external-force file")
    result = []
    for block in blocks:
        fields = dict(re.findall(r"(\w+)\s*=\s*(\S+)", block))
        if fields.get("type") != "mutual_trap":
            raise ValueError("Submodels currently support DNA relaxation pair traps only; remove other external forces")
        a, b = int(fields["particle"]), int(fields["ref_particle"])
        if a not in ids or b not in ids:
            if a in mobile or b in mobile:
                raise ValueError("A mobile base's pair-restraint partner lies outside the shell; enlarge the shell")
            continue
        block = re.sub(r"(?m)^(\s*)(particle|ref_particle)\s*=\s*(\d+)",
                       lambda m: f"{m[1]}{m[2]} = {ids[int(m[3])]}", block)
        result.append("{" + block + "}")
    return "\n".join(result) + ("\n" if result else "")


class DisplayFrame(dict):
    """Source-keyed display frame with a fixed-boundary alignment reference."""
    submodel_fixed_keys = None


def display_frame(frame, path):
    """Attach stage-local alignment anchors without changing particle coordinates."""
    import json
    from pathlib import Path
    recipe_path = Path(path).parent / "submodel" / "extraction.json"
    if not recipe_path.is_file():
        return frame
    recipe = json.loads(recipe_path.read_text())
    mobile_keys = {tuple(recipe["source_keys"][i])[:3] for i in recipe["mobile_source_indices"]}
    result = DisplayFrame(frame)
    result.submodel_fixed_keys = tuple(k for k in frame if tuple(k)[:3] not in mobile_keys)
    return result
