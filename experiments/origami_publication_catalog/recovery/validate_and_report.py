"""Post-recovery held-out checks. Never writes recovered topology/sequences."""
from recover_first5 import ROOT,OUT,REVIEW,ASSETS,dump,Design,validate_design
import pymupdf,json,re,csv,collections,hashlib,html
cases=[('D007','shapes-supp.pdf',12),('D008','shapes-supp.pdf',13),('D005','twist-supp.pdf',37),('D006','twist-supp.pdf',39)]
results=[]
for ident,file,pg in cases:
 path=next(REVIEW.glob(ident+'*.nadoc'));d=Design.model_validate_json(path.read_text());hmap={h.id:h for h in d.helices}
 text=pymupdf.open(ASSETS/'sources'/file)[pg-1].get_text()
 refs=[{'start':(int(h),int(b)),'end':(int(e),int(f)),'sequence':''.join(seq.split()),'length':int(n)} for h,b,e,f,seq,n in re.findall(r'(\d+)\[(\d+)\]\s+(\d+)\[(\d+)\]\s+([ACGT\s]+?)\s+(\d+)\s+#[a-fA-F0-9]+',text)]
 byseq={r['sequence']:r for r in refs};bystart={r['start']:r for r in refs}
 rows=[];paired={};comp_errors=0
 for s in d.strands:
  loc=[(dom.helix_id,b) for dom in s.domains for b in range(dom.start_bp,dom.end_bp+(1 if dom.start_bp<=dom.end_bp else -1),1 if dom.start_bp<=dom.end_bp else -1)]
  if s.strand_type.value=='scaffold':
   if s.sequence:paired.update(zip(loc,s.sequence))
   continue
  if s.sequence:
   comp_errors+=sum(base!=paired[key].translate(str.maketrans('ACGT','TGCA')) for key,base in zip(loc,s.sequence) if key in paired)
  a,z=s.domains[0],s.domains[-1];start=(int(hmap[a.helix_id].label),a.start_bp);end=(int(hmap[z.helix_id].label),z.end_bp)
  length=sum(abs(dom.end_bp-dom.start_bp)+1+sum(ls.delta for ls in hmap[dom.helix_id].loop_skips if min(dom.start_bp,dom.end_bp)<=ls.bp_index<=max(dom.start_bp,dom.end_bp)) for dom in s.domains)
  ref=byseq.get(s.sequence) if s.sequence else bystart.get(start)
  rows.append({'strand_id':s.id,'image_start':str(start),'image_end':str(end),'image_length_nt':length,'sequence_5to3':s.sequence or '', 'sequence_status':'image glyphs' if s.sequence else 'UNRESOLVED: no nucleotide letters in figure','published_start':str(ref['start']) if ref else '', 'published_end':str(ref['end']) if ref else '', 'published_length_nt':ref['length'] if ref else '', 'exact_sequence_match':bool(s.sequence and ref), 'endpoints_and_length_match':bool(ref and start==ref['start'] and end==ref['end'] and length==ref['length']), 'domains_5to3':'; '.join(f'{hmap[x.helix_id].label}[{x.start_bp}→{x.end_bp}]' for x in s.domains)})
 with (REVIEW/(ident+'_staples.csv')).open('w',newline='') as f:
  w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
 assert validate_design(d).passed and comp_errors==0
 result={'id':ident,'published_staples':len(refs),'image_staples':len(rows),'exact_sequence_matches':sum(r['exact_sequence_match'] for r in rows),'endpoints_and_lengths_match':sum(r['endpoints_and_length_match'] for r in rows),'complement_mismatches':comp_errors,'unmatched_image_sequences':[r for r in rows if r['sequence_5to3'] and not r['exact_sequence_match']],'sequence_not_reconstructed':sum(not r['sequence_5to3'] for r in rows),'source_table_page':pg,'source_table_pdf':file,'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'nadoc_validator_passed':True,'save_reload_passed':Design.model_validate_json(d.model_dump_json()).model_dump()==d.model_dump()}
 if ident=='D008':result['coordinate_convention']='Every matched table start/end is image coordinate +4. Figure-local BP register retained; no author JSON used to resolve this discrepancy.'
 results.append(result)
dump(REVIEW/'validation.json',results);dump(OUT/'held_out_validation.json',results)
for r in results:print({k:v for k,v in r.items() if k not in ('unmatched_image_sequences','sha256')})
# Self-contained review index with source/trace evidence and explicit failures.
notes={'D007':'Image-only topology and sequences. All 144 published staples match exactly.', 'D008':'149 image staples; all 148 published sequences match. One image staple is absent from the table. Table coordinates = figure-local coordinates +4; absolute register discrepancy remains unresolved.','D005':'217 image-derived staple routes; 361 insertion sites (360 × 1 nt + one 144-nt loop), 8,064 scaffold nt. No nucleotide letters: sequences remain unassigned.','D006':'209 image-derived staple routes, 7,704 scaffold nt. Carrier helix19 placement used author-file diagnostics after a logged image-only failure. No nucleotide letters: sequences remain unassigned.','D021':'INCOMPLETE: 55 helix positions and 62 unjoined scaffold evidence fragments. No staples or inter-helix connections recovered. Fragment boundaries are not biological nicks. Absolute register unknown.'}
rowshtml=[]
for ident in ['D007','D008','D005','D006','D021']:
 p=next(REVIEW.glob(ident+'*.nadoc'));report=json.loads((OUT/(ident+'_report.json')).read_text());dump(REVIEW/(ident+'_recovery.json'),report)
 links=f'<a href="{p.name}">NADOC</a> · <a href="{ident}_recovery.json">recovery evidence</a>'
 if ident!='D021':links+=f' · <a href="{ident}_staples.csv">staple list</a>'
 rowshtml.append(f'<tr><td>{ident}</td><td>{html.escape(notes[ident])}</td><td>{links}</td></tr>')
(REVIEW/'review.html').write_text('<!doctype html><meta charset="utf-8"><title>First five image recovery attempts</title><style>body{max-width:1200px;margin:35px auto;font:16px system-ui;line-height:1.5;color:#203040}td,th{padding:16px;border:1px solid #ccd4dd;text-align:left}table{border-collapse:collapse}a{color:#075a9c}</style><h1>First five image recovery attempts</h1><p>Side project · research drafts · ranked order · 2 sequence recoveries, 2 routing-only recoveries, 1 incomplete raster attempt.</p><p>Published staple lists were held out until comparison. Original caDNAno files were not recovery inputs; the sole diagnostic exception is D006 helper-helix placement. A NADOC validator pass checks internal consistency, not agreement with an unavailable or ambiguous source.</p><table><tr><th>Design</th><th>Result and limitations</th><th>Review files</th></tr>'+''.join(rowshtml)+'</table><p><a href="validation.json">Held-out validation</a> · <a href="PROCESS.txt">Process and provenance</a></p>')
(REVIEW/'PROCESS.txt').write_text('''FIRST FIVE IMAGE RECOVERY ATTEMPTS — research side project, not a production feature

Ranking snapshot: D007 (100), D008 (100), D005 (100), D006 (98), D021 (85).

Process generalized from Gerling:
1. Restrict recovery input to the selected published figure page. Keep author designs and staple tables out of the parser.
2. Distinguish vector from raster evidence. Normalize figure rotation; calibrate base pitch and numbered helix tracks. Do not substitute a native scaffold router.
3. Trace actual 5′→3′ stroked paths, with arrows/parity as checks. Preserve long/nonlocal junctions and unpaired carriers. Decode slice labels rather than relying on PDF drawing order.
4. Decode subset-font nucleotide glyphs by inspecting magnified visible glyphs. Use only letters printed on the image, never the held-out staple sequences.
5. Read every insertion label. D005 has a 144-nt insertion as well as 360 one-base insertions; treating every marker as +1 loses 143 nt.
6. Require unique base occupancy, reciprocal links, strand polarity and NADOC validation. Export image-derived strand topology through the existing importer; synthesized interchange data are NOT author caDNAno files.
7. Save recovery outputs before consulting staple tables. Compare full sequences, endpoints and lengths; do not fill unknown nucleotides from the table.
8. On a recorded failure, narrowly inspect author files for diagnostics. D006: helix19 is missing from the figure's slice, so only its position relative to helix0 was taken from protractor_0_v3.json. No author routing or sequences were copied. No other native file was read during recovery.
9. Retain unresolved cases as explicitly partial evidence, not guessed complete designs. D021 has no recoverable vector paths and no native file; current raster segmentation retains scaffold fragments and slice locations only.

Generalization limits:
- This is a reusable extraction framework with figure-specific calibration/glyph maps, not a universal unattended recognizer.
- Routing-only figures cannot determine absolute nucleotide sequences without an external scaffold sequence and its assignment register. D005/D006 have no assigned sequences; the published scaffold identities p8064/p7704 were observed only during held-out checking.
- D008 has one image-only staple (sequence recorded in validation.json) absent from the 148-entry table, plus a four-base coordinate offset. Its image-local register is retained.
- D021: fragment ends are extraction boundaries, NOT physical nicks; do not simulate or synthesize this partial file.
- Lattice geometry is unrelaxed. No physical folding or simulation validation was performed.

Reproducible scripts:
experiments/origami_publication_catalog/recovery/recover_first5.py
experiments/origami_publication_catalog/recovery/recover_pin_partial.py
experiments/origami_publication_catalog/recovery/validate_and_report.py
Run with .venv/bin/python from the repository root. Recovery scripts do not read reference staple tables or original design files (D006's diagnosed placement relation is documented in code).

Detailed trace evidence, source crops, pre-comparison hashes and failure logs:
.development-artifacts/image-recovery-first5-20261102/ (mounted Archive)
''')
