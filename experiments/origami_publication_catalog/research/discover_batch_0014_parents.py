"""Preserve two explicitly cited method sources; no equivalence inferred."""
import json
import ledger as L
from review_batch_0001 import evidence

def main():
 source='10.1021/acsami.8b12374'
 ev=evidence(L.ROOT/'assets/sources/acs-expansion-20261104/13444007-am8b12374_si_001.pdf','https://ndownloader.figshare.com/files/13444007','Experimental methods S3–4 and References1–2 printedS24')
 for target,loc in [('10.1021/ja300897h','Ref1: Fu2012 JACS134:5516–5519; enzyme conjugation method'),('10.1126/science.1150082','Ref2: Ke2008 Science319:180–183; rectangular origami preparation')]:
  L.upsert('discovery_edges',dict(edge_id='B0014:method:'+source+':'+target,source_key=source,target_key=target,relation='cites',evidence_url=ev['url'],local_file=ev['local_file'],sha256=ev['sha256'],locator=loc,reconciliation_state='bibliographic_match_design_lineage_pending',run_id='B0014',date=L.DATE),'Match explicit bibliography to existing registry; exact design lineage remains pending')
 print(json.dumps(L.validate()))

if __name__=='__main__':main()
