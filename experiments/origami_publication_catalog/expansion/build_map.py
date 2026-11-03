"""Build the broader research map without altering image-only scores or topology."""
import csv,html,json,re,hashlib
from pathlib import Path
from collections import Counter
H=Path(__file__).resolve().parents[1];A=H/'assets';O=A/'sources/pre2020-expansion'
def read(p):return json.loads(p.read_text())
def write(name,obj): (H/name).write_text(json.dumps(obj,indent=2,ensure_ascii=False)+'\n')
def csvout(name,rows):
 keys=list(dict.fromkeys(k for r in rows for k in r))
 with (H/name).open('w',newline='')as f:
  w=csv.DictWriter(f,keys);w.writeheader();w.writerows({k:json.dumps(v,ensure_ascii=False)if isinstance(v,(dict,list))else v for k,v in r.items()}for r in rows)
def clean(t):return html.unescape(re.sub('<[^>]+>','',t or ''))
def doi(t):return (t or '').lower().strip().removeprefix('https://doi.org/')
scan=read(O/'screening.json');cross=read(O/'crossref.json');chase=read(O/'citation_chase.json');cur=read(H/'expansion/curation.json');old=read(H/'catalog.json')['rows'];inv=read(O/'supplement_inventory.json');repos=read(O/'repository_audit.json')
registry={}
for i,r in enumerate(scan):
 d=doi(r.get('doi'));key=d or r.get('pmcid') or f'epmc:{i}'
 registry[key]=dict(key=key,doi=d,publication=clean(r['title']),first_publication_date=r.get('firstPublicationDate',''),publication_types=r.get('publication_types',[]),discovery=['Europe PMC'],fulltext_status=r['status'],sequence_evidence=r.get('sequence_evidence',[]),lattice_evidence=r.get('lattice_evidence',[]),design_evidence=r.get('design_evidence',[]),repository_links=r.get('repository_links',[]),supplement_links=r.get('supplements',[]),xml_file=r.get('xml_file'),review_status='unresolved: discovery record, not a verified structure')
def add_cross(r,origin):
 d=doi(r.get('DOI'));parts=r.get('published',r.get('published-online',r.get('published-print',{}))).get('date-parts',[[]])[0]
 if not d or not parts or parts[0]>=2020:return
 if d in registry:
  if origin not in registry[d]['discovery']:registry[d]['discovery'].append(origin)
  return
 registry[d]=dict(key=d,doi=d,publication=clean(' '.join(r.get('title',[]))),first_publication_date='-'.join(str(n).zfill(4 if i==0 else 2)for i,n in enumerate(parts)),publication_types=[r.get('type','unknown')],discovery=[origin],fulltext_status='not_retrieved_in_this_pass',sequence_evidence=[],lattice_evidence=[],design_evidence=[],repository_links=[],supplement_links=[],review_status='unresolved: discovery record, not a verified structure')
for r in cross:
 if re.search(r'DNA.*origami|origami.*DNA|scaffolded.*DNA',' '.join(r.get('title',[])),re.I):add_cross(r,'Crossref title search (relevance-capped)')
for r in read(O/'curated_metadata.json'):add_cross(r,'curated primary publication')
for r in chase:
 if r.get('metadata'):add_cross(r['metadata'],'backward citation chase')
# Curated original image subset also supplies verified publication metadata.
for r in old:
 d=doi(r['doi'])
 if d not in registry:registry[d]=dict(key=d,doi=d,publication=r['publication'],first_publication_date=r['first_publication_date'],discovery=['original image catalog'],fulltext_status='original_sources_reviewed',sequence_evidence=[],lattice_evidence=[],design_evidence=[],repository_links=[],supplement_links=[],publication_types=['journal-article'])
for r in registry.values():
 r['publication_url']='https://doi.org/'+r['doi'] if r['doi']else ''
 r['structure_ids']=[]
 r['review_status']='unresolved: discovery record, not a verified structure'
 if any('review' in t.lower() or 'book' in t.lower() for t in r.get('publication_types',[])):r['review_status']='background_or_secondary_source: metadata triage, no design decision'
 if any('preprint' in t.lower() for t in r.get('publication_types',[])):r['review_status']='preprint: publication/version reconciliation needed'
 if re.search(r'wireframe|DNA brick|RNA origami',r['publication'],re.I):r['review_status']='likely_out_of_scope: title triage, mixed-design paper not ruled out'
# All locally retrieved publication attachments, with sequence evidence separate from completeness.
sources={}
for x in inv:
 d=doi(x.get('doi'))
 sources.setdefault(d,[]).append({k:x[k]for k in ['url','local_file','filename','sha256','sequence_like_strings','sequence_pages']if k in x})
