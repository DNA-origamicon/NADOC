"""Enumerate every retained publisher reference, without relevance filtering."""
import json
from html.parser import HTMLParser
import ledger as L
from review_batch_0001 import evidence
class References(HTMLParser):
 def __init__(self):super().__init__();self.rows=[];self.cur=None;self.in_text=False
 def handle_starttag(self,t,attrs):
  a=dict(attrs)
  if t=='li' and 'c-article-references__item' in a.get('class','').split():self.cur={'number':int(a['data-counter'].rstrip('.')),'text_parts':[],'dois':[]}
  if self.cur is not None:
   if t=='p':self.in_text=a.get('id','').startswith('ref-CR')
   if a.get('data-doi') and a['data-doi'].lower() not in self.cur['dois']:self.cur['dois'].append(a['data-doi'].lower())
 def handle_data(self,d):
  if self.cur is not None and self.in_text:self.cur['text_parts'].append(d)
 def handle_endtag(self,t):
  if t=='p':self.in_text=False
  if t=='li' and self.cur is not None:
   self.cur['text']=' '.join(''.join(self.cur.pop('text_parts')).split());self.rows.append(self.cur);self.cur=None

def main():
 path=L.ROOT/'assets/research-20261105/funke-positioner-2015.html';p=References();p.feed(path.read_text());assert [r['number'] for r in p.rows]==list(range(1,34))
 ev=evidence(path,'https://www.nature.com/articles/nnano.2015.240','Complete publisher References list, ref-CR1 through ref-CR33; subscription preview includes bibliography')
 known={r['doi']:r['registry_key'] for r in L.read('publication_reviews') if r['doi']};runid='backward-positioner-20261105'
 for r in p.rows:
  target=known.get(r['dois'][0],r['dois'][0]) if len(r['dois'])==1 else 'reference:positioner2015:'+str(r['number'])
  L.upsert('discovery_edges',dict(edge_id=runid+':'+str(r['number']),source_key='10.1038/nnano.2015.240',target_key=target,relation='cites',evidence_url=ev['url'],local_file=ev['local_file'],sha256=ev['sha256'],locator='HTML #ref-CR'+str(r['number']),target_metadata=r,reconciliation_state='matched_explicit_doi; relevance_pending' if target in known.values() else 'pending_identity_and_scope',run_id=runid,date=L.DATE),'Retain every reference including non-origami methodological papers')
 L.atomic(L.HERE/'positioner_reference_inventory.json',json.dumps(p.rows,indent=2,ensure_ascii=False))
 L.upsert('discovery_runs',dict(run_id=runid,route='backward_citations',query_or_seed='10.1038/nnano.2015.240 complete publisher reference list',source_url=ev['url'],date=L.DATE,pagination={'references':33,'first':1,'last':33,'all_enumerated':True},provider_total=33,retrieved_count=33,deduplicated_additions=33,additions_unit='Citation edges, not eligible works',evidence=[ev],failures=[],closure_state='exhausted',checkpoint='This one bibliography enumerated; target relevance, unmatched identities and recursive/forward discovery remain open.'),'Record source-local enumeration closure only')
 print({'references':len(p.rows),'doi_identified':sum(bool(r['dois']) for r in p.rows),'validation':L.validate()})
if __name__=='__main__':main()
