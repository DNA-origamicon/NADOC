"""Build source-addressable stage-two evidence and independent reference audits."""
import json
from pathlib import Path
import pymupdf
from backend.core.image_reconstruction import extract_page_evidence, cadnano_summary


def run(root, source):
    inventory = {r['id']:r for r in json.loads(Path('frontend/src/data/nanobase_inventory.json').read_text())['records']}
    report = []
    for entry in json.loads((root/'evaluation/summary.json').read_text()):
        result = {'id':entry['id'], 'source_pdf_sha256':entry['review']['pdf_sha256'], 'page':entry['review']['page'], 'figure':entry['review']['figure'], 'references':[]}
        with pymupdf.open(entry['source_pdf']) as doc:
            evidence = extract_page_evidence(doc[entry['review']['page']-1])
        dest = root/'reconstruction'/str(entry['id']);dest.mkdir(parents=True,exist_ok=True)
        (dest/'evidence.json').write_text(json.dumps(evidence))
        result['paths'] = len(evidence['paths'])
        result['raster_images'] = evidence['raster_images']
        for native in inventory[entry['id']]['files']:
            if native.get('schema') != 'caDNAno v2':continue
            ref = {'name':native['name']}
            try:
                data = json.loads((source/'native'/str(entry['id'])/native['name']).read_text())
                audit = cadnano_summary(data)
                ref.update(counts=audit['counts'],crossovers=len(audit['crossovers']),termini=len(audit['termini']),connectivity_problems=len(audit['connectivity_problems']))
                (dest/(native['name']+'.audit.json')).write_text(json.dumps(audit,indent=2))
            except Exception as exc: ref['error']=str(exc)
            result['references'].append(ref)
        result['reconstruction_status']='Needs reviewed registration and strand walks' if evidence['paths'] else 'Raster tracing required'
        result['discrepancy_status']='Not base-resolved: detected candidates cannot yet be equated to complete reference designs'
        report.append(result)
    (root/'reconstruction-summary.json').write_text(json.dumps(report,indent=2))


if __name__=='__main__':
    import sys
    run(Path(sys.argv[1]),Path(sys.argv[2]))
