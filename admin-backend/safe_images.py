"""Bounded HTTPS image retrieval: exact origins, public DNS, pinned connection.

Never use this for private business attachments; those are read by storage ID.
Every redirect is independently checked. Environment proxy settings are ignored.
"""
import http.client
import base64
import ipaddress
import io
import os
import socket
import ssl
import time
import threading
import warnings
from contextlib import contextmanager
from urllib.parse import urlsplit, urljoin, unquote
from PIL import Image

MAX_BYTES = 32 * 1024 * 1024
MAX_PIXELS = 40_000_000
_TLS_CONTEXT = ssl.create_default_context()
_ACTIVE_TRANSPORT = threading.local()


def allowed_origins():
    return {value.strip().rstrip('/') for value in os.environ.get('PUBLIC_IMAGE_ORIGINS', '').split(',') if value.strip()}


def validate_url(url):
    p = urlsplit(url)
    if p.scheme != 'https' or not p.hostname or p.username or p.password or p.port not in {None, 443}:
        raise ValueError('Image origin is not allowed')
    origin = 'https://' + p.hostname.lower()
    if origin not in allowed_origins() or p.fragment or len(url) > 2048:
        raise ValueError('Image origin is not allowed')
    addresses = socket.getaddrinfo(p.hostname, 443, type=socket.SOCK_STREAM)
    if not addresses or any(not public_address(item[4][0]) for item in addresses):
        raise ValueError('Image destination is not public')
    # Prefer a usable IPv4 route on hosts with partial IPv6 connectivity. All
    # returned DNS addresses were checked above; the selected one is still
    # pinned for the HTTPS connection and never re-resolved by the client.
    addresses.sort(key=lambda item: item[0] != socket.AF_INET)
    return p, addresses[0][4][0]


def public_address(value):
    try:
        address = ipaddress.ip_address(value.split('%')[0])
        if '%' in value: return False
        if address.version == 6 and address.ipv4_mapped: address = address.ipv4_mapped
        return address.is_global and not address.is_multicast
    except ValueError:
        return False


class PinnedHTTPS(http.client.HTTPSConnection):
    def __init__(self, host, address, timeout, *, proxy_url=None):
        super().__init__(host, port=443, timeout=timeout, context=_TLS_CONTEXT)
        self.address = address
        self.proxy_url = proxy_url

    def connect(self):
        if self.proxy_url:
            # Explicit operator-controlled migration transport, never inferred
            # from ambient proxy variables or accepted from a browser request.
            proxy = urlsplit(self.proxy_url)
            if proxy.scheme != 'http' or not proxy.hostname or proxy.path not in {'', '/'} or proxy.query or proxy.fragment:
                raise ValueError('Invalid configured migration proxy')
            headers = {}
            if proxy.username is not None:
                credentials = unquote(proxy.username) + ':' + unquote(proxy.password or '')
                headers['Proxy-Authorization'] = 'Basic ' + base64.b64encode(credentials.encode()).decode()
            tunnel = http.client.HTTPConnection(proxy.hostname, proxy.port or 80, timeout=self.timeout)
            # The proxy connects to the already validated public IP, not a
            # second DNS resolution of the destination hostname.
            tunnel.set_tunnel(self.address, 443, headers=headers)
            try:
                tunnel.connect()
                sock = tunnel.sock
                tunnel.sock = None
            finally:
                tunnel.close()
        else:
            sock = socket.create_connection((self.address, 443), self.timeout)
        try:
            self.sock = self._context.wrap_socket(sock, server_hostname=self.host)
        except BaseException:
            sock.close()
            raise


class ImageTransport:
    """Request-scoped, one idle pinned HTTPS connection per worker thread."""
    def __init__(self):
        self.local = threading.local()
        self.idle = set()
        self.lock = threading.Lock()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    @contextmanager
    def use(self):
        previous = getattr(_ACTIVE_TRANSPORT, 'value', None)
        _ACTIVE_TRANSPORT.value = self
        try:
            yield
        finally:
            _ACTIVE_TRANSPORT.value = previous

    def acquire(self, host, address, timeout, proxy_url):
        key = (host, address, proxy_url)
        cached = getattr(self.local, 'connection', None)
        if cached is not None:
            old_key, connection = cached
            self.local.connection = None
            with self.lock:
                self.idle.discard(connection)
            if old_key == key and connection.sock is not None:
                connection.timeout = timeout
                try:
                    connection.sock.settimeout(timeout)
                    return connection, True
                except OSError:
                    pass
            connection.close()
        options = {'proxy_url': proxy_url} if proxy_url else {}
        return PinnedHTTPS(host, address, timeout, **options), False

    def release(self, host, address, proxy_url, connection):
        self.local.connection = ((host, address, proxy_url), connection)
        with self.lock:
            self.idle.add(connection)

    def discard(self):
        cached = getattr(self.local, 'connection', None)
        if cached is not None:
            self.local.connection = None
            connection = cached[1]
            with self.lock:
                self.idle.discard(connection)
            connection.close()

    def close(self):
        with self.lock:
            connections, self.idle = self.idle, set()
        for connection in connections:
            connection.close()


