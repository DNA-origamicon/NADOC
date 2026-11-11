"""Resumable PDF extraction with source hashes and retained parser diagnostics.
Text is an index only; inspect source images for layout, colors and sequences.
"""
import hashlib
import json
from pathlib import Path
import subprocess
import ledger as L


def main():
    root=L.ROOT/'assets/research-20261105';manifest_path=root/'text_index.json'
    manifest=json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
    selected=set()
    for r in L.read('publication_reviews'):
        if r['review_stage']!='unreviewed':
            selected.update(e['local_file'] for e in r.get('evidence',[]) if e.get('local_file','').endswith('.pdf'))
    selected.update(str(p.relative_to(L.ROOT)) for p in root.glob('FNANO*.pdf'))
    for relative in sorted(selected):
        source=L.ROOT/relative; digest=hashlib.sha256(source.read_bytes()).hexdigest();target=root/(source.stem+'.txt')
        old=manifest.get(relative)
        if old and old['sha256']==digest and target.exists() and hashlib.sha256(target.read_bytes()).hexdigest()==old.get('text_sha256'):continue
        result=subprocess.run(['pdftotext','-layout',str(source),'-'],capture_output=True)
        if result.returncode==0:
            L.atomic(target,result.stdout.decode('utf-8'))
        manifest[relative]={'source':relative,'sha256':digest,'text_file':str(target.relative_to(L.ROOT)),
                           'text_sha256':hashlib.sha256(result.stdout).hexdigest() if result.returncode==0 else None,
                           'status':'indexed_with_warnings' if result.returncode==0 and result.stderr else 'indexed' if result.returncode==0 else 'failed',
                           'parser':'pdftotext -layout','stderr':result.stderr.decode('utf-8',errors='replace'),
                           'review_status':'extraction_is_not_review','date':L.DATE}
        L.atomic(manifest_path,json.dumps(manifest,indent=2)+'\n')
    print(json.dumps({'sources':len(manifest),'warnings':[k for k,v in manifest.items() if v['status']!='indexed']},indent=2))


if __name__=='__main__':main()
