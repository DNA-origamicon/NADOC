import json,collections,requests,concurrent.futures
from pathlib import Path
O=Path('experiments/origami_publication_catalog/assets/sources/pre2020-expansion');d=json.loads((O/'screening.json').read_text());known={r['doi'].lower()for r in d};c=collections.Counter(x['doi'].lower()for r in d for x in r.get('references',[])if x['doi'] and x['doi'].lower()not in known)
def run(doi):
 try:r=requests.get('https://api.crossref.org/works/'+doi,timeout=25);r.raise_for_status();return {'doi':doi,'cited_by_corpus_papers':c[doi],'metadata':r.json()['message']}
 except Exception as e:return {'doi':doi,'cited_by_corpus_papers':c[doi],'error':str(e)}
with concurrent.futures.ThreadPoolExecutor(max_workers=4)as ex:r=list(ex.map(run,c))
(O/'citation_chase.json').write_text(json.dumps(r,indent=2));edges=[{'citing_doi':r['doi'],'cited_doi':x['doi'].lower(),'citation':x['citation']}for r in d for x in r.get('references',[])if x['doi']];(O/'citation_edges.json').write_text(json.dumps(edges,indent=2));print('resolved',sum('metadata'in x for x in r),'of',len(r))
