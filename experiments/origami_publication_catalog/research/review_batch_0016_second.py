"""Source-reviewed antenna and explicit tile/origami terminology boundary."""
import re,subprocess,xml.etree.ElementTree as E
import ledger as L
from review_batch_0001 import evidence

def main():
 rid='B0016';k='10.1021/acs.nanolett.9b02886';g='10.34133/2019/7403580'
 path=L.ROOT/'assets/sources/acs-expansion-20261104/17430617-nl9b02886_si_001.pdf'
 ev=evidence(path,'https://ndownloader.figshare.com/files/17430617','All12SIpages text read; FigS1 PDF3 and TableS1 PDF4 visually inspected. FigureS2 PDF5 binding-site variants.')
 note='SI specifies square-lattice two-layer sheet2LS approximately60x50x5nm, p7249M13mp18. FigS1 visually shows42helix labels0–41 and2x21cross-section. Each face has four15A handles to bind one60nmAuNP; Cy5 uses3Tspacer, endcaps4C extensions. FigureS2 compares1BS/2BS origami; exact strand replacement sets unverified. TableS1 provides modification recipes with literal staple placeholders, not a complete sequence list. Its thiolDNA row has19T in text (visually checked against PDF4), but caption and PDF5methods say15T; discrepancy retained. No native file/full staple inventory recovered. Procedural citations do not prove identical parent geometry.'
 qs=['Acquire main and primary first-online date; determine new versus modified/reused design with parent sources.','Recover nativecaDNAno and all staple sequences plus exact1BS/2BS/reference combinations.','Resolve thiolDNA19Tprinted-row versus15Tcaption/methods conflict.','Keep square-lattice geometry evidence separate from incomplete catalog source eligibility.']
 p=next(p for p in L.read('publication_reviews') if p['registry_key']==k)
 p.update(review_stage='design_sources_reviewed',relevance='design_bearing',design_contributions=['uncertain'],catalog_eligibility='unresolved',access='SI_available; main_pending',rationale=note,reviewer='Codex SI text and routing/table visual review',run_id=rid,date=L.DATE,unresolved_questions=qs)
 if ev not in p['evidence']:p['evidence'].append(ev)
 L.upsert('publication_reviews',p,'Verify antenna geometry and source limitations from acquired SI')
 did='RDE0057';old=next((d for d in L.read('design_evidence') if d['design_id']==did),None);assert old is None or k in old['publication_keys']
 L.upsert('design_evidence',dict(design_id=did,publication_keys=[k],named_objects=['2LS square-lattice two-layer sheet optical antenna;1BS/2BS variants'],identity_status='Geometry and named variants supported; exact source combinations pending',lattice_decision='Square lattice explicit in SI4; FigS1 has2x21helices. Geometry within lattice scope; complete source eligibility unresolved.',catalog_eligibility='unresolved',core_variant_composition=note,relationships=[],variant_links=[],source_completeness='not_verified',source_files=[ev],evidence=[ev],outstanding_checks=qs,review_stage='source_reviewed',review_run=rid,run_id=rid,date=L.DATE,legacy_record={}), 'Record antenna source group without asserting synthesis completeness')
 text=subprocess.check_output(['pdftotext','-layout',str(path),'-']).decode();thiol=re.search(r'Thiol-DNA\s+5.*?C6\s+([T]+)',text).group(1);assert len(thiol)==19
 refs=re.findall(r'(?ms)^\s*\((\d+)\)\s*(.*?)(?=^\s*\(\d+\)|\Z)',text.split('References',1)[1]);assert len(refs)==9
 for n,t in refs:
  L.upsert('discovery_edges',dict(edge_id='B0016:directing:SI-ref'+n,source_key=k,target_key='citation:directing:SI:'+n,relation='cites',citation=' '.join(re.sub(r'\n\s*\d+\s*\f',' ',t).split()),evidence_url=ev['url'],local_file=ev['local_file'],sha256=ev['sha256'],locator='SI reference'+n,reconciliation_state='pending_identity_date_scope_reconciliation',run_id=rid,date=L.DATE),'Retain all9SIreferences')
 path=L.ROOT/'assets/sources/pre2020-expansion/PMC6750079.xml';r=E.parse(path).getroot();ge=evidence(path,'https://www.ebi.ac.uk/europepmc/webservices/rest/PMC6750079/fullTextXML','Entire main body sections1–4.7 and supplement caption inspected; Results/Discussion describe five-strand tiles; supplement Figure1caption gives two48ntstrands.')
 p=next(p for p in L.read('publication_reviews') if p['registry_key']==g)
 p.update(review_stage='fulltext_reviewed',relevance='uncertain',design_contributions=['uncertain'],catalog_eligibility='excluded',access='main_XML_available; actual_SI_file_pending',rationale='Main calls structures ribbon-like DNA origami but Discussion explicitly describes five-strand DNA tiles. Results folds S1/S2 using N1/N2/N3 into repeated units and connects them to ribbons; S3/S4 add15base overhangs for mica-assisted2Dlattices. Supplement caption specifies two48ntstrands. Main methods use five oligos, no long scaffold. Excluded from narrow accepted catalog as repeating tile assembly; broad origami terminology boundary left explicit rather than automatically excluding from literature on strand length alone. Actual supplementary figures/sequence table not reviewed.',reviewer='Codex complete main XML and supplement-caption inspection',run_id=rid,date=L.DATE,unresolved_questions=['Acquire actual SI and inspect sequence/table/routing evidence.','Resolve broad census classification for short-scaffold/tile boundary; preserve authors origami terminology and narrow tile exclusion.','Reconcile all bibliography entries and original template leads.'])
 if ge not in p['evidence']:p['evidence'].append(ge)
 L.upsert('publication_reviews',p,'Separate tile catalog exclusion from uncertain broad origami terminology')
 refs=r.findall('.//ref-list/ref')
 for ref in refs:
  n=ref.get('id');doi=ref.find('.//pub-id[@pub-id-type="doi"]')
  L.upsert('discovery_edges',dict(edge_id='B0016:gold-metamaterials:'+n,source_key=g,target_key=doi.text.lower() if doi is not None else 'citation:gold-metamaterials:'+n,relation='cites',citation=' '.join(ref.itertext()),evidence_url=ge['url'],local_file=ge['local_file'],sha256=ge['sha256'],locator='XML reference'+n,reconciliation_state='pending_identity_date_scope_reconciliation',run_id=rid,date=L.DATE),'Retain complete main bibliography')
 b=next(b for b in L.read('batches') if b['batch_id']==rid)
 b['completed_actions'].append(f'Reviewed4of25: antennaSI geometry42helices/2layers and incomplete sources; gold metamaterial five-strand tile boundary explicit. Saved9SI and{len(refs)}main references.')
 b['exclusion_audit']['sample'].append(g);b['exclusion_audit']['reason']+=' Gold tile exclusion based on complete main methods/results and caption; broad literature classification uncertain.'
 b.update(after_counts=L.counts(),validation=[L.validate()],next_queue=['Remaining21B0016 inputs, starting acquired engineered-defects SI.','Antenna main/native/staples and19T/15Tdiscrepancy; gold actualSI and broad classification boundary.','Human dissertation request pending; continue independent author/citation routes.'])
 L.upsert('batches',b,'Save4of25progress and conservative source decisions');print(len(refs),L.validate())
if __name__=='__main__':main()
