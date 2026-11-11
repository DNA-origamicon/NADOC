"""Read-only source inventory. Requires xlrd; never authors a molecular structure."""
import hashlib,json,zipfile
import xlrd
import ledger as L
from review_batch_0001 import evidence

def main():
 root=L.ROOT/'assets/sources/acs-expansion-20261104'
 path=root/'8831800-nn7b03187_si_002.xls';b=xlrd.open_workbook(path)
 sheets=[{'name':s.name,'rows':s.nrows,'columns':s.ncols,'first_two_rows':[s.row_values(i) for i in range(min(2,s.nrows))]} for s in b.sheets()]
 path2=root/'10302255-nn7b06699_si_002.zip';z=zipfile.ZipFile(path2);members=[]
 for info in z.infolist():
  row={'name':info.filename,'bytes':info.file_size,'compressed_bytes':info.compress_size,'crc32':f'{info.CRC:08x}'}
  if info.filename.endswith(('.json','.svg')):
   data=z.read(info.filename);row['sha256']=hashlib.sha256(data).hexdigest()
   if info.filename.endswith('.json'):
    j=json.loads(data);row.update(json_name=j.get('name'),top_level_keys=list(j),virtual_helix_records=len(j.get('vstrands',[])),first_helix_fields=list(j['vstrands'][0]))
  members.append(row)
 out={'xls':evidence(path,'https://ndownloader.figshare.com/files/8831800','All sheet names, dimensions and first two rows; not full sequence/variant audit'),'xls_reader':{'library':'xlrd','version':xlrd.__version__},'sheets':sheets,'zip':evidence(path2,'https://ndownloader.figshare.com/files/10302255','Entire central-directory inventory; JSON and SVG bytes read and hashed; AVI not inspected'),'members':members,'limitations':['Sheet row counts are not sequence or complete source counts.','JSON presence and virtual-helix count do not certify physical geometry, full staple coverage or source compatibility.','PDF text FigS15 says three offset groups; spreadsheet11H-shift header says two. Preserve discrepancy.']}
 L.atomic(L.HERE/'batch_0011_source_inventory.json',json.dumps(out,ensure_ascii=False,indent=2)+'\n');print({'sheets':len(sheets),'archive_members':len(members)})
if __name__=='__main__':main()
