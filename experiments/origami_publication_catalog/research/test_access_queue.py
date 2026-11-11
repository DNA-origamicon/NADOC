import tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import access_queue as A
class AccessTests(unittest.TestCase):
 def setUp(self):
  self.t=tempfile.TemporaryDirectory();self.addCleanup(self.t.cleanup);self.root=Path(self.t.name)
  for obj,k,v in [(A,'QUEUE',self.root/'q.json'),(A,'PAGE',self.root/'q.html'),(A,'ASSETS',self.root/'assets'),(A.L,'ROOT',self.root)]:
   x=patch.object(obj,k,v);x.start();self.addCleanup(x.stop)
 def req(self):return A.request('10.test/x','https://example.org/paper','Browser challenge',['Publisher403; repository unavailable'])
 def test_request_resume(self):
  a=self.req();self.assertEqual(a,self.req());self.assertEqual(len(A.read()),1)
 def test_challenge_rejected(self):
  r=self.req();p=self.root/'x.pdf';p.write_text('<html>Just a moment</html>')
  with self.assertRaises(ValueError):A.ingest(r['id'],p)
  self.assertEqual(A.read()[0]['status'],'needs_user')
 def test_ingest_resume_conflict_and_integrity(self):
  r=self.req();p=self.root/'x.pdf';p.write_bytes(b'%PDF-1.4\ntest fixture');a=A.ingest(r['id'],p);self.assertEqual(a,A.ingest(r['id'],p));self.assertTrue(p.exists())
  p.write_bytes(b'%PDF-1.4\nother')
  with self.assertRaises(ValueError):A.ingest(r['id'],p)
  self.assertEqual(A.read()[0]['file']['sha256'],a['file']['sha256'])
 def test_private_url_rejected(self):
  for u in ['https://user:pass@example.org/x','https://example.org/x?token=secret','file:///tmp/x']:
   with self.assertRaises(ValueError):A.public_url(u)
 def test_answer_history(self):
  r=A.request('10.test/y','https://example.org/paper','Which version?',['Ambiguity documented'],'question');A.answer(r['id'],'Use accepted manuscript')
  with self.assertRaises(ValueError):A.answer(r['id'],'Overwrite')
if __name__=='__main__':unittest.main()
