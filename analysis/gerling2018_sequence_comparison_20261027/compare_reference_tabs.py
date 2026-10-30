"""Compare all candidate lists using one domain matcher and unchanged topology."""
from pathlib import Path
import json,hashlib,csv
import openpyxl
from backend.core.models import Design,StrandType
from backend.core.sequences import assign_custom_scaffold_sequence,assign_staple_sequences,P7560_SEQUENCE
from backend.core.image_sequence_matches import match_design_domains
O=Path(__file__).resolve().parent
src=Path('/home/jojo/Work/NADOC/workspace/Gerling2018_FigS1_42hb_CONTROL_traced_staples_v4.nadoc')
pub=Path('/media/jojo/Archive/NADOC_archive/design_reconstruction/gerling2018/aau1157_Table_S1.xlsx')
d=Design.model_validate_json(src.read_text());before=d.model_dump_json();w=openpyxl.load_workbook(pub,data_only=True)
rows=[];details={}
for register in [0,3541]:
 candidate,_,_=assign_custom_scaffold_sequence(d.model_copy(deep=True),P7560_SEQUENCE[register:]+P7560_SEQUENCE[:register]);candidate=assign_staple_sequences(candidate)
 for name in ['42hb (1)-(3)','42hb (1)-(4)','Brick']:
  refs=[{'index':i,'sequence':s} for i,s in list(w[name].values)[1:] if isinstance(s,str)]
  report=match_design_domains(candidate,12,{'title':name,'sequences':refs});hits=report['matches']
  core_set=lambda hs:{(h['strand_id'],h['domain_index']) for h in hs}
  covered={(h['strand_id'],h['domain_index'],i) for h in hits for i in range(h['offset'],h['offset']+h['length'])}
  pubseq={r['sequence'] for r in refs}
  row={'sheet':name,'test_register_0based':register,'published_oligos':len(refs),'matched_domains_12plus':len(core_set(hits)),'matched_staples_12plus':len({h['strand_id'] for h in hits}),'matched_domains_16plus':len(core_set([h for h in hits if h['length']>=16])),'whole_domains_12plus':len(core_set([h for h in hits if h['full_domain']])),'unique_domain_bases_covered_12plus':len(covered),'exact_whole_staples':sum(s.sequence in pubseq for s in candidate.strands if s.strand_type==StrandType.STAPLE)}
  rows.append(row);details[f'{name}@{register}']=report;print(row,flush=True)
assert before==d.model_dump_json()
out={'source_sha256':hashlib.sha256(src.read_bytes()).hexdigest(),'workbook_sha256':hashlib.sha256(pub.read_bytes()).hexdigest(),'method':'Exact same-orientation >=12nt maximal matches within individual duplex domains. Offset3541 is a hypothetical in-memory reassignment on unchanged, truncated topology, not a validated reconstruction. Counts deduplicate domains and covered bases.','summary':rows,'details':details}
(O/'reference_tab_comparison.json').write_text(json.dumps(out,indent=2)+'\n')
with (O/'reference_tab_comparison.csv').open('w') as f:
 writer=csv.DictWriter(f,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
