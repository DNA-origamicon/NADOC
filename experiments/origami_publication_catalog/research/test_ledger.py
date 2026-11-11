"""Small, network-free persistence checks for the research sidecars."""
import json
import hashlib
import acquire_sources
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch, MagicMock
import ledger


class LedgerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_screening_resume_skips_active_discovery_batch(self):
        discovery = {'batch_id': 'DISC0007', 'status': 'in_progress'}
        screening = {'batch_id': 'B0011', 'status': 'in_progress'}
        with patch.object(ledger, 'read', return_value=[discovery, screening]):
            self.assertEqual(ledger.select(), screening)

    def test_discovery_batch_does_not_block_new_screening_selection(self):
        discovery = {'batch_id': 'DISC0007', 'status': 'in_progress', 'input_keys': []}
        article = {'registry_key': '10.test/a', 'doi': '10.test/a', 'registry_id': 'P1',
                   'review_stage': 'unreviewed', 'legacy_record': {'priority': 'discovery_only'},
                   'date_evidence': {'date': '2013-01-01'}}
        (self.root / 'acs_acquisition.json').write_text('{"records": []}')
        records = {'batches': [discovery], 'publication_reviews': [article], 'design_evidence': []}
        with patch.object(ledger, 'ROOT', self.root), patch.object(ledger, 'read', side_effect=lambda name: records[name]), patch.object(ledger, 'counts', return_value={}), patch.object(ledger, 'upsert') as save:
            selected = ledger.select()
        self.assertEqual(selected['batch_id'], 'B0001')
        self.assertEqual(selected['input_keys'], ['10.test/a'])
        save.assert_called_once()

    def test_unicode_separators_remain_inside_json_record(self):
        row = {'run_id': 'q', 'title': 'first\u2028second\u0085third'}
        ledger.save('discovery_runs', [row], self.root)
        self.assertEqual(ledger.read('discovery_runs', self.root), [row])

    def test_acquisition_resume_accepts_equivalent_query_order(self):
        directory = self.root / 'assets/research-20261105'
        directory.mkdir(parents=True)
        (directory / 'source.json').write_bytes(b'{}')
        item = {'url': 'https://example.test/?a=1&b=2', 'status': 'available', 'sha256': hashlib.sha256(b'{}').hexdigest()}
        (directory / 'acquisition.json').write_text(json.dumps({'source.json': item}))
        with patch.object(ledger, 'ROOT', self.root):
            self.assertEqual(acquire_sources.fetch('https://example.test/?b=2&a=1', 'source.json'), item)
            with self.assertRaises(ValueError):
                acquire_sources.fetch('https://example.test/?b=3&a=1', 'source.json')

    def test_resume_is_idempotent(self):
        row = {'run_id': 'query:1', 'cursor': '*', 'revision_history': []}
        ledger.upsert('discovery_runs', row, 'start', self.root)
        before = (self.root / 'discovery_runs.jsonl').read_bytes()
        ledger.upsert('discovery_runs', row, 'resume', self.root)
        self.assertEqual(before, (self.root / 'discovery_runs.jsonl').read_bytes())

    def test_empty_response_is_failed_and_not_resumed(self):
        directory = self.root / 'assets/research-20261105'
        directory.mkdir(parents=True)
        (directory / 'empty.html').write_bytes(b'')
        old = {'url': 'https://example.test/', 'status': 'available', 'sha256': hashlib.sha256(b'').hexdigest()}
        (directory / 'acquisition.json').write_text(json.dumps({'empty.html': old}))
        response = MagicMock()
        response.__enter__.return_value.read.return_value = b''
        with patch.object(ledger, 'ROOT', self.root), patch('acquire_sources.time.sleep'), patch('acquire_sources.urllib.request.urlopen', return_value=response) as request:
            result = acquire_sources.fetch(old['url'], 'empty.html')
        request.assert_called_once()
        self.assertEqual(result['status'], 'failed')
        self.assertIn('Empty response', result['error'])

    def test_revision_preserves_previous_cursor(self):
        ledger.upsert('discovery_runs', {'run_id': 'q', 'cursor': '*'}, 'start', self.root)
        ledger.upsert('discovery_runs', {'run_id': 'q', 'cursor': 'next'}, 'page saved', self.root)
        rows = ledger.read('discovery_runs', self.root)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['revision_history'][0]['superseded']['cursor'], '*')

    def test_html_challenge_is_not_an_acquired_pdf(self):
        response = MagicMock()
        response.__enter__.return_value.read.return_value = b'<html>Checking your browser</html>'
        with patch.object(ledger, 'ROOT', self.root), patch('acquire_sources.time.sleep'), patch('acquire_sources.urllib.request.urlopen', return_value=response):
            result = acquire_sources.fetch('https://example.test/si.pdf', 'si.pdf')
        self.assertEqual(result['status'], 'failed')
        self.assertIn('non-PDF', result['error'])
        self.assertFalse((self.root / 'assets/research-20261105/si.pdf').exists())
        acquire_sources.validate_payload('si.pdf', b'%PDF-1.7\nfixture')

    def test_repeated_update_does_not_add_false_revision(self):
        ledger.upsert('discovery_runs', {'run_id': 'q', 'cursor': '*'}, 'start', self.root)
        ledger.upsert('discovery_runs', {'run_id': 'q', 'cursor': 'next'}, 'advance', self.root)
        before = (self.root / 'discovery_runs.jsonl').read_bytes()
        ledger.upsert('discovery_runs', {'run_id': 'q', 'cursor': 'next'}, 'resume', self.root)
        self.assertEqual(before, (self.root / 'discovery_runs.jsonl').read_bytes())

    def test_duplicate_rejected_before_write(self):
        with self.assertRaises(ValueError):
            ledger.save('discovery_runs', [{'run_id': 'q'}, {'run_id': 'q'}], self.root)
        self.assertFalse((self.root / 'discovery_runs.jsonl').exists())

    def test_failed_replace_preserves_old_output(self):
        path = self.root / 'state'
        ledger.atomic(path, 'old')
        with patch('ledger.os.replace', side_effect=OSError('fixture disk failure')):
            with self.assertRaises(OSError):
                ledger.atomic(path, 'new')
        self.assertEqual(path.read_text(), 'old')
        self.assertEqual(list(self.root.glob('*.tmp')), [])


if __name__ == '__main__':
    unittest.main()
