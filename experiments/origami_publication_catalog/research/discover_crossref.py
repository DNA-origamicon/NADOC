"""Uncapped cursor discovery for individual origami/scaffolded search terms.
Live multiword Crossref probes return much broader result sets; these explicit revised
queries retain all hits, without an automated relevance or lattice decision.
"""
import hashlib
import json
from urllib.parse import urlencode
import ledger as L
from acquire_sources import fetch

ROWS=1000
TERMS=['origami','scaffolded']
DOCS='https://www.crossref.org/documentation/retrieve-metadata/rest-api/tips-for-using-the-crossref-rest-api/'


def normalize_doi(value):
    value=value.strip().lower()
    for prefix in ['https://doi.org/','http://doi.org/','doi:']:
        if value.startswith(prefix):value=value[len(prefix):].strip()
    if not value.startswith('10.') or '/' not in value:raise ValueError('Invalid/missing DOI')
    return value


def page_additions(items, existing, run_id, ev):
    known={normalize_doi(r['doi']) for r in existing if r.get('doi')}
    additions=[]
    for item in items:
        doi=normalize_doi(item['DOI'])
        if doi in known:continue
        known.add(doi)
        parts=item.get('published',{}).get('date-parts',[[]])[0]
        date='-'.join(str(n) if i==0 else f'{n:02}' for i,n in enumerate(parts)) or None
        additions.append({'registry_key':doi,'registry_id':'R-'+hashlib.sha256(doi.encode()).hexdigest()[:16],
            'doi':doi,'title':' '.join(item.get('title',[])),'authors':item.get('author',[]),
            'canonical_work_id':'work:'+doi,'canonical_work_status':'provisional_unreconciled','version_links':[],
            'publication_type':[item.get('type','unknown')],
            'date_evidence':{'date':date,'source':ev,'primary_verified':False,'meaning':'Crossref indexed publication date; verify first online date'},
            'review_stage':'unreviewed','relevance':'uncertain','design_contributions':[],
            'catalog_eligibility':'unresolved','access':'not_attempted','evidence':[],
            'discovery_evidence':[ev], 'metadata_record':item,
            'rationale':'Raw bibliographic hit. No title/keyword-based inclusion or exclusion.',
            'reviewer':None,'run_id':run_id,'date':L.DATE,
            'unresolved_questions':['Screen original article; establish DNA-origami relevance, version identity and first online date.'],
            'legacy_record':{'priority':'discovery_only'},'revision_history':[]})
    return additions


def next_state(message):
    items=message['items']
    if len(items)<ROWS:return 'exhausted',None
    cursor=message.get('next-cursor')
    if not cursor:raise ValueError('Full page lacks next cursor; cannot claim exhaustion')
    return 'in_progress',cursor


def main():
    for term in TERMS:
        rid='crossref-uncapped-'+term+'-20261105'
        run=next((r for r in L.read('discovery_runs') if r['run_id']==rid),None)
        if run and run['closure_state']=='exhausted':continue
        if not run:
            run={'run_id':rid,'route':'bibliographic_search','query_or_seed':{'query.bibliographic':term,'filter':'from-pub-date:2006-01-01,until-pub-date:2019-12-31'},
                 'source_url':'https://api.crossref.org/works','date':L.DATE,'pagination':{'cursor':'*','next_page':0,'rows':ROWS},
                 'provider_total':None,'retrieved_count':0,'deduplicated_additions':0,'failures':[],
                 'checkpoint':'Query not yet retrieved','closure_state':'in_progress','evidence':[],
                 'scope_note':'All results retained regardless of relevance. Single-term queries replace broad multiword retrieval; not claimed equivalent to exhausting old DNA-only tails.',
                 'capabilities_reference':DOCS}
            L.upsert('discovery_runs',run,'Persist uncapped query before retrieval')
        while run['closure_state']!='exhausted':
            page=run['pagination']['next_page'];params={**run['query_or_seed'],'cursor':run['pagination']['cursor'],'rows':ROWS,
                 'select':'DOI,title,author,published,published-online,published-print,type,relation,URL,container-title'}
            url='https://api.crossref.org/works?'+urlencode(params)
            result=fetch(url,f'crossref-{term}-page-{page:05}.json')
            if result['status']!='available':
                run['failures'].append(result);run['checkpoint']='Retrieval failed; resume saved cursor. If cursor expired, start a new explicit run and deduplicate retained DOIs.'
                run['closure_state']='blocked';L.upsert('discovery_runs',run,'Preserve failed request and resumable cursor');break
            try:
                message=json.loads((L.ROOT/result['local_file']).read_text())['message']
                closure,cursor=next_state(message)
                ev={**result,'locator':f'Crossref message.items page {page}; query recorded in URL'}
                reviews=L.read('publication_reviews');additions=page_additions(message['items'],reviews,rid,ev)
                L.save('publication_reviews',reviews+additions)
                edges={e['edge_id']:e for e in L.read('discovery_edges')}
                by_doi={normalize_doi(r['doi']):r['registry_key'] for r in reviews+additions if r.get('doi')}
                for item in message['items']:
                    doi=normalize_doi(item['DOI']);key=rid+':'+doi
                    edges.setdefault(key,{'edge_id':key,'source_key':rid,'target_key':by_doi[doi],'relation':'bibliographic_query_hit',
                        'evidence_url':url,'local_file':result['local_file'],'sha256':result['sha256'],
                        'locator':'message.items DOI '+doi,'reconciliation_state':'matched_registry_doi','run_id':rid})
                L.save('discovery_edges',list(edges.values()))
                # Count additions from saved records, so a crash between files is idempotent.
                run['deduplicated_additions']=sum(r.get('run_id')==rid for r in L.read('publication_reviews'))
                run['evidence'].append(ev);run['provider_total']=message['total-results']
                run['retrieved_count']+=len(message['items']);run['closure_state']=closure
                run['pagination'].update(cursor=cursor,next_page=page+1)
                run['checkpoint']='Short final page reached; all query hits retained, review pending.' if closure=='exhausted' else 'Page saved; follow next cursor without relevance cutoff.'
                L.upsert('discovery_runs',run,'Save complete API page and cursor after durable records')
                print(term,page,len(message['items']),len(additions),closure,flush=True)
            except Exception as error:
                run['failures'].append({'url':url,'error':str(error)});run['closure_state']='blocked';run['checkpoint']='Processing failed; retained raw page and prior cursor enable replay.'
                L.upsert('discovery_runs',run,'Preserve page-processing failure');raise
    print(L.counts())


if __name__=='__main__':main()
