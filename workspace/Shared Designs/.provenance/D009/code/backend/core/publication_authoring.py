"""Compile complete PDF evidence to ordinary editor operations, never an import root."""
import hashlib
from uuid import NAMESPACE_URL, uuid5

import pymupdf
from backend.core.publication_routing import (extract_publication_paths, staple_tables,
    pair_endpoint_table, classify_scaffold, resolve_insertions)
from backend.core.publication_sequence_search import search_declared_scaffold
from backend.core.sequences import SCAFFOLD_LIBRARY, P7704_SEQUENCE
from backend.core.publication_unpaired_scaffold import aligned_unpaired_scaffold
from backend.core.publication_auxiliary_placement import infer_auxiliary_placement
from backend.core.publication_native_tracks import prepare_native_tracks


def domains(sites):
    result=[]
    for site in sites:
        if not result or site[0]!=result[-1][-1][0] or abs(site[1]-result[-1][-1][1])!=1:
            result.append([])
        result[-1].append(site)
    if any(len(d)<2 for d in result):
        raise ValueError('Single-base domains need additional polarity evidence')
    return result


def compile_publication(pdf, *, diagram_page, table_page, name, source_path,
                        continuous_staples=True, periodic_staple_seams=True, allow_partial=False):
    from backend.core.models import LatticeType
    from backend.core.lattice import _lattice_direction
    from backend.core.crossover_positions import crossover_neighbor
    with pymupdf.open(stream=pdf,filetype='pdf') as doc:
        graph=extract_publication_paths(doc[diagram_page-1])
        table=next(t for t in staple_tables(doc) if t['page']==table_page)
    pairing=pair_endpoint_table(graph,table)
    classified=classify_scaffold(pairing)
    insertions=resolve_insertions(pairing,classified,table)
    sequence=search_declared_scaffold(classified,insertions,table)
    from backend.core.publication_sequence_search import apply_supported_insertions
    source_insertions = insertions
    insertions = apply_supported_insertions(insertions, sequence)
    from backend.core.publication_staple_overhangs import classify_staple_overhangs, apply_overhang_evidence
    overhangs=classify_staple_overhangs(classified,insertions,graph.get('base_labels',[]),
                                     base_index_offset=pairing['base_index_offset'])
    sequence=apply_overhang_evidence(sequence,overhangs)
    from backend.core.publication_missing_staples import recover_unlisted_staples
    classified, derived_staples = recover_unlisted_staples(classified, insertions, sequence)
    route_search = None
    omissions = []
    if allow_partial:
        from backend.core.publication_route_search import search_missing_routes
        route_search = search_missing_routes(classified, insertions, sequence, table, graph['lattice'])
        for item in route_search['rows']:
            if item['status'] == 'unique':
                classified['stap'].append({'path_id': f"table-search-{item['table_row']}",
                    'sites': item['candidates'][0]['sites'], 'table_row': table['rows'][item['table_row']],
                    'basis': 'Unique bounded native crossover/sequence search'})
            else:
                omissions.append({'kind':'missing_staple', **item})
        overhangs=classify_staple_overhangs(classified,insertions,graph.get('base_labels',[]),
                                         base_index_offset=pairing['base_index_offset'])
        if sequence.get('length_discrepancy'):
            omissions.append({'kind':'scaffold_length_discrepancy','unrepresented_sequence_indices':sequence['unrepresented_sequence_indices'],
                              'detail':sequence['length_discrepancy_note']})
    unpaired = aligned_unpaired_scaffold(classified, insertions, table, sequence, graph['lattice'])
    placement = infer_auxiliary_placement(graph['lattice'], classified, unpaired)
    if classified['unresolved'] or len(classified['scaf'])!=1 or len(classified['stap'])!=len(table['rows'])+len(derived_staples):
        if not allow_partial:
            raise ValueError('Incomplete directed routing; native construction blocked')
        omissions.extend({'kind':'unclassified_path','path':p} for p in classified['unresolved'])
    if insertions['unresolved'] or not (sequence.get('alignment_resolved') if allow_partial else sequence.get('resolved')) or (sequence['length_discrepancy'] and not allow_partial):
        raise ValueError('Unresolved insertions or sequence reconciliation; native construction blocked')
    if not overhangs['resolved']:
        raise ValueError('Unresolved overhang sequence or polarity')
    if sequence['best']['reverse']:
        raise ValueError('Reversed scaffold origin needs a native direction mapping')
    if not unpaired['resolved']:
        if not allow_partial:
            raise ValueError('Unexplained unpaired scaffold runs; complete native construction blocked')
        omissions.append({'kind':'unpaired_scaffold_review','detail':unpaired})
    tracks = prepare_native_tracks(classified, graph['lattice'], placement, unpaired)
    annotated = {(h,b) for h,b,_ in insertions['counts']}
    from backend.core.publication_unpaired_scaffold import terminal_scaffold_sites
    terminal_sites = terminal_scaffold_sites(classified, graph['lattice'], unpaired)
    if not allow_partial and any(len(run['sites']) > 1 and not all(tuple(s) in annotated | tracks['auxiliary_sites'] | terminal_sites for s in run['sites'])
           for run in unpaired['runs']):
        raise ValueError('AGENT_PROCESS_REQUIRED: supported unpaired scaffold requires a recorded loop representation; native construction blocked')
    lattice=LatticeType.HONEYCOMB
    if graph['lattice']['kind']!='honeycomb':
        raise ValueError('Only recovered honeycomb lattice evidence is supported')
    cells=tracks['cells']
    scaffold=tracks['classified']['scaf'][0]['sites']
    paths=[tracks['classified']['scaf'][0],*tracks['classified']['stap']]
    # The image fit fixes relative cells; sequence-supported scaffold polarity
    # fixes the parity of their otherwise arbitrary integer translation.
    polarity={}
    for d in domains(scaffold):
        direction='FORWARD' if d[-1][1]>d[0][1] else 'REVERSE'
        if d[0][0] in polarity and polarity[d[0][0]]!=direction:
            raise ValueError('Scaffold polarity is inconsistent on a helix')
        polarity[d[0][0]]=direction
    shifts=[shift for shift in ((0,) if tracks['native_cells'] else (0,1)) if all(
        _lattice_direction(row+shift,col,lattice).value==polarity.get(h)
        for h,(row,col) in cells.items())]
    if len(shifts)!=1:
        raise ValueError('Lattice polarity translation is ambiguous')
    cells={h:(r+shifts[0],c) for h,(r,c) in cells.items()}
    identity=lambda label:str(uuid5(NAMESPACE_URL,f'nadoc:publication:{name}:{label}'))
    hid={h:identity(f'helix:{h}') for h in cells}
    operations=[]
    def add(kind,label,params,evidence):
        operations.append({'kind':kind,'label':label,'params':params,'evidence':[evidence]})
    extent=max(bp for path in paths for _,bp in path['sites'])+1
    for h in sorted(cells):
        r,c=cells[h]
        source = tracks['sources'][h]
        label = f"Figure helix {source['source_helix']}"
        basis = f'Diagram page {diagram_page}; numbered honeycomb inset'
        if 'source_start' in source:
            label += f" segment {source['source_start'][1]} to {source['source_end'][1]}"
            basis = 'Independent drawn loop; unique minimum forced-ligation-span cell at the source register; unrelaxed geometry'
        add('helix-add-at-cell',label,{'row':r,'col':c,'length_bp':extent,
            'populate_strands':False,'_helix_id':hid[h]},basis)
    for h,bp,n in insertions['counts']:
        native_h, native_bp = tracks['site_mapping'].get((h,bp), (h,bp))
        add('loop-skip-insert',f'Figure helix {h}[{bp}]: {n} inserted bases',
            {'helix_id':hid[native_h],'bp_index':native_bp,'delta':n},'Observed insertion annotation; oligo lengths and scaffold mass balance')
    scaffold_sequence={**{name:seq for name,_,seq in SCAFFOLD_LIBRARY}, 'p7704':P7704_SEQUENCE}[sequence['scaffold_name']]
    offset=sequence['best']['offset']
    scaffold_sequence=scaffold_sequence[offset:]+scaffold_sequence[:offset]
    if sequence['length_discrepancy']:
        # The accepted nick-boundary hypothesis is explicit in both the report
        # and the recorded sequence operation; no extra topology is invented.
        if sequence['length_discrepancy'] != 1:
            raise ValueError('Only the supported one-base omission hypothesis can be authored')
        scaffold_sequence=scaffold_sequence[:sequence['represented_length']]
    # Apply selected image/table bases without losing original source evidence.
    from copy import deepcopy
    selected_classified=deepcopy(classified)
    for run in overhangs['runs']:
        row=selected_classified['stap'][run['staple_row']]['table_row']
        bases=list(row['sequence'])
        for base in run['bases']: bases[base['table_offset']]=base['selected_base']
        row['sequence']=''.join(bases)
    selected_paths=selected_classified['stap']

    from backend.core.publication_appearance import staple_colors, figure_order
    colors=staple_colors(classified['stap'])
    row_order=figure_order(graph['calibration']['row_centers'],tracks['sources'])
    counters={'crossovers':0,'forced_ligations':0}
    for number,path in enumerate(paths):
        title=sequence['scaffold_name'] if number==0 else f'Staple {number}'
        path_basis=path.get('basis',f'Diagram page {diagram_page}; table endpoints and sequence-supported direction')
        ds=domains(path['sites'])
        ids=[identity(f'strand:{number}:domain:{i}') for i in range(len(ds))]
        direction=lambda d:'FORWARD' if d[-1][1]>d[0][1] else 'REVERSE'
        for i,d in enumerate(ds):
            add('strand-add',f'Draw {title}, domain {i+1}',{'_strand_id':ids[i],
                'strand_type':'scaffold' if number==0 else 'staple',
                'domains':[{'helix_id':hid[d[0][0]],'start_bp':d[0][1],
                            'end_bp':d[-1][1],'direction':direction(d)}]},
                path_basis)
        for i,(a,b) in enumerate(zip(ds,ds[1:])):
            ah,ab=a[-1];bh,bb=b[0]
            canonical=ah!=bh and ab==bb and any(
                crossover_neighbor(lattice,*cells[x],ab,is_scaffold=sc)==cells[y]
                for x,y in [(ah,bh),(bh,ah)] for sc in [False,True])
            if canonical:
                add('crossover-place',f'Connect {title} domains {i+1}/{i+2}',
                    {'crossover_id':identity(f'join:{number}:{i}'),
                     'half_a':{'helix_id':hid[ah],'index':ab,'strand':direction(a)},
                     'half_b':{'helix_id':hid[bh],'index':bb,'strand':direction(b)},
                     'nick_bp_a':ab,'nick_bp_b':bb-(1 if direction(b)=='FORWARD' else -1)},path_basis+'; native lattice crossover site')
                counters['crossovers']+=1
            else:
                add('forced-ligation-create',f'Join {title} domains {i+1}/{i+2}',
                    {'_fl_id':identity(f'join:{number}:{i}'),'three_prime_strand_id':ids[0],
                     'five_prime_strand_id':ids[i+1]},path_basis+'; nonlocal connection, never substituted for a native crossover')
                counters['forced_ligations']+=1
        add('strand-sequence',f'Assign {title}',{'strand_id':ids[0],'name':title,
            'sequence':scaffold_sequence if number==0 else selected_paths[number-1]['table_row']['sequence']},
            (path['table_row']['basis'] if number and path['table_row'].get('sequence_source') == 'derived_from_aligned_scaffold'
             else f'Table page {table_page}; exhaustive scaffold alignment' + (('; '+sequence['length_discrepancy_note']) if number==0 and sequence['length_discrepancy'] else '')))
        if number and colors[number-1]['color'] is not None:
            operations[-1]['params']['color']=colors[number-1]['color']
            operations[-1]['evidence'].append('Staple appearance: '+colors[number-1]['basis'])
    precursor_summary = None
    if continuous_staples or periodic_staple_seams:
        from backend.core.publication_precursors import staple_precursors
        operations, precursor_summary = staple_precursors(
            operations, paths, hid, identity, periodic_seams=periodic_staple_seams, span_gaps=True)
    if row_order != sorted(cells):
        add('helix-reorder','Match source figure helix row order',{'ordered_ids':[hid[h] for h in row_order]},
            'Top-to-bottom row centers in orientation-normalized figure; preserve current visible helix labels')
    recipe={'version':1,'design_id':name,'name':name,'lattice':'HONEYCOMB','unresolved':[],
            'sources':[{'path':source_path,'sha256':hashlib.sha256(pdf).hexdigest(),
                        'diagram_page':diagram_page,'table_page':table_page}], 'operations':operations}
    evidence={'sequence_search':sequence,'unpaired_scaffold':unpaired,
              'normalization_rotation':graph.get('normalization_rotation',0),'lattice_translation_rows':shifts[0],
              'helix_ids':hid,'helix_sources':tracks['sources'],'auxiliary_placement':placement,
              'cells':cells,'insertions':insertions,'classified':classified,
              'source_insertions':source_insertions,
              'connections':counters,'operations':len(operations), 'staple_precursors': precursor_summary,
              'terminal_unpaired_scaffold_sites': sorted(terminal_sites),
              'derived_staples': derived_staples,
              'staple_overhangs':overhangs,
              'native_reference_consulted':False, 'route_search':route_search,
              'reconstruction_report':{'status':'partial' if omissions else 'complete', 'omissions':omissions,
                  'base_conflicts':overhangs['conflicts'], 'scaffold_sequence_assigned':scaffold_sequence,
                  'appearance':{'helix_order':row_order,'staple_colors':colors},
                  'included_staples':len(classified['stap']), 'table_staples':len(table['rows']),
                  'limitation':'Unrelaxed source reconstruction; omitted or ambiguous routes are not filled with guessed strands.'},
              'assigned_staple_sequences':[p['table_row']['sequence'] for p in selected_paths],
              'appearance':{'staple_colors':colors,'helix_order':row_order}}
    return recipe,evidence
