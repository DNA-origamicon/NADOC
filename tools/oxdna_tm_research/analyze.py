"""Full-Hamiltonian DNA2 reweighting and mixing diagnostics for proposal pilots.

Research only. Copies no structures and writes only analysis into owned campaigns.
Native per-particle energies are converted to total reduced energies.
"""
import argparse
import json
from pathlib import Path
import subprocess
import time

import numpy as np
from scipy.special import logsumexp

from backend.core.oxdna_vmmc_precision import precision_report, inefficiency, tm_of
from tools.oxdna_umbrella.native import digest


def weighted_counts(energy, temperatures, source_temperature, q, sample_bias):
    """Inverse-bias full-Hamiltonian weights, unnormalized across equal ensembles."""
    temperatures=np.asarray(temperatures);q=np.asarray(q);sample_bias=np.asarray(sample_bias)
    kts=(temperatures+273.15)/3000
    source=np.flatnonzero(temperatures==source_temperature)
    if len(source)!=1 or energy.shape!=(len(temperatures),len(q)) or (sample_bias<=0).any():
        raise ValueError('Misaligned temperature energies or invalid bias')
    logits=-energy/kts[:,None]+energy[source[0]]/kts[source[0]]-np.log(sample_bias)
    normalized=np.exp(logits-logsumexp(logits,axis=1)[:,None])
    weights=np.exp(logits)
    if not np.isfinite(weights).all(): raise ValueError('Reweighting overflow')
    counts=np.stack([weights*(q==0),weights*(q>0)],axis=1).transpose(2,1,0)
    return counts,normalized


