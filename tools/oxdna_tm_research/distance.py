"""Native two-coordinate VMMC umbrella support, research only.

q is native HB count; d is native minimum-base-distance bin. Native histograms
already remove both-coordinate bias. Marginalization sums, never averages bins.
"""
from pathlib import Path
import re
import numpy as np
from backend.core.oxdna_vmmc_precision import precision_report


def table(weights,n_pairs):
    ids=np.arange(len(weights))
    return np.column_stack((ids%(n_pairs+1),ids//(n_pairs+1),weights))


def parse_rows(text,n_pairs,n_temperatures):
    a=np.array([list(map(float,line.split())) for line in text.splitlines() if line.strip() and not line.startswith('#')])
    assert a.shape==(2*(n_pairs+1),n_temperatures+4),a.shape
    assert np.isfinite(a).all() and (a>=0).all()
    index=(a[:,0]+(n_pairs+1)*a[:,1]).astype(int)
    order=np.argsort(index)
    assert np.array_equal(index[order],np.arange(len(a)))
    return np.column_stack((index[order],a[order,2:]))


def histogram(path,n_pairs,n_temperatures):
    return parse_rows(Path(path).read_text(),n_pairs,n_temperatures)


def campaign_report(paths,temperatures,n_pairs,**options):
    arrays=[];transitions=[];cadence=None
    for replica in paths:
        blocks=[];states=[]
        for path in replica:
            p=Path(path)
            previous=np.zeros((2*(n_pairs+1),len(temperatures)+2));last_step=0
            for record in re.split(r'(?m)^#t\s*=\s*',(p/'traj_hist.dat').read_text())[1:]:
                header,_,rows=record.partition('\n');step=int(header.split(';')[0])
                native_ts=np.array(list(map(float,header.split('extr. Ts:')[1].split())))*3000-273.15
                assert np.allclose(native_ts,temperatures,atol=.002,rtol=0)
                a=parse_rows(rows,n_pairs,len(temperatures))[:,1:]
                if step==0: previous=a;continue
                delta=a-previous
                assert (delta>=-2e-5*np.maximum(a,previous)-1e-10).all()
                delta=np.maximum(delta,0)
                unbound=(np.arange(len(a))%(n_pairs+1))==0
                blocks.append(np.stack((delta[unbound,2:].sum(axis=0),delta[~unbound,2:].sum(axis=0))))
                if last_step: assert step-last_step==cadence
                cadence=step-last_step;last_step=step;previous=a
            e=np.loadtxt(p/'energy.dat',ndmin=2)
            states.extend(e[e[:,0]>0,5]>0)
        arrays.append(np.array(blocks));transitions.append(int(np.count_nonzero(np.diff(states))))
    result=precision_report(arrays,temperatures,**options)
    result.update(recorded_transitions=transitions,histogram_interval_steps=cadence)
    if min(transitions)<20:
        result['reasons'].append('Fewer than twenty recorded binding/unbinding transitions in a replica.')
        result.update(status='inconclusive',nominal_target_met=False,early_stop_target_met=False)
    return result
