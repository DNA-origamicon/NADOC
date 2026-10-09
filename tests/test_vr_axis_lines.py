"""Compare VR centerlines with the actual desktop axis TubeGeometry builder."""
import json
from pathlib import Path
import subprocess

import numpy as np
import pytest
from backend.core.models import Design, DeformationOp, BendParams
from backend.core.lattice import make_bundle_design
from backend.core.sweep import build_sweep, SweepRequest
from backend.core.deformation import deformed_helix_axes
from backend.core.vr_axis_lines import axis_line_paths

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize('arc_length', [False, True])
def test_batched_curve_samples_match_threejs_including_degenerate_spans(arc_length):
    from backend.core.vr_scene_projection import _centripetal_catmull_rom
    rng = np.random.default_rng(829)
    curves = [
        [[0, 0, 0], [1, 2, 3], [2, 4, 6]],
        [[2, 3, 4]] * 5,
        [[0, 0, 0], [0, 0, 0], [1, 2, 3], [1, 2, 3], [4, -1, 8]],
        np.cumsum(rng.normal(size=(37, 3)), axis=0).tolist(),
    ]
    program = """
import fs from 'node:fs';
import * as THREE from 'three';
const {curves,arc_length}=JSON.parse(fs.readFileSync(0,'utf8'));
console.log(JSON.stringify(curves.map(points=>{
 const curve=new THREE.CatmullRomCurve3(points.map(p=>new THREE.Vector3(...p)));
 return (arc_length ? curve.getSpacedPoints(83) : curve.getPoints(83)).map(p=>p.toArray());
})));
"""
    result = subprocess.run(['node', '--input-type=module', '-e', program], cwd=ROOT/'frontend',
                            input=json.dumps(dict(curves=curves, arc_length=arc_length)),
                            text=True, capture_output=True, check=True)
    for points, expected in zip(curves, json.loads(result.stdout), strict=True):
        actual = _centripetal_catmull_rom(tuple(np.asarray(p) for p in points),
                                        segments=83, arc_length=arc_length)
        np.testing.assert_allclose(actual, expected, rtol=0, atol=1e-9)


def test_two_point_curve_retains_linear_endpoint_extrapolation():
    from backend.core.vr_scene_projection import _centripetal_catmull_rom
    points = (np.array([0., 0., 0.]), np.array([1., 2., 3.]))
    for arc_length in (False, True):
        actual = _centripetal_catmull_rom(points, segments=83, arc_length=arc_length)
        np.testing.assert_allclose(actual, np.linspace(*points, 84), atol=1e-12)


DESKTOP = """
import fs from 'node:fs';
import * as THREE from 'three';
import {buildHelixObjects} from './src/scene/helix_renderer.js';
const {design,axes}=JSON.parse(fs.readFileSync(0,'utf8'));
const ctrl=buildHelixObjects([],design,new THREE.Scene(),{},[],Object.fromEntries(axes.map(a=>[a.helix_id,a])));
ctrl.setAxisShaftMode('deformed');
const paths=[];
ctrl.root.traverseVisible(o=>{if(o.name==='axisLine' && o.geometry?.type==='TubeGeometry') {
 const {path,tubularSegments}=o.geometry.parameters;
 paths.push(path.getSpacedPoints(tubularSegments).map(p=>p.toArray()));
}});
console.log(JSON.stringify(paths));
"""


@pytest.mark.parametrize('kind', ['bend','sweep'])
@pytest.mark.parametrize('gaps', [False,True])
def test_axis_curves_match_desktop_and_preserve_domain_gaps(kind,gaps):
    if kind=='sweep':
        design=build_sweep(Design(),SweepRequest(cells=[(0,0)],
            points_nm=[(0,0,0),(5,1,8),(-5,2,16),(0,0,24)],ligate_adjacent=False))
    else:
        design=make_bundle_design([(0,0)],80)
        design=design.copy_with(deformations=[DeformationOp(type='bend',plane_a_bp=0,plane_b_bp=79,
            params=BendParams(curvature_deg_per_bp=1.1,direction_deg=25))])
    if gaps:
        strands=[]
        for strand in design.strands:
            domain=strand.domains[0]
            lo,hi=sorted((domain.start_bp,domain.end_bp))
            ranges=[(lo,lo+20),(hi-20,hi)]
            if domain.start_bp>domain.end_bp:ranges=[(b,a) for a,b in reversed(ranges)]
            strands.append(strand.model_copy(update={'domains':[
                domain.model_copy(update={'start_bp':a,'end_bp':b}) for a,b in ranges]}))
        design=design.copy_with(strands=strands)
    axes=deformed_helix_axes(design)
    result=subprocess.run(['node','--input-type=module','-e',DESKTOP],cwd=ROOT/'frontend',
        input=json.dumps({'design':design.model_dump(mode='json'),'axes':axes}),text=True,capture_output=True,check=True)
    desktop=json.loads(result.stdout)
    native=[np.asarray(path) for axis,helix in zip(axes,design.helices)
            for path,_,_ in axis_line_paths(axis,helix)]
    assert len(native)==len(desktop)==(2 if gaps else 1)
    for actual,expected in zip(native,desktop):
        np.testing.assert_allclose(actual,expected,atol=1e-9)
        chord=actual[0]+np.linspace(0,1,len(actual))[:,None]*(actual[-1]-actual[0])
        assert np.max(np.linalg.norm(actual-chord,axis=1))>.05
    if gaps:assert np.linalg.norm(native[0][-1]-native[1][0])>1
    # Verify the scene exporter actually emits these curves, not endpoint chords.
    from backend.api.routes_vr import _snapshot, VRLaunchRequest
    from backend.core.vr_scene_contract import parse_scene_contract
    from urllib.parse import unquote
    text=_snapshot(VRLaunchRequest(),design_snapshot=design,representations={'full'})
    rotation=np.asarray([float(v) for v in next(l for l in text.splitlines() if l.startswith('O ')).split()[1:]]).reshape(3,3).T
    exported=[p for p in parse_scene_contract(text)['full'].values()
              if p.record_type=='C' and unquote(p.identity).endswith(':axis')]
    expected=np.asarray([[rotation@a,rotation@b] for path in native for a,b in zip(path,path[1:])])
    assert len(exported)==len(expected)
    # The scene's existing wire format uses seven significant decimal digits.
    # Compare exactly at that precision; unrounded desktop parity above is 1e-9.
    expected=np.asarray([float(f'{v:.7g}') for v in expected.ravel()]).reshape(expected.shape)
    np.testing.assert_array_equal(np.asarray([p.values[:6] for p in exported]).reshape(-1,2,3),expected)
