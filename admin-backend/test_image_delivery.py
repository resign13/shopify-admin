import io
import os
from pathlib import Path
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock, patch

from botocore.exceptions import ClientError
from flask import Flask
from PIL import Image
import image_delivery as delivery


class ImageDeliveryTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.uploads = self.root / 'uploads'
        self.uploads.mkdir()
        self.cache = self.root / 'cache'
        self.app = Flask(__name__)
        self.app.add_url_rule('/uploads/<path:filename>', view_func=lambda filename:
            delivery.deliver_image(self.uploads, self.cache, filename, self.app.logger))
        data = io.BytesIO()
        Image.new('RGB', (1800, 2400), 'orange').save(data, 'JPEG', quality=95)
        self.original = data.getvalue()
        self.client = Mock()
        self.client.get_object.side_effect = lambda **kw: {'Body': io.BytesIO(self.original), 'ContentLength': len(self.original)}
        self.env = patch.dict(os.environ, {'R2_BUCKET': 'fixture'})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.mock = patch.object(delivery, 'r2_client', return_value=self.client)
        self.mock.start()
        self.addCleanup(self.mock.stop)

    def get(self, url, **kwargs):
        with self.app.test_client() as client:
            response = client.get(url, **kwargs)
            result = (response.status_code, response.get_data(), response.headers.copy())
            response.close()
            return result

    def test_thumbnail_original_and_conditional_cache(self):
        status, body, headers = self.get('/uploads/example.jpg?w=160')
        self.assertEqual(status, 200)
        self.assertEqual(headers['Content-Type'], 'image/webp')
        image = Image.open(io.BytesIO(body))
        self.assertEqual(image.size, (160, 213))
        self.assertLess(len(body), len(self.original) // 4)
        self.assertIn('public', headers['Cache-Control'])
        self.assertEqual(self.get('/uploads/example.jpg?w=160', headers={'If-None-Match': headers['ETag']})[0], 304)
        self.assertEqual(self.get('/uploads/example.jpg')[1], self.original)
        self.assertEqual(self.client.get_object.call_count, 1)

    def test_concurrent_misses_download_once(self):
        with ThreadPoolExecutor(max_workers=6) as pool:
            results = list(pool.map(lambda _: self.get('/uploads/nested/image.jpg?w=320'), range(6)))
        self.assertTrue(all(result[0] == 200 for result in results))
        self.assertEqual(self.client.get_object.call_count, 1)
        self.assertEqual(len({result[1] for result in results}), 1)

    def test_local_original_preserved_and_updated_variant(self):
        path = self.uploads / 'local.jpg'
        path.write_bytes(self.original)
        first = self.get('/uploads/local.jpg?w=160')[1]
        self.assertEqual(path.read_bytes(), self.original)
        Image.new('RGB', (500, 500), 'blue').save(path)
        second = self.get('/uploads/local.jpg?w=160')[1]
        self.assertNotEqual(first, second)
        self.client.get_object.assert_not_called()

    def test_invalid_width_and_traversal(self):
        for url in ['/uploads/test.jpg?w=99999', '/uploads/test.jpg?w=abc']:
            self.assertEqual(self.get(url)[0], 400)
        self.assertEqual(self.get('/uploads/../secret.jpg')[0], 404)
        self.assertEqual(self.get('/uploads/a%5Cb.jpg')[0], 404)
        self.client.get_object.assert_not_called()

    def test_missing_and_unavailable_are_not_cached(self):
        self.client.get_object.side_effect = ClientError({'Error': {'Code': 'NoSuchKey'}}, 'GetObject')
        response = self.get('/uploads/missing.jpg?w=160')
        self.assertEqual(response[0], 404)
        self.assertEqual(response[2]['Cache-Control'], 'no-store')
        self.client.get_object.side_effect = RuntimeError('offline fixture')
        self.assertEqual(self.get('/uploads/unavailable.jpg')[0], 503)
        self.assertFalse(list(self.cache.glob('*.source')))

    def test_oversized_download_rejected_and_body_closed(self):
        body = io.BytesIO(b'large')
        self.client.get_object.side_effect = None
        self.client.get_object.return_value = {'Body': body, 'ContentLength': delivery.MAX_SOURCE_BYTES + 1}
        self.assertEqual(self.get('/uploads/large.jpg?w=160')[0], 413)
        self.assertTrue(body.closed)
        self.assertFalse(list(self.cache.glob('*.source')))

    def test_pdf_and_animation_keep_original(self):
        (self.uploads / 'document.pdf').write_bytes(b'%PDF-fixture')
        self.assertEqual(self.get('/uploads/document.pdf?w=160')[1], b'%PDF-fixture')
        path = self.uploads / 'animated.gif'
        Image.new('RGB', (10, 10), 'red').save(path, save_all=True, append_images=[Image.new('RGB', (10, 10), 'blue')], duration=100, loop=0)
        self.assertEqual(self.get('/uploads/animated.gif?w=160')[1], path.read_bytes())

    def test_budget_cleanup(self):
        self.cache.mkdir()
        old = self.cache / 'old.source'
        old.write_bytes(b'x' * 100)
        os.utime(old, (1, 1))
        with patch.object(delivery, 'CACHE_BUDGET', 10):
            delivery.prune_cache(self.cache, set())
        self.assertFalse(old.exists())


if __name__ == '__main__':
    unittest.main()
