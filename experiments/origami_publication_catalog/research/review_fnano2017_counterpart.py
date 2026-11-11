"""Inspect retained caliper SI and preserve tentative conference identity."""
import ledger as L
from review_batch_0001 import evidence

def main():
 doi='10.1021/acsnano.6b03218';p=next(r for r in L.read('publication_reviews') if r['registry_key']==doi)
 ev=evidence(L.ROOT/'assets/sources/acs-expansion-20261104/5466962-nn6b03218_si_001.pdf','https://ndownloader.figshare.com/files/5466962','PDF pp.1,3,5,19–20,23,27–28: authors, TEM, diagram caption, folding screen and separate tables; printed page labels differ from PDF numbering')
 if p['run_id']=='bootstrap-20261105':
  p.update(review_stage='design_sources_reviewed',relevance='design_bearing',design_contributions=['modified_design','reused_design'],catalog_eligibility='unresolved',evidence=[ev],rationale='TEM documents nanocalipers with integrated nucleosomes. SI separately identifies the caliper staple list, nucleosomal DNA variants6L/26L/51L/75L and variants with Gal4 sites. FigS16 names a caDNAno diagram and says the native file is available upon request; no native-file access or complete sequence mapping is certified.',unresolved_questions=['Inspect main design methods and original caliper reference; verify lattice and source diagram at base-register resolution.','Reconcile asterisk-marked staple modifications and TableS2 nucleosomal variants; exact core/attachment composition remains unverified.','Native caDNAno source described as available on request; search public repositories, do not contact authors without authorization.'],access='partial',reviewer='Codex primary SI section inspection',run_id='fnano2017-counterpart',date=L.DATE)
  L.upsert('publication_reviews',p,'Inspect experimental nanocaliper SI; retain original-template and source gaps')
 c=next(r for r in L.read('publication_reviews') if r.get('run_id')=='fnano-2017' and r['authors'][0]=='J.V. Le')
 c['authors']=['J.V. Le','Yi Luo','Michael Darcy','Michael Poirier','Carlos Castro'];c['full_author_list_transcribed']=True
 L.upsert('publication_reviews',c,'Transcribe full program-listed author group for selected caliper lead')
 L.upsert('discovery_edges',dict(edge_id='possible_counterpart:'+c['registry_key']+':'+doi,source_key=c['registry_key'],target_key=doi,relation='possible_journal_counterpart',evidence_url=ev['url'],local_file=ev['local_file'],sha256=ev['sha256'],locator='SI title/authors p1 and experimental caliper sections; conference p1',reconciliation_state='matching_title_author_group_and_experimental_topic; abstract_confirmation_pending',run_id='fnano2017-counterpart',date=L.DATE),'Keep likely counterpart distinct until conference scope is confirmed')
 b=next(b for b in L.read('batches') if b['batch_id']=='DISC0004')
 if doi not in b['input_keys']:b['input_keys'].append(doi)
 action='Inspected nanocaliper journal SI, transcribed full conference author group and saved tentative counterpart relationship.'
 if action not in b['completed_actions']:b['completed_actions'].append(action)
 b.update(after_counts=L.counts(),validation=[L.validate()],unresolved_keys=b['input_keys'])
 L.upsert('batches',b,'Save substantive primary-source follow-up within ongoing conference batch')
 print(L.validate())
if __name__=='__main__':main()
