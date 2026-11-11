"""Custom-scaffold source inspection and read-only supplemental inventory."""
import hashlib,json,posixpath
from zipfile import ZipFile
from xml.etree import ElementTree as E
import ledger as L
from review_batch_0001 import evidence

def main():
 folder=L.ROOT/'assets/sources/acs-expansion-20261104'
 files=['14941472-nn9b01025_si_001.pdf','14941475-nn9b01025_si_002.xlsx','14941478-nn9b01025_si_003.zip']
 n={'m':'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
 inventory={'files':[{ 'name':f,'sha256':hashlib.sha256((folder/f).read_bytes()).hexdigest()} for f in files],'limitations':'Read-only workbook/archive inventory; no software executed, structures generated, or full synthesis sets certified.'}
 with ZipFile(folder/files[2]) as z:
  inventory['archive_members']=[dict(name=i.filename,size=i.file_size) for i in z.infolist()]
 with ZipFile(folder/files[1]) as z:
  ss=[''.join(t.itertext()) for t in E.fromstring(z.read('xl/sharedStrings.xml')).findall('m:si',n)]
  rel={r.attrib['Id']:r.attrib['Target'] for r in E.fromstring(z.read('xl/_rels/workbook.xml.rels'))}
  sheets=[]
  for s in E.fromstring(z.read('xl/workbook.xml')).findall('m:sheets/m:sheet',n):
   target=rel[s.attrib['{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id']]
   path=target.lstrip('/') if target.startswith('/') else posixpath.normpath('xl/'+target)
   rows=[]
   for row in E.fromstring(z.read(path)).findall('m:sheetData/m:row',n):
    cells=[]
    for c in row.findall('m:c',n):
     v=c.find('m:v',n)
     if v is not None:
      value=ss[int(v.text)] if c.attrib.get('t')=='s' else v.text
      cells.append(dict(cell=c.attrib['r'],length=len(value),preview=value[:140]))
    rows.append(cells)
   sheets.append(dict(name=s.attrib['name'],stored_rows=len(rows),rows=rows))
  inventory['workbook_sheets']=sheets
 L.atomic(L.HERE/'nn9b01025_source_inventory.json',json.dumps(inventory,indent=2)+'\n')
 key='10.1021/acsnano.9b01025';p=next(p for p in L.read('publication_reviews') if p['registry_key']==key)
 for f,loc in zip(files,['Note S1 workflow; Notes S2/S3 headings and production descriptions; Fig S6–S17 captions, including duplicated S17 label','Workbook sheet names and named scaffold/header entries inspected; entire cell inventory summarized','Archive member inventory only; software not executed']):
  ev=evidence(folder/f,'https://ndownloader.figshare.com/files/'+f.split('-')[0],loc)
  if ev not in p['evidence']:p['evidence'].append(ev)
 ev=evidence(L.HERE/'nn9b01025_source_inventory.json','https://doi.org/'+key,'Read-only file hashes, ZIP member inventory and workbook cells/lengths/previews')
 if ev not in p['evidence']:p['evidence'].append(ev)
 p.update(title=p['legacy_record']['publication'],review_stage='design_sources_reviewed',relevance='design_bearing',design_contributions=['uncertain'],catalog_eligibility='unresolved',access='partial',rationale='SI documents42-helix bundles with conventional/custom scaffold variants; SC3–SC6 share SC2 topology but edge oligos carry10T rather than3T. One-pot experiments include pointer and10-helix bundles, while dual-scaffold controls use94-helix bundles. Dimer/trimer/tetramer/pentamer assemblies must be distinguished from monomer cores. Fig S15 shows126-helix bundle SC1/SC2; S16 shows13-helix bundles with1024/1536/2048nt scaffolds. Switch arms join through two DNAzyme cassettes. Both switch and welding-pointer diagrams are labeled S17 (printed21 and22). Workbook contains only Scaffolds and Helper plasmids sheets, with21 and3 stored rows respectively; rows are not a count of designs or complete synthesis sets. ZIP contains GENE_SPLITTER,SEQUENCE_STATISTICS,SCAFFOLD_SMITH nested software packages and readme; not executed. Full main article, per-object scaffold/staple/routing reconciliation, native design availability, parent lineage and lattice/source eligibility remain pending.',unresolved_questions=['Inspect main article and reconcile each diagram/variant to actual scaffold and complete staple set.','Inspect nested package documentation as needed without running authoring software; find native design sources.','Follow backward/forward citations and author histories; distinguish scaffold variants from core geometry and assemblies.'],reviewer='Codex named SI captions/workflow plus workbook and archive inventory',run_id='B0015',date=L.DATE)
 L.upsert('publication_reviews',p,'Record multi-design scaffold study without conflating source inventory and complete sets')
 b=next(b for b in L.read('batches') if b['batch_id']=='B0015');b['completed_actions'].append('Input9 custom-scaffold paper reviewed; PDF captions and XLSX/ZIP inventories saved;9of25 first passes.')
 b.update(after_counts=L.counts(),validation=[L.validate()],next_queue=['acscentsci.9b00174 and remaining6ACS plus10rotating2015 inputs','FNANO2010,234CV identities and all prior source/citation followups'])
 L.upsert('batches',b,'Save9of25 first-pass coverage')
 L.atomic(L.HERE/'batch_0015_fifth_audit.json',json.dumps(dict(reviewed_keys=[key],first_pass_count=9,input_count=25,validation=L.validate(),counts=L.counts()),indent=2)+'\n');print(L.validate())
if __name__=='__main__':main()
