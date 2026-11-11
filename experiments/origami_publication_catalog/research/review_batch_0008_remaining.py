"""Explicit primary-source decisions for B0008; no automatic relevance rules."""
import ledger as L
from review_batch_0001 import evidence

def local(name,url,locator):
 return evidence(L.ROOT/'assets/research-20261105'/name,url,locator)
def web(url,locator,rotary=False):
 return evidence(L.HERE/('batch_0008_rotary_web_evidence.json' if rotary else 'batch_0008_remaining_web_evidence.json'),url,locator)

def main():
 rows={p['registry_key']:p for p in L.read('publication_reviews')}
 def review(doi,relevance,stage,ev,rationale,questions,**extra):
  p=rows[doi]
  p.update(relevance=relevance,review_stage=stage,evidence=ev,rationale=rationale,unresolved_questions=questions,design_contributions=['uncertain'],catalog_eligibility='unresolved',access='partial',reviewer='Codex inspectable primary source review',run_id='B0008',date=L.DATE,**extra)
  L.upsert('publication_reviews',p,'Review remaining rotated record using specified primary sections; preserve unresolved source/identity questions')
 review('10.1039/c3cc41707g','design_bearing','metadata_screened',[
  web('https://pubs.rsc.org/en/content/articlelanding/2013/cc/c3cc41707g','b8rsc primary RSC landing search result: Abstract, article type and dates'),
  web('https://www.rsc.org/suppdata/cc/c3/c3cc41707g/c3cc41707g.pdf','b8rsc primary SI indexed excerpt: Materials and Methods only; direct PDF404')],
  'Primary abstract reports long RNA scaffold folded by short DNA staples; retained as hybrid-origami design evidence, not silently treated as conventional all-DNA catalog material. SI indexed Methods identifies pUC19 PCR template/T7 transcription and points to FigS1 sequences. Abstract1:1 staple ratio is a tested condition; indexed regular Methods uses1:10 unless specified. Full SI was not acquired.',
  ['Acquire complete SI and inspect FigS1 routing/sequences and all design variants.','Resolve RNA-scaffold chemistry against narrower catalog scope before any eligibility decision.','Reconcile related Pengfei Wang Purdue dissertation; separate publication/version record, not automatic duplicate.'],publication_type=['journal_article'],primary_dates={'first_online':'2013-04-03','issue_year':2013})
 review('10.1063/1.4822042','background_or_review','fulltext_reviewed',[
  local('hinckley-2013-pmc.html','https://pmc.ncbi.nlm.nih.gov/articles/PMC3808442/','Results structural properties/persistence length/melting/rate constants; Discussion applications; Conclusion')],
  'Primary Results benchmark32bp duplex structural properties, ss/dsDNA persistence lengths, duplex/hairpin melting and hybridization. Conclusion presents DNA origami as a possible future application. Inspected sections do not present, modify or simulate an origami design. Retained as background method, without inventing a design from a keyword mention.',
  ['Inspect supplementary material and remaining methods/appendices before closing all source checks.','Keep any later3SPN origami applications as distinct publications.'],publication_type=['journal_article'])
 review('10.1080/07391102.2013.786383','design_bearing','metadata_screened',[
  local('nanophotonic-2013-crossref.json','https://api.crossref.org/works/10.1080/07391102.2013.786383','Publisher-deposited vol31sup1pp90–91 metadata and Deng reference DOI'),
  web('https://www.tandfonline.com/doi/full/10.1080/07391102.2013.786383','b8search2 primary publisher abstract and two references'),
  web('https://www.tandfonline.com/toc/tbsd20/31/sup1','b8primary3 publisher issue title Book of Abstracts. Albany2013: The18th Conversation')],
  'Conference abstract141 reports origami-patterned QDs and AuNP/fluorophore assemblies and explicitly cites Deng2012 and Pal2013(in revision). Publisher issue identifies a book of abstracts; Crossref generic journal-article type is insufficient. Abstract supports design relevance but not complete synthesis/design evidence. Crossref link to DOI10.1080/10256018808623883 is inconsistent and must not be used as this record PDF.',
  ['Reconcile Deng10.1021/ja3081023 and Pal Quantum efficiency modification journal publication; inspect full designs there.','Retain conference abstract independently; no automatic canonical work merge.'],publication_type=['conference_abstract'],primary_dates={'online':'2013-05-29','crossref_print_year_month':'2013-01','date_discrepancy_retained':True})
 review('10.1007/978-3-642-36077-0_10','background_or_review','metadata_screened',[
  local('liu-fan-2013-chapter.html','https://link.springer.com/chapter/10.1007/978-3-642-36077-0_10','Publisher chapter identity, abstract and References preview')],
  'Liu/Fan chapter207–224 explicitly summarizes structural evolution, assembly and applications. Classified as background/review from the primary abstract, with full chapter unavailable; no new original design inferred. Accessible bibliography is a discovery source.',
  ['Acquire full chapter if needed to assess any original design contributions beyond abstract.','Enumerate complete visible bibliography and reconcile its targets without relevance caps.'],publication_type=['book_chapter'],primary_dates={'first_online':'2013-01-01'})
 review('10.1016/j.bpj.2012.11.019','uncertain','metadata_screened',[
  local('kauert-2013-crossref.json','https://api.crossref.org/works/10.1016/j.bpj.2012.11.019','vol104issue2S1p1a; full six-author list; publisherPIIS0006349512012404'),
  local('kauert-2013-symposium.pdf','https://www.biophysics.org/Portals/0/BPSAssets/Subgroups/Documents/Molecular_2013.pdf','Society symposium program p1; Dominik Kauert matching title10:00AM Feb2,2013 Philadelphia')],
  'Crossref supplement/page1a metadata plus exact-title/first-author society symposium program support a conference abstract identity. Primary abstract text remains inaccessible in attempted Cell/DOI routes. Program establishes presentation, not specific design or complete sources; relevance stays uncertain pending primary abstract/full counterpart review.',
  ['Acquire primary abstract PII S0006349512012404.','Reconcile bending/torsion measurement and torque-sensor journal counterparts; title/program alone cannot establish exact design reuse.'],publication_type=['conference_abstract'])
 review('10.1021/ja310454k','design_bearing','metadata_screened',[
  web('https://pubs.acs.org/doi/10.1021/ja310454k','Primary ACS indexed abstract and date fields; direct page403',True)],
  'Primary abstract reports B–Z transition rotary motor observed within frame-shaped DNA origami, with motor/control assays. Frame and motor contribution identity remain unresolved. Publisher header says December19,2012 while explicit Published Online field says January11,2013 and issue January23,2013; retain discrepancy rather than silently choose a date.',
  ['Acquire ACS SI via existing public paced downloader and inspect frame routing, motor/control sequences and movies.','Resolve header/online date discrepancy using source version history.','Establish parentage of frame design before new-core counting.'],publication_type=['journal_article'],primary_dates={'header':'2012-12-19','published_online_field':'2013-01-11','issue':'2013-01-23','date_discrepancy_retained':True})
 review('10.1038/ncomms2690','design_bearing','design_sources_reviewed',[
  local('shen-2013-graphene.html','https://www.nature.com/articles/ncomms2690','Results Metallized DNA lithography/Fig1; Methods DNA nanorings, letter junctions, nanoribbons; ref24'),
  local('jin-2013-graphene-si.pdf','https://static-content.springer.com/esm/art%3A10.1038%2Fncomms2690/MediaObjects/41467_2013_BFncomms2690_MOESM549_ESM.pdf','All3pages text: FigS1 caption, TablesS1–S2; morphology/Raman, no staple set')],
  'Jin et al. use p7308-scaffold3D-origami rings as lithography templates (designed13nm width75nm outer diameter; parentref24Dietz2009). Letter junctions L/X/Y/Z and nanoribbons are explicitly SST, not additional origami cores. Supplement3pages records morphology/Raman data rather than sequences. Existing acquisition filename shen-2013-graphene.html is only a filename; actual first author is Zhong Jin.',
  ['Map exact ring variant to10.1126/science.1174251 parent source and check lattice/routing/staples.','Do not count SST letters or processed graphene products as origami cores.'],publication_type=['journal_article'])
 p=next(p for p in L.read('publication_reviews') if p['registry_key']=='10.1038/ncomms2690');p['design_contributions']=['reused_design'];L.upsert('publication_reviews',p,'Record explicitly attributed ring reuse')
 ev=p['evidence'][0];target='10.1126/science.1174251'
 L.upsert('discovery_edges',dict(edge_id='reuses_design_from:10.1038/ncomms2690:'+target,source_key=p['registry_key'],target_key=target,relation='reuses_design_from',evidence_url=ev['url'],local_file=ev['local_file'],sha256=ev['sha256'],locator='Methods Preparation of DNA nanorings and ref24',reconciliation_state='bibliographic_parent_matched; exact_design_variant_pending',run_id='B0008',date=L.DATE),'Trace ring source while keeping exact variant unresolved')
 review('10.1039/c2cc37257f','design_bearing','metadata_screened',[
  web('https://pubs.rsc.org/en/content/articlelanding/2013/cc/c2cc37257f','b8primary3 primary RSC abstract/date fields'),
  web('https://www.rsc.org/suppdata/cc/c2/c2cc37257f/c2cc37257f.pdf','b8primary3 primary SI indexed Methods excerpt; direct PDF404')],
  'Primary abstract reports surface-loop orientation variants affecting origami2D crystallization; vertical connected loops yield micrometer-scale crystals. SI indexed excerpt identifies M13mp18 scaffold and separate main staples, loop sequences and connecting strands. Complete designs and sequence sets have not been inspected. First-online2012 differs from2013issue year and is retained.',
  ['Acquire full SI/primary article and enumerate all loop variants and controls.','Separate modified tile core from connecting strands and higher-order crystals.','Verify lattice and source completeness.'],publication_type=['journal_article'],primary_dates={'first_online':'2012-11-23','issue_year':2013})
 b=next(b for b in L.read('batches') if b['batch_id']=='B0008');b['status']='completed';b.setdefault('completed_actions',[]).append('Finished eight remaining first passes: two conference abstracts, review chapter, background simulation method and four design-bearing articles; section depth and access gaps explicit.')
 b.update(after_counts=L.counts(),validation=[L.validate()],unresolved_keys=b['input_keys'],next_queue=['Enumerate Liu/Fan chapter and Jin graphene bibliographies; reconcile abstract141journal counterparts.','Continue FNANO2014schedule and remaining2006–2014programs/abstract routes.','Resume balanced B0009 plus named candidate and source gaps; no full source closure claimed.'])
 L.upsert('batches',b,'Complete bounded first-pass batch25/25 with all source gaps retained')
 print(L.validate())
if __name__=='__main__':main()
