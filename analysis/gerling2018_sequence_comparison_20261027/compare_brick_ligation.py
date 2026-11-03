"""Read-only comparison; strand numbers are one-based staple order in the saved design."""
from pathlib import Path
import csv, hashlib, json, re
from collections import Counter
import openpyxl
ROOT=Path('/home/jojo/Work/NADOC')
OUT=Path(__file__).resolve().parent / "brick_ligation"
OUT.mkdir(exist_ok=True)
SRC=ROOT/'workspace/Gerling2018_FigS1_42hb_CONTROL_traced_staples_v4.nadoc'
PUB=Path('/media/jojo/Archive/NADOC_archive/design_reconstruction/gerling2018/aau1157_Table_S1.xlsx')
d=json.loads(SRC.read_text()); staples=[s for s in d['strands'] if s['strand_type']=='staple']
w=openpyxl.load_workbook(PUB,data_only=True)
sets={sheet.title:[{'index':i,'sequence':s} for i,s in list(sheet.values)[1:] if isinstance(s,str)] for sheet in [w["Brick"]]}
def walk(s):
 return [(x['helix_id'],bp,x['direction']) for x in s['domains'] for bp in range(x['start_bp'],x['end_bp']+(1 if x['end_bp']>=x['start_bp'] else -1),1 if x['end_bp']>=x['start_bp'] else -1)]
def core(s):
 seq=s['sequence'];offset=0;parts=[]
 for x in s['domains']:
  n=abs(x['end_bp']-x['start_bp'])+1
  if not x.get('overhang_id'):parts.append(seq[offset:offset+n])
  offset+=n
 assert offset==len(seq)
 return ''.join(parts)
def permissive(seq):
 # Allows arbitrary added Ts anywhere but never removes/changes a design base.
 # Deliberately more permissive than the paper, so a negative result is useful.
 return re.compile('T*'.join(seq))
def matches(seq, mode):
 pat=permissive(seq) if mode=='T_insertion' else None
 return {name:[p['index'] for p in ps if (pat.search(p['sequence']) if pat else seq in p['sequence'])] for name,ps in sets.items()}
walks=[walk(s) for s in staples];start={p[0]:i for i,p in enumerate(walks)}
assert len(start)==len(walks)
nexts={}
for i,p in enumerate(walks):
 h,b,direction=p[-1];key=(h,b+(1 if direction=='FORWARD' else -1),direction)
 if key in start and start[key]!=i and not staples[i]['domains'][-1].get('overhang_id') and not staples[start[key]]['domains'][0].get('overhang_id'):nexts[i]=start[key]
rows=[]
for i,s in enumerate(staples):
 row={'number':i+1,'id':s['id'],'length':len(s['sequence']),'sequence_5to3':s['sequence'],'core_sequence':core(s),'domains':'; '.join(f"{x['helix_id']}:{x['start_bp']}->{x['end_bp']}" for x in s['domains']),'exact_substring':matches(s['sequence'],'exact'),'T_insertion_substring':matches(core(s),'T_insertion'),'inline_successor':nexts.get(i,-1)+1}
 rows.append(row)
chains=[];maxlen=max(len(p['sequence']) for ps in sets.values() for p in ps)
for i in range(len(staples)):
 chain=[i];seq=staples[i]['sequence']
 while chain[-1] in nexts:
  j=nexts[chain[-1]]
  if j in chain:break
  chain.append(j);seq+=staples[j]['sequence']
  if len(seq)>maxlen:break
  if not any(len(staples[k]['sequence'])<15 for k in chain):continue
  cs=''.join(core(staples[k]) for k in chain)
  chains.append({'strands':[k+1 for k in chain],'length':len(seq),'sequence_5to3':seq,'exact_full':{name:[p['index'] for p in ps if seq==p['sequence']] for name,ps in sets.items()},'T_insertion_substring':matches(cs,'T_insertion')})
short=[r for r in rows if r['length']<15]
summary={'source':str(SRC.resolve()),'source_sha256':hashlib.sha256(SRC.read_bytes()).hexdigest(),'published':str(PUB),'published_sha256':hashlib.sha256(PUB.read_bytes()).hexdigest(),'staples':len(staples),'total_staple_nt':sum(len(s['sequence']) for s in staples),'core_nt':sum(len(core(s)) for s in staples),'short_staples':len(short),'short_lengths':dict(Counter(r['length'] for r in short)),'inline_ligatable_boundaries':len(nexts),'short_containing_chains_up_to_max_published_length':len(chains),'published_sets':{name:{'count':len(ps),'total_nt':sum(len(p['sequence']) for p in ps),'min_length':min(len(p['sequence']) for p in ps),'max_length':max(len(p['sequence']) for p in ps),'exact_full_staples':sum(any(s['sequence']==p['sequence'] for p in ps) for s in staples),'exact_substring_staples':sum(bool(r['exact_substring'][name]) for r in rows),'T_insertion_substring_staples':sum(bool(r['T_insertion_substring'][name]) for r in rows),'T_insertion_short_substrings':sum(bool(r['T_insertion_substring'][name]) for r in short),'exact_ligated_full_matches':sum(bool(c['exact_full'][name]) for c in chains),'T_insertion_ligated_substring_matches':sum(bool(c['T_insertion_substring'][name]) for c in chains)} for name,ps in sets.items()}}
(OUT/'results.json').write_text(json.dumps({'summary':summary,'staples':rows,'ligation_chains':chains},indent=2)+'\n')
for filename,data in [('all_staples.csv',rows),('short_staples.csv',short),('ligation_candidates.csv',chains)]:
 with (OUT/filename).open('w') as f:
  writer=csv.DictWriter(f,fieldnames=list(data[0]));writer.writeheader();writer.writerows(data)
print(json.dumps(summary,indent=2))
print('short tolerant hits',[(r['number'],r['T_insertion_substring']) for r in short if any(r['T_insertion_substring'].values())])
assert hashlib.sha256(SRC.read_bytes()).hexdigest()==summary['source_sha256']
