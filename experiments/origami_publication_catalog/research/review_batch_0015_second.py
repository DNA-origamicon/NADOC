"""Inspect image-only sequence table before classifying tetrahedron paper."""
import json
import ledger as L
from review_batch_0001 import evidence

def main():
 key='10.1021/acs.analchem.8b05407'
 p=next(p for p in L.read('publication_reviews') if p['registry_key']==key)
 e=evidence(L.ROOT/'assets/sources/acs-expansion-20261104/14448869-ac8b05407_si_001.pdf','https://ndownloader.figshare.com/files/14448869','SI S1–S9 text; Table S1 S3–S4 visually inspected from rendered PDF pages; Fig S2 stability text')
 if e not in p['evidence']:p['evidence'].append(e)
 p.update(title=p['legacy_record']['publication'],review_stage='design_sources_reviewed',relevance='not_origami',design_contributions=[],catalog_eligibility='excluded',access='partial',rationale='SI reports DNA tetrahedra as enzyme-cascade scaffolds. Image-only Table S1 was visually inspected: TDN13,TDN17,TDN26,TDN30 have a–d oligo sets; TDN37 has a–h. These short-oligo tetrahedral constructs do not establish origami scaffold/staple folding. Fig S2 describes GOx-S1/HRP-S2/GOx-S3/HRP-S4 attachment at four pendant vertex sequences on TDN30. Enzyme loading and methylene-blue/glucose optimization are assay conditions. Same-agent exclusion audit used actual sequence-table images plus stability methods, not title alone. Main article not inspected; citation followups remain pending.',unresolved_questions=['Inspect main article for any additional origami objects or explicit reuse not established in SI.','Enumerate references and follow relevant citation routes.'],reviewer='Codex SI text and rendered Table S1 inspection; same-agent exclusion audit',run_id='B0015',date=L.DATE)
 L.upsert('publication_reviews',p,'Record tetrahedron sequence-set evidence with image-table inspection')
 b=next(b for b in L.read('batches') if b['batch_id']=='B0015')
 b['completed_actions'].append('Fourth input inspected: ac8b05407 SI, including image-only sequence table; nonorigami exclusion audited.')
 b.update(after_counts=L.counts(),validation=[L.validate()],next_queue=['Resume10.1021/acs.biochem.9b00057; remaining11ACS and10rotating2015 records','FNANO2010 enumeration;234pending Hao Yan CV identities; source and citation followups'])
 L.upsert('batches',b,'Save4of25 first passes with remaining queue')
 L.atomic(L.HERE/'batch_0015_second_audit.json',json.dumps(dict(reviewed_keys=[key],first_pass_count=4,input_count=25,exclusion_audit='Same agent visually inspected Table S1 S3–S4 and read Fig S2 methods; main article pending',validation=L.validate(),counts=L.counts()),indent=2)+'\n')
 print(L.validate())
if __name__=='__main__':main()
