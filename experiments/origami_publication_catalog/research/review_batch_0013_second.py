"""Primary SI review and read-only scaffold table inventory."""
import json,re,hashlib,subprocess
import ledger as L
import review_batch_0013_first as base
ROWS=[('10.1021/acs.nanolett.8b01374','12302483-nl8b01374_si_004.pdf','12302483','SI p2methods; FigS2caption/p7,FigS3/p8; TableS2/p27; references/p37; graphical sequences not fully traced',
 'Six-helix DOTP uses425nt scaffold cut by BsaAI from7308ntM13 with two helper oligos; TableS2 gives scaffold and16numbered staples plus functional strands. FigS2 identifies1H1P with peptide on helix4or6,1H2P,2H2P,3H2P; table distinguishes22%/77%GC hairpins on helices1/3/5, dye,quencher-thiol,passivation and peptide/biotin variants. Cellular assays use cRGDfK whereas BFP uses biotin adhesion strands. These vary force transduction/attachment on a shared bundle; exact staple replacement and mixed-hairpin subsets require diagram/main audit. Simulation sections exist but were not executed or used to certify experimental compositions.'),
('10.1021/acsami.8b04757','12304379-am8b04757_si_001.pdf','12304379','17-page SI p2FigS1/S2,p3FigS3/TablesS1/S2; TablesS3/S4headers and supplementary caption survey; p17references',
 'DE and LS origami have caDNAno diagrams and separate staple tables. LS diagram marks changes relative to DE; handles separately bind gold-attachment oligos and bioreceptors. Structural relations and full differences need map/sequence audit, not assumed to be mere ligand variants. Separate tetrahedron comparator assembles three53ntthiolated strands plus55ntplain or103ntTBA-bearing strand; this four-oligo object must not be counted as an origami core. TBA,biotin,thiol andfluorescent oligos are supplied separately. FigS2caption calls five color categories but describes four; preserve discrepancy and inspect color map. Exact scaffold/base/native sources and table coverage unresolved.'),
('10.1021/acsami.8b09222','12383498-am8b09222_si_001.pdf','12383498','33-page SI pp3–5design/assembly; FigsS5–S10 pp8–12; TablesS2–S5 scaffold text inventory',
 'Single-layer rectangles use caDNAno square lattice; triangles use Tiamat. FigsS6–S10 map10563ntrectangle,10782nttriangle,21261ntrectangle,31274ntrectangle and31274nttriangle; FigS5also reports M13mp18rectangle comparator. TableS4instead labels20307nt and extracted sequence length20307, conflicting with methods/caption21261nt. Other tables extract10563,10782,31274bases;10782table has a lowercase t retained in source and accepted in case-insensitive count. Sequence count is not sequence correctness or complete design proof. Staple/native-file availability and graphical routing require separate audit; square-lattice statement applies rectangles, not automatically triangles.')]
def main():
 path=L.ROOT/'assets/sources/acs-expansion-20261104/12383498-am8b09222_si_001.pdf'
 s=subprocess.check_output(['pdftotext','-layout',str(path),'-']).decode();rows=[]
 for n in range(2,6):
  a=s.index('Table S'+str(n)+'.');b=s.index('Table S'+str(n+1)+'.',a) if n<5 else s.index('References',a)
  lines=[l.strip() for l in s[a:b].splitlines() if re.fullmatch('[ACGTacgt]+',l.strip())];seq=''.join(lines)
  rows.append(dict(table='S'+str(n),extracted_bases=len(seq),lowercase_bases=sum(c.islower() for c in seq),sequence_sha256=hashlib.sha256(seq.encode()).hexdigest()))
 L.atomic(L.HERE/'chen2018_scaffold_inventory.json',json.dumps(dict(source=str(path.relative_to(L.ROOT)),sha256=hashlib.sha256(path.read_bytes()).hexdigest(),method='pdftotext layout; concatenate only all-ACGT lines, accepting upper/lower case without altering source; no molecular construction',tables=rows,limitation='Not sequence correctness, scaffold identity reconciliation or synthesis-source certification'),indent=2)+'\n')
 pubs={p['registry_key']:p for p in L.read('publication_reviews')}
 for key,name,fid,loc,note in ROWS:
  e=base.evidence(L.ROOT/'assets/sources/acs-expansion-20261104'/name,'https://ndownloader.figshare.com/files/'+fid,loc);p=pubs[key]
  if e not in p['evidence']:p['evidence'].append(e)
  p.update(title=p['legacy_record']['publication'],review_stage='design_sources_reviewed',relevance='design_bearing',design_contributions=['uncertain'],catalog_eligibility='unresolved',access='partial',rationale=note,unresolved_questions=['Inspect main/native sources and full scaffold/staple/variant compositions.','Resolve diagram and sequence discrepancies and narrow catalog scope.','Follow bibliography, forward citations and author routes.'],reviewer='Codex named SI sections',run_id='B0013',date=L.DATE)
  L.upsert('publication_reviews',p,'Record next three SI reviews with explicit evidence limits')
 b=next(b for b in L.read('batches') if b['batch_id']=='B0013')
 b['completed_actions']=[a for a in b['completed_actions'] if a!='First2of25inputs inspected: FRET triangular arrays and light-driven enzyme channeling supplement; no complete-source certifications.']+['First2inputs inspected: FRET arrays and channeling SI.','Next3inputs inspected: tension probes,DE/LSbiosensing andcustom scaffolds;5of25first-pass coverage,20unreviewed.']
 b.update(next_queue=['Remaining10ACS SI starting bioconjchem8b00418','Ten rotating2015records','FNANO2010 and prior source/discovery followups'],after_counts=L.counts(),validation=[L.validate()])
 L.upsert('batches',b,'Save cumulative5of25screened,20unreviewed')
 L.atomic(L.HERE/'batch_0013_second_audit.json',json.dumps(dict(reviewed_keys=[r[0] for r in ROWS],first_pass_count=5,input_count=25,scaffold_inventory=rows,validation=L.validate(),counts=L.counts()),indent=2)+'\n')
if __name__=='__main__':main()
