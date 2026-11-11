"""Wireframe evolution: main/SI review and read-only source archive inventory."""
import hashlib,html,json,re,zipfile
from pathlib import PurePosixPath
import ledger as L
from review_batch_0001 import evidence

def main():
 k='10.1021/acsnano.9b03473';rid='B0016';base=L.ROOT/'assets/sources/acs-expansion-20261104'
 mp=L.ROOT/'assets/research-20261105/evolution-main.html'
 me=evidence(mp,'https://pmc.ncbi.nlm.nih.gov/articles/PMC7613751/','Complete author manuscript Abstract, Introduction, Results/Discussion and Methods text read. MainFig1-3captions read; manuscript available2022 does not change original2019 publication date.')
 se=evidence(base/'18005924-nn9b03473_si_002.pdf','https://ndownloader.figshare.com/files/18005924','All7pages text read; Figure6PDF7TEM visually inspected for reported initial/optimized square rod comparison.')
 zp=base/'18005921-nn9b03473_si_001.zip';ze=evidence(zp,'https://ndownloader.figshare.com/files/18005921','ZIP read-only inventory with per-file hashes; README decodedcp1252 and read; prova.top first5lines inspected. No archive software executed or structures authored.')
 members=[];candidates=[]
 with zipfile.ZipFile(zp) as z:
  for x in z.infolist():
   p=PurePosixPath(x.filename);data=z.read(x) if not x.is_dir() else b''
   row=dict(name=x.filename,bytes=x.file_size,sha256=hashlib.sha256(data).hexdigest(),directory=x.is_dir())
   members.append(row)
   if p.suffix in ['.ply','.rpoly','.top','.json','.ma','.csv','.xlsx'] and not any(s.startswith('._') for s in p.parts) and '/maya_python_packages/' not in x.filename:candidates.append(row)
  assert len(members)==3577
  header=z.read('oxDNAiter/prova.top').decode().splitlines()[0].strip()
 L.atomic(L.HERE/'evolution_archive_inventory.json',json.dumps(dict(evidence=ze,members=members,total_uncompressed_bytes=sum(x['bytes'] for x in members),source_candidates=candidates,topology_header=header,limitations='Inventory only; filenames and15908nucleotides/205strands header are not proof of mapping to experimental design. No complete figure-specific sequence/native source set verified.'),indent=2)+'\n')
 note='Main/SI study wireframe origami: small barrel60helices/about2200bp, smaller30helix722bp structure, full-size hexagonal rod/about8000bp,198edge sphere with directed/random mutation variants, and square-cross-section13subunit rod with internal supports. Insertion/deletion and relocated staple-staple support connections produce actual modified designs; hundreds of simulations/mutations are not automatically distinct verified designs. Only the supported square rod is explicitly experimentally compared before/after optimization in mainFig3/SIFig6; other reviewed objects are computational examples. Broad census design-bearing, narrow catalog excluded as wireframe/truss despite word square in cross-section. ZIP is experimental software for moving internal edges (READMEFig3), mostly bundled libraries and metadata; five candidate geometry/topology files do not establish complete experiment-specific source sets. prova.top header15908nucleotides205strands cannot be assigned to a paper figure without evidence.'
 qs=['Map five archive geometry/topology candidates to exact figures/variants using contents and manuscript; do not infer from filenames.','Find complete scaffold/staple sets and initial/final support connectivity for experimentally compared square rods.','Reconcile predecessor designs with Benson2015Nature523:441 reference18; methods reuse is not proof of unchanged design reuse.','Split source group into resolved design identities and generation variants only when source mapping supports it.','Compare author manuscript with version of record and verify exact first-online date;2019 documented.','Reconcile36main references and maintain priority-author/citation routes.']
 p=next(p for p in L.read('publication_reviews') if p['registry_key']==k)
 p.update(review_stage='design_sources_reviewed',relevance='design_bearing',design_contributions=['new_design','modified_design'],catalog_eligibility='excluded',access='public_author_manuscript_HTML_and_SI_PDF_ZIP_available',rationale=note,reviewer='Codex main/SI text review,experimental figure visual and read-only archive inventory',run_id=rid,date=L.DATE,unresolved_questions=qs)
 for e in [me,se,ze]:
  if e not in p['evidence']:p['evidence'].append(e)
 L.upsert('publication_reviews',p,'Separate broad wireframe design relevance from narrow catalog exclusion')
 did='RDE0062';old=next((d for d in L.read('design_evidence') if d['design_id']==did),None);assert old is None or k in old['publication_keys']
 L.upsert('design_evidence',dict(design_id=did,publication_keys=[k],named_objects=['60helix barrel','30helix722bp small structure','Hexagonal wireframe rod','198edge sphere','13subunit internally supported square wireframe rod'],identity_status='Five source families and iterative variants; not one geometry or a certified count of unique designs',lattice_decision='Explicit wireframe meshes and internal struts; square/hexagonal rod cross-section does not imply square/honeycomb packing.',catalog_eligibility='excluded',core_variant_composition=note,relationships=[],variant_links=[],source_completeness='not_verified',source_files=[se,ze],evidence=[me,se,ze],outstanding_checks=qs,review_stage='source_reviewed',review_run=rid,run_id=rid,date=L.DATE,legacy_record={}), 'Record wireframe family sourcegroup without catalog expansion')
 raw=mp.read_text();refs=re.findall(r'<li id="(R\d+)">(.*?)</li>',raw,re.S);assert len(refs)==36
 for n,t in refs:
  cite=re.search(r'<cite>(.*?)</cite>',t,re.S);d=re.search(r'href="https://doi.org/([^"]+)"',t)
  citation=html.unescape(re.sub('<[^>]+>',' ',cite.group(1) if cite else t))
  L.upsert('discovery_edges',dict(edge_id='B0016:evolution:'+n,source_key=k,target_key=html.unescape(d.group(1)).lower() if d else 'citation:evolution:'+n,relation='cites',citation=citation,evidence_url=me['url'],local_file=me['local_file'],sha256=me['sha256'],locator='MainHTML '+n,reconciliation_state='pending_identity_date_scope_reconciliation',run_id=rid,date=L.DATE),'Retain36author-manuscript references')
 b=next(b for b in L.read('batches') if b['batch_id']==rid);action='Reviewed11of25: evolutionary wireframe refinement main/SI; five source families and experimental supported-rod comparison recorded. ZIP3577members inventoried,36references saved; catalog excluded but census design-bearing.'
 if action not in b['completed_actions']:b['completed_actions'].append(action)
 if k not in b['exclusion_audit']['sample']:b['exclusion_audit']['sample'].append(k)
 b['exclusion_audit']['reason']+=' Evolution paper: main explicitlywireframe; internal supports and squarecrosssection do not satisfy filled-domain lattice scope.'
 b.update(after_counts=L.counts(),validation=[L.validate()],next_queue=['Remaining14B0016inputs; next10.1021/jacs.9b09308 downloadedSI.',*qs]);L.upsert('batches',b,'Save11of25progress and explicit broad/narrow distinction');print(L.validate())
if __name__=='__main__':main()
