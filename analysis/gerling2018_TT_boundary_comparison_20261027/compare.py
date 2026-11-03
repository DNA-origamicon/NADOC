"""Sequence-only comparison of disputed TT boundaries; no annotation mutation."""
from pathlib import Path
from functools import lru_cache
from collections import Counter
import csv,html,json
import openpyxl
from openpyxl.styles import Font,PatternFill,Alignment
R=Path(__file__).resolve().parents[2];O=Path(__file__).resolve().parent
S=(R/'backend/core/p7560.txt').read_text().strip();N=len(S);C=S.translate(str.maketrans('ACGT','TGCA'))
# Traversal begins at scaffold index0 and proceeds backwards, as a binding staple.
D=''.join(C[-i%N] for i in range(N));DD=D+D
@lru_cache(None)
def hits(q):
 out=[];i=DD.find(q)
 while 0<=i<N:
  out.append(-i%N);i=DD.find(q,i+1)
 return sorted(out)
def best_bridge(left,gap,right):
 candidates=[]
 for a in range(4,len(left)+1):
  for b in range(4,len(right)+1):
   q=left[-a:]+gap+right[:b];h=hits(q)
   if h:candidates.append({'sequence':q,'flank_nt':a+b,'left_nt':a,'right_nt':b,'hit_count':len(h),'first_scaffold_indices_0based':h})
 return max(candidates,key=lambda x:(x['flank_nt'],-x['hit_count']),default=None)
def extension(left,gap,right):
 options=[]
 for side,flank in [('left',left),('right',right)]:
  for k in range(4,len(flank)+1):
   q=flank[-k:]+gap if side=='left' else gap+flank[:k];h=hits(q)
   if h:options.append({'side':side,'sequence':q,'flank_nt':k,'hit_count':len(h),'first_scaffold_indices_0based':h})
 return max(options,key=lambda x:(x['flank_nt'],-x['hit_count']),default=None)
def flank_match(q,side):
 for k in range(len(q),3,-1):
  t=q[-k:] if side=='left' else q[:k];h=hits(t)
  if h:return {'sequence':t,'length':k,'hit_count':len(h),'first_scaffold_indices_0based':h}
 return None
source=json.loads((R/'analysis/gerling2018_T_annotations_20261027/annotations.json').read_text());records=[];excluded=[]
for row in source:
 if row['status']!='ambiguous':continue
 q=row['original_sequence'];candidates={};annotations=[row['proposed']]+row['alternatives']
 for ai,ann in enumerate(annotations):
  segs=ann['segments']
  for j,s in enumerate(segs):
   if s['kind']!='unpaired_T_candidate' or s['length']!=2 or j==0 or j==len(segs)-1:continue
   a=s['start_1based']-1;b=s['end_1based'];assert q[a:b]=='TT'
   # Union of flanks across alternatives may include other hypothesized insertions;
   # keep each context separately, then use the longest available flank at this TT.
   left=segs[j-1]['sequence'][-14:];right=segs[j+1]['sequence'][:14]
   entry=candidates.setdefault((a,b),{'left':left,'right':right,'sources':[]})
   if len(left)>len(entry['left']):entry['left']=left
   if len(right)>len(entry['right']):entry['right']=right
   entry['sources'].append(ai)
 if not candidates:excluded.append({'key':row['key'],'published_id':row['published_id'],'reason':'No internal 2T block in saved proposal/alternatives; ambiguity is terminal or involves other loop lengths.'})
 for (a,b),v in sorted(candidates.items()):
  left,right=v['left'],v['right'];keep=best_bridge(left,'TT',right);omit=best_bridge(left,'',right);ext=extension(left,'TT',right)
  lm=flank_match(left,'left');rm=flank_match(right,'right')
  strong_keep=bool(keep and len(keep['sequence'])>=12 and keep['hit_count']==1)
  strong_omit=bool(omit and len(omit['sequence'])>=12 and omit['hit_count']==1)
  strong_ext=bool(ext and len(ext['sequence'])>=12 and ext['hit_count']==1)
  if strong_keep and strong_omit: verdict='conflicting long-match evidence'
  elif strong_keep:verdict='paired TT favored: unique spanning match'
  elif strong_omit and strong_ext:verdict='conflicting long-match evidence'
  elif strong_omit:verdict='unpaired TT favored: unique bridge after omission'
  elif strong_ext:verdict='paired TT possible: unique one-sided extension'
  elif lm and rm and lm['length']>=7 and rm['length']>=7 and lm['hit_count']==rm['hit_count']==1:verdict='split unpaired TT compatible; not decisive'
  else:verdict='unresolved from local sequence'
  disputed=any(pos in row['ambiguous_positions_1based'] for pos in range(a+1,b+1))
  records.append({'key':row['key'],'sheet':row['sheet'],'published_id':row['published_id'],'start_1based':a+1,'end_1based':b,'TT_bases_disputed_in_near_best':disputed,'present_in_proposal':0 in v['sources'],'annotation_sources':v['sources'],'context':left+'[TT]'+right,'left_context':left,'right_context':right,'keep_TT_bridge':keep,'omit_TT_bridge':omit,'keep_TT_one_sided_extension':ext,'left_independent_match':lm,'right_independent_match':rm,'verdict':verdict,'original_annotation':row['proposed']['annotated_sequence']})
