import ipaddress
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from prepare_proxy_config import parse_ranges, prepare, SOURCES

V4 = '\n'.join('104.16.' + str(i) + '.0/24' for i in range(10)).encode()
V6 = '\n'.join('2606:4700:' + str(i) + '::/48' for i in range(5)).encode()


class ProxyPreparationTest(unittest.TestCase):
    def test_verified_ranges_and_ops_have_distinct_trust(self):
        with TemporaryDirectory() as directory:
            output = Path(directory) / 'new'
            calls = []
            def fetch(url):
                calls.append(url)
                return V4 if url == SOURCES[4] else V6
            self.assertEqual(prepare(output, ['127.0.0.1/32', '192.0.2.8/32'], fetch), 15)
            trusted = (output / 'cloudflare-trusted-peers.conf').read_text()
            allowed = (output / 'cloudflare-origin-peers.conf').read_text()
            self.assertNotIn('192.0.2.8', trusted)
            self.assertIn('192.0.2.8/32 1;', allowed)
            self.assertEqual(calls, list(SOURCES.values()))
            self.assertFalse(json.loads((output / 'manifest.json').read_text())['installed'])
            with self.assertRaises(ValueError):
                prepare(output, ['127.0.0.1/32'], fetch)

    def test_invalid_or_partial_responses_never_create_config(self):
        for raw, version in [(b'', 4), (b'<html>error</html>', 4), (b'0.0.0.0/0\n' * 10, 4), (b'127.0.0.0/8\n' * 10, 4), (V4, 6), (b'x' * 65537, 4), (V4 + b'\n104.16.0.0/24', 4)]:
            with self.subTest(version=version), self.assertRaises((ValueError, UnicodeError)):
                parse_ranges(raw, version)
        with TemporaryDirectory() as directory:
            output = Path(directory) / 'new'
            with self.assertRaises(ValueError):
                prepare(output, ['127.0.0.1/32'], lambda url: V4 if url == SOURCES[4] else b'bad')
            self.assertFalse(output.exists())

    def test_broad_or_missing_ops_admission_is_rejected(self):
        for ops in [[], ['0.0.0.0/0'], ['::/0'], ['10.0.0.0/8']]:
            with self.assertRaises(ValueError):
                prepare('unused-fixture-path', ops, lambda url: self.fail('Invalid ops must fail before network access'))

    def test_phase1_has_no_login_throttle_or_private_upload_replacement(self):
        root = Path(__file__).parent
        http = (root / 'nginx-phase1-http.conf').read_text()
        site = (root / 'nginx-phase1-site.conf').read_text()
        routing = (root / 'nginx-phase1-routing.conf.example').read_text()
        self.assertNotIn('zone=gingtto_login', site + http)
        self.assertNotIn('location /uploads/', site)
        self.assertNotIn('gingtto-security-images.conf', routing)
        self.assertIn('geo $realip_remote_addr', http)
        self.assertIn('gingtto_origin_peer_allowed = 0', routing)
        self.assertNotIn('$proxy_add_x_forwarded_for', site)
        self.assertIn('location /api/', http)
        self.assertIn('return 426', http)


if __name__ == '__main__':
    unittest.main()
