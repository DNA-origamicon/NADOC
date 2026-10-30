"""Audit and render the connectivity-assisted 42hb13 provisional reconstruction."""
import ast
import csv
import hashlib
import json
import math
import shutil
from collections import Counter
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.colors import ListedColormap, BoundaryNorm
from matplotlib.patches import Patch, Rectangle, PathPatch
from matplotlib.path import Path as MPath
import numpy as np

R = Path(__file__).resolve().parents[2]
O = Path(__file__).resolve().parent
N = 7560
OLD = R/'analysis/gerling2018_revnano_variations_20261027'
TRIAL = O/'trials/142_seed'
SOURCE = R/'workspace/Gerling2018_FigS1_42hb_CONTROL_traced_staples_v4.nadoc'
ARCHIVE = Path('/media/jojo/Archive/NADOC_archive/design_reconstruction/gerling2018')


def read(path):
    return json.loads(path.read_text())


def save_csv(name, rows):
    with (O/name).open('w',newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


def binding_segments(m):
    result, offset = [], 0
    for length in m['section_lengths']:
        positions = m['base_i53'][offset:offset+length]
        if positions[0]>=0:
            assert positions == [(positions[0]-k)%N for k in range(length)]
            result.append({'scaffold_indices':positions, 'staple_offset':offset})
        offset += length
    return result


def main():
    global metrics
    original_hash = hashlib.sha256(SOURCE.read_bytes()).hexdigest()
    design = read(SOURCE)
    labels = [str(h['label'] if h['label'] is not None else i) for i,h in enumerate(design['helices'])]
    indices = {h['id']:i for i,h in enumerate(design['helices'])}
    scaffold = next(s for s in design['strands'] if s['strand_type']=='scaffold')
    walk = []
    for d in scaffold['domains']:
        a,b = d['start_bp'],d['end_bp']
        step = 1 if a<=b else -1
        walk += [(indices[d['helix_id']],p) for p in range(a,b+step,step)]
    assert len(walk)==len(set(walk))==5292
    projection = {(i+17)%N:location for i,location in enumerate(walk)}
    neighbors = set()
    for i,a in enumerate(design['helices']):
        for j,b in enumerate(design['helices'][:i]):
            distance = math.hypot(a['axis_start']['x']-b['axis_start']['x'],a['axis_start']['y']-b['axis_start']['y'])
            if abs(distance-2.25)<.01:
                neighbors.add(tuple(sorted((i,j))))
    assert (1,10) in neighbors
    refs = read(R/'backend/data/gerling2018_42hb13.json')['sequences']
    assert [r['index'] for r in refs] == list(range(1,214))
    sequence = (R/'backend/core/p7560.txt').read_text().strip()
    complement = sequence.translate(str.maketrans('ACGT','TGCA'))
    old = read(OLD/'42hb13_best_contactmap.json')
    new = read(TRIAL/'solver/contactmap.json')
    context = read(O/'trials/loopout_context/solver/contactmap.json')
    annotations = read(TRIAL/'annotations.json')
    diag = read(TRIAL/'solver/fragment_diagnostics.json')
    solver = read(TRIAL/'solver/summary.json')
    serial = read(O/'validation/serial/summary.json')
    assert new == read(O/'validation/serial/contactmap.json')
    assert solver['tree_digests'] == serial['tree_digests']
    assert solver['stage_results'] == serial['stage_results']
    assert old == read(O/'trials/parity/solver/contactmap.json')
    assert context == read(O/'trials/loopout_context_lattice/solver/contactmap.json')
    st, sc, circular = new
    assert circular and len(sc)==N
    occupied = set()
    for p,letter in enumerate(sequence):
        assert sc[str(p)]['base_letter']==letter
    for sid,m in st.items():
        i = int(sid)
        assert m['sequence53']==refs[i]['sequence']
        expected = {p for s in annotations[i]['segments'] if s['kind']=='unpaired_T_candidate'
                    for p in range(s['start_1based']-1,s['end_1based'])}
        assert expected == {p for p,b in enumerate(m['base_i53']) if b<0}
        for k,p in enumerate(m['base_i53']):
            if p<0:
                continue
            assert p not in occupied and m['sequence53'][k]==complement[p]
            assert sc[str(p)]['staple_id']==i and sc[str(p)]['staple_base_id']==k
            occupied.add(p)
    new_ids = sorted(int(s)+1 for s in st if s not in old[0])
    rerouted = sorted(int(s)+1 for s in st if s in old[0] and st[s]['base_i53']!=old[0][s]['base_i53'])
    assert set(old[0])<=set(st)
    controls = {str(pid):[p for p in st[str(pid-1)]['base_i53'] if p>=0]==list(range(first,first-19,-1))
                for pid,first in [(163,3119),(171,3175),(174,398),(178,76)]}
    assert all(controls.values())
    rows, projected, fragment_occupancy = [], [], {}
    for i,ref in enumerate(refs):
        blocks = [s for s in annotations[i]['segments'] if s['kind']=='paired_candidate']
        ids = [i]+diag['extra_staples'].get(str(i),[])
        assert len(blocks)==len(ids)
        for bi,(vid,block) in enumerate(zip(ids,blocks)):
            route = diag['staples_placed'].get(str(vid),[])
            positions = [(first-k)%N for first,length in route for k in range(length)]
            if route:
                assert ''.join(complement[p] for p in positions)==block['sequence']
            status = ('newly_placed' if i+1 in new_ids else 'rerouted' if i+1 in rerouted else 'retained') if str(i) in st else 'unresolved_fragment'
            reasons = [label for label,field in [('no_tree','staple_ids_with_no_tree'),('collapsed','staple_ids_with_zero_route'),
                       ('ambiguous','staple_ids_with_persistent_ambiguous_route'),('overlap','staple_ids_with_overlap_problems')]
                       if vid in (diag.get(field) or [])]
            rows.append({'published_id':i+1,'block_1based':bi+1,'start_1based':block['start_1based'],
                         'end_1based':block['end_1based'],'sequence':block['sequence'],'paired_nt':block['length'],
                         'whole_staple_placed':str(i) in st,'status':status,'reason':';'.join(reasons),
                         'scaffold_route_0based':json.dumps(route)})
            for k,p in enumerate(positions):
                assert p not in fragment_occupancy
                fragment_occupancy[p] = {'published_id':i+1,'status':status}
                if p in projection:
                    h,bp = projection[p]
                    projected.append({'published_id':i+1,'staple_base_1based':block['start_1based']+k,
                                      'scaffold_index_0based':p,'helix_label':labels[h],'bp':bp,'status':status,
                                      'coordinate_basis':'unverified native 5292-base route at offset17'})
    assert len(fragment_occupancy)==solver['stage_results']['stage3_result'][0]
    save_csv('fragment_diagnosis.csv',rows)
    save_csv('projected_bases.csv',projected)
    staple_rows = []
    for i,ref in enumerate(refs):
        m = st.get(str(i))
        status = ('newly_placed' if i+1 in new_ids else 'rerouted' if i+1 in rerouted else 'retained') if m else 'unresolved'
        locations = [(projection[p]) for p in m['base_i53'] if p in projection] if m else []
        staple_rows.append({'published_id':i+1,'status':status,
                            'candidate_paired_nt':sum(s['length'] for s in annotations[i]['segments'] if s['kind']=='paired_candidate'),
                            'mapped_nt':sum(p>=0 for p in m['base_i53']) if m else 0,
                            'projected_nt':len(locations),'projected_helix_labels':';'.join(sorted({labels[h] for h,b in locations},key=int)),
                            'original_sequence':ref['sequence'],'annotation':annotations[i]['annotated_sequence'],
                            'scaffold_routes_0based':json.dumps([s['scaffold_indices'] for s in binding_segments(m)]) if m else '[]'})
    save_csv('staple_changes.csv',staple_rows)

    # Check whether the native projection could legitimately be a hard spatial rule.
    lattice_rows = []
    for sid,m in old[0].items():
        segments = binding_segments(m)
        for a,b in zip(segments,segments[1:]):
            p,q = a['scaffold_indices'][-1],b['scaffold_indices'][0]
            if q==(p-1)%N:
                continue
            left,right = projection.get(p),projection.get(q)
            pair = tuple(sorted((left[0],right[0]))) if left and right else None
            lattice_rows.append({'published_id':int(sid)+1,'scaffold_from':p,'scaffold_to':q,
                'from_helix_label':labels[left[0]] if left else '', 'from_bp':left[1] if left else '',
                'to_helix_label':labels[right[0]] if right else '', 'to_bp':right[1] if right else '',
                'both_projected':bool(left and right),'lattice_neighbors':pair in neighbors,
                'bp_difference':abs(left[1]-right[1]) if left and right else ''})
    save_csv('baseline_lattice_audit.csv',lattice_rows)
    summary = {
        'list':'42hb (1)-(3), Fig. S1 / PDF page 3', 'selected_trial':str(TRIAL.relative_to(R)),
        'baseline':{'complete_staples':len(old[0]),'scaffold_bases':6071,'coverage_percent':6071/N*100},
        'automatic_connectivity_result':{'complete_staples':len(context[0]),'scaffold_bases':6432,'coverage_percent':6432/N*100},
        'selected_result':{'complete_staples':len(st),'total_staples':213,'scaffold_bases':len(occupied),
            'coverage_percent':len(occupied)/N*100,'uncovered_scaffold_bases':N-len(occupied),
            'new_staples':new_ids,'rerouted_existing_staples':rerouted,'lost_staples':[],
            'unresolved_staples':[i+1 for i in range(213) if str(i) not in st],
            'candidate_paired_nt':sum(r['candidate_paired_nt'] for r in staple_rows),
            'stage3_fragment_bases':len(fragment_occupancy),'incomplete_staple_fragment_bases':len(fragment_occupancy)-len(occupied)},
        'projection':{'note':'Unverified native5292-base walk with offset17; not a recovered7560-base geometric route',
            'native_routed_bases':5292,'lattice_neighbor_pairs':len(neighbors),'helix_1_neighbors':[labels[j if i==1 else i] for i,j in sorted(neighbors) if 1 in (i,j)],
            'baseline_crossover_edges':len(lattice_rows),'both_endpoints_projected':sum(r['both_projected'] for r in lattice_rows),
            'neighbor_and_bp_difference_at_most_1':sum(r['lattice_neighbors'] and r['bp_difference']<=1 for r in lattice_rows),
            'lattice_prior_changed_contactmap':False},
        'staple142':{'evidence_level':'locally figure-supported candidate, admitted to full-list solver; not independently proven unique',
            'helix_labels_in_order':['41','40','31','30'],'paired_domain_lengths':[7,7,14,7],
            'routes':[[[57,7]],[[102,7]],[[799,12],[6497,2]],[[859,7]]],
            'paired_sequence':'AGAGTCCAAGAATACTTAAGTGTCCTACCTTTCTC',
            'annotation':annotations[141]['annotated_sequence'],
            'reciprocal_support':[{'staple':167,'placed_edge':[800,95],'predicted_partner':[96,799]},
                                  {'staple':104,'placed_edge':[860,6495],'predicted_partner':[6496,859]}],
            'source_figure_path_0based':208,'reverted_to_original_reviewed_annotation':True,
            'seeded_block':'CTTAAGTGTCCTAC; exact12+2 scaffold pieces on one proposed14-base helix domain',
            'rerouted_vs_automatic_connectivity':[7,67]},
        'validation':{'all_original_sequences_preserved':True,'annotation_masks_match':True,'all_assigned_bases_complementary':True,
            'overlap_bases':0,'reciprocal_contactmap_indices_valid':True,'parallel_cached_serial_exact_contactmap_tree_and_stage_parity':True,
            'no_hook_control_exact_baseline_parity':True,'nineteen_base_cap_controls':controls,
            'source_design_sha256':original_hash,'unit_tests':4},
        'limitations':['Heuristic graph distance can select wrong repeat matches; complete does not mean physically validated.',
                       'Local142 route includes a supplied seam candidate; it is not a blind REVNANO recovery.',
                       '46 seam candidate injection was skipped because Stage0 already had48 routes. It remains unresolved.',
                       'Lattice neighbors alone cannot determine a connection, exact register, or staple identity.',
                       '42hb14 was not rerun in this experiment.']}
    assert ''.join(complement[p] for p in st['141']['base_i53'] if p>=0)==summary['staple142']['paired_sequence']
    (O/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    (O/'selected_best.json').write_text(json.dumps({'42hb13':{'path':str(TRIAL.relative_to(R)),**summary['selected_result']}},indent=2)+'\n')
    for src,dst in [('input.rev','42hb13_best.rev'),('annotations.json','42hb13_best_annotations.json'),
                    ('solver/contactmap.json','42hb13_best_contactmap.json'),('solver/contactmap.csv','42hb13_best_contactmap.csv')]:
        shutil.copy2(TRIAL/src,O/dst)

    # Update the user's existing schematic projection, retaining its assumptions.
    lo,hi = min(b for _,b in walk),max(b for _,b in walk)
    colors = ['#dde2e6','#668ba8','#078087','#9163ad','#d76b25']
    old_grid,new_grid = np.zeros((42,hi-lo+1)),np.zeros((42,hi-lo+1))
    old_rows = list(csv.DictReader((OLD/'42hb13_fragment_diagnosis.csv').open()))
    for r in old_rows:
        for first,length in json.loads(r['scaffold_route_0based']):
            for k in range(length):
                p = (first-k)%N
                if p in projection:
                    h,bp = projection[p]
                    old_grid[h,bp-lo] = 1 if r['whole_staple_placed']=='True' else 4
    codes = {'retained':1,'newly_placed':2,'rerouted':3,'unresolved_fragment':4}
    for p,item in fragment_occupancy.items():
        if p in projection:
            h,bp = projection[p]
            new_grid[h,bp-lo] = codes[item['status']]
    fig,axes = plt.subplots(1,2,figsize=(16,10))
    fig.subplots_adjust(left=.045,right=.985,bottom=.18,top=.85,wspace=.11)
    for ax,grid,title in zip(axes,[old_grid,new_grid],['Before: 176 staples · 80.3% coverage','After: 186 staples · 85.5% coverage']):
        ax.imshow(grid,cmap=ListedColormap(colors),norm=BoundaryNorm(np.arange(-.5,5),5),aspect='auto',interpolation='nearest',extent=(lo-.5,hi+.5,41.5,-.5))
        for start in (28,49,70,91):
            ax.add_patch(Rectangle((start-.5,-.5),7,42,fill=False,edgecolor='#9b7509',linewidth=1.3))
        for h in (1,10):
            ax.add_patch(Rectangle((lo-.5,h-.5),hi-lo+1,1,fill=False,edgecolor='#243c51',linewidth=1.1,linestyle=':'))
        ax.set_yticks(range(42),labels=labels,fontsize=8)
        ax.set_xticks(range(0,126,7))
        ax.tick_params(axis='x',rotation=90)
        ax.set(xlabel='Provisional schematic BP coordinate',ylabel='Visible helix label',title=title)
    fig.suptitle('Gerling Fig. S1 — connectivity-assisted provisional map\n10 additional complete staples; exact sequence matches, geometry still unverified',fontsize=16)
    handles = [Patch(color=c,label=t) for c,t in zip(colors,['No mapped fragment','Retained whole staple','Newly placed staple','Revised route of existing staple','Fragment of unresolved staple'])]
    fig.legend(handles=handles,loc='lower center',bbox_to_anchor=(.5,.075),ncol=3,fontsize=10)
    fig.text(.5,.025,'Both panels assume the existing 5,292-base route at p7560 offset 17. Coverage percentages use all 7,560 bases.\nGold outlines: wide drawing intervals. Dotted rows: helices 1 and 10, confirmed lattice neighbors.',ha='center',fontsize=10,color='#536275')
    for ext in ('png','svg'):
        fig.savefig(O/f'provisional_projection_updated.{ext}',dpi=170)
    plt.close(fig)

    # Reuse the established circle renderer with these audited whole-staple maps.
    maps,metrics = {},{}
    for name,contact in [('before',old),('after',new)]:
        maps[name] = [{'id':int(s)+1,'segments':binding_segments(m)} for s,m in contact[0].items()]
        covered = {p for m in contact[0].values() for p in m['base_i53'] if p>=0}
        metrics[name] = {'shown':len(maps[name]),'total':213,'intervals':sum(len(m['segments']) for m in maps[name]),
                         'links':sum(len(m['segments'])-1 for m in maps[name]),'covered':len(covered)}
    source = R/'analysis/gerling2018_circle_graphs_20261027/build_revnano_graphs.py'
    funcs = [n for n in ast.parse(source.read_text()).body if isinstance(n,ast.FunctionDef) and n.name in ('xy','draw','plot')]
    exec(compile(ast.Module(body=funcs,type_ignores=[]),str(source),'exec'),globals())
    plot([(maps['before'],'before','Previous result','176 complete staples · selected annotations','#668ba8'),
          (maps['after'],'after','Connectivity-assisted result','186 complete staples · includes local 142 candidate','#078087')],'circle_graphs_updated')
    (O/'README.txt').write_text(
        'GERLING 2018 FIG. S1 — CONNECTIVITY-ASSISTED PROVISIONAL RECONSTRUCTION\n\n'
        'Result: 176 -> 186 of213 complete staples;6071 ->6467 of7560 scaffold bases\n'
        '(80.3% ->85.5%). All176 prior whole staples retained;396 net additional bases.\n'
        f'New staples: {new_ids}. Revised existing routes: {rerouted}.\n'
        '27 staples and1093 scaffold bases remain unresolved. The7560 sequence is unchanged.\n\n'
        'METHOD AND CONTROLS\n'
        'Helices1 and10 are lattice neighbors. The provisional5292-base helix projection\n'
        f'places only{summary["projection"]["neighbor_and_bp_difference_at_most_1"]}/{summary["projection"]["both_endpoints_projected"]} doubly projected old crossover edges on\n'
        'neighbor helices within1BP. It is unsuitable as a global hard routing constraint.\n'
        'Used453 actual figure crossover sites as a soft preference; this made no difference.\n'
        'Restored edges across annotated loopouts between consecutive placed fragments\n'
        'of the SAME oligo, and scored ambiguous fragments against their placed neighbors.\n'
        'This breaks repeated7mer ties in REVNANO Stage2. Default scores ignore this context.\n'
        'Exact existing candidate routes compete normally; no new base matches or overlaps.\n'
        'Controlled runs: no hook176/6071; loopout edges only173/5950; neighbor context only\n'
        '183/6362; both185/6432; both+projected lattice prior185/6432, identical map.\n'
        'The185 result uses unchanged selected annotations and adds9 whole staples.\n\n'
        'LOCAL STAPLE142\n'
        'The figure path41 ->40 ->31 ->30 supports7+7+14+7 paired domains. Restoring its\n'
        'original reviewed TT annotations alone leaves185/6432. A documented exact\n'
        '12+2 scaffold-seam candidate for its14-base helix31 domain gives186/6467.\n'
        'The2-base piece is inside one proposed physical domain; it is not a2-base\n'
        'physical helix segment. Connections96->799 and6496->859 are reciprocal partners\n'
        'of167(edge800->95) and104(edge860->6495). All35 paired bases match p7560.\n'
        'Candidate admitted after Stage0 only for a fragment with no valid tree; it then\n'
        'passes ordinary Stage1-3 competition. Existing7 and67 reroute; none is lost.\n'
        'This is an externally guided candidate, not an independent blind reconstruction.\n'
        'Uniqueness and physical helix geometry remain unproven.46 still unresolved;\n'
        'its optional seam candidates were skipped because it already had48 Stage0 routes.\n\n'
        'VALIDATION\n'
        'All full published sequences and annotation masks preserved; every assigned base\n'
        'complements p7560; zero overlaps; reciprocal contact-map indices valid.\n'
        'Four19-base cap controls pass. No-hook map exactly matches the old baseline.\n'
        'Selected parallel and cached serial maps, routing tree digests and stage results\n'
        'are identical. Four targeted connectivity/tree regression tests pass.\n'
        'Solver MU_MIN5,SIGMA4,BETA0.2, ordered-pruning enabled.4workers; total address\n'
        'ceilings3072MiB; cached serial1024MiB. All trials retain inputs,logs,summaries\n'
        'and adapter snapshots. Original design, prior maps and42hb14 unchanged.\n\n'
        'ARTIFACTS\n'
        'provisional_projection_updated.png/.svg: before/after helix/BP projection.\n'
        'circle_graphs_updated.png/.svg: before/after complete-staple circle maps.\n'
        'staple_changes.csv: published IDs,status,sequence,annotation,scaffold routes.\n'
        'projected_bases.csv: visible helix labels and explicitly provisional BP positions.\n'
        'fragment_diagnosis.csv: all individual blocks,including unresolved whole staples.\n'
        'summary.json,trial_results.json,seam_trial_results.json: metrics and evidence.\n'
        '42hb13_best_contactmap.json/.csv,42hb13_best.rev,42hb13_best_annotations.json.\n'
        'Reproduce: .venv/bin/python analysis/gerling2018_lattice_completion_20261027/run_trials.py\n'
        'then seam_trials.py, selected cached-serial validation (see serial_validation.log),\n'
        'test_connectivity.py and report.py. Experimental adapter is private to this study.\n'
        'Stage3 maps7086 bases;619 belong to incomplete staples and are NOT counted in6467.\n')
    assert hashlib.sha256(SOURCE.read_bytes()).hexdigest()==original_hash
    print(json.dumps(summary,indent=2))


if __name__=='__main__':
    main()
