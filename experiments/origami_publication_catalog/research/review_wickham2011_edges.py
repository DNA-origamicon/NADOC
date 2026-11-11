"""Narrow follow-up of edge-strand discrepancy; retain unresolved Mem role."""
import ledger as L
from review_batch_0001 import evidence

def main():
 url='https://groups.physics.ox.ac.uk/molecularmotors/People/D.Phil%20Theses/Shelley%20Wickham%202011.pdf'
 e=evidence(L.ROOT/'assets/research-20261105/wickham-2011-thesis.pdf',url,'Printed45–46/PDF57–58 edge-loop text and Fig2.3; FigC.1/PDF225 visually inspected at1800px; TableC.1/PDF231–232')
 note='Follow-up: Section2.2 explicitly adds4T loops at external edge-staple turns to reduce stacking. FigC.1 visually places all24 non31/32nt position-named rows at outermost +/-9 edges:20x36nt and four corner rows (M9t0i28nt,M9t22j48nt,M-9t2i48nt,M-9t24j28nt). This supports an edge/corner explanation for simplified count differences, but exact base pairing and insertions are not independently mapped. Fifteen Mem rows remain unassigned; do not infer they bind the244nt remainder solely from name or table location.'
 for ledger,keyfield,key in [('publication_reviews','registry_key','thesis:oxford:wickham:2011'),('design_evidence','design_id','RDE0039')]:
  p=next(p for p in L.read(ledger) if p[keyfield]==key)
  if e not in p['evidence']:p['evidence'].append(e)
  field='rationale' if ledger=='publication_reviews' else 'core_variant_composition'
  if note not in p[field]:p[field]+=' '+note
  L.upsert(ledger,p,'Resolve edge-position context while preserving unresolved exact sequence composition')
 print(L.validate())
if __name__=='__main__':main()
