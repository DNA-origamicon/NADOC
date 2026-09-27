"""Audit native frames against the original QM fragment stereocenters and fitted charges."""

from pathlib import Path
import sys

import numpy as np
from openmm import app

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
from experiments.cpd_anti_additive.preliminary_protocol import require
from experiments.cpd_anti_additive.validation_gate import read, checked, source
from experiments.cpd_anti_additive.prepare_engine_v2 import save
from experiments.cpd_anti_additive.run_engine_v2 import read_binary
from backend.core.dcd_fast import read_layout, read_frame

ART = REPO/'.development-artifacts'


def volume(x):
    a, b, c, d = x
    return float(np.dot(b-a, np.cross(c-a, d-a)))


def review():
    _, receipt = require('engine')
    candidate = Path(receipt['candidate'])
    root = ART/'cpd-anti-native-smoke-v2b'
    result = read(root/'assessment.json')
    assert result['engineering_test_passed'] and not result['preliminary_research_qualified']
    names = read(candidate/'two-nucleosides/atom_map.json')
    psf = app.CharmmPsfFile(str(candidate/'two-nucleosides/fragment.psf'))
    assert len(names)==len(psf.atom_list)==62 and len(psf.residue_list)==2
    assert len(psf.bond_list)==66 and abs(sum(a.charge for a in psf.atom_list))<1e-8
    expected_links = {('1:C5', '2:C6'), ('1:C6', '2:C5')}
    links = {tuple(sorted((names[b.atom1.idx], names[b.atom2.idx]))) for b in psf.bond_list
             if names[b.atom1.idx][0]!=names[b.atom2.idx][0]}
    assert links==expected_links
    centers = []
    fitpath = ART/'cpd-anti-charge-minima-fit-v2/assessment.json'
    fit = read(fitpath)
    for endpoint in (1, 2):
        folder = candidate/f'endpoint-{endpoint}'
        source_names = read(folder/'atom_map.json')
        original_qm = np.loadtxt(folder/'starting_A.txt')
        native = app.CharmmPsfFile(str(folder/'fragment.psf'))
        fitted = next(r for r in fit['records'] if r['id']==f'endpoint-{endpoint}-original')
        assert fitted['names']==source_names
        for key in names:
            if key.startswith(f'{endpoint}:'):
                assert abs(psf.atom_list[names.index(key)].charge-
                           fitted['charges_e'][source_names.index(key)])<1e-11
        for atom in ('C5', 'C6', "C1'", "C3'", "C4'"):
            key = f'{endpoint}:{atom}'
            index = source_names.index(key)
            ns = []
            for bond in native.bond_list:
                a, b = bond.atom1.idx, bond.atom2.idx
                if a==index:
                    ns.append(b)
                elif b==index:
                    ns.append(a)
            assert len(ns)==4
            centers.append(dict(key=key, reference_volume=volume(original_qm[ns]),
                indices=[names.index(source_names[i]) for i in ns],
                original_fragment=source(folder/'starting_A.txt')))
    trajectory = checked(result['smoke']['trajectory'])
    layout = read_layout(trajectory)
    frames = [read_frame(trajectory, layout, i)[0] for i in range(layout.n_frames)]
    frames.append(read_binary(root/'smoke/smoke.coor', 62))
    stereo = []
    for center in centers:
        products = [volume(x[center['indices']])*center['reference_volume'] for x in frames]
        stereo.append(dict(**center, all_frames_preserved=bool(min(products)>0)))
    distances = {}
    for a, b in sorted(links):
        values = [np.linalg.norm(x[names.index(a)]-x[names.index(b)]) for x in frames]
        distances[f'{a}--{b}'] = [float(min(values)), float(max(values))]
    for comparison in result['native_equivalence']:
        checked(comparison['log'])
        checked(comparison['forces'])
        assert comparison['energy_error_kcal']<.001 and comparison['max_force_error_kcal_A']<.001
    assert result['smoke']['final_step']==101000 and layout.n_frames==101
    assert all(s['all_frames_preserved'] for s in stereo)
    output = root/'independent_review.json'
    if output.exists():
        raise FileExistsError(output)
    report = dict(passed=True, assessment=source(root/'assessment.json'),
        stereochemistry_reference='Original QM endpoint fragments; four lesion plus six sugar stereocenters',
        centers=stereo, inspected_frames_including_final=len(frames), crosslink_ranges_A=distances,
        exact_charge_transfer=True, net_charge=float(sum(a.charge for a in psf.atom_list)),
        verified_native_comparisons=len(result['native_equivalence']),
        native_duration_ps=100, environment='Vacuum', full_DNA_NAMD_tested=False,
        preliminary_research_qualified=False, simulation_ready=False, reviewer=source(Path(__file__)))
    save(output, report)
    print({k:v for k,v in report.items() if k not in ('centers', 'reviewer', 'assessment')})


if __name__=='__main__':
    review()
