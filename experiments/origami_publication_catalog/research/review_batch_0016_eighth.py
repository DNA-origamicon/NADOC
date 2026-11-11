"""Diastereomer SI audit with literal unresolved bases preserved."""
import json,re,subprocess
from collections import Counter
import ledger as L
from review_batch_0001 import evidence

def main():
 k='10.1021/acsnano.9b06734';rid='B0016';path=L.ROOT/'assets/sources/acs-expansion-20261104/17811194-nn9b06734_si_001.pdf'
 se=evidence(path,'https://ndownloader.figshare.com/files/17811194','All16pages extracted text read; PDF2routing,PDF12ambiguous sequence andPDF15capture/switching table visually inspected. Main article not acquired.')
 cp=L.ROOT/'assets/research-20261105/diastereomer-crossref.json';ce=evidence(cp,'https://api.crossref.org/works/10.1021/acsnano.9b06734','Publisher-deposited metadata:44references and September24online date; differs from current ACS history/PubMedSeptember26.')
 text=subprocess.check_output(['pdftotext','-layout',str(path),'-']).decode();rows=[];table=None
 for page,t in enumerate(text.split('\f'),1):
  for line in t.splitlines():
   m=re.search(r'Table S([2-7])\.',line)
   if m:table=int(m[1])
   m=re.match(r'\s*(\d+\[\d+\])\s+(\d+\[\d+\])\s+([ACGT?]+)\s+(\d+)\s*$',line)
   if m:
    start,end,seq,n=m.groups();rows.append(dict(table='S'+str(table),pdf_page=page,start=start,end=end,sequence_literal=seq,stated_length=int(n),literal_character_count=len(seq),unknown_characters=seq.count('?')))
 counts=dict(Counter(x['table'] for x in rows));assert counts=={'S2':126,'S3':23,'S4':12,'S5':12}
 assert all(x['literal_character_count']==x['stated_length'] for x in rows)
 unknown=[x for x in rows if x['unknown_characters']];assert len(unknown)==1 and unknown[0]['unknown_characters']==2
 L.atomic(L.HERE/'diastereomer_sequence_index.json',json.dumps(dict(evidence=se,row_counts=counts,rows=rows,limitations='Only TablesS2-S5. Literal32characters in one row include two unknown question marks, visually confirmed in PDF. TableS7 wrapped and bold functional domains not reconstructed. Capture extensions and complete variant mixtures unresolved. Not a certified synthesis set.'),indent=2)+'\n')
 note='SI p2 specifies p8064 scaffold and caDNAno routing. Cross-section shows honeycomb placement of plate helices10-55 and arm0-9, plus auxiliary57; auxiliary routing role and exact activehelix count not certified. TablesS2-S5 yield173 coordinate-keyed rows:126plate,23arm,12armcapture,12platecapture. All extracted literal character counts match printed lengths, but plate33[147]to35[150] reads ACTTTTTCATGA??GAGGGTAGCAACGGGAAA (32characters including two literal question marks), confirmed visuallyPDF12. TableS6 supplies three separate thiolated AuNR DNA strands. TableS7 gives three chiral-center switching systems with distinct L/R functional strands and blocker/activator fuels. TableS1 traces two reconfiguration paths through L/R/O states; observed configurations and AuNR dimers/trimers/tetramers must not be counted automatically as independent core designs. Complete core/capture-extension/switch replacement recipe, assembly stoichiometry, parent attribution and native source remain unverified without main article.'
 qs=['Acquire main article through public author/repository or CU browser route; paced ACS PDF attempt returned403, not proof of missing entitlement. Exact-title search found publisher/PubMed metadata but no public original PDF.','Resolve literal?? in plate33[147]to35[150] using authoritative correction/native sequence; do not infer bases.','Audit nativecaDNAno and auxiliaryhelix57; map plate/arm scaffold connection and source identities.','Reconcile capture extensions,TableS6 coating sequences and TableS7 wrapped/bold domains into each actual variant mixture.','Reconcile September24Crossref versus September26publisherhistory/PubMed first-online date; both2019.','Determine whole-object narrow catalog eligibility; honeycomb component layout alone does not certify source eligibility.','Review main bibliography and parent relationships;44Crossref references retained as metadata leads.']
 p=next(p for p in L.read('publication_reviews') if p['registry_key']==k)
 p.update(review_stage='design_sources_reviewed',relevance='design_bearing',design_contributions=['new_design','modified_design'],catalog_eligibility='unresolved',access='SI_available; main_PDF403; public_alternatives_pending',rationale=note,reviewer='Codex complete SI text and selected figure/table visual review',run_id=rid,date=L.DATE,unresolved_questions=qs)
 for e in [se,ce]:
  if e not in p['evidence']:p['evidence'].append(e)
 p['date_evidence'].update(primary_verified=False,crossref_online='2019-09-24',publisher_history_online='2019-09-26',publisher_history_url='https://pubs.acs.org/doi/10.1021/acsnano.9b06734',meaning='ACS banner/CrossrefSeptember24 differs from explicit published-onlineSeptember26; exactdate pending,pre2020 unaffected.')
 L.upsert('publication_reviews',p,'Review switching platform sources and preserve literal unresolved bases')
 did='RDE0061';old=next((d for d in L.read('design_evidence') if d['design_id']==did),None);assert old is None or k in old['publication_keys']
 L.upsert('design_evidence',dict(design_id=did,publication_keys=[k],named_objects=['p8064 plate-arm switching platform','AuNR dimer/trimer/tetramer assemblies with up to three chiral centers'],identity_status='Source group; exact platform variants and assemblies awaiting main-text reconciliation',lattice_decision='Honeycomb arrangement visible in caDNAno cross-section; plate10-55 and arm0-9 plus auxiliary57. Whole-object/source eligibility unresolved.',catalog_eligibility='unresolved',core_variant_composition=note,relationships=[],variant_links=[],source_completeness='not_verified; literal_unknown_bases',source_files=[se],evidence=[se,ce],outstanding_checks=qs,review_stage='source_reviewed',review_run=rid,run_id=rid,date=L.DATE,legacy_record={}), 'Record sourcegroup and explicit incomplete sequence,not complete synthesis set')
 refs=json.loads(cp.read_text())['message']['reference'];assert len(refs)==44
 for i,ref in enumerate(refs,1):
  L.upsert('discovery_edges',dict(edge_id='B0016:diastereomer:ref'+str(i),source_key=k,target_key=ref.get('DOI','citation:diastereomer:'+str(i)).lower(),relation='cites',citation=json.dumps(ref,ensure_ascii=False),evidence_url=ce['url'],local_file=ce['local_file'],sha256=ce['sha256'],locator='Crossref reference'+str(i),reconciliation_state='pending_identity_date_scope_reconciliation',run_id=rid,date=L.DATE),'Retain44publisher-deposited references,main bibliography not read')
 b=next(b for b in L.read('batches') if b['batch_id']==rid);action='Reviewed10of25: plasmonic diastereomer SI,173coordinate-keyed rows indexed; two literal unknown bases visually confirmed,44metadata references retained. Main and complete variant sources pending.'
 if action not in b['completed_actions']:b['completed_actions'].append(action)
 b.update(after_counts=L.counts(),validation=[L.validate()],next_queue=['Remaining15B0016inputs; next10.1021/acsnano.9b03473 downloadedSI.',*qs]);L.upsert('batches',b,'Save10of25progress and sourceambiguity audit');print(L.validate())
if __name__=='__main__':main()