for x in read(O/'landmark_downloads.json'):
 if x.get('file'):sources.setdefault('10.1038/nature04586',[]).append(dict(url=x['url'],local_file='sources/pre2020-expansion/'+x['file'],sha256=x['sha256']))
for x in read(O/'extra_landmarks.json'):
 for f in x.get('downloads',[]):
  if f.get('file'):sources.setdefault(x['doi'],[]).append(dict(url=f['url'],local_file='sources/pre2020-expansion/'+f['file'],sha256=f['sha256']))
repo_by={r['doi']:r for r in repos}
imaging=[
 dict(doi='10.1038/nature07971',accession='EMD-1612',kind='processed_cryo_em_map',url='https://www.ebi.ac.uk/emdb/EMD-1612',scope='DNA box with controllable lid',notes='Processed reconstruction; not raw micrographs or particle stacks.'),
 dict(doi='10.1073/pnas.1215713109',accession='EMD-2210',kind='processed_cryo_em_map',url='https://www.ebi.ac.uk/emdb/EMD-2210',scope='Square-lattice pointer object',notes='Match deposited object, buffer and processing before simulation comparison.'),
 dict(doi='10.1073/pnas.1215713109',accession='4V5X',kind='atomic_model',url='https://www.rcsb.org/structure/4V5X',scope='Square-lattice pointer object',notes='Model polymer sequences do not establish completeness of the synthesis staple list; supersedes earlier split PDB entries.'),
 dict(doi='10.1039/c8nr10113b',accession='EMD-4653',kind='processed_cryo_em_map',url='https://www.ebi.ac.uk/emdb/EMD-4653',scope='Viral capsid packaging study; origami scope unresolved',notes='Map describes capsid; do not assume it resolves the packaged origami.'),
 dict(doi='10.1126/sciadv.aau1157',accession='EMD-0028',kind='processed_cryo_em_map',url='https://www.ebi.ac.uk/emdb/EMD-0028',scope='excluded brick-named objects',notes='Retained as scope boundary evidence, not included as an eligible design.'),
 dict(doi='10.1126/sciadv.aau1157',accession='EMD-4354',kind='processed_cryo_em_map',url='https://www.ebi.ac.uk/emdb/EMD-4354',scope='excluded brick-named objects',notes='Retained as scope boundary evidence, not included as an eligible design.')]
rows=[]
for x in old:
 r=dict(x);r['inclusion_basis']='published_CAD_image';r['map_status']='reviewed_in_scope';r['family']=r['design'];r['publication_supplements']=sources.get(doi(r['doi']),[]);r['complete_staple_set_validated']=False;rows.append(r)
for i,x in enumerate(cur,1):
 d=x['doi'];meta=registry.get(d)
 if not meta:raise ValueError('Missing metadata for '+d)
 fs=sources.get(d,[]);rf=repo_by.get(d,{}).get('files',[])
 # Avoid attaching other 6HB variants as if they match the chosen scaffold length.
 match=re.search(r'(1512|2268|3024)-nt',x['design'])
 if match:rf=[f for f in rf if match[1]in f['path']]
 r=dict(x,id=f'S{i:03}',publication=meta['publication'],first_publication_date=meta['first_publication_date'],publication_url='https://doi.org/'+d,inclusion_basis='published_staple_list',map_status='reviewed_in_scope'if x['review_status']=='primary_source_reviewed'else 'candidate',image_file=None,quality_score=None,image_kind='not_reviewed',rating_status='not_scored_no_reviewed_CAD_image',publication_supplements=fs,design_files=rf,complete_staple_set_validated=False)
 r['staple_list']=dict(status='publication_material_downloaded_variant_matching_pending'if fs or rf else 'reported_in_primary_publication',location=x['sequence_location'],sources=fs+rf,notes='Source availability is not proof of complete core + variant + modified staple coverage. See design-specific notes; sequence-like string counts are retrieval aids only.')
 r['structural_characterization']=dict(modalities=x['characterization'],source_url=r['publication_url'],scope='named structure or variant family; confirm experiment-specific variant')
 r['imaging_datasets']=dict(public_raw_dataset_status='not_verified',resources=[m for m in imaging if m['doi']==d],notes='Linked maps/models are distinct from raw imaging datasets; no raw-data absence claim.')
 rows.append(r)
for r in rows:
 meta=registry[doi(r['doi'])];meta['structure_ids'].append(r['id']);meta['review_status']='contains_reviewed_structure_groups'if r['map_status']=='reviewed_in_scope'or meta['review_status']=='contains_reviewed_structure_groups'else 'named_structure_candidate: scope/list verification pending'
