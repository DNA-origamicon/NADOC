"""Complete first-pass queue, preserving proposal/version/access distinctions."""
import json
import ledger as L
from review_batch_0001 import evidence
ROWS=[
('10.1088/0957-4484/26/7/074004','review','metadata_screened','background_or_review','batch_0014_final_primary1.json','Primary PubMed abstract/type and author-hosted publisher PDF search header',
 'Review surveys nanopore sensing and DNA-motion control, including biological motors and transport modifications. Primary metadata supports review status; exact origami passages and bibliography remain uninspected. Publisher PDF header reports published2February2015, distinct from20Februaryissue.'),
('10.1093/nar/gkv602','journal_article','metadata_screened','design_bearing','batch_0014_final_primary4.json','PubMed abstract and Fig1caption',
 'Primary abstract reports bulk-fluorescence measurement of junction cooperativity up to neighboring junctions in an origami object. Fig1caption compares caDNAno gear-like object,brick,single-layer rectangle plus four3D and two2D shapes designed by authors. These are explicitly different analytical contexts; do not count each as an experimentally realized or source-complete design. Exact objects, parent relationships, scaffold/staple/native files and narrow eligibility require main/SI inspection. First online13June2015 confirmed by publisher metadata and PubMed.'),
('10.1098/rsta.2014.0215','journal_article','fulltext_reviewed','design_bearing','batch_0014_final_primary4.json','Abstract/Introduction; section3(a) platform tiles and3(d) implementation',
 'Proposed light-controlled computation uses origami platform and floating tiles in alternating checkerboard updates. Section3 describes an approximately100nm square-cross tile with horizontal helices above vertical ones and six helix-pairs per edge. Six floating tile types per red/green species implement the proposed rule; logical types are not independently demonstrated DNA cores. Earlier arrays/replication experiments are cited foundations, not experiments reported for this complete system. Exact parent source, sequences and proposed per-type compositions remain unresolved. Broad theoretical design relevance supported, no experimental or source-completeness claim.'),
('10.1109/cleopr.2015.7375859','conference_paper','metadata_screened','uncertain','batch_0014_final_primary3.json','Primary Optica proceedings page25E3_4 and abstract; ORCID date context in primary2',
 'Optica proceedings page identifies Hwang/Wickham/Perrault/Yoo/Park/Shih/Lee presentation at CLEO-PR,Busan24–28August2015,paper25E3_4. Abstract proposes origami arrangement of metal nanoparticles but does not establish an exact documented design. Retain uncertain pending full conference text. ORCID imported metadata gives2016 while event/proceedings page gives2015; exact first-publication date needs reconciliation, not automatic date replacement. No complete-source inference from abstract.'),
('10.1115/detc2015-46833','conference_paper','metadata_screened','uncertain','batch_0014_final_primary2.json','Secondary proceedings metadata; primary DOI failure in primary4; OSU journal counterpart in primary3',
 'Proceedings record retained separately; primary DOI endpoint inaccessible. Secondary abstract describes review of origami mechanisms, but primary conference scope is not verified, so relevance remains uncertain. OSU institutional publication history identifies possible2017journal counterpart10.1115/1.4036216 with similar title/authors. Do not merge or infer identical design content before comparing texts; journal and conference dates/types remain separate.')]

def main():
 pubs={p['registry_key']:p for p in L.read('publication_reviews')}
 for key,typ,stage,rel,name,loc,note in ROWS:
  p=pubs[key]
  for file in dict.fromkeys([name,'batch_0014_final_primary1.json','batch_0014_final_primary3.json','batch_0014_final_primary4.json']):
   ev=evidence(L.HERE/file,'https://doi.org/'+key,loc if file==name else 'Supporting primary metadata/access or counterpart search; see rationale for source limits')
   if ev not in p['evidence']:p['evidence'].append(ev)
  p.update(title=p['legacy_record']['publication'],publication_type=[typ],review_stage=stage,relevance=rel,design_contributions=['uncertain'] if rel=='design_bearing' else [],catalog_eligibility='unresolved',access='partial',rationale=note,unresolved_questions=['Inspect complete main/SI and reconcile exact objects, design lineage and sources.','Verify publication versions/dates and enumerate backward/forward citations and author histories.'],reviewer='Codex primary named sections or explicitly limited metadata inspection',run_id='B0014',date=L.DATE)
  L.upsert('publication_reviews',p,'Finish first-pass queue with theoretical and conference distinctions')
 ev=evidence(L.HERE/'batch_0014_final_primary3.json','https://mae.osu.edu/idr/publications','OSU publication entry55 and institutional journal record; exact conference overlap pending')
 L.upsert('discovery_edges',dict(edge_id='B0014:kinematic:journal',source_key='10.1115/detc2015-46833',target_key='10.1115/1.4036216',relation='possible_counterpart',evidence_url=ev['url'],local_file=ev['local_file'],sha256=ev['sha256'],locator=ev['locator'],reconciliation_state='version_scope_pending',run_id='B0014',date=L.DATE),'Preserve potential conference/journal relationship without merging')
 b=next(b for b in L.read('batches') if b['batch_id']=='B0014');pubs={p['registry_key']:p for p in L.read('publication_reviews')}
 assert len(b['input_keys'])==25 and all(pubs[k]['review_stage']!='unreviewed' for k in b['input_keys'])
 action='All25 B0014 inputs first-pass screened; complete-source and bibliographic closure remain open.'
 if action not in b['completed_actions']:b['completed_actions'].append(action)
 b.update(status='completed',unresolved_keys=[k for k in b['input_keys'] if pubs[k]['unresolved_questions']],after_counts=L.counts(),validation=[L.validate()],next_queue=['FNANO2010 full schedule enumeration and abstract/counterpart followups','Reconcile Hao Yan CV entries and source duplicates','Acquire cooperativity main/SI and compare conference/journal mechanisms','Select balanced B0015; retain all previous source/discovery followups'])
 L.upsert('batches',b,'Complete first passes only; preserve unresolved source and discovery work')
 out=dict(batch_id='B0014',first_pass_count=25,input_count=25,unresolved_followup_count=len(b['unresolved_keys']),complete_source_certifications=0,validation=L.validate(),counts=L.counts())
 L.atomic(L.HERE/'batch_0014_complete_audit.json',json.dumps(out,indent=2)+'\n');print(out)

if __name__=='__main__':main()
