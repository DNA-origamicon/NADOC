"""Read-only sequence-table extraction; does not create molecular structures."""
import hashlib,json,re,subprocess
import ledger as L

def main():
 path=L.ROOT/'assets/sources/acs-expansion-20261104/14534945-la8b03804_si_001.pdf'
 text=subprocess.check_output(['pdftotext','-layout',str(path),'-'],text=True)
 headings=['S2.1 Sequences for the rectangle','Forming a large pore requires','“Horizontal” strands folding','“Vertical” strands folding','Forming a small pore requires','Forming a half of the rectangle requires','Forming a half of the rectangle (no seam) requires']
 starts=[text.index(h) for h in headings];blocks={}
 for i,h in enumerate(headings):
  section=text[starts[i]:starts[i+1] if i+1<len(starts) else text.index('The same method applies')]
  rows=re.findall(r'^\s*(t?-?\d+r\d+[a-z]|tr-rem1)[,，]?\s*[：:]\s*([ACGT]+)\s*$',section,re.M)
  blocks[h]=dict(rows=rows,row_count=len(rows),unique_names=len(dict(rows)))
 base=dict(blocks[headings[0]]['rows'])
 checks={}
 for h in headings[1:]:
  rows=blocks[h]['rows'];norm=[(n if n.startswith('t') else 't'+n,s) for n,s in rows]
  checks[h]=dict(missing_names=[n for n,s in norm if n not in base],sequence_mismatches=[n for n,s in norm if n in base and base[n]!=s])
 out=dict(source=str(path),sha256=hashlib.sha256(path.read_bytes()).hexdigest(),method='pdftotext layout; named row regex; small-pore t-prefix normalized only for comparison',limitations='Extraction audit only; not a native routing or scaffold coverage validation. Color maps and omission geometry not verified.',blocks=blocks,checks=checks)
 L.atomic(L.HERE/'la8b03804_table_audit.json',json.dumps(out,indent=2)+'\n')
 print(json.dumps(dict(counts={h:b['row_count'] for h,b in blocks.items()},checks=checks)))
if __name__=='__main__':main()
