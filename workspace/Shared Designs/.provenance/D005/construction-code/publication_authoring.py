"""Compile complete PDF evidence to ordinary editor operations, never an import root."""
import hashlib
from uuid import NAMESPACE_URL, uuid5

import pymupdf
from backend.core.publication_routing import (extract_publication_paths, staple_tables,
    pair_endpoint_table, classify_scaffold, resolve_insertions)
from backend.core.publication_sequence_search import search_declared_scaffold
from backend.core.sequences import SCAFFOLD_LIBRARY, P7704_SEQUENCE


def domains(sites):
    result=[]
    for site in sites:
        if not result or site[0]!=result[-1][-1][0] or abs(site[1]-result[-1][-1][1])!=1:
            result.append([])
        result[-1].append(site)
    if any(len(d)<2 for d in result):
        raise ValueError('Single-base domains need additional polarity evidence')
    return result


def compile_publication(pdf, *, diagram_page, table_page, name, source_path):
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
    if not graph['lattice']['resolved']:
        raise ValueError('Incomplete or ambiguous lattice positions; native construction blocked')
    if classified['unresolved'] or len(classified['scaf'])!=1 or len(classified['stap'])!=len(table['rows']):
        raise ValueError('Incomplete directed routing; native construction blocked')
    if insertions['unresolved'] or not sequence.get('resolved') or sequence['length_discrepancy']:
        raise ValueError('Unresolved insertions or sequence reconciliation; native construction blocked')
    if sequence['best']['reverse']:
        raise ValueError('Reversed scaffold origin needs a native direction mapping')
    lattice=LatticeType.HONEYCOMB
    if graph['lattice']['kind']!='honeycomb':
        raise ValueError('Only recovered honeycomb lattice evidence is supported')
    cells=graph['lattice']['cells']
    scaffold=classified['scaf'][0]['sites']
    paths=[classified['scaf'][0],*classified['stap']]
    # The image fit fixes relative cells; sequence-supported scaffold polarity
    # fixes the parity of their otherwise arbitrary integer translation.
    polarity={}
    for d in domains(scaffold):
        direction='FORWARD' if d[-1][1]>d[0][1] else 'REVERSE'
        if d[0][0] in polarity and polarity[d[0][0]]!=direction:
            raise ValueError('Scaffold polarity is inconsistent on a helix')
        polarity[d[0][0]]=direction
    shifts=[shift for shift in (0,1) if all(
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
        add('helix-add-at-cell',f'Figure helix {h}',{'row':r,'col':c,'length_bp':extent,
            'populate_strands':False,'_helix_id':hid[h]},f'Diagram page {diagram_page}; numbered honeycomb inset')
    for h,bp,n in insertions['counts']:
        add('loop-skip-insert',f'Figure helix {h}[{bp}]: {n} inserted bases',
            {'helix_id':hid[h],'bp_index':bp,'delta':n},'Observed insertion annotation; oligo lengths and scaffold mass balance')
    scaffold_sequence={**{name:seq for name,_,seq in SCAFFOLD_LIBRARY}, 'p7704':P7704_SEQUENCE}[sequence['scaffold_name']]
    offset=sequence['best']['offset']
    scaffold_sequence=scaffold_sequence[offset:]+scaffold_sequence[:offset]
    counters={'crossovers':0,'forced_ligations':0}
    for number,path in enumerate(paths):
        title=sequence['scaffold_name'] if number==0 else f'Staple {number}'
        ds=domains(path['sites'])
        ids=[identity(f'strand:{number}:domain:{i}') for i in range(len(ds))]
        direction=lambda d:'FORWARD' if d[-1][1]>d[0][1] else 'REVERSE'
        for i,d in enumerate(ds):
            add('strand-add',f'Draw {title}, domain {i+1}',{'_strand_id':ids[i],
                'strand_type':'scaffold' if number==0 else 'staple',
                'domains':[{'helix_id':hid[d[0][0]],'start_bp':d[0][1],
                            'end_bp':d[-1][1],'direction':direction(d)}]},
                f'Diagram page {diagram_page}; table endpoints and sequence-supported direction')
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
                     'nick_bp_a':ab,'nick_bp_b':bb-(1 if direction(b)=='FORWARD' else -1)},'Drawn crossover; native lattice site')
                counters['crossovers']+=1
            else:
                add('forced-ligation-create',f'Join {title} domains {i+1}/{i+2}',
                    {'_fl_id':identity(f'join:{number}:{i}'),'three_prime_strand_id':ids[0],
                     'five_prime_strand_id':ids[i+1]},'Drawn nonlocal connection; never substituted for a native crossover')
                counters['forced_ligations']+=1
        add('strand-sequence',f'Assign {title}',{'strand_id':ids[0],'name':title,
            'sequence':scaffold_sequence if number==0 else path['table_row']['sequence']},
            f'Table page {table_page}; exhaustive scaffold alignment')
    recipe={'version':1,'design_id':name,'name':name,'lattice':'HONEYCOMB','unresolved':[],
            'sources':[{'path':source_path,'sha256':hashlib.sha256(pdf).hexdigest(),
                        'diagram_page':diagram_page,'table_page':table_page}], 'operations':operations}
    evidence={'sequence_search':sequence,'lattice_translation_rows':shifts[0],
              'helix_ids':hid,'cells':cells,'insertions':insertions,'classified':classified,
              'connections':counters,'operations':len(operations),
              'native_reference_consulted':False}
    return recipe,evidence
