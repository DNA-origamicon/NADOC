"""Read-only archive metadata; no extraction, execution or molecular authoring."""
import hashlib,json
from pathlib import PurePosixPath
from zipfile import ZipFile
import ledger as L

def main():
 records=[]
 for name in ['14163344-nn8b08671_si_002.zip','14163347-nn8b08671_si_003.zip']:
  path=L.ROOT/'assets/sources/acs-expansion-20261104'/name
  with ZipFile(path) as z:
   members=[dict(name=i.filename,bytes=i.file_size,sha256=hashlib.sha256(z.read(i)).hexdigest()) for i in z.infolist() if not i.is_dir()]
  records.append(dict(file=str(path.relative_to(L.ROOT)),sha256=hashlib.sha256(path.read_bytes()).hexdigest(),members=members))
 library=records[0]['members']
 ply=[m for m in library if m['name'].endswith('_Geometry.ply')]
 seq=[m for m in library if m['name'].endswith('_Sequence.csv')]
 assert len(ply)==len(seq)==240
 assert {str(PurePosixPath(m['name']).parent) for m in ply}=={str(PurePosixPath(m['name']).parent) for m in seq}
 out=dict(archives=records,geometry_sequence_directory_pairs=240,method='List and hash existing ZIP members in memory; confirm directory pairing only',limitations=['240 file pairs are not independently validated source sets or experimentally confirmed designs.','No software executed and no structures extracted, modified or reconstructed.','Content-level sequence/scaffold/routing consistency remains unaudited.'])
 L.atomic(L.HERE/'talos_archive_inventory.json',json.dumps(out,indent=2)+'\n')
 print(json.dumps({'file_pairs':240,'non_directory_members':[len(r['members']) for r in records]}))

if __name__=='__main__':main()
