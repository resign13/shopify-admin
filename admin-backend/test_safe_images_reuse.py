"""No network: pinned keep-alive and deadline security regressions."""
import http.client
import io
import os
import socket
import ssl
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock, patch
from urllib.parse import urlsplit
from PIL import Image
import safe_images


class Response:
    def __init__(self, data, status=200, location=None):
        self.data, self.status, self.location, self.will_close = data, status, location, False
    def getheader(self, name, default=None):
        return {'Content-Type': 'image/png', 'Location': self.location}.get(name, default)
    def read(self, size):
        result, self.data = self.data[:size], self.data[size:]
        return result


class Connection:
    def __init__(self, host, address, timeout, factory):
        self.host, self.address, self.timeout, self.factory = host, address, timeout, factory
        self.sock, self.closed = Mock(), False
    def request(self, *args, **kwargs):
        if self.factory.fail_request:
            error, self.factory.fail_request = self.factory.fail_request, None
            raise error
    def getresponse(self):
        return self.factory.responses.pop(0)
    def close(self):
        self.closed = True
        self.sock = None


class Factory:
    def __init__(self, responses):
        self.responses, self.connections, self.fail_request = responses, [], None
    def __call__(self, host, address, timeout, **kwargs):
        connection = Connection(host, address, timeout, self)
        self.connections.append(connection)
        return connection


