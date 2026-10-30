"""Bounded Fig.S1 reconstruction. Run from repo root: PYTHONPATH=. .venv/bin/python <this file>."""
from pathlib import Path
import csv, json, hashlib, dataclasses
import openpyxl
from backend.core.models import Design, Domain, Strand, Crossover, HalfCrossover, StrandExtension
from backend.core.sequences import assign_staple_sequences
from backend.core.validator import validate_design
O=Path(__file__).resolve().parent
ROOT=O.parents[1]
SOURCE=ROOT/'workspace/Gerling2018_FigS1_42hb_CONTROL_traced_staples_v4.nadoc'
WB=Path('/media/jojo/Archive/NADOC_archive/design_reconstruction/gerling2018/aau1157_Table_S1.xlsx')
S=(ROOT/'backend/core/p7560.txt').read_text().strip().upper(); assert len(S)==7560
C=S.translate(str.maketrans('ACGT','TGCA'))
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
before=sha(SOURCE); source=Design.model_validate_json(SOURCE.read_text())
w=openpyxl.load_workbook(WB,data_only=True)
refs={int(i):s.strip().upper() for i,s in list(w['42hb (1)-(3)'].values)[1:] if isinstance(s,str)}
# Hypotheses explicitly fix chemistry: ordinary terminal T, cap10T, crossoverTT.
# Match complete cap oligos; do not strip arbitrary T runs from sequence domains.
caps=[]
for pub,q in refs.items():
 for left,right in [(1,10),(10,1)]:
  if not(q.startswith('T'*left) and q.endswith('T'*right)):continue
  core=q[left:-right]
  for first in range(len(S)):
   if ''.join(C[(first-k)%len(S)] for k in range(len(core)))==core:
    caps.append(dict(published=pub,left_T=left,right_T=right,paired_nt=len(core),first_scaffold_index=first,core=core))
# Source path207:19paired bases, forward on row41 bp-5..13. Source path208
# starts row41 bp14..20 then row40 bp20..14 before traversing two more helices.
candidates=[]
for cap in caps:
 if cap['left_T']!=10 or cap['paired_nt']!=19:continue
 register=(cap['first_scaffold_index']-59)%len(S)
 def low41(bp):return (register+54-bp)%len(S)
 def low40(bp):return (register+65+bp)%len(S)
 prefix='T'+''.join(C[low41(b)] for b in range(14,21))+'TT'+''.join(C[low40(b)] for b in range(20,13,-1))+'TT'
 prefix_hits=[i for i,q in refs.items() if q.startswith(prefix)]
 suffix_hits=[]
 for n in range(8,27):
  seq=''.join(C[low41(b)] for b in range(21,21+n))
  for i,q in refs.items():
   if q.endswith('TT'+seq+'T'):suffix_hits.append(dict(published=i,paired_nt=n,sequence=seq))
 candidates.append(dict(register=register,cap=cap,p208_prefix=prefix,p208_hits=prefix_hits,p203_suffix_hits=suffix_hits))
selected=[c for c in candidates if c['p208_hits'] and c['p203_suffix_hits']]
assert len(selected)==1 and selected[0]['register']==17
assert selected[0]['cap']['published']==178 and selected[0]['p208_hits']==[142]
hits=selected[0]['p203_suffix_hits']; assert hits==[dict(published=46,paired_nt=17,sequence='ACTATTAAAGAACGTGG')]
row41=''.join(C[71-b] for b in range(21,38))
q=refs[46]; row40=q[1:-(2+len(row41)+1)]
assert q=='T'+row40+'TT'+row41+'T' and len(row40)==10
# Enumerate junctions spanning the source path203 row40domain; late branch
# uses index=B+bp. Preserve every exact candidate in searched range20..30.
alternatives=[]
for junction in range(20,31):
 for B in range(len(S)):
  seq=''.join(C[((82+b) if b<=junction else (B+b))%len(S)] for b in range(30,20,-1))
  if seq==row40:alternatives.append(dict(junction_last_early_bp=junction,late_branch_intercept=B))