def passages(q, high):
    endpoints = np.where(q == 0, 0, np.where(q >= high, 1, -1))
    endpoints = endpoints[endpoints >= 0]
    n = int(np.count_nonzero(np.diff(endpoints)))
    return dict(passages=n, round_trips=n//2)


def analyze(root, binary):
    start = time.monotonic()
    root, binary = Path(root).resolve(), Path(binary).resolve(strict=True)
    manifest = json.loads((root/'manifest.json').read_text())
    result = json.loads((root/'result.json').read_text())
    assert digest(binary.parent.parent/'lib/liboxdna_common.so') == manifest['library_sha256']
    temperatures = np.arange(60., 80.01, .5)
    kts = (temperatures+273.15)/3000
    source_index = int(np.flatnonzero(temperatures == 70)[0])
    arrays, reports, native_approx_all, all_pair_arrays = [], [], [], []
    n = int((root/'topology.top').read_text().split()[0])
    for replica, paths in enumerate(result['production_directories']):
        all_data, states, sampled_bias, max_energy_error = [], [], [], 0.
        for path in paths:
            p = Path(path)
            tables = []
            for temp in temperatures:
                out = p/f'full_{temp:g}.dat'
                inp = p/f'full_{temp:g}.input'
                inp.write_text(f'''backend = CPU
interaction_type = DNA2
T = {temp}C
salt_concentration = {manifest['salt_M']}
use_average_seq = false
seq_dep_file = {root/'oxDNA2_sequence_dependent_parameters.txt'}
topology = {root/'topology.top'}
trajectory_file = {p/'trajectory.dat'}
verlet_skin = 1
analysis_data_output_1 = {{
name = {out}
print_every = 1
col_1 = {{ type = step }}
col_2 = {{ type = potential_energy }}
col_3 = {{ type = potential_energy
split = true }}
}}
''')
                with (p/f'full_{temp:g}.log').open('w') as log:
                    subprocess.run([str(binary),str(inp)],cwd=p,stdout=log,stderr=subprocess.STDOUT,check=True,timeout=60)
                data=np.loadtxt(out,ndmin=2)
                data=data[data[:,0]>0]
                if tables:
                    assert np.array_equal(data[:,0],tables[0][:,0])
                tables.append(data)
            e=np.loadtxt(p/'energy.dat',ndmin=2)
            indices=np.searchsorted(e[:,0],tables[0][:,0])
            assert np.array_equal(e[indices,0],tables[0][:,0])
            max_energy_error=max(max_energy_error,float(np.max(np.abs(tables[source_index][:,1]-e[indices,1]))))
            assert max_energy_error < 2e-5, max_energy_error
            states.extend(e[indices,5].astype(int))
            # Read exact frozen weights, not the six-digit printed bias column.
            bias=np.loadtxt(p/'weights.txt')[:,-1]
            ids=e[indices,5].astype(int)
            if manifest.get('distance_split',0):
                ids += 9*e[indices,6].astype(int)
            sampled_bias.extend(bias[ids])
            all_data.append(np.array(tables))
        data=np.concatenate(all_data,axis=1)
        q=np.array(states)
        energy=data[:,:,1]*n
        counts,normalized=weighted_counts(energy,temperatures,70,q,sampled_bias)
        arrays.append(counts)
        audit_path=root/'pairing_audit/pairing_states.npz'
        if audit_path.exists():
            audited=np.load(audit_path)[f'replica_{replica}']
            audited=audited[audited[:,0]>0]
            assert np.array_equal(audited[:,1],q)
            all_counts,_=weighted_counts(energy,temperatures,70,audited[:,2],sampled_bias)
            all_pair_arrays.append(all_counts)
        # Reconstruct native linear-in-T stacking extrapolation on identical frames.
        # Split columns: total, bond, excluded, stacking, nonbond excluded, HB, cross, coax, DH.
        # Determine column count explicitly; stacking term index is native interaction id 2.
        assert data.shape[2] == 10, data.shape
        stack=data[source_index,:,4]*n
        # Native DNA2 constants from model.h (verified in source).
        factor=2.6717
        base=1.3523
        slope=stack*factor/(base+kts[source_index]*factor)
        approximate=energy[source_index]+(kts[:,None]-kts[source_index])*slope
        residual=energy-approximate-n*(data[:,:,9]-data[source_index,:,9])
        decomposition_error=float(np.max(np.abs(residual)))
        assert decomposition_error < .001, decomposition_error
        appw=np.exp(-approximate/kts[:,None]+energy[source_index]/kts[source_index]-np.log(sampled_bias))
        native_approx_all.append(np.stack([appw*(q==0),appw*(q>0)],axis=1).transpose(2,1,0))
        idx=source_index
        u,b=counts[:,0,idx],counts[:,1,idx]
        influence=b/b.mean()-u/u.mean() if b.mean()>0 and u.mean()>0 else np.ones(len(q))
        g=inefficiency(influence)
        reports.append(dict(replica=replica,start=manifest['starts'][replica],frames=len(q),
            occupancy=np.bincount(q,minlength=9).tolist(), passages_6=passages(q,6),passages_8=passages(q,8),
            transitions=int(np.count_nonzero(np.diff(q>0))),
            tm_c=tm_of(counts.sum(axis=0),temperatures),weight_ess=(1/(normalized**2).sum(axis=1)).tolist(),
            largest_normalized_frame_weight=normalized.max(axis=1).tolist(),
            q_inefficiency=inefficiency(q),
            influence_inefficiency_70=g, effective_frames_70=len(q)/g,
            p_bound_70=float(normalized[source_index]@(q>0)),
            first_half_tm=tm_of(counts[:len(q)//2].sum(axis=0),temperatures),
            second_half_tm=tm_of(counts[len(q)//2:].sum(axis=0),temperatures),
            stacking_plus_electrostatics_decomposition_max_error=decomposition_error,
            energy_agreement_max_per_particle=max_energy_error))
    precision=precision_report(arrays,temperatures,target=1,bootstrap=1000,max_looks=1,seed=99117)
    report=dict(temperatures_c=temperatures.tolist(),replicas=reports,precision=precision,
                bound_start_tm_c=tm_of(arrays[0].sum(axis=0)+arrays[2].sum(axis=0),temperatures),
                unbound_start_tm_c=tm_of(arrays[1].sum(axis=0)+arrays[3].sum(axis=0),temperatures),
                pooled_first_half_tm_c=tm_of(sum(a[:len(a)//2].sum(axis=0) for a in arrays),temperatures),
                pooled_second_half_tm_c=tm_of(sum(a[len(a)//2:].sum(axis=0) for a in arrays),temperatures),
                all_interstrand_bond_tm_c=tm_of(sum(a.sum(axis=0) for a in all_pair_arrays),temperatures) if all_pair_arrays else None,
                native_histogram_tm_c=result['tm_c'],
                same_frame_stacking_only_tm_c=tm_of(sum(x.sum(axis=0) for x in native_approx_all),temperatures),
                analysis_seconds=time.monotonic()-start,certified=False,
                qualification='Exploratory fixed-budget intervals, not calibrated coverage. Selection and prior trials excluded from precision claim. Native-pair binding definition requires all-pair audit.')
    (root/'full_analysis.json').write_text(json.dumps(report,indent=2)+'\n')
    np.savez_compressed(root/'sufficient_statistics.npz',temperatures=temperatures,**{f'replica_{i}':a for i,a in enumerate(arrays)})
    print(json.dumps(report,indent=2))
    return report

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('campaign',type=Path)
    p.add_argument('--binary',type=Path,required=True)
    a=p.parse_args()
    analyze(a.campaign,a.binary)
