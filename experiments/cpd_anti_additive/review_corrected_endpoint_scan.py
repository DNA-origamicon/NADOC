"""Review constrained progress and conformational changes without new QM."""
from pathlib import Path
import argparse
import sys
import numpy as np

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
from experiments.cpd_anti_additive.corrected_core_stage1 import read, save, pin, checked, now
from experiments.cpd_anti_additive.endpoint_scan_geometry import constraint_metrics, torsion, wrapped


def review(root):
    out = root / 'conformational_progress_review.json'
    if out.exists():
        raise FileExistsError(out)
    audit = read(root / 'completion_audit.json')
    plan = read(checked(audit['plan']))
    design = read(checked(plan['scan_design']))
    model = read(checked(plan['model']))
    reference = read(checked(design['reference_result']))
    ref_x = np.load(checked(reference['geometry']))
    keys = model['atom_keys']
    ring = ["1:O4'", "1:C1'", "1:C2'", "1:C3'", "1:C4'"]
    torsions = {'sugar_ring_' + str(i): [ring[(i+j) % 5] for j in range(4)] for i in range(5)}
    torsions.update(cap_5OH=["1:HO5'", "1:O5'", "1:C5'", "1:C4'"],
                    cap_3OH=["1:HO3'", "1:O3'", "1:C3'", "1:C2'"],
                    sugar_exocyclic=["1:O5'", "1:C5'", "1:C4'", "1:C3'"],
                    cyclobutane=['1:C5', '1:C6', '2:C5', '2:C6'])
    reference_angles = {name: torsion(ref_x, [keys.index(k) for k in atoms]) for name, atoms in torsions.items()}
    rows = []
    for record in audit['records']:
        result = read(checked(record['source']))
        x = np.load(checked(result['geometry']))
        projected, _ = constraint_metrics(x, np.asarray(result['gradient_hartree_bohr']), plan['constraint'])
        angles = {name: torsion(x, [keys.index(k) for k in atoms]) for name, atoms in torsions.items()}
        rows.append(dict(result=record['source'], projected=projected,
                         energy_hartree=result['energy_hartree'],
                         energy_relative_to_stationary_reference_kcal_mol=627.509474*(result['energy_hartree']-reference['energy_hartree']),
                         torsion_degrees=angles,
                         torsion_change_from_reference_degrees={name: wrapped(value-reference_angles[name]) for name, value in angles.items()}))
    assert audit['passed'] and rows[-1]['result'] == audit['last_accepted_result']
    # Descriptive evidence only: a cap/sugar rearrangement is not a photoproduct identity change.
    data = dict(at=now(), source=pin(Path(__file__)), completion_audit=pin(root / 'completion_audit.json'),
                reference=design['reference_result'], torsion_definitions=torsions, reference_torsion_degrees=reference_angles,
                rows=rows, last_accepted_result=audit['last_accepted_result'],
                maximum_torsion_error_degrees=max(v['projected']['torsion_error_degrees'] for v in rows),
                interpretation='Energy continues falling while the 5-prime hydroxyl and sugar torsions rearrange. This is ongoing conformational relaxation, not convergence or evidence of numerical failure. A distinct basin is not yet certified.',
                branch_status='Suspected conformational branch departure; 5-prime OH cap rotation is substantial. Retain all data and the original stationary reference.',
                fit_scope='Do not accept this unfinished point as a single glycosidic torsion target relative to the original zero. Coupled sugar/cap relaxation contributes to energy; matched-basin zero-offset control and branch review are required before fitting.',
                proceed_with_one_constrained_continuation=True,
                necessity='Identify the relaxed destination at the same prescribed angle before deciding on a matched unconstrained reference or additional training points.',
                alternatives='A full endpoint Hessian would characterize the original stationary reference, but cannot replace examination of this observed relaxation. Keep method/threads unchanged; measured gradient cost is stable. Reuse the accepted full-precision gradient and audit one more bounded chunk.',
                next_review='If continued relaxation converges, review branch and decide on a matched zero-offset release; do not overwrite original reference or silently use lowest energy. If progress stalls or identity fails, diagnose before more compute.',
                minimum_certified=False, simulation_ready=False)
    save(out, data)
    print({k: data[k] for k in ('maximum_torsion_error_degrees', 'branch_status', 'proceed_with_one_constrained_continuation')})
    print(rows[-1])


if __name__ == '__main__':
    p = argparse.ArgumentParser(); p.add_argument('root', type=Path)
    review(p.parse_args().root.resolve())