# Verify every reported match against original circular scaffold, independently of D.
for r in records:
 for key in ['keep_TT_bridge','omit_TT_bridge','keep_TT_one_sided_extension','left_independent_match','right_independent_match']:
  match=r[key]
  if match:
   for p in match['first_scaffold_indices_0based']:assert match['sequence']==''.join(C[(p-k)%N] for k in range(len(match['sequence'])))
summary={key:{'ambiguous_staples':sum(r['key']==key and r['status']=='ambiguous' for r in source),'staples_with_TT_test':len({r['published_id'] for r in records if r['key']==key}),'TT_boundaries_tested':sum(r['key']==key for r in records),'verdict_counts':dict(Counter(r['verdict'] for r in records if r['key']==key))} for key in ['42hb13','42hb14']}
for key in summary:
 for name,predicate in [('approved_TT_verdicts',lambda r:r['present_in_proposal']),('near_best_disputed_TT_verdicts',lambda r:r['TT_bases_disputed_in_near_best'])]:
  summary[key][name]=dict(Counter(r['verdict'] for r in records if r['key']==key and predicate(r)))
(O/'comparisons.json').write_text(json.dumps(records,indent=2)+'\n');(O/'summary.json').write_text(json.dumps({'summary':summary,'no_internal_TT_candidates':excluded},indent=2)+'\n')
def describe(m):
 if not m:return 'No exact match meeting minimum flank length'
 return f"{m['sequence']} | {len(m['sequence'])} nt | {m['hit_count']} placements | starts: "+','.join(map(str,m['first_scaffold_indices_0based']))
headers=['List','Published ID','TT start (1-based)','TT end (1-based)','Near-best disputed TT','In approved proposal','Context','Interpretation','TT included: spanning match','TT omitted: spanning match','TT included: one-sided extension','Independent left match','Independent right match','Approved annotation','Reviewer notes']
values=[]
for r in records:values.append([r['key'],r['published_id'],r['start_1based'],r['end_1based'],r['TT_bases_disputed_in_near_best'],r['present_in_proposal'],r['context'],r['verdict'],*[describe(r[k]) for k in ['keep_TT_bridge','omit_TT_bridge','keep_TT_one_sided_extension','left_independent_match','right_independent_match']],r['original_annotation'],''])
with (O/'TT_comparison.csv').open('w',newline='') as f:w=csv.writer(f);w.writerow(headers);w.writerows(values)
wb=openpyxl.Workbook();ws=wb.active;ws.title='TT comparisons';ws.append(headers)
for row in values:ws.append(row)
ws.freeze_panes='G2';ws.auto_filter.ref=ws.dimensions
for c in ws[1]:c.font=Font(bold=True,color='FFFFFF');c.fill=PatternFill('solid',fgColor='234B68')
for col in 'ABCDEFGHIJKLMNO':ws.column_dimensions[col].width=18 if col in 'ABCDEF' else 55
for row in ws.iter_rows(min_row=2):
 for cell in row:cell.alignment=Alignment(wrap_text=True,vertical='top')
 ws.row_dimensions[row[0].row].height=90
