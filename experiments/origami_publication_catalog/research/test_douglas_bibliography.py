"""Duplicate anchors and keyword-free entries must survive bibliography ingestion."""
import tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import ledger as L
import discover_douglas_bibliography as D
class BibliographyTest(unittest.TestCase):
 def test_duplicate_anchor_retention_and_resume(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);assets=root/'assets/research-20261105';assets.mkdir(parents=True)
   (assets/'douglas-lab-publications.html').write_text('<p id="same">First paper (2026)<a href="https://doi.org/10.1/a">publisher</a></p><p id="same">Second paper (2024)</p><p id="old">Unrelated low-keyword record (2018)</p>')
   rd=L.read;up=L.upsert
   with patch.object(L,'ROOT',root),patch.object(L,'read',side_effect=lambda n,directory=root:rd(n,directory)),patch.object(L,'upsert',side_effect=lambda n,r,why:up(n,r,why,root)),patch.object(L,'validate',return_value={'fixture':'not_full_campaign_validation'}):
    D.main();rows=rd('discovery_edges',root)
    self.assertEqual(len(rows),3);self.assertEqual(len({r['edge_id'] for r in rows}),3)
    self.assertEqual(sorted(r['target_metadata']['stated_year'] for r in rows),[2018,2024,2026])
    before=(root/'discovery_edges.jsonl').read_bytes();D.main();self.assertEqual(before,(root/'discovery_edges.jsonl').read_bytes())
if __name__=='__main__':unittest.main()
