"""Uncapped, resumable Europe PMC forward citation enumeration for one reviewed seed.
All dates retained as citation leads; no automatic relevance or date eligibility.
"""
import json
from collections import Counter
import ledger as L
from acquire_sources import fetch

RID='forward-18187649-20261105'
SEED='10.1126/science.1150082'
BASE='https://www.ebi.ac.uk/europepmc/webservices/rest/MED/18187649/citations'

def main():
    run=next((r for r in L.read('discovery_runs') if r['run_id']==RID),None)
    if run and run['closure_state']=='exhausted':return
    if run is None:
        manifest=json.loads((L.ROOT/'assets/research-20261105/acquisition.json').read_text())
        run={'run_id':RID,'route':'forward_citations','query_or_seed':SEED,'source_url':BASE,'date':L.DATE,'pagination':{'next_page':1,'pageSize':100},'provider_total':None,'retrieved_count':0,'deduplicated_additions':0,'failures':[manifest['forward-18187649-page-00001.json']],'evidence':[],'closure_state':'in_progress','checkpoint':'1000-row request failed HTTP500; 100-row pages work. Retain all dates without title filtering.','scope_note':'Enumeration of this provider network for one seed, not complete field coverage. Targets require DOI/version/date and relevance reconciliation.'}
        L.upsert('discovery_runs',run,'Persist forward route and capability failure')
    while True:
        page=run['pagination']['next_page']
        url=BASE+f'?format=json&page={page}&pageSize=100'
        result=fetch(url,f'forward-18187649-size100-page-{page:05}.json')
        if result['status']!='available':
            run['failures'].append(result);run.update(closure_state='blocked',checkpoint='Request failed; resume this page, not successful prior pages.')
            L.upsert('discovery_runs',run,'Retain forward retrieval failure');break
        data=json.loads((L.ROOT/result['local_file']).read_text())
        if not isinstance(data.get('hitCount'),int) or 'citationList' not in data:raise ValueError('Incomplete provider response cannot establish exhaustion')
        items=data['citationList'].get('citation',[])
        edges={e['edge_id']:e for e in L.read('discovery_edges')}
        prior={e['target_key'] for e in edges.values() if e.get('run_id')==RID}
        for item in items:
            target='epmc:'+item['source']+':'+str(item['id']);eid=RID+':'+target
            edges.setdefault(eid,{'edge_id':eid,'source_key':SEED,'target_key':target,'relation':'cited_by','evidence_url':url,'local_file':result['local_file'],'sha256':result['sha256'],'locator':'citationList.citation '+item['source']+'/'+str(item['id']),'target_metadata':item,'date_scope':'pre2020_year_lead' if int(item['pubYear'])<2020 else 'later_citation_lead','reconciliation_state':'pending_identity_and_scope','run_id':RID,'date':L.DATE})
        L.save('discovery_edges',list(edges.values()))
        current=[e for e in edges.values() if e.get('run_id')==RID]
        ev={**result,'locator':f'citationList.citation, page {page}'}
        if not any(e['local_file']==ev['local_file'] for e in run['evidence']):run['evidence'].append(ev)
        run.update(provider_total=data['hitCount'],retrieved_count=len(current),deduplicated_additions=len(current),additions_unit='unreconciled provider citation targets, NOT new eligible works',date_scopes=dict(Counter(e['date_scope'] for e in current)))
        if len(items)<100:
            if len(current)!=data['hitCount']:raise ValueError('Short page but unique total mismatch; inspect pagination/provider drift')
            run.update(closure_state='exhausted',checkpoint='All pages of this seed/provider network enumerated; citation-target identity and review remain pending.')
        elif len(current)==len(prior) and not any(e['local_file']==result['local_file'] for e in edges.values() if e.get('run_id')==RID):
            raise ValueError('Repeated full page; cannot advance or claim exhausted')
        else:run.update(closure_state='in_progress',checkpoint='Page saved; continue all pages.')
        run['pagination']['next_page']=page+1
        L.upsert('discovery_runs',run,'Save forward citation page after durable edges')
        print(page,len(items),len(current),run['closure_state'],flush=True)
        if run['closure_state']=='exhausted':break
    print(L.validate())

if __name__=='__main__':main()
