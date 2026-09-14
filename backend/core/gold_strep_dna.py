"""Explicitly prescribed fixed-core streptavidin/DNA example geometry."""
import numpy as np
from backend.core.models import Helix, Strand, Domain, Direction, Vec3, StrandType, BiotinDNA
from backend.core.streptavidin import streptavidin_asset
import uuid


def pocket_geometry(particle, chain):
    protein = particle.coating.protein
    template = streptavidin_asset('biotin_tether')
    a = np.array([[x.x,x.y,x.z] for x in template.atoms if x.chain_id == 'A' and x.name == 'CA'])
    b = np.array([[x.x,x.y,x.z] for x in protein.atoms if x.chain_id == chain and x.name == 'CA'])
    u, _, vt = np.linalg.svd((a-a.mean(0)).T @ (b-b.mean(0)))
    r = vt.T @ u.T
    if np.linalg.det(r)<0: vt[-1]*=-1; r=vt.T@u.T
    t = b.mean(0)-r@a.mean(0)
    ligand = {x.name: np.array([x.x,x.y,x.z]) for x in template.atoms if x.res_name=='BTN'}
    anchor = r@ligand['C11']+t
    axis = r@(ligand['C11']-ligand['C10']); axis /= np.linalg.norm(axis)
    m = particle.pose.to_array() @ particle.coating.poses[0].to_array()
    return m[:3,:3]@anchor+m[:3,3], m[:3,:3]@axis


def build_dna(particle, sequence, chain='auto', linker_nm=2.):
    if particle.kind!='gold_nanosphere' or not particle.coating or len(particle.coating.poses)!=1:
        raise ValueError('This workflow requires one gold sphere with exactly one streptavidin tetramer.')
    sequence=sequence.strip().upper()
    if not 2<=len(sequence)<=200 or any(b not in 'ACGT' for b in sequence):
        raise ValueError('Enter 2–200 DNA bases (A, C, G, T).')
    if particle.biotin_dna: raise ValueError('Remove the existing biotinylated DNA before creating another.')
    center=particle.pose.to_array()[:3,3]; radius=particle.diameter_nm/2
    choices=[]
    for site in 'ABCD':
        if particle.coating.mode=='biotin_tether' and site=='A': continue
        anchor,axis=pocket_geometry(particle,site)
        points=anchor+np.arange(0,linker_nm+len(sequence)*.34,.1)[:,None]*axis
        if np.min(np.linalg.norm(points-center,axis=1))<radius+.3: continue
        choices.append((float(np.dot(axis,(anchor-center)/np.linalg.norm(anchor-center))),site,anchor,axis))
    if chain!='auto': choices=[x for x in choices if x[1]==chain]
    if not choices: raise ValueError('No selected unoccupied pocket has a core-clear outward linker path.')
    _,site,anchor,axis=max(choices,key=lambda x:x[0])
    start=anchor+linker_nm*axis; end=start+max(.34,(len(sequence)-1)*.34)*axis
    hid='__strep_dna__'+uuid.uuid4().hex; sid=str(uuid.uuid4())
    vec=lambda a:Vec3(x=float(a[0]),y=float(a[1]),z=float(a[2]))
    helix=Helix(id=hid,axis_start=vec(start),axis_end=vec(end),length_bp=len(sequence),label='Biotinylated DNA')
    strand=Strand(id=sid,domains=[Domain(helix_id=hid,start_bp=0,end_bp=len(sequence)-1,direction=Direction.FORWARD)],strand_type=StrandType.STAPLE,sequence=sequence,name=f'5′ biotin–DNA · strep pocket {site}')
    return BiotinDNA(strand_id=sid,helix_id=hid,chain=site,linker_nm=linker_nm),helix,strand


def validate_fixed_core_design(design):
    for p in design.nanoparticles:
        if not p.oxdna_fixed_core or p.kind!='gold_nanosphere' or not p.coating or len(p.coating.poses)!=1 or len(p.biotin_dna)!=1:
            raise ValueError('oxDNA gold support currently requires fixed-core gold, one streptavidin and one biotinylated DNA per particle. Configure this in Conjugate Manager.')
        record=p.biotin_dna[0]
        strand=next((s for s in design.strands if s.id==record.strand_id),None)
        helix=next((h for h in design.helices if h.id==record.helix_id),None)
        if strand is None or helix is None:
            raise ValueError('The nanoparticle biotin–DNA attachment references a missing strand or helix.')
        if (len(strand.domains)!=1 or strand.domains[0].helix_id!=helix.id
                or strand.domains[0].start_bp!=0
                or strand.domains[0].end_bp!=helix.length_bp-1
                or strand.domains[0].direction!=Direction.FORWARD):
            raise ValueError('The biotinylated DNA handle must remain a complete forward strand on its owned helix.')
        if p.coating.mode=='biotin_tether' and record.chain=='A':
            raise ValueError('Streptavidin pocket A is already occupied by the gold tether.')
        if np.linalg.norm(helix.axis_end.to_array()-helix.axis_start.to_array())<1e-8:
            raise ValueError('The biotinylated DNA handle requires a nonzero axis.')