for r in registry.values():
 r['downloaded_supplements']=sources.get(r['doi'],[])
 r['priority']='named_structure'if r['structure_ids']else 'sequence_evidence_to_review'if r.get('sequence_evidence')and not r['review_status'].startswith(('background','likely_out','preprint'))else 'discovery_only'
regs=sorted(registry.values(),key=lambda r:(r['first_publication_date'],r['key']))
for i,r in enumerate(regs,1):r['id']=f'P{i:04}'
counts=dict(publication_discovery_records=len(regs),europe_pmc_records=len(scan),accessible_fulltexts=sum(r['status']=='fulltext_evidence_triaged'for r in scan),papers_with_sequence_related_contexts=sum(bool(r.get('sequence_evidence'))for r in scan),reviewed_design_groups=sum(r['map_status']=='reviewed_in_scope'for r in rows),candidate_design_groups=sum(r['map_status']=='candidate'for r in rows),reviewed_publications=len({r['doi']for r in rows if r['map_status']=='reviewed_in_scope'}),mapped_publications=len({r['doi']for r in rows}),new_sequence_only_reviewed_groups=sum(r['id'].startswith('S')and r['map_status']=='reviewed_in_scope'for r in rows),downloaded_supplement_files=len({s['local_file']for ss in sources.values()for s in ss}),new_repository_files=sum(len(r.get('files',[]))for r in repos),registry_review_states=dict(Counter(r['review_status']for r in regs)),fulltext_states=dict(Counter(r['status']for r in scan)))
write('structure_map.json',dict(schema_version=1,status='research_side_project',production_feature=False,recovery_status='paused_pending_full_feature_log_revamp',cutoff_exclusive='2020-01-01',reviewed='2026-11-02',coverage='expanded_search_pass_with_explicit_unresolved_records_not_exhaustive_verified_map',counts=counts,rows=rows))
write('publication_registry.json',regs);csvout('publication_registry.csv',regs);csvout('structure_map.csv',rows);write('imaging_resources.json',imaging);csvout('imaging_resources.csv',imaging)
write('search_coverage.json',dict(counts=counts,europe_pmc_queries=read(O/'queries.json'),crossref_queries=read(O/'crossref_queries.json'),citation_candidates=len(chase),citation_metadata_resolved=sum(bool(x.get('metadata'))for x in chase),limitations=['Crossref queries relevance-capped, not exhaustive.','Full-text access failures and non-PMC articles remain unresolved.','Automated sequence/lattice mentions are not inclusion decisions.','Grouped variants are not counts of unique structures.','Complete per-variant staple sets have not been validated.','Raw imaging data search has not established absence.','Backward citations scanned only in accessible origami-related references; citation closure is incomplete.']))
def esc(s):return html.escape(str(s or ''))
def link(url,label):return '<a href="'+esc(url)+'">'+esc(label)+'</a>'if url else esc(label)
def files(fs):
 fs=[dict(local_file=f)if isinstance(f,str)else f for f in fs]
 return '<br>'.join(link('assets/'+f['local_file'],Path(f['local_file']).name)+(' · '+link(f.get('url'), 'source')if f.get('url')else '')for f in fs if f.get('local_file'))
def page(title,body,headers,trs):
 return '''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>'''+esc(title)+'''</title><style>body{font:15px system-ui;margin:24px;color:#203040}a{color:#1260a0}table{border-collapse:collapse;width:100%}td,th{padding:10px;border:1px solid #cbd5df;text-align:left;vertical-align:top}th{background:#e8eef3;position:sticky;top:0}td{min-width:150px;max-width:420px;overflow-wrap:anywhere}img{width:230px;max-height:260px;object-fit:contain}input,select{padding:10px;margin:12px 8px 12px 0}small{color:#52616f}.candidate{background:#fff9e9}</style><h1>'''+esc(title)+'''</h1>'''+body+'''<p><a href="structure_map.html">Structure map</a> · <a href="publication_registry.html">Publication search registry</a> · <a href="catalog.html">Image-scored subset</a> · <a href="SEARCH_COVERAGE.md">Coverage and gaps</a></p><input id="q" aria-label="Search" placeholder="Search all columns"><select id="status" aria-label="Review status"><option value="">All statuses</option><option value="reviewed_in_scope">Reviewed in scope</option><option value="candidate">Candidates</option></select><span id="count"></span><table><thead><tr>'''+''.join('<th>'+esc(h)+'</th>'for h in headers)+'''</tr></thead><tbody>'''+''.join(trs)+'''</tbody></table><script>const q=document.querySelector('#q'),s=document.querySelector('#status'),rows=[...document.querySelectorAll('tbody tr')];function filter(){let n=0;for(const r of rows){const ok=r.textContent.toLowerCase().includes(q.value.toLowerCase())&&(!s.value||r.dataset.status===s.value);r.hidden=!ok;if(ok)n++}document.querySelector('#count').textContent=n+' rows shown'}q.oninput=filter;s.onchange=filter;filter()</script></html>'''
