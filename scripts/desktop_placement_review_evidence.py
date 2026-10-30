"""Retain aligned-document geometry comparisons for the fixture-context incident."""
import ast
import hashlib
import json
from pathlib import Path
import subprocess
from unittest.mock import patch

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
import orjson
from backend.core import design_geometry as geometry
from backend.core.models import Design
from backend.core.native_slab_placement import authoritative_slab_pose
from tests.test_native_compact_geometry import _design

BASELINE = '2f3b962966b4917d9f626e486d56680306600363'
OUT = Path('docs/benchmarks/desktop')


def main():
    source = subprocess.check_output(['git','show',f'{BASELINE}:backend/core/design_geometry.py'],text=True)
    ns = dict(vars(geometry))
    node = next(n for n in ast.parse(source).body if isinstance(n, ast.FunctionDef) and n.name == '_strand_nucleotide_info')
    exec(compile(ast.Module(body=[node],type_ignores=[]),'<original-metadata>','exec'),ns)
    figure, axes = plt.subplots(2, 3, figsize=(12, 8))
    cases = []
    for ax, kind in zip(axes.flat, ['straight','bend','twist','sweep','partial']):
        design = _design(kind)
        serialized = design.model_dump_json()
        with patch.object(geometry,'_strand_nucleotide_info',ns['_strand_nucleotide_info']):
            before = geometry._geometry_for_design(design)
        after = geometry._geometry_for_design(design)
        assert orjson.dumps(before) == orjson.dumps(after)
        assert geometry._geometry_for_design(Design.model_validate_json(serialized)) == after
        hid = design.helices[0].id
        assert geometry._geometry_for_helices(design,helix_ids=frozenset([hid])) == [r for r in after if r['helix_id']==hid]
        sites = []
        for expected, actual in zip(before,after):
            authoritative_slab_pose(actual)
            fields = {}
            for field in ['backbone_position','base_position','slab_position','slab_quaternion','axis_tangent','base_normal']:
                a,b = np.asarray(expected[field]),np.asarray(actual[field])
                fields[field] = dict(expected=a.tolist(),actual=b.tolist(),delta=(b-a).tolist())
            sites.append(dict(identity={k:actual[k] for k in ['helix_id','bp_index','direction','copy_k']},fields=fields))
        b=np.asarray([r['backbone_position'] for r in before]);a=np.asarray([r['backbone_position'] for r in after]); slab=np.asarray([r['slab_position'] for r in after])
        ax.scatter(b[:,0],b[:,2],s=18,facecolors='none',edgecolors='#225ea8',label='Original backbone')
        ax.scatter(a[:,0],a[:,2],s=6,c='#d95f0e',marker='+',label='Current backbone')
        ax.scatter(slab[:,0],slab[:,2],s=3,c='#238b45',label='Authoritative slab')
        ax.set(title=f'{kind}: {len(after)} sites, max delta 0 nm',xlabel='x (nm)',ylabel='z (nm)');ax.set_aspect('equal',adjustable='datalim')
        cases.append(dict(kind=kind,sites=sites,exact_json=True,reload_exact=True,partial_exact=True,input_unchanged=design.model_dump_json()==serialized))
    axes.flat[-1].axis('off');handles,labels=axes.flat[0].get_legend_handles_labels();axes.flat[-1].legend(handles,labels,loc='center')
    figure.suptitle('Aligned-document review: same-frame native geometry\nOriginal/current metadata helper; no placement formulas changed')
    figure.tight_layout();figure.savefig(OUT/'round2_placement_shared_frame.png',dpi=120);plt.close(figure)
    (OUT/'round2_placement_site_evidence.json').write_text(json.dumps(dict(baseline=BASELINE,scope='Aligned document metadata comparison. Not displacement evidence for mismatched documents; those HTTP failures cannot be assigned a physical displacement.',source_sha256=hashlib.sha256(Path(geometry.__file__).read_bytes()).hexdigest(),cases=cases),separators=(',',':'))+'\n')
    print([(c['kind'],len(c['sites'])) for c in cases])


if __name__=='__main__':main()
