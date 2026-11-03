"""Render the completed audit as a portable, source-linked review table."""
import hashlib
import html
import json
from pathlib import Path


def run(root):
    baseline = json.loads((root/'evaluation/summary.json').read_text())
    reconstruction = {r['id']:r for r in json.loads((root/'reconstruction-summary.json').read_text())}
    exports = json.loads((root/'export-comparison.json').read_text())
    inventory = {r['id']:r for r in json.loads(Path('frontend/src/data/nanobase_inventory.json').read_text())['records']}
    e = html.escape
    sections=[]
    for b in baseline:
        rid=b['id'];r=reconstruction[rid]
        references='; '.join(f"{x['name']}: {x.get('counts',{}).get('active_helices','?')} helices, {x.get('crossovers','?')} directed crossovers, {x.get('connectivity_problems','?')} invalid links" for x in r['references']) or 'No parseable reference JSON (moDON)'
        candidates='; '.join(f"{c['rows']} detected rows / {c['crossovers']} branches" for c in b['candidates']) or 'No candidates detected'
        image_kind='Substantial vector content' if r['paths']>100 else 'Raster routing (incidental vector marks possible)'
        sections.append(f'<tr><td>{rid}</td><td>{e(inventory[rid]["title"])}</td><td><a href="{e(b["source_url"],quote=True)}">{e(b["review"]["figure"])}</a><br>PDF page {b["review"]["page"]}</td><td>{image_kind}</td><td>{e(candidates)}</td><td>{e(references)}</td></tr>')
        review={'name':inventory[rid]['title']+' image reconstruction draft','source_sha256':b['review']['pdf_sha256'],'source_page':b['review']['page'],'evidence_ids':[], 'registration_source':None,'directions_reviewed':False,'termini_reviewed':False,'indels_reviewed':False,'lattice':None,'helices':[],'anchors':{},'routes':[],'indels':[]}
        (root/'reconstruction'/str(rid)/'review-template.json').write_text(json.dumps(review,indent=2))
    export_rows=[];classification=[]
    for x in exports:
        g=x.get('aligned_geometry',{});matching=[]
        for c in x['deposited_comparisons']:
            if c.get('compatible_ordered_topologies'):
                confirmed=c['header'][0]=='t = 0' and c['conditional_index_aligned_geometry']['rmsd_nm']<1e-8
                classification.append({'record':x['id'],'native':x['native'],'configuration':c['file'],'status':'converter-matching starting configuration' if confirmed else ('exclude: nonzero simulation time' if c['header'][0] != 't = 0' else 'unresolved zero-time candidate: converter-coordinate mismatch'),'header':c['header'],'reference_rmsd_nm':c['conditional_index_aligned_geometry']['rmsd_nm']})
                matching.append('converter-matching start' if confirmed else ('EXCLUDE: simulated state despite unrelaxed label' if c['header'][0] != 't = 0' else 'UNRESOLVED: zero-time file differs from converter'))
        export_rows.append(f'<tr><td>{x["id"]}</td><td>{e(x["native"])}</td><td>{x.get("nadoc",{}).get("nucleotides","?")}</td><td>{g.get("particles","?")}</td><td>{g.get("rmsd_nm",0):.3f}</td><td>{g.get("a3_median_angle_deg",0):.2f}°</td><td>{e("; ".join(matching))}</td></tr>')
    (root/'starting-state-classification.json').write_text(json.dumps(classification,indent=2))
    body='''<!doctype html><html lang="en"><meta charset="utf-8"><title>NADOC figure and exporter audit</title><style>body{font:16px system-ui;margin:2em;max-width:1600px;color:#17212b}table{border-collapse:collapse;width:100%;font-size:14px}td,th{padding:9px;border:1px solid #b9c6d3;text-align:left;vertical-align:top}th{background:#e5edf4}h1,h2{color:#173e61}p{max-width:1050px;line-height:1.5}code{background:#edf1f5}summary{cursor:pointer}</style>
<h1>21-record figure reconstruction and oxDNA export audit</h1><p>27 October 2026. All 21 verified figure records were passed through the existing evaluator, one verified page at a time. Original source hashes and page numbers are retained. Shared paper/pages and multiple uploaded variants are not independent training pairs.</p>
<p><strong>Outcome:</strong> candidates in 3/21 records; no complete image-derived design validated. Fourteen raster-routing records need tracing; seven have substantial vector content. Rotating/scaling vector drawings can produce severe grid false positives. Detection counts below are observations, not reconstruction accuracy.</p>
<p><strong>Next-stage prototype:</strong> source-addressable vector primitives; explicit piecewise BP anchors; directed reviewed-image trace expansion; caDNAno draft compilation preserving nicks and single branches; exact site/crossover/terminus/indel reference differences. Headless CLI: <code>python -m tools.design_archive.reconstruct_image</code>. Each reconstruction folder contains an intentionally incomplete review template. Reference-assisted registration must be labelled and cannot be called independent reconstruction. No production geometry or live designs were changed.</p>
<h2>All figure records</h2><table><thead><tr><th>Nanobase</th><th>Design</th><th>Published figure</th><th>Image content</th><th>Baseline detector</th><th>Deposited reference variants</th></tr></thead><tbody>'''+''.join(sections)+'''</tbody></table>
<h2>Exporter comparison</h2><p>Nine deposited configurations across eight records reproduce fresh tacoxDNA coordinates and orientations to numerical precision (position RMSD ≤1.1×10⁻¹⁰ nm). Record 35's description-labelled unrelaxed file has t=100358760 and nonzero energies; excluded. Its filename-labelled unrelaxed alternative has zero time/energies but differs from the current converter by 2.926 nm RMSD; retained as an unresolved starting-state candidate. Descriptions conflict with filenames. Records 52/53 provide topology files labelled relaxed, but their ordered adjacency matches the fresh converter; coordinates independently match. Other records lack explicit, verified pre-relaxed inputs in the inspected manifests.</p>
<p>NADOC import → native Full geometry → ordinary unseeded oxDNA export was compared with tacoxDNA commit b8a1706d27548c96dcb13eabc8e5b9340bf241c3, seed 1234. The lattice choice follows NADOC's current import classification, and the deposited-coordinate matches independently support that choice for nine files. Particle counts and strand-length multisets match in all ten trials. All tested single-copy-address directed neighbors match; inserted-copy order is not assumed, so this is not full graph certification. Sequences are not validated: converter defaults can randomize bases while caDNAno usually omits sequence.</p>
<p><strong>Geometry equivalence fails.</strong> Table positions use one proper rigid rotation/translation (no reflection, scaling, deformation, or periodic unwrapping), with particle registration from caDNAno helix/bp/strand-class addresses. Axes use that same rotation. These metrics do not diagnose a root cause or predict relaxation success. No constants, phase conventions or production exporters were changed. No energy minimizations or simulations were run.</p>
<table><thead><tr><th>Record</th><th>Native file</th><th>Total particles</th><th>Mapped single-copy particles</th><th>Position RMSD (nm)</th><th>Median a3 angle</th><th>Deposited state</th></tr></thead><tbody>'''+''.join(export_rows)+'''</tbody></table>
<h2>Specific discrepancies and limits</h2><ul><li>Square record132: 88 detected rows equals 88 reference helices, but a single color subset is not the whole routed design.</li><li>Tweezer record18: detector fragments the drawing into six overlapping/color subsets (11–26 rows) versus 56 reference helices; those counts must not be summed.</li><li>Modular triangle270: 26 detected rows versus 29 reference helices; three missing helices cannot be asserted without registration. Publication/upload interface variants remain unresolved.</li><li>Records16 and35 share a T-pore publication panel but deposited native files have 126 versus79 active helices and different nucleotide counts. They are not interchangeable references.</li><li>Record311 has three seed/SST native variants, while only seed-S Fig.S1 was visually verified. Record19 has two NanoDyn variants; record18 has two positioner variants.</li><li>Nanoengine196: the figure labels helices0–24 (25 identities), whereas the deposited NE_halo_dsDNA reference has20 active helices. This is a visible completeness/variant discrepancy requiring pairing review.</li><li>moDON263 has a verified figure but no parseable archived native reference. No invented comparison is substituted.</li><li>All24 parseable reference variants have reciprocal neighbor links. This does not establish publication equivalence, chemical correctness or physical stability.</li><li>Source figure completeness, helix IDs, direction, scaffold register, missing/half crossovers, nicks, insertions/deletions and overhangs require review. Upscaling cannot supply missing evidence.</li></ul>
<h2>Evidence files</h2><p><a href="evaluation/summary.json">Baseline</a> · <a href="normalization-summary.json">Rejected normalization hypotheses</a> · <a href="reconstruction-summary.json">Reference audits</a> · <a href="export-comparison.json">Full export metrics</a> · <a href="starting-state-classification.json">Starting-state classification</a> · <a href="starting-oxdna/manifest.json">Downloaded-input hashes/descriptions</a></p>
<p>Source converter documentation: <a href="https://github.com/lorenzo-rovigatti/tacoxDNA/tree/b8a1706d27548c96dcb13eabc8e5b9340bf241c3">pinned tacoxDNA</a>. Tests and software provenance: <a href="verification.json">verification.json</a>.</p></html>'''
    (root/'report.html').write_text(body)
    source_hashes={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in [Path('backend/core/cadnano.py'),Path('backend/core/design_geometry.py'),Path('backend/physics/oxdna_interface.py'),Path('backend/core/image_evaluation.py'),Path('backend/core/image_reconstruction.py')]}
    (root/'software-source-hashes.json').write_text(json.dumps(source_hashes,indent=2))


if __name__=='__main__':
    import sys
    run(Path(sys.argv[1]))
