import unittest
from acquire_sources import validate_payload
class SourcePayloadTests(unittest.TestCase):
 def test_cookie_challenge_is_not_source(self):
  with self.assertRaises(ValueError):
   validate_payload('pubmed.html',b'<h1>Cookies must be enabled</h1><script>const challengeId = "fixture";</script>')
 def test_challenge_is_not_source(self):
  for data in [b'<title>NC State University Libraries Bot Detection</title>',b'<html>Verifying you are not a bot...</html>']:
   with self.assertRaises(ValueError):validate_payload('history.html',data)
 def test_real_source_and_pdf_check(self):
  validate_payload('history.html',b'<html><h1>Publications</h1></html>')
  validate_payload('si.pdf',b'%PDF-1.7\n')
  with self.assertRaises(ValueError):validate_payload('si.pdf',b'<html>login</html>')
if __name__=='__main__':unittest.main()
