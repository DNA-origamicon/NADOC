"""Primary abstract evidence and stable identity resolution for two rotating records."""
import json
import ledger as L
from review_batch_0001 import evidence

def main():
 root=L.ROOT/'assets/research-20261105'
 specs={
 'epmc:1320':('lally-thesis-ora.html','https://ora.ox.ac.uk/objects/uuid%3A26573255-79bc-482d-9dd9-8c9f771ccbd8','Repository abstract and Bibliographic Details; publication 2010, deposit 2012-04-18','Repository abstract explicitly reports Chapter 3 use of a 2D origami tile, functionalized surface strands and experimentally templated reactions. Thesis is design-bearing even though its title lacks origami.','Inspect Chapter 3 methods and sequence appendices, determine parent geometry and journal overlap, and distinguish thesis award date from first public availability.'),
 '10.1038/nnano.2010.5':('nnano20105.html','https://www.nature.com/articles/nnano.2010.5','Publisher abstract, publication date and supplementary-information link','Publisher abstract reports locally addressed cleavage and bond-forming reactions on an origami scaffold with AFM observation. The main body is subscription preview, while a public supplement link is provided.','Inspect supplement methods, modified strands and template source; main article body remains inaccessible in this fetch.')}
 for r in L.read('publication_reviews'):
  k=r['registry_key']
  if k not in specs or r.get('run_id')!='bootstrap-20261105':continue
  name,url,loc,note,q=specs[k];ev=evidence(root/name,url,loc)
  r.update(review_stage='metadata_screened',relevance='design_bearing',catalog_eligibility='unresolved',design_contributions=['modified_design'],evidence=[ev],rationale=note,unresolved_questions=[q],access='partial',reviewer='Codex primary abstract inspection',run_id='B0004',date=L.DATE)
  if k=='epmc:1320':
   r.update(doi='10.5287/ora-n6xorgb1j',authors=[{'name':'P. Lally','source':ev}],publication_type=['doctoral_thesis'],identity_evidence=[ev])
   r['date_evidence']={'date':'2010','source':ev,'primary_verified':True,'meaning':'Repository-stated thesis publication/award year; first public availability not verified','repository_deposit_date':'2012-04-18'}
  else:r['date_evidence']={'date':'2010-02-28','source':ev,'primary_verified':True,'meaning':'Publisher first published date'}
  L.upsert('publication_reviews',r,'Inspect primary abstracts and preserve stable no-DOI key while adding repository DOI')
 b=next(b for b in L.read('batches') if b['batch_id']=='B0004')
 if b['status']=='in_progress':
  b.update(status='completed',after_counts=L.counts(),validation=[L.validate()],completed_actions=b['completed_actions']+['Inspected eight rotating deposited metadata records and two primary repository/publisher abstracts.','Resolved thesis epmc:1320 to P. Lally, Oxford, 2010, DOI 10.5287/ora-n6xorgb1j; stable key retained.'],exclusion_audit={'sample':[],'reason':'No final publication or catalog exclusions in this batch.'},next_queue=['Inspect acquired Lally thesis Chapter 3 and chemistry supplement when retrieval finishes.','Resolve eight metadata-only bodies and source gaps for all 15 ACS papers.','Continue 291 unmatched forward targets, other FNANO years and author bibliographies.'])
  L.upsert('batches',b,'Complete first-pass B0004 screening; design/source checks remain open')
 print(L.validate())

if __name__=='__main__':main()
