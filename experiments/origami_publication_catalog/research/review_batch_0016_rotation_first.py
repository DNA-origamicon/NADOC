"""Full-text exclusions/analogy screening from low-keyword2006 rotation."""
import re,html,subprocess
import ledger as L
from review_batch_0001 import evidence

def main():
 base=L.ROOT/'assets/research-20261105';rid='B0016';g='10.1209/epl/i2006-10302-7';c='10.1529/biophysj.106.098699'
 ge=evidence(base/'olympic-gels2006.pdf','https://home.csulb.edu/~gpickett/epl9633.pdf','All7pages text inspected; PDF2 Simple model and PDF7 conclusion/references. PDF1 explicit online25October2006.')
 ce=evidence(base/'chromatin2006.html','https://pmc.ncbi.nlm.nih.gov/articles/PMC1783869/','Complete commentary body and8references; final paragraph uses origami as a speculative analogy, not an experiment.')
 entries=[(g,ge,'not_origami',['journal-article'],'Theory of flexible polymer melts end-decorated with complementary DNA ligands; Simple model PDF2 specifies a flexible central polymer chain with two short DNA end tags. Ring-closing competes with interchain joining. No scaffold-and-staple origami design or reused origami structure is modeled. DNA-origami is used broadly for sequence-specific interaction sites; ref11 cites Rothemund2006 as background. Figure4 is a speculative interlocking-ring membrane/paper model, not a documented DNA-origami design. Exclude from accepted design catalog while retaining theoretical adjacent-literature and citation evidence.'),(c,ce,'background_or_review',['Comment'],'Complete short commentary discusses nucleosome/chromatin polymer physics and summarizes T4genome compaction/transcription using cationic nanoparticles in Zinchenko et al. The last paragraph speculates that RNA could crosslink genomic DNA and cites Rothemund as analogy. No origami structure is constructed, modified or reused; no experimental methods/source set is supplied by this commentary. Preserve as background citation lead, exclude from design-bearing catalog.')]
 for key,ev,rel,typ,note in entries:
  p=next(p for p in L.read('publication_reviews') if p['registry_key']==key)
  if ev not in p['evidence']:p['evidence'].append(ev)
  p.update(title=p['legacy_record']['publication'],publication_type=typ,review_stage='fulltext_reviewed',relevance=rel,design_contributions=[],catalog_eligibility='excluded',access='main_available',rationale=note,reviewer='Codex complete full-text review',run_id=rid,date=L.DATE,unresolved_questions=['Reconcile all retained references; exclusion applies to this publication, not to cited original designs.'])
  if key==g:p['date_evidence']=dict(date='2006-10-25',source=ev,primary_verified=True,meaning='Explicit first-online date on author-hosted publisher PDF; issue15November2006.')
  L.upsert('publication_reviews',p,'Full-text audit distinguishes scaffolded origami from DNA-end-tag polymer theory and chromatin analogy')
 text=subprocess.check_output(['pdftotext','-layout',str(base/'olympic-gels2006.pdf'),'-']).decode().split('REFERENCES',1)[1]
 refs=re.findall(r'(?ms)^\s*\[(\d+)\]\s*(.*?)(?=^\s*\[\d+\]|\Z)',text);assert [int(n) for n,_ in refs]==list(range(1,15))
 allrefs=[(g,'olympic',ge,n,' '.join(t.split()),'10.1038/nature04586' if n=='11' else 'citation:olympic:'+n) for n,t in refs]
 raw=(base/'chromatin2006.html').read_text();refs=re.findall(r'<li id="bib(\d+)">(.*?)</li>',raw,re.S);assert len(refs)==8
 for n,t in refs:
  title=re.search(r'<cite>(.*?)</cite>',t,re.S).group(1);doi=re.search(r'href="https://doi.org/([^"]+)"',t)
  allrefs.append((c,'chromatin',ce,n,html.unescape(re.sub('<[^>]+>','',title)),html.unescape(doi.group(1)).lower() if doi else 'citation:chromatin:'+n))
 for key,prefix,ev,n,t,target in allrefs:
  L.upsert('discovery_edges',dict(edge_id='B0016:'+prefix+':ref'+n,source_key=key,target_key=target,relation='cites',citation=t,evidence_url=ev['url'],local_file=ev['local_file'],sha256=ev['sha256'],locator='Reference'+n,reconciliation_state='pending_identity_date_scope_reconciliation',run_id=rid,date=L.DATE),'Retain all citations including submitted2006Pickett lead without assuming publication')
 b=next(b for b in L.read('batches') if b['batch_id']==rid)
 b['completed_actions'].append('Reviewed2of25: Olympic-gel polymer theory excluded as not scaffolded origami; chromatin commentary retained as background and excluded from design catalog. Read full texts; preserved14+8references.')
 b.update(after_counts=L.counts(),validation=[L.validate()],exclusion_audit=dict(sample=[g,c],reason='All exclusions in this partial batch audited against entire main text, including models/conclusion/reference context; no keyword-only decisions.'),next_queue=['Review remaining23B0016 inputs including acquiredACS SI and low-keyword review/conference records.','Reconcile Pickett submitted2006reference12 and other retained citations; no conference-search expansion.','Human dissertation request remains pending; independent sources unblocked.'])
 L.upsert('batches',b,'Save2of25 rotating full-text reviews; batch remains in progress')
 print(L.validate())
if __name__=='__main__':main()