def check_image(data, suffix=None):
    if not data or len(data) > MAX_BYTES: raise ValueError('Invalid image size')
    with warnings.catch_warnings():
        warnings.simplefilter('error', Image.DecompressionBombWarning)
        with Image.open(io.BytesIO(data)) as image:
            if image.width * image.height > MAX_PIXELS or getattr(image, 'n_frames', 1) > 100:
                raise ValueError('Image dimensions are too large')
            formats = {'.jpg': 'JPEG', '.jpeg': 'JPEG', '.png': 'PNG', '.webp': 'WEBP', '.avif': 'AVIF', '.gif': 'GIF', '.bmp': 'BMP'}
            # Camera MPO files are a bounded multi-picture JPEG container.
            # Keep the original bytes, but validate/serve them as JPEG.
            detected = 'JPEG' if image.format == 'MPO' else image.format
            if detected not in set(formats.values()) or (suffix and formats.get(suffix) != detected):
                raise ValueError('Image content does not match its extension')
            image.verify()
            return Image.MIME.get(detected, 'application/octet-stream')


def fetch_file(url, image_only=True, *, timeout_seconds=25, request_timeout_seconds=8, proxy_url=None, client=None):
    if not 1 <= timeout_seconds <= 90 or not 1 <= request_timeout_seconds <= min(timeout_seconds, 30):
        raise ValueError('Invalid image retrieval timeout')
    deadline = time.monotonic() + timeout_seconds
    client = client if client is not None else getattr(_ACTIVE_TRANSPORT, 'value', None)
    retry_used = False
    for hop in range(4):
        for attempt in range(2):
            try:
                parts, address = validate_url(url)
            except Exception:
                if client is not None:
                    client.discard()
                raise
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                if client is not None:
                    client.discard()
                raise TimeoutError('Image retrieval timed out')
            timeout = min(request_timeout_seconds, remaining)
            if client is None:
                options = {'proxy_url': proxy_url} if proxy_url else {}
                connection, reused = PinnedHTTPS(parts.hostname, address, timeout, **options), False
            else:
                connection, reused = client.acquire(parts.hostname, address, timeout, proxy_url)
            retained = False
            try:
                path = parts.path or '/'
                if parts.query: path += '?' + parts.query
                try:
                    connection.request('GET', path, headers={'Accept': 'image/*', 'Accept-Encoding': 'identity', 'User-Agent': 'GINGTTO-Image-Export/1.0'})
                    response = connection.getresponse()
                    if response.status in {301, 302, 303, 307, 308}:
                        if hop == 3: raise ValueError('Too many image redirects')
                        url = urljoin(url, response.getheader('Location', ''))
                        break
                    if response.status != 200 or (image_only and not response.getheader('Content-Type', '').lower().startswith('image/')):
                        raise ValueError('Image retrieval failed')
                    if int(response.getheader('Content-Length', '0')) > MAX_BYTES or response.getheader('Content-Encoding', 'identity') != 'identity':
                        raise ValueError('Image is too large')
                    chunks, size = [], 0
                    while True:
                        length = getattr(response, 'length', None)
                        if getattr(response, 'isclosed', lambda: False)() is True or length == 0:
                            if type(length) is int and length > 0:
                                raise http.client.IncompleteRead(b'', length)
                            break
                        remaining = deadline - time.monotonic()
                        if remaining <= 0: raise TimeoutError('Image retrieval timed out')
                        response_socket = connection.sock
                        if response_socket is None:
                            response_socket = getattr(getattr(getattr(response, 'fp', None), 'raw', None), '_sock', None)
                        if response_socket is not None:
                            response_socket.settimeout(min(request_timeout_seconds, remaining))
                        chunk = response.read(min(65536, MAX_BYTES + 1 - size))
                        if not chunk:
                            length = getattr(response, 'length', None)
                            if type(length) is int and length > 0:
                                raise http.client.IncompleteRead(b'', length)
                            break
                        size += len(chunk)
                        if size > MAX_BYTES: raise ValueError('Image is too large')
                        chunks.append(chunk)
                    data = b''.join(chunks)
                except (OSError, http.client.HTTPException) as error:
                    # One shared retry budget covers fresh GET idle timeouts
                    # and stale keep-alive sockets, including across redirects.
                    if ((reused or isinstance(error, TimeoutError)) and not retry_used
                            and not isinstance(error, (ssl.SSLError, PermissionError)) and time.monotonic() < deadline):
                        retry_used = True
                        continue
                    raise
                if image_only: check_image(data)
                if client is not None and not response.will_close and connection.sock is not None:
                    client.release(parts.hostname, address, proxy_url, connection)
                    retained = True
                return data
            finally:
                if not retained:
                    connection.close()
    raise ValueError('Image retrieval failed')


def fetch_image(url):
    return fetch_file(url,image_only=True)
