"""Five low-keyword records: primary scope audits and explicit access limits."""
import json
import ledger as L
from review_batch_0001 import evidence
ROWS=[
('10.1155/2015/245154','review','fulltext_reviewed','background_or_review','PMC4415482.xml','Abstract, section survey and concluding origami proposal',
 'Review of muscle contraction and actomyosin mechanics. Concluding discussion proposes origami scaffolds for ordered motor arrays as future work, citing ref351; no implemented origami design established by the inspected passages. Full bibliography and cited motor-scaffold source remain to be reconciled.'),
('10.1158/1078-0432.ccr-14-3126','commentary','metadata_screened','background_or_review','batch_0014_commentary_verified_metadata.json','Primary PubMed search metadata; full-text access challenge saved separately',
 'Primary bibliographic title identifies a20th-anniversary commentary on therapeutic nanoparticles in cancer. This supports commentary/background classification at metadata depth only; no design contribution inferred. PMC4610251 and direct PubMed opening returned browser challenges. Full origami passages and bibliography remain uninspected.'),
('10.1186/s12896-015-0180-6','journal_article','fulltext_reviewed','not_origami','PMC4551372.xml','Abstract, complete Methods, Conclusions and origami comparison paragraphs; refs32/34',
 'Implemented scaffolds are recombinant CCMV coat-protein virus-like particles with peptide epitopes. Methods and Conclusions describe protein expression and particle reassembly, not DNA-origami construction or reuse. Origami-coated cellular delivery(ref32) and CpG-origami(ref34) are cited prior/comparative work. Same-agent method/object audit supports exclusion from origami-design census while retaining both discovery leads.'),
('10.1371/journal.pone.0130875','journal_article','fulltext_reviewed','not_origami','PMC4482597.xml','Abstract; complete Materials and Methods; Results/Discussion scope and concluding assay interpretation',
 'Study measures pairing/melting of35-base short-oligo systems with abasic sites and TexasRed/BHQ1 reporter pairs. Results concern grouping bases and detecting mismatches; origami appears as potential application context in the abstract, not an implemented scaffold. Same-agent method/object audit supports not_origami exclusion. Full bibliography recursion remains open.'),
('10.15729/nanocellnews.2015.01.14.002','unresolved','metadata_screened','uncertain','batch_0014_rotation_primary.json','Secondary OpenAlex metadata only; primary DOI access failed',
 'Portuguese Nanocell News item is retained as unresolved. Secondary metadata identifies title, outlet and2015date, but primary content was not accessed. Do not classify it as original research, news commentary or a complete design from its title. Primary DOI failed through web tool; find archived article and any referenced journal counterpart. Date not primary verified.')]

def main():
 pubs={p['registry_key']:p for p in L.read('publication_reviews')}
 for key,typ,stage,rel,name,loc,note in ROWS:
  path=L.ROOT/'assets/sources/pre2020-expansion'/name if name.endswith('.xml') else L.HERE/name
  ev=evidence(path,'https://doi.org/'+key,loc);p=pubs[key]
  if ev not in p['evidence']:p['evidence'].append(ev)
  if not name.endswith('.xml'):
   ae=evidence(L.HERE/'batch_0014_rotation_access.json','https://doi.org/'+key,'Browser challenges or DOI opening failure; not proof of source absence')
   if ae not in p['evidence']:p['evidence'].append(ae)
  p.update(title=p['legacy_record']['publication'],publication_type=[] if typ=='unresolved' else [typ],review_stage=stage,relevance=rel,design_contributions=[],catalog_eligibility='excluded' if rel=='not_origami' else 'unresolved',access='partial',rationale=note,unresolved_questions=['Follow primary design references, complete bibliography and author-history coverage.']+(['Acquire primary article, determine publication type and counterpart.'] if rel=='uncertain' else []),reviewer='Codex named primary sections or explicitly limited metadata inspection',run_id='B0014',date=L.DATE)
  L.upsert('publication_reviews',p,'Record low-keyword scope decisions and access uncertainty')
 ev=evidence(L.ROOT/'assets/sources/pre2020-expansion/PMC4551372.xml','https://doi.org/10.1186/s12896-015-0180-6','References32/34 and discussion context')
 for n,target in [(32,'10.1021/nl500677j'),(34,'10.1021/nn203161y')]:
  L.upsert('discovery_edges',dict(edge_id='B0014:CCMV:ref'+str(n),source_key='10.1186/s12896-015-0180-6',target_key=target,relation='cites',evidence_url=ev['url'],local_file=ev['local_file'],sha256=ev['sha256'],locator='Ref'+str(n)+' explicit DOI and comparative origami context',reconciliation_state='explicit_citation_followup_pending',run_id='B0014',date=L.DATE),'Retain origami citations from excluded protein-particle study')
 b=next(b for b in L.read('batches') if b['batch_id']=='B0014');pubs={p['registry_key']:p for p in L.read('publication_reviews')}
 action='20of25 first-pass screened; review/commentary, two audited nonorigami studies and unresolved Nanocell item retained.'
 if action not in b['completed_actions']:b['completed_actions'].append(action)
 for key in ['10.1186/s12896-015-0180-6','10.1371/journal.pone.0130875']:
  if key not in b['exclusion_audit']['sample']:b['exclusion_audit']['sample'].append(key)
 b['exclusion_audit']['reason']='Same-agent primary scope audits; includes nonorigami objects and broad/narrow TALOS distinction, no independent review claim.'
 b.update(after_counts=L.counts(),unresolved_keys=[k for k in b['input_keys'] if pubs[k]['unresolved_questions']],validation=[L.validate()],next_queue=['Five remaining rotating records: nanopore074004,cooperativitygkv602,ping-pong2014.0215,CLEOPR7375859,DETC46833','CV identities, FNANO2010, all source and discovery followups'])
 L.upsert('batches',b,'Save20of25 first passes and retain all source/discovery questions')
 L.atomic(L.HERE/'batch_0014_rotation_first_audit.json',json.dumps(dict(first_pass_count=20,input_count=25,reviewed_keys=[r[0] for r in ROWS],counts=L.counts(),validation=L.validate()),indent=2)+'\n');print(L.validate())

if __name__=='__main__':main()
