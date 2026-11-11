"""Match bibliography PMID links to primary local article identifiers only."""
import re,json
import xml.etree.ElementTree as ET
import ledger as L
from review_batch_0001 import evidence
RID='douglas-local-identity-20261105'
def main():
 known={p['doi']:p['registry_key'] for p in L.read('publication_reviews') if p['doi']};index={};evs={};conflicts=[];files=sorted((L.ROOT/'assets/sources').rglob('*.xml'))
 for f in files:
  try:root=ET.parse(f).getroot()
  except ET.ParseError:continue
  ids={x.get('pub-id-type'):''.join(x.itertext()).strip() for x in root.findall('./front/article-meta/article-id')};pmid=ids.get('pmid');doi=ids.get('doi','').lower()
  if not pmid or doi not in known:continue
  if pmid in index and index[pmid]!=known[doi]:conflicts.append(pmid);continue
  index[pmid]=known[doi];evs[pmid]=evidence(f,'https://doi.org/'+doi,'front/article-meta/article-id PMID and DOI')
 assert not conflicts,conflicts
 for e in L.read('discovery_edges'):
  if e.get('run_id')!='author-douglas-20261105':continue
  pmids=[]
  for url in e['target_metadata']['links']:
   m=re.search(r'(?:pubmed\.ncbi\.nlm\.nih\.gov/|ncbi\.nlm\.nih\.gov/pubmed/)(\d+)',url)
   if m:pmids.append(m[1])
  targets={index[m] for m in pmids if m in index}
  if not targets:continue
  assert len(targets)==1
  pmid=next(m for m in pmids if m in index);e.update(target_key=index[pmid],identity_evidence=evs[pmid],identity_run=RID,reconciliation_state='matched_registry_explicit_pmid_doi; other_versions_pending')
  L.upsert('discovery_edges',e,'Reconcile bibliography PMID using actual primary article DOI; no title match')
 matched=[e for e in L.read('discovery_edges') if e.get('identity_run')==RID];evidence_by_path={e['identity_evidence']['local_file']:e['identity_evidence'] for e in matched}
 L.upsert('discovery_runs',dict(run_id=RID,route='identifier_reconciliation',query_or_seed='All17 Douglas bibliography entries versus retained XML PMID/DOI pairs',source_url='local primary XML',date=L.DATE,pagination={'files_scanned':len(files),'complete':True},provider_total=17,retrieved_count=len(matched),deduplicated_additions=0,evidence=list(evidence_by_path.values()),failures=[],closure_state='exhausted',closure_scope='Local identifier scan only; unmatched entries and external author coverage remain open',checkpoint=f'{len(matched)} explicit PMID matches; no relevance decisions',conflicts=conflicts),'Persist bounded local identity pass')
 print({'matches':[(e['edge_id'],e['target_key']) for e in matched],'validation':L.validate()})
if __name__=='__main__':main()
