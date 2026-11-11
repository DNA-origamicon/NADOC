"""Upgrade two B0004 records from primary abstracts to inspected design sources."""
import json
import ledger as L
from review_batch_0001 import evidence

def main():
 root=L.ROOT/'assets/research-20261105';manifest=json.loads((root/'acquisition.json').read_text())
 for key,name,loc,note,questions in [
 ('epmc:1320','lally-thesis.pdf','PDF p.1; pp.171–172 (printed161–162), pp.209–214 (printed199–204), sections3.4.2–3.4.3 and B.1','Parminder Lally thesis documents a 960nt small tile with 30 staples and a full-M13 minimum-twist tile designed by Shelley Wickham. The latter deletes six bases per helix; source gives distinct core and modified staple sets, including 4/6/8nt sticky-end controls.','Inspect complete Appendix B, routing figures and source images; verify all base strings, replacement combinations, author/journal relationships and first public availability.'),
 ('10.1038/nnano.2010.5','nnano20105-si.pdf','PDF p.8 assembly and refs8–9; pp.31,33 cleavage schematic description/list; pp.37–38 bond-forming schematic/list','SI explicitly uses the tall rectangular template with Rothemund numbering. Separate cleavage and bond-forming designs contain core, index, merged and chemically modified strands; two distinct sequence sections are provided.','Reconcile every core/merged/modified strand with both diagrams and conditions; inspect source images because text extraction emits font warnings. Main article body remains preview-only.')]:
  r=next(r for r in L.read('publication_reviews') if r['registry_key']==key)
  ev=evidence(root/name,manifest[name]['url'],loc)
  if not any(e.get('local_file')==ev['local_file'] for e in r['evidence']):
   r.update(review_stage='design_sources_reviewed',design_contributions=['reused_design','modified_design'],rationale=note,unresolved_questions=[questions],evidence=r['evidence']+[ev])
   if key=='epmc:1320':r['authors']=[{'name':'Parminder Lally','source':ev}]
   L.upsert('publication_reviews',r,'Inspect acquired primary design source; retain unresolved completeness and date gaps')
 r=next(r for r in L.read('publication_reviews') if r['registry_key']=='epmc:1320');ev=r['evidence'][-1]
 for did,name,composition,loc in [
 ('RDE0003','Lally 960nt small tile','960nt segment of M13mp18; ten rows of 96nt and thirty32nt staples; separate unmodified and FRET/click staple sets.','Appendix B.1.1, PDFpp209–213'),
 ('RDE0004','Wickham minimum-twist tile used in Lally thesis','Full M13mp18; six deletions per helix described; modified positions2/5 and4/6/8nt sticky-end sets.','Section3.4.2 PDFp171 and Appendix B.1.2 PDFpp213–214 onward')]:
  if any(d['design_id']==did for d in L.read('design_evidence')):continue
  de={**ev,'locator':loc}
  L.upsert('design_evidence',{'design_id':did,'publication_keys':['epmc:1320'],'named_objects':[name],'variant_links':[],'relationships':[{'relation':'documented_in','target_key':'epmc:1320','evidence':de}],'lattice_decision':'unresolved_filled_planar_design_description; inspect_routing','catalog_eligibility':'unresolved','evidence':[de],'source_files':[de],'core_variant_composition':composition,'source_completeness':'not_verified','outstanding_checks':r['unresolved_questions'],'legacy_record':{},'review_run':'B0004','date':L.DATE,'revision_history':[]},'Record two separately described thesis design groups without map promotion')
 pubs={r['registry_key']:r for r in L.read('publication_reviews')};existing={e['edge_id'] for e in L.read('discovery_edges')}
 for source,target,relation,loc in [
 ('epmc:1320','10.1038/nature04586','uses_method_from','Appendix B.1 PDFp209 explicitly identifies foundation'),
 ('10.1038/nnano.2010.5','10.1038/nature04586','reuses_design_from','SI p.8 ref8 and pp31–38 original tall-rectangle numbering'),
 ('epmc:1320','10.1038/nnano.2010.5','cites','Thesis PDFpp128–130 review of Voigt work; distinct from own Chapter3 experiments')]:
  eid=relation+':'+source+':'+target
  if eid in existing:continue
  e=pubs[source]['evidence'][-1]
  L.upsert('discovery_edges',{'edge_id':eid,'source_key':source,'target_key':target,'relation':relation,'evidence_url':e['url'],'local_file':e['local_file'],'sha256':e['sha256'],'locator':loc,'reconciliation_state':'publication_link_supported; exact_variant_pending','run_id':'B0004','date':L.DATE},'Record explicit source reference; no unproven version merge')
 b=next(b for b in L.read('batches') if b['batch_id']=='B0004');b['after_counts']=L.counts();b['validation']=[L.validate()];b['next_queue']=['Complete Lally Appendix B source/routing verification; reconcile Wickham credit and journal counterparts.','Complete tall-rectangle variant combinations in Voigt SI.','Review eight metadata-only B0004 records and source gaps in fifteen ACS records.','Continue forward identifiers, conference programs and author bibliography routes.'];L.upsert('batches',b,'Save follow-up source inspection after B0004 first-pass screening')
 print(L.validate())

if __name__=='__main__':main()
