"""Review source contents without misclassifying protein adapter oligos as staples."""
import hashlib,json
import ledger as L
from review_batch_0001 import evidence

def main():
 key='10.1021/acsnano.6b05938';base=L.ROOT/'assets/research-20261105';before=L.counts();ev=[]
 for row in json.loads((base/'precise-coating-figshare-search.json').read_text()):
  meta=json.loads((base/f"precise-coating-figshare-{row['id']}.json").read_text());assert meta['resource_doi']==key
  for f in meta['files']:
   path=base/('precise-coating-'+f['name']);assert path.stat().st_size==f['size'];assert hashlib.md5(path.read_bytes()).hexdigest()==f['computed_md5']
   ev.append(evidence(path,f['download_url'],'SI PDF all3pages extracted text read; TableS1 protein-encoding adapter oligos, FigureS5 origami digestion assay.' if path.suffix=='.pdf' else 'Supplementary fluorescence movie acquired and provider checksum verified; video contents not yet reviewed.'))
 p=next(p for p in L.read('publication_reviews') if p['registry_key']==key)
 qs=['Read acquired main or obtain author copy from NUS; identify origami template and parent references.','Review three fluorescence videos separately; do not infer origami identity from generic DNA movie labels.','Verify primary first-online date2016-12-12 versus2017issue and retain separate date meanings.','Continue full backlog rotation and author histories; exact origami source completeness remains unresolved.']
 p.update(review_stage='design_sources_reviewed',relevance='design_bearing',design_contributions=['uncertain'],catalog_eligibility='unresolved',access='SI_PDF_and_three_movies_available; main_attempt_recorded',evidence=p['evidence']+ev,rationale='SI FigureS5 explicitly reports enzymatic digestion of origami DNA nanostructures alone and protein-coated, alongside plasmid controls. TableS1 contains four oligos for constructing an adapter encoding the Sso7d protein binding domain: these are not origami staples. FiguresS1/S3 concern plasmid DNA andS4 M13ssDNA; their presence does not identify a folded origami geometry. No origami staple table/native routing supplied in this3pageSI. Three videos acquired but not reviewed. Main/template/parent verification remains pending.',reviewer='Codex SI text inspection',run_id='author-priority-thomas-labean',date=L.DATE,unresolved_questions=qs)
 L.upsert('publication_reviews',p,'Confirm experimental origami from SI; distinguish protein cloning oligos from structure sources')
 L.upsert('batches',dict(batch_id='AUTHOR0031',date=L.DATE,status='completed',input_keys=[key,'10.1021/acsnano.6b07291'],selection='Related LaBean low-keyword source review and exact access handoff',before_counts=before,after_counts=L.counts(),completed_actions=['Verified all four public publisher supplement files by providerMD5 and size.','Read3pageSI; confirmed origami assay, ruled out protein adapter table as origami staple evidence.','Created ACCESS-a556b23d8f for Estrich dissertation after direct/API and independent web access encountered bot verification; continued independent research.'],validation=[L.validate()],unresolved_keys=[key,'10.1021/acsnano.6b07291'],next_queue=qs+['Collect ACCESS-a556b23d8f only when user supplies downloaded file; no credentials or browser state.']),'Save SI evidence and access request with independent next work')
 print(L.validate())
if __name__=='__main__':main()
