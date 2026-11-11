"""Primary pScaf review and explicit publisher-deposited version reconciliation."""
import json,csv
import ledger as L
from review_batch_0001 import evidence

def main():
 doi='10.1093/synbio/ysy015';pre='10.1101/309682';base=L.ROOT/'assets/research-20261105'
 ev=evidence(L.ROOT/'assets/sources/PMC6461039.xml','https://pmc.ncbi.nlm.nih.gov/articles/PMC6461039/','XML publication date; Methods2.4; Results3.2–3.3/Fig4; Availability')
 pe=evidence(base/'10.1101_309682.json','https://api.crossref.org/works/10.1101/309682','message.relation.is-preprint-of; author list and published date')
 p=next(r for r in L.read('publication_reviews') if r['registry_key']==doi)
 if p['run_id']=='bootstrap-20261105':
  p.update(review_stage='fulltext_reviewed',relevance='design_bearing',design_contributions=['new_design','modified_design'],catalog_eligibility='unresolved',evidence=[ev],rationale='Six custom scaffolds1512–10080nt are experimentally folded into brick-like objects. Three smaller scaffolds are separately folded into6HB nanotubes and combined with or without connector staples into trimer assemblies. Fig4 and Results distinguish these components; scaffold method alone does not define a single design.',unresolved_questions=['Verify each6HB core, scaffold sequence and connector-staple combination against pinned repository source files.','Apply narrower catalog morphology rules individually to six brick-like objects and6HB components; no blanket eligibility promotion.'],reviewer='Codex primary Methods/Results inspection',access='partial',run_id='pscaf-source-review',date=L.DATE,date_evidence={'date':'2018-08-09','source':ev,'primary_verified':True,'meaning':'XML publication date'})
  L.upsert('publication_reviews',p,'Inspect actual origami experiments and source availability')
 for key in [doi,pre]:
  r=next(r for r in L.read('publication_reviews') if r['registry_key']==key)
  r['canonical_work_id']='work:'+doi;r['canonical_work_status']='version_relation_verified_crossref';r['version_links']=[{'relation':'has_preprint' if key==doi else 'is_preprint_of','target_key':pre if key==doi else doi,'evidence':pe,'scope':'Publication version identity; design content equivalence not independently checked'}]
  if key==pre and r['review_stage']=='unreviewed':r.update(review_stage='metadata_screened',publication_type=['preprint'],relevance='uncertain',evidence=[pe],rationale='Publisher-deposited Crossref relation explicitly identifies journal version; preprint design contents have not been separately inspected.',reviewer='Codex deposited version metadata inspection',run_id='pscaf-version-review',date=L.DATE,date_evidence={'date':'2018-04-27','source':pe,'primary_verified':False,'meaning':'Crossref deposited preprint publication date'},unresolved_questions=['Inspect preprint and revisions to establish which design/source details were public at each date.'],access='partial')
  L.upsert('publication_reviews',r,'Reconcile explicit is-preprint-of relation while retaining separate publication versions and dates')
 L.upsert('discovery_edges',dict(edge_id='version:'+pre+':'+doi,source_key=pre,target_key=doi,relation='is_preprint_of',evidence_url=pe['url'],local_file=pe['local_file'],sha256=pe['sha256'],locator=pe['locator'],reconciliation_state='explicit_crossref_relation',run_id='pscaf-version-review',date=L.DATE),'Record explicit version identity, not title similarity')
 inventory=list(csv.DictReader((L.ROOT/'expansion_repository_files.csv').open()));audit=[]
 for did,size in [('S008',1512),('S009',2268),('S010',3024)]:
  files=[f for f in inventory if f['doi']==doi and f'6hb-{size}.' in f['path']];refs=[]
  for f in files:
   path=L.ROOT/'assets'/f['local_file'];refs.append(evidence(path,f['url'],'Pinned author repository member '+f['path']))
   if path.suffix=='.csv':
    rows=list(csv.DictReader(path.open()));bad=[i+2 for i,r in enumerate(rows) if len(r['Sequence'])!=int(r['Length'])];audit.append({'design_id':did,'source':str(path.relative_to(L.ROOT)),'rows':len(rows),'length_mismatch_rows':bad,'scope':'Length-field consistency only; not sequence-to-routing or scaffold-completeness proof'})
  d=next(d for d in L.read('design_evidence') if d['design_id']==did);d.update(review_run='pscaf-source-review',evidence=[ev],source_files=refs,source_completeness='not_verified',core_variant_composition=f'{size}nt6HB core source and staple CSV retained at pinned commit. Connector staples for trimer must be separately reconciled.',outstanding_checks=p['unresolved_questions']);L.upsert('design_evidence',d,'Attach inspected source inventory and explicitly limited CSV consistency audit')
 d=next(d for d in L.read('design_evidence') if d['design_id']=='S011');d.update(review_run='pscaf-source-review',evidence=[ev],source_completeness='not_verified',core_variant_composition='Three6HB scaffold/staple sets tested with and without connectors. Assembly is distinct from isolated components.',outstanding_checks=p['unresolved_questions']);L.upsert('design_evidence',d,'Inspect trimer assembly experiment while retaining connector source gap')
 L.atomic(L.HERE/'pscaf_source_audit.json',json.dumps(audit,indent=2))
 for c in [r for r in L.read('publication_reviews') if r.get('run_id') in ['fnano-2017','fnano-2018'] and 'phage' in r.get('title','').lower() and r['authors'][0]=='Parsa Nafisi']:
  L.upsert('discovery_edges',dict(edge_id='possible_counterpart:'+c['registry_key']+':'+doi,source_key=c['registry_key'],target_key=doi,relation='possible_journal_counterpart',evidence_url=ev['url'],local_file=ev['local_file'],sha256=ev['sha256'],locator='Primary pScaf abstract/Results compared with conference title and author group',reconciliation_state='pending_conference_abstract_confirmation',run_id='pscaf-source-review',date=L.DATE),'Preserve likely conference relation without merging or backdating source availability')
 print(L.validate())
if __name__=='__main__':main()