priority=wb.create_sheet('Priority review',0);priority.append(headers)
for value,r in zip(values,records):
 if r['present_in_proposal'] and ('favored' in r['verdict'] or 'conflicting' in r['verdict']):priority.append(value)
priority.freeze_panes='G2';priority.auto_filter.ref=priority.dimensions
for col in 'ABCDEFGHIJKLMNO':priority.column_dimensions[col].width=18 if col in 'ABCDEF' else 55
for rr in priority:
 for cell in rr:cell.alignment=Alignment(wrap_text=True,vertical='top')
 priority.row_dimensions[rr[0].row].height=90
wb.save(O/'TT_comparison.xlsx')
parts=['<!doctype html><meta charset="utf-8"><title>Ambiguous TT comparisons</title><style>body{font:15px system-ui;margin:30px;max-width:1200px;color:#24364b}article{border:1px solid #ccc;border-radius:8px;padding:15px;margin:15px 0}code{overflow-wrap:anywhere}input,select{padding:8px}td,th{padding:6px;text-align:left;vertical-align:top}table{width:100%}.tt{color:#bd253c;font-weight:bold}</style><h1>Ambiguous TT boundaries — circular p7560 comparison</h1><p>Each boundary is tested with TT included or omitted from a contiguous match, plus separate flanking matches. Omission is a diagnostic, not a sequence edit. At a scaffold crossover, the flanks need not match contiguously under either interpretation. No annotations or REVNANO maps have been changed.</p><p>Spanning tests require at least 4 bases on each side. Stronger evidence means a unique match of at least 12 nt. One-sided extensions can be fortuitous across a domain boundary; independent 7-base matches do not prove an unpaired insertion.</p><label>List <select id="sheet"><option value="">Both</option><option>42hb13</option><option>42hb14</option></select></label> <label>Published ID <input id="id" type="number"></label> <label><input id="disputed" type="checkbox">Only TT bases disputed in near-best alternatives</label> <label><input id="approved" type="checkbox">Only TT in approved proposal</label> <span id="count"></span>']
for r in records:
 parts.append(f'<article data-approved="{int(r["present_in_proposal"])}" data-sheet="{r["key"]}" data-id="{r["published_id"]}" data-disputed="{str(r["TT_bases_disputed_in_near_best"]).lower()}"><h2>{r["key"]} #{r["published_id"]} · bases {r["start_1based"]}–{r["end_1based"]}</h2><p><b>{r["verdict"]}</b></p><code>{r["context"].replace("[TT]","<span class=tt>[TT]</span>")}</code><table>')
 for label,k in [('TT paired — spanning','keep_TT_bridge'),('TT unpaired — omitted bridge','omit_TT_bridge'),('TT paired — one flank','keep_TT_one_sided_extension'),('Left flank alone','left_independent_match'),('Right flank alone','right_independent_match')]:parts.append(f'<tr><th>{label}</th><td><code>{html.escape(describe(r[k]))}</code></td></tr>')
 parts.append(f'</table><details><summary>Approved annotation</summary><code>{r["original_annotation"]}</code><p>TT in approved proposal: {r["present_in_proposal"]}; TT bases disputed among near-best alternatives: {r["TT_bases_disputed_in_near_best"]}.</p></details></article>')
parts.append("<script>function filter(){const sheet=document.getElementById('sheet'),id=document.getElementById('id'),disputed=document.getElementById('disputed'),approved=document.getElementById('approved'),count=document.getElementById('count');let n=0;document.querySelectorAll('article').forEach(a=>{a.hidden=(sheet.value&&sheet.value!==a.dataset.sheet)||(id.value&&id.value!==a.dataset.id)||(disputed.checked&&a.dataset.disputed!=='true')||(approved.checked&&a.dataset.approved!=='1');if(!a.hidden)n++});count.textContent=n+' boundaries shown'}['sheet','id','disputed','approved'].forEach(k=>document.getElementById(k).addEventListener('input',filter));filter()</script>")
(O/'review.html').write_text(''.join(parts));print(json.dumps(summary,indent=2));print('Excluded strands without an internal TT candidate:',len(excluded))
