from pathlib import Path
import sys,json,re,zipfile,xml.etree.ElementTree as ET
import pymupdf
ROOT=Path(__file__).resolve().parents[3];A=ROOT/'experiments/origami_publication_catalog/assets';O=A/'sources/pre2020-expansion'
records=json.loads((O/'supplement_downloads.json').read_text());out=[]
by_pmc={r['pmcid']:r for r in json.loads((O/'screening.json').read_text())}
for item in json.loads((A/'sources/evidence-downloads.json').read_text()):
 for f in item.get('downloads',[]):
  if f['path'].endswith('.pdf'):
   records.append({'status':'downloaded','doi':by_pmc.get(item['pmcid'],{}).get('doi',''),'pmcid':item['pmcid'],'filename':Path(f['path']).name,'local_file':f['path'],'url':f['source_url']})
records=list({r.get('local_file',r.get('url')):r for r in records}.values())
for r in records:
 if r['status']!='downloaded':continue
 p=A/r['local_file'];item=dict(r);item['sequence_like_strings']=0;item['sequence_pages']=[]
 try:
  if p.suffix.lower()=='.pdf':
   doc=pymupdf.open(p);pages=[]
   for i,page in enumerate(doc):
    text=page.get_text();n=len(re.findall(r'[ACGT]{15,}',text));item['sequence_like_strings']+=n
    if n>10:item['sequence_pages'].append(i+1)
    lines=[l.strip()for l in text.splitlines() if re.search(r'staple|sequence|honeycomb|square.lattice|DNA origami|Table S',l,re.I)]
    if lines:pages.append({'page':i+1,'sequence_like_strings':n,'headings':lines[:10]})
   item['page_evidence']=pages;(O/(p.stem+'.text.txt')).write_text('\n'.join(page.get_text()for page in doc))
  elif p.suffix.lower()in ('.xlsx','.docx'):
   z=zipfile.ZipFile(p);text=' '.join(' '.join(ET.fromstring(z.read(n)).itertext())for n in z.namelist()if n in ['xl/sharedStrings.xml','word/document.xml']);item['sequence_like_strings']=len(re.findall(r'[ACGT]{15,}',text));item['text_excerpt']=text[:600]
  elif p.suffix.lower()=='.zip':item['members']=zipfile.ZipFile(p).namelist()
 except Exception as e:item['parse_error']=str(e)
 out.append(item)
(O/'supplement_inventory.json').write_text(json.dumps(out,indent=2))
for r in out:
 if r['sequence_like_strings']>30:print(r['pmcid'],r['doi'],r['filename'],'SEQ',r['sequence_like_strings'],'pages',r['sequence_pages'])
