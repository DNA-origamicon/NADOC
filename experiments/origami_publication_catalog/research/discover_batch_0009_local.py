"""Enumerate every reference in the five B0009 primary XML articles, uncapped."""
import xml.etree.ElementTree as ET
from urllib.parse import parse_qs
import ledger as L
from review_batch_0001 import evidence

def main():
 pubs=L.read('publication_reviews');known={r['doi']:r['registry_key'] for r in pubs if r['doi']};evs=[];total=0;targets=set()
 for doi,relative in [('10.1093/nar/gkt592','sources/pre2020-expansion/PMC3794576.xml'),('10.1093/nar/gkt1269','sources/pre2020-expansion/PMC3936709.xml'),('10.1091/mbc.e13-03-0155','sources/pre2020-expansion/PMC3842987.xml'),('10.1101/gad.226837.113','sources/pre2020-expansion/PMC3841729.xml'),('10.1083/jcb.2002pi','sources/pre2020-expansion/PMC3549966.xml')]:
  path=L.ROOT/'assets'/relative;root=ET.parse(path).getroot();ev=evidence(path,'https://doi.org/'+doi,'Every XML ref, including non-origami references');evs.append(ev)
  for i,ref in enumerate(root.findall('.//ref'),1):
   target_doi=next((''.join(x.itertext()).strip().lower() for x in ref.findall('.//pub-id') if x.get('pub-id-type')=='doi'),'')
   links=ref.findall('.//ext-link')
   if not target_doi:target_doi=next((x.get('{http://www.w3.org/1999/xlink}href','').removeprefix('https://doi.org/').removeprefix('http://dx.doi.org/').lower() for x in links if x.get('ext-link-type')=='doi'),'')
   loc=ref.get('id') or str(i);target=known.get(target_doi,target_doi or 'reference:'+doi+':'+loc)
   scholar=next((parse_qs(x.get('{http://www.w3.org/1999/xlink}href','')) for x in links if x.get('ext-link-type')=='google-scholar'),{})
   title=ref.find('.//article-title');year=ref.find('.//year')
   L.upsert('discovery_edges',dict(edge_id='cites:'+doi+':'+loc,source_key=doi,target_key=target,relation='cites',evidence_url=ev['url'],local_file=ev['local_file'],sha256=ev['sha256'],locator='XML ref '+loc,target_doi=target_doi,target_title=''.join(title.itertext()) if title is not None else scholar.get('title',[None])[0],target_year=year.text if year is not None else scholar.get('publication_year',[None])[0],raw_reference=' '.join(ref.itertext()),reconciliation_state='matched_registry_doi' if target_doi in known else 'pending_identity_and_scope',run_id='backward-B0009-local',date=L.DATE),'Retain every reference as discovery evidence without relevance inference')
   total+=1;targets.add(target)
 L.upsert('discovery_runs',dict(run_id='backward-B0009-local',route='backward_citations',query_or_seed=['10.1093/nar/gkt592','10.1093/nar/gkt1269','10.1091/mbc.e13-03-0155','10.1101/gad.226837.113','10.1083/jcb.2002pi'],source_url='Retained primary XML',date=L.DATE,pagination={'method':'all XML ref elements','complete':True},provider_total=total,retrieved_count=total,unique_targets=len(targets),deduplicated_additions=len(targets-set(known.values())),additions_unit='unresolved reference targets, not new eligible publications',evidence=evs,failures=[],closure_state='exhausted',closure_scope='Reference extraction for these five sources only; recursive identity/scope review pending',checkpoint='Resolve all unmatched targets; follow explicit origami parent citations'),'Save completed uncapped reference-list enumeration')
 print({'references':total,'unique_targets':len(targets),'validation':L.validate()})
if __name__=='__main__':main()
