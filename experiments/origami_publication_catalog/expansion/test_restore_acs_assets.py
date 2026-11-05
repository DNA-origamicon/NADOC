"""Offline portability checks; no publisher requests or retained corpus changes."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import restore_acs_assets as restore


class RestoreTests(unittest.TestCase):
    def test_restore_and_resume_without_mutating_audit(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data = b'%PDF fixture'
            file = {'status': 'downloaded', 'local_file': 'sources/test.pdf',
                    'url': 'https://example.test/file', 'bytes': len(data),
                    'sha256': hashlib.sha256(data).hexdigest()}
            audit = root / 'acs_acquisition.json'
            audit.write_text(json.dumps({'records': [{'doi': 'test', 'articles': [], 'files': [file]}]}))
            before = audit.read_bytes()
            args = ['restore', '--assets', str(root / 'assets')]
            with patch.object(restore, 'ROOT', root), patch('sys.argv', args):
                self.assertEqual(restore.main(), 1)
                with patch('sys.argv', args + ['--restore']), patch.object(restore, 'get', return_value=data) as get:
                    self.assertEqual(restore.main(), 0)
                    get.assert_called_once()
                with patch.object(restore, 'get', side_effect=AssertionError('Unexpected download')):
                    self.assertEqual(restore.main(), 0)
                self.assertEqual(audit.read_bytes(), before)

    def test_rejects_corrupt_bytes(self):
        with self.assertRaises(ValueError):
            restore.verify(b'changed', {'bytes': 7, 'sha256': '0' * 64})

    def test_rejects_path_escape(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                restore.destination(Path(tmp), '../outside.pdf')

    def test_broken_storage_link_fails_before_network(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'assets').symlink_to(root / 'unmounted', target_is_directory=True)
            with patch('sys.argv', ['restore', '--assets', str(root / 'assets'), '--restore']):
                with self.assertRaisesRegex(SystemExit, 'unavailable'):
                    restore.main()


if __name__ == '__main__':
    unittest.main()
