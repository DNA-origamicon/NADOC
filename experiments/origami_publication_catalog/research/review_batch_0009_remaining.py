"""Finish B0009 first-pass screening with explicit source-depth limits."""
import json
import ledger as L
from review_batch_0001 import evidence
WEB=L.HERE/'batch_0009_remaining_web_evidence.json'
NOTES=[
('10.1098/rsif.2012.0740','fulltext_reviewed','background_or_review',['review_article'],'https://pmc.ncbi.nlm.nih.gov/articles/PMC3565727/','Abstract; section3.2 entire nucleic-acid discussion; section5 Conclusions',
 'Primary text explicitly identifies a review. Section3.2 attributes origami methods and devices to Rothemund, Douglas and Andersen; section5 cites the earlier nanorobot. No new origami design is established by these reviewed sections. Protein nanoparticle designs discussed by the authors are separate from origami.',
 ['Enumerate complete bibliography, including refs25–30; reconcile attributed designs without treating review illustrations as new cores.']),
('10.1073/pnas.1310092110','metadata_screened','uncertain',['journal_article'],'https://pubmed.ncbi.nlm.nih.gov/24101463/','Retained primary abstract (extra turn60search1) and indexed PMC discussion excerpt (turn60search3)',
 'Abstract describes experimental/model coassembly of R/S chiral oligo(p-phenylene vinylene), not an origami construct. Indexed discussion compares stepwise assembly with DNA origami refs25–28. Likely background-only origami relevance, but leave uncertain until full Discussion/Methods can be inspected. PMC HTML was a browser challenge, EuropePMC XML returned500 and institutional PDF404.',
 ['Acquire complete primary article via alternate institutional/publisher route; inspect whether origami appears only as analogy.','Resolve and follow refs25–28; do not equate reference occurrence with design reuse.']),
('10.1080/07391102.2013.786386','metadata_screened','design_bearing',['conference_abstract'],'https://www.tandfonline.com/doi/full/10.1080/07391102.2013.786386','search turn59search0: abstract144, issue title, date, full abstract and three references',
 'Publisher identifies Albany2013 The18thConversation Book of Abstracts, not a full journal research report. Abstract reports origami-supported plasmonic particle helices, optical activity and orientation effects, explicitly citing Kuzyk2012. Generic8kb/~200oligo description is not a complete design specification. Later hotspots/orientation observations require journal-counterpart reconciliation; do not merge the whole abstract into Kuzyk2012 automatically.',
 ['Reconcile orientation/hotspot results with journal publications or preprints using primary evidence.','Retain separate conference identity; inspect cited Kuzyk2012 exact helix variant/source.']),
('10.1088/0957-4484/24/43/435601','metadata_screened','design_bearing',['journal_article'],'https://pubmed.ncbi.nlm.nih.gov/24076521/','search turn59search1: primary author abstract and article date; Choi lab bibliography matching title/authors',
 'Author abstract reports short origami cylinders linked into tubules, disassembled through toehold-mediated strand displacement and reassembled with different chirality; hairpin or AuNP decoration variants. This establishes broad design relevance, not exact core routing/lattice, sequence completeness or unique new geometry count. IOP PDF attempt returned non-PDF content.',
 ['Acquire main/SI and inspect monomer core, linker substitutions, source parentage and per-variant sequences.','Reconcile ASME2014-36708 same-title technical presentation without assuming it is a full proceedings paper.'])]
def main():
 pubs={p['registry_key']:p for p in L.read('publication_reviews')}
 for key,stage,rel,types,url,locator,note,qs in NOTES:
  path=L.ROOT/'assets/research-20261105/doll-2013-main.html' if key=='10.1098/rsif.2012.0740' else WEB
  ev=evidence(path,url,locator);p=pubs[key]
  p.update(review_stage=stage,relevance=rel,publication_type=types,design_contributions=['uncertain'] if rel in ('uncertain','design_bearing') else [],catalog_eligibility='unresolved',access='partial',evidence=[ev],rationale=note,unresolved_questions=qs,reviewer='Codex primary content inspection at stated depth',run_id='B0009',date=L.DATE)
  if key=='10.1080/07391102.2013.786386':p['date_evidence']={'date':'2013-05-29','meaning':'publisher first-online date','source':ev,'primary_verified':True}
  L.upsert('publication_reviews',p,'Complete balanced first-pass review; retain uncertain scope and separate conference type')
 source='10.1080/07391102.2013.786386';ev=pubs[source]['evidence'][0]
 for target,loc in [('10.1038/nature04586','Reference Rothemund2006 Nature440:207'),('10.1146/annurev-biochem-060308-102244','Reference Seeman2010 Annual Review of Biochemistry79; DOI candidate pending primary identity verification'),('10.1038/nature10889','Reference Kuzyk2012 Nature483:311')]:
  L.upsert('discovery_edges',dict(edge_id='albany144:cites:'+target,source_key=source,target_key=target,relation='cites',evidence_url=ev['url'],local_file=ev['local_file'],sha256=ev['sha256'],locator=loc,reconciliation_state='pending_primary_identity_and_design_overlap',run_id='B0009',date=L.DATE),'Retain entire three-reference conference bibliography; do not infer version identity')
 ev=evidence(WEB,'https://www.asme.org/wwwasmeorg/media/ResourceFiles/Events/IMECE/Program2014.pdf','search turn59search14: Track2 Tuesday November18,1pm,IMECE2014-36708,Technical Presentation')
 L.upsert('discovery_edges',dict(edge_id='B0009:conference:IMECE2014-36708',source_key='10.1088/0957-4484/24/43/435601',target_key='conference:IMECE2014-36708',relation='possible_conference_counterpart',evidence_url=ev['url'],local_file=ev['local_file'],sha256=ev['sha256'],locator=ev['locator'],target_metadata={'title':'Hierarchically Assembled DNA Origami Tubules With Reconfigurable Chirality','authors':['Haorong Chen','Jong Hyun Choi'],'publication_type':['conference_presentation'],'year':2014},reconciliation_state='pending_program_acquisition_and_counterpart_identity',run_id='B0009',date=L.DATE),'Retain official-program lead; presentation is not proof of a complete design or full proceedings paper')
 b=next(b for b in L.read('batches') if b['batch_id']=='B0009');b.setdefault('completed_actions',[]).append('Completed remaining four balanced first passes: Doll review, uncertain Korevaar primary abstract, Albany144 conference abstract, tubule author abstract; retained conference leads.')
 b.update(status='completed',after_counts=L.counts(),validation=[L.validate()],unresolved_keys=b['input_keys'],next_queue=['Continue B0010 balanced selection; all B0009 design-specific source follow-ups remain.','Enumerate Choi lab bibliography and FNANO2014; recurse citations and reconcile conference counterparts.'])
 L.upsert('batches',b,'Finish25/25 first-pass batch without implying full-source closure')
 L.atomic(L.HERE/'batch_0009_completion_audit.json',json.dumps(dict(batch_id='B0009',first_pass_count=25,input_count=25,complete_sources_certified=0,validation=L.validate(),counts=L.counts()),indent=2)+'\n')
 print(L.validate())
if __name__=='__main__':main()
