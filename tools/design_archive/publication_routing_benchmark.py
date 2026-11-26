"""Independent audit of original published images against archived author files.

The extraction module sees only PDF pages and published tables. Reference JSON
is loaded afterwards by this validator. Outputs contain evidence, no designs.
"""
import argparse
import hashlib
import json
from pathlib import Path

import pymupdf

from backend.core.publication_routing import extract_publication_paths, staple_tables, pair_endpoint_table, classify_scaffold, resolve_insertions

CASES = [
    ('monolith','shapes',4,12,'shapes/monolith.json'),
    ('square nut','shapes',5,13,'shapes/squarenut.json'),
    ('railed bridge','shapes',6,14,'shapes/railedbridge.json'),
    ('right-twisted bundle','twist',19,37,'twist/monolith_right_twist.json'),
    ('straight 3x6 bundle','twist',20,39,'twist/protractor_0_v3.json'),
]


def pointers(paths):
    result={}
    for path in paths:
        sites=path['sites']
        for i,site in enumerate(sites):
            if site in result:
                raise ValueError('Two recovered strands occupy the same site.')
            result[site]=tuple(sites[i-1] if i else (-1,-1))+tuple(sites[i+1] if i+1<len(sites) else (-1,-1))
    return result


def compare(paths, reference, kind):
    actual=pointers(paths)
    expected={(h['num'],i):tuple(v) for h in reference['vstrands'] for i,v in enumerate(h[kind]) if v!=[-1]*4}
    shared=actual.keys()&expected.keys()
    return {'reference_sites':len(expected),'recovered_sites':len(actual),
            'missing_sites':len(expected.keys()-actual.keys()),'extra_sites':len(actual.keys()-expected.keys()),
            'wrong_pointers':sum(actual[k]!=expected[k] for k in shared)}


def audit(root):
    reports=[]
    for label,source,page,table_page,native in CASES:
        data=(root/'sources'/f'{source}-supp.pdf').read_bytes()
        report={'design':label,'pdf_sha256':hashlib.sha256(data).hexdigest(),'diagram_page':page,'table_page':table_page,
                'reference_topology_recovered':False}
        try:
            with pymupdf.open(stream=data,filetype='pdf') as doc:
                graph=extract_publication_paths(doc[page-1])
                table=next(t for t in staple_tables(doc) if t['page']==table_page)
                pairing=pair_endpoint_table(graph,table)
                classified=classify_scaffold(pairing)
                insertion_solution=resolve_insertions(pairing,classified,table)
            # This oracle is deliberately outside the extraction call.
            ref_data=(root/'designs'/native).read_bytes()
            reference=json.loads(ref_data)
            report.update(reference_sha256=hashlib.sha256(ref_data).hexdigest(),
                          matched_staples=len(pairing['matched']),table_rows=len(table['rows']),
                          base_index_offset=pairing['base_index_offset'],
                          length_agreements=sum(p['length_agrees'] for p in pairing['matched']),
                          unclassified_paths=len(classified['unresolved']),
                          comparison={kind:compare(classified[kind],reference,kind) for kind in ('scaf','stap')})
            lattice=graph['lattice']
            if lattice['resolved']:
                min_row=min(h['row'] for h in reference['vstrands']);min_col=min(h['col'] for h in reference['vstrands'])
                report['lattice_mismatches']=sum(lattice['cells'].get(h['num'])!=[h['row']-min_row,h['col']-min_col] for h in reference['vstrands'])
            report['lattice']=lattice
            expected_loops={(h['num'],i):n for h in reference['vstrands'] for i,n in enumerate(h['loop']) if n}
            observed_loops={(h,b):n for h,b,n in insertion_solution['counts']}
            report['insertions_exact']=expected_loops==observed_loops and not insertion_solution['unresolved']
            report['insertion_solution']=insertion_solution
            report['reference_indel_bases']=sum(sum(abs(v) for v in h['skip'])+sum(h['loop']) for h in reference['vstrands'])
            report['routing_exact']=all(not c[k] for c in report['comparison'].values() for k in ('missing_sites','extra_sites','wrong_pointers'))
            report['reference_topology_recovered']=(report['routing_exact'] and report.get('lattice_mismatches')==0
                and report['insertions_exact'] and not any(v for h in reference['vstrands'] for v in h['skip']))
            report['status']='topology, insertion lengths and relative lattice compared; molecular geometry not built'
        except ValueError as exc:
            report['status']='unsupported evidence';report['reason']=str(exc)
        reports.append(report)
    return {'method':'original-publication-vector-endpoint-audit-v1','designs':reports,
            'code_sha256':{p:hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in
                           ('backend/core/publication_routing.py','backend/core/publication_diagram_labels.py','tools/design_archive/publication_routing_benchmark.py')}}


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--assets',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();report=audit(args.assets)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report['designs'],indent=2))
