from pathlib import Path
import csv,json
O=Path(__file__).resolve().parent;R=O.parents[1]
S=(R/'backend/core/p7560.txt').read_text().strip();C=S.translate(str.maketrans('ACGT','TGCA'))
refs={x['index']:x['sequence'] for x in json.load(open(R/'backend/data/gerling2018_42hb13.json'))['sequences']}
def read_staples(name):
 rows=[]
 for row in csv.reader((O/(name+'.csv')).read_text().splitlines()):
  if row and row[0].startswith('> SCAFFOLD TO'):break
  if row and not row[0].startswith('>') and len(row)==6:
   idx=int(row[0]);seq=row[1];ps=[int(x) for x in row[5].split(';')]
   assert len(seq)==len(ps)
   assert all(p==-1 or seq[k]==C[p] for k,p in enumerate(ps))
   rows.append({'solver_id':idx,'published_id':[163,171,174,178,46,142][idx],'sequence':seq,'scaffold_indices':ps})
 for row in rows:assert row['sequence']==refs[row['published_id']]
 return rows
caps=read_staples('caps_annotated');six=read_staples('local6_annotated')
assert len(caps)==4 and len(six)==5
assert [next(p for p in r['scaffold_indices'] if p>=0) for r in caps]==[3119,3175,398,76]
st46=next(r for r in six if r['published_id']==46)
assert st46['scaffold_indices'][1:11]==[1355,1354,1353,1352,1351,1386,1385,1384,1383,1382]
report={'cap_controls':'Four published sequences preserved exactly; 76 paired bases exact complements and all four scaffold intervals agree with independent local mapping.','local6':'Five of six physical staples output; all mapped bases complementary; #142 omitted.','published46_warning':'REVNANO routes first10 paired bases as5+5 at scaffold1355..1351 and1386..1382, unlike the figure-constrained 8+2 or9+1 alternatives. Last17 bases50..34 agree. A sequence-valid route is not proof of correct geometry.','caps':caps,'local6_staples':six}
(O/'control_validation.json').write_text(json.dumps(report,indent=2)+'\n');print(report['cap_controls']);print(report['local6']);print(report['published46_warning'])
