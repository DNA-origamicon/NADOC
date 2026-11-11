import unittest
from discover_dietz_bibliography import entries
from discover_positioner_references import References
class BibliographyParsing(unittest.TestCase):
 def test_punctuated_springer_reference_counter(self):
  p=References();p.feed('<li class="c-article-references__item" data-counter="73."><p id="ref-CR73">Last citation</p></li>')
  self.assertEqual(p.rows[0]['number'],73)
 def test_repeated_label_not_deduplicated(self):
  rows,_=entries('<h3>2025</h3><p>(100) First authors</p><p>First title</p><h3>2024</h3><p>(100) Other authors</p><p>Other title</p>')
  self.assertEqual(len(rows),2);self.assertEqual([r['stated_year_heading'] for r in rows],[2025,2024])
 def test_isbn_year_is_not_numbered_article(self):
  rows,other=entries('<p>(1) Article</p><h2>Books, theses</h2><p>Chapter</p><p>(2006), ISBN 0-7503-1023-5</p>')
  self.assertEqual(len(rows),1);self.assertEqual(len(other),2)
 def test_reference_text_and_explicit_identifier(self):
  p=References();p.feed('<li>Menu</li><li class="c-article-references__item" data-counter="1"><p id="ref-CR1">A. Author. <i>A title</i> (2010).</p><p><a data-doi="10.1234/ABC">Article</a></p></li>')
  self.assertEqual(p.rows,[{'number':1,'dois':['10.1234/abc'],'text':'A. Author. A title (2010).'}])
if __name__=='__main__':unittest.main()
