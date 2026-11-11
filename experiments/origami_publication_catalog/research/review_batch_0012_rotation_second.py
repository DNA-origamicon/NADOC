"""Four rotated records: primary metadata, database identity and review context."""
import json
import ledger as L
from review_batch_0001 import evidence

def main():
 pubs={p['registry_key']:p for p in L.read('publication_reviews')}
 web=L.HERE/'batch_0012_rotation_metadata.json'
 meta=evidence(web,'https://www.eurekaselect.com/article/62352','Publisher title/authors/2014issue/pages and abstract; main not acquired')
 pdb=evidence(L.ROOT/'assets/research-20261105/pdb4v5x-entry-metadata.json','https://data.rcsb.org/rest/v1/core/entry/4V5X','Primary citation, accession dates, split-entry relations andEMD-2210; metadata only')
 hist=evidence(web,'https://www.rcsb.org/versions/4V5X','Version history:2014release; pre2020major revisions and2024update')
 syn=evidence(L.ROOT/'assets/sources/PMC4244866.xml','https://doi.org/10.3389/fbioe.2014.00060','Abstract explicitly review; section-title survey of design/assembly/prototyping tools; not full article audit')
 apt=evidence(L.ROOT/'assets/sources/pre2020-expansion/PMC3958272.xml','https://doi.org/10.3390/s140203156','Abstract review; aptamer-gated nanorobot discussion andFig6caption; ref35Douglas/Bachelet/Church2012')
 rows=[('10.2174/138527281815140916092815','journal_article','metadata_screened','design_bearing',[meta],
 'Primary abstract reports toehold-mediated strand displacement on DNA origami chip with AuNPs for SNP detection. The particle/strand exchange modification is supported, but no core shape, scaffold, lattice or complete sequence set can be inferred from abstract. Publisher page offers purchase; no private authentication attempted and main remains unacquired.',
 ['Acquire main/SI via public or institutional route and inspect chip parent/core/modified oligos.','Verify exact first-online date;2014issue supported, legacy day not revalidated.']),
 ('10.2210/pdb4v5x/pdbx','dataset','metadata_screened','design_bearing',[pdb,hist],
 'Structural database deposition, not an additional journal article. RCSB primary citation is Bai2012PNAS10.1073/pnas.1215713109.4V5Xreleased2014-07-09 with deposition date2012-10-09; supersedes split2YMF/2YMG/2YMH/2YMI/2YMR and associatesEMD-2210. Metadata reports11.5Angstrom cryoEMpointer object. Pre2020model revisions and2024metadata update must not be conflated; currently retrieved metadata is not a frozen2019model. Coordinate/model availability does not certify authoring source completeness. No coordinates downloaded, reconstructed or simulated.',
 ['Inspect historical release metadata and linked primary/SI/native sources; retain dataset/journal identities.','Reconcile split entries and EMDB without counting them as separate core designs.']),
 ('10.3389/fbioe.2014.00060','review','metadata_screened','background_or_review',[syn],
 'Author abstract explicitly describes review of synthetic-biology design-cycle tools. Section survey covers chassis/biopart engineering,DNA assembly/genome engineering and rapid prototyping. This establishes review status, not a complete absence-of-origami audit. No new origami design evidence in inspected material; retain background and open citation review.',
 ['Inspect relevant full text and bibliography for overlooked origami-related sources.']),
 ('10.3390/s140203156','review','fulltext_reviewed','background_or_review',[apt],
 'Aptamer-smart-materials review attributes the hexagonal hinged DNA-origami nanorobot to Church/coauthors ref35; discusses aptamer locks/cargo as prior work. Figure6is adapted from the cited2012paper. No new origami-core source inferred from review description. Citation is a discovery route, not independent design proof.',
 ['Enumerate full bibliography and inspect original nanorobot source/variants.'])]
 for key,typ,stage,rel,evs,note,qs in rows:
  p=pubs[key]
  for e in evs:
   if e not in p['evidence']:p['evidence'].append(e)
  p.update(title=p['legacy_record']['publication'],publication_type=[typ],review_stage=stage,relevance=rel,design_contributions=['uncertain'],catalog_eligibility='unresolved',access='partial',rationale=note,unresolved_questions=qs,reviewer='Codex primary context inspection',run_id='B0012',date=L.DATE)
  if typ=='dataset':p['date_evidence']={'date':'2014-07-09','meaning':'4V5Xinitial release, distinct from2012deposition/journal and later revisions','source':pdb,'primary_verified':True}
  L.upsert('publication_reviews',p,'Screen rotated record with explicit evidence depth and publication type')
 for source,target,relation,ev,locator in [('10.2210/pdb4v5x/pdbx','10.1073/pnas.1215713109','has_primary_citation',pdb,'rcsb_primary_citation'),('10.3390/s140203156','10.1126/science.1214081','cites',apt,'XMLref35 and review attribution')]:
  L.upsert('discovery_edges',dict(edge_id='B0012:relation:'+source+':'+target,source_key=source,target_key=target,relation=relation,evidence_url=ev['url'],local_file=ev['local_file'],sha256=ev['sha256'],locator=locator,reconciliation_state='explicit_primary_relation' if target in pubs else 'target_identity_pending',run_id='B0012',date=L.DATE),'Retain explicit source relation without merging distinct publication types')
 b=next(b for b in L.read('batches') if b['batch_id']=='B0012');pubs={p['registry_key']:p for p in L.read('publication_reviews')}
 action='Reviewed4rotating records: SNPchip primary abstract,4V5Xdataset metadata,synthetic-biology review andaptamer review attribution.'
 if action not in b['completed_actions']:b['completed_actions'].append(action)
 b.update(after_counts=L.counts(),unresolved_keys=[k for k in b['input_keys'] if pubs[k]['review_stage']=='unreviewed'],next_queue=['Bionanostructure protein review andsupercritical-angle microscopy','PolyploidyDNAstorage article,HS-AFMreview,cancer nanomedicine review','All source-completeness and discovery follow-ups'],validation=[L.validate()])
 L.upsert('batches',b,'Save20of25screened,5unreviewed inputs')
 L.atomic(L.HERE/'batch_0012_rotation_second_audit.json',json.dumps({'reviewed_keys':[r[0] for r in rows],'batch_screened':20,'batch_inputs':25,'validation':L.validate(),'counts':L.counts()},indent=2)+'\n');print(L.validate())
if __name__=='__main__':main()
