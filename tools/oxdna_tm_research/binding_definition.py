"""Compare native-register and any-interstrand association from retained audits."""
import argparse
import json
from pathlib import Path
import time
import numpy as np
from backend.core.oxdna_vmmc_precision import precision_report,tm_of
from tools.oxdna_tm_research.analyze import passages


def analyze(root):
    start=time.monotonic();root=Path(root)
    with np.load(root/'sufficient_statistics.npz') as original, np.load(root/'pairing_audit/pairing_states.npz') as pairing:
        temperatures=original['temperatures'];arrays=[];rows=[]
        for i in range(4):
            counts=original[f'replica_{i}'];p=pairing[f'replica_{i}'];p=p[p[:,0]>0]
            assert len(p)==len(counts)
            bound=p[:,2]>0;weights=counts.sum(axis=1)
            a=np.stack((weights*(~bound)[:,None],weights*bound[:,None]),axis=1);arrays.append(a)
            native_q=p[:,1];true_endpoint_q=np.where((native_q==0)&bound,-1,native_q)
            rows.append(dict(replica=i,true_unbound_to_native8=passages(true_endpoint_q,8),true_unbound_to_native6=passages(true_endpoint_q,6),matched_10k_true_unbound_to_native8=passages(true_endpoint_q[p[:,0]%10000==0],8),native0_frames=int((native_q==0).sum()),native0_with_interstrand_bonds=int(((native_q==0)&bound).sum())))
        report=precision_report(arrays,temperatures,target=1,bootstrap=1000,max_looks=1,seed=99117)
        return dict(precision=report,replicas=rows,bound_start_tm_c=tm_of(arrays[0].sum(axis=0)+arrays[2].sum(axis=0),temperatures),unbound_start_tm_c=tm_of(arrays[1].sum(axis=0)+arrays[3].sum(axis=0),temperatures),analysis_seconds=time.monotonic()-start,certified=False,qualification='Any interstrand hydrogen bond defines association; unbound macrostate excludes non-native interstrand bonds. Sampling uncertainty remains conditional and uncalibrated for hidden states.')

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('campaign');a=p.parse_args();r=analyze(a.campaign);Path(a.campaign,'binding_definition.json').write_text(json.dumps(r,indent=2)+'\n');print(json.dumps(r,indent=2))
