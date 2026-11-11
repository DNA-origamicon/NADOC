"""Finish B0013 first passes without treating unresolved sources as exclusions."""
import json
import ledger as L
from review_batch_0001 import evidence

ROWS = [
 ('10.1088/0957-4484/26/4/044001', 'metadata_screened', 'uncertain',
  'Primary abstract describes solid silicon-nitride nanopores, ion-beam sculpting, annealing, TEM drilling, tomography and DNA translocation. It does not establish origami use. Retain uncertain until full experimental scope is inspected; PMC4288979 access challenge is not source absence.'),
 ('10.1021/ct5007482', 'metadata_screened', 'design_bearing',
  'Primary abstract models substrate diffusion around glucose oxidase and horseradish peroxidase on an origami scaffold using GeomBD. Scaffold obstruction and enzyme orientation/separation establish theoretical reuse at the system level. Exact DNA representation, parent design and complete source remain unresolved. Publisher date fields conflict between December2 and December18,2014; do not certify an exact first-online day. No simulation executed.'),
 ('10.1039/c4ra15451g', 'metadata_screened', 'design_bearing',
  'Primary abstract describes seeding thin DNA origami with5nm gold nanoparticles while varying hybridization time, magnesium, particle-to-origami ratio and particle age. These are preparation variants, not demonstrated distinct DNA cores. Exact origami shape, parent and staple/native sources await main/SI inspection. Publisher first published2014-12-23, distinct from2015issue.'),
 ('10.1063/1.4921957', 'metadata_screened', 'uncertain',
  'Primary abstract introduces oxDNA2 changes including major/minor grooves and interactions intended to improve large-origami modeling. This alone does not identify an actually reused origami benchmark. Main text and supplementary design examples remain necessary before inclusion/exclusion. No simulation executed.'),
 ('10.1073/pnas.1408869112', 'fulltext_reviewed', 'design_bearing',
  'Inspected primary mechanism-design and simple-motion sections: hinges, two slider versions, crank-slider and Bennett linkage. Slider has30-helix outer tube around6-helix inner bundle with42-helix base. Version1 uses49/28nt connections and15nt hairpin-suppression staples; version2 uses86/96nt connections with three18–20nt staples per connection. Full routing, sequence tables and per-mechanism scaffold compositions remain unaudited. Linked SI PDF and sequence XLS returned browser challenges; links are not acquired complete sources. First online2015-01-05, issueJanuary20.')
]

def main():
 pubs = {p['registry_key']: p for p in L.read('publication_reviews')}
 for key, stage, rel, note in ROWS:
  p = pubs[key]
  for name in ['batch_0013_final_primary1.json', 'batch_0013_final_primary2.json', 'batch_0013_final_open.json']:
   ev = evidence(L.HERE/name, 'https://doi.org/'+key, 'Primary publisher/PubMed search and opened source contexts; see record rationale for inspection depth')
   if ev not in p['evidence']: p['evidence'].append(ev)
  p.update(title=p['legacy_record']['publication'], publication_type=['journal_article'], review_stage=stage, relevance=rel,
   design_contributions=['uncertain'], catalog_eligibility='unresolved', access='partial', rationale=note,
   unresolved_questions=['Inspect full main and SI, identify exact represented origami designs and parent sources.', 'Audit native routing, scaffold/staple/variant completeness and narrow catalog eligibility.', 'Follow backward/forward citations and author histories.'],
   reviewer='Codex primary metadata or specified full-text section inspection', run_id='B0013', date=L.DATE)
  L.upsert('publication_reviews', p, 'Finish first-pass screening with explicit unresolved source depth')
 b = next(b for b in L.read('batches') if b['batch_id']=='B0013')
 pubs = {p['registry_key']:p for p in L.read('publication_reviews')}
 assert len(b['input_keys']) == 25 and all(pubs[k]['review_stage']!='unreviewed' for k in b['input_keys'])
 action = 'All25 B0013 inputs first-pass screened; source completeness and bibliographic closure remain open.'
 if action not in b['completed_actions']: b['completed_actions'].append(action)
 b.update(status='completed', unresolved_keys=[k for k in b['input_keys'] if pubs[k]['unresolved_questions']], after_counts=L.counts(), validation=[L.validate()], next_queue=['Acquire motion SI PDF and sequence XLS through available public endpoints; audit exact mechanisms.', 'Inspect nanopore and oxDNA2 main texts before relevance decisions.', 'Enumerate FNANO2010 schedule; continue author/citation/counterpart discovery.', 'Select balanced B0014, preserving all unresolved source follow-ups.'])
 L.upsert('batches', b, 'Complete first passes only; preserve all unresolved follow-ups')
 out = dict(batch_id='B0013', first_pass_count=25, input_count=25, unresolved_followup_count=len(b['unresolved_keys']), complete_source_certifications=0, validation=L.validate(), counts=L.counts())
 L.atomic(L.HERE/'batch_0013_complete_audit.json', json.dumps(out, indent=2)+'\n')
 print(out)

if __name__ == '__main__': main()
