import unittest
from discover_shih_bibliography import Bibliography
class ParserTests(unittest.TestCase):
 def test_old_citations_under_new_heading_and_duplicate_links(self):
  p=Bibliography();p.feed('<p>menu</p><h1>PUBLICATIONS</h1><p>2004</p><p>Author. Old study. 1994. <a href="http://doi.org/10.1/ABC">DOI</a><a href="https://x/_files/a.zip?dn=a.zip">ZIP</a><a href="https://x/_files/a.zip?dn=a.zip">ZIP</a></p><h2>FUNDING</h2><p>ignore1990</p>')
  self.assertEqual(len(p.rows),1);r=p.rows[0]
  self.assertEqual(r['heading_year'],2004);self.assertEqual(r['citation_years'],[1994]);self.assertEqual(r['doi_links'],['10.1/abc']);self.assertEqual(r['source_links'],['https://x/_files/a.zip'])
if __name__=='__main__':unittest.main()
