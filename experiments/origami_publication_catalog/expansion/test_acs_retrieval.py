"""Network-free checks of bounded retries and server cooldown handling."""
import io
import unittest
from email.message import Message
from unittest.mock import patch
import urllib.error
import fetch_acs_repository as fetch

URL = 'https://api.figshare.com/v2/articles/2816488'


def failure(code, retry_after=None):
    headers = Message()
    headers['Content-Type'] = 'text/html'
    if retry_after:
        headers['Retry-After'] = retry_after
    return urllib.error.HTTPError(URL, code, 'error', headers, io.BytesIO(b'body must not enter diagnostic'))


class RetrievalTests(unittest.TestCase):
    def setUp(self):
        fetch._last_request = 0
        self.sleep = patch.object(fetch.time, 'sleep').start()
        patch.object(fetch.time, 'monotonic', return_value=100).start()
        self.addCleanup(patch.stopall)

    def test_temporary_forbidden_recovers_without_authentication(self):
        with patch.object(fetch.urllib.request, 'urlopen', side_effect=[failure(403), io.BytesIO(b'[]')]) as opener:
            self.assertEqual(fetch.get(URL), b'[]')
        self.assertEqual(opener.call_count, 2)
        self.sleep.assert_any_call(30)
        for call in opener.call_args_list:
            self.assertFalse(call.args[0].has_header('Authorization'))
            self.assertFalse(call.args[0].has_header('Cookie'))

    def test_repeated_forbidden_is_bounded_and_safe(self):
        with patch.object(fetch.urllib.request, 'urlopen', side_effect=[failure(403) for _ in range(3)]) as opener:
            with self.assertRaises(fetch.RetrievalError) as caught:
                fetch.get(URL)
        self.assertEqual(opener.call_count, 3)
        self.assertEqual(caught.exception.diagnostic['http_status'], 403)
        self.assertNotIn('body', str(caught.exception.diagnostic))

    def test_unauthorized_does_not_retry(self):
        with patch.object(fetch.urllib.request, 'urlopen', side_effect=failure(401)) as opener:
            with self.assertRaises(fetch.RetrievalError) as caught:
                fetch.get(URL)
        self.assertEqual(opener.call_count, 1)
        self.assertEqual(caught.exception.diagnostic['classification'], 'authentication_required')

    def test_long_server_cooldown_defers_instead_of_shortening(self):
        with patch.object(fetch.urllib.request, 'urlopen', side_effect=failure(429, '120')) as opener:
            with self.assertRaises(fetch.RetrievalError):
                fetch.get(URL)
        self.assertEqual(opener.call_count, 1)

    def test_server_cooldown_respected_within_bound(self):
        with patch.object(fetch.urllib.request, 'urlopen', side_effect=[failure(429, '45'), io.BytesIO(b'ok')]):
            self.assertEqual(fetch.get(URL), b'ok')
        self.sleep.assert_any_call(45)

    def test_file_size_cap_is_enforced(self):
        with patch.object(fetch.urllib.request, 'urlopen', return_value=io.BytesIO(b'12345')):
            with self.assertRaisesRegex(ValueError, 'size bound'):
                fetch.get(URL, limit=4)


if __name__ == '__main__':
    unittest.main()
