"""Three primary-source reviews with explicit component/assembly distinctions."""
import json
import ledger as L
from review_batch_0001 import evidence
ROWS=[['10.1021/jacs.8b06146', [['12484238-ja8b06146_si_001.pdf', '12484238', 'SI p2oligonucleotide table; source context checked against primary XML']], 'Primary main XML Introduction, Conclusion, all Results subsection openings and Experimental subsection openings inspected. Implemented template is benzene-1,3,5-tricarboxamide polymer bearing10ntDNAhandles; computing modules are strand displacement,ANDgates,CHA,HCR. Origami is prior-work comparison; microscopy flow-chamber protocol is adapted from an origami study without using an origami object. SI oligo table agrees withBTAhandles/circuit strands. Same-agent second-pass scope audit supports not_origami exclusion from design census; cited origami literature remains a discovery route.'], ['10.1021/acsami.8b11167', [['12714815-am8b11167_si_001.pdf', '12714815', 'SI p3origami method; TableS1header/p6; TableS2p12,TableS3p13,SchemeS1captionp14']], 'M13mp18rectangle90x60x2nm carries three linear AuNRbinding regions with seven capture strands each. Methods omit side staples100–111and205–216, but modified capture table includes102(R3)and215(R1); exact replacement/omission interpretation unresolved. TableS2 specifiesR1positions215,201,200,177,176,152,153;R2positions123,13,119,18,116,24,112;R3positions31,32,55,56,79,80,102. Three complementary thiolated AuNRoligos are separate. AuNRdimers/trimers and small/large rod variants are particle assemblies on the platform, not automatically distinct origami cores. Full base table, scaffold sequence and per-assembly subsets remain unaudited.'], ['10.1021/acsomega.8b00934', [['12809096-ao8b00934_si_001.pdf', '12809096', 'Entire9-page SI text/caption/table survey, especiallyTableS1p3 andTableS2p9']], 'Drug-loading study uses five named origami objects:6HB,60HB,Zshape,triangle,bowtie. TableS1reports basepairs/unpaired nucleotides respectively7140/109,5460/1789,6942/1155,7196/51,6962/1167. These are source-reported counts spanning scaffold/staples/overhangs, not independently verified scaffold lengths. Methylene-blue loading and netropsin competition are binding conditions, not newly authored DNAcore variants. Salmon-testes dsDNA is a non-origami comparator. SI does not supply complete construction sequences; main/parent/native sources and exact lattice/source eligibility remain open.']]
def main():
 pubs={p['registry_key']:p for p in L.read('publication_reviews')}
 for key,sources,note in ROWS:
  p=pubs[key]
  for name,fid,loc in sources:
   e=evidence(L.ROOT/'assets/sources/acs-expansion-20261104'/name,'https://ndownloader.figshare.com/files/'+fid,loc)
   if e not in p['evidence']:p['evidence'].append(e)
  if key=='10.1021/jacs.8b06146':
   ev=evidence(L.ROOT/'assets/sources/pre2020-expansion/PMC6077772.xml','https://doi.org/'+key,'Introduction/Conclusion; Results and Experimental subsection openings, microscopy protocol context')
   if ev not in p['evidence']:p['evidence'].append(ev)
  p.update(title=p['legacy_record']['publication'],review_stage='design_sources_reviewed',relevance='design_bearing',design_contributions=['uncertain'],catalog_eligibility='unresolved',access='partial',rationale=note,unresolved_questions=['Inspect main and original/native sources; exact scaffold/base/variant compositions and narrow eligibility.','Audit full sequence lists against per-variant maps and assembly recipes.','Enumerate bibliography and follow citations/author histories.'],reviewer='Codex specified SI context inspection',run_id='B0013',date=L.DATE)
  if key=='10.1021/jacs.8b06146':p.update(review_stage='fulltext_reviewed',relevance='not_origami',design_contributions=[],catalog_eligibility='excluded',unresolved_questions=['Enumerate cited origami studies and reconcile primary source identities.'])
  L.upsert('publication_reviews',p,'Record primary component distinctions and unresolved composition')
 b=next(b for b in L.read('batches') if b['batch_id']=='B0013');pubs={p['registry_key']:p for p in L.read('publication_reviews')}
 action='Next3records inspected:BTAcomputing excluded after primary scope audit; AuNRchirality and drug-loading evidence saved; cumulative11of25screened.'
 if action not in b['completed_actions']:b['completed_actions'].append(action)
 b.update(after_counts=L.counts(),unresolved_keys=[k for k in b['input_keys'] if pubs[k]['review_stage']=='unreviewed'],validation=[L.validate()],next_queue=['Remaining4ACS startingacsnano8b04148','Ten rotating2015records','FNANO2010 and all source/discovery followups'])
 b['exclusion_audit']={'sample':['10.1021/jacs.8b06146'],'reason':'Same-agent second-pass main Results/Methods/Conclusion versus SI scope inspection; BTApolymer not origami. Not an independent reviewer.'}
 L.upsert('batches',b,'Save11of25firstpasses,14unreviewed inputs')
 L.atomic(L.HERE/'batch_0013_fourth_audit.json',json.dumps(dict(reviewed_keys=[r[0] for r in ROWS],first_pass_count=11,input_count=25,validation=L.validate(),counts=L.counts()),indent=2)+'\n');print(L.validate())
if __name__=='__main__':main()
