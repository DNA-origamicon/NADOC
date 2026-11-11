"""B0005 explicit decisions from inspected ACS source sections; partial batch."""
import json
import ledger as L
from review_batch_0001 import evidence

D={
'ja404354c':('modified_design','PDF pp.4,13,19 FigS1/S10 and replacement strand sets','Bifacial rectangular M13 origami positions nanoparticles on opposing faces. A basic core list and replacement strands for different dimer arrangements are separated.','Reconcile all bifacial capture sets and baseline routing; do not count nanoparticle size alone as a distinct DNA geometry.'),
'ja403863a':('reused_design,modified_design','PDF pp.4–5 Sample preparation and AFM imaging','Actual M13 experiments use216 staples with biotin at selected5-prime ends, with or without polyT spacers. The periodic four-strand simulation earlier in SI is a separate model, not the whole authored origami.','Resolve original template references8–9 and actual modified strands; distinguish physical experiment from periodic simulation representation.'),
'nl400881w':('reused_design,modified_design','PDF p.2 Supplementary NoteS2','A twelve-helix segment of the tall rectangle is closed into a cylinder; hairpins bias cyclization and seed growth of distinct REd/SEd tile nanotubes.','Reconcile origami seed routing, seam/hairpin variants and tile docking. Non-origami growth products do not erase relevance of the origami seed.'),
'bm4011722':('reused_design,modified_design','PDF pp.1–2 nanostructure assembly and sequence section','Tall Rothemund rectangle is redesigned at selected staples for biotin and peptide patterning; experimental cellular signaling follows assembly.','Match redesigned/biotinylated replacements to parent tall rectangle and tested peptide arrangements.'),
'ac402493u':('uncertain','PDF pp.1–3 polarization theory and simulation movie descriptions','SI models six-helix and triangular origami polarization and concentration distributions. It does not provide synthesis methods or routing.','Retrieve primary methods to resolve actual reuse and parent sources; theoretical use is not proof of experimentally assembled variants.'),
'jz402076b':('modified_design','PDF p.3 FigS1 and AFM characterization section','AFM characterizes origami functionalized with two5nm AuNPs and measures their center spacing for Raman substrates.','Inspect origami preparation and parent design; verify attachment staples and core sets separately from AuNP DNA coating.'),
'ja408656y':('modified_design','PDF pp.2–3 FigsS1–S3 captions','AFM documents DFc and DFc-loxP frames with orientation markers and four connection points; Cre-treated objects include synaptic/recombination products.','Inspect frame routing, loxP orientation variants and full component lists; extracted captions are garbled and need image checks.'),
'nn405408g':('new_design,modified_design','PDF pp.19–20 FigsS7–S11 captions; contents sequence section','Five design schematics are labeled by joint lengths, including0,11,53 and74 bases; analytical and imaging sections accompany compliant origami variants.','Inspect diagrams and exact variable-joint staple composition; verify all five lengths and source images before synthesis completeness claims.'),
'la403617r':('reused_design','PDF pp.1–3 FigsS1–S4 and control table','T-shaped and bar-shaped origami are metallized with gold/copper; images and controls document substrate-specific assembly use.','Retrieve core geometries and parent publications; coatings alone do not establish new DNA routing.'),
'ja4109819':('modified_design','PDF p.2 Preparation of hexagonal DNA origami units','M13 units designed in caDNAno combine cholesterol-modified staples and azobenzene-linked oligos for membrane-surface assembly.','Reconcile parent azobenzene design and membrane anchor substitutions. Hexagonal outline does not determine helix lattice.'),
'ac403661z':('modified_design','PDF pp.2–7 FigsS1–S10 and DNA/microRNA/core sequence headings','YES/AND gate experiments and mismatch controls are paired with signal/block strands and a separately named DNA-origami helper list.','Inspect whole origami geometry and gate attachment scheme; match gate-specific strands to core sequences, not just table counts.'),
'nl404183t':('modified_design','PDF pp.1–4 contents and ionic-trapping figure captions','Leash and no-leash nanopore designs are explicitly distinguished in the experimental ionic-trapping material; section9 is identified as the staple/layout source.','Inspect actual section9 and both geometry variants and parent source before scope/source decisions.'),
'nl500092j':('reused_design,modified_design','PDF p.3 DNA origami structures; p.15 FigS3','M13 rectangles use186 staples and thiol/biotin/ssDNA modifications. SI also reports400nm six-helix bundles with eight thiol anchors as a distinct binding test.','Resolve both core parents and all surface-anchor/docking variants; distinguish experimental switch from separately modified simulation domains.'),
'ja411446q':('new_design,modified_design','PDF p.2 experimental materials and frame assembly','M13mp18 and PhiX174 scaffolds are coassembled with helper strands as a frame; DX tile strands are prepared separately for growth inside it.','Inspect frame routing and scaffold identities plus origami/DX interfaces. Review frame eligibility separately from non-origami tile arrays.')}

def main():
 acs={r['doi']:r for r in json.loads((L.ROOT/'acs_acquisition.json').read_text())['records']}
 for r in L.read('publication_reviews'):
  suffix=r.get('doi','').split('/')[-1]
  if suffix not in D or r.get('run_id')!='bootstrap-20261105':continue
  c,loc,note,q=D[suffix];f=next(f for f in acs[r['doi']]['files'] if f.get('local_file','').endswith('.pdf'))
  r.update(review_stage='design_sources_reviewed',relevance='uncertain' if c=='uncertain' else 'design_bearing',catalog_eligibility='unresolved',design_contributions=c.split(','),evidence=[evidence(L.ROOT/'assets'/f['local_file'],f['url'],loc)],rationale=note,unresolved_questions=[q],access='partial',reviewer='Codex source inspection',run_id='B0005',date=L.DATE)
  L.upsert('publication_reviews',r,'B0005 explicit supplement review; retain component and source distinctions')
 b=next(b for b in L.read('batches') if b['batch_id']=='B0005')
 if b['status']=='completed':
  print(L.validate());return
 b.update(completed_actions=['Inspected cited source sections of14 ACS supplements;13 design-bearing and one theoretical-source case remains uncertain.','Paper-origami assay candidate requires main-text exclusion check.'],after_counts=L.counts(),validation=[L.validate()],unresolved_keys=b['input_keys'],next_queue=['10.1021/ac402118a']+b['input_keys'][15:])
 L.upsert('batches',b,'Save partial B0005 source decisions and remaining balanced queue')
 print(L.validate())

if __name__=='__main__':main()
