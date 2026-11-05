"""Index retrieved PDFs/archives for review; matches never certify eligibility."""
import json
import hashlib
import re
import zipfile
from pathlib import Path
import pymupdf

H = Path(__file__).resolve().parents[1]

def main():
    audit = json.loads((H / 'acs_acquisition.json').read_text())
    rows = []
    native_files = []
    for record in audit['records']:
        for source in record['files']:
            if source['status'] != 'downloaded':
                continue
            path = H / 'assets' / source['local_file']
            row = {'doi': record['doi'], 'local_file': source['local_file'], 'sha256': source['sha256'], 'status': 'unindexed_format'}
            try:
                if path.suffix.lower() == '.pdf':
                    with pymupdf.open(path) as doc:
                        row.update(status='text_indexed_unreviewed', pages=len(doc), sequence_pages=[], design_pages=[], lattice_contexts=[])
                        for number, page in enumerate(doc, 1):
                            text = page.get_text()
                            if re.search(r'sequence|oligonucleotide|staple strand', text, re.I):
                                row['sequence_pages'].append(number)
                            if re.search(r'cadnano|folding path|design schematic|routing|design template', text, re.I):
                                row['design_pages'].append(number)
                            for match in re.finditer(r'honeycomb|square.lattice|hexagonal.lattice|wireframe|DNA.brick', text, re.I):
                                if len(row['lattice_contexts']) < 6:
                                    row['lattice_contexts'].append({'page': number, 'text': ' '.join(text[max(0, match.start()-100):match.end()+170].split())})
                elif path.suffix.lower() == '.zip':
                    with zipfile.ZipFile(path) as archive:
                        row.update(status='archive_names_indexed_unreviewed', members=archive.namelist(), possible_native_design_members=[n for n in archive.namelist() if n.lower().endswith(('.json', '.cdn', '.sc', '.scadnano'))])
                        for name in row['possible_native_design_members']:
                            if archive.getinfo(name).file_size > 50 * 1024**2:
                                continue
                            try:
                                data = archive.read(name)
                                parsed = json.loads(data)
                                if not isinstance(parsed, dict) or not parsed.get('vstrands'):
                                    continue
                                native_files.append({'doi': record['doi'], 'publication': record['publication'], 'archive': source['local_file'], 'archive_sha256': source['sha256'], 'member': name, 'member_sha256': hashlib.sha256(data).hexdigest(), 'format': 'caDNAno vstrands JSON', 'helix_records': len(parsed['vstrands']), 'qualification': 'Original archive member decoded in memory; no topology/sequence/eligibility validation and no native NADOC publication.'})
                            except (ValueError, UnicodeError):
                                continue

            except Exception as exc:
                row.update(status='index_failed', error=str(exc))
            rows.append(row)
    (H / 'acs_source_index.json').write_text(json.dumps({'qualification': 'Automated retrieval aids only; no eligibility or completeness inference.', 'rows': rows}, indent=2) + '\n')
    (H / 'acs_native_file_inventory.json').write_text(json.dumps(native_files, indent=2) + '\n')
    print('Indexed', len(rows), 'files; native-file archive leads:', sum(bool(r.get('possible_native_design_members')) for r in rows))

if __name__ == '__main__':
    main()
