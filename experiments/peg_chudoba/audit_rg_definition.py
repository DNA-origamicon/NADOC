"""Audit mean Rg versus RMS Rg against the published 795-mer density curves.

This checks consistency between two panels, not simulation validation. Coordinates
are taken from vector paths of the pinned preprint; no model output is used.
"""
import hashlib
import json
from pathlib import Path
import numpy as np
import pymupdf


def main():
    root = Path(__file__).parent / 'reference'
    source = root / 'chudoba_2017_preprint.pdf'
    drawings = pymupdf.open(source)[8].get_drawings()
    targets = json.loads((root / 'published_targets.json').read_text())['chain_dimensions']
    rows = []
    for temperature, start, stop in [(294,2,5),(320,5,8),(347,8,11),
                                    (361,11,14),(371,14,17),(381,17,20),(396,20,23)]:
        points = []
        for index in range(start, stop):
            items = drawings[index]['items']
            if index == start:
                items = items[1:]  # Separate horizontal legend sample.
            for kind, a, b in items:
                assert kind == 'l'
                for p in (a,b):
                    points.append((2+(p.x-92.46399688720703)/194*12,
                                   (173.1389923095703-p.y)/113.05000305175781*2))
        xy = np.array(sorted(set(points)))
        x, y = xy.T
        assert np.all(np.diff(x)>0) and y.min()>-1e-6
        # Exact integration of x^k times each piecewise-linear density segment
        # using two-point Gauss quadrature (polynomial degree <= 3).
        mid=(x[:-1]+x[1:])/2; half=np.diff(x)/2
        q=np.stack([mid-half/np.sqrt(3),mid+half/np.sqrt(3)])
        density=y[:-1]+(q-x[:-1])*(np.diff(y)/np.diff(x))
        moments=[float(np.sum(half*density*q**k)) for k in range(3)]
        mean=moments[1]/moments[0]; rms=np.sqrt(moments[2]/moments[0])
        marker=next(r['rg_nm'] for r in targets if r['figure']=='7b' and r['n']==795 and r['temperature_K']==temperature)
        rows.append(dict(temperature_K=temperature,plotted_density_area=moments[0],
                         mean_rg_nm=mean,rms_rg_nm=float(rms),panel_b_marker_nm=marker,
                         mean_minus_marker_nm=mean-marker,rms_minus_marker_nm=float(rms-marker),
                         vector_points=len(x),range_nm=[float(x[0]),float(x[-1])]))
    report=dict(source='arXiv:1710.09191v1, Figure 7(a,b)',source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
                method='Piecewise-linear vector density paths, exact moments by Gauss quadrature; normalize each plotted curve area.',
                limitation='Finite plot range, rounded vector coordinates and histogram smoothing; this is an observable-convention cross-check, not raw trajectory data.',
                results=rows)
    (root/'rg_definition_audit.json').write_text(json.dumps(report,indent=2)+'\n')
    for r in rows:print(f"{r['temperature_K']} K: mean={r['mean_rg_nm']:.4f}, RMS={r['rms_rg_nm']:.4f}, marker={r['panel_b_marker_nm']:.4f}, area={r['plotted_density_area']:.4f}")


if __name__=='__main__':main()
