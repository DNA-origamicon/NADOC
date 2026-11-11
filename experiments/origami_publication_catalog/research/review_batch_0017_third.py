"""Evidence-supported exclusion of an educational paper-folding DNA model."""
import ledger as L
from review_batch_0001 import evidence

def main():
 k='10.55838/1980-3540.ge.2007.32';rid='B0017';a=L.ROOT/'assets/research-20261105'
 ev=evidence(a/'sepel2007-paper.pdf','https://geneticanaescola.com/revista/article/download/32/26','Entire3-page article text and Figures1-4 captions read, printed3-5; classroom activities specify printed paper, base-letter completion and mountain/valley folding. Figure images and linked teaching templates not independently audited.')
 date=evidence(a/'sepel2007-publisher.html','https://geneticanaescola.com/revista/article/view/32','Publisher displayed publication date and DC.Date.issued/citation_date:2007-03-15; title,authors,abstract andPDFlink match acquired paper.')
 note='Educational physical model of the DNA double helix made by folding printed paper. Classroom activities ask students to fill base letters and fold mountain/valley creases; right/left-handed paper models illustrate secondary structure. No DNA-strand self-assembly or molecular origami designs reported. Authors adapt Yen1995 and dnai.org teaching materials, moving base labels inside and backbone labels to sides. Broad not_origami and narrow catalog excluded; no design group. Linked origami de DNA.pdf,modP&B.pdf,origamiDNA.pdf are teaching instructions/templates, not molecular staple supplements; not acquired in this review.'
 p=next(x for x in L.read('publication_reviews') if x['registry_key']==k)
 p.update(review_stage='fulltext_reviewed',relevance='not_origami',design_contributions=[],catalog_eligibility='excluded',access='main_PDF_and_publisher_HTML_available',rationale=note,reviewer='Codex complete article text and exclusion audit',run_id=rid,date=L.DATE,unresolved_questions=['Three bibliography records retained as leads; primary identities not yet reconciled. Teaching templates not acquired; article activities provide direct material/scope evidence.'])
 for e in [ev,date]:
  if e not in p['evidence']:p['evidence'].append(e)
 p['date_evidence']=dict(date='2007-03-15',primary_verified=True,source=date,meaning='Publisher displayed publication date and issued metadata agree; PDF issue2007.')
 L.upsert('publication_reviews',p,'Exclude paper-folding pedagogy using full article activities, not keyword screening')
 refs=['Loreto,E.L.S.;Sepel,L.M.N. Atividades Experimentais e Didáticas de Biologia Molecular e Celular. São Paulo,SBG,2003,2ed.','Watson,J.D. A dupla hélice. Lisboa,Gradiva,1987.','Yen,T. Make your own DNA. Trends in Biochemical Sciences20:94,1995.']
 for n,c in enumerate(refs,1):
  L.upsert('discovery_edges',dict(edge_id=f'B0017:sepel2007:{n}',source_key=k,target_key=f'citation:sepel2007:{n}',relation='cites',citation=c,evidence_url=ev['url'],local_file=ev['local_file'],sha256=ev['sha256'],locator=f'PDF3 bibliography item{n}',reconciliation_state='pending_identity_date_scope_reconciliation',run_id=rid,date=L.DATE),'Retain entire three-item bibliography of excluded article')
 b=next(x for x in L.read('batches') if x['batch_id']==rid)
 action='Processed3of25:2substantive reviews plus1metadata-only. Sepel2007 excluded as paper-folding pedagogy from full article;3references retained.'
 if action not in b['completed_actions']:b['completed_actions'].append(action)
 if k not in b['exclusion_audit']['sample']:b['exclusion_audit']['sample'].append(k)
 b['exclusion_audit']['reason']+=' Sepel2007: all three pages inspected; classroom paper and crease instructions establish non-molecular material, no molecular design claim.'
 b.update(after_counts=L.counts(),validation=[L.validate()],next_queue=['Next balanced inputs epmc:1842 and epmc:1391 patent identity/content reconciliation;22untouched B0017 inputs.','epmc:1391 title search suggests Shih/Douglas/Chou WO2007127020A2 family; compare source identity/dates before linking, legacy2007-04-03 unverified.','Rothemund remainingSI/citations; EBSA2007actualPDF; priority author discovery; FNANO deferred.'])
 L.upsert('batches',b,'Save3of25processed and evidence-supported exclusion audit')
 print(L.validate())

if __name__=='__main__':main()
