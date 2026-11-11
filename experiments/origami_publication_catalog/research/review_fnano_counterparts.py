"""Inspect two candidate journal counterparts; conference identity remains tentative."""
import ledger as L
from review_batch_0001 import evidence

SPECS=[
 ('10.1038/s41467-018-03601-5','sources/PMC5899095.xml','Results: Design and fabrication of nanoscale components; Assembly/fabrication of micron-scale systems; Methods: Design and fabrication of nanoconstructs','Two prototype devices, a nano-rotor and a nano-hinge, connect to stiff polymerized levers. Methods explicitly specify a 56-helix honeycomb nano-brick; two sequence variants shift scaffold registration by 31 bases. Polymerization strands join separately folded components and are distinct from ordinary overhang modifications.','Inspect SI figures2/4/6 and tables1–6; reconcile both scaffold-register variants, polymerization sets, and platform/hinge parents. No molecular authoring authorized.'),
 ('10.1038/s41565-018-0336-3','sources/pre2020-expansion/PMC6420075.xml','Design and Characterization of Patterned Surface Plasmon Resonance; Online Methods: Preparation of antigen decorated nanostructures','An 18-helix bundle and a brick display hapten patterns for pairwise and 2D antigen tests. Methods explicitly cite prior characterization of the 18HB; decorated staples and linker-length variants modify that core.','Inspect SI designs/sequence tables and references34–36 for exact parent 18HB; independently verify brick lattice. Check publisher correction DOI10.1038/s41565-019-0404-3 before source certification.')]

def main():
 for key,relative,loc,note,q in SPECS:
  r=next(r for r in L.read('publication_reviews') if r['registry_key']==key)
  if r.get('run_id')!='bootstrap-20261105':continue
  ev=evidence(L.ROOT/'assets'/relative,'https://pmc.ncbi.nlm.nih.gov/articles/'+relative.split('/')[-1].removesuffix('.xml')+'/',loc)
  r.update(review_stage='fulltext_reviewed',relevance='design_bearing',catalog_eligibility='unresolved',design_contributions=['new_design','reused_design','modified_design'],evidence=[ev],rationale=note,unresolved_questions=[q],access='partial',reviewer='Codex primary article section inspection',run_id='fnano-counterparts-2018',date=L.DATE)
  L.upsert('publication_reviews',r,'Inspect actual experimental design sections of candidate counterpart; no title-only inclusion')
 pubs=L.read('publication_reviews');spec=[('Stephanie Lauback','10.1038/s41467-018-03601-5'),('Bjorn Hogberg','10.1038/s41565-018-0336-3')]
 for author,doi in spec:
  source=next(r for r in pubs if r.get('run_id')=='fnano-2018' and r['authors']==[author]);target=next(r for r in pubs if r['registry_key']==doi);ev=target['evidence'][0]
  eid='possible_counterpart:'+source['registry_key']+':'+doi
  if any(e['edge_id']==eid for e in L.read('discovery_edges')):continue
  L.upsert('discovery_edges',{'edge_id':eid,'source_key':source['registry_key'],'target_key':doi,'relation':'possible_journal_counterpart','evidence_url':ev['url'],'local_file':ev['local_file'],'sha256':ev['sha256'],'locator':ev['locator'],'reconciliation_state':'pending_abstract_confirmation; matching_author_title_and_experimental_topic','run_id':'fnano-counterparts-2018','date':L.DATE},'Retain likely counterpart without merging versions or promoting conference design claims')
 target=next(r for r in pubs if r['registry_key']=='10.1038/s41467-018-03601-5');ev=target['evidence'][0]
 if not any(d['design_id']=='RDE0005' for d in L.read('design_evidence')):
  L.upsert('design_evidence',{'design_id':'RDE0005','publication_keys':[target['registry_key']],'named_objects':['56-helix nano-brick / rotor arm'],'variant_links':[],'relationships':[{'relation':'presented_in','target_key':target['registry_key'],'evidence':ev}],'lattice_decision':'honeycomb_explicit_main_methods','catalog_eligibility':'unresolved','evidence':[ev],'source_files':[ev],'core_variant_composition':'Same geometry with a 31-base scaffold registration shift in a second sequence variant. Polymerization strands and attachment overhang sets require separate reconciliation.','source_completeness':'not_verified','outstanding_checks':target['unresolved_questions'],'legacy_record':{},'review_run':'fnano-counterparts-2018','date':L.DATE,'revision_history':[]},'Document main-methods lattice statement while retaining source verification gate')
 for did in ['D026','D027']:
  d=next(d for d in L.read('design_evidence') if d['design_id']==did)
  if d.get('review_run'):continue
  d.update(review_run='fnano-counterparts-2018',evidence=[ev],source_completeness='not_verified',outstanding_checks=target['unresolved_questions'],core_variant_composition='Article distinguishes base platform, 36-helix hinge arms and 56-helix lever/rotor parts; SI combinations not reconciled.')
  L.upsert('design_evidence',d,'Retain existing design IDs and inspect component descriptions')
 print(L.validate())

if __name__=='__main__':main()
