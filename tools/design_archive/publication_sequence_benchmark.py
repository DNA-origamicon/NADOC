"""Reproducible PDF-only sequence audit; no native design oracle is opened."""
import argparse
import hashlib
import json
from pathlib import Path
import time

import pymupdf

from backend.core.publication_routing import extract_publication_paths, staple_tables, pair_endpoint_table, classify_scaffold, resolve_insertions
from backend.core.publication_sequence_search import search_declared_scaffold

CASES=[('D005','right-twisted 10x6 bundle','twist',19,37),
       ('D006','straight 3x6 bundle','twist',20,39),
       ('D007','monolith','shapes',4,12),
       ('D008','square nut','shapes',5,13),
       ('D009','railed bridge','shapes',6,14)]


def run_audit(assets):
    output=[]
    for identifier,name,source,page,table_page in CASES:
        path=assets/'sources'/f'{source}-supp.pdf'
        data=path.read_bytes()
        start=time.monotonic()
        with pymupdf.open(stream=data,filetype='pdf') as doc:
            table=next(t for t in staple_tables(doc) if t['page']==table_page)
            pairing=pair_endpoint_table(extract_publication_paths(doc[page-1]),table)
        classified=classify_scaffold(pairing)
        insertions=resolve_insertions(pairing,classified,table)
        search=search_declared_scaffold(classified,insertions,table)
        output.append({'id':identifier,'name':name,'source_sha256':hashlib.sha256(data).hexdigest(),
                       'diagram_page':page,'table_page':table_page,'table_rows':len(table['rows']),
                       'matched_routes':len(pairing['matched']),'unclassified_paths':len(classified['unresolved']),
                       'unresolved_insertions':insertions['unresolved'],'sequence_search':search,
                       'elapsed_seconds':round(time.monotonic()-start,3)})
    return {'method':'PDF-only bounded scaffold sequence audit','designs':output,
            'code_sha256':{p:hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in
                           ['backend/core/publication_routing.py','backend/core/publication_sequence_search.py',
                            'backend/core/publication_loop_search.py',
                            'tools/design_archive/publication_sequence_benchmark.py']}}


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--assets',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();report=run_audit(args.assets)
    args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(report,indent=2)+'\n')
    for row in report['designs']:
        s=row['sequence_search']
        print(row['id'],s.get('status'),s.get('best',{}),s.get('confidence',{}).get('score'),s.get('reason',''))
