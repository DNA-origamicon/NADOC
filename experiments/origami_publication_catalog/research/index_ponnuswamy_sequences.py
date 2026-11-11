"""Index workbook cells and modifications without inferring strand roles or completeness."""
import json,re,zipfile,xml.etree.ElementTree as E
from collections import Counter
import ledger as L
from review_batch_0001 import evidence
NS={'s':'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
def cells(path):
 with zipfile.ZipFile(path) as z:
  ss=[''.join(x.itertext()) for x in E.fromstring(z.read('xl/sharedStrings.xml')).findall('s:si',NS)]
  sheets=E.fromstring(z.read('xl/workbook.xml')).findall('s:sheets/s:sheet',NS);assert len(sheets)==1 and sheets[0].get('name')=='Sheet1'
  result=[]
  for c in E.fromstring(z.read('xl/worksheets/sheet1.xml')).findall('.//s:sheetData/s:row/s:c',NS):
   v=c.find('s:v',NS)
   if v is None:continue
   value=ss[int(v.text)] if c.get('t')=='s' else v.text
   bare=re.sub(r'/[^/]+/','',value)
   result.append(dict(cell=c.get('r'),value=value,sequence_candidate=bool(re.fullmatch('[ACGTacgt]+',bare)),base_count=len(bare) if re.fullmatch('[ACGTacgt]+',bare) else None,modifications=re.findall(r'/[^/]+/',value)))
  return result

def main():
 base=L.ROOT/'assets/research-20261105/shih-extracted/34';source=json.loads((L.HERE/'shih_source_archive_inventory.json').read_text());url=next(x for x in source if x['ordinal']==34)['archive']['url'];out=[]
 for n in range(1,11):
  p=base/f'PonnuswamyN_ncomm_2017_SuppData{n}.xlsx';r=cells(p);seq=[x for x in r if x['sequence_candidate']]
  out.append(dict(supplement_number=n,sheet='Sheet1',evidence=evidence(p,url,'Author ZIP member '+p.name+'; Sheet1 cell index'),nonempty_cells=len(r),sequence_candidate_cells=len(seq),nonsequence_cells=[x for x in r if not x['sequence_candidate']],length_histogram=dict(Counter(x['base_count'] for x in seq)),modification_counts=dict(Counter(m for x in seq for m in x['modifications'])),cells=r))
 L.atomic(L.HERE/'ponnuswamy_sequence_index.json',json.dumps(dict(workbooks=out,limitations='Candidate counts are lexical cell counts, not verified staple or synthesis-set counts. No routing reconstruction, molecular authoring or sequence-to-route validation performed.'),indent=2)+'\n')
 for r in out:print(r['supplement_number'],r['sequence_candidate_cells'],[(c['cell'],c['value']) for c in r['nonsequence_cells']],r['modification_counts'])
if __name__=='__main__':main()
