"""GPU-resident larger-box six-replica validation; fixed original context deadline."""
import argparse
import os
from pathlib import Path
import subprocess
import sys
import time
import traceback

import numpy as np

REPO = Path(os.environ.get('NADOC_REPO_ROOT', Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(REPO))
from experiments.cpd_anti_additive.validation_gate import read, source, checked
from experiments.cpd_anti_additive.sella_pilot import save, now
from experiments.cpd_anti_additive.gpu_largebox_startup_v3 import (
    ROOT, ART, NAMD, config, checkpoint as check_checkpoint, evaluate, dimensions)
from experiments.cpd_anti_additive.run_engine_v2 import read_binary
from experiments.cpd_anti_additive.native_log_v3 import parse_log
from backend.core.dcd_fast import read_layout, read_frame
N = dimensions()[1]


def dihedral(x, ids):
    a, b, c, d = x[ids]
    axis = c - b
    axis /= np.linalg.norm(axis)
    v = a - b; v -= np.dot(v, axis) * axis
    w = d - c; w -= np.dot(w, axis) * axis
    return float(np.degrees(np.arctan2(np.dot(np.cross(axis, v), w), np.dot(v, w))))


def observables(x, spec, case):
    selection = spec['cases'][case]
    local = set(spec['local_residue_indices'])
    rings = {}; residues = []
    for r in selection['residues']:
        points = x[r['ring']]
        center = points.mean(axis=0)
        normal = np.linalg.svd(points-center)[2][-1]
        rings[r['residue_index']] = (center, normal)
        if r['residue_index'] in local:
            sugar = r['sugar']
            residues.append(dict(residue_index=r['residue_index'],
                sugar_dihedrals_deg=[dihedral(x, [sugar[(i+j)%5] for j in range(4)]) for i in range(5)],
                chi_deg=dihedral(x, r['chi']),
                attachment_A=float(np.linalg.norm(x[r['attachment'][0]]-x[r['attachment'][1]]))))
    def pair_metrics(pairs):
        result = []
        for a, b in pairs:
            ca, na = rings[a]; cb, nb = rings[b]
            delta = cb-ca
            distance = float(np.linalg.norm(delta))
            projection = float(abs(np.dot(delta, na)))
            result.append(dict(residues=[a,b],centroid_distance_A=distance,
                normal_angle_deg=float(np.degrees(np.arccos(np.clip(abs(np.dot(na,nb)),0,1)))),
                projected_separation_A=projection,
                lateral_displacement_A=float(np.sqrt(max(0,distance**2-projection**2)))))
        return result
    distances = [float(np.linalg.norm(x[c['atoms'][0]]-x[c['atoms'][1]]))
                 for c in selection['source_close_interstrand_polar_contacts']]
    return dict(lesion_cross_distances_A=[float(np.linalg.norm(x[a]-x[b]))
                for a,b in spec['lesion_cross_bonds']],local_residues=residues,
                polar_contact_distances_A=distances,
                source_contact_fraction=float(np.mean(np.array(distances)<3.5)),
                contact_ring_pairs=pair_metrics(selection['contact_residue_pairs']),
                adjacent_stack_pairs=pair_metrics(selection['stack_pairs']))


def segment_config(case, checkpoint, seed, first):
    text = config(case, Path(str(checkpoint)+'.coor'), first=first, seed=seed, checkpoint=checkpoint)
    text = text.replace('DCDfreq 500\n','DCDfreq 5000\n')
    text = text.replace('restartfreq 500\n','restartfreq 50000\n')
    text = text.replace('outputEnergies 500\n','outputEnergies 5000\n')
    # Explicit final checkpoint also covers endpoints not divisible by restartfreq.
    return text + 'run 500000\noutput result.restart\noutput result\n'


def review_segment(case, out, first, spec):
    rows = parse_log(out/'run.log')
    last = first+500000
    assert rows[0]['TS']==first and rows[-1]['TS']==last
    layout = read_layout(out/'result.dcd')
    assert layout.n_atoms==N and layout.n_frames==100 and layout.nsavc==5000
    assert layout.istart==first+5000 and layout.istart+99*5000==last
    records = []
    for i in range(101):
        x = (read_frame(out/'result.dcd',layout,i)[0] if i<100
             else read_binary(out/'result.coor',N))
        assert np.isfinite(x).all()
        physical = evaluate(case,x,i<100); gap = physical['image_clearance_A']; g = physical['geometry']
        item = dict(frame=i,final=i==100,step=first+(i+1)*5000 if i<100 else last,
                    geometry=g,image_clearance_A=gap,physical=physical,observables=observables(x.astype(float),spec,case))
        records.append(item)
        if not physical['passed']:
            save(out/'failed_frame_review.json',records)
            raise RuntimeError(f'Chemistry or image-clearance gate failed: {out}, frame {i}')
    save(out/'frames_review.json',records)
    cp = check_checkpoint(out,last)
    result = dict(at=now(),passed=True,first_step=first,last_step=last,duration_ns=1,
        frames=100,geometries=101,min_image_clearance_A=min(r['image_clearance_A'] for r in records),
        checkpoints=cp,config=source(out/'run.conf'),log=source(out/'run.log'),
        trajectory=source(out/'result.dcd'),frame_review=source(out/'frames_review.json'),
        temperature_range_K=[min(r['TEMP'] for r in rows),max(r['TEMP'] for r in rows)])
    return result,rows


def run():
    plan = read(ROOT/'validation_plan.json')
    for pin in plan['inputs']:checked(pin)
    assert read(checked(plan['startup_audit']))['passed']
    context = read(checked(plan['context_started']))
    deadline = context['deadline_epoch']
    assert time.time()<deadline
    spec = read(checked(plan['observables']))
    with (ROOT/'validation_started.json').open('x') as f:
        import json
        json.dump(dict(at=now(),epoch=time.time(),deadline_epoch=deadline,
                       plan=source(ROOT/'validation_plan.json')),f,indent=2)
    results = []
    try:
        # Round-robin segments distribute validation equally across paired replicas.
        for chunk in range(1,11):
            for replica, paired_seed in enumerate(plan['paired_seeds'],1):
                for case in plan['cases']:
                    assert not read(ART/'cpd-anti-validation-v1/campaign_pause.json')['paused']
                    first = 55000+(chunk-1)*500000
                    folder = ROOT/case/f'replica-{replica}'
                    previous = (folder/'restart' if chunk==1
                                else folder/'validation'/f'segment-{chunk-1:02d}')
                    checkpoint = previous/'result.restart'
                    input_pins = check_checkpoint(previous,first)
                    prev_rows = parse_log(previous/'run.log')
                    out = folder/'validation'/f'segment-{chunk:02d}'
                    out.mkdir(parents=True,exist_ok=False)
                    seed = paired_seed+2000+100*chunk
                    (out/'run.conf').write_text(segment_config(case,checkpoint,seed,first))
                    save(out/'inputs.json',dict(checkpoints=input_pins,previous_log=source(previous/'run.log'),
                        first_step=first,seed=seed,random_state_note='Fresh declared Langevin seed per restart; no claim of bitwise trajectory continuity'))
                    save(ROOT/'validation_progress.json',dict(at=now(),completed=results,
                        running=dict(case=case,replica=replica,segment=chunk)))
                    remaining = deadline-time.time()
                    assert remaining>0,'Original 36h context budget exhausted'
                    with (out/'run.log').open('w') as log:
                        p = subprocess.run([str(NAMD),'+p4','+devices','0','run.conf'],cwd=out,stdout=log,
                            stderr=subprocess.STDOUT,timeout=remaining)
                    save(out/'native_exit.json',dict(at=now(),returncode=p.returncode))
                    assert p.returncode==0,f'Native failure in {out}'
                    assert 'Running with GPU-resident mode' in (out/'run.log').read_text()
                    result,rows = review_segment(case,out,first,spec)
                    delta = abs(rows[0]['POTENTIAL']-prev_rows[-1]['POTENTIAL'])
                    limit = max(.01,1e-6*abs(prev_rows[-1]['POTENTIAL']))
                    assert delta<=limit,'Restart initial potential mismatch'
                    # Static CPU-bonded reference only: no CPU dynamics. Replay saved state.
                    ref=out/'endpoint-reference';ref.mkdir(exist_ok=False)
                    (ref/'run.conf').write_text(config(case,out/'result.restart.coor',first+500000,
                        seed,out/'result.restart',False)+'run 0\n')
                    with (ref/'run.log').open('w') as log:
                        pr=subprocess.run([str(NAMD),'+p4','+devices','0','run.conf'],cwd=ref,
                            stdout=log,stderr=subprocess.STDOUT,timeout=max(.01,deadline-time.time()))
                    save(ref/'native_exit.json',dict(at=now(),returncode=pr.returncode))
                    assert pr.returncode==0
                    refrows=parse_log(ref/'run.log')
                    assert refrows[-1]['TS']==first+500000
                    edelta=abs(refrows[-1]['POTENTIAL']-rows[-1]['POTENTIAL'])
                    elimit=max(.01,1e-6*abs(rows[-1]['POTENTIAL']))
                    assert edelta<=elimit,'Stored endpoint reference potential mismatch'
                    result.update(endpoint_reference_error_kcal=edelta,endpoint_reference_limit_kcal=elimit,
                        endpoint_reference_log=source(ref/'run.log'))
                    assert time.time()<deadline,'Original 36h context budget exhausted during analysis'
                    result.update(case=case,replica=replica,segment=chunk,seed=seed,
                        restart_energy_error_kcal=delta,restart_energy_limit_kcal=limit)
                    save(out/'assessment.json',result)
                    results.append(result)
        assert len(results)==60
        save(ROOT/'validation_assessment.json',dict(at=now(),all_native_and_chemistry_gates_passed=True,
             results=results,ns_each=10,replicas_each=3,structural_observable_review_pending=True,
             simulation_ready=False,minimum_certified=False))
    except BaseException:
        (ROOT/'validation_failure_traceback.txt').write_text(traceback.format_exc())
        save(ROOT/'validation_assessment.json',dict(at=now(),all_native_and_chemistry_gates_passed=False,
             results=results,simulation_ready=False,minimum_certified=False))
        raise


if __name__=='__main__':
    argparse.ArgumentParser(description=__doc__).parse_args()
    run()
