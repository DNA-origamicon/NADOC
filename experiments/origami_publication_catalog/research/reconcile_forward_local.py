"""Resolve forward targets only from explicit PMID/DOI identifiers in retained XML."""
import json
import xml.etree.ElementTree as ET
import ledger as L
from review_batch_0001 import evidence

RID='forward-local-identity-20261105'
def main():
    pubs=L.read('publication_reviews');bydoi={r['doi']:r['registry_key'] for r in pubs if r.get('doi')};index={};evs={};conflicts=[]
    for p in sorted((L.ROOT/'assets/sources/pre2020-expansion').glob('*.xml')):
        root=ET.parse(p).getroot();ids={x.get('pub-id-type'):''.join(x.itertext()).strip() for x in root.findall('./front/article-meta/article-id')}
        pmid=ids.get('pmid');doi=ids.get('doi','').lower()
        if not pmid or doi not in bydoi:continue
        target=bydoi[doi]
        if pmid in index and index[pmid]!=target:conflicts.append({'pmid':pmid,'keys':[index[pmid],target]});continue
        index[pmid]=target;evs[pmid]=evidence(p,'https://pmc.ncbi.nlm.nih.gov/articles/'+p.stem+'/','front/article-meta/article-id PMID and DOI')
    assert not conflicts,conflicts
    edges=L.read('discovery_edges');changed=0;source_evidence=[]
    for edge in edges:
        if edge.get('run_id')!='forward-18187649-20261105':continue
        item=edge['target_metadata'];pmid=str(item['id'])
        if item['source']!='MED' or pmid not in index:continue
        target=index[pmid];ev=evs[pmid]
        if edge['target_key']==target:continue
        edge['provider_target_key']='epmc:MED:'+pmid;edge['target_key']=target
        edge['identity_evidence']=ev;edge['reconciliation_state']='matched_registry_explicit_pmid_doi';edge['identity_run']=RID
        L.upsert('discovery_edges',edge,'Match explicit retained article PMID and DOI, not title similarity')
        changed+=1
    matched=[e for e in L.read('discovery_edges') if e.get('identity_run')==RID]
    unique={e['identity_evidence']['local_file']:e['identity_evidence'] for e in matched}
    run={'run_id':RID,'route':'identifier_reconciliation','query_or_seed':'311 forward targets for Science 10.1126/science.1150082 against retained PMC XML','source_url':'retained primary XML','date':L.DATE,'pagination':{'local_XML_files':len(list((L.ROOT/'assets/sources/pre2020-expansion').glob('*.xml'))),'complete':True},'provider_total':311,'retrieved_count':len(matched),'deduplicated_additions':0,'failures':[],'evidence':list(unique.values()),'closure_state':'exhausted','checkpoint':f'{len(matched)} target identities matched; {311-len(matched)} remain outside these explicit local matches. No new relevance decisions.','conflicts':conflicts}
    L.upsert('discovery_runs',run,'Save local identifier matching scope and source hashes')
    print(json.dumps({'new_matches':changed,'total_matches':len(matched),'validation':L.validate()}))

if __name__=='__main__':main()
