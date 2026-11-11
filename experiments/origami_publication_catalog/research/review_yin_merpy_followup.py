"""Primary publication-date verification and visual source-diagram inspection."""
import json
import ledger as L
from review_batch_0001 import evidence

def main():
 key='10.1093/nar/gkz998';before=L.counts();rid='AUTHOR0004'
 ev=evidence(L.HERE/'yin_merpy_primary_date.json','https://academic.oup.com/nar/article/47/22/11956/5622713','Publisher article history: Published12November2019; issue47(22),16December2019; full author list')
 fig=evidence(L.ROOT/'assets/research-20261105/yin2019-ssDNA-SI.pdf','https://yin.hms.harvard.edu/publications/2019.ssDNA.sup.zip','PDF/printedp20 FigS7 rendered and visually inspected; upper barrel and lower rectangle strand diagrams')
 note='FigS7 visually confirms two flattened caDNAno strand diagrams: upper barrel with multiple colored routed strands and red deletion marks; lower rectangle with blue perimeter/return paths, shorter colored/black strands and red deletion marks. Caption explicitly maps top to30nm barrel and bottom to20nm rectangle. No helix numbering, nucleotide ruler or cross-sectional layout is supplied in this panel; do not infer lattice or complete synthesis set from the image alone. Exact routing, strand role/color mapping and sequence correspondence remain unresolved.'
 p=next(p for p in L.read('publication_reviews') if p['registry_key']==key)
 for e in [ev,fig]:
  if e not in p['evidence']:p['evidence'].append(e)
 p['date_evidence']={'date':'2019-11-12','source':ev,'primary_verified':True,'meaning':'Publisher Published date; issue date2019-12-16; prior unverified legacy2019-12-01 retained in revision history'}
 p['authors']=['Dionis Minev','Richard Guerra','Jocelyn Y Kishi','Cory Smith','Elisha Krieg','Khaled Said','Amanda Hornick','Hiroshi M Sasaki','Gabriel Filsinger','Brian J Beliveau','Peng Yin','George M Church','William M Shih']
 p['full_author_list_transcribed']=True
 p['unresolved_questions']=[q for q in p['unresolved_questions'] if not q.startswith('Verify first-online date:') and not q.startswith('Inspect FigS7 geometry')]
 q='Verify cross-sectional lattice and exact native routing/sequence correspondence; FigS7 visually inspected but lacks helix numbering and cross-section.'
 if q not in p['unresolved_questions']:p['unresolved_questions'].append(q)
 p['source_diagram_review']=note;L.upsert('publication_reviews',p,'Resolve publication date and record bounded visual evidence')
 d=next(d for d in L.read('design_evidence') if d['design_id']=='RDE0043')
 if fig not in d['evidence']:d['evidence'].append(fig)
 d.update(lattice_decision='Unresolved after FigS7 visual inspection: flattened path diagrams without cross-sectional lattice or helix labels',diagram_review=note,outstanding_checks=p['unresolved_questions'])
 L.upsert('design_evidence',d,'Record visual diagram limits without geometry inference')
 invpath=L.HERE/'yin_bibliography_inventory.json';inv=json.loads(invpath.read_text())
 for row in inv['entries']:
  if row['anchor']=='2019.ssDNA':row.update(identity_status='primary_title_authors_doi_date_verified',target_key=key,design_review_status='main_SI_protocol_workbook_and_FigS7_inspected; full_sources_unverified',first_online='2019-11-12',identity_evidence=ev)
 L.atomic(invpath,json.dumps(inv,indent=2)+'\n')
 L.upsert('batches',dict(batch_id=rid,date=L.DATE,status='completed',input_keys=[key],selection='Resolve prior source-review date and visual-diagram questions',completed_actions=['Verified publisher first-publication date and13author list.','Visually inspected both FigS7 diagrams; catalog lattice and complete-source checks remain unresolved.'],before_counts=before,after_counts=L.counts(),unresolved_keys=[key],exclusion_audit={'sample':[],'reason':'No exclusions.'},validation=[L.validate()],next_queue=['Match parent barrel staple/miniscaffold source and rectangle pools','Continue Yin bibliography source reviews and other requested author histories']), 'Save bounded date and visual source review')
 print(L.validate())
if __name__=='__main__':main()
