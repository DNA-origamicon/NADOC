"""Index engineered-defect sources with experimental/computational boundaries."""
import json,re,subprocess
from collections import Counter
import ledger as L
from review_batch_0001 import evidence

def main():
 k='10.1021/acsnano.9b03770';rid='B0016';path=L.ROOT/'assets/sources/acs-expansion-20261104/16217996-nn9b03770_si_001.pdf'
 ev=evidence(path,'https://ndownloader.figshare.com/files/16217996','SI targeted text review: contents, methods introduction, PDF7–8,48–49,55–57,68–72,80–86,110–112. PDF7 routing and PDF82 yield table visually inspected. Tables5–7 PDF86–110 mechanically indexed, not base-by-base certified.')
 pages=subprocess.check_output(['pdftotext','-layout',str(path),'-']).decode().split('\f');rows=[]
 for n,t in enumerate(pages,1):
  if 86<=n<=110:
   for name,seq in re.findall(r'^\s*((?:4|6|10)hb_\S+)\s+([ACGT]+)\s*$',t,re.M):rows.append(dict(name=name,sequence=seq,length=len(seq),pdf_page=n))
 assert len(rows)==1373 and len({r['name'] for r in rows})==1373
 families=dict(Counter(r['name'].split('_')[0] for r in rows));assert families=={'4hb':381,'6hb':680,'10hb':312}
 variants=re.findall(r'^\s*((?:4|6|10)HB-\S+)\s+\d+',pages[80],re.M)
 L.atomic(L.HERE/'engineered_defects_sequence_index.json',json.dumps(dict(evidence=ev,rows=rows,counts_by_family=families,counts_by_name_prefix=dict(Counter('_'.join(r['name'].split('_')[:-1]) for r in rows)),table1_experimental_labels=variants,limitations=['Rows are indexed source entries across shared/replacement pools, not1373staples in one structure.','No exact experimental mixture or full scaffold/native routing certified; color columns not captured by text parser.','12HBhinge and computational cross-section sources are not covered by these three named sequence families.','Table2PDF82 prints4HB-Ref total698/wellfolded760/yield91.8%; retained inconsistent, no silent swap.','Table2PDF82prints6HB-1nt-200% while Table1PDF81has6HB-2nt-100% in corresponding position; identity unresolved.']),indent=2)+'\n')
 note='SI establishes engineered-gap experimental designs:4HBsquare lattice(Fig1PDF7),6HBhoneycomb(Fig2PDF8) and10HBhoneycomb(Fig66PDF72). Nicks are changed to programmed ssDNA gaps; gap density/length and axial distribution define variants, not merely solution conditions. PDF55–57 separately describes42ntcrossover intervals and8.2%/16.4%staple omission. PDF80reports experimental12HBhinges; exact source/parent pending. Section9PDF68–71 reports FEcross-sections4HBhex,8HBhex/square,10HBhex,12HBhex/square,13HBhex,16HBsquare; those simulation cases are not all established experimental constructions. Tables5–7 supply1373unique sequence names(3814HB,6806HB,31210HB), mechanically indexed with page provenance. Exact shared/replacement mixtures, colored maps, native routing/full scaffold and12HBsources unverified. Table2PDF82visual audit confirms inconsistent4HB-Ref counts and6HBvariant label relative to Table1; originals retained.'
 qs=['Acquire/read main; verify scaffold identities, primary dates and exact design origins.','Map indexed sequence pools to every experimental gap-density/length variant using colored layouts; verify substitutions and omissions, not row-count completeness.','Inspect remaining SI figures and sequence pages visually; resolve Table1/2variant label and4HB-Ref count inconsistencies.','Trace12HBhinge source/parent and separate computed-only cross-sections; inspect refs5/10/16 before asserting reuse.','Continue remaining20B0016inputs and priority author/citation discovery.']
 p=next(p for p in L.read('publication_reviews') if p['registry_key']==k)
 p.update(review_stage='design_sources_reviewed',relevance='design_bearing',design_contributions=['modified_design'],catalog_eligibility='unresolved',access='SI_available; main_pending',rationale=note,reviewer='Codex targeted SI text/figure/table review plus sequence indexing',run_id=rid,date=L.DATE,unresolved_questions=qs)
 if ev not in p['evidence']:p['evidence'].append(ev)
 L.upsert('publication_reviews',p,'Record experimentally supported variants while preserving incomplete sequence mapping')
 did='RDE0058';old=next((d for d in L.read('design_evidence') if d['design_id']==did),None);assert old is None or k in old['publication_keys']
 L.upsert('design_evidence',dict(design_id=did,publication_keys=[k],named_objects=['4HB square-lattice gap variants','6HB honeycomb gap/crossover/omission variants','10HB honeycomb gap variants','12HB hinge variants; parent unresolved'],identity_status='Source group spans four experimental families; not a count of distinct geometries or complete variant sets',lattice_decision='4HBsquare and6HB/10HBhoneycomb explicit;12HBhinge exact geometry/source unresolved. Computational cross-sections separately retained in rationale.',catalog_eligibility='unresolved',core_variant_composition=note,relationships=[],variant_links=[],source_completeness='not_verified',source_files=[ev],evidence=[ev],outstanding_checks=qs,review_stage='source_reviewed',review_run=rid,run_id=rid,date=L.DATE,legacy_record={}), 'Preserve experimental source group and unresolved variant mapping')
 refs=re.findall(r'(?ms)^\s*(\d+)\.\s*(.*?)(?=^\s*\d+\.\s|\Z)','\n'.join(pages[110:]).split('Supplementary references',1)[1]);assert [int(n) for n,_ in refs]==list(range(1,19))
 for n,t in refs:
  L.upsert('discovery_edges',dict(edge_id='B0016:engineered-defects:SI-ref'+n,source_key=k,target_key='citation:engineered-defects:SI:'+n,relation='cites',citation=' '.join(t.split()),evidence_url=ev['url'],local_file=ev['local_file'],sha256=ev['sha256'],locator='SI ref'+n+' PDF111–112',reconciliation_state='pending_identity_date_scope_reconciliation',run_id=rid,date=L.DATE),'Retain complete18SIreference list')
 b=next(b for b in L.read('batches') if b['batch_id']==rid);b['completed_actions'].append('Reviewed5of25: engineered-defectSI; indexed1373source rows and experimental labels, separated computed cases, recorded two visually verified table inconsistencies.18SIrefs saved.')
 b.update(after_counts=L.counts(),validation=[L.validate()],next_queue=qs)
 L.upsert('batches',b,'Save5of25progress; source completeness and full review remain open');print(len(variants),L.validate())
if __name__=='__main__':main()
