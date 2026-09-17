"""Matched DNA-only/mobile-gold CUDA timing on a real origami fixture.

Builds isolated copies; never modifies the source design. Grafts one existing
terminal staple nucleotide to an exterior core to test transmission into origami.
"""
import argparse,json,subprocess,time,copy
from pathlib import Path
import numpy as np
from backend.core.models import Design, NanoparticleConjugation, NanoparticleSurfaceStrand, Mat4x4
from backend.core.nanoparticle import create_gold_nanosphere
from backend.api.crud import _geometry_for_design
from backend.physics.oxdna_interface import write_configuration,write_topology,write_mutual_traps,_walk_strand_nucleotides
from backend.physics.oxdna_mobile_gold import append_mobile_gold,find_mobile_gold_oxdna,configure_mobile_gold_stages
from backend.core.oxdna_protocol import OxdnaStageSpec,render_stage_input


def main(out,source,steps=20000,coating_count=0):
    out.mkdir(parents=True,exist_ok=False)
    original=Design.from_json(source.read_text()).without_reference_geometry()
    records=[]
    for name in ('dna','gold'):
        d=out/name;d.mkdir();design=copy.deepcopy(original)
        write_topology(design,d/'topology.top');write_configuration(design,_geometry_for_design(design),d/'conf.dat',oxdna_native_seed=True)
        write_mutual_traps(design,d/'forces.txt')
        n=len(list(_walk_strand_nucleotides(design)))
        if name=='gold':
            rows=np.loadtxt(d/'conf.dat',skiprows=3);by_strand={}
            for i,step in enumerate(_walk_strand_nucleotides(design)):by_strand.setdefault(step.strand.id,[]).append((i,step))
            candidates=[entry[0] for entry in by_strand.values()]
            i,step=max(candidates,key=lambda v:rows[v[0],0])
            a1,a3=rows[i,3:6],rows[i,6:9];back=(rows[i,:3]-.34*a1+.3408*np.cross(a3,a1))*.8518
            p=create_gold_nanosphere(10);m=np.eye(4);m[:3,3]=back+[5.7,0,0];p.pose=Mat4x4(values=m.ravel().tolist())
            c=NanoparticleConjugation(nanoparticle_id=p.id,sequence=step.strand.sequence,requested_count=1,estimated_capacity=1,density_per_nm2=1/(100*np.pi),surface_strands=[NanoparticleSurfaceStrand(strand_id=step.strand.id,helix_id=step.key[0],overhang_id='validation_graft',site_local=(-1,0,0),sulfur_local_nm=(-5,0,0))])
            design.nanoparticles=[p];design.nanoparticle_conjugations=[c]
            if coating_count:
                from backend.core.streptavidin import build_streptavidin_coating
                p.coating=build_streptavidin_coating(10,count_override=coating_count)
            manifest=append_mobile_gold(design,d)
            (d/'design.json').write_text(design.model_dump_json())
        stage=OxdnaStageSpec('benchmark','md_relax','MD',steps,'CUDA',dt=.002,thermostat='langevin',diff_coeff=2.5,refresh_vel=False,seed=123,external_forces=True,max_backbone_force=5,max_backbone_force_far=10,print_conf_interval_override=steps,print_energy_every_override=steps)
        if name=='gold':configure_mobile_gold_stages([stage])
        text=render_stage_input(stage,'topology.top','conf.dat',forces_name='forces.txt')
        if name=='dna':
            # Permit zero initial momenta in the baseline using identical tiny initial L.
            rows=np.loadtxt(d/'conf.dat',skiprows=3);rows[:,12:15]=1e-9
            header=(d/'conf.dat').read_text().splitlines()[:3]
            (d/'conf.dat').write_text('\n'.join(header)+'\n'+'\n'.join(' '.join(map(str,r)) for r in rows)+'\n')
        text+='\nCUDA_avoid_cpu_calculations = true\nconfiguration_print_energy = false\nprint_initial_energy = false\nno_stdout_energy = true\n'
        (d/'input').write_text(text)
        start=time.perf_counter()
        with (d/'run.log').open('w') as log:
            proc=subprocess.run([find_mobile_gold_oxdna(),'input'],cwd=d,stdout=log,stderr=subprocess.STDOUT,timeout=240)
        elapsed=time.perf_counter()-start
        if proc.returncode:raise RuntimeError((d/'run.log').read_text()[-2000:])
        final=np.loadtxt(d/'last_conf.dat',skiprows=3)
        if not np.isfinite(final).all():raise RuntimeError('Nonfinite benchmark')
        rec=dict(name=name,coating_count=coating_count if name=='gold' else 0,n_dna=n,steps=steps,wall_s=elapsed,steps_per_s=steps/elapsed)
        if name=='gold':
            g=manifest['grafts'][0];ci=manifest['cores'][0]['index'];row=final[g['dna']];a1,a3=row[3:6],row[6:9]
            bb=row[:3]-.34*a1+.3408*np.cross(a3,a1)
            cp=final[ci];rot=np.column_stack((cp[3:6],np.cross(cp[6:9],cp[3:6]),cp[6:9]));anchor=cp[:3]+rot@np.array(g['site'])
            rec.update(linker_nm=float(np.linalg.norm(bb-anchor)*.8518),core_displacement_nm=float(np.linalg.norm(cp[:3]*.8518-m[:3,3])),core_rotation_rad=float(np.arccos(np.clip((np.trace(rot)-1)/2,-1,1))))
        records.append(rec);(out/'results.json').write_text(json.dumps(records,indent=2));print(rec,flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);p.add_argument('--source',type=Path,default=Path('workspace/3x6Sq_oxDNA.nadoc'));p.add_argument('--steps',type=int,default=20000);p.add_argument('--coating-count',type=int,default=0);a=p.parse_args();main(a.output,a.source,a.steps,a.coating_count)
