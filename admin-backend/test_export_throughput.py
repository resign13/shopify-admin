"""In-memory export performance regressions; no database or network access."""
import os
import threading
import unittest
from io import BytesIO
from unittest.mock import patch

os.environ['APP_ENV'] = 'test'
import db
with patch.object(db, 'ensure_database_ready'):
    import app as application
import export_resources
import safe_images
from PIL import Image, ImageOps
from openpyxl import load_workbook


def image_bytes():
    output = BytesIO()
    Image.new('RGB', (800, 400), 'red').save(output, format='PNG')
    return output.getvalue()


class ExportThroughputTest(unittest.TestCase):
    def test_prefetch_refills_free_worker_and_keeps_all_140_images(self):
        urls = [f'https://fixture.test/{i:03}.png' for i in range(140)]
        slow_started, third_started = threading.Event(), threading.Event()
        lock = threading.Lock()
        active = peak = 0
        timed_out = []

        def read(url, source):
            nonlocal active, peak
            with lock:
                active += 1
                peak = max(peak, active)
            try:
                if url == urls[0]:
                    slow_started.set()
                    if not third_started.wait(5):
                        timed_out.append(True)
                elif url == urls[1]:
                    self.assertTrue(slow_started.wait(5))
                elif url == urls[2]:
                    third_started.set()
                return url.encode()
            finally:
                with lock:
                    active -= 1

        with application.app.test_request_context('/'):
            with patch.dict(os.environ, {'ORDER_EXPORT_IMAGE_WORKERS': '2'}), \
                 patch.object(application, '_export_image_source', return_value=None), \
                 patch.object(application, '_read_export_image', side_effect=read):
                application.prefetch_export_images([{'items': [{'image': url} for url in urls]}])
            cache = export_resources.cache()
            self.assertEqual(len(cache.entries), 140)
            self.assertTrue(all(cache[(url, False)] == url.encode() for url in urls))
            paths = list(cache.entries.values())
        self.assertTrue(third_started.is_set())
        self.assertFalse(timed_out)
        self.assertEqual(peak, 2)
        self.assertTrue(all(not path.exists() for path in paths))

    def test_four_workers_are_bounded_and_keep_all_140_images(self):
        urls = [f'https://fixture.test/{i:03}.png' for i in range(140)]
        barrier, lock = threading.Barrier(4), threading.Lock()
        active = peak = 0
        def read(url, source):
            nonlocal active, peak
            with lock:
                active += 1
                peak = max(peak, active)
            try:
                if url in urls[:4]:
                    barrier.wait(5)
                return url.encode()
            finally:
                with lock:
                    active -= 1
        with application.app.test_request_context('/'):
            with patch.dict(os.environ, {'ORDER_EXPORT_IMAGE_WORKERS': '4'}), \
                 patch.object(application, '_export_image_source', return_value=None), \
                 patch.object(application, '_read_export_image', side_effect=read):
                application.prefetch_export_images([{'items': [{'image': url} for url in urls]}])
            cache = export_resources.cache()
            self.assertTrue(all(cache[(url, False)] == url.encode() for url in urls))
        self.assertEqual(peak, 4)

    def test_conversion_cache_uses_source_and_pixels_not_display_size(self):
        data = image_bytes()
        with application.app.test_request_context('/'):
            with patch.object(ImageOps, 'exif_transpose', wraps=ImageOps.exif_transpose) as convert:
                first = application.build_excel_image(data, width=100, height=100, source_key=('url', False))
                second = application.build_excel_image(data, width=200, height=200, source_key=('url', False))
                large = application.build_excel_image(data, pixels=1600, source_key=('url', False))
                attachment = application.build_excel_image(data, source_key=('url', True))
                self.assertEqual(convert.call_count, 3)
            self.assertIsNot(first, second)
            self.assertEqual((first.width, first.height), (100, 50))
            self.assertEqual((second.width, second.height), (200, 100))
            self.assertEqual((large.width, large.height), (54, 27))
            self.assertIsNotNone(attachment)
            converted = export_resources.cache().converted
            self.assertEqual(len(converted), 3)
            with Image.open(converted[(('url', False), 640)][0]) as photo:
                self.assertEqual(photo.size, (640, 320))
            with Image.open(converted[(('url', False), 1600)][0]) as photo:
                self.assertEqual(photo.size, (800, 400))

    def test_matrix_reuses_conversion_across_orders(self):
        data = image_bytes()
        orders = [{'orderNo': str(i), 'items': [{'sku': 'sku', 'image': 'url', 'sizeCode': 'S', 'quantity': 1}]} for i in range(3)]
        with application.app.test_request_context('/'):
            with patch.object(application, 'prefetch_export_images'), \
                 patch.object(application, 'fetch_image_bytes', return_value=data), \
                 patch.object(ImageOps, 'exif_transpose', wraps=ImageOps.exif_transpose) as convert:
                output = application.build_orders_export(orders)
                self.assertEqual(convert.call_count, 1)
            sheet = load_workbook(output).active
            self.assertEqual(len(sheet._images), 3)

    def test_default_tls_context_is_reused_with_verification(self):
        first = safe_images.PinnedHTTPS('fixture.test', '8.8.8.8', 5)
        second = safe_images.PinnedHTTPS('fixture.test', '8.8.8.8', 5)
        self.assertIs(first._context, second._context)
        self.assertTrue(first._context.check_hostname)
        self.assertEqual(first._context.verify_mode, safe_images.ssl.CERT_REQUIRED)


if __name__ == '__main__':
    unittest.main()
