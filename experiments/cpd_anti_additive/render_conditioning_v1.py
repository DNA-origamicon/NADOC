"""Show repaired bonds and retained force failure in the frozen design frame."""

import json
from pathlib import Path
import sys

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
from openmm import app

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
from experiments.cpd_anti_additive.validation_gate import read, checked, source
from experiments.cpd_anti_additive.prepare_engine_v2 import save


def main():
    art = REPO / '.development-artifacts'; root = art / 'cpd-anti-source-conditioning-v1b'
    result = read(root / 'assessment.json'); review = read(root / 'independent_review.json')
    assert checked(review['assessment']) == (root / 'assessment.json').resolve()
    x = np.loadtxt(art / 'cpd-anti-placement-review-v2/current_A.txt')
    y = np.loadtxt(checked(result['coordinates']))
    psf = app.CharmmPsfFile(str(art / 'cpd-anti-dna-topology-v2b/anti.psf'))
    ids = {(a.system, a.residue.idx, a.name): a.idx for a in psf.atom_list}
    labels = [f'{a.system}:{a.residue.idx}:{a.name}' for a in psf.atom_list]
    elements = [a.element.symbol for a in psf.topology.atoms()]
    bonds = sorted({tuple(sorted((b.atom1.idx, b.atom2.idx))) for b in psf.bond_list})
    anti = [tuple(sorted((ids['D001', 15, a], ids['D000', 8, b]))) for a, b in [('C5', 'C6'), ('C6', 'C5')]]
    syn = [tuple(sorted((ids['D001', 15, a], ids['D000', 8, a]))) for a in ('C5', 'C6')]
    old_bonds = sorted(set(bonds)-set(anti)|set(syn))
    bad = read(art / 'cpd-anti-local-placement-v2/source_geometry_diagnosis.json')['original_parent_covalent_violations']
    mobile = read(root / 'plan.json')['mobile_indices']; moving = set(mobile)
    centers = [x[[ids['D001', 15, "C1'"], ids['D000', 8, "C1'"]]].mean(axis=0),
               x[[ids['D002', 26, "O3'"], ids['D002', 27, 'P']]].mean(axis=0)]
    fig, axes = plt.subplots(2, 3, figsize=(17, 10), subplot_kw={'projection': '3d'}, layout='constrained')
    for row, (center, radius) in enumerate(zip(centers, [11., 7.])):
        selected = {i for i, e in enumerate(elements) if e != 'H' and min(np.linalg.norm(x[i]-center), np.linalg.norm(y[i]-center)) < radius}
        for col, sets in enumerate([[(x, old_bonds, '#a75e32')], [(y, bonds, '#087da1')], [(x, old_bonds, '#a75e32'), (y, bonds, '#087da1')]]):
            ax = axes[row, col]
            for pos, graph, color in sets:
                for a, b in graph:
                    if a in selected and b in selected:
                        ax.plot(*pos[[a, b]].T, color=color if a in moving or b in moving else '#b4b9bd', lw=1.5)
                for defect in bad:
                    a, b = defect['indices']
                    if a in selected and b in selected:
                        ax.plot(*pos[[a, b]].T, color='#bb3476', lw=3)
            if col == 2:
                for i in selected & moving:
                    ax.plot(*np.array([x[i], y[i]]).T, color='#666666', lw=.5, ls='--')
            ax.set(xlim=(center[0]-radius, center[0]+radius), ylim=(center[1]-radius, center[1]+radius),
                zlim=(center[2]-radius, center[2]+radius),
                title=['Frozen source', 'Conditioned — NOT STATIONARY', 'Shared-frame displacement'][col])
            ax.set_box_aspect([1, 1, 1]); ax.view_init(elev=25, azim=-60)
            ax.set_xlabel('Å'); ax.set_ylabel('Å'); ax.set_zlabel('Å')
    fig.suptitle('Seven inherited bond defects repaired; preparation limit reached, maximum force 19.76 kcal/mol/Å\nTop: lesion region. Bottom: remote D002:26–27. Magenta: originally defective bonds.', fontsize=14)
    fig.savefig(root / 'comparison.png', dpi=160); plt.close(fig)
    center = centers[0]
    near = [i for i in range(len(x)) if min(np.linalg.norm(x[i]-center), np.linalg.norm(y[i]-center)) < 12]
    glycosidic = [[ids[s, r, "C1'"], ids[s, r, 'N1']] for s, r in [('D001', 15), ('D000', 8)]]
    payload = dict(current=x.tolist(), candidate=y.tolist(), bondsCurrent=old_bonds, bondsCandidate=bonds,
        moved=mobile, labels=labels, elements=elements, center=center.tolist(), near=near,
        glycosidic=glycosidic, clashes=[r['indices'] for r in bad], report=result)
    template_path = Path(__file__).with_name('placement_review_viewer.html'); html = template_path.read_text()
    html = html.replace('Cis-anti placement diagnostic — rigid placement rejected', 'Source conditioning — iteration limit, not a minimum')
    old = html[html.index('<p>The source sugars'):html.index('</p>')+4]
    html = html.replace(old, '<p>All seven inherited bond-length defects and the two remote severe contacts are resolved under the declared screens. '
        'Sugar and lesion stereochemistry are retained and no ring piercing is detected. Preparation stopped at 500 iterations; the unconstrained phase did not run. '
        'Maximum mobile force is 19.76 kcal/mol/Å. This is a failed construction diagnostic, not a minimum or qualified dynamics seed. '
        'Magenta highlights originally defective bonds in both states; gray dashes show displacements. The saved design is unchanged.</p>')
    html = html.replace('Rigid anti candidate — rejected', 'Conditioned — NOT STATIONARY')
    html = html.replace('href="current_A.txt"', 'href="../cpd-anti-placement-review-v2/current_A.txt"').replace('rejected_candidate_A.txt', 'candidate_A.txt').replace('rejected candidate</a>', 'conditioned candidate</a>')
    html = html.replace('if(coords===D.candidate)for(let [i,j] of D.clashes)', 'for(let [i,j] of D.clashes)')
    html = html.replace('<h2>Measured geometry</h2>', '<p><a href="comparison.png">Lesion and remote-backbone comparisons</a> · '
        '<a href="independent_review.json">Independent force and geometry audit</a></p><h2>Measured geometry</h2>')
    rows = [['Metric / bond', 'Source', 'Conditioned candidate'],
        ['Maximum mobile force (kcal/mol/Å)', '—', f"{review['max_mobile_reference_force_kcal_A']:.3f}"],
        ['Inherited bond defects', '7', '0'], ['Remote severe contacts', '2', '0'],
        ['Maximum base displacement (Å)', '—', f"{result['max_base_displacement_A']:.3f} (product screen: 3.5)"],
        ['Preparation / unconstrained iterations', '—', '500 / 0'], ['Minimum certified / full-DNA NAMD tested', 'no / no', 'no / no']]
    for defect in bad:
        a, b = defect['indices']
        rows.append([labels[a]+' — '+labels[b]+' (Å)', f'{np.linalg.norm(x[a]-x[b]):.3f}', f'{np.linalg.norm(y[a]-y[b]):.3f}'])
    for ep, (a, b) in enumerate(glycosidic, 1):
        rows.append([f'Endpoint {ep} glycosidic bond (Å)', f'{np.linalg.norm(x[a]-x[b]):.3f}', f'{np.linalg.norm(y[a]-y[b]):.3f}'])
    table = ''.join('<tr>'+''.join('<td>'+str(v)+'</td>' for v in row)+'</tr>' for row in rows)
    start = html.index('let r=D.report;'); end = html.index('redraw();</script>', start)
    html = html[:start]+f"document.getElementById('metrics').innerHTML={json.dumps(table)};"+html[end:]
    (root / 'review.html').write_text(html.replace('__DATA__', json.dumps(payload)))
    save(root / 'viewer_manifest.json', dict(renderer=source(Path(__file__)), template=source(template_path),
        assessment=source(root / 'assessment.json'), independent_review=source(root / 'independent_review.json'),
        outputs=[source(root / p) for p in ('review.html', 'comparison.png')], saved_design_changed=False))
    print('Rendered source and conditioned lesion/backbone comparison with exact bond deltas.')


if __name__ == '__main__':
    main()
