"""Coating protocol explicitly reuses Ahmadi2018, not Ponnuswamy objects."""
import re,html
import ledger as L
from review_batch_0001 import evidence

def main():
 k='10.3791/58771';parent='10.1039/c7nr09461b';rid='B0016';path=L.ROOT/'assets/research-20261105/jove58771.html'
 ev=evidence(path,'https://www.jove.com/t/58771/gene-therapy-inspired-polycation-coating-for-protection-dna-origami','Local publisherHTML contains full article despite webtoolchallenge. Introduction, preparation/purification steps1-2, functionalization assays11-12, Results, Figures1-4captions, Discussion and28references inspected. Protocolsteps3-10 not fully read; video not viewed.')
 note='JoVEprotocol explicitly adapts priorAhmadi2018study ref16; allFigures1-4 credit modified previouslypublished figures. Results identify threeobjects: square-lattice nanorodNR and honeycomb nanobottleNB designed withcaDNAno; DAEDALUSwireframeWN. Chitosan andLPEIcoat/decoat conditions do not establish independent newcores. NRfunctional variants use3biotinylated staples for streptavidin-HRP and up to24PS2.M aptamers with15ntlinker; originalsequence positions and complete staples notpresent in inspectedarticle. Ponnuswamy2017is contextref12, not demonstrated parentoftheseobjects. Sourceidentity supported atfamily/protocol level; base-level recipes remain unverified.'
 qs=['Acquire Ahmadi2018main/SI/nativefiles and exactNR/NB/WN sequences; attempted RSCc7supplement path404.','Resolve scaffold lengths, core dimensions and specificfunctionalized stapleIDs.','Read remainingprotocolsteps3-10 and inspect video if required for source completeness.','Audit NR/NBwholeobject lattice/source eligibility; keepWNwireframeexcluded from narrowcatalog.']
 p=next(p for p in L.read('publication_reviews') if p['registry_key']==k)
 p.update(review_stage='design_sources_reviewed',relevance='design_bearing',design_contributions=['reused_design','modified_design'],catalog_eligibility='unresolved',access='publisher_articleHTML_available; video_and_parent_sources_pending',rationale=note,reviewer='Codex targeted publisherprotocol/design review',run_id=rid,date=L.DATE,unresolved_questions=qs)
 if ev not in p['evidence']:p['evidence'].append(ev)
 p['date_evidence'].update(date='2019-01-19',primary_verified=True,source=ev,meaning='Publisherpage dateJanuary19,2019')
 L.upsert('publication_reviews',p,'Record explicit2018source reuse and distinguish wireframe from latticeobjects')
 for did,names,scope,lattice in [('RDE0070',['NRsquare-lattice nanorod','NBhoneycomb nanobottle','NRHRP/PS2.M functional variants'],'unresolved','SquareNR and honeycombNB explicitResults; full geometry/source audit pending'),('RDE0071',['DAEDALUSwireframeWN coating-test object'],'excluded','Wireframe explicitResults; broad origami relevance but excluded by narrow nonwireframe scope')]:
  old=next((d for d in L.read('design_evidence') if d['design_id']==did),None);assert old is None or k in old['publication_keys']
  L.upsert('design_evidence',dict(design_id=did,publication_keys=[k,parent],named_objects=names,identity_status='Provisional sourcefamily linked by explicitprotocol adaptation; exactsequenceidentity pending',lattice_decision=lattice,catalog_eligibility=scope,core_variant_composition=note,relationships=[dict(relation='reused_design_from',publication_key=parent,qualification='Introduction andFigures1-4 explicitlyattribute priorworkref16; exactbase-level identitypending',evidence=ev)],variant_links=[],source_completeness='not_verified',source_files=[ev],evidence=[ev],outstanding_checks=qs,review_stage='source_reviewed',review_run=rid,run_id=rid,date=L.DATE,legacy_record={}), 'Preserve protocol/source family and explicit wireframe scope')
 refs=[html.unescape(t) for t in re.findall(r'<li aria-label="([^"]+)"',path.read_text())];assert len(refs)==28
 edges=L.read('discovery_edges');known={x['edge_id']:x for x in edges}
 for n,c in enumerate(refs,1):
  row=dict(edge_id='B0016:jove58771:ref'+str(n),source_key=k,target_key=parent if n==16 else 'citation:jove58771:'+str(n),relation='cites',citation=c,evidence_url=ev['url'],local_file=ev['local_file'],sha256=ev['sha256'],locator='Publisher reference'+str(n),reconciliation_state='parent_identity_supported' if n==16 else 'pending_identity_date_scope_reconciliation',run_id=rid,date=L.DATE,revision_history=[])
  if row['edge_id'] in known:assert known[row['edge_id']]==row
  else:edges.append(row)
 L.save('discovery_edges',edges)
 b=next(b for b in L.read('batches') if b['batch_id']==rid);action='Processed23of25inputs=21substantive+2metadataonly. JoVEcoating protocol NR/NB/WN sourcegroupsRDE0070/71, explicitAhmadi2018reuse,28referencesretained. WNnarrowcatalogexcluded; NR/NBsourcespending.'
 if action not in b['completed_actions']:b['completed_actions'].append(action)
 b.update(after_counts=L.counts(),validation=[L.validate()],next_queue=['Remaining2firstpassinputs:10.4049/jimmunol.202.supp.130.13 and10.5539/jmsr.v8n4p14.','Ahmadi2018parent sourceacquisition/review; avoid mergingwithPonnuswamyfamily.','Talks/news metadata-only gaps remainopen; author/citation discoverycontinues.']);L.upsert('batches',b,'Save23of25andexplicitparent scope');print(L.validate())
if __name__=='__main__':main()
