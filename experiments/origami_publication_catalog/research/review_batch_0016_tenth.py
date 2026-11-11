"""Nanocluster template modifications and explicit sequence-list discrepancies."""
import json,re,subprocess
import ledger as L
from review_batch_0001 import evidence

def main():
 k='10.1021/jacs.9b09308';rid='B0016';path=L.ROOT/'assets/sources/acs-expansion-20261104/18255026-ja9b09308_si_001.pdf'
 ev=evidence(path,'https://ndownloader.figshare.com/files/18255026','SI methodsS3-S4, figure texts/captionsS5-S32, variant instructionsS33/S39 and sequence table organization inspected. SchemeS1PDF26 andS4PDF29 visually inspected. Individual sequence bases not independently audited.')
 s=subprocess.check_output(['pdftotext','-layout',str(path),'-']).decode();tri=s.split('The original Sequences used in the assembly of triangular DNA origami template',1)[1].split('To assemble rectangular DNA origami',1)[0]
 a=[dict(name=n.replace(' ',''),sequence=q) for n,q in re.findall(r'^\s*([ABC]\s*\d+|Link-[ABC]\d[ABC]|Loop),\s*([ACGT]+),',tri,re.M)]
 rows=[]
 for page,t in enumerate(s.split('\f'),1):
  if page>=39:
   for m in re.finditer(r'^\s*(\d+[A-Z]?)\s+([ACGT][ACGT ]+)\s*$',t,re.M):rows.append(dict(name=m[1],sequence=m[2].replace(' ',''),pdf_page=page))
 assert len(a)==208 and len({x['name'] for x in a})==208;assert len(rows)==226
 names={x['name'] for x in rows};assert '214A' in names and '215' not in names
 long=[45,46,58,59,69,70,82,83,93,94,106,107,117,118,130,131,141,142,154,155,165,166,178,179]
 short=list(range(38,47))+list(range(51,60))+list(range(62,71));ell=short+long[6:];u=ell+[75,76,86,87,99,100,110,111,123,124,134,135,147,148,158,159,171,172]
 patterns={'I_long':long,'I_short':short,'L':ell,'U':u};assert [len(x) for x in patterns.values()]==[24,27,45,63]
 L.atomic(L.HERE/'nanocluster_sequence_index.json',json.dumps(dict(evidence=ev,triangle_original_rows=a,rectangle_original_rows=rows,rectangle_extension_ids=patterns,triangle_extensions={'A01-A65':'CCCTAACTCCCC','B01-B65':'CCTCCTTCCTCC','C01-C65':'CCCTTAATCCCC'},limitations='Text extraction only, no independently verified sequence recipe. Triangle methods205versus208listed. Rectangle214A/no215 and omitted side-staple identities unresolved. No extended sequences synthesized by this script.'),indent=2)+'\n')
 note='M13mp18 7249nt scaffold explicitSI3. Triangle variants add12nt at3prime to B01-B65(onearm), A01-A65+B01-B65(twoarms), or allA/B/C01-65(threearms); separate5prime dithiol capture strands carry two additional leadingA bases before complementary12mer. Original triangle list has195arm+12Link+1Loop=208entries, conflicting with205helper statementSI3. Rectangle variants add15A at5prime to24(Ilong),27(Ishort),45(L),63(U)specified stapleIDs and use separate15T3primeSH capture oligo. All side staples omitted perSI3, but exact omittedIDs not established. Rectangle original list226entries includes214A and no215. Metal/oxide identity and growth conditions do not alone create additional origami geometry designs. Core parent identity and exact variant assembly mixtures remain unresolved; no automatic merge with legacytriangle/rectangle.'
 qs=['Acquire/read main article and identify cited parent designs; compare core sequences with legacy shapes before merging IDs.','Resolve triangle205helper claim versus208listed sequences and identify strands actually used.','Identify omitted rectangle side staples and reconcile214A/no215 with routing; verify fullvariant mixtures.','Independently audit sequence characters and scaffold mapping/native designs; no complete synthesis sets certified.','Confirm primary publication date and inventory any additional source deposits.','Review narrow catalog filled-domain/lattice eligibility separately for triangular frame and rectangle.']
 p=next(p for p in L.read('publication_reviews') if p['registry_key']==k)
 p.update(review_stage='design_sources_reviewed',relevance='design_bearing',design_contributions=['modified_design'],catalog_eligibility='unresolved',access='SI_PDF_available; main_pending',rationale=note,reviewer='Codex SI methods,variant instructions and source-list review with selected routing visuals',run_id=rid,date=L.DATE,unresolved_questions=qs)
 if ev not in p['evidence']:p['evidence'].append(ev)
 L.upsert('publication_reviews',p,'Record modification recipes and preserve source-list discrepancies')
 for did,title,shape in [('RDE0063','Triangle with one/two/three modified arms','Triangular frame has multihelix packed arms visibleSchemeS1; whole-frame eligibility unresolved.'),('RDE0064','Rectangle with I-long/I-short/L/U capture patterns','Planar parallelhelix rectangle visibleSchemeS4; exact lattice and fullsource eligibility unresolved.')]:
  old=next((d for d in L.read('design_evidence') if d['design_id']==did),None);assert old is None or k in old['publication_keys']
  L.upsert('design_evidence',dict(design_id=did,publication_keys=[k],named_objects=[title],identity_status='Modification sourcegroup; parent legacy identity and exact variants pending',lattice_decision=shape,catalog_eligibility='unresolved',core_variant_composition=note,relationships=[],variant_links=[],source_completeness='not_verified',source_files=[ev],evidence=[ev],outstanding_checks=qs,review_stage='source_reviewed',review_run=rid,run_id=rid,date=L.DATE,legacy_record={}), 'Keep triangle and rectangle sourcegroups separate without parent identity assumption')
 refs=re.findall(r'(?ms)^\((\d+)\)\s*(.*?)(?=^\(\d+\)|\Z)',s.split('REFERENCE\n')[-1]);assert len(refs)==6
 for n,c in refs:
  c=re.sub(r'\s*S44\s*\f?\s*$','',c)
  L.upsert('discovery_edges',dict(edge_id='B0016:nanocluster:SIref'+n,source_key=k,target_key='citation:nanocluster:SI:'+n,relation='cites',citation=' '.join(c.split()),evidence_url=ev['url'],local_file=ev['local_file'],sha256=ev['sha256'],locator='SI44reference'+n,reconciliation_state='pending_identity_date_scope_reconciliation',run_id=rid,date=L.DATE),'Retain6SIreferences including HaoYan2008lead')
 b=next(b for b in L.read('batches') if b['batch_id']==rid);action='Reviewed12of25: nanocluster triangle/rectangle modification sources,208and226originalsequence entries indexed,7pattern recipes separated;205/208and214A/no215gaps retained,6SIreferences saved.'
 if action not in b['completed_actions']:b['completed_actions'].append(action)
 b.update(after_counts=L.counts(),validation=[L.validate()],next_queue=['Remaining13B0016inputs; next10.1021/acs.nanolett.9b02786 downloadedSI.',*qs]);L.upsert('batches',b,'Save12of25progress with source-list ambiguities');print(L.validate())
if __name__=='__main__':main()
