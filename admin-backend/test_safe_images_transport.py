"""No network or business writes: verify the explicitly pinned migration tunnel."""
import io
import os
import unittest
from unittest.mock import Mock, patch
from urllib.parse import urlsplit
from PIL import Image
import safe_images

if os.environ.get('PGHOST') != '127.0.0.1' or not os.environ.get('PGDATABASE', '').endswith('_test'):
    raise RuntimeError('Security regression requires an explicit loopback *_test database')


class ImageTransportTest(unittest.TestCase):
    def test_proxy_connects_to_validated_ip_and_tls_checks_original_hostname(self):
        sock = Mock()
        with patch('safe_images.http.client.HTTPConnection') as proxy, patch('safe_images.socket.create_connection') as direct:
            proxy.return_value.sock = sock
            connection = safe_images.PinnedHTTPS('images.fixture.test', '8.8.8.8', 5,
                                                  proxy_url='http://127.0.0.1:8888')
            connection._context = Mock()
            connection.connect()
            proxy.return_value.set_tunnel.assert_called_once_with('8.8.8.8', 443, headers={})
            connection._context.wrap_socket.assert_called_once_with(sock, server_hostname='images.fixture.test')
            direct.assert_not_called()
            proxy.return_value.close.assert_called_once()

    def test_ambient_proxy_does_not_change_runtime_connections(self):
        with patch.dict(os.environ, {'HTTPS_PROXY': 'http://127.0.0.1:8888'}), patch('safe_images.socket.create_connection') as direct:
            connection = safe_images.PinnedHTTPS('images.fixture.test', '8.8.8.8', 5)
            connection._context = Mock()
            connection.connect()
            direct.assert_called_once_with(('8.8.8.8', 443), 5)

    def test_invalid_proxy_rejected_without_connection(self):
        for url in ('file:///tmp/proxy', 'https://proxy.fixture.test', 'http://proxy.fixture.test/path', 'http://proxy.fixture.test/?key=value'):
            with self.subTest(url=url), patch('safe_images.socket.create_connection') as direct:
                connection = safe_images.PinnedHTTPS('images.fixture.test', '8.8.8.8', 5, proxy_url=url)
                with self.assertRaises(ValueError):
                    connection.connect()
                direct.assert_not_called()

    def test_timeout_limits_are_bounded_before_dns(self):
        for total, per_request in ((0, 8), (91, 8), (25, 0), (25, 26), (60, 31)):
            with self.subTest(total=total, per_request=per_request), patch('safe_images.validate_url') as validate:
                with self.assertRaises(ValueError):
                    safe_images.fetch_file('https://images.fixture.test/a.png', timeout_seconds=total,
                                          request_timeout_seconds=per_request)
                validate.assert_not_called()

    def test_runtime_download_defaults_unchanged(self):
        out = io.BytesIO()
        Image.new('RGB', (4, 4)).save(out, format='PNG')
        response = Mock(status=200)
        response.getheader.side_effect = lambda name, default=None: {'Content-Type': 'image/png'}.get(name, default)
        response.read.side_effect = [out.getvalue(), b'']
        url = 'https://images.fixture.test/a.png'
        with patch('safe_images.validate_url', return_value=(urlsplit(url), '8.8.8.8')), patch('safe_images.PinnedHTTPS') as factory:
            factory.return_value.getresponse.return_value = response
            self.assertEqual(safe_images.fetch_image(url), out.getvalue())
            args, kwargs = factory.call_args
            self.assertLessEqual(args[2], 8)
            self.assertNotIn('proxy_url', kwargs)
            factory.return_value.close.assert_called_once()

    def test_proxy_redirect_still_rejects_private_or_http_destination(self):
        response = Mock(status=302)
        response.getheader.return_value = 'http://127.0.0.1/private'
        url = 'https://images.fixture.test/a.png'
        with patch.dict(os.environ, {'PUBLIC_IMAGE_ORIGINS': 'https://images.fixture.test'}), \
                patch('safe_images.socket.getaddrinfo', return_value=[(2, 1, 6, '', ('8.8.8.8', 443))]), \
                patch('safe_images.PinnedHTTPS') as factory:
            factory.return_value.getresponse.return_value = response
            with self.assertRaises(ValueError):
                safe_images.fetch_file(url, proxy_url='http://127.0.0.1:8888')
            self.assertEqual(factory.call_count, 1)


if __name__ == '__main__':
    unittest.main()