assert alternatives==[{'junction_last_early_bp':21,'late_branch_intercept':7220},{'junction_last_early_bp':22,'late_branch_intercept':539},{'junction_last_early_bp':22,'late_branch_intercept':7220}]
# A local cropped model for each alternative; scaffold fragments deliberately
# remain separate. No invented connections or claim of full-length routing.
h40=source.helices[40].id; h41=source.helices[41].id
D=lambda h,a,b:Domain(helix_id=h,start_bp=a,end_bp=b,direction='FORWARD' if a<=b else 'REVERSE')
records=[]
for alt in alternatives:
 J=alt['junction_last_early_bp'];B=alt['late_branch_intercept']
 name=f'Gerling2018_LOCAL_p7560_J{J}_B{B}'
 draft=Design(cluster_transforms=source.cluster_transforms,lattice_frames=source.lattice_frames,helices=[h.model_copy(deep=True) for h in source.helices[40:42]],lattice_type=source.lattice_type)
 draft.metadata.name=name
 draft.metadata.description='PARTIAL RECONSTRUCTION HYPOTHESIS: two full published staples, 42hb (1)-(3) #178 and #46. Cropped p7560 scaffold fragments, NOT a full origami or connected 7560-nt scaffold. Three unresolved junction alternatives. Coordinate/register assumptions and provenance in '+str(O/'report.json')
 for sid,h,a,b,index in [('p7560_crop_h41',h41,37,-5,lambda bp:71-bp),('p7560_crop_h40_early',h40,21,J,lambda bp:82+bp),('p7560_crop_h40_late',h40,J+1,30,lambda bp:B+bp)]:
  step=1 if a<=b else -1
  seq=''.join(S[index(bp)%len(S)] for bp in range(a,b+step,step))
  draft.strands.append(Strand(id=sid,name=sid,domains=[D(h,a,b)],strand_type='scaffold',sequence=seq,notes='Artificial crop ends. p7560 indices documented in report.'))
 draft.strands.extend([Strand(id='published_178',name='42hb (1)-(3) #178 / source path207',domains=[D(h41,-5,13)]),Strand(id='published_46',name='42hb (1)-(3) #46 / source path203',domains=[D(h40,30,21),D(h41,21,37)])])
 draft.crossovers=[Crossover(half_a=HalfCrossover(helix_id=h40,index=21,strand='REVERSE'),half_b=HalfCrossover(helix_id=h41,index=21,strand='FORWARD'),extra_bases='TT')]
 for sid,left,right in [('published_178',10,1),('published_46',1,1)]:
  for end,n in [('five_prime',left),('three_prime',right)]:draft.extensions.append(StrandExtension(strand_id=sid,end=end,sequence='T'*n))
 draft=assign_staple_sequences(draft)
 v=validate_design(draft);assert v.passed,[dataclasses.asdict(r) for r in v.results if not r.passed]
 path=O/(name+'.nadoc');path.write_text(draft.model_dump_json(indent=2)+'\n')
 loaded=Design.model_validate_json(path.read_text());assert validate_design(loaded).passed
 staples={s.id:s.sequence for s in loaded.strands if not s.is_scaffold}
 full={178:'T'*10+staples['published_178']+'T',46:'T'+staples['published_46'][:10]+'TT'+staples['published_46'][10:]+'T'}
 assert all(full[i]==refs[i] for i in full)
 records.append(dict(**alt,file=path.name,paired_nt_verified=46,full_oligos=full,model_validation_passed=True))
# Full path208 provisional segmentation; only first2domains are located here.
p142parts=['T','AGAGTCC','TT','AAGAATA','TT','CTTAAGTGTCCTAC','TT','CTTTCTC','T']
assert ''.join(p142parts)==refs[142]
report=dict(source=str(SOURCE),source_sha256=before,workbook_sha256=sha(WB),scaffold_sha256=sha(ROOT/'backend/core/p7560.txt'),sheet='42hb (1)-(3)',index_convention='All scaffold indices and source vector path indices zero-based; published IDs are workbook values.',assumptions=['Source FigS1 path directions and helix identities retained.','Initial paired left boundary bp-5 and first crossover bp13/14 retained.','End caps10T, ordinary termini1T, interdomainTT for the tested oligos.','Candidate last early branch bp searched20..30; all7560 registers searched. These bounds do not prove global uniqueness.'],single_domain_caps=caps,register_candidates=candidates,selected_register=17,previous_3541_status='Rejected for this local whole-path hypothesis; prior isolated domain hits did not respect whole-oligo ordering.',nick_changes=[dict(helix=h41,old_boundary=[31,32],proposed_boundary=[37,38]),dict(helix=h40,old_boundary=[28,29],proposed_boundary=[30,31])],junction_alternatives=records,published142=dict(sequence=refs[142],provisional_parts=p142parts,located_domains=2,total_domains=4),limitations=['Only two full staples reconstructed; #142 firsttwo domains independently support registration.','Three equivalent local scaffoldjunction solutions remain.','Offset17 is relative to current startbp54; equivalently mapping index=71-bp on low h41. Neither actual breakcoordinate nor global start is established.','Scaffold fragments are artificially cropped; remaining routing and missing2268 scaffold bases are unresolved.','These are separate local hypotheses, not patches applied to the current full design.'])
(O/'report.json').write_text(json.dumps(report,indent=2)+'\n')
with (O/'reconstructed_oligos.csv').open('w') as f:
 cw=csv.writer(f);cw.writerow(['published_id','source_path_0based','sequence','paired_nt','status']);cw.writerow([178,207,refs[178],19,'full exact match']);cw.writerow([46,203,refs[46],27,'full exact match']);cw.writerow([142,208,refs[142],35,'first two domains located; remaining two provisional'])
assert sha(SOURCE)==before
print(json.dumps({'caps':caps,'candidates':candidates,'drafts':records,'source_unchanged':True},indent=2))
