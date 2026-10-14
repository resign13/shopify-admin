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
import warnings
from urllib.parse import urlsplit, urljoin, unquote
from PIL import Image

MAX_BYTES = 32 * 1024 * 1024
MAX_PIXELS = 40_000_000


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
        super().__init__(host, port=443, timeout=timeout, context=ssl.create_default_context())
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


def fetch_file(url, image_only=True, *, timeout_seconds=25, request_timeout_seconds=8, proxy_url=None):
    if not 1 <= timeout_seconds <= 90 or not 1 <= request_timeout_seconds <= min(timeout_seconds, 30):
        raise ValueError('Invalid image retrieval timeout')
    deadline = time.monotonic() + timeout_seconds
    for hop in range(4):
        parts, address = validate_url(url)
        options = {'proxy_url': proxy_url} if proxy_url else {}
        connection = PinnedHTTPS(parts.hostname, address, min(request_timeout_seconds, max(0.1, deadline - time.monotonic())), **options)
        try:
            path = parts.path or '/'
            if parts.query: path += '?' + parts.query
            connection.request('GET', path, headers={'Accept': 'image/*', 'Accept-Encoding': 'identity', 'User-Agent': 'GINGTTO-Image-Export/1.0'})
            response = connection.getresponse()
            if response.status in {301, 302, 303, 307, 308}:
                if hop == 3: raise ValueError('Too many image redirects')
                url = urljoin(url, response.getheader('Location', ''))
                continue
            if response.status != 200 or (image_only and not response.getheader('Content-Type', '').lower().startswith('image/')):
                raise ValueError('Image retrieval failed')
            if int(response.getheader('Content-Length', '0')) > MAX_BYTES or response.getheader('Content-Encoding', 'identity') != 'identity':
                raise ValueError('Image is too large')
            chunks, size = [], 0
            while True:
                if time.monotonic() > deadline: raise TimeoutError('Image retrieval timed out')
                chunk = response.read(min(65536, MAX_BYTES + 1 - size))
                if not chunk: break
                size += len(chunk)
                if size > MAX_BYTES: raise ValueError('Image is too large')
                chunks.append(chunk)
            data = b''.join(chunks)
            if image_only: check_image(data)
            return data
        finally:
            connection.close()
    raise ValueError('Image retrieval failed')


def fetch_image(url):
    return fetch_file(url,image_only=True)
