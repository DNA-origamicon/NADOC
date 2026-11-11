"""Save three inspected supplements at the user-requested stopping point."""
import json
import ledger as L
from review_batch_0001 import evidence
ROWS = [
('10.1021/acs.nanolett.8b04845','14173718-nl8b04845_si_001.pdf','14173718','Sample preparation; Table S1 and definitions; Table S2 modification rows; Fig S6–S16 captions; references', 'design_bearing',
'Rectangular origami uses 7249nt M13mp18, six 5-prime biotin staples and ten 3-prime extensions for external ATTO542 labeling. ATTO647N spacing variants span 1–10bp and 20bp. Table S2 includes the 2bp row. The 10bp variant omits a refill staple. Definitions describe constant dye at 3-prime and variable dye at 5-prime, whereas Table S2 labels constant 5[211] at 5-prime and variable 4[186] at 3-prime (20bp uses 3[192]); retain this unresolved discrepancy. Reference1 is Schmied et al.2013 nanopillars, so precise rectangular parent lineage requires checking. dsDNA model controls are not separate origami cores. Complete per-variant staple reconciliation and native routing remain unaudited.'),
('10.1021/acs.analchem.8b05706','14244926-ac8b05706_si_001.pdf','14244926','SI preparation methods, Table S1, Scheme S1 heading and downstream cell-assay methods; main article not inspected','not_origami',
'Inspected SI constructs protein-scaffolded DNA nanohydrogels from streptavidin conjugates Y1-SA/Y2-SA/Y3-SA and short biotinylated oligos. Table S1 identifies Y1/Y2/Y3, dye/quencher variants and MUC1 aptamer. ATP-responsive network disassembly, doxorubicin loading and aptamer targeting do not establish an origami scaffold/staple design. Same-agent exclusion audit rechecked preparation and oligo table; classification is based on the reported constructed objects, not title keywords. Main article and citation followups remain open.'),
('10.1021/acsmedchemlett.8b00557','14259926-ml8b00557_si_001.pdf','14259926','Fig S1–S4 captions; Table S1 heading/start; self-assembly, QD labeling and LSTDO preparation methods; references','design_bearing',
'Fig S1 identifies STDO as a 47-helix bundle with a caDNAno routing image; Table S1 gives tube oligo sequences. TrDO is a triangle attributed to Rothemund2006 and Liu et al.2012 synthetic vaccines. Both use M13mp18, but exact scaffold length was not established in inspected passages. One biotin staple per origami supports QD labeling. LSTDO is liposome-encapsulated STDO, not a distinct DNA core; drug loading and pH conditions are experimental variants. Full sequence/map reconciliation, modified staple identity, native files and narrow lattice/source eligibility remain pending.')]

def main():
 pubs={p['registry_key']:p for p in L.read('publication_reviews')}
 for key,name,fid,loc,rel,note in ROWS:
  p=pubs[key];e=evidence(L.ROOT/'assets/sources/acs-expansion-20261104'/name,'https://ndownloader.figshare.com/files/'+fid,loc)
  if e not in p['evidence']:p['evidence'].append(e)
  p.update(title=p['legacy_record']['publication'],review_stage='design_sources_reviewed',relevance=rel,design_contributions=['uncertain'] if rel=='design_bearing' else [],catalog_eligibility='excluded' if rel=='not_origami' else 'unresolved',access='partial',rationale=note,unresolved_questions=['Inspect main article and parent/native sources; reconcile complete variant sets where applicable.','Enumerate backward/forward citations and author-history routes.'],reviewer='Codex inspected named SI sections; same-agent methods audit for exclusion',run_id='B0015',date=L.DATE)
  L.upsert('publication_reviews',p,'Record inspected source evidence and explicit limits at stopping point')
 b=next(b for b in L.read('batches') if b['batch_id']=='B0015')
 b['completed_actions'].append('First3of25 inputs inspected and saved; one methods-based nonorigami exclusion; no complete-source certifications.')
 b.update(after_counts=L.counts(),unresolved_keys=list(b['input_keys']),validation=[L.validate()],next_queue=['Resume with10.1021/acs.analchem.8b05407 and remaining11ACS inputs','Ten rotating2015 inputs in B0015','Enumerate FNANO2010 and resume234pending Hao Yan CV identities','Retain all source-completeness and citation followups'])
 L.upsert('batches',b,'Save resumable3of25 first-pass progress; retain all followups')
 audit=dict(batch_id='B0015',first_pass_count=3,input_count=25,reviewed_keys=[r[0] for r in ROWS],exclusion_audit={'key':ROWS[1][0],'basis':'SI preparation and Table S1 manually inspected; protein-scaffolded short-oligo network','reviewer':'same agent','main_article_inspected':False},validation=L.validate(),counts=L.counts())
 L.atomic(L.HERE/'batch_0015_first_audit.json',json.dumps(audit,indent=2)+'\n');print(json.dumps(audit))
if __name__=='__main__':main()