trs=[]
for r in rows:
 st=r['staple_list'];ch=r['structural_characterization'];im=r['imaging_datasets'];image=link('assets/'+r['image_file'],'<image>')if r.get('image_file')else 'No reviewed CAD image; score unassigned'
 if r.get('image_file'):image='<a href="assets/'+esc(r['image_file'])+'"><img loading="lazy" alt="Published design image '+esc(r['id'])+'" src="assets/'+esc(r['image_file'])+'"></a><br>Image-only score: '+str(r['quality_score'])+'<br>'+link(r.get('image_source_url'),'image source')
 resources=im.get('resources',[])
 cells=[esc(r['id'])+'<br>'+esc(r['map_status']),link(r['publication_url'],r['publication'])+'<br>'+esc(r['doi'])+'<br>'+esc(r['first_publication_date']),esc(r['design'])+'<br><small>Family: '+esc(r['family'])+'</small>',esc(r['lattice'])+'<br>'+esc(r.get('lattice_evidence','')),image,esc(st['status'])+'<br>'+esc(st.get('location'))+'<br>'+esc(st.get('notes'))+'<details><summary>Sources and downloaded supplements</summary>'+files(st.get('sources',[]))+files(r.get('publication_supplements',[]))+'</details>',esc('; '.join(ch.get('modalities',[])))+'<br>'+esc(ch.get('simulation_comparison_notes',''))+'<br>'+link(ch.get('source_url'),'characterization source'),esc(im.get('public_raw_dataset_status'))+'<br>'+'<br>'.join(link(f.get('url'),f.get('accession')or f.get('label')or f.get('kind'))+' '+esc(f.get('kind'))for f in resources),files(r.get('design_files',[]))or 'No matching original verified',esc(r.get('notes',r.get('quality_rationale',''))) ]
 trs.append('<tr class="'+r['map_status']+'" data-status="'+r['map_status']+'">'+''.join('<td>'+c+'</td>'for c in cells)+'</tr>')
body=f'<p><strong>Research side project — recovery paused pending feature-log revamp.</strong></p><p>{counts["reviewed_design_groups"]} reviewed design groups across {counts["reviewed_publications"]} publications; {counts["candidate_design_groups"]} candidate groups. These are grouped variants, not unique-architecture counts. Staple-list availability does not certify completeness. Missing image scores remain unassigned.</p><p><a href="structure_map.csv">CSV</a> · <a href="structure_map.json">JSON</a> · <a href="imaging_resources.csv">Imaging resources</a> · <a href="expansion_repository_files.csv">Additional original files</a> · <a href="priority_review_gaps.csv">Priority review gaps</a></p>'
(H/'structure_map.html').write_text(page('Pre-2020 DNA origami structure map',body,['ID / status','Publication','Design / family','Lattice','Image / score','Staple lists','Characterization','Imaging data','Original files','Qualifications'],trs))
trs=[]
for r in regs:
 cells=[esc(r['id'])+'<br>'+esc(r['review_status']),link(r['publication_url'],r['publication'])+'<br>'+esc(r['doi'])+'<br>'+esc(r['first_publication_date']),esc(', '.join(r['structure_ids'])),esc(r['fulltext_status'])+'<br>'+esc('; '.join(r['discovery'])),esc(r['priority'])+'<details><summary>Primary-text evidence snippets (unverified matches)</summary>'+esc(json.dumps(r.get('sequence_evidence',[]),ensure_ascii=False))+'</details>',files(r['downloaded_supplements']),esc('; '.join(r.get('repository_links',[])))]
 trs.append('<tr data-status="'+('reviewed_in_scope'if r['review_status']=='contains_reviewed_structure_groups'else 'candidate')+'">'+''.join('<td>'+c+'</td>'for c in cells)+'</tr>')
(H/'publication_registry.html').write_text(page('Pre-2020 publication search registry',f'<p>{len(regs)} discovery records. This includes reviews, methods, preprints, out-of-scope papers and unresolved sources. It is not a count of eligible publications. Search snippets are automated evidence leads.</p><p><a href="publication_registry.csv">CSV</a> · <a href="publication_registry.json">JSON</a></p>',['Status','Publication','Structure IDs','Coverage','Evidence leads','Downloaded sources','Named repositories'],trs))
print(json.dumps(counts,indent=2))
