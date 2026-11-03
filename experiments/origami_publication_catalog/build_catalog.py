"""Generate local research tables and verify referenced evidence. No NADOC integration."""
import csv
import hashlib
import html
import json
from pathlib import Path
from urllib.parse import quote
from scoring import reconstruction_score

HERE = Path(__file__).resolve().parent
ASSETS = HERE/'assets'
data = json.loads((HERE/'catalog.json').read_text())
for record in data['rows']:
    assert record['quality_score'] == reconstruction_score(record['quality_components'], record['image_kind'])
rows = sorted(data['rows'], key=lambda r:(-r['quality_score'], r['doi'], r['id']))

def write_csv(name, records):
    if not records: return
    with (HERE/name).open('w', newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(records[0]));w.writeheader()
        for r in records: w.writerow({k:json.dumps(v,ensure_ascii=False) if isinstance(v,(list,dict)) else v for k,v in r.items()})

def checksum(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def local(path):return 'assets/'+quote(path, safe='/')
def link(label,url):return f'<a href="{html.escape(url,quote=True)}">{html.escape(label)}</a>'

def evidence_md(sources):
    return '<br>'.join(f"[{v['label']}]({v['url']})" + (f" · [local]({local(v['local_file'])}" + (f"#page={v['pdf_page']}" if v.get('pdf_page') else '') + ')' if v.get('local_file') else '') for v in sources)

def evidence_html(sources):
    return '<br>'.join(link(v['label'],v['url']) + (' · '+link('local',local(v['local_file'])+(f"#page={v['pdf_page']}" if v.get('pdf_page') else '')) if v.get('local_file') else '') for v in sources)

def extra_md(r):
    st=r['staple_list'];ch=r['structural_characterization'];im=r['imaging_datasets']
    return [st['status'].replace('_',' ')+'<br>'+evidence_md(st['sources'])+'<br>'+st['notes'],
            ', '.join(ch['modalities'])+f"<br>[{ch['location']}]({ch['source_url']})<br>"+ch['simulation_comparison_notes'],
            'Public raw dataset: '+im['public_raw_dataset_status'].replace('_',' ')+'<br>'+im['availability'].replace('_',' ')+'<br>'+evidence_md(im['resources'])]

def extra_html(r):
    st=r['staple_list'];ch=r['structural_characterization'];im=r['imaging_datasets']
    return ['<b>'+html.escape(st['status'].replace('_',' '))+'</b><br>'+evidence_html(st['sources'])+'<p>'+html.escape(st['notes'])+'</p>',
            '<b>'+html.escape(', '.join(ch['modalities']))+'</b><br>'+link(ch['location'],ch['source_url'])+'<p>'+html.escape(ch['simulation_comparison_notes'])+'</p>',
            '<b>Public raw dataset: not located</b><br>'+link(im['availability'].replace('_',' '),im['availability_source'])+'<p>Published panels / experimental previews below; not raw-data deposits.</p>'+evidence_html(im['resources'])]

def md_table(items):
    out=['| Rank | Publication / design | DOI | Lattice | Published image | Image | Image-only reconstruction /100 | Original files | Staple list | Structural characterization | Imaging datasets / evidence |', '|---:|---|---|---|---|---|---:|---|---|---|---|']
    for i,r in enumerate(items,1):
        files='<br>'.join(f'[{Path(f).name}]({local(f)})' for f in r['design_files']) or r['file_status'].replace('_',' ')
        out.append(f"| {i} · {r['id']} | **{r['publication']}** ({r['first_publication_date'][:4]})<br>{r['design']} | [{r['doi']}]({r['publication_url']}) | {r['lattice']} | [{r['figure_location']}]({r['image_source_url']}) · [local source]({local(r['source_file'])}) | [![{r['id']} design image]({local(r['image_file'])})]({local(r['image_file'])}) | {r['quality_score']} ({r['image_kind'].replace('_',' ')}) | {files}<br>{r['file_note']} | " + ' | '.join(extra_md(r)) + ' |')
    return '\n'.join(out)+'\n'

write_csv('catalog.csv',rows)
(HERE/'CATALOG.md').write_text('# Pre-2020 DNA origami design-image catalog\n\nResearch side project • not a production feature • initial verified subset, not exhaustive. Reviewed 2026-11-02. One row per reviewed figure/design group; a paper can appear more than once. Scores are provisional; see [methodology](README.md).\n\n'+md_table(rows))
recovery=[r for r in rows if not r['design_files'] and r['image_kind']=='complete_design_map']
(HERE/'RECOVERY_QUEUE.md').write_text('# Image recovery queue — PAUSED\n\n**Paused by user pending the full feature-log revamp. The five-design review workspace was deleted on 2026-11-02. Do not resume reconstruction from this ranking.**\n\n[Expanded structure map](structure_map.html) includes sequence-only designs.\n\nResearch-only, provisional ranking. Rows with downloaded author files are set aside for file/image comparison first. Conceptual, partial, and component-only images are retained in the main catalog but excluded from this full-design recovery queue. “Not located” means not found in checked sources, not proven unavailable. The robot paper references a missing JSON supplement: try retrieving it before reconstructing. Rows may contain several variants; the queue is not a count of unique designs.\n\n'+md_table(recovery))

# Preserve the complete discovery pool and distinguish it from the manually accepted subset.
discovery=json.loads((ASSETS/'sources/discovery.json').read_text())
screen={r['pmcid']:r for r in json.loads((ASSETS/'sources/screening.json').read_text())}
accepted={r['doi'].lower() for r in rows}
exclusions={
 '10.1126/sciadv.aav0655':'Wireframe PERDIX designs; not standard packed-lattice origami.',
 '10.1038/srep12257':'Brick assembly.',
 '10.1038/nature24648':'Scaffold-free DNA bricks.',
 '10.1093/nar/gky857':'Octahedral wireframe design.',
 '10.4061/2011/360954':'Tetrahedral wireframe design.',
 '10.1038/ncomms10935':'Four-arm open frame; excluded conservatively under truss/wireframe restriction.',
 '10.1038/s41598-018-25270-6':'RNA origami, not DNA origami.'}
ledger=[];seen=set()
for r in discovery['records']:
    doi=(r.get('doi') or '').lower();key=doi or r['source']+':'+r['id']
    if key in seen:continue
    seen.add(key);s=screen.get(r.get('pmcid'),{})
    status='awaiting_screening';reason='No inclusion decision; broad search includes reviews and irrelevant hits.'
    if doi in accepted:status='has_reviewed_images';reason='Only the explicitly listed designs/images are included, not every design in the paper.'
    elif doi in exclusions:status='excluded';reason=exclusions[doi]
    elif s.get('access_error'):status='fulltext_access_failed';reason=s['access_error']
    elif s:status='fulltext_triaged_awaiting_image_review';reason='Text/supplement links harvested; eligibility and images require review.'
    ledger.append({'publication':r.get('title',''),'doi':doi,'first_publication_date':r.get('firstPublicationDate',''),'pmcid':r.get('pmcid',''),'publication_url':'https://doi.org/'+doi if doi else 'https://europepmc.org/article/'+r['source']+'/'+r['id'],'status':status,'reason':reason})
write_csv('screening_ledger.csv',ledger)

# Original design file inventory, including files whose matching published image is still pending.
repo_dl=json.loads((ASSETS/'sources/repository-downloads.json').read_text())
stack_dl=json.loads((ASSETS/'sources/stacking-downloads.json').read_text())
origins={d['path']:d for d in repo_dl+stack_dl}
gallery={
 'rapid':('10.1093/nar/gkp436','https://www.dropbox.com/scl/fi/j0s0zxzctf8nzc77l28xj/NAR09.zip?rlkey=dwezs6wgre4lzvcinh0u4ij1a&dl=1'),
 'twist':('10.1126/science.1174251','https://www.dropbox.com/scl/fi/9lhrzf8r2svfkyten4izb/Science09.zip?rlkey=n257w8pbudlwn9964ygwma4l2&dl=1'),
 'shapes':('10.1038/nature08016','https://www.dropbox.com/scl/fi/swn5n0yij823rmtrs242p/Nature09.zip?rlkey=wf4rgxmyu6r5i3t1x8so04lk1&dl=1')}
files=[]
for p in sorted((ASSETS/'designs').rglob('*')):
    if not p.is_file() or p.suffix not in ('.json','.cdn','.sc'):continue
    rel=str(p.relative_to(ASSETS));obj=json.loads(p.read_text())
    assert isinstance(obj.get('vstrands'),list) and obj['vstrands'],rel
    group=p.parent.name;origin=origins.get(rel,{})
    if group in gallery:doi,url=gallery[group];origin={'source_url':url,'repository':'https://cadnano.org/gallery.html'}
    elif group=='pScaf':doi='10.1093/synbio/ysy015'
    elif group=='ReuseDNA':doi='10.1093/nar/gkw208'
    elif group=='stacking-bonds':doi='10.1038/nchem.1070'
    else:raise ValueError(group)
    matches=[r['id'] for r in rows if rel in r['design_files']]
    scope='in_scope_reviewed_image' if matches else 'pending_design_to_image_match'
    if 'icosahedron' in p.name:scope='excluded_wireframe'
    files.append({'publication_doi':doi,'path':rel,'local_link':local(rel),'format':'legacy_cadnano_cdn_json' if p.suffix=='.cdn' else 'cadnano_json','origin':'author_provided','source_url':origin['source_url'],'repository':origin.get('repository',''),'git_commit':origin.get('commit',''),'scope_status':scope,'catalog_rows':matches,'bytes':p.stat().st_size,'sha256':checksum(p),'virtual_helices':len(obj['vstrands']),'validation':'JSON decoded; nonempty vstrands. No topology or experimental equivalence validation.'})
write_csv('design_files.csv',files)
file_md=['# Downloaded author design files\n\nResearch assets. Files are original author sources, not reconstructions. “Pending” files are not accepted image-recovery targets. See scope and provenance columns. Legacy `.cdn` files contain caDNAno JSON; originals are kept unchanged.\n','| Publication DOI | File | Scope | Origin |','|---|---|---|---|']
for r in files:file_md.append(f"| [{r['publication_doi']}](https://doi.org/{r['publication_doi']}) | [{Path(r['path']).name}]({r['local_link']}) | {r['scope_status']} | [source]({r['source_url']}) |")
(HERE/'DESIGN_FILES.md').write_text('\n'.join(file_md)+'\n')

# Hash all local evidence used by the table, including sequence lists and microscopy supplements.
manifest={}
for r in rows:
    for field in ['source_file','image_file']:
        rel=r[field];p=ASSETS/rel
        assert p.is_file(),rel
        manifest.setdefault(rel,{'path':rel,'bytes':p.stat().st_size,'sha256':checksum(p),'source_url':r['image_source_url'],'derived_from':r['source_file'] if field=='image_file' and rel!=r['source_file'] else None,'pdf_page':r['pdf_page'] if field=='image_file' else None,'retrieved':'2026-11-02'})
for r in rows:
    for resource in r['staple_list']['sources']+r['imaging_datasets']['resources']:
        rel=resource.get('local_file')
        if not rel: continue
        p=ASSETS/rel
        assert p.is_file(), rel
        manifest.setdefault(rel, {'path':rel,'bytes':p.stat().st_size,'sha256':checksum(p),'source_url':resource['url'].split('#')[0],'retrieved':'2026-11-02'})
for f in files:manifest[f['path']]={k:f[k] for k in ('path','bytes','sha256','source_url','git_commit')}
(HERE/'assets_manifest.json').write_text(json.dumps(list(manifest.values()),indent=2)+'\n')

# A local HTML report, useful when a Markdown renderer cannot display local linked images.
body=[]
for rank,r in enumerate(rows,1):
    fl='<br>'.join(link(Path(f).name,local(f)) for f in r['design_files']) or html.escape(r['file_status'].replace('_',' '))
    body.append(f'''<tr id="{r['id']}"><td>{rank}<br><b>{r['id']}</b><br>Previously #{r['previous_rank']}</td><td><b>{html.escape(r['publication'])}</b><br>{r['first_publication_date']}<br><em>{html.escape(r['design'])}</em><br>{link(r['doi'],r['publication_url'])}</td><td>{r['lattice']}</td><td><a href="{local(r['image_file'])}"><img loading="lazy" src="{local(r['image_file'])}" alt="{html.escape(r['design'])}"></a><br>{link(r['figure_location'],r['image_source_url'])}<br>{link('Local source',local(r['source_file']))}</td><td><b>{r['quality_score']}/100</b><br>{r['image_kind'].replace('_',' ')}<br>{html.escape(r['quality_rationale'])}<details><summary>Score components /4</summary>{html.escape(json.dumps(r['quality_components']))}</details></td><td>{fl}<p>{html.escape(r['file_note'])}</p></td>''' + ''.join('<td>'+cell+'</td>' for cell in extra_html(r)) + '</tr>')
(HERE/'catalog.html').write_text('''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>Pre-2020 DNA origami research catalog</title><style>body{font:15px system-ui;margin:28px;color:#172b3a;background:#fafafa}table{border-collapse:collapse;width:100%;min-width:2400px}th,td{border:1px solid #ccd5db;padding:12px;text-align:left;vertical-align:top}th{background:#e8eef2;position:sticky;top:0}td{min-width:180px}td:first-child{min-width:75px}td:nth-child(3){min-width:90px}img{width:230px;max-height:280px;object-fit:contain;background:white}a{color:#075a8c}td:nth-child(2){max-width:330px}td:nth-child(5),td:nth-child(6){max-width:300px}input{font:inherit;padding:10px;width:400px;max-width:90%}.banner{padding:16px;background:#fff0c2}details{margin-top:12px}summary{cursor:pointer}</style><h1>Pre-2020 DNA origami design images</h1><p class="banner"><b>Research side project — not a production feature.</b> Recovery paused pending the full feature-log revamp. <a href="structure_map.html">Open the expanded structure map, including sequence-only designs.</a> This image subset is not exhaustive. Reviewed November 2, 2026. Scores are provisional.</p><p>''' + f"{len(rows)} image/design groups from {len(accepted)} publications. {len(recovery)} groups await original-file retrieval or image recovery." + ''' Click an image for full size. Rows are sorted by image-only reconstruction completeness; file availability does not affect that score.</p><p><a href="README.md">Methodology</a> · <a href="catalog.csv">CSV</a> · <a href="catalog.json">JSON</a> · <a href="DESIGN_FILES.md">Original files</a> · <a href="screening_ledger.csv">Screening backlog</a></p><label>Filter table <input id="filter" type="search" placeholder="Publication, DOI, design, lattice…"></label><table><thead><tr><th>Rank</th><th>Publication / design</th><th>Lattice</th><th>Published image</th><th>Image-only reconstruction</th><th>Original author files</th><th>Staple list</th><th>Structural characterization</th><th>Imaging datasets / evidence</th></tr></thead><tbody>''' + ''.join(body) + '''</tbody></table><script>document.querySelector('#filter').addEventListener('input',event=>{const q=event.target.value.toLowerCase();document.querySelectorAll('tbody tr').forEach(row=>{row.hidden=!row.textContent.toLowerCase().includes(q)})});</script></html>''')
summary={'score_version':data['score_version'],'staple_lists_available':sum(r['staple_list']['status']=='available' for r in rows),'conceptual_images':sum(r['image_kind']=='conceptual_illustration' for r in rows),'public_raw_datasets_verified':sum(bool(r['imaging_datasets']['raw_dataset_links']) for r in rows),'reviewed_image_groups':len(rows),'publications_with_reviewed_images':len(accepted),'recovery_queue_groups':len(recovery),'downloaded_design_files':len(files),'excluded_downloads':sum(f['scope_status'].startswith('excluded') for f in files),'raw_discovery_records':len(discovery['records']),'deduplicated_screening_records':len(ledger),'referenced_assets_verified':len(manifest),'retained_asset_bytes':sum(p.stat().st_size for p in ASSETS.rglob('*') if p.is_file())}
(HERE/'validation.json').write_text(json.dumps(summary,indent=2)+'\n')
print(json.dumps(summary,indent=2))
