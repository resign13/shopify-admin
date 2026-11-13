"""Shared image caching regressions: local files only, no database/network."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from io import BytesIO
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from PIL import Image, ImageOps
import export_image_cache as shared


def picture(color='red'):
    output = BytesIO()
    Image.new('RGB', (800, 400), color).save(output, 'PNG')
    return output.getvalue()


class SharedImageCacheTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.cache = shared.SharedImageCache(Path(self.folder.name) / 'cache')

    def test_cold_hot_and_versions_use_natural_keys(self):
        builder = unittest.mock.Mock(return_value=b'image')
        first = self.cache.get(['url', 'https://fixture/a?v=1'], builder)
        second = self.cache.get(['url', 'https://fixture/a?v=1'], builder)
        changed = self.cache.get(['url', 'https://fixture/a?v=2'], builder)
        self.assertEqual(builder.call_count, 2)
        self.assertEqual(first, second)
        self.assertNotEqual(first.token, changed.token)
        self.assertNotIn('fixture', ' '.join(path.name for path in self.cache.directory.iterdir()))

    def test_threads_join_one_inflight_read(self):
        barrier = threading.Barrier(2)
        reads = []
        def read():
            reads.append(True)
            time.sleep(0.15)
            return b'image'
        def request(_):
            barrier.wait(3)
            return self.cache.get(['source'], read)
        with ThreadPoolExecutor(2) as pool:
            values = list(pool.map(request, range(2)))
        self.assertEqual(values[0], values[1])
        self.assertEqual(len(reads), 1)

    def test_processes_join_one_inflight_read(self):
        marker = Path(self.folder.name) / 'reads'
        code = '''import sys,time
from pathlib import Path
from export_image_cache import SharedImageCache
cache=SharedImageCache(sys.argv[1])
def read():
    with Path(sys.argv[2]).open('ab') as f: f.write(b'1')
    time.sleep(0.3)
    return b'image'
entry=cache.get(['same-source'],read)
print(entry.token)
'''
        args = [sys.executable, '-c', code, str(self.cache.directory), str(marker)]
        children = [subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE) for _ in range(2)]
        results = [child.communicate(timeout=10) for child in children]
        self.assertEqual([child.returncode for child in children], [0, 0], results)
        self.assertEqual(results[0][0], results[1][0])
        self.assertEqual(marker.read_bytes(), b'1')

    def test_failure_is_not_cached_and_connection_is_closed_before_build(self):
        def read():
            with closing(sqlite3.connect(self.cache.database, timeout=0.1)) as db:
                with db:
                    db.execute('BEGIN IMMEDIATE')
                    db.execute('UPDATE images SET accessed=accessed')
            raise OSError('private-url')
        with self.assertRaises(OSError):
            self.cache.get(['broken'], read)
        entry = self.cache.get(['broken'], lambda: b'recovered')
        self.assertEqual(entry.data, b'recovered')
        self.assertFalse(list(self.cache.directory.glob('*.tmp')))

    def test_ttl_and_capacity_prune_files(self):
        cache = shared.SharedImageCache(self.cache.directory, max_bytes=10, ttl_seconds=5)
        with patch.object(shared.time, 'time', return_value=100):
            first = cache.get(['one'], lambda: b'123456')
        with patch.object(shared.time, 'time', return_value=101):
            cache.get(['two'], lambda: b'abcdef')
        self.assertFalse(cache._path(first.token).exists())
        self.assertLessEqual(sum(path.stat().st_size for path in cache.directory.glob('*.image')), 10)
        with patch.object(shared.time, 'time', return_value=107):
            cache.prune()
        self.assertFalse(list(cache.directory.glob('*.image')))

    def test_unversioned_source_short_ttl_rereads_replaced_content(self):
        values = iter([b'old', b'replaced'])
        def read():
            return next(values)
        self.assertEqual(shared.source_ttl(None), 300)
        self.assertEqual(shared.source_ttl({'legacy_channel': 'admin', 'legacy_key': 'mutable.jpg'}), 300)
        self.assertIsNone(shared.source_ttl({'legacy_path': 'local', 'legacy_channel': 'admin'}))
        with patch.object(shared.time, 'time', return_value=100):
            first = self.cache.get(['mutable-url'], read, ttl_seconds=shared.source_ttl(None))
        with patch.object(shared.time, 'time', return_value=399):
            warm = self.cache.get(['mutable-url'], read, ttl_seconds=shared.source_ttl(None))
        with patch.object(shared.time, 'time', return_value=401):
            refreshed = self.cache.get(['mutable-url'], read, ttl_seconds=shared.source_ttl(None))
        self.assertEqual(warm, first)
        self.assertEqual(refreshed.data, b'replaced')
        self.assertNotEqual(first.token, refreshed.token)

    def test_missing_file_recovers_with_new_generation(self):
        first = self.cache.get(['source'], lambda: b'one')
        self.cache._path(first.token).unlink()
        second = self.cache.get(['source'], lambda: b'two')
        self.assertEqual(second.data, b'two')
        self.assertNotEqual(first.token, second.token)

    def test_cache_namespace_does_not_follow_worker_temp_and_isolates_database(self):
        with patch.dict(os.environ, {'APP_ENV': 'test', 'PGDATABASE': 'one_test',
                                   'ORDER_EXPORT_IMAGE_CACHE_DIR': self.folder.name, 'TMPDIR': 'unrelated'}):
            first = shared.cache_directory()
            with patch.dict(os.environ, {'PGDATABASE': 'two_test'}):
                second = shared.cache_directory()
        self.assertNotEqual(first, second)
        self.assertEqual(first, Path(self.folder.name) / 'db-one_test')
        with patch.dict(os.environ, {'APP_ENV': 'test', 'PGDATABASE': 'lumiere_admin'}):
            with self.assertRaises(ValueError):
                shared.cache_directory()

    def test_local_identity_changes_on_source_update(self):
        path = Path(self.folder.name) / 'source.png'
        path.write_bytes(picture())
        source = {'legacy_path': str(path), 'legacy_channel': 'admin'}
        first = shared.source_identity('url', source)
        path.write_bytes(picture('blue') + b'changed')
        self.assertNotEqual(first, shared.source_identity('url', source))


class SourceVariantTest(unittest.TestCase):
    def test_only_plain_versioned_public_upload_urls_are_resized(self):
        url = 'https://res.cloudinary.com/fixture-cloud/image/upload/v123/folder/photo_id.png'
        with shared.image_variant(640):
            self.assertEqual(shared.export_source_url(url), url.replace('/upload/', '/upload/c_limit,w_640,h_640/'))
            with shared.image_variant(1600):
                self.assertIn('/c_limit,w_1600,h_1600/', shared.export_source_url(url))
            self.assertIn('/c_limit,w_640,h_640/', shared.export_source_url(url))
        self.assertEqual(shared.export_source_url(url), url)
        unchanged = [
            url + '?token=private', url + '#fragment',
            url.replace('/upload/v', '/upload/s--SIGNATURE--/v'),
            url.replace('/upload/v', '/upload/c_limit,w_800/v'),
            url.replace('/upload/', '/private/'), url.replace('/upload/', '/authenticated/'),
            url.replace('https://', 'http://'), url.replace('res.cloudinary.com', 'res.cloudinary.com.evil.test'),
            url.replace('res.cloudinary.com', 'user@res.cloudinary.com'),
            url.replace('res.cloudinary.com', 'res.cloudinary.com:443'),
            url.replace('/v123/', '/'), url.replace('/folder/', '/../'),
            url.replace('.png', '.avif'),
        ]
        with shared.image_variant(640):
            for value in unchanged:
                with self.subTest(value=value):
                    self.assertEqual(shared.export_source_url(value), value)

    def test_variants_are_thread_local(self):
        url = 'https://res.cloudinary.com/fixture/image/upload/v1/photo.jpg'
        barrier = threading.Barrier(2)
        def read(pixels):
            with shared.image_variant(pixels):
                barrier.wait(3)
                return shared.export_source_url(url)
        with ThreadPoolExecutor(2) as pool:
            first, second = list(pool.map(read, (640, 1600)))
        self.assertIn('/c_limit,w_640,h_640/', first)
        self.assertIn('/c_limit,w_1600,h_1600/', second)
        self.assertEqual(shared.export_source_url(url), url)


class ApplicationImageCacheTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ['APP_ENV'] = 'test'
        import db
        with patch.object(db, 'ensure_database_ready'):
            import app
        cls.application = app

    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.env = patch.dict(os.environ, {'APP_ENV': 'test', 'PGDATABASE': 'image_cache_unit_test',
                                          'ORDER_EXPORT_IMAGE_CACHE_DIR': self.folder.name})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.raw = picture()

    def test_two_requests_share_raw_and_original_quality_conversion(self):
        app = self.application
        import export_resources
        def render():
            with app.app.test_request_context('/'):
                raw = app.fetch_image_bytes('https://fixture/image.png')
                image = app.build_excel_image(raw, source_key=('https://fixture/image.png', False))
                converted = export_resources.cache().converted[(('https://fixture/image.png', False), 640)][0].read_bytes()
                return image.width, image.height, converted
        with patch.object(app, '_export_image_source', return_value=None) as authorize, \
             patch('safe_images.validate_url') as validate, \
             patch('safe_images.fetch_image', return_value=self.raw) as download, \
             patch.object(ImageOps, 'exif_transpose', wraps=ImageOps.exif_transpose) as convert:
            first, second = render(), render()
        self.assertEqual(authorize.call_count, 2)
        self.assertEqual(validate.call_count, 2)
        self.assertEqual(download.call_count, 1)
        self.assertEqual(convert.call_count, 1)
        self.assertEqual(first, second)
        with Image.open(BytesIO(first[2])) as image:
            self.assertEqual(image.size, (640, 320))

    def test_cloudinary_variants_follow_usage_and_preserve_png_alpha(self):
        app = self.application
        import export_resources
        url = 'https://res.cloudinary.com/fixture/image/upload/v123/photo.png'
        targets = [url.replace('/upload/', f'/upload/c_limit,w_{pixels},h_{pixels}/') for pixels in (640, 1600)]
        output = BytesIO()
        Image.new('RGBA', (64, 32), (10, 20, 30, 100)).save(output, 'PNG')
        raw = output.getvalue()
        order = {'items': [{'image': url}], 'labelImageUrls': [url]}
        with patch.object(app, '_export_image_source', return_value=None), \
             patch('safe_images.validate_url') as validate, \
             patch('safe_images.fetch_image', return_value=raw) as download:
            with app.app.test_request_context('/'):
                app.prefetch_export_images([order])
                cache = export_resources.cache()
                self.assertNotEqual(cache.source_tokens[(url, False)], cache.source_tokens[(url, True)])
                for attachment, pixels in ((False, 640), (True, 1600)):
                    data = app.fetch_image_bytes(url, attachment=attachment)
                    app.build_excel_image(data, pixels=pixels, source_key=(url, attachment))
                    path = cache.converted[((url, attachment), pixels)][0]
                    with Image.open(path) as image:
                        self.assertEqual(image.format, 'PNG')
                        self.assertEqual(image.size, (64, 32))
                        self.assertEqual(image.convert('RGBA').getpixel((0, 0)), (10, 20, 30, 100))
            self.assertCountEqual([call.args[0] for call in download.call_args_list], targets)
            checked = [call.args[0] for call in validate.call_args_list]
            self.assertEqual(checked.count(url), 2)
            for target in targets:
                self.assertIn(target, checked)
            download.reset_mock()
            with app.app.test_request_context('/'):
                app.fetch_image_bytes(url)
                app.fetch_image_bytes(url, attachment=True)
            download.assert_not_called()
        self.assertEqual(order['items'][0]['image'], url)
        self.assertEqual(order['labelImageUrls'], [url])

    def test_cloudinary_original_must_pass_current_validation_before_derivation(self):
        app = self.application
        url = 'https://res.cloudinary.com/fixture/image/upload/v123/photo.png'
        with app.app.test_request_context('/'), \
             patch.object(app, '_export_image_source', return_value=None) as authorize, \
             patch('safe_images.validate_url', side_effect=ValueError('denied original')) as validate, \
             patch('safe_images.fetch_image') as download:
            with self.assertRaises(shared.ExportImageError):
                app.fetch_image_bytes(url)
            authorize.assert_called_once_with(url, False)
            validate.assert_called_once_with(url)
            download.assert_not_called()

    def test_registered_storage_source_is_not_derived(self):
        app = self.application
        url = 'https://res.cloudinary.com/fixture/image/upload/v123/photo.png'
        source = {'storage_channel': 'admin', 'storage_key': 'fixture.png', 'byte_size': len(self.raw), 'sha256': 'existing'}
        with app.app.test_request_context('/'), patch.object(app, '_export_image_source', return_value=source), \
             patch.object(app.media, 'read', return_value=self.raw) as read, \
             patch('safe_images.validate_url') as validate, patch('safe_images.fetch_image') as download:
            self.assertEqual(app.fetch_image_bytes(url), self.raw)
            read.assert_called_once_with(source)
            validate.assert_not_called()
            download.assert_not_called()

    def test_warm_image_still_requires_authorization_and_current_origin(self):
        app = self.application
        with app.app.test_request_context('/'), patch.object(app, '_export_image_source', return_value=None), \
             patch('safe_images.validate_url'), patch('safe_images.fetch_image', return_value=self.raw):
            app.fetch_image_bytes('https://fixture/image.png')
        with app.app.test_request_context('/'), patch.object(app, '_export_image_source', side_effect=PermissionError('private-url')):
            with self.assertRaises(shared.ExportImageError) as error:
                app.fetch_image_bytes('https://fixture/image.png')
            self.assertNotIn('private-url', str(error.exception))
        with app.app.test_request_context('/'), patch.object(app, '_export_image_source', return_value=None), \
             patch('safe_images.validate_url', side_effect=ValueError('private-url')):
            with self.assertRaises(shared.ExportImageError):
                app.fetch_image_bytes('https://fixture/image.png')

    def test_early_failure_does_not_skip_later_images_or_build_partial_workbook(self):
        app = self.application
        import export_resources
        from flask import g
        urls = [f'https://fixture/{index}.png' for index in range(3)]
        order = {'items': [{'image': url} for url in urls]}
        reads, progress = [], []
        def download(url):
            reads.append(url)
            if url == urls[0]:
                raise TimeoutError('private-url')
            return self.raw
        with patch.dict(os.environ, {'ORDER_EXPORT_IMAGE_WORKERS': '1'}), \
             patch.object(app, '_export_image_source', return_value=None), \
             patch('safe_images.validate_url'), \
             patch('safe_images.fetch_image', side_effect=download), \
             patch('order_matrix_export.build') as build:
            with app.app.test_request_context('/'):
                g.export_progress = lambda *value: progress.append(value)
                with self.assertRaises(shared.ExportImageError):
                    app.build_orders_export([order])
                cache = export_resources.cache()
                self.assertIsNone(cache[(urls[0], False)])
                self.assertEqual(cache[(urls[1], False)], self.raw)
                self.assertEqual(cache[(urls[2], False)], self.raw)
                self.assertEqual(progress[-1], ('images', 3, 3))
            build.assert_not_called()
            self.assertEqual(reads, urls)
        # Successful images survived the failed request in the shared cache.
        # The failure did not: it must attempt a fresh read on recovery.
        with app.app.test_request_context('/'), \
             patch.object(app, '_export_image_source', return_value=None), \
             patch('safe_images.validate_url'), \
             patch('safe_images.fetch_image', return_value=self.raw) as retry:
            self.assertEqual(app.fetch_image_bytes(urls[1]), self.raw)
            self.assertEqual(app.fetch_image_bytes(urls[2]), self.raw)
            retry.assert_not_called()
            self.assertEqual(app.fetch_image_bytes(urls[0]), self.raw)
            retry.assert_called_once_with(urls[0])

    def test_read_and_conversion_failures_are_explicit(self):
        app = self.application
        order = {'items': [{'image': 'https://fixture/broken.png'}]}
        with app.app.test_request_context('/'), patch.object(app, '_export_image_source', return_value=None), \
             patch.object(app, '_read_export_image', side_effect=OSError('private-url')):
            with self.assertRaises(shared.ExportImageError):
                app.prefetch_export_images([order])
        with app.app.test_request_context('/'):
            with self.assertRaises(shared.ExportImageError):
                app.build_excel_image(b'invalid')


if __name__ == '__main__':
    unittest.main()
