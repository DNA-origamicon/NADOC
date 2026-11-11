"""Hash and inventory selected author archives; safely extract scientific files."""
import hashlib,json,zipfile,subprocess
from pathlib import PurePosixPath
import ledger as L
from review_batch_0001 import evidence

def main():
 base=L.ROOT/'assets/research-20261105';manifest=json.loads((base/'acquisition.json').read_text());out=[]
 for n in [26,32,34,44]:
  name=f'shih-source-{n}.zip';p=base/name;ev=evidence(p,manifest[name]['url'],'Author-linked ZIP; content inventory does not certify design completeness');members=[]
  with zipfile.ZipFile(p) as z:
   assert sum(i.file_size for i in z.infolist())<500*1024**2
   assert z.testzip() is None
   for i in z.infolist():
    if i.is_dir():continue
    data=z.read(i.filename);h=hashlib.sha256(data).hexdigest();metadata=i.filename.startswith('__MACOSX/') or PurePosixPath(i.filename).name.startswith('._')
    row=dict(member=i.filename,bytes=len(data),sha256=h,metadata=metadata)
    if not metadata:
     ext=PurePosixPath(i.filename).suffix.lower();assert ext in ['.pdf','.xlsx']
     target=base/'shih-extracted'/str(n)/PurePosixPath(i.filename).name;target.parent.mkdir(parents=True,exist_ok=True)
     if target.exists():assert hashlib.sha256(target.read_bytes()).hexdigest()==h
     else:target.write_bytes(data)
     row['local_file']=str(target.relative_to(L.ROOT))
     if ext=='.pdf':
      assert data.startswith(b'%PDF-');txt=target.with_suffix('.txt');subprocess.run(['pdftotext','-layout',str(target),str(txt)],check=True)
      row['text_file']=str(txt.relative_to(L.ROOT));row['text_sha256']=hashlib.sha256(txt.read_bytes()).hexdigest()
    members.append(row)
  out.append(dict(ordinal=n,archive=ev,members=members,scientific_files=sum(not m['metadata'] for m in members),content_status='scientific_files_present_unreviewed' if any(not m['metadata'] for m in members) else 'empty_scientific_content'))
 L.atomic(L.HERE/'shih_source_archive_inventory.json',json.dumps(out,indent=2)+'\n')
 for r in out:print(r['ordinal'],r['scientific_files'],r['content_status'])
if __name__=='__main__':main()
