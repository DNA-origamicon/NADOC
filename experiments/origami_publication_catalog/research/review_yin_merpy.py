"""Record bounded primary source inspection of MeRPy origami demonstrations."""
import hashlib,json,zipfile,xml.etree.ElementTree as E
import ledger as L
from review_batch_0001 import evidence

def main():
 key='10.1093/nar/gkz998';rid='AUTHOR0003';before=L.counts();base=L.ROOT/'assets/research-20261105';url='https://yin.hms.harvard.edu/publications/2019.ssDNA.sup.zip'
 ev=evidence(base/'yin2019-ssDNA.pdf','https://yin.hms.harvard.edu/publications/2019.ssDNA.pdf','Main pp2–5 origami methods/results/Fig2B; reference26 on p7')
 si=evidence(base/'yin2019-ssDNA-SI.pdf',url,'ZIP member gkz998_supplemental_files/191028_MeRPy_Supporting_Information.pdf; ProtocolS4 printedpp13–14; FigS7 caption only (diagram not geometrically reviewed)')
 seq=evidence(base/'yin2019-ssDNA-sequences.xlsx',url,'ZIP member gkz998_supplemental_files/MeRPy_Sequences.xlsx; Sheet1 rows1–23, especially22–23')
 archive=evidence(base/'yin2019-ssDNA-supplement.zip',url,'Full archive inventory; three nonmetadata files: SI PDF, sequences XLSX, yield XLSX')
 ns={'s':'http://schemas.openxmlformats.org/spreadsheetml/2006/main'};out=[]
 with zipfile.ZipFile(base/'yin2019-ssDNA-sequences.xlsx') as z:
  ss=[''.join(x.itertext()) for x in E.fromstring(z.read('xl/sharedStrings.xml')).findall('s:si',ns)]
  for row in E.fromstring(z.read('xl/worksheets/sheet1.xml')).findall('.//s:row',ns):
   d={}
   for c in row.findall('s:c',ns):
    v=c.find('s:v',ns)
    if v is not None:d[c.get('r')]=ss[int(v.text)] if c.get('t')=='s' else v.text
   out.append(d)
 assert len(out)==23 and out[21]['A22']=='p3315' and out[22]['A23']=='p7308'
 inventory=[]
 with zipfile.ZipFile(base/'yin2019-ssDNA-supplement.zip') as z:
  for x in z.infolist():
   if not x.is_dir():inventory.append(dict(member=x.filename,bytes=x.file_size,sha256=hashlib.sha256(z.read(x.filename)).hexdigest()))
 L.atomic(L.HERE/'yin_merpy_source_inventory.json',json.dumps(dict(archive=archive,members=inventory,sequence_sheet='Sheet1',stored_rows=23,rows=out,limitations='Sequence entries are not staple sets; no sequences/routing certified. Yield workbook inventoried only.'),indent=2)+'\n')
 p=next(p for p in L.read('publication_reviews') if p['registry_key']==key)
 for e in [ev,si,seq,archive]:
  if e not in p['evidence']:p['evidence'].append(e)
 note='Main Fig2B/results demonstrate MeRPy-generated p7308-derived scaffolds folded into30nm barrel(3315nt) and20nm rectangle(7308nt). Barrel explicitly cites Ponnuswamy2017(ref26) as parent. ProtocolS4 barrel pool includes miniscaffold; rectangle requires core/helper/handle pools. Sequence Sheet1 has23 rows including header: rows22/23 contain p3315 and p7308 plus primer/template metadata, not complete staple lists. FigS7 caDNAno diagram exists but geometric/lattice and sequence-to-route matching remain unreviewed.'
 p.update(title='Rapid in vitro production of single-stranded DNA',publication_type=['journal_article'],review_stage='design_sources_reviewed',relevance='design_bearing',design_contributions=['reused_design','uncertain'],catalog_eligibility='unresolved',access='partial',rationale=note,reviewer='Codex main-text, SI protocol and sequence-workbook inspection',run_id=rid,date=L.DATE,unresolved_questions=['Inspect FigS7 geometry and reconcile rectangle/barrel identities with upstream designs.','Acquire complete barrel staple/miniscaffold and rectangle core/helper/handle lists; verify exact scaffold routing and sequences.','Verify first-online date: lab bibliography says12Nov2019; legacy date1Dec2019 retained pending publisher check.','Follow all references and native source links; no complete design source certification.'])
 L.upsert('publication_reviews',p,'Record experimental origami reuse and exact source limitations')
 did='RDE0043';old=next((d for d in L.read('design_evidence') if d['design_id']==did),None)
 if old:assert key in old['publication_keys']
 d=dict(design_id=did,publication_keys=[key],named_objects=['30nm barrel demonstration','20nm rectangle demonstration'],identity_status='Paper-level source-review group for two objects; not proof of new/distinct architectures; upstream reconciliation pending',lattice_decision='Unresolved; FigS7 geometry not yet inspected',catalog_eligibility='unresolved',core_variant_composition=note,relationships=[{'relation':'reuses_design_from','target':'10.1038/ncomms15654','scope':'Barrel explicitly cites main reference26; exact variant matching pending'}],variant_links=[],source_completeness='not_verified',evidence=[ev,si,seq],source_files=[ev,si,seq,archive],outstanding_checks=p['unresolved_questions'],review_stage='source_reviewed',review_run=rid,run_id=rid,date=L.DATE,legacy_record={})
 L.upsert('design_evidence',d,'Retain two demonstrated objects without new-design or source-completeness inference')
 L.upsert('discovery_edges',dict(edge_id='merpy2019:barrel-parent',source_key=key,target_key='10.1038/ncomms15654',relation='reuses_design_from',evidence_url=ev['url'],local_file=ev['local_file'],sha256=ev['sha256'],locator=ev['locator'],reconciliation_state='explicit_parent_attribution; exact_variant_pending',run_id='author-priority-peng-yin',date=L.DATE),'Record explicit barrel source attribution')
 L.upsert('batches',dict(batch_id=rid,date=L.DATE,status='completed',input_keys=[key],selection='Yin/Shih named author bibliography source review',completed_actions=['Inspected main origami experiment, SI folding protocols, sequence Sheet1 and archive inventory.','Recorded two-object source group and explicit barrel reuse edge; no complete sources certified.'],before_counts=before,after_counts=L.counts(),unresolved_keys=[key],exclusion_audit={'sample':[],'reason':'No exclusions.'},validation=[L.validate()],next_queue=p['unresolved_questions']),'Save bounded source review with all followups')
 print(L.validate())
if __name__=='__main__':main()
