import unittest
from discover_bathe_bibliography import parse_lab,parse_cv
class BibliographyTests(unittest.TestCase):
 def test_cv_headers_and_missing_number_dot(self):
  s='Publications\n2 Author A. (2019). Title.\nMark Bathe MIT\nProfessor Bio\n77 Massachusetts Ave\nBuilding16\nCambridge MA\n1. Author B. (1999). Title.\nPatents\n1. Other'
  rows=parse_cv(s);self.assertEqual([r['number'] for r in rows],[2,1]);self.assertNotIn('Massachusetts',rows[0]['citation'])
 def test_public_identifier_query_and_page_not_year(self):
  s='<h2>2</h2><div data-widget_type="text-editor.default"><div class="elementor-widget-container">A. Title. 2019;13:2083.</div></div><a href="https://journals.plos.org/ploscompbiol/article?id=10.1371/journal.pcbi.1&amp;token=private">article</a><h2>1</h2><div data-widget_type="text-editor.default"><div class="elementor-widget-container">B. Title. 1999;3:1.</div></div>'
  r=parse_lab(s)[0];self.assertEqual(r['stated_years'],[2019]);self.assertIn('id=10.1371',r['links'][0]);self.assertNotIn('token',r['links'][0]);self.assertEqual(r['doi_links'],['10.1371/journal.pcbi.1'])
if __name__=='__main__':unittest.main()
