"""B0004 rotating records: explicit metadata-only decisions, no final exclusions."""
import json
import ledger as L
from review_batch_0001 import evidence

NOTES={
'10.1039/c0cc01167c':'Deposited title concerns three-helix blunt-end stacking. Title cannot establish whether an origami scaffold is involved; primary methods needed.',
'10.1073/pnas.1001454107':'Deposited abstract describes mechanical unzipping and base-pair thermodynamics, not an origami experiment. Retain uncertainty until methods/SI are inspected before final exclusion.',
'10.1117/12.848392':'Crossref identifies proceedings-article, with title addressing origami adhesion to patterned silicon. Preserve conference/proceedings type; no complete design established.',
'10.1146/annurev-biochem-060308-102244':'Abstract surveys branched DNA, crystals and nanomechanical devices; accessible original design reuse must be checked before a final background-only exclusion.',
'10.1149/ma2010-01/25/1250':'Deposited abstract explicitly says abstract not available. Meeting Abstracts container and origami-metallization title are conference leads, not proof of a complete design.',
'10.1039/c0cc00044b':'Deposited title reports reversible protein patterning on origami; no abstract or methods reviewed, so retain uncertain relevance at metadata stage.',
'10.3724/sp.j.1095.2010.90384':'Deposited title suggests a review of DNA origami; no body inspected, so no final background-only exclusion.',
'10.1002/anie.201005911':'Crossref date 2010-11-04 differs from PubMed 2011 issue year; retain first-online verification as separate question. Publisher-deposited title alone does not complete design review.'}

def main():
 for r in L.read('publication_reviews'):
  k=r['registry_key']
  if k not in NOTES or r.get('run_id')!='bootstrap-20261105':continue
  p=L.ROOT/'assets/research-20261105'/(k.replace('/','_')+'.json');m=json.loads(p.read_text())['message'];ev=evidence(p,'https://api.crossref.org/works/'+k,'message.title/type/abstract/published/container-title')
  r.update(review_stage='metadata_screened',relevance='uncertain',catalog_eligibility='unresolved',design_contributions=['uncertain'],evidence=[ev],rationale=NOTES[k],unresolved_questions=['Retrieve and inspect primary body, methods and supplementary context; establish first-online date and version relationships.'],access='partial',reviewer='Codex metadata inspection',run_id='B0004',date=L.DATE)
  if k=='10.1117/12.848392':r['publication_type']=['proceedings_article']
  if k=='10.1149/ma2010-01/25/1250':r['publication_type']=['conference_abstract']
  L.upsert('publication_reviews',r,'B0004 rotating metadata screen; preserve unresolved cases')
 print(L.validate())

if __name__=='__main__':main()
