"""Read-only thesis sequence-table inventory and evidence review; no molecular authoring."""
import hashlib,json,re,subprocess
from collections import Counter
import ledger as L
from review_batch_0001 import evidence

def main():
 path=L.ROOT/'assets/research-20261105/wickham-2011-thesis.pdf'
 url='https://groups.physics.ox.ac.uk/molecularmotors/People/D.Phil%20Theses/Shelley%20Wickham%202011.pdf'
 pages=subprocess.check_output(['pdftotext','-layout',str(path),'-']).decode().split('\f');rows=[]
 for n in range(226,233):
  for line in pages[n-1].splitlines():
   m=re.match(r'\s*(M(?:-?\d+t\d+[a-z]|em\d+))\s+([ACGT]+)\s*$',line)
   if m:rows.append(dict(pdf_page=n,name=m[1],length=len(m[2]),sequence_sha256=hashlib.sha256(m[2].encode()).hexdigest(),group='Mem' if m[1].startswith('Mem') else 'position_named'))
 assert len(rows)==231 and len({r['name'] for r in rows})==231
 inv=dict(source_file=str(path.relative_to(L.ROOT)),source_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),locator='TableC.1 PDF226–232, printed214–220',method='Regex extraction of single-line M position names and Mem names with ACGT sequences; counts/hashes only, not a validated synthesis set or molecular design',rows=rows,counts={g:dict(Counter(r['length'] for r in rows if r['group']==g)) for g in ['position_named','Mem']},unresolved=['216 position-named rows differ in lengths from Chapter2 simplified144x31+72x32 description; edge modifications require graphical/source inspection.','15 Mem rows require assignment to scaffold remainder or other role, not assumed to be core staples.','Sequence identity, exact scaffold and all modified replacements not independently verified.'])
 L.atomic(L.HERE/'wickham2011_sequence_inventory.json',json.dumps(inv,indent=2)+'\n')
 ev=evidence(path,url,'PDF53–54,65–66,200,224–227,231–233,172–173,244; printed41–42,53–54,188,212–215,219–221,160–161,232')
 iev=evidence(L.HERE/'wickham2011_sequence_inventory.json',url,'Read-only TableC.1 row inventory; no source-completeness certification')
 key='thesis:oxford:wickham:2011';p=next(p for p in L.read('publication_reviews') if p['registry_key']==key)
 for e in [ev,iev]:
  if e not in p['evidence']:p['evidence'].append(e)
 note='Two core designs explicitly identified: TypeA Rothemund2006 seam rectangle,216 nominal32nt staples,24x288bp helices; TypeB reduced-twist variant with6 skipped bases per helix,24x282bp helices and remainder loop244nt versus100nt. Section2.6 describes144x31nt+72x32nt staples, but TableC.1 has216 position-named rows with other lengths plus15Mem rows; exact end modifications/remainder role pending. AppendixA.1 assigns TypeA to Ch2/Ch3AFM/Ch4/Ch6 and TypeB to Ch3fluorescence/Ch5. More specific C.3.1 says initial Ch3fluorescence Figs3.4/3.5 used TypeA; Section2.6 also tests TypeB despite broad Ch2 assignment. Preserve these exceptions. Ch6 uses three tris-NTA internal staple modifications with biotin on opposite face; same DNA design used for E.coli and yeast F1. No new core inferred solely from protein species.'
 p.update(review_stage='design_sources_reviewed',rationale=note,access='partial',unresolved_questions=inv['unresolved']+['Audit all Ch3–6 track/block/release/fluorophore replacements and graphical maps.','Inspect original RothemundSI1p28 and exact scaffold sequence; reconcile thesis/journal variant lineage.','Enumerate complete thesis bibliography and author/publication routes.'],reviewer='Codex inspected named thesis sections and table inventory',run_id='fnano-2011',date=L.DATE)
 L.upsert('publication_reviews',p,'Record explicit core assignment and exceptions without certifying complete source set')
 d=dict(design_id='RDE0039',publication_keys=[key],named_objects=['TypeA seam rectangle','TypeB reduced-twist rectangle','Motor tracks and tris-NTA protein attachment variants'],identity_status='Provisional thesis family; exact variant composition and publication overlap pending',core_variant_composition=note,lattice_decision='Unresolved narrow catalog eligibility; hexagonal array of addressable pixels in Section2.1 does not establish honeycomb packing',catalog_eligibility='unresolved',source_completeness='not_verified',review_stage='source_reviewed',source_files=[ev,iev],evidence=[ev,iev],outstanding_checks=p['unresolved_questions'],relationships=[],variant_links=[],review_run='fnano-2011',run_id='fnano-2011',date=L.DATE,legacy_record={})
 L.upsert('design_evidence',d,'Record source-supported thesis family with unresolved table composition')
 print(json.dumps({'rows':len(rows),'counts':inv['counts'],'validation':L.validate()},indent=2))
if __name__=='__main__':main()
