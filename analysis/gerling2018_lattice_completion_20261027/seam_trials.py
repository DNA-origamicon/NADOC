"""Test local figure-supported scaffold seams; preserve all candidate evidence."""
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent


def main():
    base = json.loads((OUT/'trials/loopout_context/annotations.json').read_text())
    approved = {r['published_id']: r['proposed'] for r in json.loads(
        (ROOT/'analysis/gerling2018_T_annotations_20261027/annotations.json').read_text())
        if r['key'] == '42hb13'}
    scaffold = (ROOT/'backend/core/p7560.txt').read_text().strip()
    comp = scaffold.translate(str.maketrans('ACGT', 'TGCA'))
    refs = json.loads((ROOT/'backend/data/gerling2018_42hb13.json').read_text())['sequences']
    seeds = json.loads((OUT/'seam_seeds.json').read_text())
    trials = [('142_annotation', [142], False), ('142_seed', [142], True),
              ('46_142_annotations', [46,142], False), ('46_142_seeds', [46,142], True)]
    report = []
    old = json.loads((OUT/'trials/loopout_context/solver/contactmap.json').read_text())[0]
    for label, changes, seed_enabled in trials:
        dest = OUT/'trials'/label
        dest.mkdir(parents=True, exist_ok=True)
        annotations = list(base)
        for pid in changes:
            annotations[pid-1] = approved[pid]
        for a, r in zip(annotations, refs):
            assert a['annotated_sequence'].replace('*', '') == r['sequence']
        (dest/'annotations.json').write_text(json.dumps(annotations, indent=2)+'\n')
        (dest/'input.rev').write_text('# Figure-supported seam annotation test\nCIRCULAR\n'+scaffold+'\n'+
                                    '\n'.join(a['annotated_sequence'] for a in annotations)+'\n')
        (dest/'seeds.json').write_text(json.dumps([s for s in seeds if s['published_id'] in changes], indent=2)+'\n')
        command = [str(ROOT/'.venv/bin/python'), str(OUT/'runner/run.py'), str(dest/'input.rev'),
                   '--output', str(dest/'solver'), '--workers', '4', '--mu-min', '5', '--sigma', '4',
                   '--beta', '.2', '--ordered-pruning', '--loopout-graph', '--context-weight', '1']
        if seed_enabled:
            command += ['--route-seeds', str(dest/'seeds.json')]
        if not (dest/'solver/summary.json').exists():
            with (dest/'solver.log').open('w') as log:
                p = subprocess.run(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)
            assert p.returncode in (0,2), (label, p.returncode)
        summary = json.loads((dest/'solver/summary.json').read_text())
        st, sc, circular = json.loads((dest/'solver/contactmap.json').read_text())
        occupied = set()
        assert circular and len(sc) == 7560
        for sid, m in st.items():
            i = int(sid)
            assert m['sequence53'] == refs[i]['sequence']
            unpaired = {p for s in annotations[i]['segments'] if s['kind'] == 'unpaired_T_candidate'
                        for p in range(s['start_1based']-1, s['end_1based'])}
            assert unpaired == {p for p,b in enumerate(m['base_i53']) if b<0}
            for k,p in enumerate(m['base_i53']):
                if p<0:
                    continue
                assert m['sequence53'][k] == comp[p] and p not in occupied
                assert sc[str(p)]['staple_id'] == i and sc[str(p)]['staple_base_id'] == k
                occupied.add(p)
        result = {'label':label, 'path':str(dest.relative_to(ROOT)), 'placed':len(st),
                  'covered':len(occupied), 'seconds':summary['solver_seconds'],
                  'added_vs_context':[int(s)+1 for s in st if s not in old],
                  'lost_vs_context':[int(s)+1 for s in old if s not in st],
                  'rerouted_vs_context':[int(s)+1 for s in st if s in old and st[s]['base_i53']!=old[s]['base_i53']],
                  'seeds':summary['route_seeds']}
        report.append(result)
        (OUT/'seam_trial_results.json').write_text(json.dumps(report, indent=2)+'\n')
        print(label, result['placed'], result['covered'], 'added',result['added_vs_context'],
              'lost', result['lost_vs_context'], 'rerouted',result['rerouted_vs_context'],flush=True)


if __name__ == '__main__':
    main()
