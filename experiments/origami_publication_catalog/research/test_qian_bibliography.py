import unittest
from discover_qian_bibliography import parse_page


class BibliographyTests(unittest.TestCase):
    def test_sections_versions_and_private_links(self):
        rows = parse_page('''<h4>Experimental work</h4>
        <p>[1] Example (2011). <a href="paper.pdf">PDF</a>
        <a href="paper?token=private">share</a></p>
        <p>News commentary (2012)</p><h4>Theoretical work</h4>
        <p>[1] Journal (2011), conference (2009).
        <a href="/stoken/private">share</a></p>''')
        self.assertEqual(len(rows), 2)
        self.assertNotEqual(rows[0]['section'], rows[1]['section'])
        self.assertEqual(rows[1]['stated_years'], [2011, 2009])
        self.assertEqual(rows[0]['source_links'], ['https://www.qianlab.caltech.edu/paper.pdf'])
        self.assertEqual(rows[1]['source_links'], [])


if __name__ == '__main__':
    unittest.main()
