"""Compare published vector pair curves with analytic parameters and tail rules.

Figure 4(b) is a direct Hamiltonian cross-check, independent of chain-size fits.
"""
import hashlib
import json
from pathlib import Path
import numpy as np
import pymupdf
from tools.oxdna_peg.chudoba_reference import parameters


def energy(r,p):
    n,m=p['n'],p['m']
    return (p['epsilon']*n/(n-m)*(n/m)**(m/(n-m))*((p['sigma']/r)**n-(p['sigma']/r)**m)
            +p['gamma']*np.exp(-((r-p['mu'])/p['delta'])**2))


def main():
    root=Path(__file__).parent/'reference';source=root/'chudoba_2017_preprint.pdf'
    page=pymupdf.open(source)[6];rows=[]
    for temperature,indices,discrete in [(294,[71,72],dict(m=10.14,sigma=.4081,mu=.6888)),
                                         (371,[86,87],dict(m=6.53,sigma=.4188,mu=.7070))]:
        points=[]
        for j,index in enumerate(indices):
            for item in page.get_drawings()[index]['items'][1 if j==0 else 0:]:
                assert item[0]=='l'
                for pt in item[1:]:
                    points.append((.3+(pt.x-97.21399688720703)/190.40001678466797*.9,
                                   (187.49298095703125-pt.y)/77.25*1.5))
        xy=np.array(sorted(set(points)));x,y=xy.T
        grid=np.linspace(.45,.895,446);observed=np.interp(grid,x,y)
        p=parameters(temperature)
        variants=[]
        for parameter_source in ('continuous_table2','discrete_tableS1'):
            q=dict(p)
            if parameter_source=='discrete_tableS1':q.update(discrete)
            raw=energy(grid,q)
            for rule in ('raw','shifted','zero_outer_attractive_tail'):
                if rule=='raw':predicted=raw
                elif rule=='shifted':predicted=raw-energy(.9,q)
                else:predicted=np.where(grid>q['mu'],np.maximum(raw,0),raw)
                variants.append(dict(parameters=parameter_source,tail_rule=rule,
                    rmse_kj_per_mol=float(np.sqrt(np.mean((predicted-observed)**2))),
                    maximum_absolute_error_kj_per_mol=float(np.max(np.abs(predicted-observed)))))
        rows.append(dict(temperature_K=temperature,variants=variants,
            vector_points_nm_kj_per_mol=xy.tolist(),
            samples=[dict(r_nm=float(r),published_kj_per_mol=float(np.interp(r,x,y)),
                          continuous_raw_kj_per_mol=float(energy(r,p))) for r in [.5,.6,.7,.8,.83,.85,.87,.89]]))
    report=dict(source='arXiv:1710.09191v1 Figure 4(b), page 7',source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
        method='Digitized vector lines with legend segments excluded. Compare 0.45–0.895 nm at 0.001 nm spacing; no parameters fit.',
        limitations='Rounded drawing coordinates and line interpolation; Figure 4 discrete fitted potentials need not equal the continuous functions used in Figure 7. Final journal main text and original GROMACS tables still unavailable.',results=rows)
    (root/'potential_curve_audit.json').write_text(json.dumps(report,indent=2)+'\n')
    for row in rows:
        print(row['temperature_K'])
        for v in row['variants']:print(v)


if __name__=='__main__':main()
