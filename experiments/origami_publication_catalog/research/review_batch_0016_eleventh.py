"""Castro NP hinges: separate routing pools and array connectors."""
import json,re,subprocess
from collections import Counter
import ledger as L
from review_batch_0001 import evidence

def main():
 k='10.1021/acs.nanolett.9b02786';rid='B0016';path=L.ROOT/'assets/sources/acs-expansion-20261104/18533306-nl9b02786_si_001.pdf'
 se=evidence(path,'https://ndownloader.figshare.com/files/18533306','SI1-26text/captions read; TablesS1/S2 organization and selected functional rows34,41,42,46,47read. FigureS20PDF35 visually inspected; individual bases and allwrapped sequences not independently audited.')
 te=evidence(L.ROOT/'assets/research-20261105/johnson-control-thesis.pdf','https://etd.ohiolink.edu/acprod/odb_etd/ws/send_file/send?accession=osu1577996668813983&disposition=inline','Titlepage:JoshuaAlanJohnson,OhioState,2020,Control of DNA Origami from Self-Assembly to Higher-Order Assembly. Title/contents and publication-title occurrences inspected; chapters not yet reviewed. Later thesis is source lead,not pre2020 publication.')
 pages=subprocess.check_output(['pdftotext','-layout',str(path),'-']).decode().split('\f');index={}
 for name,start,end in [('S1',25,34),('S2',34,47)]:
  rows=[]
  for page in range(start,end):
   for n in re.findall(r'\bCore\d+\b|\b(?:top|bot)_OH_(?:poly|rep)_set\d+_\d+\b|\bZag_Poly_set\d+_\d+\b',pages[page]):rows.append(dict(name=n,pdf_page=page+1))
  index[name]=rows
 assert sum(x['name'].startswith('Core') for x in index['S1'])==171
 assert sum(x['name'].startswith('Core') for x in index['S2'])==139
 L.atomic(L.HERE/'reciprocal_hinge_source_index.json',json.dumps(dict(evidence=se,named_rows=index,limitations='Name/page index only. Core IDs restart between routing pools. S2 has54polymerizationoverhang and54replacement names plus48separateZag connectors; not one simultaneous mixture. Wrapped sequence bases and repeatedsite labels not resolved.'),indent=2)+'\n')
 note='SI25 explicitly states two different staple routings: TableS1 sites1-3 (171Core labels), TableS2 site4/polymerization/fluorescence (139Core labels). Core numbering restarts and is not cross-design identity. Site4 bottom overhangs5A-9A have three strands perlength; bivalent/trivalent and NP5/15nm conditions are distinguished. TableS2 includes54polymerizationoverhang names(24top,30bottom),54matchingreplacement names and48separateZag connectors in pools4/8/12/24 labeledset1/2/3/6. SItext describes sixsets of four; extra bottomsets7/8 need exactrecipe reconciliation. Polymer arrays use bridging strands between neighboring hinge arms,with100%,50%,33%overlap,not ordinary staple extensions. Alexa488 and BHQ1 labeledstrands report state. 8064scaffold is identified in gel captions; fullsequence/native lattice, exactparenthinge and all variant recipes pending. Open/closed bindingstates not distinct designs automatically.'
 qs=['Review Johnson2020thesis relevantchapters for main-paper context and parent hinge attribution; later thesis must not become pre2020 eligible record.','Acquire/compare journal main and nativecaDNAno to resolve arm geometry/lattice and sourceversions.','Audit both routing-specific staple mixtures; reconcile sixsets-of-four description with extra bottomsets7/8 and replacement usage.','Map48Zag connector strands to100/50/33percent overlap assembly recipes; retain assembly identity separately.','Independently reconstruct wrapped sequence table rows and verify fullscaffold/labels without counting all alternate oligos in one mixture.','Verify exactfirst-online date: ACSbannerOctober30 versus explicit history/PubMedNovember6,both2019.']
 p=next(p for p in L.read('publication_reviews') if p['registry_key']==k)
 p.update(review_stage='design_sources_reviewed',relevance='design_bearing',design_contributions=['modified_design'],catalog_eligibility='unresolved',access='SI_and_related2020thesis_available; main_review_pending',rationale=note,reviewer='Codex SI source-composition and selected routing visual review',run_id=rid,date=L.DATE,unresolved_questions=qs)
 for ev in [se,te]:
  if ev not in p['evidence']:p['evidence'].append(ev)
 L.upsert('publication_reviews',p,'Distinguish hinge routing pools,NPvariants and array assembly connectors')
 did='RDE0065';old=next((d for d in L.read('design_evidence') if d['design_id']==did),None);assert old is None or k in old['publication_keys']
 L.upsert('design_evidence',dict(design_id=did,publication_keys=[k],named_objects=['NP hinge sites1-3 routing','NP hinge site4/polymerization routing','Zigzag hinge arrays with100/50/33percent arm overlap'],identity_status='Two explicit staple-routing pools with functional variants and separate array assemblies; parentdesign identity pending',lattice_decision='caDNAno routing visible; physical arm packing not established by routingdiagram alone.',catalog_eligibility='unresolved',core_variant_composition=note,relationships=[dict(relation='array_assembly',components='neighboring hinge arms',connection='separate bridging polymerization strands',evidence=se)],variant_links=[],source_completeness='not_verified',source_files=[se,te],evidence=[se,te],outstanding_checks=qs,review_stage='source_reviewed',review_run=rid,run_id=rid,date=L.DATE,legacy_record={}), 'Preserve hinge and assembly source roles without certifying fullset')
 L.upsert('discovery_edges',dict(edge_id='B0016:reciprocal:johnson2020thesis',source_key=k,target_key='thesis:johnson2020:osu1577996668813983',relation='related_source_lead',citation='JoshuaAlanJohnson,Control of DNA Origami from Self-Assembly to Higher-Order Assembly,OhioState2020. Relevantchapters not reviewed.',evidence_url=te['url'],local_file=te['local_file'],sha256=te['sha256'],locator=te['locator'],reconciliation_state='pending_exact_variant_and_source_verification',run_id=rid,date=L.DATE),'Retain acquired laterthesis as source lead,not pre2020 publication')
 b=next(b for b in L.read('batches') if b['batch_id']==rid);action='Reviewed13of25: CastroNP-hinge SI separates2routing pools and assembly connectors;2020Johnsonthesis acquired publicly for followup. Fullsource/parentmapping pending.'
 if action not in b['completed_actions']:b['completed_actions'].append(action)
 b.update(after_counts=L.counts(),validation=[L.validate()],next_queue=['Review acquiredJohnsonthesis relevantchapters for hingeparent/source context.','Remaining12B0016inputs; next10.1021/acsnano.9b05746 downloadedSI.',*qs]);L.upsert('batches',b,'Save13of25progress and publicthesis acquisition');print(L.validate())
if __name__=='__main__':main()
