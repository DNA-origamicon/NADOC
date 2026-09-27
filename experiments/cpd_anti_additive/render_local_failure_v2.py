"""Retain an inspectable shared-frame account of the stopped construction."""

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
from experiments.cpd_anti_additive.validation_gate import read, source, checked
from experiments.cpd_anti_additive.prepare_engine_v2 import save

ART = REPO / '.development-artifacts'


def main():
    root = ART / 'cpd-anti-local-placement-v2'
    report = read(root / 'assessment.json')
    reviewed = read(root / 'independent_review.json')
    assert reviewed['assessment'] == source(root / 'assessment.json')
    x = np.loadtxt(ART / 'cpd-anti-placement-review-v2/current_A.txt')
    y = np.loadtxt(checked(report['coordinates']))
    failed = np.loadtxt(root / 'failed_stereo_A.txt')
    diagnosis = read(root / 'source_geometry_diagnosis.json')
    psf = app.CharmmPsfFile(str(ART / 'cpd-anti-dna-topology-v2b/anti.psf'))
    elements = [a.element.symbol for a in psf.topology.atoms()]
    labels = [f'{a.system}:{a.residue.idx}:{a.name}' for a in psf.atom_list]
    ids = {(a.system, a.residue.idx, a.name): a.idx for a in psf.atom_list}
    mobile = read(root / 'plan.json')['mobile_indices']
    anti = [tuple(sorted((ids['D001', 15, 'C5'], ids['D000', 8, 'C6']))),
            tuple(sorted((ids['D001', 15, 'C6'], ids['D000', 8, 'C5'])))]
    syn = [tuple(sorted((ids['D001', 15, n], ids['D000', 8, n]))) for n in ('C5', 'C6')]
    bonds = sorted({tuple(sorted((b.atom1.idx, b.atom2.idx))) for b in psf.bond_list})
    current_bonds = sorted(set(bonds)-set(anti)|set(syn))
    center_atom = ids['D000', 7, "C3'"]
    defect = [d['index'] for d in diagnosis['inverting_center']]
    center = (x[center_atom]+y[center_atom])/2
    near = [i for i in range(len(x)) if min(np.linalg.norm(x[i]-center), np.linalg.norm(y[i]-center)) < 12]
    bad_bonds = [r['indices'] for r in diagnosis['original_parent_covalent_violations']]
    fig, axes = plt.subplots(2, 3, figsize=(16, 10), subplot_kw={'projection': '3d'}, layout='constrained')
    for col, (coords, graph, title) in enumerate(zip((x, y, failed), (current_bonds, bonds, bonds),
        ('Frozen source', 'Last valid iterate — NOT STATIONARY', 'Step 24 — REJECTED inversion'))):
        for row, radius in enumerate((11, 2.5)):
            ax = axes[row, col]
            selected = set(near) if row == 0 else set(defect)
            for a, b in graph:
                if a not in selected or b not in selected:
                    continue
                if row == 0 and (elements[a] == 'H' or elements[b] == 'H'):
                    continue
                ax.plot(*coords[[a, b]].T, color='#18779c' if a in mobile or b in mobile else '#a7aeb2', lw=2)
            if row == 0:
                for a, b in bad_bonds:
                    if a in selected and b in selected:
                        ax.plot(*coords[[a, b]].T, color='#c13947', lw=3)
                        ax.text(*coords[[a, b]].mean(axis=0), f'{np.linalg.norm(coords[a]-coords[b]):.2f} Å', fontsize=9)
            else:
                for i in defect:
                    ax.scatter(*coords[i], color='#ba3b57' if i == center_atom else '#177ea5', s=36)
                    ax.text(*coords[i], labels[i].split(':')[-1], fontsize=11)
                a, b, c, d = coords[defect[1:]]
                volume = np.dot(b-a, np.cross(c-a, d-a))
                title = f"D000:7 C3′ neighbor volume: {volume:+.4f} Å³"
            ax.set(xlim=(center[0]-radius, center[0]+radius), ylim=(center[1]-radius, center[1]+radius),
                   zlim=(center[2]-radius, center[2]+radius), title=title)
            ax.set_box_aspect([1, 1, 1]); ax.view_init(elev=25, azim=-60)
            ax.set_xlabel('Å'); ax.set_ylabel('Å'); ax.set_zlabel('Å')
    fig.suptitle('Local construction stopped at neighboring sugar inversion; all anti lesion centers retained', fontsize=15)
    fig.savefig(root / 'failure_comparison.png', dpi=160)
    plt.close(fig)
    # Reuse the reviewed standalone camera/atom renderer, with explicit failure
    # copy and a separate metric table. The historical viewer is not modified.
    payload = dict(current=x.tolist(), candidate=y.tolist(), bondsCurrent=current_bonds, bondsCandidate=bonds,
        moved=mobile, labels=labels, elements=elements, center=center.tolist(), near=near,
        glycosidic=[[ids[s, r, "C1'"], ids[s, r, 'N1']] for s, r in [('D001', 15), ('D000', 8)]],
        clashes=bad_bonds, report=report)
    template_path = Path(__file__).with_name('placement_review_viewer.html')
    html = template_path.read_text()
    html = html.replace('Cis-anti placement diagnostic — rigid placement rejected',
                        'Local anti construction — stopped at sugar inversion')
    old = html[html.index('<p>The source sugars'):html.index('</p>')+4]
    html = html.replace(old, '<p>The last valid iterate is shown in blue. Step 24 was rejected after '
        'D000:7 C3′ inverted; all four anti lesion centers remained correct. The last valid iterate '
        'has maximum mobile force 88.34 kcal/mol/Å and is not a minimum or dynamics seed. '
        'Magenta marks bonds already overstretched in the source; four outside the mobile region remain '
        'overstretched. Orange marks glycosidic bonds; gray dashed lines show displacement. '
        'No geometry has been applied to the saved design. All views share the same frame and camera.</p>')
    html = html.replace('Rigid anti candidate — rejected', 'Last valid iterate — NOT STATIONARY')
    html = html.replace('href="current_A.txt"', 'href="../cpd-anti-placement-review-v2/current_A.txt"')
    html = html.replace('rejected_candidate_A.txt', 'candidate_A.txt').replace('rejected candidate</a>', 'last valid iterate</a>')
    html = html.replace('comparison.png', 'failure_comparison.png')
    html = html.replace('<h2>Measured geometry</h2>', '<p><a href="failure_comparison.png">Source / last valid / rejected step with sugar close-ups</a> · '
        '<a href="source_geometry_diagnosis.json">Inherited bond defects</a> · '
        '<a href="independent_review.json">Independent geometry and force review</a></p><h2>Measured geometry</h2>')
    start = html.index("let r=D.report;")
    end = html.index('redraw();</script>', start)
    rows = [['Metric', 'Source', 'Last valid iterate'],
            ['Maximum mobile force (kcal/mol/Å)', '—', f"{reviewed['max_mobile_reference_force_kcal_A']:.3f}"],
            ['Inherited parent bonds outside length screen', '7', '4 (all fixed)'],
            ['Maximum base displacement (Å)', '—', f"{report['max_base_displacement_A']:.3f} (limit 3.5)"],
            ['Original sugar centers retained', '288', '288'],
            ['Anti lesion centers retained', 'not anti', '4'],
            ['Severe mobile contacts / all detected piercings', '—', '0 / 0'],
            ['Minimum certified / full-DNA NAMD tested', 'no / no', 'no / no']]
    rows += [[f"Endpoint {g['endpoint']} glycosidic bond (Å)", f"{g['current_A']:.3f}", f"{g['candidate_A']:.3f}"]
             for g in report['glycosidic']]
    table = ''.join('<tr>'+''.join('<td>'+str(v)+'</td>' for v in row)+'</tr>' for row in rows)
    html = html[:start] + f"document.getElementById('metrics').innerHTML={json.dumps(table)};" + html[end:]
    (root / 'review.html').write_text(html.replace('__DATA__', json.dumps(payload)))
    save(root / 'failure_viewer_manifest.json', dict(renderer=source(Path(__file__)), template=source(template_path),
        sources=[source(root / p) for p in ('assessment.json', 'independent_review.json', 'source_geometry_diagnosis.json',
                                           'candidate_A.txt', 'failed_stereo_A.txt')],
        outputs=[source(root / p) for p in ('review.html', 'failure_comparison.png')], saved_design_changed=False))
    print('Wrote shared-frame failure viewer and stereocenter comparison.')


if __name__ == '__main__':
    main()
