"""Fixed gold exclusion body and explicitly prescribed streptavidin restraints."""
import numpy as np
from backend.core.constants import NM_TO_OXDNA
from backend.core.models import ProteinAttachment, Mat4x4
from backend.core.protein_cg import protein_beads
from backend.core.gold_strep_dna import validate_fixed_core_design, pocket_geometry


def coating_blocks(design):
    validate_fixed_core_design(design)
    attachments=[]; blocks=[]
    for p in design.nanoparticles:
        matrix=p.pose.to_array() @ p.coating.poses[0].to_array()
        att=ProteinAttachment(id=f'{p.id}:strep:0',asset_id=p.coating.protein.id,target={'kind':'free'},pose=Mat4x4(values=matrix.ravel().tolist()))
        attachments.append(att); blocks.append(protein_beads(p.coating.protein,att))
    return attachments,blocks


def fixed_core_forces(design, attachments, blocks, geometry):
    from backend.physics.oxdna_protein import conjugation_trap_text, dna_particle_index
    from backend.physics.oxdna_interface import anchor_trap_block, resolved_nuc_map, oxdna_native_seed_map
    offset=sum(len(b) for b in blocks); parts=[]; base=0
    resolved=seed_fixed_dna(design,oxdna_native_seed_map(design,resolved_nuc_map(design,geometry)))
    for att,beads in zip(attachments,blocks):
        p=next((p for p in design.nanoparticles if att.id==f'{p.id}:strep:0'),None)
        if p is None: base+=len(beads); continue
        center=p.pose.to_array()[:3,3]*NM_TO_OXDNA
        # Upstream sphere confines particles INSIDE; moving sphere is the exterior
        # repulsive potential. Zero motion makes a fixed reference core.
        radius=(p.diameter_nm/2-.8)*NM_TO_OXDNA
        parts.append('{\ntype = repulsive_sphere_moving\nparticle = -1\nstiff = 10\nrate = 0\nsteps = 0\nr0 = %.9f\ncenter = %.9f,%.9f,%.9f\n}\n' % (radius,*center))
        xyz=np.array([b.pos_nm for b in beads])
        # Three separated contact-side beads hold the prescribed orientation while
        # allowing elastic fluctuations; no claimed adsorption free energy.
        radial=np.linalg.norm(xyz-p.pose.to_array()[:3,3],axis=1)
        candidates=np.argsort(radial)[:max(12,len(beads)//5)]
        chosen=[int(candidates[0])]
        for _ in range(2):
            chosen.append(int(max(candidates,key=lambda i:min(np.linalg.norm(xyz[i]-xyz[j]) for j in chosen))))
        for i in chosen: parts.append(anchor_trap_block(base+i,xyz[i]*NM_TO_OXDNA,10.))
        record=p.biotin_dna[0]
        anchor,_=pocket_geometry(p,record.chain)
        local=min((i for i,b in enumerate(beads) if b.chain_id==record.chain),key=lambda i:np.linalg.norm(xyz[i]-anchor))
        from backend.physics.oxdna_interface import _strand_nucleotide_order
        key=next((k for k in _strand_nucleotide_order(design) if k[0]==record.helix_id and k[1]==0),None)
        particle=dna_particle_index(design,key,offset) if key is not None else None
        if particle is None or key not in resolved: raise ValueError('Cannot resolve the biotinylated DNA 5′ terminus')
        # Linker is coarse-grained into an equilibrium-length spring; no fake BTN bead.
        from backend.physics.oxdna_interface import nuc_conf_line
        dna=np.array([float(x) for x in nuc_conf_line(resolved[key]).split()[:3]])
        rest=np.linalg.norm(dna-xyz[local]*NM_TO_OXDNA)
        parts.append(conjugation_trap_text(base+local,particle,1.424,float(rest)))
        base+=len(beads)
    return ''.join(parts)


def seed_fixed_dna(design, resolved):
    """Extended unpaired handle seed with legal oxDNA backbone lengths.

    A biotin handle is ssDNA, not a duplex whose helical rise can be reused as
    the center-to-center bead spacing. Retain stable nucleotide identities.
    """
    result=dict(resolved)
    for p in design.nanoparticles:
        if not p.oxdna_fixed_core: continue
        for record in p.biotin_dna:
            h=next(h for h in design.helices if h.id==record.helix_id)
            axis=h.axis_end.to_array()-h.axis_start.to_array(); axis/=np.linalg.norm(axis)
            normal=np.cross(axis,[1.,0.,0.] if abs(axis[0])<.9 else [0.,1.,0.]);normal/=np.linalg.norm(normal)
            for key,nuc in resolved.items():
                if key[0]!=record.helix_id: continue
                result[key]={**nuc,'backbone_position':(h.axis_start.to_array()+axis*key[1]*.7564/NM_TO_OXDNA).tolist(), 'base_normal':normal.tolist(),'axis_tangent':axis.tolist()}
    return result
