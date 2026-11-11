"""Save observed routing-panel features and explicitly bound image interpretation."""
import json
import ledger as L
from review_batch_0001 import evidence

def main():
 before=L.counts();key='10.1038/ncomms15654';batch='AUTHOR0009'
 archive=next(a for a in json.loads((L.HERE/'shih_source_archive_inventory.json').read_text()) if a['ordinal']==34)['archive']
 ev=evidence(L.ROOT/'assets/research-20261105/shih-extracted/34/PonnuswamyN_ncomm_2017_SI.pdf',archive['url'],'SI Figs41–48 at PDF/printedpp40–47, individually visually inspected; DN5 enlarged with pdftoppm at600dpi but source remains low resolution')
 notes={
 'DN1':'Fig41,p40: staggered open strip of numbered helix circles, auxiliary circles on one side; long flattened colored strand paths with deletions/insertions. No closed barrel geometry is directly encoded by the flat cross-section alone.',
 'DN2':'Fig42,p41: similar staggered open-strip cross-section and visibly shorter flattened routing thanDN1. Exact shared strand/sequence identity not verified.',
 'DN3':'Fig43,p42: broader staggered strip with two isolated protruding numbered circles near center; colored paths include crosslinks across central gap and red deletion marks.',
 'DN4':'Fig44,p43: narrower staggered cross-section strip with auxiliary circles and elongated flattened routing. Small axis labels limit exact numerical transcription.',
 'DN5':'Fig45,p44: very small ring-like cross-section icon above long narrow routing panel. Enlarged600dpi crop remains pixelated; exact labels and connectivity cannot be verified. The prior mainFig2 appearance must not be called planar: a rectangular projection does not establish planarity.',
 'DN6':'Fig46,p45: numbered0–23 cross-section arranged in a compact ring/bundle-like pattern around an empty region; flattened paths show terminal scaffold returns and multiple strand crossovers. Full topology/native lattice assignment still requires verification.',
 'DN7':'Fig47,p46: numbered0–47 cross-section with filled/unfilled circles arranged in a multirow staggered pattern; flattened colored strands and blue returns are visible. Fig2 rod-like appearance is insufficient to infer final arrangement from this unrolled diagram.',
 'DN8':'Fig48,p47: twelve separated six-circle cross-section groups numbered through71, with long connections between routing blocks; mainFig2 depicts an octahedral frame. Local bundle layout does not on its own resolve catalog eligibility or final inter-bundle routing.'}
 report=dict(evidence=ev,objects=[dict(name=n,figure=i+41,pdf_page=i+40,note=note) for i,(n,note) in enumerate(notes.items())],limitations='Visual review, not reconstruction or validation of native connectivity. Source sequence mappings, variant identities and full lattice decisions remain open.',render_commands=['pdftoppm -f 40 -l 47 -scale-to 1600 -png SI.pdf /tmp/layout','pdftoppm -f 44 -singlefile -r 600 -x 500 -y 850 -W 4000 -H 500 -png SI.pdf /tmp/dn5-detail'])
 L.atomic(L.HERE/'ponnuswamy_diagram_review.json',json.dumps(report,indent=2)+'\n')
 d=next(d for d in L.read('design_evidence') if d['design_id']=='RDE0045')
 d['object_diagram_reviews']=report['objects'];d['lattice_decision']='All eight caDNAno panels visually inspected. Staggered/bundle cross-sections and path diagrams observed, but exact native topology, final shape and narrow lattice/source eligibility remain unresolved per object.'
 d['core_variant_composition']=d['core_variant_composition'].replace('DN5 planar rectangular object','DN5 object with rectangular appearance in mainFig2 (planarity unverified)').replace('while exact native routing/lattice and other panels remain unchecked','while exact native routing/lattice remains unchecked; all eight panels subsequently visually inspected in AUTHOR0009')
 d['outstanding_checks']=[q.replace('Inspect DN3–DN8 diagrams individually and verify','All DN1–DN8 panels visually inspected; now verify') for q in d['outstanding_checks']]
 if ev not in d['evidence']:d['evidence'].append(ev)
 L.upsert('design_evidence',d,'Record all eight visual panel inspections and correct unsupported planarity descriptor')
 p=next(p for p in L.read('publication_reviews') if p['registry_key']==key)
 p['rationale']=p['rationale'].replace('DN5 planar rectangular object','DN5 object with rectangular appearance in mainFig2 (planarity unverified)').replace('while exact native routing/lattice and other panels remain unchecked','while exact native routing/lattice remains unchecked; all eight panels subsequently visually inspected in AUTHOR0009')
 p['source_diagram_review']=report['objects'];p['unresolved_questions']=d['outstanding_checks']
 if ev not in p['evidence']:p['evidence'].append(ev)
 L.upsert('publication_reviews',p,'Advance bounded visual review without inferring complete sources')
 L.upsert('batches',dict(batch_id=batch,date=L.DATE,status='completed',input_keys=[key],selection='Finish the six remaining caDNAno panel inspections afterAUTHOR0008',completed_actions=['Inspected all remaining panels; recorded object-level visual observations and readability limits.','Corrected unsupported DN5 planarity description; retained exact topology, source and variant uncertainties.'],before_counts=before,after_counts=L.counts(),unresolved_keys=[key],exclusion_audit={'sample':[],'reason':'No new exclusions or eligibility promotions.'},validation=[L.validate()],next_queue=['Find native routing files and verify source-to-variant identity, including DN5 low-resolution panel.','Resolve DN9 parent provenance and MeRPy barrel correspondence.','Review acquired Hahn2019 and Krieg2018 sources; rotate author histories.']), 'Save completed panel-inspection batch and reproducible render instructions')
 print(L.validate())
if __name__=='__main__':main()
