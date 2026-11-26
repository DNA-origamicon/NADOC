"""Isolated native reconstruction packages with explicit partial-result reports."""
import hashlib
import io
import json
import tempfile
import zipfile
from pathlib import Path


def reconstruct_package(payload):
    from backend.core.article_reconstruction import decode_pdf
    from backend.core.publication_authoring import compile_publication
    from tools.design_archive.recorded_authoring import construct
    from scripts.reconstruct_publication_design import compare
    from scripts.agent_structure_guard import publish, audit
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
    with tempfile.TemporaryDirectory(prefix='nadoc-reconstruction-') as temporary:
        root=Path(temporary)
        with zipfile.ZipFile(output,'w',zipfile.ZIP_DEFLATED) as archive:
            for index,choice in enumerate(selections,1):
                if not isinstance(choice,dict) or choice.get('source_sha256') not in sources:
                    raise ValueError('The selected figure source is missing; detect designs again.')
                if any(type(choice.get(k)) is not int or choice[k]<1 for k in ('diagram_page','table_page')):
                    raise ValueError('Select a PDF diagram and endpoint-table page.')
                data=sources[choice['source_sha256']]
                name=f'Reconstructed-{index}-p{choice["diagram_page"]}'
                source_path=f'.provenance/{name}/source.pdf'
                report={'status':'not_constructed','diagram_page':choice['diagram_page'],'table_page':choice['table_page'],
                        'source_sha256':choice['source_sha256']}
                try:
                    recipe,evidence=compile_publication(data,diagram_page=choice['diagram_page'],table_page=choice['table_page'],
                        name=name,source_path=source_path,allow_partial=True)
                    report.update(evidence['reconstruction_report'])
                    design=construct(recipe)
                    comparison=compare(design,evidence)
                    path=root/(name+'.nadoc')
                    publication=publish(design,path)
                    reopened=Design.model_validate_json(path.read_bytes())
                    report['verification']={'comparison':comparison,'publication':publication,'reopened':audit(reopened)}
                    archive.write(path,path.name)
                    archive.writestr(source_path,data)
                    archive.writestr(f'.provenance/{name}/recipe.json',json.dumps(recipe,indent=2))
                    archive.writestr(f'.provenance/{name}/extraction.json',json.dumps(evidence,indent=2))
                except (ValueError,RuntimeError,StopIteration) as exc:
                    report['status']='not_constructed'
                    report['construction_error']=str(exc) or type(exc).__name__
                    if hasattr(exc,'report'):report['bond_review']=exc.report
                archive.writestr(name+'.reconstruction.json',json.dumps(report,indent=2))
            archive.writestr('README.txt','Open the .nadoc files in NADOC. Each reconstruction has a .reconstruction.json report. Partial designs omit unsupported or ambiguous routes; use the report to complete them manually. A report without a .nadoc means native construction or publication validation could not complete. Source PDFs and recipes are in .provenance.\n')
    return output.getvalue()
