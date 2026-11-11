"""Five rotating records, with primary evidence depth and publication types."""
import json
import ledger as L
from review_batch_0001 import evidence
ROWS=[
('10.1074/jbc.r115.638452','review','metadata_screened','background_or_review','batch_0013_rotation_primary.json','https://pubmed.ncbi.nlm.nih.gov/25957410/','Primary abstract and publisher MINIREVIEW heading/date',
 'Review of in-vitro microtubule/MAP systems; primary abstract and minireview heading support review classification. No new origami design inferred from metadata. Exact origami passages and cited studies need full-text inspection. Publisher first online2015-05-08, distinct fromJulyissue.'),
('10.1089/ten.teb.2014.0494','review','metadata_screened','background_or_review','batch_0013_rotation_primary.json','https://journals.sagepub.com/doi/abs/10.1089/ten.TEB.2014.0494','Primary review abstract and publisher first-online date',
 'Review surveys DNA machines for biomedical applications. Metadata establishes review status, not new-design absence across all text. Publisher explicitly reports first online2014-12-29; PubMedarticle-date2015-02-09 andJune2015issue are different date fields. Full origami attribution and bibliography inspection pending; author-hosted PDF located in saved search.'),
('10.1080/07391102.2015.1032691','conference_abstract','metadata_screened','design_bearing','batch_0013_abstract74_primary.json','https://www.tandfonline.com/toc/tbsd20/33/sup1?nav=tocList','Publisher supplement Abstract74 entry; adjoining-item PDF snippet includes abstract74text; Caltech publication history corroboration',
 'Numbered abstract74 in journal supplement, authorsTikhomirov/Petersen/Qian; not a full journal design article. Primary abstract describes symmetric square origami units assembled into finite/unbounded Truchet-pattern arrays using double-stranded labels and stacking/short sticky ends. No complete routing/sequence proof from abstract. PublisherTOC reports online2015-06-23; exact conference/event metadata still pending. Primary Caltech history identifies possible2016BiophysJabstract10.1016/j.bpj.2015.11.243 and2017journal10.1038/nnano.2016.256 counterparts; do not merge without scope comparison. DOI1032690PDF belongs to neighboring abstract and is only evidence for shared-page text, not DOIreplacement.'),
('10.1093/nar/gkv994','journal_article','fulltext_reviewed','not_origami','PMC4787745.xml','https://doi.org/10.1093/nar/gkv994','Abstract; Methods sequence/conformer definitions; section survey; origami comparison paragraph andref73',
 'Work simulates telomeric G-hairpins, duplexes, triplexes and quadruplex intermediates using short sequences and PDB-derived conformers. Origami experiment is prior evidence from Sugiyama group ref73, not a scaffold present in these simulations. Same-agent scope audit of methods and stated objects supports exclusion from origami-design census; citation remains a discovery lead. No simulations executed.'),
('10.1038/srep08721','journal_article','fulltext_reviewed','not_origami','PMC4348642.xml','https://doi.org/10.1038/srep08721','Abstract; Discussion; complete Methods; origami comparison paragraph',
 'Implemented SNP assay uses80bpPCRproducts with9nttoeholds and80ntdisplacing strands plus protector oligos, combining3/4-waybranchmigration. Origami-based steric-hindrance assay is attributed toSubramanian etalref34 as comparison. Primary Methods/Discussion scope audit supportsnot_origami exclusion; no origami template used in described experiments. Retain cited assay source for discovery.')]
def main():
 pubs={p['registry_key']:p for p in L.read('publication_reviews')}
 for key,typ,stage,rel,name,url,loc,note in ROWS:
  path=L.ROOT/'assets/sources/pre2020-expansion'/name if name.endswith('.xml') else L.HERE/name
  e=evidence(path,url,loc);p=pubs[key]
  if e not in p['evidence']:p['evidence'].append(e)
  p.update(title=p['legacy_record']['publication'],publication_type=[typ],review_stage=stage,relevance=rel,design_contributions=['uncertain'] if rel=='design_bearing' else [],catalog_eligibility='excluded' if rel=='not_origami' else 'unresolved',access='partial',rationale=note,unresolved_questions=['Follow primary citations and exact design/counterpart sources; full bibliography and author-history coverage pending.'],reviewer='Codex explicit primary metadata or named full-text scope audit',run_id='B0013',date=L.DATE)
  dates={'10.1074/jbc.r115.638452':'2015-05-08','10.1089/ten.teb.2014.0494':'2014-12-29','10.1080/07391102.2015.1032691':'2015-06-23'}
  if key in dates:p['date_evidence']={'date':dates[key],'meaning':'Publisher first online; distinguish issue and PubMedarticle dates','source':e,'primary_verified':True}
  L.upsert('publication_reviews',p,'Screen rotated record with explicit source depth/type')
 for source,target,rel,name,loc in [('10.1093/nar/gkv994','10.1002/anie.201308903','cites','PMC4787745.xml','ref73explicitDOI'),('10.1080/07391102.2015.1032691','10.1016/j.bpj.2015.11.243','possible_counterpart','batch_0013_abstract74_primary.json','Caltech author history; exact scope pending'),('10.1080/07391102.2015.1032691','10.1038/nnano.2016.256','possible_counterpart','batch_0013_abstract74_primary.json','Caltech author history; exact scope pending')]:
  path=L.ROOT/'assets/sources/pre2020-expansion'/name if name.endswith('.xml') else L.HERE/name
  e=evidence(path,'https://doi.org/'+source,loc)
  L.upsert('discovery_edges',dict(edge_id='B0013:rotating:'+source+':'+target,source_key=source,target_key=target,relation=rel,evidence_url=e['url'],local_file=e['local_file'],sha256=e['sha256'],locator=loc,reconciliation_state='source_identity_or_scope_pending',run_id='B0013',date=L.DATE),'Preserve source and counterpart leads without merging')
 b=next(b for b in L.read('batches') if b['batch_id']=='B0013');pubs={p['registry_key']:p for p in L.read('publication_reviews')}
 action='Five rotating records screened:two reviews,one numbered conference abstract,two nonorigami primary studies;20of25firstpasses.'
 if action not in b['completed_actions']:b['completed_actions'].append(action)
 for k in ['10.1093/nar/gkv994','10.1038/srep08721']:
  if k not in b['exclusion_audit']['sample']:b['exclusion_audit']['sample'].append(k)
 b['exclusion_audit']['reason']='Same-agent primary method/object context checks; no independent reviewer claim.'
 b.update(after_counts=L.counts(),unresolved_keys=[k for k in b['input_keys'] if pubs[k]['review_stage']=='unreviewed'],validation=[L.validate()],next_queue=['Nanopore044001,enzyme modelct5007482,goldseedingc4ra15451g,oxDNA1.4921957,motionpnas1408869112','Conferenceabstract74counterparts andall prior source/discovery followups'])
 L.upsert('batches',b,'Save20of25firstpasses;5unreviewed inputs')
 L.atomic(L.HERE/'batch_0013_rotation_first_audit.json',json.dumps(dict(reviewed_keys=[r[0] for r in ROWS],first_pass_count=20,input_count=25,validation=L.validate(),counts=L.counts()),indent=2)+'\n');print(L.validate())
if __name__=='__main__':main()
