import unittest
from discover_yin_bibliography import parse
class ParserTests(unittest.TestCase):
 def test_duplicate_anchor_and_nested_media(self):
  s='<a name="2020.x"></a>[2] A <b>First title</b> DOI: 10.1234/abc <a href="publications/a.pdf">PDF</a><ul><li><a href="news">News</a></li></ul><a name="2020.x"></a>[1] B <b>Second title</b>'
  r=parse(s);self.assertEqual([x['occurrence'] for x in r],[1,2]);self.assertEqual(r[0]['explicit_doi_candidates'],['10.1234/abc']);self.assertEqual(r[1]['explicit_doi_candidates'],[]);self.assertEqual(r[0]['links'],['https://yin.hms.harvard.edu/publications/a.pdf']);self.assertEqual(r[1]['title'],'Second title');self.assertEqual(parse(s),r)
if __name__=='__main__':unittest.main()
