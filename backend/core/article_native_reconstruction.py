"""Isolated native reconstruction packages with explicit partial-result reports."""
import hashlib
import io
import json
import tempfile
import zipfile
from collections import Counter
from pathlib import Path

from backend.core.publication_reconstruction_report import (
    ReconstructionBlocked, classify_reconstruction, package_entry,
)


def reconstruct_package(payload):
    from backend.core.article_reconstruction import decode_pdf
    from backend.core.publication_authoring import compile_publication
    from tools.design_archive.recorded_authoring import construct
    from scripts.reconstruct_publication_design import compare
    from scripts.agent_structure_guard import publish, audit
    from scripts.agent_bond_review import BondReviewRequired
    from experiments.recorded_review_process import ProcessRequired
    from backend.core.models import Design
    if payload.get('scaffold_sequence', '').strip():
        raise ValueError('Native generation currently supports publication-named library scaffolds; custom scaffold generation is not yet supported.')
    selections=payload.get('selections',[])
    if not isinstance(selections,list) or not 1<=len(selections)<=20:
        raise ValueError('Select between one and twenty detected figure/list pairs.')
    sources={}
    for item in [payload.get('paper'),*payload.get('supplements',[])]:
        if item:
            data=decode_pdf(item);sources[hashlib.sha256(data).hexdigest()]=data
    output=io.BytesIO()
    entries = []
    with tempfile.TemporaryDirectory(prefix='nadoc-reconstruction-') as temporary:
        root=Path(temporary)
        with zipfile.ZipFile(output,'w',zipfile.ZIP_DEFLATED) as archive:
            for index,choice in enumerate(selections,1):
                if not isinstance(choice,dict) or choice.get('source_sha256') not in sources:
                    raise ValueError('The selected figure source is missing; detect designs again.')
                if any(type(choice.get(k)) is not int or choice[k]<1 for k in ('diagram_page','table_page')):
                    raise ValueError('Select a PDF diagram and table page.')
                data=sources[choice['source_sha256']]
                name=f'Reconstructed-{index}-p{choice["diagram_page"]}'
                source_path=f'.provenance/{name}/source.pdf'
                report={'status':'not_constructed','diagram_page':choice['diagram_page'],'table_page':choice['table_page'],
                        'source_sha256':choice['source_sha256']}
                imported = None
                native_file = failure = None
                stage, default_code = 'extraction', 'extraction_failed'
                try:
                    if choice.get('table_modules') is not None:
                        from backend.core.publication_import_evidence import extraction_evidence
                        imported = extraction_evidence(data, choice)
                        if imported['table_import']:
                            raise ReconstructionBlocked(
                                'sequence_alignment_unresolved',
                                'Module table imported; strand placement and nucleotide registration remain unresolved. See source-evidence.json.')
                    recipe,evidence=compile_publication(data,diagram_page=choice['diagram_page'],table_page=choice['table_page'],
                        name=name,source_path=source_path,allow_partial=True)
                    report.update(evidence['reconstruction_report'])
                    stage, default_code = 'construction', 'construction_failed'
                    design=construct(recipe)
                    stage, default_code = 'verification', 'verification_failed'
                    compare(design,evidence)
                    path=root/(name+'.nadoc')
                    stage, default_code = 'publication', 'publication_failed'
                    publication=publish(design,path)
                    reopened=Design.model_validate_json(path.read_bytes())
                    stage, default_code = 'verification', 'verification_failed'
                    report['verification']={'comparison':compare(reopened, evidence),
                                            'publication':publication,'reopened':audit(reopened)}
                    archive.write(path,path.name)
                    native_file = path.name
                    archive.writestr(f'.provenance/{name}/recipe.json',json.dumps(recipe,indent=2))
                    archive.writestr(f'.provenance/{name}/extraction.json',json.dumps(evidence,indent=2))
                except (ValueError,RuntimeError,StopIteration) as exc:
                    report['status']='not_constructed'
                    report['construction_error']=str(exc) or type(exc).__name__
                    code = default_code
                    if isinstance(exc, ReconstructionBlocked):
                        code = exc.code
                    elif isinstance(exc, ProcessRequired):
                        code = 'process_required'
                    elif isinstance(exc, BondReviewRequired):
                        code = 'bond_review_required'
                        report['bond_review'] = exc.report
                    failure = (stage, code, report['construction_error'])
                # Preserve imported rows and visible raster traces even when native routing fails.
                from backend.core.publication_import_evidence import extraction_evidence
                try:
                    imported = imported or extraction_evidence(data, choice)
                    if imported['table_import'] or imported['raster_evidence']:
                        archive.writestr(f'.provenance/{name}/source-evidence.json', json.dumps(imported,indent=2))
                        report['source_evidence'] = f'.provenance/{name}/source-evidence.json'
                        report['remaining_import_steps'] = (imported['raster_evidence'] or {}).get('unresolved', [])
                        fallback = imported.get('sequence_fallback')
                        if fallback:
                            report['sequence_fallback_summary'] = {
                                'status':fallback.get('status','candidate_domains_only'),
                                'scaffold_name':fallback.get('scaffold_name'),
                                'refinement_summary':{
                                    'added_candidates':fallback.get('anchor_refinement',{}).get('added_candidates'),
                                    'paired_bases':(fallback.get('anchor_refinement',{}).get('compatibility') or {}).get('paired_bases'),
                                    'surviving_cores':len((fallback.get('anchor_refinement',{}).get('anchor_recheck') or {}).get('anchors',[])),
                                    'unassigned_scaffold_bases':fallback.get('anchor_refinement',{}).get('residual_scaffold',{}).get('unassigned_bases'),
                                    'offset_endpoint_markers':fallback.get('image_anchor_candidates',{}).get('offset_marker_count',0),
                                    'connector_drawings':fallback.get('image_anchor_candidates',{}).get('connector_drawing_count',0),
                                    'connector_hypotheses':fallback.get('image_anchor_candidates',{}).get('connector_candidate_count',0),
                                    'image_mapping_status':'classified_staple_candidates_unresolved' if fallback.get('image_anchor_candidates') else 'not_attempted'},
                                'anchor_summary': {
                                    'sampled_cores':len(fallback.get('anchors',{}).get('anchors',[])),
                                    'provisional_cores':sum(a['status']=='provisional_sequence_anchor' for a in fallback.get('anchors',{}).get('anchors',[])),
                                    'shared_paired_bases':fallback.get('anchors',{}).get('shared_paired_bases'),
                                    'challenges':fallback.get('anchors',{}).get('challenge_summary'),
                                    'limitation':fallback.get('anchors',{}).get('limitation')},
                                'native_routing_resolved':False,
                                'passes':[{'minimum_domain':p['minimum_domain'],
                                    'compatible_paired_bases':p['compatibility'].get('paired_bases'),
                                    'solver_status':p['compatibility']['status'],
                                    'alternative_search':{k:v for k,v in p['compatibility'].get('alternative_search',{}).items() if k!='assignments'},
                                    'candidate_pool_complete':p['compatibility']['candidate_pool_complete']}
                                    for p in fallback.get('passes',[])]}

                except (ValueError, RuntimeError) as exc:
                    report['source_evidence_error'] = str(exc)
                archive.writestr(source_path, data)
                report['source_file'] = source_path
                report['classification'] = classify_reconstruction(
                    report, native_file=native_file, source_evidence=imported, failure=failure)
                report_file = name + '.reconstruction.json'
                archive.writestr(report_file, json.dumps(report, indent=2))
                entries.append(package_entry(report_file, report))
            counts = Counter(entry['output'] for entry in entries)
            archive.writestr('reconstruction-index.json', json.dumps({
                'schema_version': 1, 'results': entries,
                'counts': {status: counts[status] for status in ('complete', 'partial', 'report_only')},
            }, indent=2))
            lines = ['Reconstruction results', '']
            for entry in entries:
                label = entry['output'].replace('_', ' ')
                lines.append(f"{entry['name']} — {label} — {entry['native_file'] or entry['report_file']}")
                for issue in entry['issues']:
                    lines.append(f"  {issue['code']}: {issue['action']}")
            lines.extend(['', 'Open the .nadoc files in NADOC and consult their .reconstruction.json reports.',
                          'See reconstruction-index.json for file paths and issue details.'])
            archive.writestr('README.txt', '\n'.join(lines) + '\n')
    return output.getvalue()