class ReuseTest(unittest.TestCase):
    def setUp(self):
        out = io.BytesIO()
        Image.new('RGB', (2, 2), 'blue').save(out, format='PNG')
        self.raw = out.getvalue()
        self.urls = ['https://images.fixture.test/a.png', 'https://images.fixture.test/b.png']
        self.env = patch.dict(os.environ, {'PUBLIC_IMAGE_ORIGINS': 'https://images.fixture.test'})
        self.env.start()
        self.addCleanup(self.env.stop)

    @staticmethod
    def address(ip):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, '', (ip, 443))]

    def test_same_host_reuses_only_after_full_read_and_checks_dns_each_time(self):
        factory = Factory([Response(self.raw), Response(self.raw)])
        with patch('safe_images.PinnedHTTPS', factory), \
             patch('safe_images.socket.getaddrinfo', return_value=self.address('8.8.8.8')) as dns:
            with safe_images.ImageTransport() as transport:
                for url in self.urls:
                    self.assertEqual(safe_images.fetch_file(url, client=transport), self.raw)
                self.assertEqual(len(factory.connections), 1)
                self.assertFalse(factory.connections[0].closed)
                self.assertEqual(dns.call_count, 2)
            self.assertTrue(factory.connections[0].closed)

    def test_changed_address_closes_old_connection(self):
        factory = Factory([Response(self.raw), Response(self.raw)])
        with patch('safe_images.PinnedHTTPS', factory), \
             patch('safe_images.socket.getaddrinfo', side_effect=[self.address('8.8.8.8'), self.address('1.1.1.1')]):
            with safe_images.ImageTransport() as transport:
                for url in self.urls: safe_images.fetch_file(url, client=transport)
                self.assertEqual(len(factory.connections), 2)
                self.assertTrue(factory.connections[0].closed)

    def test_redirect_closes_connection_and_rechecks_every_dns_address(self):
        factory = Factory([Response(b'', 302, self.urls[1])])
        mixed = self.address('8.8.8.8') + self.address('127.0.0.1')
        with patch('safe_images.PinnedHTTPS', factory), \
             patch('safe_images.socket.getaddrinfo', side_effect=[self.address('8.8.8.8'), mixed]):
            with safe_images.ImageTransport() as transport:
                with self.assertRaises(ValueError): safe_images.fetch_file(self.urls[0], client=transport)
                self.assertTrue(factory.connections[0].closed)
                self.assertEqual(len(factory.connections), 1)

    def test_stale_reused_connection_gets_one_retry_with_original_deadline(self):
        factory = Factory([Response(self.raw), Response(self.raw)])
        clock = Mock(return_value=0.0)
        with patch('safe_images.PinnedHTTPS', factory), \
             patch('safe_images.socket.getaddrinfo', return_value=self.address('8.8.8.8')) as dns, \
             patch('safe_images.time.monotonic', clock):
            with safe_images.ImageTransport() as transport:
                safe_images.fetch_file(self.urls[0], client=transport)
                def stale(*args, **kwargs):
                    factory.connections[0].request = Mock()
                    clock.return_value = 24.8
                    raise http.client.RemoteDisconnected()
                factory.connections[0].request = stale
                safe_images.fetch_file(self.urls[1], client=transport)
                self.assertEqual(len(factory.connections), 2)
                self.assertTrue(factory.connections[0].closed)
                self.assertLessEqual(factory.connections[1].timeout, 0.21)
                self.assertEqual(dns.call_count, 3)

    def test_stale_connection_retries_at_most_once(self):
        factory = Factory([Response(self.raw)])
        with patch('safe_images.PinnedHTTPS', factory), \
             patch('safe_images.socket.getaddrinfo', return_value=self.address('8.8.8.8')):
            with safe_images.ImageTransport() as transport:
                safe_images.fetch_file(self.urls[0], client=transport)
                def fail_and_arm_next(*args, **kwargs):
                    factory.fail_request = OSError('replacement failed')
                    raise http.client.RemoteDisconnected()
                factory.connections[0].request = fail_and_arm_next
                with self.assertRaises(OSError): safe_images.fetch_file(self.urls[1], client=transport)
                self.assertEqual(len(factory.connections), 2)
                self.assertTrue(all(connection.closed for connection in factory.connections))

    def test_stale_connection_does_not_retry_after_total_deadline(self):
        factory = Factory([Response(self.raw)])
        clock = Mock(return_value=0.0)
        with patch('safe_images.PinnedHTTPS', factory), \
             patch('safe_images.socket.getaddrinfo', return_value=self.address('8.8.8.8')), \
             patch('safe_images.time.monotonic', clock):
            with safe_images.ImageTransport() as transport:
                safe_images.fetch_file(self.urls[0], client=transport)
                def stale(*args, **kwargs):
                    clock.return_value = 25.1
                    raise http.client.RemoteDisconnected()
                factory.connections[0].request = stale
                with self.assertRaises(http.client.RemoteDisconnected):
                    safe_images.fetch_file(self.urls[1], client=transport)
                self.assertEqual(len(factory.connections), 1)
                self.assertTrue(factory.connections[0].closed)

    def test_ssl_failure_never_retries_reused_connection(self):
        factory = Factory([Response(self.raw)])
        with patch('safe_images.PinnedHTTPS', factory), \
             patch('safe_images.socket.getaddrinfo', return_value=self.address('8.8.8.8')):
            with safe_images.ImageTransport() as transport:
                safe_images.fetch_file(self.urls[0], client=transport)
                factory.fail_request = ssl.SSLError('certificate')
                with self.assertRaises(ssl.SSLError): safe_images.fetch_file(self.urls[1], client=transport)
                self.assertTrue(factory.connections[0].closed)
                self.assertEqual(len(factory.connections), 1)

    def test_fresh_timeout_retries_once_with_remaining_deadline_and_new_dns_pin(self):
        factory = Factory([Response(self.raw)])
        clock = Mock(return_value=0.0)
        def connect(*args, **kwargs):
            connection = factory(*args, **kwargs)
            if len(factory.connections) == 1:
                def timeout(*args, **kwargs):
                    clock.return_value = 24.8
                    raise TimeoutError('idle timeout')
                connection.request = timeout
            return connection
        with patch('safe_images.PinnedHTTPS', side_effect=connect), \
             patch('safe_images.socket.getaddrinfo', side_effect=[self.address('8.8.8.8'), self.address('1.1.1.1')]) as dns, \
             patch('safe_images.time.monotonic', clock):
            self.assertEqual(safe_images.fetch_file(self.urls[0]), self.raw)
        self.assertEqual(len(factory.connections), 2)
        self.assertEqual(factory.connections[1].address, '1.1.1.1')
        self.assertLessEqual(factory.connections[1].timeout, 0.21)
        self.assertEqual(dns.call_count, 2)
        self.assertTrue(all(connection.closed for connection in factory.connections))

    def test_fresh_timeout_does_not_retry_after_total_deadline(self):
        factory = Factory([])
        clock = Mock(return_value=0.0)
        def connect(*args, **kwargs):
            connection = factory(*args, **kwargs)
            def timeout(*args, **kwargs):
                clock.return_value = 25.1
                raise TimeoutError('idle timeout')
            connection.request = timeout
            return connection
        with patch('safe_images.PinnedHTTPS', side_effect=connect), \
             patch('safe_images.socket.getaddrinfo', return_value=self.address('8.8.8.8')) as dns, \
             patch('safe_images.time.monotonic', clock):
            with self.assertRaises(TimeoutError):
                safe_images.fetch_file(self.urls[0])
        self.assertEqual(len(factory.connections), 1)
        self.assertEqual(dns.call_count, 1)
        self.assertTrue(factory.connections[0].closed)

    def test_timeout_retry_budget_is_shared_across_redirects(self):
        factory = Factory([Response(b'', 302, self.urls[1])])
        def connect(*args, **kwargs):
            connection = factory(*args, **kwargs)
            if len(factory.connections) in (1, 3):
                connection.request = Mock(side_effect=TimeoutError('idle timeout'))
            return connection
        with patch('safe_images.PinnedHTTPS', side_effect=connect), \
             patch('safe_images.socket.getaddrinfo', return_value=self.address('8.8.8.8')) as dns:
            with self.assertRaises(TimeoutError):
                safe_images.fetch_file(self.urls[0])
        self.assertEqual(len(factory.connections), 3)
        self.assertEqual(dns.call_count, 3)
        self.assertTrue(all(connection.closed for connection in factory.connections))

    def test_fresh_certificate_error_is_not_retried(self):
        factory = Factory([])
        factory.fail_request = ssl.SSLCertVerificationError('certificate')
        with patch('safe_images.PinnedHTTPS', factory), \
             patch('safe_images.socket.getaddrinfo', return_value=self.address('8.8.8.8')) as dns:
            with self.assertRaises(ssl.SSLCertVerificationError):
                safe_images.fetch_file(self.urls[0])
        self.assertEqual(len(factory.connections), 1)
        self.assertEqual(dns.call_count, 1)
        self.assertTrue(factory.connections[0].closed)

    def test_permission_failure_on_reused_connection_is_not_retried(self):
        factory = Factory([Response(self.raw)])
        with patch('safe_images.PinnedHTTPS', factory), \
             patch('safe_images.socket.getaddrinfo', return_value=self.address('8.8.8.8')):
            with safe_images.ImageTransport() as transport:
                safe_images.fetch_file(self.urls[0], client=transport)
                factory.fail_request = PermissionError('permission denied')
                with self.assertRaises(PermissionError):
                    safe_images.fetch_file(self.urls[1], client=transport)
        self.assertEqual(len(factory.connections), 1)
        self.assertTrue(factory.connections[0].closed)

    def test_http_denial_not_found_and_invalid_image_are_not_retried(self):
        for response in (Response(b'', 403), Response(b'', 404), Response(b'invalid image')):
            with self.subTest(status=response.status):
                factory = Factory([response])
                with patch('safe_images.PinnedHTTPS', factory), \
                     patch('safe_images.socket.getaddrinfo', return_value=self.address('8.8.8.8')) as dns:
                    with self.assertRaises((ValueError, OSError)):
                        safe_images.fetch_file(self.urls[0])
                self.assertEqual(len(factory.connections), 1)
                self.assertEqual(dns.call_count, 1)
                self.assertTrue(factory.connections[0].closed)

    def test_fresh_connection_failure_is_closed_without_retry(self):
        factory = Factory([])
        factory.fail_request = OSError('disconnected')
        with patch('safe_images.PinnedHTTPS', factory), \
             patch('safe_images.socket.getaddrinfo', return_value=self.address('8.8.8.8')):
            with safe_images.ImageTransport() as transport:
                with self.assertRaises(OSError): safe_images.fetch_file(self.urls[0], client=transport)
                self.assertEqual(len(factory.connections), 1)
                self.assertTrue(factory.connections[0].closed)

    def test_dns_rejection_also_closes_idle_connection(self):
        factory = Factory([Response(self.raw)])
        with patch('safe_images.PinnedHTTPS', factory), \
             patch('safe_images.socket.getaddrinfo', side_effect=[self.address('8.8.8.8'), self.address('127.0.0.1')]):
            with safe_images.ImageTransport() as transport:
                safe_images.fetch_file(self.urls[0], client=transport)
                with self.assertRaises(ValueError): safe_images.fetch_file(self.urls[1], client=transport)
                self.assertTrue(factory.connections[0].closed)

    def test_workers_do_not_share_connections(self):
        factory = Factory([Response(self.raw), Response(self.raw)])
        barrier = threading.Barrier(2)
        with patch('safe_images.PinnedHTTPS', factory), \
             patch('safe_images.socket.getaddrinfo', return_value=self.address('8.8.8.8')):
            with safe_images.ImageTransport() as transport, ThreadPoolExecutor(max_workers=2) as pool:
                def fetch(url):
                    barrier.wait(5)
                    return safe_images.fetch_file(url, client=transport)
                self.assertEqual(list(pool.map(fetch, self.urls)), [self.raw, self.raw])
                self.assertEqual(len(factory.connections), 2)
            self.assertTrue(all(connection.closed for connection in factory.connections))

    def test_real_http_response_connection_close_complete_body(self):
        receiving, sending = socket.socketpair()
        sending.sendall(b'HTTP/1.1 200 OK\r\nContent-Type: image/png\r\nConnection: close\r\nContent-Length: '
                        + str(len(self.raw)).encode() + b'\r\n\r\n' + self.raw)
        sending.close()
        response = http.client.HTTPResponse(receiving, method='GET')
        response.begin()
        self.assertTrue(response.will_close)
        receiving.close()  # The HTTPResponse's file owns the remaining fd reference.
        connection = Mock()
        connection.sock = receiving
        connection.getresponse.return_value = response
        with patch('safe_images.validate_url', return_value=(urlsplit(self.urls[0]), '8.8.8.8')), \
             patch('safe_images.PinnedHTTPS', return_value=connection):
            self.assertEqual(safe_images.fetch_file(self.urls[0]), self.raw)
        self.assertTrue(response.isclosed())
        self.assertEqual(receiving.fileno(), -1)
        connection.close.assert_called_once()

    def test_real_http_response_truncated_content_length_is_error(self):
        receiving, sending = socket.socketpair()
        sending.sendall(b'HTTP/1.1 200 OK\r\nContent-Type: image/png\r\nConnection: close\r\nContent-Length: '
                        + str(len(self.raw) + 10).encode() + b'\r\n\r\n' + self.raw)
        sending.close()
        response = http.client.HTTPResponse(receiving, method='GET')
        response.begin()
        receiving.close()
        connection = Mock()
        connection.sock = receiving
        connection.getresponse.return_value = response
        with patch('safe_images.validate_url', return_value=(urlsplit(self.urls[0]), '8.8.8.8')), \
             patch('safe_images.PinnedHTTPS', return_value=connection):
            with self.assertRaises(http.client.IncompleteRead): safe_images.fetch_file(self.urls[0])
        connection.close.assert_called_once()


if __name__ == '__main__':
    unittest.main()
