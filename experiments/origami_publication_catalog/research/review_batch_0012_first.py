"""Evidence-supported paper-origami false-positive screening and exclusion audit."""
import ledger as L
from review_batch_0001 import evidence

def main():
 key='10.1021/acssensors.7b00825';p=next(p for p in L.read('publication_reviews') if p['registry_key']==key)
 main=evidence(L.ROOT/'assets/research-20261105/yang-2018-paper-origami-main.pdf','https://eprints.gla.ac.uk/155194/7/155194.pdf','Accepted manuscript: Abstract/Introduction/Fig1; Experimental Paper-origami devices and DNA extraction; second-pass Results paper device and Conclusion')
 si=evidence(L.ROOT/'assets/sources/acs-expansion-20261104/10391871-se7b00825_si_002.pdf','https://ndownloader.figshare.com/files/10391871','Entire six-page SI text: LAMP primer TableS1, PCR methods and FigsS1–S5 captions; movie not reviewed')
 meta=evidence(L.HERE/'batch_0012_paper_primary.json','https://pubmed.ncbi.nlm.nih.gov/29322764/','PubMed and publisher explicit online2018-02-05; publisher header/Glasgow date2018-01-11 matches acceptance, repository availability separate')
 p.update(title=p['legacy_record']['publication'],publication_type=['journal_article'],review_stage='fulltext_reviewed',relevance='not_origami',design_contributions=['uncertain'],catalog_eligibility='excluded',access='partial',evidence=p.get('evidence',[])+[e for e in [main,si,meta] if e not in p.get('evidence',[])],rationale='Device consists of folded filter-paper panels, wax-printed channels, plastic LAMP chambers and glass-fibre DNA capture disk. DNA is extracted pathogen genomic analyte and amplification primers, not a self-assembled structural scaffold. Methods specify physical paper folding; Results/Conclusion independently confirm paper diagnostic workflow. This is a supported paper-origami title false positive, not a lattice exclusion of a DNA design. SI sequences are LAMP primers, not origami staples.',unresolved_questions=['No DNA-origami design evidence found in inspected main sections/SI; full bibliography and movie remain unreviewed.'],date_evidence={'date':'2018-02-05','meaning':'Explicit publisher online date and PubMed Epub; January11is acceptance in publisher history, repository labels conflict','source':meta,'primary_verified':True},reviewer='Codex primary main/SI review with separate exclusion pass',run_id='B0012',date=L.DATE)
 L.upsert('publication_reviews',p,'Exclude physical-paper origami after inspectable primary-methods and results audit')
 b=next(b for b in L.read('batches') if b['batch_id']=='B0012')
 action='Screened acssensors7b00825 from main/SI; physical paper-folding false positive, exclusion second-pass Methods/Results/Conclusion.'
 if action not in b['completed_actions']:b['completed_actions'].append(action)
 pubs={p['registry_key']:p for p in L.read('publication_reviews')}
 b.update(after_counts=L.counts(),unresolved_keys=[k for k in b['input_keys'] if pubs[k]['review_stage']=='unreviewed'],next_queue=['acssynbio7b00278 Inside-Out Viruses SI','Remaining14ACS sources and10rotating low/broad records','FNANO2011 and open conference source follow-ups'],exclusion_audit={'sample':[key],'reason':'All1new exclusion checked by same-agent second pass through main Methods, Results and Conclusion; no claim of independent reviewer.'},validation=[L.validate()])
 L.upsert('batches',b,'Save actual1of25 screening progress and exclusion evidence');print(L.validate())
if __name__=='__main__':main()
